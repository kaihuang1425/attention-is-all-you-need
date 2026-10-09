# Model spec

All maths runs on normalised coordinates (offense attacks +x). Frame step Δt = 0.1 s. Every parameter below is a starting value, kept in one config file (`pipeline/config.yaml`) so it can be tuned without code changes.

## 1. Who counts

- **Offensive candidates for attention:** every offensive player except the QB (`pff_role != "Pass"`). Route runners and blockers both receive attention, so the same matrix covers coverage and protection.
- **Pass targets:** players with `pff_role == "Pass Route"`. Running backs who stay in to block are not targets on that play.
- **Defenders:** all 11. Coverage players and rushers are both rows of the matrix.

## 2. Soft attention

For defender d and offensive player j at frame f:

```
dist(d,j)  = distance between d and j
θ(d,j)     = angle between d's orientation vector (sin o, cos o) and the vector d→j
score(d,j) = -dist(d,j) / σ  +  k · cos θ(d,j)
a(d→j)     = softmax_j( score(d,j) / T )          # each defender's row sums to 1
A(j)       = Σ_d a(d→j)                           # "defender-equivalents" on player j
```

Starting values: σ = 4 yd, k = 1.0, T = 1.0.

Notes:
- Add an **"unattached" column** with a fixed score (e.g. −3) so a deep safety in zone, far from everyone, does not get forced onto a receiver. Its weight shows how much attention is spent on space rather than players. Don't draw it as an edge.
- `o` is body orientation (sensor in the shoulder pads), not eye direction. Describe it as body orientation in the UI.
- Smooth `o` over 3 frames before use; it is noisy.

### Validation of attention (must pass before building the UI on it)

1. **Man vs zone:** for `pff_passCoverageType == "Man"`, the mean of each coverage defender's maximum row weight at the throw should clearly exceed the same statistic for Zone plays. Report both distributions.
2. **Blocks:** for each blocker with a `pff_nflIdBlockedPlayer`, the rusher's highest-attention offensive player in the first 1.0 s after the snap should be that blocker (or a teammate double-teaming) in most cases. Report the agreement rate.
3. **Sanity on the demo play:** see `07_DEMO_PLAYS.md`.

Tune σ, k and T against checks 1 and 2, not against outcomes.

## 3. Arrival margin (the "too far is risky" model)

Distance alone is not the risk. The risk is how long the ball is in the air, because that is how long defenders have to close. For receiver j at frame f, with QB position q:

```
v_ball      = 24 yd/s (median release speed measured in this data; see 01_DATA_SPEC)
t_release   = 0.2 s (time to get the throw off)

# Iterate to find the catch point (2–3 fixed-point iterations are enough):
p0          = receiver position + receiver velocity * 0.8 s   (initial guess)
t_ball      = t_release + |p - q| / v_ball
p           = receiver position + receiver velocity * t_ball  (constant-velocity projection)

# Defender arrival at p:
t_def(d)    = τ_react + |p - pos_d| / v_max(d),  but never less than a straight-line time
              using current velocity component toward p
τ_react     = 0.5 s
v_max(d)    = max(observed max speed of d this play, 7.0 yd/s)

margin(j)   = min_d t_def(d) - t_ball
pCatch(j)   = sigmoid(margin(j) / τ),  τ = 0.25 s     # then calibrate (section 7)
pInt(j)     = c_int * (1 - pCatch(j)) * closeness(nearest defender at p),  c_int = 0.08
```

Option: extend the projection with acceleration and current direction of travel, capped at the sideline and end line.

**Per-receiver flight time** is `t_ball(j)`. It drives the projected-catch circles on the field and the "1.3 s flight" labels. Never use a fixed projection offset.

## 4. Value of a completion

Version 1 (fast, no external data):

```
gain(j)      = catch-point x' - los'   (+ expected YAC: 2.0 yd short, 3.5 yd deep; tune)
firstDown(j) = catch-point x' + YAC >= firstDownX'
value(j)     = EP(down', distance', yardline') - EP(down, distance, yardline)
```

Version 2 (better): fit an EP lookup from nflverse 2021 play-by-play (`ep` against `down`, `ydstogo`, `yardline_100`, smoothed with a GAM or binned means). Use it for both completions and non-pass options so all values share one scale.

