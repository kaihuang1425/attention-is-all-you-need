# Defensive Attention: project brief

> Paste this file into your coding agent as standing context (for example as `CLAUDE.md` at the repo root, or as the first message of every session). Every build prompt in `05_BUILD_PROMPTS.md` assumes the agent has read it.

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
