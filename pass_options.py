"""
Pass Options: rank every route runner, every 0.1 s from snap to throw.

Per-receiver metrics (computed each frame):
    separation    distance to the nearest defender (yds)
    attention     defender-equivalents on him: each coverage defender's focus is split
                  across receivers plus a "nobody" option, so no defender is counted twice
    lane          closest defender to the QB->receiver throwing line (yds)
    depth         yards past the line of scrimmage; reaches_sticks = depth >= yards to go
    safety_pull   yards the deep safeties have moved toward him since the snap

Completion model: logistic regression learned from real targeted throws
(features at the throw -> complete or not). Trained on Weeks 1-6, tested on Weeks 7-8.

Ranking modes:
    value (default)  expected yards = P(complete) x (depth + expected YAC + first-down bonus)
    safe  (backup)   P(complete) only - the safest throw

Usage:
    python pass_options.py --data path/to/data --out output
    python pass_options.py --data path/to/data --out output --reuse   # skip feature extraction

Outputs (in --out):
    throw_features.csv       one row per route runner at the throw, every play
    model.json               coefficients + held-out validation
    plays/play_<game>_<play>.json   per-frame export for the showcase plays (frontend reads these)
"""
import argparse
import glob
import json
import os

import numpy as np
import pandas as pd

from safety_pull import SAFETY_ALIGN, SNAP, THROW, load_meta, target_from_desc

EXPECTED_YAC = 3.0       # yards after catch assumed for every completion (simple, stated assumption)
FIRST_DOWN_BONUS = 5.0   # extra value for a catch that reaches the line to gain
SIGMA = 3.0              # attention kernel width (yds)
NOBODY_R = 7.0           # a defender further than ~7 yds from everyone is "nobody's"
FEATURES = ["sep", "lane", "attention", "depth", "depth2"]


# ---------------------------------------------------------------- geometry
def normalise(t):
    """Offense always attacks right (+x). Flip positions and angles for 'left' plays."""
    left = t["playDirection"] == "left"
    t.loc[left, "x"] = 120 - t.loc[left, "x"]
    t.loc[left, "y"] = 53.3 - t.loc[left, "y"]
    for c in ("dir", "o"):
        t.loc[left, c] = (t.loc[left, c] + 180) % 360
    r = np.deg2rad(t["dir"].fillna(0))
    t["vx"] = t["s"] * np.sin(r)  # verified: displacement matches vx=s*sin(dir), vy=s*cos(dir)
    t["vy"] = t["s"] * np.cos(r)
    return t


def seg_dist(p, a, b):
    """Distance from points p (n,2) to the middle of the throwing line a->b (25%-85%): skips rushers at the QB
    and the receiver's own defender at the catch point, which separation already covers."""
    ab = b - a
    L2 = max(float(ab @ ab), 1e-6)
    u = ((p - a) @ ab) / L2
    ok = (u >= 0.25) & (u <= 0.85)
    proj = a + np.clip(u, 0, 1)[:, None] * ab
    d = np.linalg.norm(p - proj, axis=1)
    return np.where(ok, d, np.inf)


def frame_metrics(R, Dcov, Dall, qb, los_x, togo):
    """R: receivers (nR,2); Dcov: coverage defenders (nC,2); Dall: all defenders; qb: (2,)."""
    sep = np.linalg.norm(R[:, None] - Dall[None], axis=-1).min(1) if len(Dall) else np.full(len(R), 10.0)
    if len(Dcov):
        D = np.linalg.norm(Dcov[:, None] - R[None], axis=-1)           # (nC, nR)
        q = np.exp(-(D ** 2) / (2 * SIGMA ** 2))
        q_none = np.exp(-(NOBODY_R ** 2) / (2 * SIGMA ** 2))
        w = q / (q_none + q.sum(1, keepdims=True))
        att = w.sum(0)
    else:
        att = np.zeros(len(R))
    lane = np.array([min(10.0, seg_dist(Dall, qb, r).min()) if len(Dall) else 10.0 for r in R])
    depth = R[:, 0] - los_x
    return dict(sep=np.minimum(sep, 10.0), attention=att, lane=lane, depth=depth,
                reaches_sticks=depth >= togo)


