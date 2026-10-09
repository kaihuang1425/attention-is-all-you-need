"""Arrival margin and catch probability (model spec §3).

For receiver j at frame f, with QB position q:

    p0      = r_j + v_j * 0.8 s                                  initial guess
    t_ball  = t_release + |p - q| / v_ball                       ball time to the catch point
    p       = clamp(r_j + v_j * t_ball)                          constant-velocity projection
    (fixed-point iteration, 3 rounds; p is kept inside the field)

    t_def(d) = tau_react + |p - (r_d + v_d * tau_react)| / v_max(d)
               floored at |p - r_d| / v_max(d)
    margin   = min_d t_def(d) - t_ball                           > 0: receiver gets there first
    pCatch   = sigmoid(margin / tau_catch)                       before calibration (§7)
    pInt     = c_int * (1 - pCatch) * closeness
    closeness = exp(-gap / int_closeness_yd), gap = yards the fastest defender is still short of p
                when the ball arrives (0 when he is there first)

The spec's defender rule ("tau_react + distance / v_max, never less than a straight-line time
using the current velocity component toward p") is implemented the standard way: during the
reaction time the defender keeps his current velocity, then runs straight at v_max. A defender
already running at p loses little to the reaction time; one running away loses more.

Forward passes are legal only while the QB is behind the LOS (x' <= los_x'). On frames where he
is past it every pass option is removed (values set to NaN, `legal` False).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import derived_dir, load_config
from .playdata import PlayArrays


@dataclass(frozen=True)
class ArrivalParams:
    v_ball: float = 24.0
    t_release: float = 0.2
    initial_projection_s: float = 0.8
    iterations: int = 3
    tau_react: float = 0.5
    v_max_floor: float = 7.0
    tau_catch: float = 0.25
    c_int: float = 0.08
    int_closeness_yd: float = 1.5
    x_min: float = 0.5
    x_max: float = 119.5
    y_min: float = 0.5
    y_max: float = 52.8

    @classmethod
    def from_config(cls) -> ArrivalParams:
        c = load_config()["arrival"]
        clamp = c["field_clamp"]
        return cls(
            v_ball=float(c["v_ball"]),
            t_release=float(c["t_release"]),
            initial_projection_s=float(c["initial_projection_s"]),
            iterations=int(c["fixed_point_iterations"]),
            tau_react=float(c["tau_react"]),
            v_max_floor=float(c["v_max_floor"]),
            tau_catch=float(c["tau_catch"]),
            c_int=float(c["c_int"]),
            int_closeness_yd=float(c["int_closeness_yd"]),
            x_min=float(clamp.get("x_min", 0.5)),
            x_max=float(clamp["x_max"]),
            y_min=float(clamp["y_min"]),
            y_max=float(clamp["y_max"]),
        )


@dataclass
class PlayArrival:
    frames: np.ndarray  # (F,)
    receiver_ids: np.ndarray  # (R,) Pass Route players
    legal: np.ndarray  # (F,) forward pass legal and frame within snap..end
    p: np.ndarray  # (F, R, 2) projected catch point
    t_ball: np.ndarray  # (F, R) s
    t_def: np.ndarray  # (F, R) fastest defender arrival, s
    margin: np.ndarray  # (F, R) s
    p_catch: np.ndarray  # (F, R)
    p_int: np.ndarray  # (F, R)
    closeness: np.ndarray  # (F, R) interception closeness factor in [0, 1]
    nearest_def: np.ndarray  # (F, R) nflId of the fastest defender to p (0 when undefined)
    v_ball: float  # ball speed used


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.tanh(0.5 * x))


def arrival_core(
    qb_xy: np.ndarray,
    rec_xy: np.ndarray,
    rec_v: np.ndarray,
    def_xy: np.ndarray,
    def_v: np.ndarray,
    def_vmax: np.ndarray,
    params: ArrivalParams,
    v_ball: float | None = None,
) -> dict[str, np.ndarray]:
    """Vectorised arrival model.

    qb_xy (F, 2); rec_xy, rec_v (F, R, 2); def_xy, def_v (F, D, 2); def_vmax (D,).
    Returns p (F, R, 2), t_ball, t_def, margin, p_catch, p_int (F, R), nearest (F, R) index.
    """
    vb = params.v_ball if v_ball is None else float(v_ball)
    lo = np.array([params.x_min, params.y_min])
    hi = np.array([params.x_max, params.y_max])
    q = qb_xy[:, None, :]

    p = np.clip(rec_xy + rec_v * params.initial_projection_s, lo, hi)
    for _ in range(max(1, params.iterations)):
        t_ball = params.t_release + np.linalg.norm(p - q, axis=-1) / vb
        p = np.clip(rec_xy + rec_v * t_ball[..., None], lo, hi)
    t_ball = params.t_release + np.linalg.norm(p - q, axis=-1) / vb

    # Defender arrival at every catch point: (F, R, D)
    vmax = np.maximum(def_vmax, params.v_max_floor)[None, None, :]
    after_react = def_xy + def_v * params.tau_react  # (F, D, 2)
    d_react = np.linalg.norm(p[:, :, None, :] - after_react[:, None, :, :], axis=-1)
    d_now = np.linalg.norm(p[:, :, None, :] - def_xy[:, None, :, :], axis=-1)
    t_def_all = np.maximum(params.tau_react + d_react / vmax, d_now / vmax)
    t_def_all = np.where(np.isfinite(t_def_all), t_def_all, np.inf)
    nearest = t_def_all.argmin(axis=-1)
    t_def = np.take_along_axis(t_def_all, nearest[..., None], axis=-1)[..., 0]

    margin = t_def - t_ball
    p_catch = sigmoid(margin / params.tau_catch)
    near_vmax = np.take_along_axis(np.broadcast_to(vmax, t_def_all.shape), nearest[..., None], axis=-1)[..., 0]
    gap_yd = np.maximum(margin, 0.0) * near_vmax
    closeness = np.exp(-gap_yd / params.int_closeness_yd)
    p_int = params.c_int * (1.0 - p_catch) * closeness
    return {
        "p": p,
        "t_ball": t_ball,
        "t_def": t_def,
        "margin": margin,
        "p_catch": p_catch,
        "p_int": p_int,
        "closeness": closeness,
        "nearest": nearest,
    }


def defender_vmax(pa: PlayArrays) -> np.ndarray:
    """Observed top speed of each defender over the play (NaN-safe)."""
    with np.errstate(invalid="ignore"):
        return np.nan_to_num(np.nanmax(pa.def_s, axis=0), nan=0.0)


def forward_pass_legal(pa: PlayArrays) -> np.ndarray:
    """(F,) True on frames from the snap to the end event while the QB is behind the LOS."""
    in_play = (pa.frames >= pa.snap_frame) & (pa.frames <= pa.end_frame)
    behind = pa.qb_xy[:, 0] <= pa.los_x
    return in_play & behind


def arrival_for_play(pa: PlayArrays, params: ArrivalParams | None = None, v_ball: float | None = None) -> PlayArrival:
    prm = params or ArrivalParams.from_config()
    route = pa.route_mask
    out = arrival_core(
        pa.qb_xy, pa.off_xy[:, route], pa.off_v[:, route], pa.def_xy, pa.def_v, defender_vmax(pa), prm, v_ball
    )
    legal = forward_pass_legal(pa)
    mask = legal[:, None]
    nan = np.nan
    nearest_ids = np.where(mask, pa.def_ids[out["nearest"]], 0)
    return PlayArrival(
        frames=pa.frames,
        receiver_ids=pa.off_ids[route],
        legal=legal,
        p=np.where(mask[..., None], out["p"], nan),
        t_ball=np.where(mask, out["t_ball"], nan),
        t_def=np.where(mask, out["t_def"], nan),
        margin=np.where(mask, out["margin"], nan),
        p_catch=np.where(mask, out["p_catch"], nan),
        p_int=np.where(mask, out["p_int"], nan),
        closeness=np.where(mask, out["closeness"], nan),
        nearest_def=nearest_ids,
        v_ball=prm.v_ball if v_ball is None else float(v_ball),
    )


def observed_release_speed(pa: PlayArrays) -> float | None:
    """Median frame-to-frame ball speed from the throw frame to the end of tracking (yd/s)."""
    if pa.throw_frame is None:
        return None
    i0 = pa.idx(pa.throw_frame)
    xy = pa.ball_xy[i0:]
    if len(xy) < 2:
        return None
    steps = np.linalg.norm(np.diff(xy, axis=0), axis=1) * 10.0
    steps = steps[np.isfinite(steps)]
    return float(np.median(steps)) if len(steps) else None


def format_table(pa: PlayArrays, arr: PlayArrival, frame_id: int) -> str:
    i = pa.idx(frame_id)
    jersey = dict(zip(pa.off_ids.tolist(), pa.off_jersey.tolist()))
    djersey = dict(zip(pa.def_ids.tolist(), pa.def_jersey.tolist()))
    head = f"frame {frame_id} (t = {pa.t(frame_id):.1f} s){'' if arr.legal[i] else '  [QB past LOS: no forward pass]'}"
    lines = [head, "rcv   t_ball  t_def  margin  pCatch  pInt   nearest  catch point (x', y')"]
    order = np.argsort(-np.nan_to_num(arr.margin[i], nan=-9))
    for r in order:
        rid = int(arr.receiver_ids[r])
        nd = int(arr.nearest_def[i, r])
        lines.append(
            f"#{jersey[rid]:<4} {arr.t_ball[i, r]:5.2f}  {arr.t_def[i, r]:5.2f}  {arr.margin[i, r]:+5.2f}   "
            f"{arr.p_catch[i, r]:5.2f}  {arr.p_int[i, r]:5.3f}  #{djersey.get(nd, '-'):<4}    "
            f"({arr.p[i, r, 0]:5.1f}, {arr.p[i, r, 1]:4.1f})"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """Report observed release speeds and target margins at release; print the demo tables."""
    import argparse

    import pandas as pd

    from . import normalise as N
    from .playdata import iter_play_arrays, load_play
    from .targets import read_targets

    ap = argparse.ArgumentParser(description="Arrival model report (P05)")
    ap.add_argument("--games", type=int, nargs="*")
    args = ap.parse_args(argv)

    prm = ArrivalParams.from_config()
    targets = read_targets().set_index(N.KEYS)
    rows = []
    for pa in iter_play_arrays(args.games or None):
        v = observed_release_speed(pa)
        row = {"gameId": pa.gameId, "playId": pa.playId, "endType": pa.end_type, "vBallObserved": v}
        key = (pa.gameId, pa.playId)
        if pa.end_type == "throw" and key in targets.index:
            t = targets.loc[key]
            tid = t["targetNflId"]
            arr = arrival_for_play(pa, prm)
            i = pa.idx(pa.end_frame)
            hit = np.flatnonzero(arr.receiver_ids == (int(tid) if pd.notna(tid) else -1))
            if hit.size and arr.legal[i]:
                r = hit[0]
                row.update(passResult=t["passResult"], margin=arr.margin[i, r], tBall=arr.t_ball[i, r], pCatch=arr.p_catch[i, r])
        rows.append(row)
    df = pd.DataFrame(rows)
    v = df["vBallObserved"].dropna()
    print(f"observed release speed on {len(v)} throws (median frame-to-frame ball speed, throw frame to end of tracking):")
    print(f"  median {v.median():.1f} yd/s, IQR {v.quantile(.25):.1f}-{v.quantile(.75):.1f}; config default v_ball = {prm.v_ball}")
    if "margin" in df:
        tgt = df.dropna(subset=["margin"])
        print(f"\nactual target at release ({len(tgt)} throws with a matched route runner):")
        print(tgt.groupby("passResult")[["margin", "tBall", "pCatch"]].agg(["mean", "median"]).round(2).to_string())
        print(f"  t_ball range {tgt['tBall'].min():.2f}-{tgt['tBall'].max():.2f} s; "
              f"margins within -1..+2 s: {tgt['margin'].between(-1, 2).mean():.1%}")
    path = derived_dir() / "release_speed.parquet"
    df.to_parquet(path, index=False)
    print(f"wrote {path}")

    pa = load_play(2021090900, 1687)
    arr = arrival_for_play(pa, prm)
    for f in (24, 38):
        print("\n" + format_table(pa, arr, f))


if __name__ == "__main__":
    main()