```
EV_pass(j) = pCatch(j) * value_complete(j)
           + (1 - pCatch(j) - pInt(j)) * value_incomplete
           + pInt(j) * value_interception
```

`value_incomplete` = EP of next down, same spot, minus current EP. `value_interception` = −(EP for the opponent at the catch point) − current EP.

## 5. Non-pass options

| Option | Available when | Value |
|---|---|---|
| **Scramble** | always while the QB has the ball | Expected yards = distance the QB can run along his best lane before the first defender can reach that lane (same arrival logic, QB speed 6.5 yd/s), then EP of the result. |
| **Throw away** | QB outside the tackle box, or a receiver/sideline is reachable without grounding | EP of next down, same spot. If the QB is inside the tackle box and no eligible receiver is near the landing point, flag grounding risk instead. |
| **Hold** | always | Value of waiting 0.5 s = (1 − pSack(0.5 s)) × best option value next frame + pSack × EP after a typical sack (−7 yd). |

**Sack hazard:** fit a logistic model on frames from all plays with features: minimum rusher distance to QB, STRAIN of the closest rusher (`-d'(t)/d(t)`), number of unblocked rushers (rushers whose top attention target is not an offensive lineman), time since snap. Target: a sack or QB-hit within the next 0.5 s (use `pff_sack`, `pff_hit` plus the `qb_sack` frame). Show it as "Sack risk 18% in next 0.5 s".

**Rules applied to options:**
- Forward-pass options exist only while the QB's x' ≤ los' (QB behind the LOS). After he crosses, only scramble remains.
- Receivers behind the LOS are valid targets (screens, check-downs).
- Backward passes are legal at any time but are not modelled (they are almost absent: 1 `lateral` event in the data).

## 6. Lane clearance and gravity

**Lane clearance (2D proxy):** sample the straight path from q to the catch point p at 10 points. For each defender, project his position forward to the time the ball passes each sample point. Clearance = minimum distance. Flag "tight lane" under 1.5 yd. Linemen within 2 yd of the QB at release with a hand-up opportunity count as batted-ball risk. Always label it "2D proxy; ball height unavailable".

**Gravity (proxy):** for receiver j, gravity = A(j) at release − expected A for his alignment (`pff_positionLinedUp`), route depth bucket (x' − los' at release: <5, 5–15, >15 yd) and coverage type. The expected value is the mean over all plays in the same bucket. Label it "heuristic, not causal".

## 7. Calibration

- Over all targeted throws (C, I, IN with a matched target), compare `pCatch(target)` at the release frame with the actual completion. Fit isotonic or Platt calibration on weeks 1–6 and report on weeks 7–8.
- Plot a reliability curve (10 bins) and report the Brier score before and after.
- Never use the calibration result to claim what *would* have happened on a non-targeted receiver. It only shows the model is not miscalibrated on the throws we can see.

## 8. Decision gap

At the release frame:

```
best      = argmax over options of EV
chosen    = EV of the actual target (or scramble/sack if passResult is R/S)
gap       = EV(best) - EV(chosen)          # >= 0
```

Aggregate by QB, team, coverage and time-to-throw bucket. Exclude plays with no matched target, spikes, and plays with penalties that nullify the play (`foulName1` present and `playResult` inconsistent with the description).

## 9. Model-derived flags

Computed per frame, written to the per-play JSON (see `04_TIMELINE_FLAGS_SPEC.md`):

| Flag | Rule |
|---|---|
| `window_open` (per receiver) | margin crosses from < +0.3 s to ≥ +0.3 s |
| `window_close` (per receiver) | margin crosses back below +0.3 s |
| `best_option_change` | argmax of EV changes (ignore changes that revert within 2 frames) |
| `pressure_arrives` | any rusher within 2.0 yd of the QB for the first time |
| `block_beaten` (per blocker) | the rusher he first blocked gets closer to the QB than the blocker (projected onto the blocker→QB line) for 2+ consecutive frames |
| `unblocked_rusher` | a rusher with no `pff_nflIdBlockedPlayer` pointing at him crosses los' |
| `peak_decision_gap` | frame before release where EV(best option) − EV(the receiver the QB eventually targeted) is largest |

Hysteresis: require the new state to hold for 2 frames before emitting a flag.
