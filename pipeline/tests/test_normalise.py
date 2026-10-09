from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pipeline import load
from pipeline import normalise as N

# ------------------------------------------------------------------------------------------
# Unit tests (no data needed)
# ------------------------------------------------------------------------------------------


def _rows(direction: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "gameId": [1, 1],
            "playId": [1, 1],
            "nflId": [10, 20],
            "frameId": [1, 1],
            "playDirection": [direction, direction],
            "x": [30.0, 100.0],
            "y": [10.0, 50.0],
            "s": [5.0, 0.0],
            "o": [90.0, 350.0],
            "dir": [90.0, 270.0],
        }
    )


def test_right_plays_unchanged_and_velocity():
    out = N.normalise_tracking(_rows("right"))
    assert out["x"].tolist() == [30.0, 100.0]
    assert out["y"].tolist() == [10.0, 50.0]
    # dir 90 = +x in this convention (unit vector = (sin, cos))
    assert out["vx"].iloc[0] == pytest.approx(5.0, abs=1e-5)
    assert out["vy"].iloc[0] == pytest.approx(0.0, abs=1e-5)


def test_left_plays_flip():
    out = N.normalise_tracking(_rows("left"))
    assert out["x"].tolist() == pytest.approx([90.0, 20.0])
    assert out["y"].tolist() == pytest.approx([43.3, 3.3], abs=1e-4)
    assert out["o"].tolist() == pytest.approx([270.0, 170.0])
    assert out["dir"].tolist() == pytest.approx([270.0, 90.0])
    # A left-moving player running toward -x (dir 270 raw) runs toward +x after the flip.
    raw = _rows("left").assign(dir=[270.0, 270.0])
    assert N.normalise_tracking(raw)["vx"].iloc[0] == pytest.approx(5.0, abs=1e-5)


def test_los_and_first_down_columns():
    play = {"absoluteYardlineNumber": 85.0, "yardsToGo": 8, "playDirection": "left"}
    out = N.normalise_tracking(_rows("left"), play)
    assert out["los_x"].iloc[0] == pytest.approx(35.0)
    assert out["firstDown_x"].iloc[0] == pytest.approx(43.0)


@pytest.mark.parametrize(
    "x, label",
    [(85.0, "TB 25"), (93.0, "TB 17"), (60.0, "50"), (35.0, "DAL 25"), (110.0, "TB goal line"), (59.6, "50")],
)
def test_yard_label(x, label):
    assert N.yard_label(x, "DAL", "TB") == label


def test_canonical_events_merge_duplicates():
    ball = pd.DataFrame(
        {
            "gameId": [1] * 6,
            "playId": [7] * 6,
            "frameId": [6, 38, 58, 146, 172, 173],
            "event": ["autoevent_ballsnap", "line_set", "line_set", "ball_snap", "autoevent_passforward", "pass_forward"],
        }
    )
    ev = N.canonical_events(ball)
    snaps = ev[ev["type"] == "ball_snap"]
    throws = ev[ev["type"] == "pass_forward"]
    assert len(snaps) == 1 and int(snaps["frameId"].iloc[0]) == 146
    assert int(snaps["autoFrame"].iloc[0]) == 6
    assert len(throws) == 1 and int(throws["frameId"].iloc[0]) == 173
    assert ev[ev["type"] == "line_set"]["frameId"].tolist() == [38, 58]


def test_canonical_events_auto_fallback():
    ball = pd.DataFrame({"gameId": [1, 1], "playId": [7, 7], "frameId": [3, 30], "event": ["autoevent_ballsnap", "qb_sack"]})
    ev = N.canonical_events(ball)
    snap = ev[ev["type"] == "ball_snap"].iloc[0]
    assert int(snap["frameId"]) == 3 and bool(snap["fromAuto"]) and snap["rawEvent"] == "autoevent_ballsnap"


# ------------------------------------------------------------------------------------------
# Data tests
# ------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def play_index():
    # Build the index for the three demo games only (fast); the full index is built by
    # `python -m pipeline.normalise`.
    return N.build_play_index([2021090900, 2021091202], verbose=False)


def _row(idx: pd.DataFrame, game_id: int, play_id: int) -> pd.Series:
    sel = idx[(idx["gameId"] == game_id) & (idx["playId"] == play_id)]
    assert len(sel) == 1
    return sel.iloc[0]


@pytest.mark.data
def test_demo_play_1687(play_index):
    r = _row(play_index, 2021090900, 1687)
    assert r["snapFrame"] == 6
    assert r["endFrame"] == 38
    assert r["endType"] == "throw"
    assert r["timeToThrow"] == pytest.approx(3.2)
    assert r["losLabel"] == "TB 25"
    assert r["firstDownLabel"] == "TB 17"
    assert r["formation"] == "2x2"
    assert r["qbName"] == "Dak Prescott"
    assert (r["possessionTeam"], r["defensiveTeam"]) == ("DAL", "TB")
    assert (r["down"], r["yardsToGo"], r["quarter"], r["gameClock"]) == (2, 8, 2, "05:43")


@pytest.mark.data
def test_demo_play_3406_manual_snap_wins(play_index):
    r = _row(play_index, 2021090900, 3406)
    assert r["snapFrame"] == 146, "the bogus autoevent_ballsnap at frame 6 must not win"
    assert r["snapAutoFrame"] == 6
    assert r["endFrame"] == 173
    assert r["timeToThrow"] == pytest.approx(2.7)


@pytest.mark.data
def test_demo_play_210_sack(play_index):
    r = _row(play_index, 2021091202, 210)
    assert r["snapFrame"] == 6
    assert r["endFrame"] == 34
    assert r["endType"] == "sack"


@pytest.mark.data
def test_offense_behind_los_at_snap(sample_tracking, plays):
    ball = load.ball_rows(sample_tracking)
    fidx = N.play_frame_index(ball)
    fidx = fidx[fidx["snapSource"].isin(["manual", "auto"])]
    plays_los = plays[["gameId", "playId", "absoluteYardlineNumber", "possessionTeam"]]
    fidx = fidx.merge(plays_los, on=N.KEYS)
    fidx["los_x"] = np.where(fidx["playDirection"] == "left", N.FIELD_LENGTH - fidx["absoluteYardlineNumber"], fidx["absoluteYardlineNumber"])

    at_snap = load.player_rows(sample_tracking).merge(
        fidx[N.KEYS + ["snapFrame", "los_x", "possessionTeam"]].rename(columns={"snapFrame": "frameId"}), on=N.KEYS + ["frameId"]
    )
    offense = N.normalise_tracking(at_snap[at_snap["team"].astype(str) == at_snap["possessionTeam"]])
    behind = offense["los_x"] - offense["x"]
    print(f"\noffensive players at the snap: {len(offense)} on {offense.groupby(N.KEYS).ngroups} plays; "
          f"max yards behind LOS {behind.max():.1f}; max yards past LOS {(-behind).max():.1f}")
    assert behind.max() <= 15.0, f"measured {behind.max():.1f} yd behind the LOS"