# ---------------------------------------------------------------- per-play extraction
def play_context(p, meta, roles):
    ev = p.drop_duplicates("frameId").set_index("frameId")["event"]
    snap = ev.index[ev.isin(SNAP)].min() if ev.isin(SNAP).any() else None
    throw = ev.index[ev.isin(THROW)].min() if ev.isin(THROW).any() else None
    if snap is None or throw is None or throw - snap < 5:
        return None
    ball = p[p["nflId"].isna()].set_index("frameId")
    if snap not in ball.index:
        return None
    los_x = float(ball.loc[snap, "x"])
    pl = p[p["nflId"].notna()]
    ids = lambda role: [i for i in roles.index[roles["pff_role"] == role] if i in set(pl["nflId"])]
    routes, cov, rush, qbs = ids("Pass Route"), ids("Coverage"), ids("Pass Rush"), ids("Pass")
    if not routes or not qbs:
        return None
    defense = list(pl.loc[pl["team"] == meta["defensiveTeam"], "nflId"].unique())
    deep = [s for s in cov if roles.loc[s, "pff_positionLinedUp"] in SAFETY_ALIGN]
    return dict(snap=int(snap), throw=int(throw), los_x=los_x, routes=routes, cov=cov, rush=rush,
                qb=qbs[0], defense=defense, deep=deep, togo=float(meta["yardsToGo"]))


def pos(P, ids, f):
    return P.loc[[(i, f) for i in ids], ["x", "y"]].to_numpy() if ids else np.empty((0, 2))


def extract_throw_rows(data, plays, pff, games, names):
    pff_g = pff.groupby(["gameId", "playId"])
    pidx = plays.set_index(["gameId", "playId"])
    week = games.set_index("gameId")["week"]
    rows = []
    files = sorted(glob.glob(os.path.join(data, "tracking", "tracking_*.csv")))
    for i, f in enumerate(files):
        gid = int(os.path.basename(f)[9:-4])
        t = normalise(pd.read_csv(f))
        for pid, p in t.groupby("playId"):
            if (gid, pid) not in pidx.index:
                continue
            meta = pidx.loc[(gid, pid)]
            try:
                roles = pff_g.get_group((gid, pid)).set_index("nflId")
            except KeyError:
                continue
            c = play_context(p, meta, roles)
            if c is None:
                continue
            P = p[p["nflId"].notna()].set_index(["nflId", "frameId"])
            f_ = c["throw"]
            try:
                R = pos(P, c["routes"], f_)
                m = frame_metrics(R, pos(P, c["cov"], f_), pos(P, c["defense"], f_),
                                  pos(P, [c["qb"]], f_)[0], c["los_x"], c["togo"])
            except KeyError:
                continue
            target = target_from_desc(meta["playDescription"], c["routes"], names)
            for k, r in enumerate(c["routes"]):
                rows.append(dict(gameId=gid, playId=pid, week=int(week[gid]), nflId=r,
                                 is_target=(r == target), has_target=target is not None,
                                 complete=int(meta["passResult"] == "C"), togo=c["togo"],
                                 **{key: float(v[k]) for key, v in m.items()}))
        print(f"[{i + 1}/{len(files)}] {gid}  rows: {len(rows)}", flush=True)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- completion model (numpy logistic)
def design(df, mu=None, sd=None):
    X = df.assign(depth2=df["depth"] ** 2)[FEATURES].to_numpy(float)
    if mu is None:
        mu, sd = X.mean(0), X.std(0) + 1e-9
    return np.column_stack([np.ones(len(X)), (X - mu) / sd]), mu, sd


def fit_logistic(X, y, ridge=1e-3, iters=50):
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ b))
        W = p * (1 - p)
        H = X.T @ (X * W[:, None]) + ridge * np.eye(len(b))
        step = np.linalg.solve(H, X.T @ (y - p) - ridge * b)
        b += step
        if np.abs(step).max() < 1e-8:
            break
    return b


