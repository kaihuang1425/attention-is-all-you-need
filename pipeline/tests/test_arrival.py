from __future__ import annotations

import numpy as np
import pytest

from pipeline import arrival as AR

P = AR.ArrivalParams()


def _one(qb, rec, rec_v, defs, def_v, vmax=None, **kw):
    qb_xy = np.array([qb], dtype=float)
    rec_xy = np.array([[rec]], dtype=float)
    rec_v = np.array([[rec_v]], dtype=float)
    def_xy = np.array([defs], dtype=float)
    def_v = np.array([def_v], dtype=float)
    vmax = np.full(len(defs), 7.0) if vmax is None else np.asarray(vmax, dtype=float)
    return AR.arrival_core(qb_xy, rec_xy, rec_v, def_xy, def_v, vmax, P, **kw)


def test_open_receiver():
    # Receiver 10 yd downfield running away from the QB; every defender is 30+ yd away.
    out = _one((20, 26.65), (30, 26.65), (5, 0), [(70, 5), (70, 48), (65, 26)], [(0, 0)] * 3)
    assert out["margin"][0, 0] > 1.5
    assert out["p_catch"][0, 0] > 0.95


def test_covered_receiver():
    # A defender 1 yd away moving the same way as the receiver gets there first.
    out = _one((20, 26.65), (35, 26.65), (7, 0), [(36, 26.65)], [(7, 0)])
    assert out["margin"][0, 0] < 0


def test_faster_ball_shortens_flight():
    rng = np.random.default_rng(1)
    qb = np.tile([[20.0, 26.65]], (4, 1))
    rec = rng.uniform([25, 5], [60, 48], size=(4, 5, 2))
    rv = rng.uniform(-6, 6, size=(4, 5, 2))
    dxy = rng.uniform([25, 5], [60, 48], size=(4, 11, 2))
    dv = rng.uniform(-6, 6, size=(4, 11, 2))
    vmax = np.full(11, 8.0)
    slow = AR.arrival_core(qb, rec, rv, dxy, dv, vmax, P, v_ball=20.0)
    fast = AR.arrival_core(qb, rec, rv, dxy, dv, vmax, P, v_ball=40.0)
    assert np.all(fast["t_ball"] < slow["t_ball"])


def test_catch_point_stays_in_field():
    out = _one((20, 26.65), (100, 52.0), (8, 6), [(60, 10)], [(0, 0)])
    x, y = out["p"][0, 0]
    assert x <= P.x_max and P.y_min <= y <= P.y_max


def test_reaction_time_and_momentum():
    # Same spot, one defender sprinting toward the catch point, one sprinting away.
    toward = _one((20, 26.65), (40, 26.65), (0, 0), [(30, 26.65)], [(7, 0)])
    away = _one((20, 26.65), (40, 26.65), (0, 0), [(30, 26.65)], [(-7, 0)])
    assert toward["t_def"][0, 0] < away["t_def"][0, 0]
    # Never faster than a straight line at top speed.
    assert toward["t_def"][0, 0] >= 10.0 / 7.0 - 1e-9


class _FakePlay:
    """Minimal PlayArrays stand-in for the legality rule."""

    def __init__(self, qb_x):
        self.frames = np.arange(1, len(qb_x) + 1)
        self.snap_frame, self.end_frame, self.los_x = 1, len(qb_x), 50.0
        self.qb_xy = np.stack([np.asarray(qb_x, float), np.full(len(qb_x), 26.65)], axis=1)


def test_forward_pass_removed_past_los():
    legal = AR.forward_pass_legal(_FakePlay([45, 48, 50, 50.5, 53]))
    assert legal.tolist() == [True, True, True, False, False]


@pytest.mark.data
def test_demo_play_ranges():
    from pipeline.playdata import load_play

    pa = load_play(2021090900, 1687)
    arr = AR.arrival_for_play(pa)
    i = pa.idx(38)
    assert arr.legal[i]
    assert np.all((arr.t_ball[i] > 0.3) & (arr.t_ball[i] < 2.5))
    assert np.all((arr.margin[i] > -1.5) & (arr.margin[i] < 2.0))
    assert np.isnan(arr.margin[pa.idx(3)]).all(), "no options before the snap"
