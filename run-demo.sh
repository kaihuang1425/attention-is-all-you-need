#!/usr/bin/env bash
# Start the Defensive Attention demo: installs the app's packages on first run, then opens the browser.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/app"
if ! command -v node >/dev/null 2>&1; then
  echo "Node.js 20 or newer is required. Install it from https://nodejs.org and run this again." >&2
  exit 1
fi
if [ ! -d node_modules/vite ]; then
  echo "Installing app packages, this takes about a minute the first time..."
  npm ci
fi
echo "Starting the demo at http://localhost:5173 . Press Ctrl+C to stop."
exec npm run dev -- --open
