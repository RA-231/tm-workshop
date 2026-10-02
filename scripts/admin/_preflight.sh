#!/usr/bin/env bash
# Shared guard for the admin scripts. Sourced, not run.
#
# Two jobs:
#   1. Refuse to run without an admin credential that works, so a curious attendee
#      who clones the repo gets a clear message instead of a confusing half-failure
#      partway through a 50-seat loop.
#   2. Resolve the workshop project at run time rather than storing its id in the
#      repo -- the project id identifies the org, the same reason the AWS account
#      id was never committed.
#
# Expects, from your environment (see scripts/admin/README.md):
#   LLM_ADMIN_KEY     an admin key (sk-admin-...). Project keys cannot administer.
#   LLM_PROJECT_ID    the workshop project, or LLM_PROJECT_NAME to look it up.

API=${LLM_API_BASE:-https://api.openai.com/v1}
_FMT="$(dirname "${BASH_SOURCE[0]}")/_fmt.py"

[ -n "${LLM_ADMIN_KEY:-}" ] || {
  cat >&2 <<MSG
No admin credential.

These scripts administer the workshop's LLM project; they are for the
facilitator, not for attendees. Attendees need nothing from this directory --
their key comes on a card.

  export LLM_ADMIN_KEY=\$(secret get OPEN_AI_ADMIN_KEY)

It must be an admin key (sk-admin-...); a project key (sk-proj-...) cannot
create service accounts.
MSG
  exit 1
}

_api() {  # _api <method> <path> [json-body]
  if [ -n "${3:-}" ]; then
    curl -sS -X "${1}" "${API}${2}" \
      -H "Authorization: Bearer ${LLM_ADMIN_KEY}" \
      -H "Content-Type: application/json" -d "${3}"
  else
    curl -sS -X "${1}" "${API}${2}" -H "Authorization: Bearer ${LLM_ADMIN_KEY}"
  fi
}

_PROJECTS=$(_api GET "/organization/projects?limit=100")

if printf '%s' "${_PROJECTS}" | grep -q '"error"'; then
  echo "admin credential rejected:" >&2
  printf '%s' "${_PROJECTS}" | python3 "${_FMT}" projects >/dev/null 2>&1 || true
  printf '%s' "${_PROJECTS}" | python3 "${_FMT}" projects 2>&1 >/dev/null | head -2 >&2
  echo "  (an sk-proj-... project key cannot reach /organization/*; use an sk-admin-... key)" >&2
  exit 1
fi

if [ -z "${LLM_PROJECT_ID:-}" ]; then
  if [ -n "${LLM_PROJECT_NAME:-}" ]; then
    LLM_PROJECT_ID=$(printf '%s' "${_PROJECTS}" | python3 "${_FMT}" project-id "${LLM_PROJECT_NAME}") || {
      echo "no active project named '${LLM_PROJECT_NAME}'." >&2; exit 1; }
  else
    echo "Set LLM_PROJECT_ID, or LLM_PROJECT_NAME to look it up. Active projects:" >&2
    printf '%s' "${_PROJECTS}" | python3 "${_FMT}" projects >&2
    exit 1
  fi
fi
export LLM_PROJECT_ID

echo "project $(printf '%s' "${_PROJECTS}" | python3 "${_FMT}" project-name "${LLM_PROJECT_ID}") (${LLM_PROJECT_ID})"
