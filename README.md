# Defensive Attention

A play replay tool for the Big Data Bowl regional event data (2021 season, weeks 1–8). It shows where the defense spends its attention, which receiver that leaves open, and how the quarterback's choice compares with the best option available before the throw.

The specs and build prompts are in [`docs/`](docs/README.md). Start with `docs/00_PROJECT_BRIEF.md`.

## Quick start

Three commands, run from the repo root.

```bash
# 1. Get the data (about 1 GB, cloned into data/raw; re-running is a no-op)
bash scripts/get_data.sh

# 2. Run the pipeline (writes JSON to app/public/data)
python -m pipeline.export

# 3. Run the app
cd app && npm install && npm run dev
```

`pipeline.export` arrives with prompt P10. The stages built so far run on their own:

```bash
bash scripts/get_nflverse.sh      # optional: nflverse 2021 play-by-play (20 MB) into data/external
python -m pipeline.normalise      # data/derived/play_index.parquet (key frames, labels, formation)
python -m pipeline.targets        # data/derived/targets.parquet (actual target per play)
```

## Setup

Python 3.10+ (3.11+ recommended):

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate    Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

Node 20+ for the app (`npm test`, `npm run lint`, `npm run build`).

On Windows, run `scripts/get_data.sh` from Git Bash. Tests that need the data are marked `data` and skip when `data/raw` is missing. Set `NFL_DATA_DIR` to point at a copy of the CSVs stored elsewhere.

## Layout

```
pipeline/   Python package: load, normalise, targets, attention, arrival, values, lanes, flags, export
  config.yaml   every model parameter with its starting value
  tests/
app/        React 18 + Vite + TypeScript
  src/{data,field,panels,timeline,validation}
  public/data/  pipeline output
scripts/    get_data.sh, get_nflverse.sh
docs/       project brief, specs, build and review prompts, mockups
data/       raw/ (cloned), derived/ (pipeline intermediates), external/ (optional nflverse files); not committed
```

## Safety Pull analysis

The existing `safety_pull.py` analysis measures how much of the deep safeties' movement between the snap and the throw each route runner draws toward himself—the decoy work that never appears in a box score. Across 7,541 throws from Weeks 1–8 of the 2021 season, outside receivers 8–18 yards downfield drag the safeties up to twice their fair share. Against a single-high shell, a teammate who pulls a safety 2+ yards gives the targeted receiver +0.25 yards of separation and about +4 points of completion rate, while against two-high shells the effect is zero because the second safety is still there.

![Safety Pull heatmap](output/safety_pull_heatmap.png)
![Decoy effect](output/decoy_effect.png)
![Pull Over Expected leaderboard](output/pull_over_expected.png)

### How it works

- **Deep safeties:** players in a safety alignment (PFF `FS`/`SS` variants) who line up at least 7 yards deep at the snap.
- **Pull:** on every frame from the snap to the throw, the safety's own movement toward each route runner is measured. The route runner he moves toward most gets the credit, so receiver movement doesn't count.
- **Safety Pull index:** a route runner's share of that movement multiplied by the number of route runners on the play. 1.0 is an even split.
- **Pull Over Expected:** the heatmap is the expected-pull model. A receiver's index minus the average index for routes ending in the same 3×3-yard cell against the same shell gives his own contribution. This follows the same logic as the NBA's Gravity stat.
- **Decoy effect:** OLS regression, separately for each shell. The targeted receiver's separation at the throw is regressed on whether a teammate pulled a safety 2+ yards, controlling for time to throw, target depth, and the target's own pull.
- **Intended receiver:** parsed from the play description because tracking ends 0.5 seconds after the throw. This matches 93% of plays.

### Run Safety Pull

```bash
python safety_pull.py --data <folder with games.csv, plays.csv, tracking/...> --out output
```

Requires `pandas`, `numpy`, and `matplotlib`. The full run takes about 2 minutes. `--weeks 1` gives a quick test, and `--plot-only` redraws from saved results.

### Limitations

- In zone coverage, safeties widen to their deep areas regardless of the receiver. Pull Over Expected controls for this by spot and shell, but not by play call.
- A safety may react to the QB's eyes rather than the receiver.
- The decoy effect is an association with controls, not a causal estimate.
