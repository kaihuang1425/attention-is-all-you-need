@echo off
rem Start the Defensive Attention demo: installs the app's packages on first run, then opens the browser.
setlocal
cd /d "%~dp0app"
where node >nul 2>nul
if errorlevel 1 (
  echo Node.js 20 or newer is required. Install it from https://nodejs.org and run this again.
  pause
  exit /b 1
)
if not exist node_modules\vite (
  echo Installing app packages, this takes about a minute the first time...
  call npm ci
  if errorlevel 1 (
    echo npm ci failed. See the messages above.
    pause
    exit /b 1
  )
)
echo Starting the demo at http://localhost:5173 . Press Ctrl+C to stop.
call npm run dev -- --open
