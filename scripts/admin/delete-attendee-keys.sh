#!/usr/bin/env bash
# Delete the service accounts for a seat prefix, revoking their keys.
#
#   ./delete-attendee-keys.sh                 # the tmws-NN seats, with a prompt
#   ./delete-attendee-keys.sh --prefix dryrun # rehearsal leftovers
#   ./delete-attendee-keys.sh --yes           # no prompt, for scripted re-mints
#
# This is for RE-MINTING, not teardown. mint-attendee-keys.sh skips seat names
# that already exist, so minting a second time over an earlier run silently
# produces nothing -- delete first, then mint. End-of-workshop cleanup needs no
# action at all: every key carries its own expiry.
#
# Deletion is immediate and permanent. Cards already handed out stop working.
set -euo pipefail

PREFIX=tmws
ARGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX=$2; shift 2 ;;
    --yes)    ARGS+=(--yes); shift ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

HERE="$(cd "$(dirname "${0}")" && pwd)"
. "${HERE}/_preflight.sh"

python3 "${HERE}/_delete.py" "${LLM_PROJECT_ID}" "${PREFIX}" "${ARGS[@]+"${ARGS[@]}"}"
