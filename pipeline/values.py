"""Expected points and option values (model spec §4 and §8, prompt P06).

EP lookup, two versions (the active one is reported as `EPModel.version` and goes into the export
metadata):

- v1 (no external data): closed form per down,
      EP = a + b*u + c*u^2 + e*ln(ytg),  u = yardline_100 / 100.
  The constants were fitted by least squares to nflverse 2021 `ep` (regular season, downs 1-4,
  40,007 plays) and rounded to 2 decimals. RMSE 0.41 points against nflverse EP, whose standard
  deviation is 1.76; most of the residual is clock and score, which this model ignores.
- v2 (needs data/external/pbp_2021.parquet, see scripts/get_nflverse.sh): binned means of
  nflverse `ep` by down x yards-to-go bucket x yardline_100, smoothed across yardline with a
  Gaussian kernel (3 yd) and shrunk toward v1 where a bin has few plays.

Option values (all in expected points added, EPA, from the offense's view):

    value_complete(j)  = EP(after a catch at p_j plus expected YAC) - EP(now)
    value_incomplete   = EP(next down, same spot) - EP(now)
    value_interception = -EP_opponent(1st & 10 at the catch point) - EP(now)
    EV_pass(j) = pCatch*value_complete + (1 - pCatch - pInt)*value_incomplete + pInt*value_interception

Touchdown = +7 points, safety = -2 (both minus EP(now)). A 4th-down incompletion or a 4th-down
catch short of the line is a turnover on downs. No return yards on interceptions; a pick in the
end zone is a touchback.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .arrival import PlayArrival
from .config import derived_dir, external_dir, load_config
from .playdata import PlayArrays

# v1 coefficients per down: (a, b, c, e). Source: least-squares fit to nflverse 2021 `ep`,
# see module docstring.
EP_V1_COEF = {
    1: (6.53, -6.55, 0.40, -0.35),
    2: (6.13, -6.65, 0.43, -0.40),
    3: (5.49, -6.66, 0.47, -0.44),
    4: (4.14, -8.17, 1.92, -0.22),
}
TD_POINTS = 7.0
SAFETY_POINTS = -2.0

# Yards-to-go buckets for the v2 table: 1..10 each, then 11-13, 14-16, 17-20, 21+.
YTG_EDGES = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 14, 17, 21])


def ep_v1(down, ytg, yl100) -> np.ndarray:
    down = np.clip(np.asarray(down, dtype=int), 1, 4)
    u = np.clip(np.asarray(yl100, dtype=float), 1, 99) / 100.0
    lg = np.log(np.clip(np.asarray(ytg, dtype=float), 1, 99))
    coef = np.array([EP_V1_COEF[d] for d in (1, 2, 3, 4)])[down - 1]
    return coef[..., 0] + coef[..., 1] * u + coef[..., 2] * u**2 + coef[..., 3] * lg


def _ytg_bucket(ytg) -> np.ndarray:
    return np.clip(np.digitize(np.asarray(ytg, dtype=float), YTG_EDGES) - 1, 0, len(YTG_EDGES) - 1)


@dataclass
class EPModel:
    version: str
    table: np.ndarray | None = field(default=None, repr=False)  # (4, n_buckets, 99) for v2

    def __call__(self, down, ytg, yl100) -> np.ndarray:
        if self.table is None:
            return ep_v1(down, ytg, yl100)
        d = np.clip(np.asarray(down, dtype=int), 1, 4) - 1
        b = _ytg_bucket(ytg)
        y = np.clip(np.rint(np.asarray(yl100, dtype=float)), 1, 99).astype(int) - 1
        return self.table[d, b, y]


def fit_ep_v2(pbp: pd.DataFrame, bandwidth_yd: float = 3.0, prior_n: float = 5.0) -> np.ndarray:
    """Smoothed binned-mean EP table from nflverse play-by-play."""
    d = pbp[(pbp["season_type"] == "REG") & pbp["down"].between(1, 4) & pbp["ep"].notna() & pbp["yardline_100"].between(1, 99)]
    d = d[d["ydstogo"] > 0]
    down = d["down"].to_numpy(dtype=int) - 1
    b = _ytg_bucket(d["ydstogo"].to_numpy())
    y = d["yardline_100"].to_numpy(dtype=int) - 1
    nb = len(YTG_EDGES)
    sums = np.zeros((4, nb, 99))
    counts = np.zeros((4, nb, 99))
    np.add.at(sums, (down, b, y), d["ep"].to_numpy(dtype=float))
    np.add.at(counts, (down, b, y), 1.0)

    # Gaussian smoothing across yardline (weighted by counts), then shrink toward v1.
    offs = np.arange(-9, 10)
    kern = np.exp(-0.5 * (offs / bandwidth_yd) ** 2)
    pad = len(offs) // 2
    sp = np.pad(sums, ((0, 0), (0, 0), (pad, pad)))
    cp = np.pad(counts, ((0, 0), (0, 0), (pad, pad)))
    ssm = sum(k * sp[..., i : i + 99] for i, k in enumerate(kern))
    csm = sum(k * cp[..., i : i + 99] for i, k in enumerate(kern))

    # v1 prior evaluated at a representative yards-to-go for each bucket.
    rep_ytg = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 18, 23], dtype=float)
    dd, bb, yy = np.meshgrid(np.arange(1, 5), rep_ytg, np.arange(1, 100), indexing="ij")
    prior = ep_v1(dd, bb, yy)
    return (ssm + prior_n * prior) / (csm + prior_n)


def load_ep_model(version: str | None = None) -> EPModel:
    """'auto' (default from config): v2 when the nflverse file exists, else v1."""
    version = version or str(load_config()["values"]["ep_version"])
    pbp_path = external_dir() / "pbp_2021.parquet"
    if version == "v1" or (version == "auto" and not pbp_path.exists()):
        return EPModel("v1-closed-form")
    cache = derived_dir() / "ep_table_v2.npy"
    if cache.exists() and cache.stat().st_mtime >= pbp_path.stat().st_mtime:
        return EPModel("v2-nflverse-2021", np.load(cache))
    pbp = pd.read_parquet(pbp_path, columns=["season_type", "down", "ydstogo", "yardline_100", "ep"])
    table = fit_ep_v2(pbp)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache, table)
    return EPModel("v2-nflverse-2021", table)


# --------------------------------------------------------------------------------------------
# State transitions
# --------------------------------------------------------------------------------------------


def _first_down_ytg(yl100: np.ndarray) -> np.ndarray:
    return np.where(yl100 < 10, np.maximum(yl100, 1), 10)


def ep_after_gain(ep: EPModel, down: int, ytg: float, yl100: float, gain: np.ndarray) -> np.ndarray:
    """EP (offense's view) of the state after a play that gains `gain` yards and keeps the ball
    with the offense unless it is a turnover on downs. Handles TD, safety, first down."""
    gain = np.asarray(gain, dtype=float)
    new_yl = yl100 - gain
    td = new_yl <= 0
    safety = new_yl >= 100
    yl = np.clip(new_yl, 1, 99)
    first = gain >= ytg
    ep_first = ep(1, _first_down_ytg(yl), yl)
    ep_next = ep(min(down + 1, 4), np.maximum(ytg - gain, 1), yl)
    if down == 4:
        # Short of the line on 4th down: opponent takes over at the spot.
        opp_yl = np.clip(100 - yl, 1, 99)
        ep_next = -ep(1, _first_down_ytg(opp_yl), opp_yl)
    out = np.where(first, ep_first, ep_next)
    out = np.where(td, TD_POINTS, out)
    return np.where(safety, SAFETY_POINTS, out)


def ep_after_incomplete(ep: EPModel, down: int, ytg: float, yl100: float) -> float:
    if down >= 4:
        opp_yl = float(np.clip(100 - yl100, 1, 99))
        return float(-ep(1, _first_down_ytg(np.array(opp_yl)), opp_yl))
    return float(ep(down + 1, ytg, yl100))


def ep_after_interception(ep: EPModel, catch_x: np.ndarray) -> np.ndarray:
    """Offense's EP after a pick at normalised catch_x: minus the opponent's 1st-and-10 EP."""
    opp_yl = np.asarray(catch_x, dtype=float) - 10.0  # opponent attacks toward x = 10
    opp_yl = np.where(opp_yl >= 100, 80.0, opp_yl)  # pick in the end zone: touchback
    opp_yl = np.clip(opp_yl, 1, 99)
    return -ep(1, _first_down_ytg(opp_yl), opp_yl)


# --------------------------------------------------------------------------------------------
# Pass option values
# --------------------------------------------------------------------------------------------


@dataclass
class PassValues:
    ep_now: float
    value_incomplete: float
    gain: np.ndarray  # (F, R) yards past the LOS at the catch point plus expected YAC
    first_down: np.ndarray  # (F, R) bool
    touchdown: np.ndarray  # (F, R) bool
    yards_short: np.ndarray  # (F, R) yards short of the line to gain (0 when it is reached)
    value_complete: np.ndarray  # (F, R)
    value_interception: np.ndarray  # (F, R)
    ev: np.ndarray  # (F, R) expected EPA of passing to each receiver (NaN when illegal)


def situation(pa: PlayArrays) -> tuple[int, float, float]:
    """(down, yards to go, yardline_100) at the snap."""
    m = pa.meta
    return int(m["down"]), float(m["yardsToGo"]), float(110.0 - pa.los_x)


def expected_yac(catch_depth: np.ndarray) -> np.ndarray:
    c = load_config()["values"]
    return np.where(catch_depth >= float(c["deep_air_yards"]), float(c["yac_deep"]), float(c["yac_short"]))


def pass_values(pa: PlayArrays, arr: PlayArrival, ep: EPModel, p_catch: np.ndarray | None = None) -> PassValues:
    """EV of passing to each route runner on every frame (spec §4).

    `p_catch` overrides arr.p_catch, e.g. with calibrated probabilities.
    """
    down, ytg, yl100 = situation(pa)
    ep_now = float(ep(down, ytg, yl100))
    catch_x = arr.p[..., 0]
    depth = catch_x - pa.los_x
    gain = depth + expected_yac(depth)
    after = ep_after_gain(ep, down, ytg, yl100, np.nan_to_num(gain))
    v_complete = after - ep_now
    v_incomplete = ep_after_incomplete(ep, down, ytg, yl100) - ep_now
    v_int = ep_after_interception(ep, np.nan_to_num(catch_x, nan=pa.los_x)) - ep_now

    pc = arr.p_catch if p_catch is None else p_catch
    pi = arr.p_int
    ev = pc * v_complete + (1.0 - pc - pi) * v_incomplete + pi * v_int
    illegal = ~np.isfinite(pc)
    nan = np.nan
    return PassValues(
        ep_now=ep_now,
        value_incomplete=float(v_incomplete),
        gain=np.where(illegal, nan, gain),
        first_down=np.where(illegal, False, gain >= ytg),
        touchdown=np.where(illegal, False, yl100 - gain <= 0),
        yards_short=np.where(illegal, nan, np.maximum(ytg - gain, 0.0)),
        value_complete=np.where(illegal, nan, v_complete),
        value_interception=np.where(illegal, nan, v_int),
        ev=np.where(illegal, nan, ev),
    )


# --------------------------------------------------------------------------------------------
# Decision gap (spec §8)
# --------------------------------------------------------------------------------------------


@dataclass
class DecisionGap:
    frame: int
    options: dict[str, float]  # option name -> EV at the release frame
    best: str
    chosen: str | None
    gap: float | None  # EV(best) - EV(chosen), >= 0; None when the chosen option is unknown


def option_name(nfl_id: int) -> str:
    return f"pass:{int(nfl_id)}"


def decision_gap(
    options: dict[str, float],
    chosen: str | None,
    frame: int,
) -> DecisionGap:
    finite = {k: v for k, v in options.items() if v is not None and np.isfinite(v)}
    if not finite:
        return DecisionGap(frame, options, "", chosen, None)
    best = max(finite, key=finite.get)
    gap = None
    if chosen is not None and chosen in finite:
        gap = float(finite[best] - finite[chosen])
    return DecisionGap(frame, finite, best, chosen, gap)


def chosen_option(pass_result: str, target_nfl_id) -> str | None:
    """The QB's actual choice: the targeted receiver, or scramble (R) / hold (S)."""
    if pass_result == "R":
        return "scramble"
    if pass_result == "S":
        return "hold"
    if pd.notna(target_nfl_id):
        return option_name(int(target_nfl_id))
    return None


def pass_options_at(pa: PlayArrays, arr: PlayArrival, pv: PassValues, frame_id: int) -> dict[str, float]:
    i = pa.idx(frame_id)
    return {option_name(r): float(pv.ev[i, k]) for k, r in enumerate(arr.receiver_ids)}


def main(argv: list[str] | None = None) -> None:
    """Report EV of the actual target at release by passResult; print the demo play values."""
    import argparse
    import time

    from . import normalise as N
    from .arrival import ArrivalParams, arrival_for_play
    from .playdata import iter_play_arrays, load_play
    from .targets import read_targets

    ap = argparse.ArgumentParser(description="Option values report (P06)")
    ap.add_argument("--games", type=int, nargs="*")
    ap.add_argument("--ep", choices=["auto", "v1", "v2"], default=None)
    args = ap.parse_args(argv)

    ep = load_ep_model(args.ep)
    print(f"EP model: {ep.version}")
    prm = ArrivalParams.from_config()
    targets = read_targets().set_index(N.KEYS)
    rows = []
    start = time.perf_counter()
    for pa in iter_play_arrays(args.games or None):
        key = (pa.gameId, pa.playId)
        if pa.end_type != "throw" or key not in targets.index:
            continue
        t = targets.loc[key]
        if t["passResult"] not in ("C", "I", "IN"):
            continue
        arr = arrival_for_play(pa, prm)
        pv = pass_values(pa, arr, ep)
        i = pa.idx(pa.end_frame)
        if not arr.legal[i]:
            continue
        opts = pass_options_at(pa, arr, pv, pa.end_frame)
        chosen = chosen_option(t["passResult"], t["targetNflId"])
        g = decision_gap(opts, chosen, pa.end_frame)
        k = np.flatnonzero(arr.receiver_ids == (int(t["targetNflId"]) if pd.notna(t["targetNflId"]) else -1))
        rows.append(
            {
                "gameId": pa.gameId,
                "playId": pa.playId,
                "week": int(pa.meta["week"]),
                "passResult": t["passResult"],
                "targetMatched": bool(k.size),
                "evTarget": float(pv.ev[i, k[0]]) if k.size else np.nan,
                "pCatchTarget": float(arr.p_catch[i, k[0]]) if k.size else np.nan,
                "evBest": g.options.get(g.best, np.nan),
                "best": g.best,
                "chosen": chosen,
                "gap": g.gap,
                "epNow": pv.ep_now,
            }
        )
    df = pd.DataFrame(rows)
    print(f"{len(df)} targeted throws evaluated in {time.perf_counter() - start:.0f}s")
    m = df[df["targetMatched"]]
    tab = m.groupby("passResult")["evTarget"].agg(["count", "mean", "median"]).reindex(["C", "I", "IN"])
    print("\nEV_pass of the actual target at release (expected EPA), by passResult:")
    print(tab.round(3).to_string())
    ok = tab.loc["C", "mean"] > tab.loc["I", "mean"] > tab.loc["IN", "mean"]
    print("C > I > IN:", "yes" if ok else "NO - stop and check the model")
    gaps = m["gap"].dropna()
    print(f"\npass-only decision gap at release: n={len(gaps)}, mean {gaps.mean():.3f}, median {gaps.median():.3f}, "
          f"QB picked the model's best option on {(gaps < 1e-9).mean():.1%}")
    path = derived_dir() / "pass_values_release.parquet"
    df.to_parquet(path, index=False)
    print(f"wrote {path}")

    pa = load_play(2021090900, 1687)
    arr = arrival_for_play(pa, prm)
    pv = pass_values(pa, arr, ep)
    i = pa.idx(38)
    jersey = dict(zip(pa.off_ids.tolist(), pa.off_jersey.tolist()))
    print(f"\nDemo 2021090900/1687 at frame 38 (release): EP now {pv.ep_now:.2f}, incomplete {pv.value_incomplete:+.2f}")
    print("rcv   pCatch  pInt   gain  1st  TD   v_complete  v_int   EV")
    for k in np.argsort(-pv.ev[i]):
        r = int(arr.receiver_ids[k])
        print(f"#{jersey[r]:<4} {arr.p_catch[i, k]:5.2f}  {arr.p_int[i, k]:5.3f}  {pv.gain[i, k]:5.1f}  "
              f"{'Y' if pv.first_down[i, k] else '-'}    {'Y' if pv.touchdown[i, k] else '-'}    "
              f"{pv.value_complete[i, k]:+5.2f}      {pv.value_interception[i, k]:+5.2f}  {pv.ev[i, k]:+5.2f}")


if __name__ == "__main__":
    main()
