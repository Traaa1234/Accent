#!/usr/bin/env bash
# Starts Accent Coach; finishes the setup first if it didn't complete.
cd "$(dirname "$0")/.." || exit 1
export PATH="$HOME/.local/bin:$PATH"

# Keep recordings where a container rebuild won't delete them, and move over any
# data saved in the home folder by earlier versions.
export ACCENT_DATA_DIR="${ACCENT_DATA_DIR:-/workspaces/accent-data}"
if [ ! -e "$ACCENT_DATA_DIR" ] && [ -d "$HOME/.accent_analyzer" ]; then
  cp -a "$HOME/.accent_analyzer" "$ACCENT_DATA_DIR" && echo "Moved your recordings to $ACCENT_DATA_DIR"
fi
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v uv >/dev/null 2>&1 \
   || ! uv run accent-analyzer --version >/dev/null 2>&1; then
  echo "Finishing setup first (a minute or two)..."
  bash .devcontainer/setup.sh || exit 1
fi
exec uv run accent-analyzer app --no-browser
