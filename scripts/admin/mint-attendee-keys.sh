#!/usr/bin/env bash
# Mint one expiring Bedrock API key per attendee seat. Run the night before or
# the morning of the workshop.
#
# Each seat is an IAM user (tmws-NN) carrying a Bedrock service-specific
# credential: a 132-char bearer token that can ONLY call Bedrock. Attendees get
# no AWS access keys, no console, no SDK credentials. CloudTrail attributes
# every call to the seat's IAM user, and `revoke-attendee-keys.sh --seat NN`
# kills one seat without touching the other 49.
#
# Validity window:
#   start  midnight MST on the day this script is run (computed at run time)
#   end    2026-10-06T23:59:59 MST -- HARD-CODED, the workshop's last moment
#
# Both are enforced as IAM Deny conditions on the group, so they apply to every
# key regardless of what anyone still holds, and independently of each key's own
# --days expiry.
#
#   ./mint-attendee-keys.sh [--seats 50] [--days 2]
#
# Writes attendee-keys.csv (mode 0600) -- the only copy of the secrets.
set -euo pipefail

SEATS=50; DAYS=2; GROUP=tm-workshop-attendees
PREFIX=tmws; OUT=attendee-keys.csv
POLICY_NAME=tm-workshop-attendee-bedrock

# MST is UTC-7 with no daylight adjustment, exactly as specified. If the venue
# actually observes MDT (UTC-6) on Oct 6, this cutoff lands at 00:59 local on
# Oct 7 -- an hour late rather than an hour early, which is the safe direction.
CUTOFF_LOCAL="2026-10-06T23:59:59-07:00"

while [ $# -gt 0 ]; do
  case "$1" in
    --seats)   SEATS=$2; shift 2 ;;
    --days)    DAYS=$2;  shift 2 ;;
    --profile) PROFILE=$2; shift 2 ;;
    --out)     OUT=$2;   shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done
# Credentials, account discovery and the IAM-admin check live here.
. "$(dirname "${0}")/_preflight.sh"
export AWS_REGION=${AWS_REGION:-us-east-1}

# Today in MST -- not UTC. Run at 7pm MST and the UTC date is already tomorrow;
# using that would open the window a day late.
read -r START END < <(python3 - "${CUTOFF_LOCAL}" <<'PY'
import sys
from datetime import datetime, timezone, timedelta
mst = timezone(timedelta(hours=-7))
start = datetime.now(mst).replace(hour=0, minute=0, second=0, microsecond=0)
end = datetime.fromisoformat(sys.argv[1])
fmt = lambda d: d.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
print(fmt(start), fmt(end))
PY
)

now_utc=$(python3 -c "from datetime import datetime,timezone;print(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))")
if [[ "${now_utc}" > "${END}" ]]; then
  echo "refusing to mint: the hard cutoff ${END} has already passed." >&2
  echo "the keys would be born dead. edit CUTOFF_LOCAL if the workshop moved." >&2
  exit 1
fi

echo "window:  ${START}  ..  ${END}   (cutoff ${CUTOFF_LOCAL})"
echo "seats:   ${SEATS}, key self-expiry: ${DAYS} days"
echo

POLICY_ARN="arn:aws:iam::${ACCOUNT}:policy/${POLICY_NAME}"
aws iam get-policy --policy-arn "${POLICY_ARN}" >/dev/null 2>&1 || {
  echo "missing policy ${POLICY_NAME} -- create it first" >&2; exit 1; }

echo "== group ${GROUP}"
aws iam get-group --group-name "${GROUP}" >/dev/null 2>&1 \
  || aws iam create-group --group-name "${GROUP}" >/dev/null
aws iam attach-group-policy --group-name "${GROUP}" --policy-arn "${POLICY_ARN}"

# Two separate Deny statements: conditions inside ONE statement are AND'ed, so
# "before start" and "after end" cannot share a statement.
W=$(mktemp -t window)
cat > "${W}" <<JSON
{"Version":"2012-10-17","Statement":[
 {"Sid":"DenyBeforeToday","Effect":"Deny","Action":"*","Resource":"*",
  "Condition":{"DateLessThan":{"aws:CurrentTime":"${START}"}}},
 {"Sid":"DenyAfterWorkshop","Effect":"Deny","Action":"*","Resource":"*",
  "Condition":{"DateGreaterThan":{"aws:CurrentTime":"${END}"}}}]}
JSON
aws iam put-group-policy --group-name "${GROUP}" \
  --policy-name workshop-time-window --policy-document "file://${W}"
rm -f "${W}"
echo "== time window applied"

umask 077
printf 'seat,user,alias,credential_id,expires,api_key\n' > "${OUT}"
for i in $(seq -f '%02g' 1 "${SEATS}"); do
  u="${PREFIX}-${i}"
  aws iam get-user --user-name "${u}" >/dev/null 2>&1 || \
    aws iam create-user --user-name "${u}" --tags \
      Key=purpose,Value=tm-workshop Key=seat,Value="${i}" \
      Key=cutoff,Value="${END}" Key=managed-by,Value=mint-attendee-keys >/dev/null
  aws iam add-user-to-group --group-name "${GROUP}" --user-name "${u}" 2>/dev/null || true
  aws iam create-service-specific-credential --user-name "${u}" \
      --service-name bedrock.amazonaws.com --credential-age-days "${DAYS}" --output json \
    | python3 -c "
import json,sys,csv
c=json.load(sys.stdin)['ServiceSpecificCredential']
csv.writer(sys.stdout).writerow(['${i}','${u}',c['ServiceCredentialAlias'],
  c['ServiceSpecificCredentialId'],c.get('ExpirationDate',''),c['ServiceCredentialSecret']])" >> "${OUT}"
  echo "  seat ${i} -> ${u}"
done
chmod 600 "${OUT}"
echo
echo "Wrote ${OUT} ($(($(wc -l < "${OUT}")-1)) keys, mode 0600)."
echo "Usable ${START} .. ${END}; each key also self-expires after ${DAYS} days."
