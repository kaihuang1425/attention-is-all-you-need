"""Dense per-play arrays (frames x players) in normalised coordinates, shared by the model stages.

Order of players inside a play:
- offense (non-QB): Pass Route first, then Pass Block; within a role, left to right from the
  offense's view at the snap (descending y). 10 players.
- defense: Pass Rush first, then Coverage; same left-to-right order. 11 players.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import load
from . import normalise as N

ROLE_ORDER = {load.ROLE_ROUTE: 0, load.ROLE_BLOCK: 1, load.ROLE_PASSER: 2, load.ROLE_RUSH: 3, load.ROLE_COVERAGE: 4}


@dataclass
class PlayArrays:
    gameId: int
    playId: int
    frames: np.ndarray  # (F,) frameId
    snap_frame: int
    end_frame: int
    end_type: str
    throw_frame: int | None
    los_x: float
    first_down_x: float
    meta: dict = field(repr=False)  # play index row as a dict

    off_ids: np.ndarray = field(repr=False)  # (10,)
    off_roles: np.ndarray = field(repr=False)
    off_jersey: np.ndarray = field(repr=False)
    off_aligned: np.ndarray = field(repr=False)
    qb_id: int = 0
    qb_jersey: int = 0
    def_ids: np.ndarray = field(default=None, repr=False)  # (11,)
    def_roles: np.ndarray = field(default=None, repr=False)
    def_jersey: np.ndarray = field(default=None, repr=False)
    def_aligned: np.ndarray = field(default=None, repr=False)

    off_xy: np.ndarray = field(default=None, repr=False)  # (F, 10, 2)
    off_v: np.ndarray = field(default=None, repr=False)  # (F, 10, 2)
    off_s: np.ndarray = field(default=None, repr=False)  # (F, 10)
    off_o: np.ndarray = field(default=None, repr=False)  # (F, 10) degrees
    qb_xy: np.ndarray = field(default=None, repr=False)  # (F, 2)
    qb_v: np.ndarray = field(default=None, repr=False)
    qb_s: np.ndarray = field(default=None, repr=False)
    qb_o: np.ndarray = field(default=None, repr=False)
    def_xy: np.ndarray = field(default=None, repr=False)  # (F, 11, 2)
    def_v: np.ndarray = field(default=None, repr=False)
    def_s: np.ndarray = field(default=None, repr=False)
    def_o: np.ndarray = field(default=None, repr=False)
    ball_xy: np.ndarray = field(default=None, repr=False)  # (F, 2)

    def idx(self, frame_id: int) -> int:
        """Row index of a frameId (frames are consecutive)."""
        i = int(frame_id) - int(self.frames[0])
        if i < 0 or i >= len(self.frames):
            raise IndexError(f"frame {frame_id} outside {self.frames[0]}..{self.frames[-1]}")
        return i

    @property
    def release_frame(self) -> int:
        """Frame where the QB's decision is evaluated: the throw, sack or scramble start."""
        return int(self.end_frame)

    @property
    def route_mask(self) -> np.ndarray:
        return self.off_roles == load.ROLE_ROUTE

    @property
    def rush_mask(self) -> np.ndarray:
        return self.def_roles == load.ROLE_RUSH

    def t(self, frame_id: int | np.ndarray) -> float | np.ndarray:
        return (np.asarray(frame_id) - self.snap_frame) / 10.0


def _dense(df: pd.DataFrame, ids: np.ndarray, frames: np.ndarray, col: str) -> np.ndarray:
    """(F, len(ids)) array of `col`, NaN where a player is missing on a frame."""
    out = np.full((len(frames), len(ids)), np.nan)
    col_of = {int(i): k for k, i in enumerate(ids)}
    fi = df["frameId"].to_numpy(dtype=np.int64) - int(frames[0])
    pj = np.array([col_of.get(int(i), -1) for i in df["nflId"].to_numpy()])
    ok = (pj >= 0) & (fi >= 0) & (fi < len(frames))
    out[fi[ok], pj[ok]] = df[col].to_numpy(dtype=np.float64)[ok]
    return out


def _order(pff_side: pd.DataFrame, at_snap: pd.DataFrame) -> pd.DataFrame:
    y = at_snap.set_index("nflId")["y"] if len(at_snap) else pd.Series(dtype=float)
    side = pff_side.assign(
        _role=pff_side["pff_role"].map(ROLE_ORDER),
        _y=pff_side["nflId"].map(y).astype(float).fillna(0.0),
    )
    return side.sort_values(["_role", "_y"], ascending=[True, False])


