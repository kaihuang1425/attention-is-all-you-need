# Safety Pull

Safety Pull measures how much of the deep safeties' movement between the snap and the throw each route runner draws toward himself, the decoy work that never appears in a box score. Across 7,541 throws from Weeks 1–8 of the 2021 season, outside receivers 8–18 yards downfield drag the safeties up to twice their fair share. Against a single-high shell, a teammate who pulls a safety 2+ yards gives the targeted receiver +0.25 yards of separation and about +4 points of completion rate, while against two-high shells the effect is zero because the second safety is still there. Scouts can use Pull Over Expected to value receivers who create space without being targeted, coaches can use it to pick decoy routes against single-high looks, and broadcasters can use it to show who really opened the play.

![Safety Pull heatmap](output/safety_pull_heatmap.png)
![Decoy effect](output/decoy_effect.png)
![Pull Over Expected leaderboard](output/pull_over_expected.png)

## How it works
- **Deep safeties:** players in a safety alignment (PFF `FS`/`SS` variants) who line up at least 7 yards deep at the snap.
- **Pull:** on every frame from the snap to the throw, the safety's own movement toward each route runner is measured. The route runner he moves toward most gets the credit, so receiver movement doesn't count.
- **Safety Pull index:** a route runner's share of that movement multiplied by the number of route runners on the play. 1.0 is an even split.
- **Pull Over Expected:** the heatmap is the expected-pull model. A receiver's index minus the average index for routes ending in the same 3×3-yard cell against the same shell gives his own contribution. This follows the same logic as the NBA's Gravity stat.
- **Decoy effect:** OLS regression, separately for each shell. The targeted receiver's separation at the throw (distance to the nearest defender) is regressed on whether a teammate pulled a safety 2+ yards, controlling for time to throw, target depth and the target's own pull.
- **Intended receiver:** parsed from the play description, because tracking ends 0.5 s after the throw. This matches 93% of plays.

## Run
```
python safety_pull.py --data <folder with games.csv, plays.csv, tracking/...> --out output
```
Requires `pandas`, `numpy` and `matplotlib`. The full run takes about 2 minutes. `--weeks 1` gives a quick test, and `--plot-only` redraws from saved results.

## Limitations
- In zone coverage, safeties widen to their deep areas regardless of the receiver. Pull Over Expected controls for this by spot and shell, but not by play call.
- A safety may react to the QB's eyes rather than the receiver.
- The decoy effect is an association with controls, not a causal estimate.
