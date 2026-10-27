#!/usr/bin/env bash
# One-time setup for GitHub Codespaces: ffmpeg, uv, and the project's packages.
# Each step runs even if an earlier one complains, so one flaky package source
# can't leave the codespace without the app.
set -u
cd "$(dirname "$0")/.." || exit 1
echo "== Accent Coach setup =="

# The base image ships a Yarn apt source that Accent Coach doesn't need; when its
# signing key expires, `apt-get update` fails. Remove it.
sudo rm -f /etc/apt/sources.list.d/yarn.list

if ! command -v ffmpeg >/dev/null 2>&1; then
  sudo apt-get update -y || echo "!! apt-get update reported problems; trying the install anyway"
  sudo apt-get install -y --no-install-recommends ffmpeg || echo "!! ffmpeg install failed"
fi

# uv's standalone installer doesn't depend on which Python is active (VS Code may
# have activated the project's .venv, which has no pip).
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh || echo "!! uv installer failed; trying pip"
fi
if ! command -v uv >/dev/null 2>&1; then
  # Fallback: the image's own Python (never the project's .venv, which has no pip).
  for py in /usr/local/bin/python3 /usr/bin/python3; do
    [ -x "$py" ] && "$py" -m pip install --user --upgrade uv && break
  done
  command -v uv >/dev/null 2>&1 || echo "!! uv install failed"
fi

uv sync || echo "!! uv sync failed"

if command -v ffmpeg >/dev/null 2>&1 && uv run accent-analyzer --version >/dev/null 2>&1; then
  echo "== Setup finished: Accent Coach is ready =="
else
  echo "!! Setup incomplete. Copy the messages above when asking for help."
  exit 1
fi
