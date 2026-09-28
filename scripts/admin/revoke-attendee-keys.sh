#!/usr/bin/env bash
# Revoke attendee Bedrock keys. Three modes:
#   ./revoke-attendee-keys.sh --seat 07          disable seat 07 (reversible)
#   ./revoke-attendee-keys.sh --seat 07 --delete delete seat 07's key
#   ./revoke-attendee-keys.sh --all --delete     delete every key
#   ./revoke-attendee-keys.sh --teardown         delete keys, users, group, policy
set -euo pipefail
PREFIX=tmws; GROUP=tm-workshop-attendees
POLICY_NAME=tm-workshop-attendee-bedrock
SEAT=""; ALL=0; DELETE=0; TEARDOWN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --seat) SEAT=$2; shift 2 ;;
    --all) ALL=1; shift ;;
    --delete) DELETE=1; shift ;;
    --teardown) TEARDOWN=1; ALL=1; DELETE=1; shift ;;
    --profile) PROFILE=$2; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done
. "$(dirname "${0}")/_preflight.sh"
export AWS_REGION=${AWS_REGION:-us-east-1}

users=""
if [ -n "${SEAT}" ]; then users="${PREFIX}-${SEAT}"
elif [ "${ALL}" = 1 ]; then
  users=$(aws iam get-group --group-name "${GROUP}" --query 'Users[].UserName' --output text 2>/dev/null || true)
else echo "specify --seat NN, --all or --teardown" >&2; exit 1; fi

for u in ${users}; do
  ids=$(aws iam list-service-specific-credentials --user-name "${u}" \
        --service-name bedrock.amazonaws.com \
        --query 'ServiceSpecificCredentials[].ServiceSpecificCredentialId' --output text 2>/dev/null || true)
  for id in ${ids}; do
    if [ "${DELETE}" = 1 ]; then
      aws iam delete-service-specific-credential --user-name "${u}" --service-specific-credential-id "${id}"
      echo "  deleted ${u} / ${id}"
    else
      aws iam update-service-specific-credential --user-name "${u}" \
        --service-specific-credential-id "${id}" --status Inactive
      echo "  disabled ${u} / ${id}"
    fi
  done
  if [ "${TEARDOWN}" = 1 ]; then
    aws iam remove-user-from-group --group-name "${GROUP}" --user-name "${u}" 2>/dev/null || true
    aws iam delete-user --user-name "${u}" && echo "  deleted user ${u}"
  fi
done

if [ "${TEARDOWN}" = 1 ]; then
  aws iam delete-group-policy --group-name "${GROUP}" --policy-name expire-after-workshop 2>/dev/null || true
  aws iam detach-group-policy --group-name "${GROUP}" \
    --policy-arn "arn:aws:iam::${ACCOUNT}:policy/${POLICY_NAME}" 2>/dev/null || true
  aws iam delete-group --group-name "${GROUP}" 2>/dev/null || true
  echo "teardown complete"
fi
