#!/usr/bin/env bash
# What models can this workshop project actually reach?
#
#   ./list-models.sh              # the project's allowlist
#   ./list-models.sh --check      # also cross-check litellm/config.yaml against it
#
# The project is scoped to a subset of the provider's catalogue, and that subset
# can change without warning -- so this is the authority on what the gateway may
# serve, and the reason litellm/config.yaml carries no model names of its own.
set -euo pipefail
HERE="$(cd "$(dirname "${0}")" && pwd)"
. "${HERE}/_preflight.sh"

echo "== models available to this project =="
_api GET "/organization/projects/${LLM_PROJECT_ID}/rate_limits?limit=100" \
  | python3 "${HERE}/_fmt.py" models

[ "${1:-}" = "--check" ] || exit 0

CFG="${HERE}/../../litellm/config.yaml"
echo
echo "== model names pinned in litellm/config.yaml vs. what the project allows =="
_api GET "/organization/projects/${LLM_PROJECT_ID}/rate_limits?limit=100" \
  | python3 "${HERE}/_fmt.py" check "${CFG}"