def auc(y, s):
    o = np.argsort(s)
    r = np.empty(len(s))
    r[o] = np.arange(1, len(s) + 1)
    n1 = y.sum()
    return (r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * (len(y) - n1))


class Model:
    def __init__(self, b, mu, sd):
        self.b, self.mu, self.sd = np.asarray(b), np.asarray(mu), np.asarray(sd)

    def p(self, df):
        X, _, _ = design(df, self.mu, self.sd)
        return 1 / (1 + np.exp(-X @ self.b))


def value(p, depth, reach):
    return p * np.maximum(depth + EXPECTED_YAC + FIRST_DOWN_BONUS * reach, 0)


def train_and_validate(feat, out, plays):
    tg = feat[feat["is_target"]].copy()
    train, test = tg[tg["week"] <= 6], tg[tg["week"] >= 7]
    Xtr, mu, sd = design(train)
    b = fit_logistic(Xtr, train["complete"].to_numpy(float))
    m = Model(b, mu, sd)
    pt = m.p(test)
    yt = test["complete"].to_numpy()
    base = train["complete"].mean()
    cal = (pd.DataFrame({"p": pt, "y": yt}).assign(bin=lambda d: pd.cut(d.p, [0, .4, .55, .7, .8, .9, 1]))
           .groupby("bin", observed=True).agg(predicted=("p", "mean"), actual=("y", "mean"), n=("y", "size")))

    # Did QBs do better when they threw to our #1? (held-out weeks, ranks at the throw frame)
    te = feat[(feat["week"] >= 7) & feat["has_target"]].copy()
    te["p"] = m.p(te)
    te["value"] = value(te["p"], te["depth"], te["reaches_sticks"])
    te = te.merge(plays[["gameId", "playId", "playResult"]], on=["gameId", "playId"])
    out_rows = {}
    for mode, col in [("value", "value"), ("safe", "p")]:
        te["top"] = te.groupby(["gameId", "playId"])[col].transform("max") == te[col]
        per = te[te["is_target"]]
        agree = per["top"]
        out_rows[mode] = dict(qb_threw_to_our_1=float(agree.mean()),
                              completion_when_agree=float(per.loc[agree, "complete"].mean()),
                              completion_when_not=float(per.loc[~agree, "complete"].mean()),
                              yards_when_agree=float(per.loc[agree, "playResult"].mean()),
                              yards_when_not=float(per.loc[~agree, "playResult"].mean()),
                              first_down_rate_when_agree=float((per.loc[agree, "playResult"] >= per.loc[agree, "togo"]).mean()),
                              first_down_rate_when_not=float((per.loc[~agree, "playResult"] >= per.loc[~agree, "togo"]).mean()),
                              plays=int(len(per)))
    std_coef = dict(zip(["intercept"] + FEATURES, map(float, b)))
    res = dict(features=FEATURES, coef_standardised=std_coef, mu=mu.tolist(), sd=sd.tolist(),
               train_throws=int(len(train)), test_throws=int(len(test)),
               test_auc=float(auc(yt, pt)), test_brier=float(np.mean((pt - yt) ** 2)),
               baseline_brier=float(np.mean((base - yt) ** 2)),
               calibration=cal.reset_index().astype({"bin": str}).to_dict("records"),
               ranking_check=out_rows,
               assumptions=dict(expected_yac=EXPECTED_YAC, first_down_bonus=FIRST_DOWN_BONUS,
                                attention_sigma=SIGMA, nobody_radius=NOBODY_R))
    with open(os.path.join(out, "model.json"), "w") as fh:
        json.dump(res, fh, indent=2)
    return m, res


# ---------------------------------------------------------------- per-frame export for one play
ROLE = {"Pass": "QB", "Pass Route": "route", "Pass Block": "block", "Coverage": "coverage", "Pass Rush": "rush"}


def lane_word(l):
    return "clear" if l >= 5 else ("tight" if l >= 2 else "crowded")


