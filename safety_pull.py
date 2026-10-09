"""
Safety Pull: how far each route runner drags the safeties toward himself
between the snap and the throw, and where on the field that happens.

Usage:
    python safety_pull.py --data path/to/data --out out
    python safety_pull.py --data path/to/data --weeks 1      # quick test

Outputs (in --out):
    route_pull.csv            one row per route runner per play
    safety_pull_heatmap.png   where on the field routes drag safeties (broadcast / coach)
    decoy_effect.png/.csv     does a teammate's pull buy the target separation? (coach)
    pull_over_expected.png/.csv   receiver leaderboard (scout)
"""
import argparse
import re
import glob
import os

import numpy as np
import pandas as pd

SNAP = {"ball_snap", "autoevent_ballsnap"}
THROW = {"pass_forward", "autoevent_passforward"}
SAFETY_ALIGN = {"FS", "FSL", "FSR", "SS", "SSL", "SSR"}
NAMES = {}
TWO_HIGH = {"Cover-2", "2-Man", "Quarters", "Cover-6"}
ONE_HIGH = {"Cover-1", "Cover-3"}


def shell(cov):
    if cov in TWO_HIGH:
        return "two-high"
    if cov in ONE_HIGH:
        return "single-high"
    return "other"


def load_meta(data):
    games = pd.read_csv(os.path.join(data, "games.csv"))
    plays = pd.read_csv(os.path.join(data, "plays.csv"))
    pff = pd.read_csv(os.path.join(data, "pffScoutingData.csv"))
    players = pd.read_csv(os.path.join(data, "players.csv"))
    plays = plays[plays["passResult"].isin(["C", "I", "IN"])].copy()
    plays["shell"] = plays["pff_passCoverage"].map(shell)
    return games, plays, pff, players


NAME_RE = re.compile(r"(?: to | for )([A-Z][a-z]{0,2})\.([A-Z][A-Za-z'\-]*(?:\.? [A-Z][A-Za-z'\-]+)?)")


def target_from_desc(desc, routes, names):
    """Find the intended receiver from 'pass short right to C.Kupp' style text."""
    desc = str(desc)
    i = desc.find(" pass ")
    if i < 0:
        return None
    m = NAME_RE.search(desc[i:])
    if not m:
        return None
    init, last = m.group(1), m.group(2).strip().lower()
    for r in routes:
        n = str(names.get(r, "")).lower()
        if n.startswith(init.lower()[0]) and (n.endswith(last) or last.split()[0] in n.split()):
            return r
    return None


def first_frame(ev, frames, names):
    hit = frames[ev.isin(names)]
    return int(hit.min()) if len(hit) else None


