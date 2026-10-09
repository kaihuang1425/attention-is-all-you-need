# Demo plays

Three plays, one per story. The labels "good decision" and "missed open receiver" are hypotheses until the model runs. Prompt P20 checks them and swaps a play if the model disagrees.

## 1. Main demo: DAL @ TB, week 1 (gameId 2021090900, playId 1687)

This is the play in `mockups/mockup_v2_dal_tb_1687.png`. All facts below are from the data.

- **Situation:** Q2 05:43, 2nd & 8, ball on the TB 25, TB leads 14–7 (TB home). DAL moving right in raw coordinates. LOS raw x = 85.0, first-down line raw x = 93.0 (TB 17).
- **Description:** "(5:43) (Shotgun) D.Prescott pass incomplete deep left to C.Lamb."
- **Formation:** SHOTGUN, personnel 1 RB, 1 TE, 3 WR. 2×2 (LWR #88 and TE-L #89 on the left; RWR #13 and SRWR #1 on the right). RB #21 aligned HB-R.
- **Defense:** Cover-3 (Zone), 7 in the box, personnel 2 DL, 4 LB, 5 DB.
- **Timing:** 43 frames. `ball_snap` at frame 6, `pass_forward` at frame 38: **3.2 s from snap to throw**. Tracking ends at frame 43.

| Team | # | Player | Pos | PFF role | Aligned | First blocked / notes |
|---|---|---|---|---|---|---|
| DAL | 4 | Dak Prescott | QB | Pass | QB | |
| DAL | 77 | Tyron Smith | T | Pass Block | LT | #92 Gholston (PT) |
| DAL | 52 | Connor Williams | G | Pass Block | LG | #92 Gholston (PP) |
| DAL | 63 | Tyler Biadasz | C | Pass Block | C | #56 Nunez-Roches (PT) |
| DAL | 66 | Connor McGovern | G | Pass Block | RG | #56 Nunez-Roches (PP) |
| DAL | 71 | La'el Collins | T | Pass Block | RT | #58 Barrett (PP), **beaten by defender** |
| DAL | 21 | Ezekiel Elliott | RB | Pass Route | HB-R | |
| DAL | 89 | Blake Jarwin | TE | Pass Route | TE-L | |
| DAL | 88 | CeeDee Lamb | WR | Pass Route | LWR | **Actual target**, incomplete |
| DAL | 13 | Michael Gallup | WR | Pass Route | RWR | |
| DAL | 1 | Cedrick Wilson | WR | Pass Route | SRWR | Model pick in the mockup (illustrative) |
| TB | 92 | William Gholston | DE | Pass Rush | DRT | |
| TB | 58 | Shaquil Barrett | OLB | Pass Rush | LOLB | Beat RT Collins |
| TB | 56 | Rakeem Nunez-Roches | DT | Pass Rush | NLT | |
| TB | 98 | Anthony Nelson | OLB | Pass Rush | REO | No blocker's first assignment |
| TB | 32 | Mike Edwards | FS | Pass Rush | RLB | No blocker's first assignment |
| TB | 54 | Lavonte David | ILB | Coverage | RILB | |
| TB | 45 | Devin White | ILB | Coverage | LLB | |
| TB | 43 | Ross Cockrell | CB | Coverage | SCBL | |
| TB | 24 | Carlton Davis | CB | Coverage | LCB | |
| TB | 35 | Jamel Dean | CB | Coverage | RCB | |
| TB | 31 | Antoine Winfield | FS | Coverage | FS | |

**Talking points supported by the data:**

- Five rushers against five linemen, but the linemen doubled #92 and #56. That left #98 and #32 with no first assignment, and RT Collins lost to Barrett on the right edge. The mockup's "Right edge closing" matches PFF's `pff_beatenByDefender` for Collins.
- 3.2 s to throw is above the dataset median (2.7 s). It's a long hold against a five-man rush.
- Cover-3 with a deep left target: check whether the deep third defender (#35 Dean, aligned RCB on the offense's left) was attending to Lamb, and whether that left the underneath window to the right open.

**Model sanity checks on this play (run after P04–P07):**

- Defenders #35 and #31 should put meaningful attention on #88 late in the play.
- Rushers #92 and #56 should show their top attention on two linemen each early on.
- The Hold row's sack risk should rise in the last second before the throw.
- If the model does **not** rank another receiver above #88 at release, the "missed open receiver" story is wrong for this play. Say so and pick another play.

## 2. Good decision: DAL @ TB, week 1 (gameId 2021090900, playId 3406)

- "(:39) (Shotgun) D.Prescott pass deep right to A.Cooper for 21 yards, TOUCHDOWN."
- Q3 0:39, TB leads 28–19, 3rd & 4, Cover-1 (man), traditional dropback, no penalty. Same game as the main demo, so the audience already knows the teams.
- Timing: 177 frames. Long pre-snap phase with `line_set` at frames 38 and 58, `ball_snap` at frame 146, `pass_forward` at frame 173: **2.7 s to throw**. There is a bogus `autoevent_ballsnap` at frame 6; this play is the test case for the manual-first snap rule.
- Protection: six rushers (Suh, Pierre-Paul, Vea, Barrett, Lavonte David, Devin White), all six picked up as some blocker's first assignment.
- Expected story: man coverage, clean pocket, Cooper wins, the model's best option matches the QB's choice (gap near 0). Its long pre-snap phase also shows off the Pre-snap flag filter.

## 3. Sack with an unassigned rusher: NYJ @ CAR, week 1 (gameId 2021091202, playId 210)

- "(12:20) (Shotgun) Z.Wilson sacked at NYJ 22 for -9 yards (B.Burns)."
- Q1 12:20, 2nd & 14, Cover-3, traditional dropback, no penalty.
- Timing: 39 frames, `ball_snap` at frame 6, `qb_sack` at frame 34 (2.8 s after the snap).
- Four rushers (DaQuan Jones, Shaq Thompson, Brian Burns, Derrick Brown). Burns is credited with the sack and was the only one who was no blocker's first assignment.
- Expected story: Hold value collapses, `unblocked_rusher` and `pressure_arrives` flags fire before any window opens, scramble or throw-away was the best option.

## Backups

- 76 sacks in clean traditional dropbacks were made by a rusher no blocker engaged first (e.g. 2021091202/3420 Z.Wilson sacked by S.Thompson, Cover-1).
- 169 clean man-coverage completions of 15–30 yd on 2nd/3rd down (e.g. 2021091200/605 J.Hurts to D.Smith TD, Cover-1).
