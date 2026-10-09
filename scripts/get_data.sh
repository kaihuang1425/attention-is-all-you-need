#!/usr/bin/env bash
# Clone the Big Data Bowl regional event data (about 1 GB) into data/raw.
# Safe to re-run: skips when data/raw already holds a clone of the same repo.
set -euo pipefail

REPO_URL="https://github.com/ThompsonJamesBliss/nfl-big-data-bowl-regional-event-data"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/data/raw"

normalise_url() {
  # Compare origins without caring about a trailing ".git" or "/".
  local u="${1%/}"
  echo "${u%.git}"
}

if [ -d "$DEST" ]; then
  if [ -d "$DEST/.git" ]; then
    origin="$(git -C "$DEST" remote get-url origin 2>/dev/null || true)"
    if [ "$(normalise_url "$origin")" = "$(normalise_url "$REPO_URL")" ]; then
      echo "data/raw already holds $REPO_URL; nothing to do."
      exit 0
    fi
    echo "error: data/raw is a clone of '$origin', expected $REPO_URL" >&2
    exit 1
  fi
  if [ -n "$(ls -A "$DEST" 2>/dev/null)" ]; then
    echo "error: data/raw exists, is not empty and is not a git clone; move it aside first" >&2
    exit 1
  fi
  rmdir "$DEST"
fi

mkdir -p "$ROOT/data"
echo "Cloning $REPO_URL into data/raw (about 1 GB)..."
GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 "$REPO_URL" "$DEST"
echo "Done. CSVs are in data/raw/data/."
