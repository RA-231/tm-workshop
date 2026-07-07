#!/usr/bin/env bash
# One-time Superset init: metadata DB, admin user (admin/admin — workshop only),
# and the Trino connection pre-registered so attendees land in a working UI.
set -euo pipefail

superset db upgrade

superset fab create-admin \
  --username admin \
  --firstname Workshop \
  --lastname Admin \
  --email admin@example.com \
  --password admin 2>/dev/null || true

superset init

superset set-database-uri \
  --database_name "Trino (Iceberg telemetry)" \
  --uri "trino://trino@trino:8080/iceberg" || true

# Register the telemetry.readings table as a dataset (best-effort: skips
# cleanly if Trino/the table isn't up yet). Re-run with `task superset:dataset`.
python /app/register_dataset.py || true

exec /usr/bin/run-server.sh
