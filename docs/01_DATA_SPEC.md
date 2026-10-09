# Data spec (verified against the repo)

Source: https://github.com/ThompsonJamesBliss/nfl-big-data-bowl-regional-event-data (the Big Data Bowl 2023 release: NGS tracking + PFF scouting).

Every number in this file was measured on the cloned repo on 2026-10-09. If a check in `05_BUILD_PROMPTS.md` P01 disagrees with a number here, trust the data and update this file.

## Files

| File | Rows | Key | Notes |
|---|---|---|---|
| `data/games.csv` | 122 | `gameId` | Season 2021, weeks 1–8 |
| `data/plays.csv` | 8,557 | `gameId`, `playId` | Dropbacks only |
| `data/players.csv` | 1,679 | `nflId` | `displayName`, `officialPosition` |
| `data/pffScoutingData.csv` | 188,254 | `gameId`, `playId`, `nflId` | Roles, blocks, pressure credit |
| `data/tracking/tracking_[gameId].csv` | 122 files, ~1 GB total | `gameId`, `playId`, `nflId`, `frameId` | 10 Hz, players + ball |

Total repo size is about 1 GB. Clone with `GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 ...`.

## Gotchas found while profiling

1. **`event` uses the string `"None"` for no event.** pandas turns it into NaN by default. Read tracking with `keep_default_na=False` (and convert numeric columns yourself), or `fillna("None")` right after loading.
2. **`pff_role` capitalisation differs from the README.** The data uses `Pass`, `Pass Block`, `Pass Route`, `Pass Rush`, `Coverage`. The README says "Pass block", "Pass route", "Pass rush". Match on the data values.
3. **Duplicate snap and throw events, and the auto ones can be wrong.** 3,756 plays have both `ball_snap` and `autoevent_ballsnap`; 3,677 have both `pass_forward` and `autoevent_passforward`. They usually differ by 1–2 frames, but 190 plays have snaps more than 2 frames apart. Example: 2021090900/3406 has `autoevent_ballsnap` at frame 6, before two `line_set` events, while the real `ball_snap` is at frame 146. **Rule: use the manual event (`ball_snap`, `pass_forward`) when present; fall back to the `autoevent_*` only when the manual one is missing.** Keep one flag per moment.
4. **24 plays have no snap event at all** (and 1 play has only `autoevent_ballsnap`). Exclude them from the replay list, or infer the snap from the ball's first movement and mark it as inferred.
5. **`nflId` is NA on ball rows**, and `team == "football"`.
6. **Events are on every row of the frame** (players and ball). Read events from ball rows to avoid 23× duplicates.

## Coordinates and angles (verified)

- `x` 0–120 along the field including end zones, `y` 0–53.3 across.
- `absoluteYardlineNumber` is the line of scrimmage **in the raw `x` frame for both play directions**. At the (manual) snap, the ball's `x` is close to it: median offset +0.28 yd for left plays and −0.28 yd for right plays; within 1.5 yd on 94.5% of plays and within 2.5 yd on 98.8%.
- Angles `o` and `dir`: 0° points to +y, increasing clockwise. Unit vector = (sin θ, cos θ). Checked against frame-to-frame displacement for players moving faster than 4 yd/s: 99% sign agreement on x, 98% on y.
- Orientation `o` shows no systematic offset. For players moving faster than 4 yd/s, the median |o − dir| is 35°, and 36% sit between 45° and 135°. That spread is expected (head turns, backpedalling defensive backs), so don't "fix" it.

### Normalisation (offense always moves toward +x)

```
if playDirection == "left":
    x'   = 120 - x
    y'   = 53.3 - y
    o'   = (o + 180) % 360
    dir' = (dir + 180) % 360
    los' = 120 - absoluteYardlineNumber
else:
    los' = absoluteYardlineNumber
firstDownX' = los' + yardsToGo
```

After normalisation the offense attacks +x. The offense's **left is +y**. If you draw +y upward, the offense's left side is at the top of the screen, which matches TV broadcasts when the offense moves left to right.

## Timing (verified)

| Measure | Value |
|---|---|
| Frame rate | 10 Hz |
| Frames before the snap | median 5 (0.5 s), max 172 |
| Frames per play | min 19, median 39, max 203 |
| Time from snap to throw | median 2.7 s, mean 2.95 s, IQR 2.3–3.3 s, max 9.8 s |
| Frames after the end event | **exactly 5 frames (0.5 s) after the earliest end event** (manual or auto throw, `qb_sack`, `qb_strip_sack`, `run`) on 8,555 of 8,557 plays (99.98%). Measured from the manual-first end event the tail is 3–5 frames: {5: 5,849, 4: 2,414, 3: 284, 2: 8, 0: 2}, so only 96.6% fall in 4–6. The 3-frame cases are plays where `autoevent_passforward` fires 2 frames before `pass_forward`. (Re-measured 2026-10-09 in P01.) |

So the replay covers roughly 0.5 s before the snap through 0.5 s after the throw. The 5 post-release ball frames are useful: they give the throw direction and release speed.

**Ball release speed** (first 0.5 s after `pass_forward`, 20-game sample, n = 1,284): median 24.7 yd/s, IQR 21.8–27.3 yd/s. Use this to set the default ball speed in the arrival model, or estimate it per throw.

## Event vocabulary (ball rows, all games)

