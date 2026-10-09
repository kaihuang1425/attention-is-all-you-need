# Defensive Attention: project brief

## One-line pitch

A play replay tool that shows where the defense is spending its attention, which receiver that attention leaves open, and how the quarterback's actual choice compares with the best option available at each moment before the throw.

## What we are building

1. **A Python pipeline** that turns the Big Data Bowl regional event data (2021 season, weeks 1–8) into per-play JSON files plus a few aggregate tables.
2. **A web app** (React + Vite + TypeScript) with two tabs:
   - **Play analysis:** animated field, decision options table, playback timeline with event flags and filters, option-value chart, receiver attention strips, selected-receiver panel, post-play comparison, protection view.
   - **Aggregate validation:** QB decision gap across all plays, calibration of the catch model, attention sanity checks by coverage.

## The questions the tool answers

- At each frame between snap and throw, how much defensive attention is each offensive player drawing?
- Which receiver had the best expected value at the moment of release, and how did that compare with the receiver the QB actually targeted?
- When did each receiver's window open and close?
- Were non-pass options (scramble, throw away, hold) better than any pass?
- Which blocks failed first, and which rushers were never picked up?

## Non-negotiable rules

These come from a design review. Breaking any of them makes the demo lose credibility with a football audience.

1. **Tracking ends 0.5 s after the throw, sack or scramble.** Never draw a catch point, ball arrival or post-catch movement from tracking. Results (complete, incomplete, yards) come only from `plays.csv` and appear only in the post-play panel.
2. **Never present a counterfactual as a result.** The model's pick has an *expected* value. Its outcome is unknown. Say so in the UI ("Alternative outcome unknown").
3. **11 players per side, always.** Jersey numbers, names and positions come from the data, never invented. The formation label must match the alignment on screen.
4. **Label every model number as a model estimate.** Raw tracking facts and play-by-play facts are shown without that label. Model-derived things (attention, catch probability, EPA, flags such as "window opens") are visibly distinct.
5. **Frame is the unit of time.** 10 Hz. Seeking, flags and charts snap to integer `frameId`. Display time as seconds relative to the snap (`t = (frameId - snapFrame) / 10`, negative before the snap).
6. **Forward-pass legality.** A forward pass is only an option while the QB is behind the line of scrimmage. Once the QB crosses the LOS, remove all forward-pass options. Backward passes (laterals) are legal anywhere but are not modelled; mention this only in docs.
7. **Ball flight time is per receiver.** Projection horizons come from each receiver's own flight time, not a fixed offset.
8. **Colour has one meaning per hue.** See the colour system in `03_UI_SPEC.md`.

## Glossary

| Term | Meaning in this project |
|---|---|
| Attention a(d→j) | Share of defender d's attention on offensive player j at a frame. Each defender's row sums to 1. |
| Attention A(j) | Sum of a(d→j) over all defenders: "defender-equivalents" on player j. |
| Arrival margin | Fastest defender arrival time at the catch point minus ball arrival time. Positive = receiver gets there first. |
| Catch probability | sigmoid(arrival margin / τ), later calibrated against real completions. |
| Option value | Expected EPA of an action: pass to receiver j, scramble, throw away, hold. |
| Decision gap | Expected value of the best option at release minus expected value of the option the QB chose. |
| Gravity (proxy) | Attention a receiver draws above what his alignment and route depth would predict. Heuristic, not causal. |
| Lane clearance | Minimum distance from any defender to the ball's 2D path during flight. 2D proxy: ball height is unavailable. |
| Window | Frames where a receiver's arrival margin stays above a threshold (default +0.3 s). |

## Stack

- **Pipeline:** Python 3.11+, pandas or polars, numpy, scipy, scikit-learn (calibration), pyarrow. Outputs to `app/public/data/`.
- **App:** React 18 + Vite + TypeScript, D3 (scales, shapes only), SVG for players and annotations, a `<canvas>` layer for the heat surface. No UI kit required; plain CSS modules or Tailwind.
- **Tests:** pytest for the pipeline, Vitest for app logic (seek, filters, flag clustering).

