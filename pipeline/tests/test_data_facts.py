"""Facts about the raw data that every later stage relies on (docs/01_DATA_SPEC.md).

Each test prints the measured value (run `pytest -s` to see them). A failing test reports the
measured value in its message. Thresholds come from the spec; don't loosen one without saying why.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from pipeline import load

pytestmark = pytest.mark.data

END_EVENTS_THROW = ("pass_forward", "autoevent_passforward")
END_EVENTS_OTHER = ("qb_sack", "qb_strip_sack", "run")


def _first_frame(ball: pd.DataFrame, event: str) -> pd.Series:
    rows = ball[ball["event"] == event]
    return rows.groupby(["gameId", "playId"], observed=True)["frameId"].min()


def test_games(games):
    seasons = sorted(games["season"].unique().tolist())
    weeks = sorted(int(w) for w in games["week"].unique())
    print(f"\ngames={len(games)} seasons={seasons} weeks={weeks}")
    assert len(games) == 122, f"measured {len(games)} games"
    assert seasons == [2021], f"measured seasons {seasons}"
    assert weeks == list(range(1, 9)), f"measured weeks {weeks}"


def test_plays_and_results(plays):
    counts = plays["passResult"].value_counts().to_dict()
    print(f"\nplays={len(plays)} passResult={counts}")
    assert len(plays) == 8557, f"measured {len(plays)} plays"
    assert counts == {"C": 4620, "I": 2755, "S": 543, "R": 449, "IN": 190}, f"measured {counts}"


def test_pff_roles(pff):
    counts = pff["pff_role"].value_counts().to_dict()
    print(f"\npff_role={counts}")
    assert set(counts) == set(load.PFF_ROLES), f"measured roles {sorted(counts)}"
    assert counts[load.ROLE_PASSER] == 8557


def test_tracking_load_speed():
    gid = load.tracking_game_ids()[0]
    start = time.perf_counter()
    df = load.load_tracking(gid)
    elapsed = time.perf_counter() - start
    print(f"\nload_tracking({gid}) {elapsed:.2f}s rows={len(df)}")
    assert elapsed < 3.0, f"measured {elapsed:.2f}s"
    # "None" must survive as a string, and ball rows carry NA nflId.
    assert (df["event"] == load.NO_EVENT).any()
    assert df["event"].isna().sum() == 0
    ball = load.ball_rows(df)
    assert ball["nflId"].isna().all()


def test_eleven_per_side(sample_tracking):
    players = load.player_rows(sample_tracking)
    per_frame = players.groupby(["gameId", "playId", "frameId", "team"], observed=True).size()
    bad = per_frame[per_frame != 11]
    n_frames = per_frame.index.droplevel("team").nunique()
    print(f"\nframes checked={n_frames} team-frames not equal to 11: {len(bad)}")
    if len(bad):
        print(bad.head(20))
    assert len(bad) == 0, f"measured {len(bad)} team-frames with a count other than 11"


def test_los_matches_ball_at_snap(sample_tracking, plays):
    ball = load.ball_rows(sample_tracking)
    snap = _first_frame(ball, "ball_snap").rename("snapFrame").reset_index()
    at_snap = ball.merge(snap, on=["gameId", "playId"])
    at_snap = at_snap[at_snap["frameId"] == at_snap["snapFrame"]]
    merged = at_snap.merge(plays[["gameId", "playId", "absoluteYardlineNumber"]], on=["gameId", "playId"])
    diff = (merged["x"].astype(float) - merged["absoluteYardlineNumber"]).abs()
    share = float((diff <= 2.5).mean())
    within_15 = float((diff <= 1.5).mean())
    print(f"\nplays with a manual snap={len(merged)} |ball x - LOS| <= 2.5 yd: {share:.1%} (<= 1.5 yd: {within_15:.1%})")
    assert share >= 0.98, f"measured {share:.2%} within 2.5 yd"


def test_tracking_ends_after_end_event(sample_tracking):
    """Tracking stops exactly 5 frames after the *earliest* end event (manual or auto).

    The P01 prompt asked for 4-6 frames after the manual-first end event on >= 99% of plays.
    Measured on all 122 games that holds on only 96.6%: 284 plays have a 3-frame tail because
    autoevent_passforward fires 2 frames before pass_forward. Measured from the earliest end
    event the tail is exactly 5 frames on 99.98% (8,555 of 8,557). So this test asserts the
    stronger, correct fact and prints the manual-first numbers for reference.
    """
    ball = load.ball_rows(sample_tracking)
    last = ball.groupby(["gameId", "playId"], observed=True)["frameId"].max()

    manual = _first_frame(ball, "pass_forward")
    auto = _first_frame(ball, "autoevent_passforward")
    others = [_first_frame(ball, e) for e in END_EVENTS_OTHER]
    earliest_end = pd.concat([manual, auto, *others], axis=1).min(axis=1)
    manual_first_end = pd.concat([manual.combine_first(auto), *others], axis=1).min(axis=1)

    gap = (last.reindex(earliest_end.index) - earliest_end).astype(int)
    gap_manual = (last.reindex(manual_first_end.index) - manual_first_end).astype(int)
    share = float((gap == 5).mean())
    share_manual = float(gap_manual.between(4, 6).mean())
    n_no_end = int(last.index.difference(earliest_end.index).size)
    print(f"\nplays with an end event={len(earliest_end)} (without={n_no_end})"
          f"\n  from earliest end event: exactly 5 frames on {share:.2%}; {gap.value_counts().sort_index().to_dict()}"
          f"\n  from manual-first end event: 4-6 frames on {share_manual:.2%}; "
          f"{gap_manual.value_counts().sort_index().to_dict()}")
    assert n_no_end == 0, f"measured {n_no_end} plays without an end event"
    assert share >= 0.99, f"measured {share:.2%} of plays end exactly 5 frames after the earliest end event"


def test_angle_convention(sample_tracking):
    df = load.player_rows(sample_tracking).sort_values(["gameId", "playId", "nflId", "frameId"])
    same = (
        (df["gameId"].shift(-1) == df["gameId"])
        & (df["playId"].shift(-1) == df["playId"])
        & (df["nflId"].shift(-1) == df["nflId"])
        & (df["frameId"].shift(-1) == df["frameId"] + 1)
    ).to_numpy(dtype=bool)
    dx = (df["x"].shift(-1) - df["x"]).to_numpy(dtype=float)
    dy = (df["y"].shift(-1) - df["y"]).to_numpy(dtype=float)
    rad = np.deg2rad(df["dir"].to_numpy(dtype=float))
    fast = same & (df["s"].to_numpy(dtype=float) > 4.0) & np.isfinite(rad)
    sx = np.sign(np.sin(rad[fast])) == np.sign(dx[fast])
    sy = np.sign(np.cos(rad[fast])) == np.sign(dy[fast])
    print(f"\nfast player frames={int(fast.sum())} sign agreement x={sx.mean():.2%} y={sy.mean():.2%}")
    assert sx.mean() >= 0.97, f"measured x sign agreement {sx.mean():.2%}"
