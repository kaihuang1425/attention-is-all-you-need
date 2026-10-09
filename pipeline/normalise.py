"""Normalise tracking so the offense always attacks +x, and find the key frames of each play.

Conventions (verified in docs/01_DATA_SPEC.md):
- x 0-120 along the field (end zones included), y 0-53.3 across.
- Angles: 0 deg points to +y, clockwise. Unit vector = (sin a, cos a).
- After normalisation the offense attacks +x and the offense's left is +y.
- Frame is the unit of time (10 Hz). t = (frameId - snapFrame) / 10.

Snap and throw events come twice on many plays (manual and auto). The manual event wins; the
auto event is only a fallback. Auto snaps can be badly wrong (2021090900/3406 has
autoevent_ballsnap at frame 6 while the real ball_snap is at frame 146).
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import load
from .config import derived_dir, load_config

FIELD_LENGTH = 120.0
FIELD_WIDTH = 53.3
OWN_GOAL_X = 10.0  # normalised: offense's own goal line
OPP_GOAL_X = 110.0  # normalised: goal line the offense attacks
MIDFIELD_X = 60.0

# Raw event -> (canonical type, is_auto). Snap and throw have manual and auto versions.
_MERGED_EVENTS = {
    "ball_snap": ("ball_snap", False),
    "autoevent_ballsnap": ("ball_snap", True),
    "pass_forward": ("pass_forward", False),
    "autoevent_passforward": ("pass_forward", True),
}
_END_TYPES = {
    "pass_forward": "throw",
    "qb_sack": "sack",
    "qb_strip_sack": "sack",
    "run": "scramble",
}

KEYS = ["gameId", "playId"]


# --------------------------------------------------------------------------------------------
# Coordinates
# --------------------------------------------------------------------------------------------


def normalise_tracking(df: pd.DataFrame, play_row: pd.Series | dict | None = None) -> pd.DataFrame:
    """Return a copy with x, y, o, dir flipped for left-moving plays, plus vx, vy (yd/s).

    Works on one play or many: the flip is decided per row from `playDirection`. If `play_row`
    is given (a plays.csv row, or a play index row), `los_x` and `firstDown_x` columns are added.
    """
    out = df.copy()
    left = (out["playDirection"] == "left").to_numpy()

    x = out["x"].to_numpy(dtype=np.float64)
    y = out["y"].to_numpy(dtype=np.float64)
    o = out["o"].to_numpy(dtype=np.float64)
    d = out["dir"].to_numpy(dtype=np.float64)

    out["x"] = np.where(left, FIELD_LENGTH - x, x).astype(np.float32)
    out["y"] = np.where(left, FIELD_WIDTH - y, y).astype(np.float32)
    out["o"] = np.where(left, np.mod(o + 180.0, 360.0), o).astype(np.float32)
    d_norm = np.where(left, np.mod(d + 180.0, 360.0), d)
    out["dir"] = d_norm.astype(np.float32)

    s = out["s"].to_numpy(dtype=np.float64)
    rad = np.deg2rad(d_norm)
    out["vx"] = (s * np.sin(rad)).astype(np.float32)
    out["vy"] = (s * np.cos(rad)).astype(np.float32)

    if play_row is not None:
        direction = play_row.get("playDirection") if hasattr(play_row, "get") else None
        if direction is None:
            direction = str(df["playDirection"].iloc[0])
        los = los_x(float(play_row["absoluteYardlineNumber"]), str(direction))
        out["los_x"] = np.float32(los)
        out["firstDown_x"] = np.float32(los + float(play_row["yardsToGo"]))
    return out


def los_x(absolute_yardline: float, play_direction: str) -> float:
    """Line of scrimmage in normalised x. absoluteYardlineNumber is in the raw x frame."""
    return FIELD_LENGTH - absolute_yardline if play_direction == "left" else absolute_yardline


def yard_label(x_norm: float, offense: str, defense: str) -> str:
    """Real-field label for a normalised x, e.g. 'TB 25', '50', 'DAL 30'."""
    if x_norm >= OPP_GOAL_X:
        return f"{defense} goal line"
    if x_norm <= OWN_GOAL_X:
        return f"{offense} goal line"
    yards = int(round(x_norm - OWN_GOAL_X)) if x_norm < MIDFIELD_X else int(round(OPP_GOAL_X - x_norm))
    if yards == 50:
        return "50"
    side = offense if x_norm < MIDFIELD_X else defense
    return f"{side} {yards}"


# --------------------------------------------------------------------------------------------
# Events and key frames
# --------------------------------------------------------------------------------------------


def canonical_events(ball: pd.DataFrame) -> pd.DataFrame:
    """One row per (play, moment) from ball rows, with manual/auto duplicates merged.

    Columns: gameId, playId, frameId, type, rawEvent, autoFrame (frame of the auto duplicate when
    the manual event exists, else NA), fromAuto (True when only the auto event exists).
    Every event other than snap/throw passes through unchanged (all occurrences kept).
    """
    ev = ball.loc[ball["event"] != load.NO_EVENT, KEYS + ["frameId", "event"]].copy()
    ev["event"] = ev["event"].astype(str)
    ev = ev.drop_duplicates()

    merged_mask = ev["event"].isin(list(_MERGED_EVENTS))
    other = ev[~merged_mask].rename(columns={"event": "type"})
    other = other.assign(
        frameId=other["frameId"].astype("int64"),
        rawEvent=other["type"],
        autoFrame=pd.array([pd.NA] * len(other), dtype="Int64"),
        fromAuto=False,
    )

    m = ev[merged_mask].copy()
    m["type"] = m["event"].map(lambda e: _MERGED_EVENTS[e][0])
    m["isAuto"] = m["event"].map(lambda e: _MERGED_EVENTS[e][1])
    first = m.groupby(KEYS + ["type", "isAuto"], observed=True)["frameId"].min().unstack("isAuto")
    first = first.reindex(columns=[False, True])
    manual, auto = first[False].astype(float), first[True].astype(float)
    frame = manual.where(manual.notna(), auto)
    rows = pd.DataFrame(
        {
            "frameId": frame.astype("int64"),
            "rawEvent": np.where(manual.notna(), first.index.get_level_values("type"), "autoevent"),
            "autoFrame": auto.where(manual.notna()).astype("Int64"),
            "fromAuto": manual.isna(),
        }
    ).reset_index()
    # rawEvent for auto-only rows: the actual auto event name.
    auto_name = {"ball_snap": "autoevent_ballsnap", "pass_forward": "autoevent_passforward"}
    rows.loc[rows["fromAuto"], "rawEvent"] = rows.loc[rows["fromAuto"], "type"].map(auto_name)

    cols = KEYS + ["frameId", "type", "rawEvent", "autoFrame", "fromAuto"]
    parts = [df[cols] for df in (rows, other) if len(df)]
    out = pd.concat(parts, ignore_index=True) if parts else rows[cols]
    out["autoFrame"] = out["autoFrame"].astype("Int64")
    out["fromAuto"] = out["fromAuto"].astype(bool)
    return out.sort_values(KEYS + ["frameId", "type"]).reset_index(drop=True)


def infer_snap_frame(ball_play: pd.DataFrame, move_yd: float | None = None,
                     moving_start_speed: float | None = None) -> tuple[int | None, str]:
    """Infer the snap for a play with no snap event. Returns (frameId, source).

    - "before_tracking": the ball is already moving on the first frame, so the snap happened
      before tracking started (frameId = first frame; times from the snap are lower bounds).
    - "inferred": the frame before the ball's first frame-to-frame jump of more than `move_yd`.
      On plays with a manual snap this rule lands on the same frame at the median, within
      1 frame 63% of the time and within 2 frames 77% (20-game sample).
    - (None, "missing") when the ball never moves.
    """
    timing = load_config()["timing"]
    move_yd = float(timing["snap_infer_move_yd"]) if move_yd is None else move_yd
    moving_start_speed = float(timing["snap_moving_start_speed"]) if moving_start_speed is None else moving_start_speed
    b = ball_play.sort_values("frameId")
    frames = b["frameId"].to_numpy()
    if float(b["s"].iloc[0]) >= moving_start_speed:
        return int(frames[0]), "before_tracking"
    step = np.hypot(np.diff(b["x"].to_numpy(dtype=float)), np.diff(b["y"].to_numpy(dtype=float)))
    jumps = np.flatnonzero(step > move_yd)
    if jumps.size == 0:
        return None, "missing"
    return int(frames[jumps[0]]), "inferred"


def play_frame_index(ball: pd.DataFrame, events: pd.DataFrame | None = None) -> pd.DataFrame:
    """Key frames per play from ball rows.

    Columns: gameId, playId, playDirection, firstFrame, lastFrame, nFrames, snapFrame,
    snapSource ("manual" | "auto" | "inferred" | "before_tracking" | "missing"), snapAutoFrame,
    snapInferred,
    throwFrame (manual-first; NA when no throw), endFrame, endType ("throw" | "sack" |
    "scramble"), endEvent, ballSnapX, ballSnapY (raw coordinates at the snap).
    """
    if events is None:
        events = canonical_events(ball)
    g = ball.groupby(KEYS, observed=True)
    idx = pd.DataFrame(
        {
            "playDirection": g["playDirection"].first().astype(str),
            "firstFrame": g["frameId"].min().astype("int64"),
            "lastFrame": g["frameId"].max().astype("int64"),
        }
    )
    idx["nFrames"] = idx["lastFrame"] - idx["firstFrame"] + 1

    snaps = events[events["type"] == "ball_snap"].groupby(KEYS)[["frameId", "autoFrame", "fromAuto"]].first()
    idx = idx.join(snaps.rename(columns={"frameId": "snapFrame", "autoFrame": "snapAutoFrame", "fromAuto": "snapFromAuto"}))
    idx["snapSource"] = np.where(idx["snapFrame"].isna(), "missing", np.where(idx["snapFromAuto"] == True, "auto", "manual"))  # noqa: E712
    idx = idx.drop(columns="snapFromAuto")

    missing = idx.index[idx["snapSource"] == "missing"]
    for key in missing:
        frame, source = infer_snap_frame(ball[(ball["gameId"] == key[0]) & (ball["playId"] == key[1])])
        idx.loc[key, "snapFrame"] = frame
        idx.loc[key, "snapSource"] = source
    idx["snapInferred"] = idx["snapSource"].isin(["inferred", "before_tracking"])
    idx["snapFrame"] = idx["snapFrame"].astype("Int64")
    idx["snapAutoFrame"] = idx["snapAutoFrame"].astype("Int64")

    ends = events[events["type"].isin(list(_END_TYPES))]
    first_end = ends.groupby(KEYS + ["type"])["frameId"].min().unstack("type")
    first_end = first_end.reindex(columns=list(_END_TYPES))
    idx["throwFrame"] = first_end["pass_forward"].reindex(idx.index).astype("Int64")
    arr = first_end.to_numpy(dtype=float)
    has_end = ~np.isnan(arr).all(axis=1)
    pos = np.argmin(np.where(np.isnan(arr), np.inf, arr), axis=1)
    end_frame = pd.Series(np.where(has_end, arr[np.arange(len(arr)), pos], np.nan), index=first_end.index)
    end_event = pd.Series(np.where(has_end, np.asarray(first_end.columns)[pos], None), index=first_end.index, dtype=object)
    idx["endFrame"] = end_frame.reindex(idx.index).astype("Int64")
    idx["endEvent"] = end_event.reindex(idx.index)
    idx["endType"] = idx["endEvent"].map(_END_TYPES)

    snap_pos = ball.merge(idx["snapFrame"].dropna().rename("frameId").astype("int64").reset_index(), on=KEYS + ["frameId"])
    idx = idx.join(snap_pos.set_index(KEYS)[["x", "y"]].rename(columns={"x": "ballSnapX", "y": "ballSnapY"}))
    return idx.reset_index()


# --------------------------------------------------------------------------------------------
# Formation label
# --------------------------------------------------------------------------------------------

_LEFT_RECEIVER = {"LWR", "SLWR", "SLoWR", "SLiWR", "TE-L", "TE-oL", "TE-iL"}
_RIGHT_RECEIVER = {"RWR", "SRWR", "SRoWR", "SRiWR", "TE-R", "TE-oR", "TE-iR"}
_BACKS = {"HB", "HB-L", "HB-R", "FB", "FB-L", "FB-R"}


def formation_table(pff: pd.DataFrame) -> pd.DataFrame:
    """Receiver split per play from the offense's pff_positionLinedUp (WR and TE counted).

    Label is larger side first ("3x1"), with an "Empty " prefix when no back is aligned in the
    backfield. receiversLeft/Right are from the offense's view (left = +y after normalisation).
    """
    off = pff[pff["pff_role"].isin(load.OFFENSE_ROLES)][KEYS + ["pff_positionLinedUp"]]
    pos = off["pff_positionLinedUp"].astype(str)
    flags = pd.DataFrame(
        {
            "gameId": off["gameId"],
            "playId": off["playId"],
            "receiversLeft": pos.isin(_LEFT_RECEIVER).astype(int),
            "receiversRight": pos.isin(_RIGHT_RECEIVER).astype(int),
            "backs": pos.isin(_BACKS).astype(int),
        }
    )
    t = flags.groupby(KEYS, as_index=False).sum()
    t["empty"] = t["backs"] == 0
    big = t[["receiversLeft", "receiversRight"]].max(axis=1)
    small = t[["receiversLeft", "receiversRight"]].min(axis=1)
    label = big.astype(str) + "x" + small.astype(str)
    t["formation"] = np.where(t["empty"], "Empty " + label, label)
    return t[KEYS + ["formation", "receiversLeft", "receiversRight", "empty"]]


# --------------------------------------------------------------------------------------------
# Play index
# --------------------------------------------------------------------------------------------


def build_play_index(game_ids: list[int] | None = None, *, verbose: bool = True) -> pd.DataFrame:
    """One row per play with situation, teams, QB, formation, coverage and key frames."""
    games = load.load_games()
    plays = load.load_plays()
    pff = load.load_pff()
    players = load.load_players()

    frames = []
    start = time.perf_counter()
    for gid, trk in load.iter_tracking(game_ids):
        frames.append(play_frame_index(load.ball_rows(trk)))
    fidx = pd.concat(frames, ignore_index=True)
    if verbose:
        print(f"key frames for {len(fidx)} plays in {time.perf_counter() - start:.1f}s")

    df = plays.merge(fidx, on=KEYS, how="inner" if game_ids is not None else "left")
    df = df.merge(games[["gameId", "week", "homeTeamAbbr", "visitorTeamAbbr", "gameDate"]], on="gameId", how="left")

    qb = pff[pff["pff_role"] == load.ROLE_PASSER][KEYS + ["nflId"]].rename(columns={"nflId": "qbNflId"})
    qb = qb.drop_duplicates(KEYS).merge(players[["nflId", "displayName"]].rename(columns={"nflId": "qbNflId", "displayName": "qbName"}), on="qbNflId", how="left")
    df = df.merge(qb, on=KEYS, how="left")

    df = df.merge(formation_table(pff), on=KEYS, how="left")

    # One play (2021091904/3676) has no absoluteYardlineNumber; rebuild it from yardlineSide /
    # yardlineNumber, which agrees with absoluteYardlineNumber on every other play.
    los_from_side = np.where(
        df["yardlineNumber"] == 50,
        MIDFIELD_X,
        np.where(df["yardlineSide"] == df["possessionTeam"], OWN_GOAL_X + df["yardlineNumber"], OPP_GOAL_X - df["yardlineNumber"]),
    )
    abs_from_side = np.where(df["playDirection"] == "left", FIELD_LENGTH - los_from_side, los_from_side)
    df["losFilled"] = df["absoluteYardlineNumber"].isna() & df["playDirection"].notna()
    df["absoluteYardlineNumber"] = df["absoluteYardlineNumber"].fillna(pd.Series(abs_from_side, index=df.index))

    fps = float(load_config()["timing"]["fps"])
    df["los_x"] = np.where(df["playDirection"] == "left", FIELD_LENGTH - df["absoluteYardlineNumber"], df["absoluteYardlineNumber"])
    df["firstDown_x"] = df["los_x"] + df["yardsToGo"]
    df["losLabel"] = [yard_label(x, o, d) if pd.notna(x) else None for x, o, d in zip(df["los_x"], df["possessionTeam"], df["defensiveTeam"])]
    df["firstDownLabel"] = [yard_label(x, o, d) if pd.notna(x) else None for x, o, d in zip(df["firstDown_x"], df["possessionTeam"], df["defensiveTeam"])]
    df["isHomeOffense"] = df["possessionTeam"] == df["homeTeamAbbr"]
    df["offenseScore"] = np.where(df["isHomeOffense"], df["preSnapHomeScore"], df["preSnapVisitorScore"])
    df["defenseScore"] = np.where(df["isHomeOffense"], df["preSnapVisitorScore"], df["preSnapHomeScore"])

    snap = df["snapFrame"].astype("Float64")
    end = df["endFrame"].astype("Float64")
    df["timeToEnd"] = ((end - snap) / fps).round(1)
    df["timeToThrow"] = df["timeToEnd"].where(df["endType"] == "throw")
    # Plays the replay list and decision-gap stats can use: a trustworthy snap and an end event.
    df["replayable"] = df["snapSource"].isin(["manual", "auto", "inferred"]) & df["endFrame"].notna() & df["los_x"].notna()

    cols = [
        "gameId", "playId", "week", "gameDate", "homeTeamAbbr", "visitorTeamAbbr", "possessionTeam", "defensiveTeam",
        "qbNflId", "qbName", "quarter", "gameClock", "down", "yardsToGo", "preSnapHomeScore", "preSnapVisitorScore",
        "offenseScore", "defenseScore", "isHomeOffense", "playDirection", "absoluteYardlineNumber", "yardlineSide",
        "yardlineNumber", "los_x", "firstDown_x", "losLabel", "firstDownLabel", "formation", "receiversLeft",
        "receiversRight", "empty", "offenseFormation", "personnelO", "personnelD", "defendersInBox", "dropBackType",
        "pff_playAction", "pff_passCoverage", "pff_passCoverageType", "passResult", "playResult", "prePenaltyPlayResult",
        "penaltyYards", "foulName1", "playDescription", "firstFrame", "lastFrame", "nFrames", "snapFrame", "snapSource",
        "snapInferred", "snapAutoFrame", "throwFrame", "endFrame", "endType", "endEvent", "timeToEnd", "timeToThrow",
        "ballSnapX", "ballSnapY", "losFilled", "replayable",
    ]
    out = df[cols].copy()
    for c in ("receiversLeft", "receiversRight"):
        out[c] = out[c].astype("Int64")
    out["empty"] = out["empty"].astype("boolean")
    out["week"] = out["week"].astype("Int64")
    return out.sort_values(KEYS).reset_index(drop=True)


def write_play_index(df: pd.DataFrame, path: Path | None = None) -> Path:
    path = path or derived_dir() / "play_index.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def read_play_index(path: Path | None = None) -> pd.DataFrame:
    path = path or derived_dir() / "play_index.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run `python -m pipeline.normalise` first.")
    return pd.read_parquet(path)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Build data/derived/play_index.parquet")
    ap.add_argument("--games", type=int, nargs="*", help="limit to these gameIds")
    args = ap.parse_args(argv)
    idx = build_play_index(args.games or None)
    path = write_play_index(idx)
    print(f"wrote {path} ({len(idx)} plays)")
    print("snapSource:", idx["snapSource"].value_counts().to_dict())
    print("replayable:", int(idx["replayable"].sum()), "of", len(idx))
    print("endType:", idx["endType"].value_counts(dropna=False).to_dict())
    print("formation (top 10):", idx["formation"].value_counts().head(10).to_dict())


if __name__ == "__main__":
    main()