## Repository layout

```
/pipeline
  load.py           # read CSVs with correct NA handling, schema checks
  normalise.py      # flip left plays, LOS, first-down line, snap/throw frames
  targets.py        # actual target from playDescription
  attention.py      # soft attention matrix
  arrival.py        # flight time, projected catch point, arrival margin, catch prob
  values.py         # EP lookup, option values, non-pass options
  lanes.py          # lane clearance, gravity proxy
  flags.py          # tracking + model event flags
  export.py         # per-play JSON, aggregates
  tests/
/app
  src/
    data/           # types + loaders
    field/          # field renderer and layers
    panels/         # decision options, selected receiver, post-play, protection
    timeline/       # playback, flags, filters, charts
    validation/     # aggregate tab
  public/data/      # pipeline output
/docs               # this prompt pack
```

## Definition of done for the hackathon

- Three demo plays fully working: one good decision, one missed open receiver, one sack (see `07_DEMO_PLAYS.md`).
- Aggregate tab shows QB decision gap and a calibration plot over all targeted throws.
- Every number on screen is either a data fact or labelled as a model estimate.
- The app runs from `npm run dev` after `python -m pipeline.export`.

## Repo notes (measured on the data, keep up to date)

Commands: `bash scripts/get_data.sh` (data into `data/raw`), optional `bash scripts/get_nflverse.sh` (nflverse 2021 pbp into `data/external`), `pytest`, `python -m pipeline.normalise` (play index), `python -m pipeline.targets` (targets), `python -m pipeline.validate_attention` (P04 checks + grid search, ~3 min), `python -m pipeline.arrival` (P05 report, ~3 min), `python -m pipeline.values` (P06 report, ~3 min), `python -m pipeline.export` (app JSON, demo set). App: `cd app && npm install && npm run dev`, `npm test`, `npm run lint`.

