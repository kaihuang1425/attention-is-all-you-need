#!/usr/bin/env bash
# Optional supplemental data: nflverse 2021 play-by-play (about 20 MB), allowed by the data README.
# Used to resolve unmatched targets (P03) and to fit the expected-points table (P06).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/data/external/pbp_2021.parquet"
URL="https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_2021.parquet"

if [ -s "$DEST" ]; then
  echo "data/external/pbp_2021.parquet already present; nothing to do."
  exit 0
fi
mkdir -p "$(dirname "$DEST")"
echo "Downloading nflverse play-by-play 2021..."
curl -fSL -o "$DEST.part" "$URL"
mv "$DEST.part" "$DEST"
echo "Saved data/external/pbp_2021.parquet"
