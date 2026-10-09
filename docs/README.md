# Defensive Attention: prompt pack

Everything a coding agent needs to build the Defensive Attention hackathon project: the brief, verified data facts, model maths, UI and timeline specs, 23 ordered build prompts, 11 review prompts, demo plays, and the two UI mockups.

## Files

| File | What it is | Use it |
|---|---|---|
| `00_PROJECT_BRIEF.md` | Goal, rules, glossary, stack, repo layout | Standing context in every session (save as `CLAUDE.md`) |
| `01_DATA_SPEC.md` | Measured facts about the dataset, gotchas, coordinates, events, target parsing | Attach to pipeline prompts |
| `02_MODEL_SPEC.md` | Attention, arrival margin, EV, non-pass options, lanes, gravity, calibration, model flags | Attach to model prompts |
| `03_UI_SPEC.md` | Merged UI from both mockups with the review fixes, colour system | Attach to app prompts |
| `04_TIMELINE_FLAGS_SPEC.md` | Timeline, event flags, filter chips, seek interactions, data contract | Attach to P09 and P14 |
| `05_BUILD_PROMPTS.md` | P00–P22, in order, each with "Done when" checks | Paste one at a time |
| `06_REVIEW_PROMPTS.md` | R01–R11 stress tests, audits, Q&A rehearsal | Run between stages |
| `07_DEMO_PLAYS.md` | Three demo plays with verified facts and talking points | Attach to P20, P22, R10 |
| `prompts.jsonl` | All P and R prompts as JSON lines (id, stage, title, depends_on, attach, prompt, done_when) | For scripting or batch runs |
| `mockups/` | `mockup_v1_play042.png`, `mockup_v2_dal_tb_1687.png` | Attach to P11, P12, R07 |
| `reference/` | Workshop slides (tips, BDB history, timeline) | Background |

## How to run it

1. Start a session with `00_PROJECT_BRIEF.md` as context.
2. Run P00, then P01. Don't continue until P01's fact tests pass: everything later depends on those numbers.
3. Run P02 to P10 (pipeline). After P04 and P06, run R08 on whatever exists so far.
4. Run P11 to P19 (app). After each visible change, take a screenshot and run R05 and R07.
5. Run P20 to confirm the demo stories, then P21, then P22.
6. Before presenting, run R06 (honesty), R11 (rules) and R10 (judge Q&A).

Parallel work for a team of three:
- Person A: pipeline P01–P10.
- Person B: app P11, P12, P14 against a hand-written fixture JSON that matches `04_TIMELINE_FLAGS_SPEC.md`, swapping in real exports when P10 lands.
- Person C: R02–R04, then P19 and the pitch.

## What was verified and what wasn't

Verified on the cloned data (2026-10-09): file sizes and row counts, result and coverage counts, `pff_role` spelling, the `"None"` event string, duplicate auto events, 24 plays without a snap, the event vocabulary, 0.5 s pre-snap and post-end windows, time-to-throw distribution, ball release speed, coordinate frame of `absoluteYardlineNumber`, angle convention, target-name match rates, and every fact about the three demo plays.

Not verified: any model output. All model numbers in the mockups (74% catch, +0.50 EPA, gravity +0.8, sack risk 18%) are illustrative placeholders, and the "missed open receiver" story for the main demo play is a hypothesis that P20 tests.
