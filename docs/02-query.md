# Step 2 — Querying Data with Trino and Superset

Flink wrote our telemetry into Iceberg. Now we get to the payoff of choosing
an open table format: *any* engine can read it. We'll use Trino interactively,
look at how it plans queries against Iceberg, then point Superset at it.

## Trino in one minute

Trino is a distributed SQL query engine — it owns no storage. You give it
*catalogs* (connectors + config) and it federates queries across them. Our
`iceberg` catalog points at the same Polaris REST catalog Flink writes to:
Trino asks Polaris "where's the current metadata for `telemetry.readings`?",
gets back a pointer to a metadata file on disk, and plans the query from
there. **Polaris is the handoff point between the writer and the readers.**

```bash
task trino          # opens the Trino CLI
```

```sql
SHOW CATALOGS;
SHOW SCHEMAS FROM iceberg;
SELECT count(*) FROM iceberg.telemetry.readings;

SELECT channel, count(*) AS samples, avg(value) AS mean
FROM iceberg.telemetry.readings
GROUP BY channel
ORDER BY samples DESC
LIMIT 10;
```

## How the planner uses Iceberg

Iceberg tables carry rich metadata: every data file is tracked in manifests
along with per-column min/max statistics, and the table is partitioned (ours
by month, in the `ts_month` column). Trino exploits all of it. Compare:

```sql
EXPLAIN
SELECT avg(value) FROM iceberg.telemetry.readings
WHERE ts_month = '2000-03';
```

Look for the estimated rows on the table scan, then widen the filter (e.g.
`ts_month BETWEEN '2000-03' AND '2000-09'`) and `EXPLAIN` again. The scan size
tracks the filter because Trino consults Iceberg's metadata to **prune
partitions and skip files** before reading a single byte of Parquet. Filtering
on `ts` directly works too — Iceberg's column statistics still skip files —
but a `ts_month` filter prunes whole partitions outright. Run the queries
(without `EXPLAIN`) and compare wall-clock times; then check the query detail
in the Trino UI at [http://localhost:8080/ui/](http://localhost:8080/ui/) to
see splits and bytes read.

Iceberg also gives you tables *about* the table — snapshots, files, history:

```sql
SELECT * FROM iceberg.telemetry."readings$snapshots";
SELECT file_path, record_count, file_size_in_bytes
FROM iceberg.telemetry."readings$files" LIMIT 10;
```

Every Flink checkpoint you watched in Step 1 is a snapshot here. Time travel:

```sql
SELECT count(*) FROM iceberg.telemetry.readings
FOR VERSION AS OF <snapshot_id>;
```

## Views: enrich once, reuse everywhere

`readings` is a bare fact table — `channel, ts, value`. Step 1 also loaded
three dimension tables: `channels` (what each channel measures), `labels` (the
ESA-labeled anomaly windows), and `anomaly_types` (the taxonomy). Views let us
join those once and give everyone — SQL Lab, Superset, and the Step 4 MCP
server — a richer table to point at.

```bash
task trino:views    # creates the views below
```

Open [`trino/views.sql`](../trino/views.sql) — each is a plain `CREATE VIEW`.
The interesting ones:

```sql
-- readings + their channel metadata
SELECT channel, subsystem, physical_unit, avg(value) AS mean
FROM iceberg.telemetry.readings_enriched
GROUP BY channel, subsystem, physical_unit;

-- the payoff: every reading tagged with whether it's inside a labeled anomaly
SELECT ts, value, is_anomaly, anomaly_category
FROM iceberg.telemetry.labeled_readings
WHERE channel = 'channel_41' AND is_anomaly
ORDER BY ts
LIMIT 20;
```

`labeled_readings` is a range join — each reading matched to any anomaly window
covering its timestamp. That single view is what powers "color the anomalies"
in a Superset chart and "investigate the anomalies on channel_41" for Claude in
Step 4. (The label timestamps are ISO-8601 UTC strings; the `anomalies` view
parses them into plain timestamps that line up with `readings.ts`.)

## Superset

```bash
task up:query    # starts Trino + Superset — http://localhost:8088 (admin / admin)
```

The stack pre-registers the Trino connection (SQLAlchemy URI
`trino://trino@trino:8080/iceberg`). If you need to add it by hand:
**Settings → Database Connections → + Database → Trino** and paste that URI.

Build a first chart:

1. **SQL Lab** — run one of the queries above to confirm connectivity.
2. **Datasets → + Dataset** — pick `iceberg` / `telemetry` / `readings`.
3. Create a **chart**: time-series line, X = `ts` (day grain), Y = `AVG(value)`,
   dimension = `channel`, filter to 3–4 channels so it stays readable.
4. Add it to a dashboard, add a second chart (row counts per channel, big
   number of total samples — your call).

Superset is issuing the same SQL you wrote by hand — check **SQL Lab → Query
History** to see exactly what each chart ran, and notice the planner doing
the same pruning for dashboards as it did for you.

---

**Take a break.** ☕ When we come back: we stop writing SQL ourselves and
make a language model do it — [Step 3](03-chat.md).
