#!/usr/bin/env bash
# Drop the tables the Flink load creates, metadata-only, so re-running the load
# never appends duplicates. Idempotent — a table that isn't there is fine.
#
# Why not just DROP TABLE in the Flink SQL: Flink's FlinkCatalog.dropTable calls
# Catalog.dropTable(id), whose Iceberg default is purge=true, and there is no
# knob to change it. Polaris then deletes every data file in the background.
# At workshop scale that is ~900 Parquet files, which saturates its S3
# connection pool — measured 316 connection-acquisition timeouts and 337 failed
# deletes on one reload, which in turn made the *next* statements in the load
# fail (tables dropped but never recreated). Raising the pool only moves the
# threshold.
#
# purgeRequested=false makes the drop a catalog metadata operation: ~6ms, no
# background work, nothing competing with the load that follows. The old data
# files are left behind as orphans in the bucket — see `task clean` for the
# blunt fix, or sweep the prefix if a warehouse accumulates too many.
set -euo pipefail

POLARIS_URL="${POLARIS_URL:-http://localhost:8181}"
CLIENT_ID="${POLARIS_CLIENT_ID:-root}"
CLIENT_SECRET="${POLARIS_CLIENT_SECRET:-s3cr3t}"
CATALOG="${CATALOG_NAME:-workshop}"
NAMESPACE="${NAMESPACE:-esa_adb}"
TABLES="${TABLES:-readings channels labels anomaly_types}"

# After `task clean` the stack is rebuilt from scratch, so Polaris may still be
# starting. Wait rather than failing with a bare curl connection error.
POLARIS_WAIT_TRIES="${POLARIS_WAIT_TRIES:-30}"
polaris_up=""
for _ in $(seq 1 "${POLARIS_WAIT_TRIES}"); do
  if curl -sf -o /dev/null "${POLARIS_URL}/api/catalog/v1/oauth/tokens" -X POST \
      -d "grant_type=client_credentials&client_id=${CLIENT_ID}&client_secret=${CLIENT_SECRET}&scope=PRINCIPAL_ROLE:ALL"; then
    polaris_up=yes
    break
  fi
  sleep 2
done
[ -n "${polaris_up}" ] || {
  echo "polaris is not answering at ${POLARIS_URL} — is the ingest stack up? (task up:ingest)" >&2
  exit 1
}

TOKEN=$(curl -sf "${POLARIS_URL}/api/catalog/v1/oauth/tokens" -X POST \
  -d "grant_type=client_credentials&client_id=${CLIENT_ID}&client_secret=${CLIENT_SECRET}&scope=PRINCIPAL_ROLE:ALL" \
  | sed -n 's/.*"access_token" *: *"\([^"]*\)".*/\1/p')
[ -n "${TOKEN}" ] || { echo "failed to obtain token from ${POLARIS_URL}" >&2; exit 1; }

api="${POLARIS_URL}/api/catalog/v1/${CATALOG}/namespaces/${NAMESPACE}/tables"

for t in ${TABLES}; do
  status=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE \
    -H "Authorization: Bearer ${TOKEN}" \
    "${api}/${t}?purgeRequested=false")
  case "${status}" in
    204|200) echo "  dropped ${t}" ;;
    404)     echo "  ${t} not present" ;;
    *)       echo "  drop ${t} failed with HTTP ${status}"; exit 1 ;;
  esac
done
