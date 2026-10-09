"""Completion model and receiver metrics ported from the team's pass_options.py / passOptions.ts.

Per route runner at a frame:
    sep        distance to the nearest defender (capped at 10 yd)
    lane       closest defender to the middle 25-85% of the QB -> receiver line (capped at 10 yd)
    attention  Gaussian kernel (sigma 3 yd) over coverage defenders, each defender's focus split
               across receivers plus a "nobody" option at 7 yd (not the orientation-based
               attention in attention.py; this one is only a model input)
    depth      yards past the LOS; reaches_sticks = depth >= yards to go

Completion probability: logistic regression on (sep, lane, attention, depth, depth^2), trained by
pass_options.py on 2021 weeks 1-6 targeted throws at the release frame; held-out AUC 0.72 on
weeks 7-8. The coefficients below are copied from passOptions.ts (DEFAULT_MODEL) so the app and
the pipeline produce the same numbers.

Safety pull and pocket pressure follow the same rules as pass_options.py.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .playdata import PlayArrays

SAFETY_ALIGN = {"FS", "FSL", "FSR", "SS", "SSL", "SSR"}


@dataclass(frozen=True)
class CompletionModel:
    intercept: float = 0.7578694391359947
    coef: tuple = (0.5705272892715294, -0.09125081626188389, -0.028536078737154056, -0.3327617969832017, -0.02829357429351297)
    mu: tuple = (3.757487148025027, 3.78167896408568, 0.850562858773423, 6.790964100666172, 86.61537111398964)
    sd: tuple = (2.3025147598530564, 3.4489378587838955, 0.47084588300490043, 6.363817856458539, 134.9895540714804)
    attention_sigma: float = 3.0
    nobody_radius: float = 7.0
    source: str = "pass_options.py logistic (sep, lane, attention, depth, depth^2); trained wk 1-6, AUC 0.72 on wk 7-8"


DEFAULT_MODEL = CompletionModel()


def lane_distance(def_xy: np.ndarray, qb: np.ndarray, rec: np.ndarray) -> np.ndarray:
    """Distance of each defender (D, 2) to the middle 25-85% of the line qb -> rec; inf when not alongside."""
    ab = rec - qb
    l2 = max(float(ab @ ab), 1e-6)
    u = ((def_xy - qb) @ ab) / l2
    proj = qb + np.clip(u, 0, 1)[:, None] * ab
    d = np.linalg.norm(def_xy - proj, axis=1)
    return np.where((u >= 0.25) & (u <= 0.85), d, np.inf)


def frame_metrics(
    rec_xy: np.ndarray, cov_xy: np.ndarray, def_xy: np.ndarray, qb: np.ndarray, los_x: float, ytg: float, m: CompletionModel = DEFAULT_MODEL
) -> dict[str, np.ndarray]:
    """Metrics for R receivers at one frame. rec_xy (R, 2), cov_xy (C, 2), def_xy (D, 2), qb (2,)."""
    if len(def_xy):
        sep = np.linalg.norm(rec_xy[:, None] - def_xy[None], axis=-1).min(axis=1)
        lane = np.array([min(10.0, float(lane_distance(def_xy, qb, r).min())) for r in rec_xy])
    else:
        sep = np.full(len(rec_xy), 10.0)
        lane = np.full(len(rec_xy), 10.0)
    if len(cov_xy):
        d = np.linalg.norm(cov_xy[:, None] - rec_xy[None], axis=-1)
        s2 = 2 * m.attention_sigma**2
        q = np.exp(-(d**2) / s2)
        q_none = np.exp(-(m.nobody_radius**2) / s2)
        att = (q / (q_none + q.sum(axis=1, keepdims=True))).sum(axis=0)
    else:
        att = np.zeros(len(rec_xy))
    depth = rec_xy[:, 0] - los_x
    return {"sep": np.minimum(sep, 10.0), "lane": lane, "attention": att, "depth": depth, "reaches_sticks": depth >= ytg}


def completion_prob(metrics: dict[str, np.ndarray], m: CompletionModel = DEFAULT_MODEL) -> np.ndarray:
    f = np.stack([metrics["sep"], metrics["lane"], metrics["attention"], metrics["depth"], metrics["depth"] ** 2], axis=-1)
    z = m.intercept + ((f - np.array(m.mu)) / np.array(m.sd)) @ np.array(m.coef)
    return 1.0 / (1.0 + np.exp(-z))


@dataclass
class PlayCompletion:
    sep: np.ndarray  # (F, R)
    lane: np.ndarray
    attention: np.ndarray
    depth: np.ndarray
    p_complete: np.ndarray
    safety_pull: np.ndarray  # (F, R) cumulative yards the deep safeties moved toward each receiver


def play_completion(pa: PlayArrays, m: CompletionModel = DEFAULT_MODEL) -> PlayCompletion:
    """Metrics and completion probability for every route runner on every frame snap..end (NaN elsewhere)."""
    route = pa.route_mask
    cov = pa.def_roles == "Coverage"
    ytg = float(pa.meta["yardsToGo"])
    F, R = len(pa.frames), int(route.sum())
    out = {k: np.full((F, R), np.nan) for k in ("sep", "lane", "attention", "depth", "p")}
    pull = np.full((F, R), np.nan)

    i0, i1 = pa.idx(pa.snap_frame), pa.idx(pa.end_frame)
    rec_all = pa.off_xy[:, route]
    # Deep safeties: safety alignment and at least 7 yd deep at the snap.
    deep = [d for d in range(len(pa.def_ids)) if pa.def_aligned[d] in SAFETY_ALIGN and pa.def_xy[i0, d, 0] - pa.los_x >= 7]
    acc = np.zeros(R)
    for i in range(i0, i1 + 1):
        rec = rec_all[i]
        met = frame_metrics(rec, pa.def_xy[i, cov], pa.def_xy[i], pa.qb_xy[i], pa.los_x, ytg, m)
        for k in ("sep", "lane", "attention", "depth"):
            out[k][i] = met[k]
        out["p"][i] = completion_prob(met, m)
        if i > i0:
            for d in deep:
                s0, s1 = pa.def_xy[i - 1, d], pa.def_xy[i, d]
                to_r = rec_all[i - 1] - s0
                u = to_r / np.maximum(np.linalg.norm(to_r, axis=1, keepdims=True), 1e-6)
                toward = u @ (s1 - s0)
                if np.isfinite(toward).any() and np.nanmax(toward) > 0:
                    acc[int(np.nanargmax(toward))] += float(np.nanmax(toward))
        pull[i] = acc
    return PlayCompletion(out["sep"], out["lane"], out["attention"], out["depth"], out["p"], pull)


def pocket_pressure(pa: PlayArrays) -> list[dict | None]:
    """Nearest pass rusher to the QB per frame (snap..end), same rule as pass_options.py."""
    rush = np.flatnonzero(pa.rush_mask)
    res: list[dict | None] = [None] * len(pa.frames)
    if not len(rush):
        return res
    prev = None
    for i in range(pa.idx(pa.snap_frame), pa.idx(pa.end_frame) + 1):
        q = pa.qb_xy[i]
        d = np.linalg.norm(pa.def_xy[i, rush] - q, axis=1)
        k = int(np.nanargmin(d))
        dmin = float(d[k])
        closing = 0.0 if prev is None else (prev - dmin) * 10.0
        prev = dmin
        level = int(np.clip(round(7 * (1 - (dmin - 1) / 6)), 0, 7))
        dy = float(pa.def_xy[i, rush[k], 1] - q[1])
        side = "left" if dy > 0 else "right"  # +y is the QB's left
        if level <= 2:
            text = "Pocket clean"
        else:
            text = ("Interior pressure" if abs(dy) < 2 else f"{side.capitalize()} edge") + (" closing" if closing > 1 else "")
        res[i] = {"nearest": round(dmin, 2), "closing": round(closing, 2), "level": level, "side": side, "text": text, "rusherId": int(pa.def_ids[rush[k]])}
    return res