def build_play_arrays(trk: pd.DataFrame, pff_play: pd.DataFrame, meta: dict, jerseys: dict[int, int]) -> PlayArrays:
    """trk: normalised tracking rows (players and ball) of one play."""
    frames = np.arange(int(trk["frameId"].min()), int(trk["frameId"].max()) + 1)
    players = trk[trk["team"] != load.FOOTBALL]
    ball = trk[trk["team"] == load.FOOTBALL].sort_values("frameId")

    snap = int(meta["snapFrame"])
    at_snap = players[players["frameId"] == snap]
    off_pff = pff_play[pff_play["pff_role"].isin(load.OFFENSE_ROLES)]
    def_pff = pff_play[pff_play["pff_role"].isin(load.DEFENSE_ROLES)]
    qb_rows = off_pff[off_pff["pff_role"] == load.ROLE_PASSER]
    qb_id = int(qb_rows["nflId"].iloc[0])
    off = _order(off_pff[off_pff["pff_role"] != load.ROLE_PASSER], at_snap)
    dfn = _order(def_pff, at_snap)

    off_ids = off["nflId"].to_numpy(dtype=np.int64)
    def_ids = dfn["nflId"].to_numpy(dtype=np.int64)
    qb_ids = np.array([qb_id])

    def stack(ids, cols):
        return np.stack([_dense(players, ids, frames, c) for c in cols], axis=-1)

    ball_xy = np.full((len(frames), 2), np.nan)
    bi = ball["frameId"].to_numpy(dtype=np.int64) - frames[0]
    ball_xy[bi] = ball[["x", "y"]].to_numpy(dtype=np.float64)

    throw = meta.get("throwFrame")
    return PlayArrays(
        gameId=int(meta["gameId"]),
        playId=int(meta["playId"]),
        frames=frames,
        snap_frame=snap,
        end_frame=int(meta["endFrame"]),
        end_type=str(meta["endType"]),
        throw_frame=None if throw is None or pd.isna(throw) else int(throw),
        los_x=float(meta["los_x"]),
        first_down_x=float(meta["firstDown_x"]),
        meta=meta,
        off_ids=off_ids,
        off_roles=off["pff_role"].to_numpy(dtype=object),
        off_jersey=np.array([jerseys.get(int(i), -1) for i in off_ids]),
        off_aligned=off["pff_positionLinedUp"].to_numpy(dtype=object),
        qb_id=qb_id,
        qb_jersey=jerseys.get(qb_id, 0),
        def_ids=def_ids,
        def_roles=dfn["pff_role"].to_numpy(dtype=object),
        def_jersey=np.array([jerseys.get(int(i), -1) for i in def_ids]),
        def_aligned=dfn["pff_positionLinedUp"].to_numpy(dtype=object),
        off_xy=stack(off_ids, ["x", "y"]),
        off_v=stack(off_ids, ["vx", "vy"]),
        off_s=_dense(players, off_ids, frames, "s"),
        off_o=_dense(players, off_ids, frames, "o"),
        qb_xy=stack(qb_ids, ["x", "y"])[:, 0, :],
        qb_v=stack(qb_ids, ["vx", "vy"])[:, 0, :],
        qb_s=_dense(players, qb_ids, frames, "s")[:, 0],
        qb_o=_dense(players, qb_ids, frames, "o")[:, 0],
        def_xy=stack(def_ids, ["x", "y"]),
        def_v=stack(def_ids, ["vx", "vy"]),
        def_s=_dense(players, def_ids, frames, "s"),
        def_o=_dense(players, def_ids, frames, "o"),
        ball_xy=ball_xy,
    )


def iter_play_arrays(
    game_ids: Iterable[int] | None = None,
    *,
    plays: Iterable[tuple[int, int]] | None = None,
    index: pd.DataFrame | None = None,
    pff: pd.DataFrame | None = None,
    replayable_only: bool = True,
) -> Iterator[PlayArrays]:
    """Yield PlayArrays one play at a time, loading one game of tracking at a time."""
    if index is None:
        try:
            index = N.read_play_index()
        except FileNotFoundError:
            # No play_index.parquet yet: build the index for just the games we need.
            need = sorted({int(g) for g, _ in plays}) if plays is not None else (list(game_ids) if game_ids is not None else None)
            index = N.build_play_index(need, verbose=False)
    if pff is None:
        pff = load.load_pff()
    sel = index
    if replayable_only:
        sel = sel[sel["replayable"]]
    if plays is not None:
        keys = pd.DataFrame(list(plays), columns=N.KEYS)
        sel = sel.merge(keys, on=N.KEYS)
    if game_ids is not None:
        sel = sel[sel["gameId"].isin(list(game_ids))]

    pff_by_play = {k: g for k, g in pff[pff.set_index(N.KEYS).index.isin(sel.set_index(N.KEYS).index)].groupby(N.KEYS)}
    for gid in sorted(sel["gameId"].unique()):
        trk = load.load_tracking(int(gid))
        game_sel = sel[sel["gameId"] == gid]
        trk = trk[trk["playId"].isin(game_sel["playId"])]
        trk = N.normalise_tracking(trk)
        jerseys = {
            int(i): int(j)
            for i, j in trk.loc[trk["nflId"].notna(), ["nflId", "jerseyNumber"]].drop_duplicates("nflId").itertuples(index=False)
            if pd.notna(j)
        }
        by_play = {int(p): g for p, g in trk.groupby("playId", observed=True)}
        for meta in game_sel.to_dict("records"):
            t = by_play.get(int(meta["playId"]))
            p = pff_by_play.get((int(meta["gameId"]), int(meta["playId"])))
            if t is None or p is None:
                continue
            yield build_play_arrays(t, p, meta, jerseys)


def load_play(game_id: int, play_id: int, **kwargs) -> PlayArrays:
    for pa in iter_play_arrays(plays=[(game_id, play_id)], replayable_only=False, **kwargs):
        return pa
    raise KeyError(f"play {game_id}/{play_id} not found")