def process_play(p, play_meta, pff_play):
    """p: tracking rows for one play (already normalised). Returns list of dicts."""
    ball = p[p["nflId"].isna()]
    ev = p.drop_duplicates("frameId").set_index("frameId")["event"]
    frames = ev.index.to_series()
    snap = first_frame(ev, frames, SNAP)
    throw = first_frame(ev, frames, THROW)
    if snap is None or throw is None or throw - snap < 5:
        return []

    pl = p[p["nflId"].notna()]
    X = pl.pivot(index="nflId", columns="frameId", values="x")
    Y = pl.pivot(index="nflId", columns="frameId", values="y")
    win = [f for f in range(snap, throw + 1) if f in X.columns]
    if len(win) < 5:
        return []

    roles = pff_play.set_index("nflId")
    routes = [i for i in roles.index[roles["pff_role"] == "Pass Route"] if i in X.index]
    safeties = [
        i
        for i in roles.index[
            (roles["pff_role"] == "Coverage") & roles["pff_positionLinedUp"].isin(SAFETY_ALIGN)
        ]
        if i in X.index
    ]
    los_x = ball.loc[ball["frameId"] == snap, "x"]
    ball_y = ball.loc[ball["frameId"] == snap, "y"]
    if los_x.empty:
        return []
    los_x, ball_y = float(los_x.iloc[0]), float(ball_y.iloc[0])
    safeties = [s for s in safeties if X.loc[s, snap] - los_x >= 7]
    defense = pl.loc[pl["team"] == play_meta["defensiveTeam"], "nflId"].unique()
    if not routes:
        return []

    def xy(ids, fr):
        return np.stack([X.loc[ids, fr].to_numpy(), Y.loc[ids, fr].to_numpy()], axis=-1)

    R = xy(routes, win)  # (nR, T, 2)
    pull = np.zeros(len(routes))
    for s in safeties:
        S = xy([s], win)[0]  # (T, 2)
        step = S[1:] - S[:-1]  # safety's own movement each frame
        to_r = R[:, :-1, :] - S[None, :-1, :]  # vector safety -> receiver
        unit = to_r / np.maximum(np.linalg.norm(to_r, axis=-1, keepdims=True), 1e-6)
        toward = (unit * step[None]).sum(-1)  # (nR, T-1) yards moved toward each receiver
        best = toward.argmax(0)  # receiver he is moving toward most, each frame
        gain = np.clip(toward.max(0), 0, None)
        np.add.at(pull, best, gain)

    D = xy(list(defense), [throw])[:, 0, :] if len(defense) else np.empty((0, 2))
    Rt = R[:, -1, :]
    sep = (
        np.linalg.norm(Rt[:, None, :] - D[None, :, :], axis=-1).min(1)
        if len(D)
        else np.full(len(routes), np.nan)
    )

    target = target_from_desc(play_meta["playDescription"], routes, NAMES)

    total = pull.sum()
    share = pull / total if total >= 1.0 else np.full(len(routes), np.nan)
    secs = (throw - snap) / 10.0
    rows = []
    for k, r in enumerate(routes):
        rows.append(
            dict(
                gameId=play_meta["gameId"],
                playId=play_meta["playId"],
                nflId=r,
                pull_yds=pull[k],
                pull_share=share[k],
                n_routes=len(routes),
                secs_to_throw=secs,
                n_safeties=len(safeties),
                depth=Rt[k, 0] - los_x,
                # QB's view: positive = to the QB's right
                lateral=-(Rt[k, 1] - ball_y),
                sep_at_throw=sep[k],
                is_target=(r == target),
                has_target=target is not None,
                coverage=play_meta["pff_passCoverage"],
                shell=play_meta["shell"],
                passResult=play_meta["passResult"],
            )
        )
    return rows


def run(data, weeks, out):
    global NAMES
    games, plays, pff, players = load_meta(data)
    NAMES = players.set_index("nflId")["displayName"].to_dict()
    if weeks:
        keep = set(games.loc[games["week"].isin(weeks), "gameId"])
    else:
        keep = set(games["gameId"])
    plays_idx = plays.set_index(["gameId", "playId"])
    pff_g = pff.groupby(["gameId", "playId"])

    rows = []
    files = sorted(glob.glob(os.path.join(data, "tracking", "tracking_*.csv")))
    for i, f in enumerate(files):
        gid = int(os.path.basename(f)[9:-4])
        if gid not in keep:
            continue
        t = pd.read_csv(
            f,
            usecols=["gameId", "playId", "nflId", "frameId", "team", "playDirection", "x", "y", "event"],
        )
        left = t["playDirection"] == "left"
        t.loc[left, "x"] = 120 - t.loc[left, "x"]
        t.loc[left, "y"] = 53.3 - t.loc[left, "y"]
        for pid, p in t.groupby("playId"):
            if (gid, pid) not in plays_idx.index:
                continue
            meta = plays_idx.loc[(gid, pid)].to_dict() | {"gameId": gid, "playId": pid}
            try:
                rows += process_play(p, meta, pff_g.get_group((gid, pid)))
            except KeyError:
                continue
        print(f"[{i + 1}/{len(files)}] {gid}  routes so far: {len(rows)}", flush=True)

    df = pd.DataFrame(rows)
    names = players.set_index("nflId")[["displayName", "officialPosition"]]
    df = df.join(names, on="nflId")
    df["week"] = df["gameId"].map(games.set_index("gameId")["week"])
    os.makedirs(out, exist_ok=True)
    df.to_csv(os.path.join(out, "route_pull.csv"), index=False)
    return df


