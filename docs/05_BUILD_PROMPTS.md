# Build prompts

Run these in order with a coding agent. Each prompt lists what to attach, the prompt text to paste, and the checks that must pass before moving on. The prompt text sits inside `~~~prompt` fences so it can be copied directly or parsed (`prompts.jsonl` is generated from this file).

Before the first prompt, give the agent `00_PROJECT_BRIEF.md` as standing context.

---

## P00 · Scaffold the repository

- **Stage:** setup
- **Depends on:** none
- **Attach:** 00_PROJECT_BRIEF.md

~~~prompt
Set up the repository described in the project brief.

1. Create the folder layout from the brief: /pipeline (Python package with tests/), /app (React 18 + Vite + TypeScript), /docs.
2. Copy this prompt pack into /docs.
3. Pipeline: pyproject.toml with pandas, numpy, scipy, scikit-learn, pyarrow, pyyaml, pytest. Add pipeline/config.yaml holding every model parameter from 02_MODEL_SPEC.md with its starting value and a one-line comment.
4. Data: add a script scripts/get_data.sh that runs
   GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 https://github.com/ThompsonJamesBliss/nfl-big-data-bowl-regional-event-data data/raw
   and is idempotent (skips if the folder exists and its origin matches). Add data/raw to .gitignore. The data is about 1 GB.
5. App: Vite React TS template, Vitest configured, ESLint + Prettier, a src/ layout matching the brief (data/, field/, panels/, timeline/, validation/).
6. Root README with the three commands: get data, run pipeline, run app.

Do not write any model code yet. Keep the scaffold minimal.
~~~

**Done when:**
- `bash scripts/get_data.sh` clones the data and a second run is a no-op.
- `pytest` and `npm test` both run (zero tests is fine).
- `npm run dev` shows an empty page.

---

## P01 · Load the data and assert the known facts

- **Stage:** pipeline
- **Depends on:** P00
- **Attach:** 01_DATA_SPEC.md

~~~prompt
Write pipeline/load.py with functions load_games, load_plays, load_players, load_pff, load_tracking(gameId) and iter_tracking().

Requirements:
- Read tracking with keep_default_na=False so the event value "None" stays a string. Convert x, y, s, a, dis, o, dir to float and nflId to nullable Int64 ("NA" on ball rows).
- Use dtypes that keep memory low (float32 for kinematics, category for team, event, playDirection).
- Match pff_role on the values actually present: "Pass", "Pass Block", "Pass Route", "Pass Rush", "Coverage". Note in a comment that the README spells them differently.

Then write pipeline/tests/test_data_facts.py that asserts the facts in 01_DATA_SPEC.md:
- 122 games, all season 2021, weeks 1–8.
- 8,557 plays; passResult counts C 4620, I 2755, S 543, R 449, IN 190.
- 11 players per team on every frame (sample 10 games).
- absoluteYardlineNumber within 2.5 yd of the ball x at the snap for at least 98% of plays (sample 10 games; use the manual ball_snap frame). The full data measures 98.8%.
- Tracking ends 4–6 frames after the end event (pass_forward, falling back to autoevent_passforward; qb_sack; qb_strip_sack; run) on at least 99% of plays (sample 10 games).
- The angle convention: for players moving faster than 4 yd/s, sign(sin(dir)) matches sign(dx) for at least 97% of frames.

If any assertion fails, print the measured value and stop. Do not loosen a threshold without telling me which one and why.
~~~

**Done when:**
- All fact tests pass, or failures are reported with measured values.
- Loading one tracking file takes under 3 s.

---

## P02 · Normalise plays and build the play index

- **Stage:** pipeline
- **Depends on:** P01
- **Attach:** 01_DATA_SPEC.md, 04_TIMELINE_FLAGS_SPEC.md

~~~prompt
Write pipeline/normalise.py.

1. normalise_tracking(df, play_row): flip plays with playDirection == "left" so the offense always attacks +x, using the formulas in 01_DATA_SPEC.md (x' = 120 - x, y' = 53.3 - y, o' and dir' + 180 mod 360). Add vx, vy from s and dir using the verified convention (vx = s·sin(dir), vy = s·cos(dir)).
2. play_frame_index(df): from ball rows, find
   - snapFrame: the manual ball_snap frame. Use autoevent_ballsnap only if ball_snap is missing. Do NOT take the earliest of the two: auto snaps can be badly wrong (2021090900/3406 has autoevent_ballsnap at frame 6 but the real ball_snap at frame 146). If both are missing, infer from the first frame where the ball moves more than 0.3 yd from its starting spot and set snapInferred = true.
   - endFrame and endType: pass_forward (falling back to autoevent_passforward) for a throw, qb_sack / qb_strip_sack for a sack, run for a scramble. Take the earliest of these end types.
   - lastFrame.
   Merge duplicate manual/auto events into one canonical event per moment, keeping the manual frame.