| Event | Count | Use |
|---|---|---|
| `ball_snap` | 8,532 | Snap (canonical) |
| `autoevent_ballsnap` | 3,767 | Fallback only when `ball_snap` is missing |
| `pass_forward` | 7,548 | Throw (canonical) |
| `autoevent_passforward` | 3,734 | Fallback only when `pass_forward` is missing |
| `play_action` | 1,977 | Play-action fake |
| `run` | 474 | QB scramble starts (end event on `R` plays) |
| `qb_sack` | 451 | Sack |
| `pass_arrived` | 367 | Only when the ball arrives inside the 0.5 s tail. Rare |
| `autoevent_passinterrupted` | 201 | |
| `man_in_motion` | 177 | Pre-snap |
| `line_set` | 140 | Pre-snap |
| `shift` | 133 | Pre-snap |
| `pass_tipped` | 111 | Batted or tipped pass |
| `first_contact` | 80 | |
| `qb_strip_sack` | 58 | Sack + fumble |
| `pass_outcome_incomplete` | 40 | Rare, short throws only |
| `pass_outcome_caught` | 23 | Rare, short throws only |
| `fumble` | 17 | |
| `fumble_offense_recovered` | 11 | |
| `handoff` | 10 | |
| `huddle_break_offense` | 3 | |
| `tackle` | 3 | |
| `penalty_flag` | 2 | |
| `lateral`, `dropped_pass`, `out_of_bounds` | 1 each | |

End events by play result:

| `passResult` | Plays | Has throw | Has sack | Has `run` |
|---|---|---|---|---|
| C | 4,620 | 4,618 | 0 | 2 |
| I | 2,755 | 2,754 | 0 | 1 |
| IN | 190 | 190 | 1 | 0 |
| R | 449 | 12 | 0 | 443 |
| S | 543 | 30 | 508 | 28 |

## Play-level fields worth using

- `passResult`: C 4,620 · I 2,755 · S 543 · R 449 · IN 190.
- `pff_passCoverage`: Cover-3 2,665 · Cover-1 2,011 · Cover-2 1,085 · Quarters 1,033 · Cover-6 805 · Red Zone 376 · Cover-0 270 · 2-Man 200 · Bracket 47 · Prevent 32 · Goal Line 25 · Miscellaneous 8.
- `pff_passCoverageType`: Zone 5,588 · Man 2,481 · Other 488.
- `offenseFormation`: SHOTGUN 5,481 · EMPTY 1,396 · SINGLEBACK 1,189 · I_FORM 298 · PISTOL 154 · JUMBO 30 · WILDCAT 2 · NA 7.
- `dropBackType`: TRADITIONAL 6,542 · SCRAMBLE 899 · DESIGNED_ROLLOUT_RIGHT 285 · DESIGNED_ROLLOUT_LEFT 149 · SCRAMBLE_ROLLOUT_RIGHT 125 · SCRAMBLE_ROLLOUT_LEFT 23 · DESIGNED_RUN 5 · UNKNOWN 1 · NA 528.
- `down`, `yardsToGo`, `gameClock`, `quarter`, `preSnapHomeScore`, `preSnapVisitorScore`, `personnelO`, `personnelD`, `defendersInBox`, `pff_playAction`.

## PFF scouting

- `pff_role` counts: Coverage 57,765 · Pass Block 46,057 · Pass Route 39,513 · Pass Rush 36,362 · Pass 8,557.
- `pff_positionLinedUp`: alignment at the snap (LWR, SLWR, RWR, TE-L, HB-R, LCB, FS, LEO, DRT…). Use it for formation labels (e.g. 2×2) and for the gravity baseline.
- `pff_nflIdBlockedPlayer`: the **first** defender a blocker engaged. Blocks can switch later (`SW`), so treat it as the initial assignment.
- `pff_blockType` counts: PP 24,697 · PA 6,331 · PT 5,906 · SW 3,025 · CL 2,595 · CH 1,565 · NB 1,352 · PU 886 · SR 501 · BH 443 · UP 308 · PR 295.
- Pressure credit: `pff_hit`, `pff_hurry`, `pff_sack` (defenders); `pff_hitAllowed`, `pff_hurryAllowed`, `pff_sackAllowed`, `pff_beatenByDefender` (blockers). These have no timestamp. Any "block beaten at frame N" flag must be derived from tracking and labelled as a model flag.

## Actual target (from `playDescription`)

Patterns:
- Complete or incomplete: `... pass [incomplete] (short|deep) (left|middle|right) to C.Lamb ...`
- Interception: `... pass (short|deep) (left|middle|right) intended for C.Lamb INTERCEPTED by ...`
- 253 incompletions have no named receiver (e.g. `pass incomplete short right.`). Treat as "no target / throw-away-like" and exclude them from decision-gap stats.
- 19 descriptions mention a throw-away explicitly.

Matching the abbreviated name to `nflId`: compare (first initial, last name) with `displayName` among the offensive players on that play (`pff_role` in Pass Route / Pass Block), then fall back to last name only. Measured result:

| Result | Unique match | No match | No name in description |
|---|---|---|---|
| C | 4,578 | 42 | 0 |
| I | 2,484 | 18 | 253 |
| IN | 183 | 3 | 4 |

About 99% of named targets match uniquely. For the rest, join nflverse play-by-play (`old_game_id` = `gameId`, `play_id` = `playId`) and use `receiver_player_name` or `receiver_player_id`, or drop them.

The description also gives depth (short/deep) and side (left/middle/right). Use them as a sanity check against where the ball went in the 5 post-release frames.

## Allowed supplemental data

The README allows free public data such as nflverse and Pro Football Reference. Useful nflverse play-by-play columns (2021 season): `ep`, `epa`, `air_yards`, `yards_after_catch`, `cpoe`, `receiver_player_name`, `pass_location`, `qb_hit`, `pass_defense_1_player_name`. Use `ep` with `down`, `ydstogo`, `yardline_100` to fit an expected-points lookup for hypothetical options.