# ---------------------------------------------------------------- heatmap
# diverging around 1.0 (= fair share): blue below, neutral gray at 1.0, red above
DIVERGING = ["#184f95", "#5598e7", "#b7d3f6", "#f0efec", "#f3c2bf", "#e66767", "#b52f2f"]
INK, MUTED, GRID = "#1f1f1e", "#6b6a66", "#d9d8d4"


def heatmap(df, out, weeks=None, min_n=None):
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm

    cmap = LinearSegmentedColormap.from_list("div", DIVERGING)
    cmap.set_bad("white")
    d_edges = np.arange(-6, 22.1, 3)
    l_edges = np.arange(-27, 27.1, 3)
    panels = [("single-high", "Single-high  (Cover-1, Cover-3)"),
              ("two-high", "Two-high  (Cover-2, 2-Man, Quarters, Cover-6)")]
    wk_label = ("Week " + ", ".join(map(str, sorted(weeks)))) if weeks else "Weeks 1–8"
    df = df[df["pull_share"].notna()].copy()
    # 1.0 = fair share (safety movement split evenly across the play's route runners)
    df["pull_index"] = df["pull_share"] * df["n_routes"]
    if min_n is None:  # fewer weeks -> fewer routes per cell, so relax the blank-cell cutoff
        min_n = 25 if len(df) > 10000 else 8

    grids = []
    for key, _ in panels:
        s = df[df["shell"] == key]
        tot, _, _ = np.histogram2d(s["depth"], s["lateral"], [d_edges, l_edges], weights=s["pull_index"])
        cnt, _, _ = np.histogram2d(s["depth"], s["lateral"], [d_edges, l_edges])
        with np.errstate(invalid="ignore", divide="ignore"):
            g = np.where(cnt >= min_n, tot / cnt, np.nan)
        grids.append((g, len(s)))
    norm = TwoSlopeNorm(vmin=0, vcenter=1, vmax=2.0)  # cells above 2x saturate

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 7), sharey=True, facecolor="white")
    fig.subplots_adjust(top=0.80, bottom=0.11, left=0.07, right=0.88, wspace=0.08)
    for ax, (g, n), (_, title) in zip(axes, grids, panels):
        im = ax.pcolormesh(l_edges, d_edges, g, cmap=cmap, norm=norm, edgecolors="white", linewidth=1.0)
        ax.axhline(0, color=INK, lw=1.6)
        ax.set_title(f"{title}   ·   {n:,} routes", loc="left", color=INK, fontsize=11, pad=8)
        ax.set_ylim(-6, 22)
        ax.set_yticks([-5, 0, 5, 10, 15, 20], ["-5", "LOS", "5", "10", "15", "20"])
        ax.set_xticks([-20, -10, 0, 10, 20], ["20 L", "10 L", "ball", "10 R", "20 R"])
        ax.tick_params(colors=MUTED, length=0)
        for sp in ax.spines.values():
            sp.set_visible(False)
    axes[0].set_ylabel("Yards past the line of scrimmage at the throw", color=MUTED)
    fig.supxlabel("Receiver position at the throw, yards from the ball (QB's left / right)", color=MUTED, fontsize=10)
    cax = fig.add_axes([0.905, 0.18, 0.016, 0.55])
    cb = fig.colorbar(im, cax=cax, ticks=[0, 0.5, 1, 1.5, 2])
    cb.ax.set_yticklabels(["0", "0.5", "1.0 fair", "1.5", "2.0+"])
    cb.ax.tick_params(colors=MUTED, length=0)
    cb.outline.set_visible(False)
    fig.text(0.07, 0.945, "Safety Pull: where route runners drag the deep safeties",
             fontsize=15, fontweight="bold", color=INK)
    fig.text(0.07, 0.875,
             "Colour = a route runner's share of the deep safeties' snap-to-throw movement, vs an even split "
             "(1.0). Red = drags them more than his share.\n"
             f"2021 NFL {wk_label}, dropbacks with a throw. Cells with fewer than {min_n} routes left blank.",
             fontsize=9.5, color=MUTED, linespacing=1.5)
    path = os.path.join(out, "safety_pull_heatmap.png")
    fig.savefig(path, dpi=160, bbox_inches="tight", pad_inches=0.3)
    return path


