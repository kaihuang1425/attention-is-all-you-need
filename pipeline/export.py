"""Per-play JSON for the app (prompt P10, first cut).

    python -m pipeline.export                 # the demo set (spec demo plays + showcase plays)
    python -m pipeline.export --plays 2021090900:1687 2021091202:210
    python -m pipeline.export --games 2021090900   # every replayable play in these games

Writes app/public/data/plays/{gameId}_{playId}.json and app/public/data/index.json.
Arrays are column-oriented (frames x players) to keep files small. NaN -> null.
The TypeScript side of this contract is app/src/data/types.ts.

Model content per frame:
- attention (attention.py): A(j) for the 10 non-QB offensive players and sparse edges a(d->j) >= 0.05
- per route runner: arrival model (catch point, ball / defender time, margin) and the completion
  model ported from pass_options.py (completion.py), which supplies pCatch; expected EPA uses
  that pCatch with this pipeline's EP values (values.py)
- pocket pressure and safety pull (completion.py)
- flags (flags.py)
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import load
from . import normalise as N
from .arrival import ArrivalParams, arrival_for_play
from .attention import AttentionParams, attention_for_play
from .completion import DEFAULT_MODEL, play_completion, pocket_pressure
from .config import export_dir, load_config
from .flags import model_flags, tracking_flags
from .playdata import PlayArrays, iter_play_arrays
from .targets import build_targets
from .values import chosen_option, decision_gap, load_ep_model, option_name, pass_values

SCHEMA_VERSION = 1

# (gameId, playId, story label, starred)
DEMO_PLAYS = [
    (2021090900, 1687, "Main demo: DAL @ TB, Lamb deep left (incomplete)", True),
    (2021090900, 3406, "Good decision: Cooper TD vs Cover-1", True),
    (2021091202, 210, "Sack: Burns comes free", True),
    (2021102401, 2381, "Showcase: missed window (pass_options.py)", False),
    (2021102404, 2652, "Showcase: decoy at work (pass_options.py)", False),
    (2021103105, 2438, "Showcase: model and QB agree, big gain (pass_options.py)", False),
]

ROLE = {"Pass": "QB", "Pass Route": "route", "Pass Block": "block", "Pass Rush": "rush", "Coverage": "coverage"}
BLOCK_TYPES = {
    "PP": "Pass protection", "PA": "Play-action protection", "PT": "Post block", "SW": "Switch", "CL": "Chip left",
    "CH": "Chip", "NB": "No block", "PU": "Pull", "SR": "Set and release", "BH": "Back help", "UP": "Unblocked pass rusher",
    "PR": "Pass release",
}


def _num(v, nd: int = 2):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    if not math.isfinite(f):
        return None
    r = round(f, nd)
    return int(r) if nd == 0 else r


def _arr(a: np.ndarray, nd: int = 2):
    a = np.asarray(a, dtype=float)
    if a.ndim == 0:
        return _num(a, nd)
    return [_arr(x, nd) for x in a] if a.ndim > 1 else [_num(x, nd) for x in a]


def _clean(v):
    """JSON-safe scalar from pandas/numpy values."""
    if v is None:
        return None
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return None if not math.isfinite(float(v)) else float(v)
    if v is pd.NA or (isinstance(v, float) and math.isnan(v)):
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _players(pa: PlayArrays, pff_play: pd.DataFrame, names: dict, positions: dict) -> list[dict]:
    pff_by = pff_play.set_index("nflId")
    order = [pa.qb_id, *pa.off_ids.tolist(), *pa.def_ids.tolist()]
    jersey = {int(i): int(j) for i, j in zip(pa.off_ids, pa.off_jersey)}
    jersey.update({int(i): int(j) for i, j in zip(pa.def_ids, pa.def_jersey)})
    jersey[int(pa.qb_id)] = int(pa.qb_jersey)
    out = []
    for nid in order:
        r = pff_by.loc[nid]
        side = "offense" if r["pff_role"] in load.OFFENSE_ROLES else "defense"
        p = {
            "id": int(nid),
            "jersey": jersey.get(int(nid)),
            "name": names.get(int(nid), ""),
            "position": positions.get(int(nid), ""),
            "side": side,
            "role": ROLE[r["pff_role"]],
            "aligned": _clean(r["pff_positionLinedUp"]),
        }
        if pd.notna(r["pff_nflIdBlockedPlayer"]):
            p["blockedId"] = int(r["pff_nflIdBlockedPlayer"])
            bt = _clean(r["pff_blockType"])
            p["blockType"] = bt
            p["blockTypeName"] = BLOCK_TYPES.get(bt or "", bt)
        credit = {
            k: int(r[k])
            for k in ("pff_hit", "pff_hurry", "pff_sack", "pff_hitAllowed", "pff_hurryAllowed", "pff_sackAllowed", "pff_beatenByDefender")
            if pd.notna(r[k]) and int(r[k]) != 0
        }
        if credit:
            p["pff"] = {k.replace("pff_", ""): v for k, v in credit.items()}
        out.append(p)
    return out


def export_play(
    pa: PlayArrays,
    pff_play: pd.DataFrame,
    events: pd.DataFrame,
    target: pd.Series | None,
    names: dict,
    positions: dict,
    ep,
    label: str,
    star: bool,
) -> dict:
    meta_row = pa.meta
    att_p = AttentionParams.from_config()
    arr_p = ArrivalParams.from_config()
    att = attention_for_play(pa, att_p)
    arr = arrival_for_play(pa, arr_p)
    comp = play_completion(pa, DEFAULT_MODEL)

    # pCatch from the completion model, only where a forward pass is legal; pInt rescaled to it.
    p_catch = np.where(arr.legal[:, None], comp.p_complete, np.nan)
    p_int = arr_p.c_int * (1.0 - p_catch) * arr.closeness
    arr.p_int = p_int
    pv = pass_values(pa, arr, ep, p_catch=p_catch)
    pressure = pocket_pressure(pa)

    # Players and tracks in one order: QB, offense (routes, blockers), defense (rushers, coverage).
    players = _players(pa, pff_play, names, positions)
    xy = np.concatenate([pa.qb_xy[:, None, :], pa.off_xy, pa.def_xy], axis=1)
    o = np.concatenate([pa.qb_o[:, None], pa.off_o, pa.def_o], axis=1)
    s = np.concatenate([pa.qb_s[:, None], pa.off_s, pa.def_s], axis=1)
    v = np.concatenate([pa.qb_v[:, None, :], pa.off_v, pa.def_v], axis=1)
    dirs = (np.rad2deg(np.arctan2(v[..., 0], v[..., 1])) + 360.0) % 360.0

    # Sparse attention edges per frame: [defenderIndex, offenseIndex, weight].
    min_w = float(load_config()["attention"]["export_min_weight"])
    edges = []
    for i in range(len(pa.frames)):
        d_idx, j_idx = np.nonzero(att.edges[i] >= min_w)
        edges.append([[int(d), int(j), round(float(att.edges[i, d, j]), 3)] for d, j in zip(d_idx, j_idx)])

    # Result and decision gap at release (pass options only until non-pass options exist).
    pass_result = str(meta_row["passResult"])
    target_id = None
    if target is not None and pd.notna(target.get("targetNflId")):
        target_id = int(target["targetNflId"])
    rel = pa.idx(pa.end_frame)
    options = {option_name(r): float(pv.ev[rel, k]) for k, r in enumerate(arr.receiver_ids)}
    chosen = chosen_option(pass_result, target_id)
    gap = decision_gap(options, chosen, pa.end_frame)
    best_id = int(gap.best.split(":")[1]) if gap.best.startswith("pass:") else None

    blocked_by: dict[int, list[int]] = {}
    for p in players:
        if "blockedId" in p:
            blocked_by.setdefault(p["blockedId"], []).append(p["id"])
    jersey = {p["id"]: p["jersey"] for p in players}
    nm = {p["id"]: p["name"] for p in players}
    flags = tracking_flags(pa, events) + model_flags(
        pa, jersey, nm, arr.receiver_ids, arr.margin, pv.ev, arr.legal, blocked_by,
        target_id if target_id in set(int(r) for r in arr.receiver_ids) else None,
    )
    flags.sort(key=lambda f: (f["frameId"], f["source"] != "tracking", f["id"]))

    home, away = str(meta_row["homeTeamAbbr"]), str(meta_row["visitorTeamAbbr"])
    meta = {k: _clean(meta_row[k]) for k in (
        "gameId", "playId", "week", "gameDate", "homeTeamAbbr", "visitorTeamAbbr", "possessionTeam", "defensiveTeam",
        "qbNflId", "qbName", "quarter", "gameClock", "down", "yardsToGo", "preSnapHomeScore", "preSnapVisitorScore",
        "offenseScore", "defenseScore", "playDirection", "absoluteYardlineNumber", "los_x", "firstDown_x", "losLabel",
        "firstDownLabel", "formation", "receiversLeft", "receiversRight", "offenseFormation", "personnelO", "personnelD",
        "defendersInBox", "dropBackType", "pff_playAction", "pff_passCoverage", "pff_passCoverageType", "snapFrame",
        "snapSource", "snapInferred", "throwFrame", "endFrame", "endType", "timeToThrow", "timeToEnd", "foulName1",
    ) if k in meta_row}
    meta.update(
        title=f"{away} @ {home}",
        label=label,
        star=star,
        firstFrame=int(pa.frames[0]),
        lastFrame=int(pa.frames[-1]),
        hz=10,
        illustrative=True,
        models={
            "epVersion": ep.version,
            "pCatch": DEFAULT_MODEL.source,
            "attention": {"sigma": att_p.sigma, "k": att_p.k, "T": att_p.temperature, "unattached": att_p.unattached_score},
            "arrival": {"vBall": arr_p.v_ball, "tRelease": arr_p.t_release, "tauReact": arr_p.tau_react},
        },
    )

    route_idx = np.flatnonzero(pa.route_mask)
    doc = {
        "version": SCHEMA_VERSION,
        "meta": meta,
        "players": players,
        "frames": {"frameId": pa.frames.tolist(), "t": [round((f - pa.snap_frame) / 10.0, 1) for f in pa.frames]},
        "tracks": {
            "x": _arr(xy[..., 0]),
            "y": _arr(xy[..., 1]),
            "s": _arr(s),
            "dir": _arr(dirs, 0),
            "o": _arr(o, 0),
        },
        "ball": [None if not np.isfinite(b).all() else [round(float(b[0]), 2), round(float(b[1]), 2)] for b in pa.ball_xy],
        "model": {
            "legal": [bool(x) for x in arr.legal],
            "receivers": [int(r) for r in arr.receiver_ids],
            "catchX": _arr(arr.p[..., 0]),
            "catchY": _arr(arr.p[..., 1]),
            "tBall": _arr(arr.t_ball),
            "tDef": _arr(arr.t_def),
            "margin": _arr(arr.margin),
            "pCatch": _arr(p_catch, 3),
            "pInt": _arr(p_int, 3),
            "ev": _arr(pv.ev, 3),
            "gain": _arr(pv.gain, 1),
            "firstDown": [[bool(x) for x in row] for row in pv.first_down],
            "touchdown": [[bool(x) for x in row] for row in pv.touchdown],
            "yardsShort": _arr(pv.yards_short, 1),
            "sep": _arr(comp.sep),
            "lane": _arr(comp.lane),
            "kernelAttention": _arr(comp.attention),
            "safetyPull": _arr(comp.safety_pull),
            "epNow": round(pv.ep_now, 3),
            "valueIncomplete": round(pv.value_incomplete, 3),
            "attention": {
                "offense": [int(x) for x in pa.off_ids],
                "defense": [int(x) for x in pa.def_ids],
                "A": _arr(att.A, 3),
                "space": _arr(att.unattached, 3),
                "edges": edges,
            },
            "pressure": pressure,
        },
        "flags": flags,
        "result": {
            "passResult": pass_result,
            "playResult": _clean(meta_row.get("playResult")),
            "description": _clean(meta_row.get("playDescription")),
            "targetId": target_id,
            "targetJersey": jersey.get(target_id) if target_id else None,
            "targetName": nm.get(target_id) if target_id else None,
            "targetIsRouteRunner": bool(target_id in set(int(r) for r in arr.receiver_ids)) if target_id else False,
            "decision": {
                "frameId": pa.end_frame,
                "chosen": chosen,
                "best": gap.best,
                "bestId": best_id,
                "evChosen": _num(gap.options.get(chosen)) if chosen else None,
                "evBest": _num(gap.options.get(gap.best)),
                "gap": _num(gap.gap, 3),
                "scope": "pass options only",
            },
        },
    }
    return doc


def _parse_plays(items: list[str]) -> list[tuple[int, int]]:
    out = []
    for it in items:
        g, p = it.replace("/", ":").split(":")
        out.append((int(g), int(p)))
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Export per-play JSON for the app")
    ap.add_argument("--plays", nargs="*", help="gameId:playId ... (default: the demo set)")
    ap.add_argument("--games", type=int, nargs="*", help="every replayable play in these games")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    out_dir = args.out or export_dir()
    (out_dir / "plays").mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()

    try:
        index = N.read_play_index()
    except FileNotFoundError:
        index = None
    labels: dict[tuple[int, int], tuple[str, bool]] = {}
    if args.games:
        plays = None
        game_ids = args.games
    else:
        keys = _parse_plays(args.plays) if args.plays else [(g, p) for g, p, _, _ in DEMO_PLAYS]
        labels = {(g, p): (lab, star) for g, p, lab, star in DEMO_PLAYS}
        plays, game_ids = keys, sorted({g for g, _ in keys})
    if index is None:
        index = N.build_play_index(game_ids, verbose=False)

    pff = load.load_pff()
    players_df = load.load_players()
    names = players_df.set_index("nflId")["displayName"].to_dict()
    positions = players_df.set_index("nflId")["officialPosition"].to_dict()
    sel = index[index["gameId"].isin(game_ids)]
    if plays is not None:
        sel = sel.merge(pd.DataFrame(plays, columns=N.KEYS), on=N.KEYS)
    targets = build_targets(sel[N.KEYS], with_ball=False, verbose=False).set_index(N.KEYS)
    ep = load_ep_model()
    print(f"EP model: {ep.version}")

    entries = []
    events_by_game: dict[int, pd.DataFrame] = {}
    for pa in iter_play_arrays(game_ids, plays=plays, index=index, pff=pff):
        key = (pa.gameId, pa.playId)
        if pa.gameId not in events_by_game:
            events_by_game[pa.gameId] = N.canonical_events(load.ball_rows(load.load_tracking(pa.gameId)))
        ev = events_by_game[pa.gameId]
        ev = ev[ev["playId"] == pa.playId]
        pff_play = pff[(pff["gameId"] == pa.gameId) & (pff["playId"] == pa.playId)]
        target = targets.loc[key] if key in targets.index else None
        label, star = labels.get(key, ("", False))
        doc = export_play(pa, pff_play, ev, target, names, positions, ep, label, star)
        name = f"{pa.gameId}_{pa.playId}.json"
        path = out_dir / "plays" / name
        path.write_text(json.dumps(doc, separators=(",", ":"), allow_nan=False))
        m = doc["meta"]
        entries.append({
            "gameId": pa.gameId, "playId": pa.playId, "file": f"plays/{name}", "label": label, "star": star,
            "title": m["title"], "offense": m["possessionTeam"], "defense": m["defensiveTeam"], "qb": m["qbName"],
            "week": m["week"], "quarter": m["quarter"], "gameClock": m["gameClock"], "down": m["down"],
            "yardsToGo": m["yardsToGo"], "passResult": doc["result"]["passResult"], "playResult": doc["result"]["playResult"],
            "coverage": m["pff_passCoverage"], "description": doc["result"]["description"],
        })
        print(f"  {name}: {len(pa.frames)} frames, {len(doc['flags'])} flags, {path.stat().st_size / 1024:.0f} KB")

    order = {k: i for i, (g, p, _, _) in enumerate(DEMO_PLAYS) for k in [(g, p)]}
    entries.sort(key=lambda e: (order.get((e["gameId"], e["playId"]), 999), e["gameId"], e["playId"]))
    idx_path = out_dir / "index.json"
    idx_path.write_text(json.dumps({"version": SCHEMA_VERSION, "plays": entries}, indent=1))
    print(f"wrote {len(entries)} plays + {idx_path} in {time.perf_counter() - start:.0f}s")



if __name__ == "__main__":
    main()