- CSVs live in `data/raw/data/`; `NFL_DATA_DIR` overrides. Intermediates go to `data/derived/*.parquet`.
- Code must run on Python 3.10+ and pandas 2.2+ (including pandas 3). Tests that need data are marked `data` and skip without it.
- Tracking ends **exactly 5 frames after the earliest end event** (manual or auto throw, sack, run) on 99.98% of plays. From the manual-first end event the tail is 3-5 frames (284 plays have 3).
- Snap: manual `ball_snap` wins, auto is a fallback. 22 of the 24 plays with no snap event start tracking after the snap (ball already moving on frame 1): `snapSource = "before_tracking"`, `replayable = False`. 2 are inferred from the first ball movement, 1 uses its auto snap. 8,535 plays are replayable.
- 2021091904/3676 has no `absoluteYardlineNumber`; it is rebuilt from `yardlineSide`/`yardlineNumber` (`losFilled`).
- Targets: 7,307 of 7,308 named targets match uniquely (the miss is a QB catching his own batted pass). Deonte Harris (NO) is listed as "Deonte Harty" in players.csv; `targets.NAME_ALIASES` handles it.
- Throw direction from the post-release ball frames agrees with the parsed side: median +44 deg (left), +1 (middle), -42 (right), offense's left positive. Only 20 of 7,525 throws disagree by more than 40 deg.
- No spikes in the data; 19 explicit throw-aways, all incompletions with no named receiver.
- `pipeline/playdata.py` turns one play into dense arrays (frames x players, normalised). Offense order: route runners then blockers, left to right at the snap; defense: rushers then coverage. Model stages should take a `PlayArrays`.
- Attention (P04): grid search on weeks 1-6 picked sigma 3, k 1, T 0.75 (saved in config.yaml). Both sigma and T sit at the lowest grid value, so the optimum may lie outside the grid. Held-out weeks 7-8: coverage defenders' max weight at the throw is 0.863 in Man vs 0.698 in Zone (Mann-Whitney p = 3e-62); block agreement 84.4% (n = 10,625). With the spec defaults it was 0.655 vs 0.538 and 83.5%.
- Demo 1687 attention: #35 Dean is on #88 Lamb (0.99 at the throw); #31 Winfield is on #89 Jarwin (0.93), not Lamb. #92 and #56 put their top two weights on the linemen who doubled them.
- Arrival (P05): the defender rule is "keep current velocity for tau_react, then run straight at v_max", floored at straight-line time. Observed release speed (median frame-to-frame ball speed after the throw) is 21.9 yd/s (IQR 19.7-23.6) on 7,582 throws; config keeps v_ball = 24 as the spec says, which makes every throw about 10% faster than the data.
- Actual target at release: mean margin +0.26 s (C), +0.02 (I), -0.03 (IN); uncalibrated pCatch 0.65 / 0.51 / 0.48.
- EP (P06): v1 is a closed form per down fitted to nflverse 2021 `ep` (RMSE 0.41); v2 is a smoothed binned table from the same file and is used when `data/external/pbp_2021.parquet` exists. They agree within ~0.3 points.
- P06 check "mean EV of the actual target at release: C > I > IN" FAILS: C +0.05, I +0.16, IN +0.24 (7,282 throws). Raw pCatch still orders C 0.65 > I 0.51 > IN 0.48, and EV predicts realized nflverse EPA monotonically (quintiles -0.15, 0.03, 0.23, 0.42, 0.79; r = 0.24). Incompletions are deeper throws with more upside, so the ordering can fail even for a calibrated model. Raw pCatch is badly overconfident on throws 30+ yd downfield (0.60 vs 0.32 actual). Waiting on a decision before P07.
- Demo 1687 with the arrival model's own pCatch ranked #88 Lamb first at release; with the completion-model catch % now used everywhere, #89 Jarwin ranks first (see below).
- Export (`pipeline/export.py`, schema v1, TS contract `app/src/data/types.ts`): column-oriented frames x players; players ordered QB, route runners, blockers, rushers, coverage. The six demo/showcase plays in `app/public/data` are committed. Re-export after any model change.
- Catch % in the export and the app is the team's completion model from `pass_options.py` (logistic on sep, lane, kernel attention, depth, depth^2; trained wk 1-6, AUC 0.72 on wk 7-8). `pipeline/completion.py` reproduces `passOptions.ts` exactly (checked frame by frame against its exported JSON). pInt is rescaled to that catch %. The arrival model still supplies margin, flight time and catch points, and drives window flags.
- With that catch %, the model pick at release on 1687 is #89 Jarwin (+1.74 EPA) over the actual target #88 Lamb (+0.82); on 3406 the model agrees with Cooper (gap 0). On the 210 sack, Burns is flagged unblocked at 0.2 s and pressure arrives at 1.9 s.
- Flags (`pipeline/flags.py`): tracking events merged manual-first; model flags window_open/close (margin crossings only, not "open at snap"), best_option_change, peak_decision_gap, pressure_arrives, unblocked_rusher, block_beaten (rusher past the blocker on the blocker->QB line and closer to the QB, not already at the snap). 1687 flags Collins beaten by Barrett at 1.9 s, matching PFF.
- App structure: `src/data` (types, loader, derive helpers, passOptions.ts unchanged), `src/field` (SVG surface + heat canvas + SVG foreground; geometry.ts has crop, shadows, influence), `src/panels`, `src/timeline`, `src/state.ts` (reducer). The field is a schematic that fills its panel (see the Glyph note below).
- The app shows scramble, throw away, and hold as contextual choices without comparable EPA estimates. Aggregate validation includes held-out completion calibration and QB pass-target decision gaps; the decision gap covers pass targets only.
- The field is a schematic: `computeCrop` fills the panel, so x and y scales differ (`preserveAspectRatio="none"`). Draw any text or round marker inside `<Glyph>` in `Field.tsx`, which undoes the horizontal stretch; otherwise it renders squashed or stretched.
- `README.md` opens with the submission summary: title, three sentences (what is built, what it reveals, who could use it) and `docs/preview.png`. Everything below the "For judges" line is setup and technical reference. `docs/DEMO_SCRIPT.md` is the two-minute video script. `run-demo.cmd` / `run-demo.sh` start the app.
