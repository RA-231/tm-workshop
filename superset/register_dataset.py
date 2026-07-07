"""Register the Iceberg `esa_adb.readings` table as a Superset dataset.

Runs inside the Superset application context (so it can write straight to the
metadata DB) rather than through the REST API — which means it works at
bootstrap time, before the web server is even up.

Idempotent and best-effort: if Trino or the table isn't ready yet (e.g. you
started Superset before ingesting), it logs and exits 0 so it never blocks
Superset from starting. Re-run any time with `task superset:dataset`.
"""

import sys
import time

try:
    from superset.app import create_app
except Exception:  # pragma: no cover - import path fallback across versions
    from superset import create_app

DB_NAME = "Trino (Iceberg telemetry)"
SCHEMA = "esa_adb"
TABLE = "readings"

app = create_app()
with app.app_context():
    from superset.connectors.sqla.models import SqlaTable
    from superset.extensions import db
    from superset.models.core import Database

    database = db.session.query(Database).filter_by(database_name=DB_NAME).one_or_none()
    if database is None:
        print(f"[register_dataset] database '{DB_NAME}' not found — skipping")
        sys.exit(0)

    table = (
        db.session.query(SqlaTable)
        .filter_by(table_name=TABLE, schema=SCHEMA, database_id=database.id)
        .one_or_none()
    )
    if table is None:
        table = SqlaTable(table_name=TABLE, schema=SCHEMA, database=database)
        db.session.add(table)

    # fetch_metadata() introspects the table over Trino. Trino (and the table
    # itself) may still be coming up, so retry a few times before giving up.
    error = None
    for _ in range(12):
        try:
            table.fetch_metadata()
            error = None
            break
        except Exception as exc:  # noqa: BLE001 - best-effort bootstrap
            error = exc
            time.sleep(5)
    if error is not None:
        print(f"[register_dataset] table not queryable yet ({error}) — skipping")
        db.session.rollback()
        sys.exit(0)

    # Make time-series charts work without hand-configuration.
    if any(col.column_name == "ts" for col in table.columns):
        table.main_dttm_col = "ts"

    # SQLite metadata DB can be briefly locked by the running server; retry.
    for attempt in range(5):
        try:
            db.session.commit()
            break
        except Exception:  # noqa: BLE001
            db.session.rollback()
            time.sleep(2)
            if attempt == 4:
                raise

    print(f"[register_dataset] dataset '{SCHEMA}.{TABLE}' registered (id={table.id})")
