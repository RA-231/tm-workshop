#!/usr/bin/env bash
# Create the `workshop` catalog in Polaris and grant the root principal full
# access to it. Idempotent — safe to re-run.
#
# API flow (Polaris 1.5 quickstart):
#   1. OAuth2 client-credentials token for the bootstrapped root principal
#   2. Create the catalog (S3 storage on the Garage `warehouse` bucket)
#   3. Grant CATALOG_MANAGE_CONTENT to the catalog_admin role
#   4. Attach catalog_admin to the service_admin principal role (root has it)
set -euo pipefail

POLARIS_URL="${POLARIS_URL:-http://localhost:8181}"
CLIENT_ID="${POLARIS_CLIENT_ID:-root}"
CLIENT_SECRET="${POLARIS_CLIENT_SECRET:-s3cr3t}"
CATALOG="${CATALOG_NAME:-workshop}"
WAREHOUSE="s3://warehouse"

echo "waiting for polaris at ${POLARIS_URL} ..."
for i in $(seq 1 60); do
  if curl -sf -o /dev/null "${POLARIS_URL}/api/catalog/v1/oauth/tokens" -X POST \
      -d "grant_type=client_credentials&client_id=${CLIENT_ID}&client_secret=${CLIENT_SECRET}&scope=PRINCIPAL_ROLE:ALL"; then
    break
  fi
  sleep 2
  [ "$i" = 60 ] && { echo "polaris did not come up"; exit 1; }
done

TOKEN=$(curl -sf "${POLARIS_URL}/api/catalog/v1/oauth/tokens" -X POST \
  -d "grant_type=client_credentials&client_id=${CLIENT_ID}&client_secret=${CLIENT_SECRET}&scope=PRINCIPAL_ROLE:ALL" \
  | sed -n 's/.*"access_token" *: *"\([^"]*\)".*/\1/p')
[ -n "$TOKEN" ] || { echo "failed to obtain token"; exit 1; }

auth=(-H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json")
mgmt="${POLARIS_URL}/api/management/v1"

echo "creating catalog '${CATALOG}' ..."
create_status=$(curl -s -o /dev/null -w "%{http_code}" "${mgmt}/catalogs" "${auth[@]}" -d @- <<EOF
{
  "catalog": {
    "name": "${CATALOG}",
    "type": "INTERNAL",
    "readOnly": false,
    "properties": { "default-base-location": "${WAREHOUSE}" },
    "storageConfigInfo": {
      "storageType": "S3",
      "endpoint": "http://garage:3900",
      "endpointInternal": "http://garage:3900",
      "pathStyleAccess": true,
      "region": "garage",
      "stsUnavailable": true,
      "allowedLocations": ["${WAREHOUSE}"]
    }
  }
}
EOF
)
case "$create_status" in
  2*)  echo "  created" ;;
  409) echo "  already exists" ;;
  *)   echo "  create failed with HTTP ${create_status}"; exit 1 ;;
esac

# Both of these are PUTs that grant roles/privileges. Re-running is a no-op the
# first success makes permanent — but Polaris's JDBC backend reports an existing
# grant as a 500 "duplicate key" (not a clean 409), so treat that as success
# too. Only a genuinely new failure should abort.
put_ok() {
  local resp status body
  resp=$(curl -s -w $'\n%{http_code}' -X PUT "$1" "${auth[@]}" -d "$2")
  status=${resp##*$'\n'}
  body=${resp%$'\n'*}
  case "$status" in
    2*|409) return 0 ;;
    500) printf '%s' "$body" | grep -qiE "already exists|duplicate key" && return 0 ;;
  esac
  echo "  $1 -> HTTP ${status}: ${body}"; exit 1
}

echo "granting catalog_admin the rights to manage content ..."
put_ok "${mgmt}/catalogs/${CATALOG}/catalog-roles/catalog_admin/grants" \
  '{"grant": {"type": "catalog", "privilege": "CATALOG_MANAGE_CONTENT"}}'

echo "attaching catalog_admin to the service_admin principal role ..."
put_ok "${mgmt}/principal-roles/service_admin/catalog-roles/${CATALOG}" \
  '{"catalogRole": {"name": "catalog_admin"}}'

echo "catalog '${CATALOG}' is ready"
