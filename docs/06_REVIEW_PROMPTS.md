# Review and stress-test prompts

Use these between build stages, or whenever something looks off. They follow the workshop's seven-step loop (`reference/slide_side_quest_tips.jpg`): explore, brainstorm, validate, stress-test, scope, plan/build, stress-test again. Give the agent `00_PROJECT_BRIEF.md` plus the files named in each prompt.

---

## R01 · Explore: summarise the data

~~~prompt
Using pipeline/load.py, summarise the dataset for someone who has never seen it: what one row means in each file, how the files join, what time window the tracking covers, and the five facts most likely to trip up a newcomer. Check every number against 01_DATA_SPEC.md and list any disagreement.
~~~

## R02 · Validate: does this exist already?

~~~prompt
Search for prior public work on (a) defensive attention or "gravity" on receivers from tracking data, (b) hypothetical completion probability for every receiver at the throw, (c) field control / pitch control in American football, and (d) Big Data Bowl 2023 pass-rush entries. For each, give one line on what they did and one line on what our project does differently. Cite sources with links. Be honest if our idea overlaps heavily with something.
~~~

## R03 · Stress-test: can we compute this with what we have?

~~~prompt
Read 01_DATA_SPEC.md and 02_MODEL_SPEC.md. For each model output (attention, arrival margin, pCatch, EV, sack hazard, lane clearance, gravity, each flag), list:
- the exact columns it needs,
- whether those columns exist for every play,
- the main assumption it makes that the data cannot check,
- how we would notice if that assumption is badly wrong.
Flag anything that depends on data we don't have (ball height, eye direction, play calls, post-catch tracking).
~~~

## R04 · Scope: enough data, or go broader?

~~~prompt
Using the play index, report how many plays are left after each filter we apply (has snap, traditional dropback, no penalty, named target matched, at least 1.5 s to throw). Then for the aggregate claims (QB decision gap, calibration, man vs zone attention), estimate whether the sample is big enough: per-QB counts, per-coverage counts, bootstrap interval widths. Recommend minimum sample sizes and which QBs or coverages to drop from the charts.
~~~

## R05 · Football sanity audit (run on every new screenshot)

~~~prompt
You are an NFL team analytics staffer judging this hackathon. Look at the attached screenshot of the app and check:
1. Exactly 11 players per side; jersey numbers and names match the play file.
2. Formation label matches the alignment on screen (count receivers each side of the ball).
3. LOS and first-down line positions match down and distance and the yard line in the play bar.
4. Direction of attack and left/right labels are consistent.
5. Nothing on screen claims to show what happened after the throw except the post-play panel.
6. Every model number is labelled as an estimate.
List every problem with the exact location on screen. Don't comment on style.
~~~

## R06 · Honesty audit of copy and labels

~~~prompt
Go through every user-visible string in /app/src (grep for JSX text and template strings). For each string that states a number or a claim, mark it as DATA (from tracking, PFF or play-by-play), MODEL (estimate) or MIXED. Flag any MODEL or MIXED string that reads like a fact, any counterfactual stated as an outcome, and any use of "would have" without "expected". Propose replacement wording.
~~~

## R07 · Visual QA against the mockups

~~~prompt
Compare the attached screenshot of the current build with mockups/mockup_v2_dal_tb_1687.png (content reference) and mockups/mockup_v1_play042.png (readability reference), using 03_UI_SPEC.md as the source of truth when they disagree. List:
- spec items missing or different,
- places where text density is higher than v1,
- colour uses that break the one-meaning-per-hue table,
- labels under 12 px or contrast that looks weak.
Order by how visible each issue would be from the back of a room.
~~~

## R08 · Model stress test (step 7: does this make sense?)

~~~prompt
Act as a sceptical reviewer of the model. Using the exported data:
1. Find the 10 plays with the largest decision gaps. For each, look at the replay frames around release and say whether the model's pick is plausible or an artefact (receiver out of bounds, projection through a defender, wrong target match, broken orientation).
2. Check pCatch calibration by coverage type and by depth bucket. Report where it is worst.
3. Check whether gap correlates with time to throw, pressure, or coverage in ways that suggest a bias rather than QB skill.
4. Rank the top 5 fixes by how much they would change the headline numbers.
Do not change code in this step; report only.
~~~

## R09 · Code review

~~~prompt
Review the diff since the last tag for correctness and clarity. Focus on: coordinate normalisation (every place that reads x, y, o, dir), frame/time conversions, off-by-one errors around snapFrame and endFrame, NaN handling for "None" events and NA nflIds, and any place a model value could leak into the post-play panel or vice versa. Give file and line for each finding.
~~~

## R10 · Judge Q&A rehearsal

~~~prompt
The judges are NFL team analytics staffers (see reference/slide_bdb_timeline.jpg). Write the 12 hardest questions they are likely to ask about this project, covering data limits, model assumptions, validation, and usefulness to a coaching staff. For each, draft a two-sentence answer using only facts from 01_DATA_SPEC.md, 02_MODEL_SPEC.md, 07_DEMO_PLAYS.md and the validation outputs. Mark any question we can't answer well yet.
~~~

## R11 · Rules check

~~~prompt
Check the app and model against these rules and report any violation:
- One forward pass per down, only from behind (or within) the neutral zone. Forward-pass options disappear once the QB crosses the LOS.
- Backward passes are legal anywhere, any number, and a backward pass that hits the ground is a live ball. We don't model them, but nothing in the UI should say they are illegal.
- Intentional grounding applies inside the tackle box when no eligible receiver is in the area. The Throw away option must show the grounding warning in that case.
~~~