# ---------------------------------------------------------------- decoy effect (coach view)
def decoy_effect(df, out, min_pull=2.0):
    """Does a teammate dragging a safety give the targeted receiver more separation?
    OLS per shell: sep_at_throw ~ decoy + secs_to_throw + target depth + target's own pull."""
    import matplotlib.pyplot as plt

    d = df[df["has_target"] & df["shell"].isin(["single-high", "two-high"]) & (df["n_safeties"] > 0)]
    tgt = d[d["is_target"]].set_index(["gameId", "playId"])
    mate = d[~d["is_target"]].groupby(["gameId", "playId"])["pull_yds"].max().rename("mate_pull")
    p = tgt.join(mate).dropna(subset=["mate_pull"])
    p["decoy"] = (p["mate_pull"] >= min_pull).astype(float)
    p["complete"] = (p["passResult"] == "C").astype(float)

    rows = []
    for sh in ["single-high", "two-high"]:
        q = p[p["shell"] == sh]
        X = np.column_stack([np.ones(len(q)), q["decoy"], q["secs_to_throw"], q["depth"], q["pull_yds"]])
        res = {}
        for ycol in ["sep_at_throw", "complete"]:
            y = q[ycol].to_numpy()
            b = np.linalg.lstsq(X, y, rcond=None)[0]
            r = y - X @ b
            se = np.sqrt(np.diag(((r ** 2).sum() / (len(q) - X.shape[1])) * np.linalg.inv(X.T @ X)))
            res[ycol] = (b[1], se[1])
        rows.append(dict(shell=sh, plays=len(q), decoy_plays=int(q["decoy"].sum()),
                         sep_gain=res["sep_at_throw"][0], sep_se=res["sep_at_throw"][1],
                         comp_gain=res["complete"][0], comp_se=res["complete"][1]))
    r = pd.DataFrame(rows)
    r.to_csv(os.path.join(out, "decoy_effect.csv"), index=False)

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig, ax = plt.subplots(figsize=(10, 3.6), facecolor="white")
    fig.subplots_adjust(top=0.66, bottom=0.2, left=0.27, right=0.95)
    labels = {"single-high": "Single-high\n(Cover-1, Cover-3)", "two-high": "Two-high\n(Cover-2, 2-Man, Quarters, Cover-6)"}
    for i, row in r.iterrows():
        yv = len(r) - 1 - i
        lo, hi = row.sep_gain - 1.96 * row.sep_se, row.sep_gain + 1.96 * row.sep_se
        ax.plot([lo, hi], [yv, yv], color="#2a78d6", lw=2, solid_capstyle="round")
        ax.plot(row.sep_gain, yv, "o", ms=10, color="#2a78d6", mec="white", mew=2)
        ax.text(hi + 0.02, yv, f"{row.sep_gain:+.2f} yds   ({int(row.decoy_plays):,} of {int(row.plays):,} plays had a decoy)",
                va="center", color=INK, fontsize=9.5)
    ax.axvline(0, color=INK, lw=1.2)
    ax.set_yticks(range(len(r)), [labels[s] for s in r["shell"][::-1]])
    ax.set_xlim(-0.35, 0.75)
    ax.set_ylim(-0.6, len(r) - 0.4)
    ax.set_xlabel("Extra separation for the targeted receiver at the throw (yards)", color=MUTED)
    ax.tick_params(colors=MUTED, length=0)
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for sp in ax.spines.values():
        sp.set_visible(False)
    fig.text(0.02, 0.92, "A teammate dragging a safety frees the target, but only against single-high",
             fontsize=13.5, fontweight="bold", color=INK)
    fig.text(0.02, 0.76,
             f"Decoy = another route runner pulled a deep safety {min_pull:.0f}+ yards toward himself before the throw. "
             "Controls: time to throw, target depth,\nthe target's own pull. Dot = estimate, line = 95% interval. "
             "2021 NFL Weeks 1–8, targeted throws.",
             fontsize=9, color=MUTED, linespacing=1.5)
    path = os.path.join(out, "decoy_effect.png")
    fig.savefig(path, dpi=160, bbox_inches="tight", pad_inches=0.3)
    return path


