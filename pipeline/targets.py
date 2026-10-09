"""The receiver the QB actually targeted, parsed from playDescription.

Patterns (docs/01_DATA_SPEC.md):
- C / I:  "... pass [incomplete] (short|deep) (left|middle|right) to C.Lamb ..."
- IN:     "... pass (short|deep) (left|middle|right) intended for C.Lamb INTERCEPTED by ..."
- Some incompletions name nobody ("pass incomplete short right."): targetMatch = "no_name".

The abbreviated name is matched to an nflId among the offensive players on the play
(pff_role Pass Route or Pass Block): first by (first-name prefix, last name), then by last name
alone when that is unique. Optional fallback: nflverse play-by-play receiver_player_name.
"""

from __future__ import annotations

import argparse
import re
import unicodedata

import numpy as np
import pandas as pd

from . import load
from . import normalise as N
from .config import derived_dir, external_dir, load_config

KEYS = N.KEYS
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

# Players whose players.csv displayName differs from the name used in 2021 descriptions.
# Deonte Harris (NO) is listed under his later name, Deonte Harty.
NAME_ALIASES: dict[int, list[str]] = {48415: ["Deonte Harris"]}

# First name is one or more abbreviated parts ("C.", "Aa.", "Dj.", "A.J."), last name may be
# "St. Brown", hyphenated or carry a suffix.
# The first-name parts are matched lazily so "A.Cooper. PENALTY" stops at "A.Cooper".
_NAME = r"(?P<name>(?:[A-Z][A-Za-z]{0,2}\.)+? ?(?:St\. )?[A-Z][A-Za-z'\-]+(?: (?:Jr|Sr|II|III|IV|V)\.?(?=[\s.,(]|$))?)"
_PASS_RE = re.compile(
    r"\bpass(?P<incomplete> incomplete)?"
    r"(?: (?P<depth>short|deep))?(?: (?P<side>left|middle|right))?"
    r"(?: (?P<verb>to|intended for) " + _NAME + r")?"
)


