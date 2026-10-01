# Step 2 — Querying Data with Trino and Superset

Flink wrote our telemetry into Iceberg. Now we get to the payoff of choosing
an open table format: *any* engine can read it. We'll use Trino interactively,
look at how it plans queries against Iceberg, then point Superset at it.

## Trino in one minute

Trino is a distributed SQL query engine — it owns no storage. You give it
*catalogs* (connectors + config) and it federates queries across them. Our
`iceberg` catalog points at the same Polaris REST catalog Flink writes to:
Trino asks Polaris "where's the current metadata for `esa_adb.readings`?",
gets back a pointer to a metadata file on disk, and plans the query from
there. **Polaris is the handoff point between the writer and the readers.**

```bash
task trino          # opens the Trino CLI
```

```sql
SHOW CATALOGS;
SHOW SCHEMAS FROM iceberg;
SELECT count(*) FROM iceberg.esa_adb.readings;

SELECT channel, count(*) AS samples, avg(value) AS mean
FROM iceberg.esa_adb.readings
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
SELECT avg(value) FROM iceberg.esa_adb.readings
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
SELECT * FROM iceberg.esa_adb."readings$snapshots";
SELECT file_path, record_count, file_size_in_bytes
FROM iceberg.esa_adb."readings$files" LIMIT 10;
```

Every Flink checkpoint you watched in Step 1 is a snapshot here. Time travel:

```sql
SELECT count(*) FROM iceberg.esa_adb.readings
FOR VERSION AS OF <snapshot_id>;
```

### What the provenance columns cost

Step 1 added five columns recording where each row came from. Logically that's
a value on every one of the 27 million rows. Physically it's almost nothing,
and the reason is the same machinery as above.

Each Flink writer task reads one input file, so within any given Parquet file
`source_file` is the *same string on every row* — and `run_id`, `ingest_ts`
and `ingest_mode` are constant across the whole load. Parquet stores a column
chunk per column per row group, and for a constant column that chunk is a
dictionary page holding one entry plus a run-length marker standing in for
millions of repeats. You pay for the string roughly once per row group, not
once per row.

Adding columns also creates **no new files**. File count follows partitioning,
writer parallelism and commit cadence — new columns become column chunks
inside the files that already exist.

The overhead that is real sits in the metadata rather than the data: Parquet
footers gain a column chunk entry per column, and Iceberg manifests gain a
`lower_bound` / `upper_bound` / `null_count` / `value_count` tuple per column
per data file. That scales with file count, not row count.

Measured on this warehouse the table runs about 4 bytes/row all-in — the five
constant-per-file columns add only a low single-digit percent on top of the
`channel, ts, ts_month, value` payload. Check the absolute size with:

```sql
SELECT count(*) AS files, sum(file_size_in_bytes) AS bytes,
       round(1.0 * sum(file_size_in_bytes) / sum(record_count), 3) AS bytes_per_row
FROM iceberg.esa_adb."readings$files";
```

Don't expect that number to be identical run to run. A lot of the per-row cost
is fixed metadata *per file* — Parquet footers and the manifest stat tuples
above — and the file count itself shifts with writer parallelism and checkpoint
timing from one load to the next. The columns are cheap; the file count is the
variable that actually moves the total.

And it can buy something back — but only if you ask for it. Because
`source_file` is constant within a file, its lower and upper bounds are equal,
so `WHERE source_file = '...'` can skip whole files through the same manifest
statistics that prune `ts_month` partitions.

The catch is that Iceberg truncates string bounds to 16 characters by default.
These paths all begin `/data/prepared/c…`, so truncated bounds are **identical
for every file** and nothing prunes — the engine reads everything and filters
row by row. `ingest.sql` therefore sets:

```sql
'write.metadata.metrics.column.source_file' = 'full'
```

which keeps the untruncated value in the manifest. Check the bounds yourself:

```sql
SELECT DISTINCT lower_bounds[5], upper_bounds[5]
FROM iceberg.esa_adb."readings$files";
```

Then measure the difference — `EXPLAIN ANALYZE` reports splits read and rows
filtered, which is where pruning shows up. The plain `EXPLAIN` cost estimate
will *not* show it, because the optimizer has no statistics for this column:

```sql
EXPLAIN ANALYZE SELECT count(*) FROM iceberg.esa_adb.readings
WHERE source_file = '/data/prepared/channels/channel_61.json';
```

On this dataset that takes the scan from every file — 17.4M rows and 791 MB
of physical input — down to 180 files, 905k rows and 3.8 MB.

Note it doesn't drop to a single file, and the reason is worth understanding.
The table is partitioned by `ts_month`, not by channel, so one Parquet file
holds whichever channels were active in that month. 180 is exactly the number
of files whose `source_file` range spans `channel_61` — the planner skipped
everything it possibly could. Pruning is bounded by how the data is laid out,
not just by the statistics.

It's a good lesson in its own right: a column only prunes if the statistics
recorded about it can actually tell files apart — and even then, only as well
as the physical layout allows.

One caveat worth carrying: this is cheap *because* the values are constant per
file. Per-row provenance — a source line number, a sequence ID — would defeat
the dictionary and cost real bytes on every row.

## Views: enrich once, reuse everywhere

`readings` carries the telemetry — `channel, ts, ts_month, value` — plus five
provenance columns describing where each row came from (`source_file`,
`source_mtime`, `ingest_ts`, `run_id`, `ingest_mode`; see the metadata-column
side-note in [Step 1](01-ingest.md)). Step 1 also loaded
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
FROM iceberg.esa_adb.readings_enriched
GROUP BY channel, subsystem, physical_unit;

-- the payoff: every reading tagged with whether it's inside a labeled anomaly
SELECT ts, value, is_anomaly, anomaly_category
FROM iceberg.esa_adb.labeled_readings
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

The stack comes pre-wired: the Trino connection (SQLAlchemy URI
`trino://trino@trino:8080/iceberg`) *and* the `readings` dataset are already
registered, so you can chart immediately. (Adding one by hand, if you ever
need to, is **Settings → Database Connections** and **Datasets → + Dataset**.)

Build a first chart:

1. **SQL Lab** — run one of the queries above to confirm connectivity.
2. Create a **chart** on the pre-registered `readings` dataset: time-series
   line, X = `ts` (day grain), Y = `AVG(value)`, dimension = `channel`, filter
   to 3–4 channels so it stays readable.
3. Add `labeled_readings` as a dataset (**Datasets → + Dataset** →
   `iceberg` / `esa_adb` / `labeled_readings`) and chart `channel_41` with
   `is_anomaly` as the color dimension — the anomalies light up.
4. Add both to a dashboard.

Superset is issuing the same SQL you wrote by hand — check **SQL Lab → Query
History** to see exactly what each chart ran, and notice the planner doing
the same pruning for dashboards as it did for you.

---

**Take a break.** ☕ When we come back: we stop writing SQL ourselves and
make a language model do it — [Step 3](03-chat.md).
