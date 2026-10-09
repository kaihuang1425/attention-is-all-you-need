# Safety Pull

Safety Pull measures how much of the deep safeties' movement between the snap and the throw each route runner draws toward himself. This is the decoy work that never appears in a box score. Across 7,541 throws and 34,845 routes from Weeks 1–8 of the 2021 season, outside receivers 8–18 yards downfield drag the safeties up to twice their fair share. Against two-high shells (Cover-2, 2-Man, Quarters, Cover-6), routes between the hashes draw almost none. That shows how outside threats widen the safeties and open the middle of the field. Scouts can use it to value receivers who create space without being targeted, coaches to pick which route stretches a two-high shell, and broadcasters to show viewers who opened the play.

![Safety Pull heatmap](output/safety_pull_heatmap.png)

## How it works
- **Deep safeties:** players in a safety alignment (PFF `FS`/`SS` variants) who line up at least 7 yards deep at the snap.
- **Pull:** on every frame from the snap to the throw, the safety's own movement toward each route runner is measured. The route runner he moves toward most gets the credit, so receiver movement doesn't count.
- **Safety Pull index:** a route runner's share of that movement multiplied by the number of route runners on the play. 1.0 is an even split.
- **Intended receiver:** parsed from the play description, because tracking ends 0.5 s after the throw.

## Run
```
python safety_pull.py --data <folder with games.csv, plays.csv, tracking/...> --out out
```
Requires `pandas`, `numpy` and `matplotlib`. Add `--weeks 1` for a quick test.

## Limitation
In zone coverage, safeties widen to their deep areas regardless of the receiver, so part of the pull is coverage geometry. The heatmap serves as the expected pull for each spot on the field. A receiver's pull over that expectation is his own contribution.
