from __future__ import annotations

import json

import numpy as np
import pytest

from pipeline import completion as C



def test_lane_distance_ignores_ends_of_the_line():
    qb = np.array([0.0, 0.0])
    rec = np.array([20.0, 0.0])
    defs = np.array([[10.0, 1.0], [1.0, 0.5], [19.0, 0.5]])  # middle, at the QB, at the receiver
    d = C.lane_distance(defs, qb, rec)
    assert d[0] == pytest.approx(1.0)
    assert np.isinf(d[1]) and np.isinf(d[2])


def test_completion_model_prefers_open_receivers():
    rec = np.array([[30.0, 26.0], [30.0, 10.0]])
    cov = np.array([[30.5, 26.0]])
    allw = cov
    met = C.frame_metrics(rec, cov, allw, np.array([20.0, 26.0]), 25.0, 10.0)
    p = C.completion_prob(met)
    assert p[1] > p[0]


@pytest.fixture(scope="module")
def demo_doc(tmp_path_factory):
    from pipeline import export

    out = tmp_path_factory.mktemp("export")
    export.main(["--plays", "2021090900:1687", "2021090900:3406", "--out", str(out)])
    return {p.stem: json.loads(p.read_text()) for p in (out / "plays").glob("*.json")}, out


@pytest.mark.data
def test_export_demo_plays(demo_doc):
    docs, out = demo_doc
    d = docs["2021090900_1687"]
    sides = [p["side"] for p in d["players"]]
    assert sides.count("offense") == 11 and sides.count("defense") == 11
    snaps = [f for f in d["flags"] if f["type"] == "ball_snap"]
    throws = [f for f in d["flags"] if f["type"] == "pass_forward"]
    assert [f["frameId"] for f in snaps] == [6]
    assert [f["frameId"] for f in throws] == [38]
    last = d["meta"]["lastFrame"]
    assert all(1 <= f["frameId"] <= last for f in d["flags"])
    assert d["result"]["targetId"] == 52425
    assert (out / "plays" / "2021090900_1687.json").stat().st_size < 400_000

    d2 = docs["2021090900_3406"]
    assert [f["frameId"] for f in d2["flags"] if f["type"] == "ball_snap"] == [146]
    assert [f["frameId"] for f in d2["flags"] if f["type"] == "line_set"] == [38, 58]
    assert [f["frameId"] for f in d2["flags"] if f["type"] == "pass_forward"] == [173]
    idx = json.loads((out / "index.json").read_text())
    assert len(idx["plays"]) == 2


@pytest.mark.data
def test_pcatch_matches_completion_model_and_legality(demo_doc):
    docs, _ = demo_doc
    d = docs["2021090900_1687"]
    m = d["model"]
    pre = d["frames"]["frameId"].index(5)
    assert all(v is None for v in m["pCatch"][pre]), "no options before the snap"
    i = d["frames"]["frameId"].index(38)
    assert all(v is not None and 0 < v < 1 for v in m["pCatch"][i])
    # pCatch + pInt never exceeds 1
    for pc, pi in zip(m["pCatch"][i], m["pInt"][i]):
        assert pc + pi <= 1.0
