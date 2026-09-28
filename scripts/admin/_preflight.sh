#!/usr/bin/env bash
# Shared guard for the admin scripts. Sourced, not run.
#
# Two jobs:
#   1. Refuse to run without working AWS credentials, so a curious attendee who
#      clones the repo gets a clear message instead of a confusing half-failure
#      partway through a 50-seat loop.
#   2. Discover the account ID at run time rather than storing it in the repo.
#      The account ID is not published to attendees, so it must not be committed.
#      Everything runs against whatever account the current STS credentials
#      resolve to -- switch accounts by switching credentials, nothing else.

command -v aws >/dev/null 2>&1 || {
  echo "aws CLI not found. Install it and authenticate first." >&2; exit 1; }

if ! CALLER_JSON=$(aws sts get-caller-identity --output json 2>&1); then
  cat >&2 <<MSG
No valid AWS credentials.

These scripts administer IAM in the workshop account; they are for the
facilitator, not for attendees. Attendees need nothing from this directory --
their Bedrock key comes on a card.

Authenticate (e.g. 'aws sso login --profile <your-profile>') and retry.
MSG
  exit 1
fi

ACCOUNT=$(printf '%s' "${CALLER_JSON}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["Account"])')
CALLER_ARN=$(printf '%s' "${CALLER_JSON}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["Arn"])')

# Permission is deliberately NOT pre-checked: simulate-principal-policy rejects
# assumed-role ARNs, so for SSO identities it can only ever return "unknown" and
# wave everything through. A gate that always opens is worse than none. An
# under-permissioned caller gets a plain AccessDenied from the first real call.
echo "account ${ACCOUNT} as ${CALLER_ARN}"
