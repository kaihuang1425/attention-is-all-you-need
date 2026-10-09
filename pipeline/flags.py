"""Timeline flags (docs/04_TIMELINE_FLAGS_SPEC.md, model spec §9).

Tracking flags come from ball-row events with manual/auto duplicates merged (normalise.canonical_events).
Model flags are derived per frame with a 2-frame hysteresis and carry a one-line reason.
Ids are stable: "trk-{frameId}-{type}" and "mdl-{frameId}-{type}-{nflId}".
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from .config import load_config
from .playdata import PlayArrays

log = logging.getLogger(__name__)

TRACKING_GROUPS = {
    "ball_snap": ("key", "Snap"),
    "pass_forward": ("key", "Throw"),
    "qb_sack": ("key", "Sack"),
    "qb_strip_sack": ("key", "Strip sack"),
    "run": ("key", "Scramble"),
    "line_set": ("presnap", "Line set"),
    "man_in_motion": ("presnap", "Motion"),
    "shift": ("presnap", "Shift"),
    "huddle_break_offense": ("presnap", "Huddle break"),
    "play_action": ("play", "Play action"),
    "pass_tipped": ("play", "Pass tipped"),
    "autoevent_passinterrupted": ("play", "Pass interrupted"),
    "handoff": ("play", "Handoff"),
    "lateral": ("play", "Lateral"),
    "first_contact": ("play", "First contact"),
    "fumble": ("play", "Fumble"),
    "fumble_offense_recovered": ("play", "Fumble recovered"),
    "penalty_flag": ("play", "Penalty flag"),
    "pass_arrived": ("ballInAir", "Pass arrived"),
    "pass_outcome_caught": ("ballInAir", "Caught"),
    "pass_outcome_incomplete": ("ballInAir", "Incomplete"),
    "dropped_pass": ("ballInAir", "Dropped"),
    "out_of_bounds": ("ballInAir", "Out of bounds"),
    "tackle": ("ballInAir", "Tackle"),
}


def _t(pa: PlayArrays, frame: int) -> float:
    return round((frame - pa.snap_frame) / 10.0, 1)


def tracking_flags(pa: PlayArrays, events: pd.DataFrame) -> list[dict]:
    """events: canonical_events rows for this play."""
    out = []
    for e in events.sort_values("frameId").itertuples(index=False):
        etype = str(e.type)
        group, label = TRACKING_GROUPS.get(etype, ("play", etype.replace("_", " ").capitalize()))
        if etype not in TRACKING_GROUPS:
            log.warning("unknown event %s on %s/%s", etype, pa.gameId, pa.playId)
        f = {
            "id": f"trk-{int(e.frameId)}-{etype}",
            "frameId": int(e.frameId),
            "t": _t(pa, int(e.frameId)),
            "type": etype,
            "group": group,
            "source": "tracking",
            "label": label,
        }
        auto = e.autoFrame
        if pd.notna(auto) and abs(int(auto) - int(e.frameId)) > 2:
            f["reason"] = f"auto event at frame {int(auto)} ignored"
        if bool(e.fromAuto):
            f["reason"] = "from the auto event (no manual event)"
        out.append(f)
    if pa.meta.get("snapInferred"):
        out.append(
            {
                "id": f"trk-{pa.snap_frame}-ball_snap",
                "frameId": pa.snap_frame,
                "t": 0.0,
                "type": "ball_snap",
                "group": "key",
                "source": "tracking",
                "label": "Snap (inferred)",
                "inferred": True,
            }
        )
    return out


def _stable_runs(state: np.ndarray, hold: int) -> list[tuple[int, bool]]:
    """Indices where a boolean state changes and the new value then holds for `hold` frames.
    Returns (index, new_state). The initial state is not reported."""
    changes = []
    cur = None
    i = 0
    n = len(state)
    while i < n:
        s = bool(state[i])
        if cur is None:
            cur = s
        elif s != cur and all(bool(state[j]) == s for j in range(i, min(n, i + hold))) and i + hold <= n:
            changes.append((i, s))
            cur = s
        i += 1
    return changes


def model_flags(
    pa: PlayArrays,
    jersey: dict[int, int],
    names: dict[int, str],
    receiver_ids: np.ndarray,
    margin: np.ndarray,
    ev: np.ndarray,
    legal: np.ndarray,
    blocked_by: dict[int, list[int]],
    target_id: int | None,
) -> list[dict]:
    cfg = load_config()["flags"]
    thr = float(cfg["window_margin_s"])
    hold = int(cfg["hysteresis_frames"])
    pdist = float(cfg["pressure_distance_yd"])
    beaten_frames = int(cfg["block_beaten_frames"])
    i0, i1 = pa.idx(pa.snap_frame), pa.idx(pa.end_frame)
    frames = pa.frames
    out: list[dict] = []

    def who(nid: int) -> str:
        last = names.get(nid, "").split(" ")[-1]
        return f"#{jersey.get(nid, '?')} {last}".strip()

    def add(i: int, ftype: str, group: str, label: str, nid: int | None = None, reason: str | None = None):
        fid = int(frames[i])
        f = {
            "id": f"mdl-{fid}-{ftype}" + (f"-{nid}" if nid is not None else ""),
            "frameId": fid,
            "t": _t(pa, fid),
            "type": ftype,
            "group": group,
            "source": "model",
            "label": label,
        }
        if nid is not None:
            f["nflId"] = int(nid)
        if reason:
            f["reason"] = reason
        out.append(f)

    # Windows: margin >= threshold, per receiver, on legal frames.
    win = slice(i0, i1 + 1)
    for k, rid in enumerate(receiver_ids):
        m = margin[win, k]
        state = np.where(np.isfinite(m), m >= thr, False)
        # Only crossings are flagged; most receivers start "open" at the snap, which says nothing.
        for j, s in _stable_runs(state, hold):
            i = i0 + j
            kind = "window_open" if s else "window_close"
            word = "opens" if s else "closes"
            add(i, kind, "windows", f"{who(rid)} window {word}", int(rid), f"margin crosses {thr:+.1f} s (now {margin[i, k]:+.2f} s)")

    # Best option changes (EV argmax among legal pass options), ignoring flips that revert within `hold` frames.
    evw = ev[win]
    best = np.array([int(np.nanargmax(r)) if np.isfinite(r).any() else -1 for r in evw])
    cur = None
    for j in range(len(best)):
        b = best[j]
        if b < 0:
            continue
        if cur is None:
            cur = b
            continue
        if b != cur and all(best[jj] == b for jj in range(j, min(len(best), j + hold))) and j + hold <= len(best):
            cur = b
            rid = int(receiver_ids[b])
            add(i0 + j, "best_option_change", "decision", f"Best option: {who(rid)}", rid, f"EV {evw[j, b]:+.2f}")

    # Peak decision gap before release vs the eventual target.
    if target_id is not None and target_id in set(int(r) for r in receiver_ids):
        k = int(np.flatnonzero(receiver_ids == target_id)[0])
        gap = np.nanmax(evw, axis=1) - evw[:, k]
        if np.isfinite(gap).any():
            j = int(np.nanargmax(gap))
            if gap[j] > 0.05:
                bk = int(np.nanargmax(evw[j]))
                add(i0 + j, "peak_decision_gap", "decision", f"Peak gap: {who(int(receiver_ids[bk]))} over {who(target_id)}",
                    int(receiver_ids[bk]), f"expected EPA gap {gap[j]:+.2f}")

    # Pressure arrives: first frame a rusher is within pdist of the QB (holding `hold` frames).
    rush = np.flatnonzero(pa.rush_mask)
    if len(rush):
        d = np.linalg.norm(pa.def_xy[:, rush] - pa.qb_xy[:, None, :], axis=-1)
        near = (np.nanmin(d, axis=1) <= pdist)[win]
        for j in range(len(near)):
            if all(near[j : j + hold]) and j + hold <= len(near):
                r = int(rush[int(np.nanargmin(d[i0 + j]))])
                add(i0 + j, "pressure_arrives", "protection", f"Pressure: {who(int(pa.def_ids[r]))}", int(pa.def_ids[r]),
                    f"rusher within {pdist:.1f} yd of the QB")
                break

        # Unblocked rusher: no blocker's first assignment, crosses the LOS.
        for r in rush:
            rid = int(pa.def_ids[r])
            if rid in blocked_by:
                continue
            crossed = np.flatnonzero(pa.def_xy[win, r, 0] < pa.los_x)
            if crossed.size:
                add(i0 + int(crossed[0]), "unblocked_rusher", "protection", f"Unblocked: {who(rid)}", rid,
                    "no blocker's first assignment; crossed the LOS")

    # Block beaten: the rusher a blocker first engaged gets past him on the blocker -> QB line.
    off_index = {int(o): c for c, o in enumerate(pa.off_ids)}
    def_index = {int(d): c for c, d in enumerate(pa.def_ids)}
    for rusher, blockers in blocked_by.items():
        r = def_index.get(rusher)
        if r is None:
            continue
        for b_id in blockers:
            b = off_index.get(b_id)
            if b is None:
                continue
            bxy = pa.off_xy[win, b]
            rxy = pa.def_xy[win, r]
            q = pa.qb_xy[win]
            u = q - bxy
            u = u / np.maximum(np.linalg.norm(u, axis=1, keepdims=True), 1e-6)
            # Past him along the blocker -> QB line AND closer to the QB in plain distance.
            past = (np.einsum("ij,ij->i", rxy - bxy, u) > 0) & (
                np.linalg.norm(rxy - q, axis=1) < np.linalg.norm(bxy - q, axis=1)
            )
            if past[0]:
                continue  # already "past" at the snap: alignment geometry, not a lost block
            run = 0
            for j, p in enumerate(past):
                run = run + 1 if p else 0
                if run >= beaten_frames:
                    jj = j - beaten_frames + 1
                    add(i0 + jj, "block_beaten", "protection", f"{who(b_id)} beaten by {who(rusher)}", b_id,
                        f"{who(rusher)} is closer to the QB than {who(b_id)} for {beaten_frames}+ frames")
                    break
    return sorted(out, key=lambda f: (f["frameId"], f["id"]))
