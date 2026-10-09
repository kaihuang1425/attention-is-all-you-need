"""Export release-frame validation data for the Aggregate validation tab.

Run after normalise and targets:
    python -m pipeline.aggregate

The completion model was trained on weeks 1-6. Calibration is evaluated on
weeks 7-8 only. Decision gaps compare pass targets with other pass targets;
no scramble, throw-away, or hold value is inferred here.
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from . import load, normalise as N
from .arrival import ArrivalParams, arrival_for_play
from .attention import AttentionParams, attention_for_play
from .completion import DEFAULT_MODEL, play_completion
from .config import export_dir
from .playdata import iter_play_arrays
from .targets import read_targets
from .values import load_ep_model, pass_values


def build_aggregate() -> dict:
    index = N.read_play_index()
    targets = read_targets().set_index(N.KEYS)
    pff = load.load_pff()
    blockers = pff[pff["pff_nflIdBlockedPlayer"].notna()]
    blocks_by_play = {key: group for key, group in blockers.groupby(N.KEYS)}
    ep = load_ep_model()
    arrival_params = ArrivalParams.from_config()
    attention_params = AttentionParams.from_config()
    rows: list[dict] = []
    concentration: dict[str, list[float]] = {"Man": [], "Zone": []}
    block_hits = block_total = processed = eligible = 0
    started = time.perf_counter()

    for pa in iter_play_arrays(index=index, pff=pff):
        processed += 1
        if processed % 1000 == 0:
            print(f"  {processed} plays in {time.perf_counter() - started:.0f}s", flush=True)
        if pa.end_type != "throw":
            continue
        key = (pa.gameId, pa.playId)
        if key not in targets.index:
            continue
        target = targets.loc[key]
        if target["passResult"] not in ("C", "I", "IN") or pd.isna(target["targetNflId"]):
            continue
        target_id = int(target["targetNflId"])
        arr = arrival_for_play(pa, arrival_params)
        i = pa.idx(pa.end_frame)
        matches = np.flatnonzero(arr.receiver_ids == target_id)
        if not arr.legal[i] or not len(matches):
            continue
        eligible += 1
        k = int(matches[0])
        comp = play_completion(pa, DEFAULT_MODEL)
        # Match the play export: completion model pCatch, arrival-based INT closeness.
        p_catch = np.where(arr.legal[:, None], comp.p_complete, np.nan)
        arr.p_int = arrival_params.c_int * (1.0 - p_catch) * arr.closeness
        pv = pass_values(pa, arr, ep, p_catch=p_catch)
        values = pv.ev[i]
        if not np.isfinite(values[k]) or not np.isfinite(p_catch[i, k]):
            continue
        best_k = int(np.nanargmax(values))
        att = attention_for_play(pa, attention_params)
        coverage = str(pa.meta.get("pff_passCoverageType") or "Unknown")
        if coverage in concentration:
            cov = pa.def_roles == load.ROLE_COVERAGE
            concentration[coverage].extend(np.max(att.weights[i, cov, :-1], axis=1).tolist())

        group = blocks_by_play.get(key)
        if group is not None:
            offense = {int(nid): j for j, nid in enumerate(pa.off_ids)}
            defense = {int(nid): j for j, nid in enumerate(pa.def_ids)}
            start = pa.idx(pa.snap_frame)
            stop = min(i, start + 10) + 1
            mean = att.weights[start:stop, :, :-1].mean(axis=0)
            for rusher_id, assigned in group.groupby("pff_nflIdBlockedPlayer"):
                r = defense.get(int(rusher_id))
                accepted = {offense[int(nid)] for nid in assigned["nflId"] if int(nid) in offense}
                if r is not None and accepted:
                    block_total += 1
                    block_hits += int(int(np.argmax(mean[r])) in accepted)

        row = {
            "gameId": pa.gameId,
            "playId": pa.playId,
            "week": int(pa.meta["week"]),
            "qb": str(pa.meta["qbName"]),
            "coverage": str(pa.meta.get("pff_passCoverage") or "Unknown"),
            "coverageType": coverage,
            "timeToThrow": round(float(pa.meta["timeToThrow"]), 1),
            "gap": round(max(0.0, float(values[best_k] - values[k])), 3),
            "pCatch": round(float(p_catch[i, k]), 4),
            "complete": target["passResult"] == "C",
            "samePick": best_k == k,
            "bestX": round(float(arr.p[i, best_k, 0] - pa.los_x), 1),
            "bestY": round(float(arr.p[i, best_k, 1]), 1),
            "targetX": round(float(arr.p[i, k, 0] - pa.los_x), 1),
            "targetY": round(float(arr.p[i, k, 1]), 1),
        }
        rows.append(row)

    bins = np.linspace(0, 1, 21)
    return {
        "version": 1,
        "scope": "2021 regional event data, weeks 1-8; targeted throws with a matched route runner and legal forward pass at release",
        "model": f"{DEFAULT_MODEL.source}; {ep.version} EPA; pass options only",
        "indexedPlays": len(index),
        "replayablePlays": int(index["replayable"].sum()),
        "processedPlays": processed,
        "eligibleThrows": eligible,
        "rows": rows,
        "attention": {
            "bins": bins.round(2).tolist(),
            "Man": np.histogram(concentration["Man"], bins=bins)[0].tolist(),
            "Zone": np.histogram(concentration["Zone"], bins=bins)[0].tolist(),
            "manN": len(concentration["Man"]),
            "zoneN": len(concentration["Zone"]),
            "manMedian": round(float(np.median(concentration["Man"])), 3),
            "zoneMedian": round(float(np.median(concentration["Zone"])), 3),
            "blockHits": block_hits,
            "blockTotal": block_total,
        },
    }


def main() -> None:
    data = build_aggregate()
    path = export_dir() / "aggregate.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    print(f"wrote {path}: {len(data['rows'])} targeted throws")


if __name__ == "__main__":
    main()
