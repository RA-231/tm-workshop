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

## An aside on tuning

Nothing below is something to run — it's the layer underneath everything you
just queried. Three knobs decide how much data an engine actually reads.

### 1. Partitioning

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

That's the whole mechanism, and it explains its limits. Pruning is only as good
as the column you partitioned on: a filter on `ts` still skips files via
min/max statistics, but only a filter on `ts_month` eliminates partitions
outright. And granularity is a trade — finer partitions prune better but make
every file smaller, which the next section shows is its own problem.

### 2. Compaction, and why streaming needs it

A streaming job doesn't write one file per partition. It writes one file per
open partition **per commit**, and it commits on the checkpoint interval:

```sql
SET 'execution.checkpointing.interval' = '5s';
```

Short commit windows are the normal choice for streaming — they bound how much
work a failure replays and how quickly rows become visible — but every one of
them closes the current files and starts new ones. This load committed 10 times
and produced **842 files across 168 partitions**, roughly five per partition,
averaging 126 KB. The data is correct; the packaging is poor. That's the
standing tax of streaming ingest, and it gets worse the shorter the window.

Compaction rewrites those into fewer, larger files — in Trino one statement,
wired up here as `task trino:optimize`:

```sql
ALTER TABLE iceberg.esa_adb.readings EXECUTE optimize;
```

Result on this warehouse: **842 files averaging 126 KB become 168 averaging
641 KB** — exactly one per partition, a 5× consolidation of identical data.
That matters because file count is a fixed tax: splitting the same rows and
bytes across 918 files instead of 98 measured ~3× the scan CPU, paid on every
query and buying nothing.

Two things to know about it. Compaction adds a snapshot rather than deleting
anything, so the pre-compaction files remain available for time travel until a
separate `expire_snapshots` clears them. And it only ever merges files **within**
a partition — so your partition granularity sets a ceiling on how large a
compacted file can be. Compaction cleans up after a load; it cannot rescue a
layout partitioned too finely to begin with.

### 3. Bloom filters, for the column you didn't partition on

Compaction has a side effect worth seeing. Before it runs, the data happens to
be clustered by channel — each input file holds one channel — so a channel
filter skips files for free via min/max statistics. Compaction merges every
channel in a month into one file, so afterwards `WHERE channel = 'channel_61'`
reads **all 27.6M rows across all 168 files**. That clustering was accidental,
and compaction spent it.

`channel` is not the partition column and shouldn't be — partitioning on it
multiplies partition count and shrinks every file. A bloom filter is the tool
for exactly this case: a small per-row-group index that answers "is this value
definitely absent here?", requiring no clustering and no extra partitions.

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

A bloom filter narrows rather than eliminates — it's probabilistic, it's
evaluated per row group at read time, and it only helps equality predicates.
What it buys is selectivity on a column you can't justify partitioning on, at a
cost that doesn't grow with the number of distinct values. That's the dividing
line: partition on the handful of columns you filter by constantly, and reach
for a bloom filter for the rest.


---

**Take a break.** ☕ When we come back: we stop writing SQL ourselves and
make a language model do it — [Step 3](03-chat.md).
