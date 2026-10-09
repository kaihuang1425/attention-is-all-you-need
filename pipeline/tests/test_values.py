from __future__ import annotations

import numpy as np
import pytest

from pipeline import values as V

EP1 = V.EPModel("v1-closed-form")


def test_ep_v1_shape_and_order():
    # Closer to the goal line is worth more; later downs are worth less.
    assert EP1(1, 10, 25) > EP1(1, 10, 50) > EP1(1, 10, 75)
    assert EP1(1, 10, 50) > EP1(2, 10, 50) > EP1(3, 10, 50) > EP1(4, 10, 50)
    # Reference points (nflverse 2021 means for 1st & 10): own 25 ~ 1.0, midfield ~ 2.5, opp 25 ~ 4.1.
    assert EP1(1, 10, 75) == pytest.approx(1.0, abs=0.3)
    assert EP1(1, 10, 50) == pytest.approx(2.5, abs=0.3)
    assert EP1(1, 10, 25) == pytest.approx(4.1, abs=0.3)


def test_touchdown_and_safety():
    assert V.ep_after_gain(EP1, 2, 8, 25, np.array([30.0]))[0] == V.TD_POINTS
    assert V.ep_after_gain(EP1, 2, 8, 98, np.array([-3.0]))[0] == V.SAFETY_POINTS


def test_first_down_vs_short():
    first = V.ep_after_gain(EP1, 3, 5, 50, np.array([6.0]))[0]
    short = V.ep_after_gain(EP1, 3, 5, 50, np.array([4.0]))[0]
    assert first == pytest.approx(float(EP1(1, 10, 44)))
    assert short == pytest.approx(float(EP1(4, 1, 46)))
    assert first > short


def test_fourth_down_turnover():
    # 4th & 5 at midfield, catch for 2: opponent ball at their own 48 (yardline_100 = 52).
    v = V.ep_after_gain(EP1, 4, 5, 50, np.array([2.0]))[0]
    assert v == pytest.approx(-float(EP1(1, 10, 52)))
    assert V.ep_after_incomplete(EP1, 4, 5, 50) == pytest.approx(-float(EP1(1, 10, 50)))


def test_interception_and_touchback():
    # Pick at normalised x = 40 (offense's own 30): opponent needs 30 yards.
    assert V.ep_after_interception(EP1, np.array([40.0]))[0] == pytest.approx(-float(EP1(1, 10, 30)))
    # Pick in the end zone the offense attacks: touchback, opponent at its own 20.
    assert V.ep_after_interception(EP1, np.array([115.0]))[0] == pytest.approx(-float(EP1(1, 10, 80)))


def test_v2_table_close_to_v1():
    import pandas as pd

    rng = np.random.default_rng(0)
    n = 4000
    down = rng.integers(1, 5, n)
    ytg = rng.integers(1, 15, n)
    yl = rng.integers(1, 100, n)
    pbp = pd.DataFrame({"season_type": "REG", "down": down, "ydstogo": ytg, "yardline_100": yl, "ep": V.ep_v1(down, ytg, yl)})
    table = V.fit_ep_v2(pbp)
    m2 = V.EPModel("v2", table)
    assert float(m2(1, 10, 50)) == pytest.approx(float(EP1(1, 10, 50)), abs=0.1)


def test_decision_gap():
    g = V.decision_gap({"pass:1": 0.4, "pass:2": 0.1, "scramble": float("nan")}, "pass:2", 38)
    assert g.best == "pass:1"
    assert g.gap == pytest.approx(0.3)
    assert V.decision_gap({"pass:1": 0.4}, "pass:1", 38).gap == 0.0
    assert V.chosen_option("S", None) == "hold"
    assert V.chosen_option("R", 5) == "scramble"
    assert V.chosen_option("I", float("nan")) is None


@pytest.mark.data
def test_demo_play_values():
    from pipeline.arrival import arrival_for_play
    from pipeline.playdata import load_play

    pa = load_play(2021090900, 1687)
    arr = arrival_for_play(pa)
    pv = V.pass_values(pa, arr, V.load_ep_model())
    i = pa.idx(38)
    assert np.isfinite(pv.ev[i]).all()
    # Every pass option's EV lies between the interception and completion values.
    lo = np.minimum.reduce([pv.value_interception[i], pv.value_complete[i], np.full(len(pv.ev[i]), pv.value_incomplete)])
    hi = np.maximum.reduce([pv.value_interception[i], pv.value_complete[i], np.full(len(pv.ev[i]), pv.value_incomplete)])
    assert np.all((pv.ev[i] >= lo - 1e-9) & (pv.ev[i] <= hi + 1e-9))
