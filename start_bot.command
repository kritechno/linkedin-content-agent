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
uv run linkedin-agent bot

echo
echo "Bot stopped. Press any key to close…"
read -r -n 1
