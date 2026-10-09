"""Validate and tune the soft attention model (model spec §2, prompt P04).

1. Man vs Zone: each coverage defender's maximum weight on an offensive player at the throw.
   Man coverage should be clearly more concentrated than Zone.
2. Blocks: for each blocker with a pff_nflIdBlockedPlayer, is that rusher's top attention target
   over the first 1.0 s after the snap the blocker (or another blocker who also lists him)?
3. Grid search sigma, k, T on weeks 1-6 to maximise (Man median - Zone median) + block
   agreement; report the chosen values on weeks 7-8 and save them to config.yaml.

Run: python -m pipeline.validate_attention [--no-save] [--games ...]
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import time
from dataclasses import asdict

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

from . import load
from . import normalise as N
from .attention import AttentionParams, attention_for_play, attention_from_geometry, format_matrix, geometry, smooth_orientation
from .config import CONFIG_PATH, derived_dir, load_config
from .playdata import iter_play_arrays, load_play

GRID = {"sigma": [3.0, 4.0, 5.0, 6.0], "k": [0.5, 1.0, 1.5], "temperature": [0.75, 1.0, 1.5]}
WINDOW_FRAMES = 10  # first 1.0 s after the snap: frames snap .. snap + 10


def collect(game_ids: list[int] | None = None, verbose: bool = True) -> dict[str, np.ndarray]:
    """Geometry needed by both checks, for every replayable play, computed once."""
    index = N.read_play_index()
    pff = load.load_pff()
    blocked = pff[pff["pff_nflIdBlockedPlayer"].notna()][N.KEYS + ["nflId", "pff_nflIdBlockedPlayer"]]
    blocks_by_play = {k: g for k, g in blocked.groupby(N.KEYS)}
    week_of = index.set_index(N.KEYS)["week"].to_dict()
    cov_of = index.set_index(N.KEYS)["pff_passCoverageType"].to_dict()

    cov_dist, cov_cos, cov_week, cov_type = [], [], [], []
    blk_dist, blk_cos, blk_valid, blk_accept, blk_week = [], [], [], [], []
    start = time.perf_counter()
    n = 0
    for pa in iter_play_arrays(game_ids, index=index, pff=pff):
        n += 1
        key = (pa.gameId, pa.playId)
        o = smooth_orientation(pa.def_o, 3)
        dist, cos = geometry(pa.def_xy, o, pa.off_xy)
        week = int(week_of[key])

        # 1. coverage defenders at the throw
        ctype = cov_of.get(key)
        if pa.end_type == "throw" and ctype in ("Man", "Zone"):
            i = pa.idx(pa.end_frame)
            rows = np.flatnonzero(pa.def_roles == load.ROLE_COVERAGE)
            cov_dist.append(dist[i, rows])
            cov_cos.append(cos[i, rows])
            cov_week.append(np.full(len(rows), week))
            cov_type.append(np.full(len(rows), ctype))

        # 2. blocks in the first 1.0 s after the snap
        b = blocks_by_play.get(key)
        if b is not None:
            i0 = pa.idx(pa.snap_frame)
            i1 = min(pa.idx(pa.end_frame), i0 + WINDOW_FRAMES)
            win = slice(i0, i1 + 1)
            col_of = {int(j): c for c, j in enumerate(pa.off_ids)}
            row_of = {int(d): r for r, d in enumerate(pa.def_ids)}
            for rusher, grp in b.groupby("pff_nflIdBlockedPlayer"):
                r = row_of.get(int(rusher))
                cols = [col_of[int(x)] for x in grp["nflId"] if int(x) in col_of]
                if r is None or not cols:
                    continue
                accept = np.zeros(len(pa.off_ids), dtype=bool)
                accept[cols] = True
                d = np.full((WINDOW_FRAMES + 1, len(pa.off_ids)), np.nan, dtype=np.float32)
                c = np.zeros_like(d)
                m = dist[win, r].shape[0]
                d[:m] = dist[win, r]
                c[:m] = cos[win, r]
                for _ in cols:  # one case per blocker
                    blk_dist.append(d)
                    blk_cos.append(c)
                    blk_valid.append(np.arange(WINDOW_FRAMES + 1) < m)
                    blk_accept.append(accept)
                    blk_week.append(week)
        if verbose and n % 1000 == 0:
            print(f"  {n} plays ({time.perf_counter() - start:.0f}s)")
    if verbose:
        print(f"collected {n} plays in {time.perf_counter() - start:.0f}s")
    return {
        "cov_dist": np.concatenate(cov_dist).astype(np.float32),
        "cov_cos": np.concatenate(cov_cos).astype(np.float32),
        "cov_week": np.concatenate(cov_week),
        "cov_type": np.concatenate(cov_type),
        "blk_dist": np.stack(blk_dist),
        "blk_cos": np.stack(blk_cos),
        "blk_valid": np.stack(blk_valid),
        "blk_accept": np.stack(blk_accept),
        "blk_week": np.array(blk_week),
    }


def evaluate(ds: dict[str, np.ndarray], p: AttentionParams, weeks: list[int], keep: bool = False) -> dict:
    cm = np.isin(ds["cov_week"], weeks)
    w = attention_from_geometry(ds["cov_dist"][cm], ds["cov_cos"][cm], p)
    max_w = w[:, :-1].max(axis=1)
    types = ds["cov_type"][cm]
    man, zone = max_w[types == "Man"], max_w[types == "Zone"]
    mw = mannwhitneyu(man, zone, alternative="greater")

    bm = np.isin(ds["blk_week"], weeks)
    d = np.nan_to_num(ds["blk_dist"][bm], nan=1e3)
    bw = attention_from_geometry(d, ds["blk_cos"][bm], p)[..., :-1]  # (P, 11, 10)
    valid = ds["blk_valid"][bm][..., None]
    mean_w = (bw * valid).sum(axis=1) / valid.sum(axis=1)
    top = mean_w.argmax(axis=1)
    agree = ds["blk_accept"][bm][np.arange(len(top)), top]

    out = {
        "man_median": float(np.median(man)),
        "zone_median": float(np.median(zone)),
        "man_n": int(len(man)),
        "zone_n": int(len(zone)),
        "mannwhitney_p": float(mw.pvalue),
        "block_agreement": float(agree.mean()),
        "block_n": int(len(agree)),
    }
    out["objective"] = out["man_median"] - out["zone_median"] + out["block_agreement"]
    if keep:
        out["_man"], out["_zone"] = man, zone
    return out


def grid_search(ds: dict, train_weeks: list[int]) -> tuple[AttentionParams, pd.DataFrame]:
    base = AttentionParams.from_config()
    rows = []
    for sigma, k, t in itertools.product(GRID["sigma"], GRID["k"], GRID["temperature"]):
        p = AttentionParams(sigma=sigma, k=k, temperature=t, unattached_score=base.unattached_score)
        m = evaluate(ds, p, train_weeks)
        rows.append({"sigma": sigma, "k": k, "temperature": t, **m})
    res = pd.DataFrame(rows).sort_values("objective", ascending=False).reset_index(drop=True)
    best = res.iloc[0]
    return AttentionParams(float(best["sigma"]), float(best["k"]), float(best["temperature"]), base.unattached_score), res


def save_params(p: AttentionParams, note: str) -> None:
    """Rewrite sigma, k and temperature in config.yaml, keeping comments."""
    text = CONFIG_PATH.read_text(encoding="utf-8")
    for key, val in (("sigma", p.sigma), ("k", p.k), ("temperature", p.temperature)):
        pattern = rf"(?m)^(  {key}:\s*)([-0-9.]+)(\s*#.*)?$"
        m = re.search(pattern, text)
        if not m:
            raise ValueError(f"attention.{key} not found in config.yaml")
        comment = (m.group(3) or "").split(" [tuned")[0].rstrip()
        text = text[: m.start()] + f"{m.group(1)}{float(val)}{comment} [tuned {note}]" + text[m.end() :]
    CONFIG_PATH.write_text(text, encoding="utf-8")
    load_config.cache_clear()


def _hist(values: np.ndarray, bins: np.ndarray) -> list[int]:
    return np.histogram(values, bins=bins)[0].astype(int).tolist()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-save", action="store_true", help="don't write the chosen values to config.yaml")
    ap.add_argument("--games", type=int, nargs="*")
    args = ap.parse_args(argv)

    cfg = load_config()
    train = list(cfg["calibration"]["train_weeks"])
    test = list(cfg["calibration"]["test_weeks"])

    ds = collect(args.games or None)
    print(f"coverage defender-throws: {len(ds['cov_dist'])}; block cases: {len(ds['blk_dist'])}")

    default = AttentionParams.from_config()
    print(f"\nCurrent config {asdict(default)}")
    for name, weeks in (("weeks 1-6", train), ("weeks 7-8", test)):
        m = evaluate(ds, default, weeks)
        print(f"  {name}: Man median {m['man_median']:.3f} (n={m['man_n']}) vs Zone {m['zone_median']:.3f} "
              f"(n={m['zone_n']}), p={m['mannwhitney_p']:.1e}; block agreement {m['block_agreement']:.1%} (n={m['block_n']})")

    best, res = grid_search(ds, train)
    print("\nGrid search on weeks 1-6 (top 8 by objective):")
    print(res.head(8)[["sigma", "k", "temperature", "man_median", "zone_median", "block_agreement", "objective"]].round(3).to_string(index=False))

    m_test = evaluate(ds, best, test, keep=True)
    m_train = evaluate(ds, best, train)
    print(f"\nChosen sigma={best.sigma:g}, k={best.k:g}, T={best.temperature:g}")
    print(f"  weeks 1-6: Man {m_train['man_median']:.3f} vs Zone {m_train['zone_median']:.3f}; block agreement {m_train['block_agreement']:.1%}")
    print(f"  weeks 7-8 (held out): Man median {m_test['man_median']:.3f} (n={m_test['man_n']}) vs Zone "
          f"{m_test['zone_median']:.3f} (n={m_test['zone_n']}), Mann-Whitney p={m_test['mannwhitney_p']:.1e}; "
          f"block agreement {m_test['block_agreement']:.1%} (n={m_test['block_n']})")

    bins = np.linspace(0, 1, 21)
    out = {
        "params": asdict(best),
        "train_weeks": train,
        "test_weeks": test,
        "train": {k: v for k, v in m_train.items() if not k.startswith("_")},
        "test": {k: v for k, v in m_test.items() if not k.startswith("_")},
        "max_weight_bins": bins.round(2).tolist(),
        "max_weight_hist_test": {"Man": _hist(m_test["_man"], bins), "Zone": _hist(m_test["_zone"], bins)},
        "grid": res.drop(columns=[c for c in res.columns if c.startswith("_")]).round(4).to_dict("records"),
    }
    path = derived_dir() / "attention_validation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1))
    print(f"wrote {path}")

    if not args.no_save:
        save_params(best, "P04 grid search, weeks 1-6")
        print(f"saved sigma, k, temperature to {CONFIG_PATH.name}")

    pa = load_play(2021090900, 1687)
    att = attention_for_play(pa, best)
    print(f"\nDemo 2021090900/1687 at release (frame {pa.end_frame}, t = {pa.t(pa.end_frame):.1f} s):")
    print(format_matrix(pa, att, pa.end_frame))


if __name__ == "__main__":
    main()
