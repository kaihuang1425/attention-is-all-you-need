# Defensive Attention: Safety Pull + Pass Options

Defensive Attention is a play-replay tool built on 2021 NFL Next Gen Stats tracking (Weeks 1–8, 7,541 throws). Every 0.1 s from snap to throw, it shows where the defense is focused and which receiver is the best throw. Its core metric, Safety Pull, measures how far the deep safeties move toward each route runner: outside receivers 8–18 yards downfield drag them up to twice their fair share, and against single-high shells a teammate's pull gives the targeted receiver +0.25 yards of separation and +4 points of completion rate (no effect against two-high). Pass options are ranked by a completion model learned from real targeted throws (held-out AUC 0.72) combined with yards and first-down value, and on held-out weeks, when QBs threw to our #1 option they gained 10.0 yards and a first down 51% of the time, versus 6.5 yards and 33% otherwise. Coaches can use it to design decoy routes against single-high looks, scouts to value receivers who create space without being targeted, and broadcasters to show viewers who really opened the play.

![Safety Pull heatmap](output/safety_pull_heatmap.png)
![Decoy effect](output/decoy_effect.png)
![Pull Over Expected leaderboard](output/pull_over_expected.png)

## Safety Pull (`safety_pull.py`)
- **Deep safeties:** players in a safety alignment (PFF `FS`/`SS` variants) who line up at least 7 yards deep at the snap.
- **Pull:** on every frame from snap to throw, the safety's own movement toward each route runner is measured. The route runner he moves toward most gets the credit, so receiver movement doesn't count.
- **Safety Pull index:** share of that movement × number of route runners; 1.0 is an even split.
- **Pull Over Expected:** the heatmap is the expected model. A receiver's index minus the average for routes ending in the same 3×3-yard cell against the same shell is his own contribution, the same logic as the NBA's Gravity stat.
- **Decoy effect:** OLS regression per shell. Target separation at the throw is regressed on whether a teammate pulled a safety 2+ yards, controlling for time to throw, target depth and the target's own pull.

## Pass Options (`pass_options.py`)
For each route runner, every frame from snap to throw:

| Metric | Definition |
|---|---|
| `sep` | Distance to the nearest defender (yds, capped at 10) |
| `attention` | Defender-equivalents: each coverage defender's focus is split across receivers plus a "nobody" option (Gaussian kernel, σ = 3 yds), so no defender is counted twice |
| `lane` | Closest defender to the middle 25–85% of the QB→receiver line (yds) |
| `depth`, `reaches_sticks` | Yards past the line of scrimmage, and whether that reaches the line to gain |
| `safety_pull` | Yards the deep safeties have moved toward him since the snap |

- **Completion model:** logistic regression on separation, lane, attention, depth and depth², fitted on targeted throws at the moment of the throw. It is trained on Weeks 1–6 and tested on Weeks 7–8: AUC 0.72, Brier 0.201 vs 0.232 for a constant baseline. Separation and depth carry almost all the weight; lane and attention add little once those are known. The coefficients and calibration table are in `output/model.json`.
- **Best value (default ranking):** expected yards = P(complete) × (depth + 3 yds assumed YAC + 5-yd bonus if it reaches the sticks).
- **Safest throw (backup ranking):** P(complete) alone. On held-out weeks, completion was 77% when QBs threw to this #1 vs 58% otherwise.
- **Pocket pressure:** nearest pass rusher's distance to the QB and closing speed, shown separately. It's the same for every receiver, so it can't change the ranking.
- **"Why this window" text:** generated from the numbers for the #1 option, e.g. who draws the most defenders and where the safety has moved.

Showcase plays are picked automatically from the held-out weeks: a missed window, a decoy at work, and a play where the model and QB agree on a big gain.

## Run
```
python safety_pull.py  --data <data folder> --out output        # ~2 min: Safety Pull charts + output/route_pull.csv
python pass_options.py --data <data folder> --out output        # ~2 min: model.json + output/plays/*.json
```
`<data folder>` contains `games.csv`, `plays.csv`, `players.csv`, `pffScoutingData.csv` and `tracking/`. Requires `pandas`, `numpy` and `matplotlib`. Use `--plot-only` (safety_pull) or `--reuse` (pass_options) to skip recomputation.

## Frontend data format (`output/plays/play_<gameId>_<playId>.json`)
- `meta`: down, distance, clock, teams, formation, coverage, `los_x`, `first_down_x`, `snap_frame`, `throw_frame`, `hz` (10). The offense always attacks toward +x; the field is 0–120 by 0–53.3 yds.
- `players[]`: `id`, `jersey`, `name`, `position`, `side` (offense/defense), `role` (QB / route / block / coverage / rush).
- `frames[]`: `frame`, `t` (seconds from the snap), `phase` (pre_snap / live / post_throw), `ball {x,y}`, and `players[] {id, x, y, px, py}`, where `px,py` is the +0.5 s projection.
  - Live frames also carry `receivers[]` with all metrics plus `completion_pct`, `expected_yards`, `rank_value` and `rank_safe`, along with `pressure {nearest_rusher_yds, closing_speed, level 0–7, side, text}`, `why_value` and `why_safe`.
- `result`: actual target and outcome, `model_pick_value`, `model_pick_safe`. Outcomes for receivers who weren't targeted are unknown.
- `output/plays/index.json` lists the showcase plays with their labels.

Tracking ends 0.5 s after the throw, so the replay stops there.

## Limitations
- In zone coverage, safeties widen to their areas regardless of the receiver. Pull Over Expected controls for this by spot and shell, but not by play call.
- The completion model only sees outcomes of throws that were actually made, so values for receivers who weren't targeted are estimates.
- "QB threw to our #1" results are associations, not proof the model is better than the QB. The value ranking favours deeper throws, which gain more yards when completed.
- There is no ball height, catch point or post-throw tracking, so we don't model catch windows or arrival margins.
- Intended receivers are parsed from play descriptions (93% matched).
