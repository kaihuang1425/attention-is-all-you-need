"""
Safety Pull: how far each route runner drags the safeties toward himself
between the snap and the throw, and where on the field that happens.

Usage:
    python safety_pull.py --data path/to/data --out out
    python safety_pull.py --data path/to/data --weeks 1      # quick test

Outputs (in --out):
    route_pull.csv        one row per route runner per play
    safety_pull_heatmap.png
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
