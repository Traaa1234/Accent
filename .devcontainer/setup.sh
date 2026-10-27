#!/usr/bin/env bash
# One-time setup for GitHub Codespaces: ffmpeg, uv, and the project's packages.
# Each step runs even if an earlier one complains, so one flaky package source
# can't leave the codespace without the app.
set -u
echo "== Accent Coach setup =="

# The base image ships a Yarn apt source that Accent Coach doesn't need; when its
# signing key expires, `apt-get update` fails. Remove it.
sudo rm -f /etc/apt/sources.list.d/yarn.list

if ! command -v ffmpeg >/dev/null 2>&1; then
  sudo apt-get update -y || echo "!! apt-get update reported problems; trying the install anyway"
  sudo apt-get install -y --no-install-recommends ffmpeg || echo "!! ffmpeg install failed"
fi

python -m pip install --user --upgrade uv || echo "!! uv install failed"
python -m uv sync || echo "!! uv sync failed"

if command -v ffmpeg >/dev/null 2>&1 && python -m uv run accent-analyzer --version >/dev/null 2>&1; then
  echo "== Setup finished: Accent Coach is ready =="
else
  echo "!! Setup incomplete. Copy the messages above when asking for help."
  exit 1
fi
