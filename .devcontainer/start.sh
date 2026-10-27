#!/usr/bin/env bash
# Starts Accent Coach; finishes the setup first if it didn't complete.
cd "$(dirname "$0")/.." || exit 1
export PATH="$HOME/.local/bin:$PATH"
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v uv >/dev/null 2>&1 \
   || ! uv run accent-analyzer --version >/dev/null 2>&1; then
  echo "Finishing setup first (a minute or two)..."
  bash .devcontainer/setup.sh || exit 1
fi
exec uv run accent-analyzer app --no-browser
