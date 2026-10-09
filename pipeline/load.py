"""Read the Big Data Bowl regional event CSVs with the right NA handling and compact dtypes.

Gotchas handled here (see docs/01_DATA_SPEC.md):
- Tracking `event` uses the literal string "None" for "no event". pandas would turn it into NaN,
  so tracking is read with keep_default_na=False and only the columns that really hold "NA"
  (nflId, jerseyNumber, o, dir on ball rows) get NA parsing.
- Ball rows have team == "football" and nflId NA.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path

import numpy as np
import pandas as pd

from .config import raw_dir

# pff_role values as they appear in pffScoutingData.csv. The data README spells three of them
# with a lower-case second word ("Pass block", "Pass route", "Pass rush"); the data does not.
ROLE_PASSER = "Pass"
ROLE_BLOCK = "Pass Block"
ROLE_ROUTE = "Pass Route"
ROLE_RUSH = "Pass Rush"
ROLE_COVERAGE = "Coverage"
PFF_ROLES = (ROLE_PASSER, ROLE_BLOCK, ROLE_ROUTE, ROLE_RUSH, ROLE_COVERAGE)
OFFENSE_ROLES = (ROLE_PASSER, ROLE_BLOCK, ROLE_ROUTE)
DEFENSE_ROLES = (ROLE_RUSH, ROLE_COVERAGE)

FOOTBALL = "football"
NO_EVENT = "None"

KINEMATIC_COLS = ("x", "y", "s", "a", "dis", "o", "dir")

_TRACKING_DTYPES = {
    "gameId": "int64",
    "playId": "int32",
    "nflId": "Int64",
    "frameId": "int16",
    "time": "string",
    "jerseyNumber": "Int8",
    "team": "string",
    "playDirection": "string",
    "x": "float32",
    "y": "float32",
    "s": "float32",
    "a": "float32",
    "dis": "float32",
    "o": "float32",
    "dir": "float32",
    "event": "string",
}
# Only these columns may contain "NA" (ball rows). "None" in `event` must stay a string.
_TRACKING_NA = {c: ["NA"] for c in ("nflId", "jerseyNumber", "x", "y", "s", "a", "dis", "o", "dir")}
_TRACKING_CATEGORIES = ("team", "playDirection", "event")


def _path(*parts: str) -> Path:
    p = raw_dir().joinpath(*parts)
    if not p.exists():
        raise FileNotFoundError(f"{p} not found. Run `bash scripts/get_data.sh` or set NFL_DATA_DIR.")
    return p


def load_games() -> pd.DataFrame:
    df = pd.read_csv(_path("games.csv"))
    df["gameId"] = df["gameId"].astype("int64")
    df["week"] = df["week"].astype("int8")
    return df


def load_plays() -> pd.DataFrame:
    df = pd.read_csv(_path("plays.csv"))
    df["gameId"] = df["gameId"].astype("int64")
    df["playId"] = df["playId"].astype("int32")
    return df


def load_players() -> pd.DataFrame:
    df = pd.read_csv(_path("players.csv"))
    df["nflId"] = df["nflId"].astype("int64")
    return df


def load_pff() -> pd.DataFrame:
    df = pd.read_csv(_path("pffScoutingData.csv"))
    df["gameId"] = df["gameId"].astype("int64")
    df["playId"] = df["playId"].astype("int32")
    df["nflId"] = df["nflId"].astype("int64")
    df["pff_nflIdBlockedPlayer"] = df["pff_nflIdBlockedPlayer"].astype("Int64")
    unknown = set(df["pff_role"].unique()) - set(PFF_ROLES)
    if unknown:
        raise ValueError(f"unexpected pff_role values: {sorted(unknown)}")
    return df


def tracking_game_ids() -> list[int]:
    folder = _path("tracking")
    return sorted(int(p.stem.split("_")[1]) for p in folder.glob("tracking_*.csv"))


def load_tracking(game_id: int, *, keep_time: bool = False) -> pd.DataFrame:
    """One game of tracking: 10 Hz, players and ball, raw (un-normalised) coordinates."""
    path = _path("tracking", f"tracking_{int(game_id)}.csv")
    usecols = [c for c in _TRACKING_DTYPES if keep_time or c != "time"]
    df = pd.read_csv(
        path,
        usecols=usecols,
        dtype={c: t for c, t in _TRACKING_DTYPES.items() if c in usecols},
        keep_default_na=False,
        na_values=_TRACKING_NA,
        engine="c",
    )
    for col in _TRACKING_CATEGORIES:
        df[col] = df[col].astype("category")
    return df


def iter_tracking(game_ids: Iterable[int] | None = None, **kwargs) -> Iterator[tuple[int, pd.DataFrame]]:
    """Yield (gameId, tracking frame) one game at a time to keep memory low."""
    for gid in game_ids if game_ids is not None else tracking_game_ids():
        yield int(gid), load_tracking(gid, **kwargs)


def ball_rows(tracking: pd.DataFrame) -> pd.DataFrame:
    """Ball rows only. Events are repeated on every row of a frame, so read them here."""
    return tracking[tracking["team"] == FOOTBALL]


def player_rows(tracking: pd.DataFrame) -> pd.DataFrame:
    return tracking[tracking["team"] != FOOTBALL]


def sample_game_ids(n: int = 10, seed: int = 0) -> list[int]:
    """Deterministic sample of game ids, used by the fact tests and quick checks."""
    ids = tracking_game_ids()
    rng = np.random.default_rng(seed)
    return sorted(int(g) for g in rng.choice(ids, size=min(n, len(ids)), replace=False))
