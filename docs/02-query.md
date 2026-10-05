# Step 2 — Querying Data with Trino and Superset

[Flink](https://flink.apache.org/) wrote our telemetry into
[Iceberg](https://iceberg.apache.org/). We can query those tables with another
engine that supports the format. We'll use [Trino](https://trino.io/)
interactively, inspect its query plans, then connect
[Superset](https://superset.apache.org/) to it.

## 2.1 — Query the tables with Trino

Trino is a distributed SQL query engine that reads data from external storage.
Its catalogs contain connectors and configuration, and it can query across
them. Our `iceberg` catalog points at the same
[Polaris](https://polaris.apache.org/) REST catalog Flink writes to: Trino
requests the current metadata location for `esa_adb.readings` from Polaris and
uses that metadata to plan the query. Both engines use Polaris to locate the
table's current state.

### 2.1.1 — Open the Trino CLI

```bash
# opens the Trino CLI
task trino
```

### 2.1.2 — Run the first queries

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

## 2.2 — Inspect query plans and snapshots

### 2.2.1 — Compare query filters

Iceberg manifests track every data file along with per-column min/max
statistics, and the table is partitioned (ours
by month, in the `ts_month` column). Trino uses this metadata to plan queries:

```sql
EXPLAIN
SELECT avg(value) FROM iceberg.esa_adb.readings
WHERE ts_month = '2000-03';
```

Look for the estimated rows on the table scan, then widen the filter (e.g.
`ts_month BETWEEN '2000-03' AND '2000-09'`) and `EXPLAIN` again. The scan size
tracks the filter because Trino consults Iceberg's metadata to **prune
partitions and skip files** before reading a single byte of
[Parquet](https://parquet.apache.org/docs/overview/). Filtering on `ts`
directly works too — Iceberg's column statistics still skip files —
but a `ts_month` filter prunes whole partitions outright. Run the queries
(without `EXPLAIN`) and compare wall-clock times; then check the query detail
in the Trino UI at [http://localhost:8080/ui/](http://localhost:8080/ui/) to
see splits and bytes read.

### 2.2.2 — Query table metadata and earlier snapshots

Trino exposes Iceberg metadata tables for snapshots, files, and history:

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

## 2.3 — Create and query the telemetry views

`readings` carries the telemetry — `channel, ts, ts_month, value` — plus five
provenance columns describing where each row came from (`source_file`,
`source_mtime`, `ingest_ts`, `run_id`, `ingest_mode`; see the metadata-column
section in [Step 1](01-ingest.md)). Step 1 also loaded
three dimension tables: `channels` (what each channel measures), `labels` (the
ESA-labeled anomaly windows), and `anomaly_types` (the taxonomy). Views define
these joins for reuse in SQL Lab, Superset, and the Step 4
[MCP](https://modelcontextprotocol.io/) server.

### 2.3.1 — Create the views

```bash
# creates the views below
task trino:views
```

### 2.3.2 — Query enriched readings and anomaly labels

Open [`trino/views.sql`](../trino/views.sql) — each is a plain `CREATE VIEW`.
For example:

```sql
-- readings + their channel metadata
SELECT channel, subsystem, physical_unit, avg(value) AS mean
FROM iceberg.esa_adb.readings_enriched
GROUP BY channel, subsystem, physical_unit;

-- readings tagged with whether they're inside a labeled anomaly
SELECT ts, value, is_anomaly, anomaly_category
FROM iceberg.esa_adb.labeled_readings
WHERE channel = 'channel_41' AND is_anomaly
ORDER BY ts
LIMIT 20;
```

`labeled_readings` is a range join — each reading matched to any anomaly window
covering its timestamp. Superset uses this view to color anomaly periods, and
the model can query it to investigate channel_41 in Step 4. The label timestamps
are ISO-8601 UTC strings; the `anomalies` view parses them into timestamps that
match `readings.ts`.

## 2.4 — Create charts in Superset

### 2.4.1 — Start the query services

```bash
# starts Trino + Superset — http://localhost:8088 (admin / admin)
task up:query
```

The stack registers the Trino connection (SQLAlchemy URI
`trino://trino@trino:8080/iceberg`) and the `readings` dataset automatically.
To add them manually, use **Settings → Database Connections** and
**Datasets → + Dataset**.

### 2.4.2 — Check the SQL Lab connection

Open [Superset](http://localhost:8088), log in with `admin` / `admin`, and run
one of the queries above in **SQL Lab** to confirm connectivity.

### 2.4.3 — Chart the telemetry readings

Create a **chart** on the pre-registered `readings` dataset: time-series
line, X = `ts` (day grain), Y = `AVG(value)`, dimension = `channel`. Filter
to 3–4 channels so it stays readable.

### 2.4.4 — Chart the labeled anomalies

Add `labeled_readings` as a dataset (**Datasets → + Dataset** →
`iceberg` / `esa_adb` / `labeled_readings`) and chart `channel_41` with
`is_anomaly` as the color dimension to distinguish the labeled anomalies.

### 2.4.5 — Add a dashboard and inspect its queries

Add both charts to a dashboard.

Superset is issuing the same SQL you wrote by hand — check **SQL Lab → Query
History** to see exactly what each chart ran, and notice the planner doing
the same pruning for dashboards as it did for you.

## 2.5 — Storage layout and query performance (optional)

The following examples explain partitioning, compaction, and bloom filters.
You don't need to run them during this step.

### 2.5.1 — Partitioning

[`flink/sql/ingest.sql`](../flink/sql/ingest.sql) partitions the fact table on
one column:

```sql
) PARTITIONED BY (ts_month)
```

Iceberg stores each file's partition value in the manifest, alongside the
min/max statistics from earlier. So when a query filters on the partition
column, the planner discards non-matching files by reading metadata alone —
before opening a single Parquet file. Filtering `ts_month = '2000-03'` reads
**one file and 142,705 rows** out of 168 files and 27.6 million rows.

Partition pruning depends on the partition column: a filter on `ts` still
skips files via min/max statistics, but only a filter on `ts_month` eliminates partitions
outright. Finer partitions can improve pruning, but they also produce smaller
files, increasing the overhead described below.

### 2.5.2 — Compaction after streaming ingest

A streaming job doesn't write one file per partition. It writes one file per
open partition **per commit**, and it commits on the checkpoint interval:

```sql
SET 'execution.checkpointing.interval' = '5s';
```

Short commit windows are the normal choice for streaming — they bound how much
work a failure replays and how quickly rows become visible — but every one of
them closes the current files and starts new ones. This load committed 10 times
and produced **842 files across 168 partitions**, roughly five per partition,
averaging 126 KB. Shorter checkpoint intervals generally produce more small
files, increasing the overhead of reading them.

Compaction rewrites those into fewer, larger files. `task trino:optimize` runs
this Trino statement:

```sql
ALTER TABLE iceberg.esa_adb.readings EXECUTE optimize;
```

Result on this warehouse: **842 files averaging 126 KB become 168 averaging
641 KB** — exactly one per partition, a 5× consolidation of identical data.
Opening and processing each file adds overhead: scanning the same rows and
bytes across 918 files instead of 98 measured ~3× the scan CPU.

Compaction adds a snapshot, so the pre-compaction files remain available for
time travel until a separate `expire_snapshots` clears them. It merges files **within**
a partition — so your partition granularity sets a ceiling on how large a
compacted file can be. Compaction reduces file count but cannot merge small
partitions into larger ones.

### 2.5.3 — Bloom filters for non-partition columns

Compaction can also change data clustering. Before it runs, the data happens to
be clustered by channel — each input file holds one channel — so a channel
filter skips files via min/max statistics. Compaction merges every
channel in a month into one file, so afterwards `WHERE channel = 'channel_61'`
reads **all 27.6M rows across all 168 files**. The compacted files no longer
have the channel clustering of the input files.

Partitioning on `channel` as well as month would multiply the partition count
and produce smaller files. A bloom filter can help with channel filters without
adding partitions: it is a small per-row-group index that can identify values
that are definitely absent.

```sql
ALTER TABLE iceberg.esa_adb.readings
  SET PROPERTIES parquet_bloom_filter_columns = ARRAY['channel'];
```

Measured on a 5.4M-row slice where only 104,998 rows match the filter:

| approach | rows read |
|---|---|
| nothing | 1,193,591 |
| sort by channel | 725,278 |
| **bloom filter on channel** | **336,966** |

A bloom filter can reduce the rows read for equality predicates, but it may
return false positives. It is evaluated per row group at read time. For this
dataset, partitioning by month and adding a bloom filter on channel support
both time-window and channel queries without increasing the partition count.


---

**Break.** Next, connect a language model to the workshop stack:
[Step 3](03-chat.md).
