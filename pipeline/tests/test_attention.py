from __future__ import annotations

import numpy as np
import pytest

from pipeline import attention as AT

P = AT.AttentionParams(sigma=4.0, k=1.0, temperature=1.0, unattached_score=-3.0)


def test_rows_sum_to_one_and_unattached_column():
    rng = np.random.default_rng(0)
    def_xy = rng.uniform(0, 50, size=(5, 11, 2))
    off_xy = rng.uniform(0, 50, size=(5, 10, 2))
    o = rng.uniform(0, 360, size=(5, 11))
    dist, cos = AT.geometry(def_xy, o, off_xy)
    w = AT.attention_from_geometry(dist, cos, P)
    assert w.shape == (5, 11, 11)
    assert np.allclose(w.sum(axis=-1), 1.0)


def test_close_and_facing_wins():
    # Defender at origin facing +x (o = 90). Receiver A 2 yd ahead, receiver B 2 yd behind.
    def_xy = np.zeros((1, 1, 2))
    off_xy = np.array([[[2.0, 0.0], [-2.0, 0.0]]])
    dist, cos = AT.geometry(def_xy, np.array([[90.0]]), off_xy)
    assert cos[0, 0].tolist() == pytest.approx([1.0, -1.0])
    w = AT.attention_from_geometry(dist, cos, P)[0, 0]
    assert w[0] > w[1] > 0


def test_far_defender_attends_to_space():
    def_xy = np.zeros((1, 1, 2))
    off_xy = np.full((1, 3, 2), 40.0)
    dist, cos = AT.geometry(def_xy, np.array([[0.0]]), off_xy)
    w = AT.attention_from_geometry(dist, cos, P)[0, 0]
    assert w[-1] > 0.9


def test_orientation_smoothing_wraps_around_north():
    o = np.array([[350.0], [10.0], [350.0]])
    s = AT.smooth_orientation(o, 3)
    # Circular mean of 350/10 is ~0 deg, not 180 deg.
    assert min(s[1, 0], 360 - s[1, 0]) < 5.0


def test_smoothing_ignores_nan():
    o = np.array([[90.0], [np.nan], [90.0]])
    s = AT.smooth_orientation(o, 3)
    assert s[1, 0] == pytest.approx(90.0)


@pytest.mark.data
def test_demo_play_sanity():
    from pipeline.playdata import load_play

    pa = load_play(2021090900, 1687)
    att = AT.attention_for_play(pa)
    assert np.allclose(att.weights.sum(axis=-1), 1.0)
    J = {int(j): c for c, j in enumerate(pa.off_jersey)}
    D = {int(j): r for r, j in enumerate(pa.def_jersey)}
    rel = pa.idx(pa.end_frame)
    # #35 Dean (deep third on the offense's left) is on #88 Lamb at the throw.
    assert att.weights[rel, D[35], J[88]] > 0.5
    # Rushers #92 and #56 were double-teamed: their top two targets in the first 1.0 s are linemen.
    i0 = pa.idx(pa.snap_frame)
    linemen = {77, 52, 63, 66, 71}
    for rusher in (92, 56):
        mean = att.edges[i0 : i0 + 11, D[rusher]].mean(axis=0)
        top2 = {int(pa.off_jersey[c]) for c in np.argsort(mean)[::-1][:2]}
        assert top2 <= linemen, f"#{rusher} top targets {top2}"
