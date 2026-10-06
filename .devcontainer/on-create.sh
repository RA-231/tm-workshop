#!/usr/bin/env bash
# Host tooling + the dataset. Runs during prebuild, so everything this does
# lands in the snapshot. Deliberately needs no Docker daemon: GitHub states
# Docker-in-Docker is unavailable at this point in the lifecycle.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> installing Task"
# The scripts call `task`; the official installer drops a single binary.
sudo sh -c "$(curl --location https://taskfile.dev/install.sh)" -- -d -b /usr/local/bin

echo "==> checking python3"
# Every workshop script is stdlib-only, so the interpreter alone is enough.
if ! command -v python3 >/dev/null 2>&1; then
  sudo apt-get update -qq && sudo apt-get install -y -qq python3
fi
python3 --version

echo "==> task setup"
task setup

echo "==> downloading the small ESA dataset (~139 MB)"
# Range requests against Zenodo -- no daemon, and it bakes into the prebuild so
# attendees start Step 1 without waiting on the download.
task data:download

echo "==> on-create done"
