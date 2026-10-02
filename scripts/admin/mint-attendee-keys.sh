#!/usr/bin/env bash
# Mint one expiring API key per attendee seat. Run the night before or the
# morning of the workshop.
#
# Each seat is a service account named tmws-NN in the workshop project. The key
# it returns reaches that project and nothing else -- no dashboard, no billing,
# no other project -- and carries its own expiry, so the whole cohort dies at
# the cutoff with no teardown step.
#
# The service-account name is what the provider's usage and cost dashboards
# group by, so tmws-07 stays the unit of attribution: per-seat spend is
# visible even though per-key spend *limits* do not exist (the project's
# monthly hard limit is shared across all seats -- see README.md).
#
#   ./mint-attendee-keys.sh [--seats 50] [--prefix tmws] [--cutoff ISO8601]
#
# Use a different --prefix for rehearsals: seat names are skipped if they already
# exist, so dry-run accounts called tmws-NN would make the real mint skip those
# seats and hand out keys that expired hours earlier.
#
# Writes attendee-keys.csv (mode 0600) -- the only copy of the keys.
set -euo pipefail

SEATS=50; PREFIX=tmws; OUT=attendee-keys.csv

# MST is UTC-7 with no daylight adjustment, exactly as specified. If the venue
# actually observes MDT (UTC-6) on Oct 6, this cutoff lands at 00:59 local on
# Oct 7 -- an hour late rather than an hour early, which is the safe direction.
CUTOFF_LOCAL="2026-10-06T23:59:59-07:00"

while [ $# -gt 0 ]; do
  case "$1" in
    --seats)  SEATS=$2; shift 2 ;;
    --prefix) PREFIX=$2; shift 2 ;;
    --cutoff) CUTOFF_LOCAL=$2; shift 2 ;;
    --out)    OUT=$2;   shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

HERE="$(cd "$(dirname "${0}")" && pwd)"
. "${HERE}/_preflight.sh"

# The cutoff as an epoch, and a refusal if it has passed -- keys minted after it
# would be born dead.
read -r CUTOFF_EPOCH CUTOFF_UTC < <(python3 - "${CUTOFF_LOCAL}" <<'PY'
import sys
from datetime import datetime, timezone
end = datetime.fromisoformat(sys.argv[1])
print(int(end.timestamp()), end.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
PY
)
now_epoch=$(python3 -c 'import time; print(int(time.time()))')
if [ "${now_epoch}" -ge "${CUTOFF_EPOCH}" ]; then
  echo "refusing to mint: the cutoff ${CUTOFF_UTC} has already passed." >&2
  echo "the keys would be born dead. pass --cutoff if the workshop moved." >&2
  exit 1
fi

hours=$(( (CUTOFF_EPOCH - now_epoch) / 3600 ))
echo "cutoff:  ${CUTOFF_UTC}  (${CUTOFF_LOCAL}) -- ${hours}h from now"
echo "seats:   ${SEATS}"
echo
python3 "${HERE}/_mint.py" "${LLM_PROJECT_ID}" "${SEATS}" "${CUTOFF_EPOCH}" "${PREFIX}" "${OUT}"
