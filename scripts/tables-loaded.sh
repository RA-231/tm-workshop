#!/usr/bin/env bash
# Exit 0 if the Flink load has already landed completely, non-zero otherwise.
# Used as the `status:` guard on `task flink:job`.
#
# Why guard it: Flink's DROP TABLE always asks the catalog to purge the data
# files (FlinkCatalog calls Catalog.dropTable(id), whose Iceberg default is
# purge=true — there is no knob), so re-running the load makes Polaris delete
# a few hundred Parquet files in the background. That saturates its S3
# connection pool, and every other catalog call then blocks on a connection
# acquisition timeout — a plain CREATE VIEW measured 54s instead of 0.8s.
# `task flink:reload` is the deliberate way to redo the load.
#
# Existence alone is not enough: an interrupted load leaves the table present
# but short. Compare the committed row count against the prepared input so a
# partial load still re-runs.
#
# The prepared input is trusted only when prepare left its manifest behind. It
# writes that last, so manifest-beside-JSON means the run finished; JSON with no
# manifest means it died partway and the input on disk is short.
set -euo pipefail

POLARIS_URL="${POLARIS_URL:-http://localhost:8181}"
CLIENT_ID="${POLARIS_CLIENT_ID:-root}"
CLIENT_SECRET="${POLARIS_CLIENT_SECRET:-s3cr3t}"
CATALOG="${CATALOG_NAME:-workshop}"
NAMESPACE="${NAMESPACE:-esa_adb}"
TABLES="${TABLES:-readings channels labels anomaly_types}"
PREPARED="${PREPARED:-data/prepared/channels}"
MANIFEST="${MANIFEST:-data/prepared/manifest.json}"

TOKEN=$(curl -sf "${POLARIS_URL}/api/catalog/v1/oauth/tokens" -X POST \
  -d "grant_type=client_credentials&client_id=${CLIENT_ID}&client_secret=${CLIENT_SECRET}&scope=PRINCIPAL_ROLE:ALL" \
  | sed -n 's/.*"access_token" *: *"\([^"]*\)".*/\1/p')
[ -n "$TOKEN" ] || exit 1

api="${POLARIS_URL}/api/catalog/v1/${CATALOG}/namespaces/${NAMESPACE}/tables"

for t in $TABLES; do
  status=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer ${TOKEN}" "${api}/${t}")
  [ "$status" = "200" ] || exit 1
done

# Completeness: the readings snapshot's total-records must match the row count
# prepare recorded. Reading it from the manifest also avoids counting lines
# across the JSON itself, which is ~58 GB on the medium set.
if [ ! -f "$MANIFEST" ]; then
  # No prepared input at all is the restored-checkpoint case: the warehouse is
  # loaded and complete, the source JSON was simply never built on this machine.
  compgen -G "${PREPARED}/*.json" >/dev/null || exit 0
  echo "prepared JSON is on disk but ${MANIFEST} is not: the last \`task data:prepare\` did not finish, so the input is short. Re-run it." >&2
  exit 1
fi

expected=$(sed -n 's/.*"rows" *: *\([0-9]*\).*/\1/p' "$MANIFEST" | head -1)
if [ -z "$expected" ]; then
  echo "no row count in ${MANIFEST} — re-run \`task data:prepare\`" >&2
  exit 1
fi

actual=$(curl -sf -H "Authorization: Bearer ${TOKEN}" "${api}/readings" \
  | sed -n 's/.*"total-records" *: *"\{0,1\}\([0-9]*\).*/\1/p' | head -1)

if [ "${actual:-0}" != "$expected" ]; then
  echo "readings holds ${actual:-0} rows, prepared input has ${expected}" >&2
  exit 1
fi
