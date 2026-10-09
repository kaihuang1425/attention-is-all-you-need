# UI spec

Two mockups exist in `mockups/`:

- `mockup_v1_play042.png` (v1): clean, readable, strong "Why this window?" sentence and receiver attention strips. Problems: 12 offensive and 10 defensive players, duplicate #22, "Trips Right" label that doesn't match the alignment, a timeline that runs to "Catch / end", a fixed +0.5 s projection, an opaque "Score /100", turf texture.
- `mockup_v2_dal_tb_1687.png` (v2): uses the real play (DAL at TB, Q2 05:43, 2nd & 8, gameId 2021090900, playId 1687) with the real 22 players, a full decision table, non-pass options, an option-value chart, per-receiver flight times and honest labelling. Problems: too much text on the field, the actual throw (purple, to #88) is in the legend but not drawn, and dashed yellow lines are ambiguous between attention edges and projections.

**Build v2's content with v1's readability.** The sections below are the merged spec.

## Layout (desktop, 1536 × 1024 reference)

```
┌──────────────────────────────── Header ────────────────────────────────┐
│ DEFENSIVE ATTENTION   [Play analysis] [Aggregate validation]   badge   │
├──────────── Play bar ─────────────────────┬────────────────────────────┤
│ DAL @ TB · Dak Prescott · Q2 05:43 · 2nd & 8 · gameId · playId · formation · personnel │
├───────────────────────────────────────────┬────────────────────────────┤
│                                           │ DECISION OPTIONS           │
│             FIELD (≈ 64% width)           │  pass table                │
│                                           │  non-pass options          │
│                                           ├────────────────────────────┤
│                                           │ SELECTED RECEIVER          │
├───────────── Legend ──────────────────────┤  why this window? (1 line) │
├───────────── Timeline ────────────────────┼────────────────────────────┤
│ controls · scrubber · flags · filter chips│ POST-PLAY (play-by-play)   │
│ option-value chart (shared x)             │ decision gap (expected)    │
│ attention strips (collapsible, shared x)  │ PROTECTION (button/drawer) │
└───────────────────────────────────────────┴────────────────────────────┘
```

Below 1100 px wide, the right column moves under the field. Below 700 px, the timeline chart and strips collapse into tabs.

## Play bar

- Teams as `AWAY @ HOME`, QB name, quarter and clock, down and distance, score, `gameId`, `playId`.
- Formation label derived from `pff_positionLinedUp` (count receivers left vs right of the ball, TE included: e.g. 2×2, 3×1, Empty 3×2), plus `offenseFormation` (SHOTGUN) and `personnelO`.
- Coverage label (`pff_passCoverage`) is **hidden by default** behind a "Reveal coverage" toggle, so the presenter can ask the audience first.
- Play picker: dropdown with search by team, QB, week; starred demo plays at the top.

## Field

Rendering order (bottom to top):

1. **Field surface:** flat, dark, desaturated green-grey. No turf texture. Yard lines every 5 yd, numbers every 10 yd, hash marks. Crop to LOS − 12 yd through LOS + 35 yd by default, auto-extending to fit all players. Show the yard numbers as the real field shows them (e.g. TB 25), not raw x.
2. **Heat layer (canvas):** coverage influence surface. A 1 × 1 yd grid with the value = sum over defenders of a Gaussian centred on the defender's position + 0.5 s × velocity. Sequential single-hue ramp, semi-transparent, max opacity 0.45. Toggle: off / defense influence / offense control (diverging).
3. **LOS** (blue line with "LOS · TB25" tag) and **first-down line** (yellow with "1st down · TB17" tag).
4. **Attention edges:** a line from each defender to each offensive player with a(d→j) ≥ 0.15. Width 1–6 px proportional to weight, colour = attention ramp, solid line, no arrowheads. Only edges to the **selected receiver** are at full opacity; others are at 25%.
5. **Projected catch points:** dashed circle at each receiver's projected catch point, with a small label "1.3 s flight". Only for the top 3 options plus the selected receiver.
6. **Throw paths:**
   - Model pick: cyan dashed line from QB to its projected catch point, ending in an arrow.
   - Actual target: magenta dashed line from QB to the actual target's projected catch point. **Shown only after the throw frame**, or always if "Show actual" is on. This was missing in v2.
7. **Players:** offense = filled light discs with dark jersey numbers. Defense = dark diamonds with light numbers. 11 each. QB marked with a thicker ring. Ball as a small brown ellipse.
8. **Labels:** jersey numbers only on the field. Names, flight times, attention splits and clearance appear on hover or for the selected receiver. At most 3 callouts visible at once.

Hover a receiver: highlight his incoming attention edges, show a tooltip with name, A(j), margin, pCatch. Hover a defender: show his attention split as a mini bar ("#24: #1 0.35 · #13 0.65").

## Decision options panel

Header "DECISION OPTIONS · model estimates at 1.8 s" (time follows the scrubber).

Pass table, sorted by expected EPA, one row per eligible receiver:

| Column | Content |
|---|---|
| Option | Jersey + last name. "MODEL PICK" chip on the top row |
| Catch | pCatch, % |
| Exp EPA | signed, 2 decimals |
| INT | % |
| Arrival margin | "Ball 1.0 s / Def 1.5 s" with the signed margin below. Positive in `--positive`, negative in `--negative`, always with a + or − sign so colour isn't the only signal |
| 1st down | ✓ + marker yard line, or "4 yd short" |

Non-pass options below: Scramble (EPA, yards vs first down), Throw away (EPA, "no gain"; grounding warning when applicable), Hold (sack risk in next 0.5 s as a segmented bar + text like "Right edge closing").

Rows are clickable: clicking selects that receiver on the field.

## Selected receiver panel

- Name and number.
- Attention: "0.6 defender-equivalents (play average 1.4)". Numbers, never LOW/HIGH words alone.
- Lane: "min projected clearance 1.2 yd · 2D proxy".
- Gravity badge if applicable: "Gravity +0.8 · proxy".
- **Why this window?** One generated sentence from the top two reasons, e.g. "#88 draws two defenders deep; #1 has 0.5 s of room underneath." Template-based, not LLM-generated at runtime.

## Post-play panel

- Title "POST-PLAY · play-by-play data".
- "Observed: Prescott → Lamb #88 · Incomplete" with yards from `playResult`.
- Expected decision gap (illustrative until the model is calibrated): chosen option EPA, model pick EPA, gap.
- Footer: "Alternative outcome unknown. This shows what the model would have chosen, not a predicted result."

## Protection view

Opened from the Hold row or a "Protection" button. A drawer or overlay on the field that:

- draws each blocker → first-blocked rusher pair from `pff_nflIdBlockedPlayer`, with block type codes (PP, PT, SW…) on hover;
- marks rushers with no assigned blocker;
- colours each rusher's path to the QB by STRAIN;
- marks the `block_beaten` flag frame on the timeline;
- lists PFF credit (`pff_hurry`, `pff_beatenByDefender`, …) as data facts, separate from model flags.

## Aggregate validation tab

1. **QB decision gap:** dot plot per QB (min 50 targeted throws), mean gap with 90% bootstrap interval. Filter by coverage and time-to-throw bucket.
2. **Calibration:** reliability curve of pCatch vs completion on held-out weeks 7–8, with Brier score.
3. **Attention sanity:** distributions of max defender attention for Man vs Zone; block agreement rate.
4. **Cold zones:** average attention density on the normalised field by coverage, with the release-frame positions of the best option and of the actual target overlaid.

Every chart has a one-line caption saying what it shows and the sample size.

## Colour system

One meaning per hue. Check contrast in both light and dark themes (dark is the default).

| Token | Meaning | Suggested |
|---|---|---|
| `--offense` | Offensive players | #F2F0EA fill, #111 text |
| `--defense` | Defensive players | #1B2A44 fill, #E8EEF8 text |
| `--attention-0…4` | Attention ramp (edges, strips, heat) | sequential amber ramp |
| `--model-pick` | Model pick path, chip, row outline | cyan #22D3EE |
| `--actual` | Actual throw path, observed label | magenta #E879F9 |
| `--los` | Line of scrimmage | #3B82F6 |
| `--first-down` | First-down line | #FACC15 |
| `--positive` / `--negative` | Signed margins | cyan-tinted / orange-red, always with a sign |
| `--flag-tracking` | Tracking-event flags | neutral light grey |
| `--flag-model` | Model flags | hollow, in the attention amber |

Do not use red/green as a pair. Do not reuse amber for anything except attention.

## Typography and density

- One sans family with tabular numerals for tables and the time readout.
- Field labels ≥ 12 px, table text ≥ 13 px, panel headers 12 px caps with letter-spacing.
- No more than 3 floating callouts on the field at once.

## Badges and honesty labels

- Header badge: "MODEL VALUES ILLUSTRATIVE" until calibration exists, then "MODEL v0.x · calibrated wk 1–6".
- Footer: "Positions: NGS tracking · Roles: PFF · Result: play-by-play · Estimates: model".
- Legend entries for everything drawn on the field, including "Actual target (after throw)".