3. los_x' and firstDown_x' in normalised coordinates. Also produce display labels for the real field ("TB 25", "TB 17", "50") from the normalised x and the team on each side.
4. Write data/derived/play_index.parquet with one row per play: gameId, playId, week, teams, QB nflId and name, down, yardsToGo, quarter, gameClock, scores, formation label (count receivers left vs right of the ball using pff_positionLinedUp, TE included, e.g. "2x2", "3x1", "Empty 3x2"), offenseFormation, personnel, coverage, coverage type, passResult, playResult, snapFrame, endFrame, endType, timeToThrow, snapInferred, frame count.

Tests:
- For 2021090900/1687: snapFrame 6, endFrame 38, endType throw, timeToThrow 3.2, LOS label "TB 25", first-down label "TB 17", formation "2x2".
- For 2021090900/3406: snapFrame 146 (not 6), endFrame 173, timeToThrow 2.7.
- For 2021091202/210: snapFrame 6, endFrame 34, endType sack.
- For every play in a 10-game sample, all offensive players have x' within 15 yd behind los_x' at the snap.
~~~

**Done when:**
- The play index covers 8,533+ plays with a snap (24 have none in the raw data; they are either inferred or excluded and counted).
- The demo play test passes.

---

## P03 · Extract the actual target

- **Stage:** pipeline
- **Depends on:** P02
- **Attach:** 01_DATA_SPEC.md

~~~prompt
Write pipeline/targets.py.