# ---------------------------------------------------------------- Pull Over Expected (scout view)
def leaderboard(df, out, top=15, min_routes=None):
    """Pull Over Expected: a route runner's pull index minus the average index of routes that end
    in the same spot (3x3-yard cell) against the same shell. The heatmap is the 'expected' model."""
    import matplotlib.pyplot as plt

    d = df[df["pull_share"].notna() & df["shell"].isin(["single-high", "two-high"])].copy()
    d["idx"] = d["pull_share"] * d["n_routes"]
    d["db"] = np.floor(d["depth"] / 3)
    d["lb"] = np.floor(d["lateral"] / 3)
    d["expected"] = d.groupby(["shell", "db", "lb"])["idx"].transform("mean")
    d["poe"] = d["idx"] - d["expected"]
    if min_routes is None:
        min_routes = 60 if len(d) > 10000 else 15
    pl = (d.groupby(["nflId", "displayName", "officialPosition"])
          .agg(routes=("poe", "size"), pull_over_expected=("poe", "mean"), pull_index=("idx", "mean"))
          .reset_index())
    pl = pl[pl["routes"] >= min_routes].sort_values("pull_over_expected", ascending=False)
    pl.to_csv(os.path.join(out, "pull_over_expected.csv"), index=False)

    b = pl.head(top).iloc[::-1]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig, ax = plt.subplots(figsize=(9, 0.38 * len(b) + 2.2), facecolor="white")
    ax.barh(range(len(b)), b["pull_over_expected"], color="#2a78d6", height=0.62)
    for i, (v, n) in enumerate(zip(b["pull_over_expected"], b["routes"])):
        ax.text(v + 0.01, i, f"+{v:.2f}", va="center", color=INK, fontsize=9)
    ax.set_yticks(range(len(b)), [f"{nm}  ({pos}, {n} routes)" for nm, pos, n in
                                  zip(b["displayName"], b["officialPosition"], b["routes"])])
    ax.tick_params(colors=INK, length=0)
    ax.set_xticks([])
    ax.set_xlim(0, b["pull_over_expected"].max() * 1.15)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_title("Safety Pull Over Expected: who drags safeties more than his spot predicts\n",
                 loc="left", fontsize=13, fontweight="bold", color=INK)
    ax.text(0, 1.0, f"Avg per route vs. an average route ending in the same spot against the same shell "
                    f"(+0.50 = half an extra fair share). Min {min_routes} routes. 2021 Weeks 1–8.",
            transform=ax.transAxes, fontsize=8.5, color=MUTED, va="bottom")
    path = os.path.join(out, "pull_over_expected.png")
    fig.savefig(path, dpi=160, bbox_inches="tight", pad_inches=0.3)
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--weeks", type=int, nargs="*")
    ap.add_argument("--out", default="out")
    ap.add_argument("--plot-only", action="store_true", help="reuse out/route_pull.csv, just redraw")
    a = ap.parse_args()
    cache = os.path.join(a.out, "route_pull.csv")
    df = None
    if a.plot_only and os.path.exists(cache):
        df = pd.read_csv(cache)
        have = set(df["week"].unique()) if "week" in df.columns else set()
        want = set(a.weeks) if a.weeks else set(range(1, 9))
        if want <= have:
            df = df[df["week"].isin(want)]  # redraw from cache, only the weeks asked for
        else:
            print(f"Cached results don't cover weeks {sorted(want - have)}; recomputing.")
            df = None
    if df is None:
        df = run(a.data, a.weeks, a.out)
    print(heatmap(df, a.out, a.weeks))
    print(decoy_effect(df, a.out))
    print(leaderboard(df, a.out))