def explain(recs, jersey, key):
    """One-line 'why this window' text for the #1 option in the given ranking."""
    top = min(recs, key=lambda r: r[key])
    others = [r for r in recs if r["id"] != top["id"]]
    bits = []
    if others:
        drawer = max(others, key=lambda r: r["attention"])
        puller = max(others, key=lambda r: r["safety_pull"])
        if drawer["attention"] >= 1.0:
            bits.append(f"#{jersey[drawer['id']]} draws {drawer['attention']:.1f} defenders")
        if puller["safety_pull"] >= 2.0:
            bits.append(f"the deep safety has moved {puller['safety_pull']:.1f} yds toward #{jersey[puller['id']]}")
    lead = (" and ".join(bits) + ". ") if bits else ""
    lead = lead[:1].upper() + lead[1:]
    sticks = ", past the sticks" if top["reaches_sticks"] else ""
    return (f"{lead}#{jersey[top['id']]} has {top['sep']:.1f} yds of space and a {lane_word(top['lane'])} lane"
            f"{sticks} ({top['completion_pct']:.0f}% completion).")


def export_play(data, gid, pid, plays, pff, players, games, model, out, label):
    names = players.set_index("nflId")["displayName"].to_dict()
    posn = players.set_index("nflId")["officialPosition"].to_dict()
    meta = plays.set_index(["gameId", "playId"]).loc[(gid, pid)]
    roles = pff[(pff["gameId"] == gid) & (pff["playId"] == pid)].set_index("nflId")
    t = pd.read_csv(os.path.join(data, "tracking", f"tracking_{gid}.csv"))
    p = normalise(t[t["playId"] == pid].copy())
    c = play_context(p, meta, roles)
    if c is None:
        return None
    pl = p[p["nflId"].notna()]
    at_snap = pl[pl["frameId"] == c["snap"]]
    if len(at_snap) != 22 or at_snap["team"].value_counts().tolist() != [11, 11]:
        return None  # integrity: need 11 v 11 at the snap
    P = pl.set_index(["nflId", "frameId"])
    jersey = pl.drop_duplicates("nflId").set_index("nflId")["jerseyNumber"].astype(int).to_dict()
    ball = p[p["nflId"].isna()].set_index("frameId")
    frames = sorted(p["frameId"].unique())
    target = target_from_desc(meta["playDescription"], c["routes"], names)
    deep = [s for s in c["deep"] if P.loc[(s, c["snap"]), "x"] - c["los_x"] >= 7]
    pull = np.zeros(len(c["routes"]))
    prev_d = None
    out_frames, last_ranked = [], None

    for f in frames:
        fr = pl[pl["frameId"] == f]
        fd = dict(frame=int(f), t=round((f - c["snap"]) / 10, 1),
                  phase="pre_snap" if f < c["snap"] else ("post_throw" if f > c["throw"] else "live"),
                  ball=dict(x=round(float(ball.loc[f, "x"]), 2), y=round(float(ball.loc[f, "y"]), 2)) if f in ball.index else None,
                  players=[dict(id=int(r.nflId), x=round(r.x, 2), y=round(r.y, 2),
                                px=round(r.x + 0.5 * r.vx, 2), py=round(r.y + 0.5 * r.vy, 2))
                           for r in fr.itertuples()])
        if c["snap"] <= f <= c["throw"]:
            R = pos(P, c["routes"], f)
            if f > c["snap"] and deep:   # safety pull since the snap (same rule as safety_pull.py)
                for s in deep:
                    S0, S1 = pos(P, [s], f - 1)[0], pos(P, [s], f)[0]
                    to_r = pos(P, c["routes"], f - 1) - S0
                    u = to_r / np.maximum(np.linalg.norm(to_r, axis=1, keepdims=True), 1e-6)
                    tw = u @ (S1 - S0)
                    if tw.max() > 0:
                        pull[tw.argmax()] += tw.max()
            qb = pos(P, [c["qb"]], f)[0]
            m = frame_metrics(R, pos(P, c["cov"], f), pos(P, c["defense"], f), qb, c["los_x"], c["togo"])
            df = pd.DataFrame({k: m[k] for k in ["sep", "lane", "attention", "depth"]})
            prob = model.p(df)
            val = value(prob, m["depth"], m["reaches_sticks"])
            rv = (-val).argsort().argsort() + 1
            rs = (-prob).argsort().argsort() + 1
            recs = [dict(id=int(r), jersey=jersey[r], sep=round(float(m["sep"][k]), 2),
                         attention=round(float(m["attention"][k]), 2), lane=round(float(m["lane"][k]), 2),
                         depth=round(float(m["depth"][k]), 2), reaches_sticks=bool(m["reaches_sticks"][k]),
                         safety_pull=round(float(pull[k]), 2), completion_pct=round(100 * float(prob[k]), 1),
                         expected_yards=round(float(val[k]), 2), rank_value=int(rv[k]), rank_safe=int(rs[k]))
                    for k, r in enumerate(c["routes"])]
            # pocket pressure: nearest pass rusher to the QB
            press = None
            if c["rush"]:
                Rr = pos(P, c["rush"], f)
                d = np.linalg.norm(Rr - qb, axis=1)
                k = int(d.argmin())
                closing = 0.0 if prev_d is None else (prev_d - d.min()) * 10
                prev_d = d.min()
                level = int(np.clip(round(7 * (1 - (d.min() - 1) / 6)), 0, 7))
                side = "Left" if Rr[k, 1] > qb[1] else "Right"   # +y is the QB's left
                text = ("Pocket clean" if level <= 2 else
                        ("Interior pressure" if abs(Rr[k, 1] - qb[1]) < 2 else f"{side} edge")
                        + (" closing" if closing > 1 else ""))
                press = dict(nearest_rusher_yds=round(float(d.min()), 2), closing_speed=round(closing, 2),
                             level=level, side=side.lower(), text=text, rusher_id=int(c["rush"][k]))
            fd.update(receivers=recs, pressure=press, why_value=explain(recs, jersey, "rank_value"),
                      why_safe=explain(recs, jersey, "rank_safe"))
            last_ranked = recs
        out_frames.append(fd)

    pick = lambda key: next(r["id"] for r in last_ranked if r[key] == 1)
    doc = dict(
        label=label,
        meta=dict(gameId=int(gid), playId=int(pid), week=int(games.set_index("gameId").loc[gid, "week"]),
                  quarter=int(meta["quarter"]), down=int(meta["down"]), yardsToGo=int(meta["yardsToGo"]),
                  gameClock=str(meta["gameClock"]), possessionTeam=meta["possessionTeam"],
                  defensiveTeam=meta["defensiveTeam"], offenseFormation=str(meta["offenseFormation"]),
                  personnelO=str(meta["personnelO"]), coverage=str(meta["pff_passCoverage"]),
                  coverageType=str(meta["pff_passCoverageType"]), description=meta["playDescription"],
                  los_x=round(c["los_x"], 2), first_down_x=round(c["los_x"] + c["togo"], 2),
                  snap_frame=c["snap"], throw_frame=c["throw"], last_frame=int(frames[-1]), hz=10),
        players=[dict(id=int(i), jersey=jersey[i], name=names.get(i, ""), position=posn.get(i, ""),
                      side="offense" if i not in c["defense"] else "defense",
                      role=ROLE.get(roles.loc[i, "pff_role"], "other") if i in roles.index else "other")
                 for i in jersey],
        result=dict(target_id=int(target) if target is not None else None,
                    target_jersey=jersey.get(target) if target is not None else None,
                    passResult=meta["passResult"], yards=int(meta["playResult"]),
                    model_pick_value=pick("rank_value"), model_pick_safe=pick("rank_safe"),
                    note="Outcomes for receivers who were not targeted are unknown; model values are estimates."),
        frames=out_frames,
    )
    os.makedirs(os.path.join(out, "plays"), exist_ok=True)
    path = os.path.join(out, "plays", f"play_{gid}_{pid}.json")
    with open(path, "w") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    return path