- Parse playDescription for the receiver: " to F.Last" on C and I, " intended for F.Last" on IN. Also parse depth (short/deep) and side (left/middle/right).
- Match the abbreviated name to an nflId among the offensive players on that play (pff_role in Pass Route or Pass Block): first by (first initial, last name) against displayName, ignoring suffixes Jr/Sr/II/III/IV/V; then by last name only if that gives a unique result.
- Output targetNflId, targetMatch ("unique", "none", "multi", "no_name"), depth, side.
- Cross-check with the ball: using the 5 post-release ball frames, compute the throw direction. Flag plays where the parsed side (left/middle/right, from the offense's view) disagrees with the ball direction by more than 40 degrees.

Report the match table by passResult. Expected roughly: C 4,578 unique, I 2,484 unique and 253 no_name, IN 183 unique. Print 10 random "none" cases so I can see why they fail.

Optional: if an nflverse play-by-play file for 2021 is present at data/external/pbp_2021.parquet, use receiver_player_name to resolve the remaining cases (join old_game_id = gameId, play_id = playId).
~~~

**Done when:**
- About 99% of named targets match uniquely.
- The demo play resolves to CeeDee Lamb (#88, nflId 52425).

---

## P04 · Soft attention matrix

- **Stage:** pipeline
- **Depends on:** P02
- **Attach:** 02_MODEL_SPEC.md (sections 1–2)

~~~prompt
Write pipeline/attention.py implementing section 2 of 02_MODEL_SPEC.md.

- attention_for_play(frames) returns, for every frame, an 11 × (10 + 1) matrix: defenders × (offensive non-QB players + an "unattached" column). Rows sum to 1.
- Smooth orientation over 3 frames (circular mean) before use.
- Vectorise with numpy across frames; a full play should take under 50 ms.
- Expose A(j) per frame and a(d→j) per frame.

Validation script pipeline/validate_attention.py:
1. Man vs Zone: distribution of each coverage defender's maximum non-unattached weight at the release frame. Report medians and a Mann-Whitney test.
2. Blocks: for blockers with pff_nflIdBlockedPlayer, the share of cases where that rusher's top attention target in the first 1.0 s after the snap is that blocker (or any blocker who also lists the same rusher).
3. Grid search σ ∈ {3, 4, 5, 6}, k ∈ {0.5, 1, 1.5}, T ∈ {0.75, 1, 1.5} on weeks 1–6 to maximise (Man median − Zone median) + block agreement. Report the chosen values on weeks 7–8. Save them to config.yaml.

Print the attention matrix at the release frame of 2021090900/1687 with jersey numbers as row and column labels.
~~~

**Done when:**
- Man median max-weight is clearly above Zone (report both).
- Block agreement is reported (aim above 60%; report whatever it is).
- Demo play: #35 and #31 put meaningful weight on #88 near release; #92 and #56 point at two linemen each early on.

---

## P05 · Arrival margin and catch probability

- **Stage:** pipeline
- **Depends on:** P02
- **Attach:** 02_MODEL_SPEC.md (section 3)

~~~prompt
Write pipeline/arrival.py implementing section 3 of 02_MODEL_SPEC.md.

For every frame from snap to endFrame and every Pass Route player j:
- Solve for the catch point p and ball time t_ball by fixed-point iteration (3 iterations) using the receiver's position and velocity. Clamp p inside the field (0.5 ≤ y' ≤ 52.8, x' ≤ 119.5).
- Compute defender arrival times with reaction time and max speed, the margin, pCatch and pInt.
- Store p, t_ball, margin, pCatch, pInt, nearest defender id at p.

Estimate v_ball per thrown play from the 5 post-release ball frames and report the distribution. Keep the config default (24 yd/s) for frames before the throw.

Unit tests:
- A receiver alone on the field with no defender within 30 yd has margin > 1.5 s and pCatch > 0.95.
- A receiver with a defender 1 yd away and moving the same way has margin < 0.
- Doubling v_ball reduces t_ball for every receiver.
- Forward-pass options are removed on frames where the QB's x' > los_x'.

Print a table for 2021090900/1687 at frames 24 (t = 1.8 s) and 38 (release): receiver, t_ball, defender time, margin, pCatch.
~~~

**Done when:**
- Tests pass.
- The demo table prints and the numbers look physically sensible (t_ball between 0.3 and 2.5 s, margins mostly between −1 and +2 s).

---

## P06 · Expected points and option values

- **Stage:** pipeline
- **Depends on:** P05
- **Attach:** 02_MODEL_SPEC.md (sections 4, 8)

~~~prompt
Write pipeline/values.py.

1. EP lookup. Version 1: a hand-built function of down, distance and yardline (document the source of every constant). Version 2: if data/external/pbp_2021.parquet exists, fit a smoothed EP table from nflverse ep against down, ydstogo and yardline_100 (binned means smoothed across yardline). Use version 2 when available and say which one is active in the export metadata.
2. value_complete(j): EP after a completion at the catch point plus expected YAC (config), handling first downs and touchdowns (catch point past the goal line = TD).
3. EV_pass(j) per section 4, including incomplete and interception branches.
4. Decision gap at the release frame per section 8. For R plays the chosen option is scramble; for S plays it is hold (the sack happened).

Report: distribution of EV_pass for the actual target at release, by passResult. Completed passes should have a higher mean EV than incompletions. If not, stop and tell me.
~~~

**Done when:**
- Mean EV for C targets > I targets > IN targets at release.
- Values for the demo play print for every receiver at frame 38.

---

## P07 · Non-pass options and sack hazard

- **Stage:** pipeline
- **Depends on:** P04, P06
- **Attach:** 02_MODEL_SPEC.md (section 5)

~~~prompt
Implement the non-pass options in pipeline/values.py (or a new options.py) per section 5 of 02_MODEL_SPEC.md.

- Scramble: find the QB's best running lane (sample 9 directions between −60° and +60° from +x), compute how far he can go before a defender can reach the lane, convert to EP.
- Throw away: EP of next down at the same spot. Add groundingRisk = true when the QB is inside the tackle box (between the original tackle positions at the snap) and no eligible receiver is within 5 yd of any sideline landing point.
- Sack hazard: logistic regression on frames with features from section 5. Label = sack or QB hit within the next 5 frames (use the qb_sack / qb_strip_sack frame, and pff_sack / pff_hit for the play). Train on weeks 1–6, report AUC and calibration on weeks 7–8.
- Hold: value per section 5 using the hazard.
- Unblocked rushers: rushers whose nflId is not any blocker's pff_nflIdBlockedPlayer.
- STRAIN per rusher per frame (−Δd/Δt ÷ d), clipped to a sensible range.

Print, for 2021091202/210 (the sack demo), the hold value and sack risk over time and the frame where scramble first beats every pass option (if it does).
~~~

**Done when:**
- Hazard model AUC reported on weeks 7–8.
- Sack demo shows rising sack risk before the qb_sack frame.

---

## P08 · Lane clearance and gravity

- **Stage:** pipeline
- **Depends on:** P04, P05
- **Attach:** 02_MODEL_SPEC.md (section 6)

~~~prompt
Write pipeline/lanes.py.

- laneClearance(j, frame): straight path from QB to the catch point, 10 samples; each defender's position projected to the time the ball passes each sample; return min distance and the defender responsible. Add battedRisk = true if a defensive lineman is within 2 yd of the QB and within 1 yd of the path at the first sample.
- gravity(j) at release: A(j) minus the mean A for the same (pff_positionLinedUp, depth bucket, coverage type) bucket, computed over all plays. Store the bucket size; return null when the bucket has fewer than 30 plays.

Both outputs carry a "proxy" label in the export.
~~~

**Done when:**
- Every receiver on every play has a clearance value from snap to release.
- Gravity buckets are reported with sizes.

---

## P09 · Event flags

- **Stage:** pipeline
- **Depends on:** P02, P05, P06, P07
- **Attach:** 04_TIMELINE_FLAGS_SPEC.md, 02_MODEL_SPEC.md (section 9)

~~~prompt
Write pipeline/flags.py producing the Flag[] array defined in 04_TIMELINE_FLAGS_SPEC.md for each play.

Tracking flags:
- Read events from ball rows only.
- Merge ball_snap/autoevent_ballsnap and pass_forward/autoevent_passforward into one flag each, at the manual event's frame (auto only as a fallback). Keep the auto frame in the tooltip if it differs by more than 2 frames.
- Assign groups exactly as the spec's tables. Unknown events go to "play" and are counted in a log.
- Mark an inferred snap with inferred = true.

Model flags per section 9 of 02_MODEL_SPEC.md, with 2-frame hysteresis. Each model flag has a reason string, e.g. "#1 margin crosses +0.3 s (now +0.42 s)".

Stable ids: "trk-{frameId}-{type}" and "mdl-{frameId}-{type}-{nflId}".

Tests:
- 2021090900/1687 has exactly one snap flag at frame 6 and one throw flag at frame 38.
- 2021090900/3406 has one snap flag at frame 146, two line_set flags (frames 38 and 58) and one throw flag at frame 173.
- No play has two snap flags.
- Every flag frameId is within [1, lastFrame].
~~~

**Done when:**
- Tests pass.
- A summary prints counts of each flag type across all plays.

---

## P10 · Export per-play JSON and aggregates

- **Stage:** pipeline
- **Depends on:** P03–P09
- **Attach:** 03_UI_SPEC.md, 04_TIMELINE_FLAGS_SPEC.md

~~~prompt
Write pipeline/export.py and a command `python -m pipeline.export [--plays demo|all] [--games ...]`.

Per play, write app/public/data/plays/{gameId}_{playId}.json with:
- meta: everything in the play index plus display labels, coverage, formation label, model version, EP version, illustrative flag (true until calibration exists).
- players: nflId, jersey, name, position, team side, pff_role, pff_positionLinedUp, block pairing and block type, PFF pressure credit.
- frames: per frame t, frameId, positions (x', y', o', dir', s) rounded to 2 decimals, ball position.
- model per frame: A(j), sparse attention edges with weight ≥ 0.05, per receiver {p, t_ball, margin, pCatch, pInt, EV, clearance}, non-pass options {scramble, throwAway, hold, sackRisk}, STRAIN per rusher.
- flags: Flag[].
- result (post-play only): passResult, playResult, description, actual target nflId, decision gap.

Keep each file under 400 KB; gzip-friendly (no repeated keys inside arrays, use column arrays).

Aggregates in app/public/data/aggregate/:
- qb_decision_gap.json (QB, n, mean gap, 90% bootstrap CI), with filters precomputed by coverage and time-to-throw bucket.
- calibration.json (bins, predicted, observed, n, Brier before/after).
- attention_sanity.json (Man vs Zone distributions, block agreement).
- cold_zones.json (coverage → 1-yd grid of mean attention density near the LOS).
- index.json (play list for the picker: ids, teams, QB, week, down/distance, result, demo star).

Write a TypeScript types file app/src/data/types.ts that matches the JSON exactly, and a JSON schema test in pytest that checks a demo file against it.
~~~

**Done when:**
- The three demo plays export.
- `--plays all` finishes on a laptop in under 20 minutes (report the time).
- The schema test passes.

---

## P11 · App shell, design tokens and data loading

- **Stage:** app
- **Depends on:** P10
- **Attach:** 03_UI_SPEC.md, both mockups

~~~prompt
Build the app shell from 03_UI_SPEC.md, using the two attached mockups as visual reference (v2 for content, v1 for readability).

- Header with the two tabs (Play analysis, Aggregate validation) and the honesty badge.
- Play bar with every field listed in the spec. Coverage hidden behind a "Reveal coverage" toggle.
- CSS custom properties for every colour token in the spec's table, with a dark default and a light theme. Tabular numerals for numbers.
- Data layer: fetch index.json and a play file, typed with app/src/data/types.ts. Show loading and error states.
- A single store (Zustand or React context + reducer) holding: play, currentFrame, isPlaying, speed, selectedNflId, hoveredNflId, flagFilters, layer toggles. URL sync for game, play, frame, flags, sel (see 04_TIMELINE_FLAGS_SPEC.md "Deep links").
- Layout grid matching the spec, responsive at 1100 px and 700 px.

Leave the field, panels and timeline as labelled placeholders.
~~~

**Done when:**
- Loading `?game=2021090900&play=1687` shows the correct play bar: "DAL @ TB · Dak Prescott · Q2 05:43 · 2nd & 8", formation 2x2, coverage hidden.

---

## P12 · Field renderer

- **Stage:** app
- **Depends on:** P11
- **Attach:** 03_UI_SPEC.md (Field section), both mockups

~~~prompt
Build the field component per the Field section of 03_UI_SPEC.md.

- SVG for markings, players, edges, paths and labels; one <canvas> underneath for the heat layer.
- Flat dark field, yard lines, real yard numbers ("TB 25" style tags for LOS and first down), hash marks. Default crop LOS − 12 to LOS + 35, extending to fit every player in the play.
- Players: 11 offense discs and 11 defense diamonds, jersey numbers from data, QB ring, ball. Render positions for currentFrame; interpolate between frames only during playback.
- Heat layer: defense influence (Gaussian at position + 0.5 s × velocity), toggle off / defense influence / offense control.
- Attention edges for a(d→j) ≥ 0.15, width by weight, full opacity only for the selected receiver.
- Projected catch circles with "1.3 s flight" labels for the top 3 options and the selected receiver.
- Model pick path (cyan dashed) and actual target path (magenta dashed, only after the throw frame or with "Show actual" on).
- Hover tooltips for receivers and defenders as specified. Max 3 visible callouts.
- Legend under the field listing every mark type, including "Actual target (after throw)".

Add a dev-only assertion that renders a red warning if a frame has anything other than 11 players per side.
~~~

**Done when:**
- The demo play renders 22 players with the right numbers at frame 6 (snap) and frame 38 (throw).
- Edges, catch circles and both paths appear as specified.
- 60 fps during playback on a laptop.

---

## P13 · Decision options panel

- **Stage:** app
- **Depends on:** P12
- **Attach:** 03_UI_SPEC.md (Decision options panel)

~~~prompt
Build the decision options panel per 03_UI_SPEC.md.

- Header "DECISION OPTIONS · model estimates at {t} s" bound to currentFrame.
- Pass table sorted by EV with columns Option, Catch, Exp EPA, INT, Arrival margin ("Ball 1.0 s / Def 1.5 s" plus signed margin), 1st down (✓ + yard line, or "N yd short"). MODEL PICK chip on the top row.
- Rows clickable to select a receiver (syncs with the field).
- Non-pass options: Scramble, Throw away (grounding warning when flagged), Hold (segmented sack-risk bar + text).
- After the QB crosses the LOS, replace the pass table with "Forward pass no longer legal (QB past LOS)".
- Numbers use tabular figures; signed values always show + or −.
~~~

**Done when:**
- Scrubbing updates every number.
- Selecting a row selects the receiver on the field and vice versa.

---

## P14 · Timeline, playback, flags and filters

- **Stage:** app
- **Depends on:** P11
- **Attach:** 04_TIMELINE_FLAGS_SPEC.md

~~~prompt
Build the timeline exactly as specified in 04_TIMELINE_FLAGS_SPEC.md.

- Controls: restart, play/pause, step +0.1 s, speed (0.25×, 0.5×, 1×, 2×), readout "1.8 s · frame 24".
- Scrubber from first to last frame, time relative to the snap, the post-release 0.5 s shaded and labelled "ball in air (tracking ends)".
- Flags as buttons: solid diamonds for tracking, hollow circles for model flags. Tooltips on hover.
- Filter chips: Key (default), All tracking, Pre-snap, Windows ▾ (per receiver), Decision, Protection, Custom ▾. Chips combine. Persist in the URL and localStorage (try/catch).
- Click/tap a flag: pause, seek to its frameId, select the related player.
- Keyboard shortcuts from the spec.
- Clustering of flags within 12 px with a count badge and popover; zoom splits clusters.
- Accessibility requirements from the spec (aria-labels, slider role, 32 px hit areas, focus handling).

Write the Vitest tests listed at the end of the spec.
~~~

**Done when:**
- All timeline tests pass.
- On the demo play, "Key" shows exactly Snap (0.0 s) and Throw (3.2 s); "All tracking" shows nothing extra (this play has only those two events); "Windows" shows model flags for the selected receiver.

---

## P15 · Option-value chart and attention strips

- **Stage:** app
- **Depends on:** P14
- **Attach:** 03_UI_SPEC.md, 04_TIMELINE_FLAGS_SPEC.md (Shared x-axis)

~~~prompt
Add two linked panels under the scrubber, sharing its x-axis exactly:

1. Expected option value over time: one line per receiver plus dashed lines for scramble, throw away and hold. Highlight the selected receiver; others at 40% opacity. Vertical line at the actual throw labelled "Actual throw". Values at the playhead shown as dots.
2. Receiver attention strips (from mockup v1): one row per receiver, colour = A(j) on the attention ramp, with "window" spans outlined where margin ≥ +0.3 s. Collapsible.

Both show visible flags as faint vertical guide lines and seek on click. Legend entries use jersey + last name.
~~~

**Done when:**
- Clicking anywhere on either panel seeks.
- Flags filtered on the timeline show and hide in both panels too.

---

## P16 · Selected receiver panel and hover links

- **Stage:** app
- **Depends on:** P13
- **Attach:** 03_UI_SPEC.md (Selected receiver panel)

~~~prompt
Build the selected receiver panel:

- Attention as "0.6 defender-equivalents (play average 1.4)".
- Lane: "min projected clearance 1.2 yd · 2D proxy", with "batted-ball risk" when flagged.
- Gravity badge when non-null: "Gravity +0.8 · proxy (heuristic, not causal)".
- "Why this window?" sentence from templates. Build at least 6 templates that choose the top two reasons from: margin, attention drawn by another receiver (gravity), lane clearance, first-down reach, coverage type, pressure. Example: "#88 draws two defenders deep; #1 has 0.5 s of room underneath."

Hover sync: hovering a receiver anywhere (field, table, chart, strips) highlights him everywhere.
~~~

**Done when:**
- Every receiver on the demo play produces a sensible sentence at frames 24 and 38.

---

## P17 · Post-play panel

- **Stage:** app
- **Depends on:** P13
- **Attach:** 03_UI_SPEC.md (Post-play panel)

~~~prompt
Build the post-play panel:

- Title "POST-PLAY · play-by-play data".
- "Observed: {QB} → {target} #{jersey} · {result}" plus yards. Handle: complete, incomplete, interception, sack, scramble, no named target ("Incomplete, no intended receiver listed").
- Expected decision gap: chosen option EV, model pick EV, gap, labelled "expected" and "illustrative" while the badge says so.
- Footer sentence: "Alternative outcome unknown. This shows what the model would have chosen, not a predicted result."
- The panel shows its content from the first frame (it's play metadata), but the field's actual-target path still waits for the throw frame unless "Show actual" is on.
~~~

**Done when:**
- All five result types render correctly on real plays (find one of each in index.json).

---

## P18 · Protection view

- **Stage:** app
- **Depends on:** P12, P14
- **Attach:** 03_UI_SPEC.md (Protection view)

~~~prompt
Build the protection overlay opened from the Hold row or a "Protection" button.

- Draw blocker → first-blocked rusher links from the PFF pairing, with block type on hover (show the full name from 01_DATA_SPEC.md, e.g. "PT · Post block").
- Mark rushers who were no blocker's first assignment with a ring and the label "no first assignment".
- Colour each rusher's path from the snap to the current frame by STRAIN.
- List PFF credit as data facts (hurry, hit, sack, beaten by defender, allowed) separately from model flags (block_beaten, pressure_arrives).
- Turn on the Protection flag group automatically while the overlay is open.
~~~

**Done when:**
- On the demo play: #92 and #56 each show two blockers, #98 and #32 show "no first assignment", Collins (#71) shows "beaten by defender".

---

## P19 · Aggregate validation tab

- **Stage:** app
- **Depends on:** P10, P11
- **Attach:** 03_UI_SPEC.md (Aggregate validation tab)

~~~prompt
Build the Aggregate validation tab with four charts from the aggregate JSON files:

1. QB decision gap dot plot with 90% CI (QBs with at least 50 targeted throws), filters for coverage and time-to-throw bucket. Clicking a QB lists his plays with the largest gaps, each linking to the replay.
2. Calibration reliability curve with the diagonal, bin counts, and Brier score before/after, on held-out weeks 7–8.
3. Attention sanity: Man vs Zone max-weight distributions and the block agreement rate.
4. Cold zones: per coverage, a field heatmap of mean attention near the LOS with the best-option and actual-target release positions overlaid.

Each chart gets a one-line caption with sample size. Use the same colour tokens as the play view.
~~~

**Done when:**
- All four charts render from real aggregate files.
- Clicking through from a QB's worst play opens the replay at its release frame.

---

## P20 · Demo play check and play picker

- **Stage:** app
- **Depends on:** P13–P19
- **Attach:** 07_DEMO_PLAYS.md

~~~prompt
Using the model outputs, check each demo story in 07_DEMO_PLAYS.md:

- Main demo (2021090900/1687): does the model rank another receiver above #88 at release? Report the top 3 with EV and margin.
- Good decision (2021090900/3406): is the QB's choice the model's best option, or within 0.05 EPA?
- Sack (2021091202/210): do unblocked_rusher and pressure_arrives fire, and does scramble or throw away beat every pass before the sack?

If a story doesn't hold, search for a replacement play that does (same criteria, clean traditional dropback, no penalty), prefer DAL @ TB week 1 so the audience knows the teams, and update 07_DEMO_PLAYS.md with the facts.

Then build the play picker: searchable dropdown over index.json (team, QB, week, result), demo plays starred at the top, and a "random play" button.
~~~

**Done when:**
- Each demo story is confirmed or replaced, with the evidence printed.
- The picker opens any play in under 1 s.

---

## P21 · Accessibility and performance pass

- **Stage:** quality
- **Depends on:** P20
- **Attach:** 03_UI_SPEC.md, 04_TIMELINE_FLAGS_SPEC.md

~~~prompt
Do an accessibility and performance pass:

- Contrast: check every text and mark colour against its background in both themes (WCAG AA for text, 3:1 for marks). Fix failures in the tokens, not per component.
- Keyboard: every control reachable; visible focus; shortcuts don't fire while typing in the picker.
- Screen reader: field has a text summary that updates on seek ("Frame 24, 1.8 s after snap. Model pick #1 Wilson, margin +0.5 s").
- Colour independence: margins, flags and paths are distinguishable in greyscale.
- Performance: profile playback on the demo play; keep frame time under 16 ms. Memoise per-frame derived data; draw the heat canvas only when the frame or layer changes.

Report what you changed.
~~~

**Done when:**
- No AA failures remain.
- Playback holds 60 fps on a mid-range laptop.

---

## P22 · Pitch mode

- **Stage:** demo
- **Depends on:** P20
- **Attach:** 07_DEMO_PLAYS.md, 00_PROJECT_BRIEF.md

~~~prompt
Add a "Pitch mode" toggle that walks through the three demo plays as a guided sequence:

1. For each play, a list of stops (deep links with frame, filters and selected player) and a one-sentence caption per stop.
2. Arrow keys move between stops; the replay animates from the previous stop to the next.
3. Large type for captions, everything else unchanged.

Write the captions from the confirmed facts in 07_DEMO_PLAYS.md only. Keep each caption under 20 words and in plain language.
~~~

**Done when:**
- The full pitch runs in under 4 minutes with arrow keys only.
