#!/bin/bash
# One-click launcher for the LinkedIn content agent Telegram bot.
# Double-click this file in Finder — it opens Terminal and starts the bot.

# Always run from the project directory (where this file lives), so .env loads.
cd "$(dirname "$0")" || exit 1

echo "──────────────────────────────────────────────"
echo "  LinkedIn content agent — Telegram bot"
echo "  $(pwd)"
echo "──────────────────────────────────────────────"

# Finder gives launched .command files a minimal PATH; add the usual uv homes
# (Intel + Apple-Silicon Homebrew, and ~/.local/bin).
export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
  echo "❌ 'uv' not found on PATH. Install it (https://docs.astral.sh/uv/) and retry."
  echo "Press any key to close…"; read -r -n 1; exit 1
fi

# Telegram allows only one poller at a time — stop any bot already running.
if pkill -f "linkedin-agent bot" 2>/dev/null; then
  echo "Stopped a previous bot instance."
  sleep 1
fi

echo "Starting bot…  (press Ctrl+C, or close this window, to stop)"
echo

# Auto-restart on crashes (e.g. transient Telegram network timeouts) so the bot
# self-heals. A clean Ctrl+C shutdown exits 0 and breaks the loop.
trap 'echo; echo "Stopping."; exit 0' INT
while true; do
  uv run linkedin-agent bot
  code=$?
  if [ "$code" -eq 0 ]; then
    break
  fi
  echo
  echo "⚠️  Bot exited (code $code) — restarting in 5s.  Press Ctrl+C to stop."
  sleep 5
done

echo
echo "Bot stopped. Press any key to close…"
read -r -n 1