# ---------------------------------------------------------------- showcase selection
def pick_showcase(feat, model, plays, pull_csv):
    te = feat[(feat["week"] >= 7) & feat["has_target"]].copy()   # held-out weeks only
    te["p"] = model.p(te)
    te["value"] = value(te["p"], te["depth"], te["reaches_sticks"])
    te["rank"] = te.groupby(["gameId", "playId"])["value"].rank(ascending=False, method="first")
    n_routes = te.groupby(["gameId", "playId"])["nflId"].transform("size")
    te = te[n_routes >= 3]
    pm = plays.set_index(["gameId", "playId"])
    tgt = te[te["is_target"]].set_index(["gameId", "playId"])
    top = te[te["rank"] == 1].set_index(["gameId", "playId"])
    j = tgt.join(top, rsuffix="_top").join(pm[["passResult", "playResult"]])
    if os.path.exists(pull_csv):
        rp = pd.read_csv(pull_csv, usecols=["gameId", "playId", "is_target", "pull_yds"])
        mate = rp[~rp["is_target"]].groupby(["gameId", "playId"])["pull_yds"].max().rename("mate_pull")
        j = j.join(mate)
    else:
        j["mate_pull"] = 0.0
    j = j.reset_index()
    a = j[(j["rank"] != 1) & j["passResult"].isin(["I", "IN"]) & (j["p_top"] >= 0.65) & (j["sep_top"] >= 3)]
    a = a.assign(gap=a["value_top"] - a["value"]).sort_values("gap", ascending=False)
    b = j[(j["rank"] == 1) & (j["passResult"] == "C") & (j["mate_pull"] >= 3) & (j["sep"] >= 3)]
    b = b.sort_values("mate_pull", ascending=False)
    cc = j[(j["rank"] == 1) & (j["passResult"] == "C") & (j["playResult"] >= 15)].sort_values("playResult", ascending=False)
    return [("Missed window: the model's #1 was open, the QB threw elsewhere (incomplete)", a),
            ("Decoy at work: a teammate dragged the safety, the #1 option was hit", b),
            ("Model and QB agree: #1 option, big gain", cc)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="output")
    ap.add_argument("--reuse", action="store_true", help="reuse output/throw_features.csv")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    games, plays, pff, players = load_meta(a.data)
    names = players.set_index("nflId")["displayName"].to_dict()
    fcsv = os.path.join(a.out, "throw_features.csv")
    if a.reuse and os.path.exists(fcsv):
        feat = pd.read_csv(fcsv)
    else:
        feat = extract_throw_rows(a.data, plays, pff, games, names)
        feat.to_csv(fcsv, index=False)
    model, res = train_and_validate(feat, a.out, plays)
    print(f"held-out AUC {res['test_auc']:.3f}  Brier {res['test_brier']:.3f} (baseline {res['baseline_brier']:.3f})")
    for mode, r in res["ranking_check"].items():
        print(f"{mode}: QB threw to our #1 on {r['qb_threw_to_our_1']:.0%} of throws | when he did vs didn't: "
              f"completion {r['completion_when_agree']:.0%} vs {r['completion_when_not']:.0%}, "
              f"yards {r['yards_when_agree']:.1f} vs {r['yards_when_not']:.1f}, "
              f"first downs {r['first_down_rate_when_agree']:.0%} vs {r['first_down_rate_when_not']:.0%}")

    index = []
    used_games = set()
    for label, cands in pick_showcase(feat, model, plays, os.path.join(a.out, "route_pull.csv")):
        for row in cands.itertuples():
            if row.gameId in used_games:
                continue
            path = export_play(a.data, row.gameId, row.playId, plays, pff, players, games, model, a.out, label)
            if path:
                used_games.add(row.gameId)
                index.append(dict(label=label, file=os.path.relpath(path, a.out),
                                  gameId=int(row.gameId), playId=int(row.playId)))
                print("exported", path, "-", label)
                break
    with open(os.path.join(a.out, "plays", "index.json"), "w") as fh:
        json.dump(index, fh, indent=2)


if __name__ == "__main__":
    main()