def _fold(text: str) -> str:
    """Lower-case, strip accents and every non-letter, e.g. "St. Brown" -> "stbrown"."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", text.lower())


def _strip_suffix(parts: list[str]) -> list[str]:
    while len(parts) > 1 and _fold(parts[-1]) in SUFFIXES:
        parts = parts[:-1]
    return parts


def split_abbrev(name: str) -> tuple[str, str]:
    """'C.Lamb' -> ('c', 'lamb'); 'A.St. Brown' -> ('a', 'stbrown'); 'Dj.Moore' -> ('dj', 'moore')."""
    m = re.match(r"^((?:[A-Z][A-Za-z]{0,2}\.)+?) ?((?:St\. )?[A-Z][A-Za-z'\-]+.*)$", name.strip())
    if not m:
        return "", _fold(name)
    first = _fold(m.group(1))
    last = " ".join(_strip_suffix(m.group(2).split()))
    return first, _fold(last)


def split_display(name: str) -> tuple[str, str]:
    """'CeeDee Lamb' -> ('ceedee', 'lamb'); 'Amon-Ra St. Brown' -> ('amonra', 'stbrown')."""
    parts = _strip_suffix(name.split())
    if len(parts) == 1:
        return "", _fold(parts[0])
    return _fold(parts[0]), _fold(" ".join(parts[1:]))


def parse_description(desc: str) -> dict:
    """Pull receiver name, depth and side out of one playDescription."""
    out = {"targetName": None, "depth": None, "side": None, "throwAway": False, "spike": False}
    if not isinstance(desc, str):
        return out
    low = desc.lower()
    out["throwAway"] = "thrown away" in low or "throw away" in low or "throws away" in low
    out["spike"] = "spiked the ball" in low or " spike" in low
    m = _PASS_RE.search(desc)
    if not m:
        return out
    out["depth"] = m.group("depth")
    out["side"] = m.group("side")
    name = m.group("name")
    if name:
        out["targetName"] = name.rstrip(".") if not re.search(r"\b(Jr|Sr)\.$", name) else name
    return out


def match_target(abbrev: str, candidates: pd.DataFrame) -> tuple[int | None, str]:
    """Match an abbreviated name to one nflId among `candidates` (columns nflId, displayName)."""
    if not abbrev:
        return None, "no_name"
    first, last = split_abbrev(abbrev)
    names = [(int(i), n) for i, n in zip(candidates["nflId"], candidates["displayName"]) if isinstance(n, str)]
    names += [(i, alias) for i, _ in names for alias in NAME_ALIASES.get(i, [])]
    split = [(i, *split_display(n)) for i, n in names]

    same_last = {i for i, _, l in split if l == last}
    by_first = {i for i, f, l in split if l == last and first and f.startswith(first)}
    if len(by_first) == 1:
        return by_first.pop(), "unique"
    if not by_first and first:
        # First initial only, for nicknames ("Aa" -> "Aaron" is covered above; this catches the rest).
        by_initial = {i for i, f, l in split if l == last and f[:1] == first[:1]}
        if len(by_initial) == 1:
            return by_initial.pop(), "unique"
    if len(same_last) == 1:
        return same_last.pop(), "unique"
    if len(same_last) > 1 or len(by_first) > 1:
        return None, "multi"
    return None, "none"


def _pbp_receivers() -> pd.DataFrame | None:
    path = external_dir() / "pbp_2021.parquet"
    if not path.exists():
        return None
    pbp = pd.read_parquet(path, columns=["old_game_id", "play_id", "receiver_player_name"])
    pbp = pbp.dropna(subset=["old_game_id", "play_id"])
    pbp = pbp.assign(gameId=pbp["old_game_id"].astype("int64"), playId=pbp["play_id"].astype("int64"))
    return pbp[KEYS + ["receiver_player_name"]]


# --------------------------------------------------------------------------------------------
# Ball direction cross-check
# --------------------------------------------------------------------------------------------

# Direction sectors from the offense's view, in degrees from +x with the offense's left positive.
SIDE_SECTORS = {"left": (10.0, 180.0), "middle": (-30.0, 30.0), "right": (-180.0, -10.0)}


def sector_distance(angle: float, side: str) -> float:
    """Degrees between `angle` and the sector for `side` (0 when inside it)."""
    lo, hi = SIDE_SECTORS[side]
    if lo <= angle <= hi:
        return 0.0
    return float(min(abs(angle - lo), abs(angle - hi)))


def throw_directions(game_ids: list[int] | None = None, index: pd.DataFrame | None = None) -> pd.DataFrame:
    """Ball direction over the post-release frames for every play with a throw.

    Columns: gameId, playId, throwAngle (deg, offense's left positive), releaseSpeed (yd/s over
    the post-release frames), postFrames (number of ball frames used).
    """
    if index is None:
        index = N.read_play_index()
    throws = index[index["endType"] == "throw"][KEYS + ["throwFrame", "lastFrame"]]
    rows = []
    for gid, trk in load.iter_tracking(game_ids if game_ids is not None else sorted(throws["gameId"].unique())):
        ball = N.normalise_tracking(load.ball_rows(trk))
        t = throws[throws["gameId"] == gid]
        b = ball.merge(t, on=KEYS)
        b = b[(b["frameId"] >= b["throwFrame"]) & (b["frameId"] <= b["lastFrame"])]
        for (g, p), grp in b.groupby(KEYS, observed=True):
            grp = grp.sort_values("frameId")
            if len(grp) < 2:
                continue
            dx = float(grp["x"].iloc[-1] - grp["x"].iloc[0])
            dy = float(grp["y"].iloc[-1] - grp["y"].iloc[0])
            dt = (int(grp["frameId"].iloc[-1]) - int(grp["frameId"].iloc[0])) / float(load_config()["timing"]["fps"])
            rows.append((g, p, float(np.degrees(np.arctan2(dy, dx))), float(np.hypot(dx, dy) / dt), len(grp) - 1))
    return pd.DataFrame(rows, columns=KEYS + ["throwAngle", "releaseSpeed", "postFrames"])


# --------------------------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------------------------


def build_targets(
    index: pd.DataFrame | None = None, *, with_ball: bool = True, use_pbp: bool = True, verbose: bool = True
) -> pd.DataFrame:
    plays = load.load_plays()
    pff = load.load_pff()
    players = load.load_players()[["nflId", "displayName"]]
    if index is not None:
        plays = plays.merge(index[KEYS], on=KEYS)

    offense = pff[pff["pff_role"].isin([load.ROLE_ROUTE, load.ROLE_BLOCK])][KEYS + ["nflId"]].merge(players, on="nflId", how="left")
    by_play = {k: g for k, g in offense.groupby(KEYS)}

    parsed = pd.DataFrame([parse_description(d) for d in plays["playDescription"]], index=plays.index)
    out = pd.concat([plays[KEYS + ["passResult", "playDescription"]], parsed], axis=1)

    ids, how = [], []
    for row in out.itertuples(index=False):
        if row.passResult not in ("C", "I", "IN"):
            ids.append(None)
            how.append("not_targeted")
            continue
        cands = by_play.get((row.gameId, row.playId))
        if cands is None:
            ids.append(None)
            how.append("none")
            continue
        nid, h = match_target(row.targetName if isinstance(row.targetName, str) else "", cands)
        ids.append(nid)
        how.append(h)
    out["targetNflId"] = pd.array(ids, dtype="Int64")
    out["targetMatch"] = how
    out["targetSource"] = np.where(out["targetMatch"] == "unique", "description", None)

    pbp = _pbp_receivers() if use_pbp else None
    if pbp is not None:
        unresolved = out["targetMatch"].isin(["none", "multi"])
        fix = out[unresolved].merge(pbp, on=KEYS, how="left")
        n_fixed = 0
        for i, row in zip(out.index[unresolved], fix.itertuples(index=False)):
            if isinstance(row.receiver_player_name, str):
                nid, h = match_target(row.receiver_player_name, by_play.get((row.gameId, row.playId), offense.iloc[0:0]))
                if h == "unique":
                    out.at[i, "targetNflId"] = nid
                    out.at[i, "targetMatch"] = "unique"
                    out.at[i, "targetSource"] = "nflverse"
                    n_fixed += 1
        if verbose:
            print(f"nflverse play-by-play resolved {n_fixed} of {int(unresolved.sum())} unmatched targets")
    elif verbose and use_pbp:
        print("data/external/pbp_2021.parquet not found; skipping the nflverse fallback (scripts/get_nflverse.sh)")

    if with_ball:
        dirs = throw_directions(index=index if index is not None else None)
        out = out.merge(dirs, on=KEYS, how="left")
        dist = [
            sector_distance(a, s) if (isinstance(s, str) and pd.notna(a)) else np.nan
            for a, s in zip(out["throwAngle"], out["side"])
        ]
        out["sideDisagreeDeg"] = dist
        out["sideMismatch"] = out["sideDisagreeDeg"] > 40.0
    return out


def match_table(t: pd.DataFrame) -> pd.DataFrame:
    sub = t[t["passResult"].isin(["C", "I", "IN"])]
    tab = pd.crosstab(sub["passResult"], sub["targetMatch"])
    return tab.reindex(["C", "I", "IN"]).fillna(0).astype(int)


def write_targets(t: pd.DataFrame) -> None:
    path = derived_dir() / "targets.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    t.to_parquet(path, index=False)
    print(f"wrote {path}")


def read_targets() -> pd.DataFrame:
    path = derived_dir() / "targets.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run `python -m pipeline.targets` first.")
    return pd.read_parquet(path)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Parse actual targets into data/derived/targets.parquet")
    ap.add_argument("--no-ball", action="store_true", help="skip the ball-direction cross-check")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    t = build_targets(with_ball=not args.no_ball)
    write_targets(t)
    print("\nMatch table by passResult:")
    print(match_table(t).to_string())
    named = t[t["passResult"].isin(["C", "I", "IN"]) & t["targetName"].notna()]
    print(f"\nnamed targets matched uniquely: {(named['targetMatch'] == 'unique').mean():.2%} of {len(named)}")
    print(f"targetSource: {t['targetSource'].value_counts().to_dict()}")
    print(f"explicit throw-aways: {int(t['throwAway'].sum())}; spikes: {int(t['spike'].sum())}")
    none = t[t["targetMatch"].isin(["none", "multi"])]
    if len(none):
        print(f"\n{min(10, len(none))} unmatched cases:")
        for row in none.sample(min(10, len(none)), random_state=args.seed).itertuples():
            print(f"  {row.gameId}/{row.playId} [{row.targetMatch}] name={row.targetName!r}: {row.playDescription[:140]}")
    if "sideMismatch" in t:
        thrown = t[t["throwAngle"].notna() & t["side"].notna()]
        print(f"\nball direction vs parsed side: {int(thrown['sideMismatch'].sum())} of {len(thrown)} throws disagree by > 40 deg")
        print(f"release speed over post-release frames (yd/s): {t['releaseSpeed'].describe(percentiles=[.25, .5, .75]).round(1).to_dict()}")


if __name__ == "__main__":
    main()
