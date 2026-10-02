# Step 1 — Ingesting Data into Iceberg with Flink

Load raw ESA telemetry files into an Iceberg table with Flink. This step
explains how the table format stores data and how the catalog tracks it.

## 1.1 — Iceberg table layout

Iceberg is a table format that tracks data files and their metadata.
A table is a set of objects in the warehouse — here, the `warehouse` bucket in
Garage:

```
s3://warehouse/esa_adb/readings/
├── metadata/
│   ├── v3.metadata.json        ← table schema, partition spec, snapshot list
│   ├── snap-8231...avro        ← manifest list: one per snapshot
│   └── 92f1...-m0.avro         ← manifests: which data files, with stats
└── data/
    └── ts_month=2000-03/
        └── 00000-0-...parquet  ← the actual rows
```

To read a table, an engine finds the current `metadata.json`, follows it to a
snapshot and its manifests, then reads the data files that match the query's
filters. To write, it creates new Parquet files and metadata, then atomically
updates the pointer to the current metadata. This update commits the write;
readers continue to see the previous snapshot until it completes.

This supports two important operations:

1. **Time travel and rollback.** Retained snapshots describe earlier versions
   of the table.
2. **Coordinated commits.** The catalog manages the metadata pointer for
   writers and readers.

## 1.2 — The Polaris catalog

Polaris is an implementation of the **Iceberg REST catalog** protocol. It's
the service that maps `esa_adb.readings` → "current
metadata file is `v3.metadata.json`" and performs the atomic swap on commit.

Because Flink (writer) and Trino (reader, Step 2) both speak the REST catalog
protocol to the same Polaris instance, they use the same table metadata.
The catalog coordinates access without requiring Flink and Trino to
communicate directly.

> In production, Polaris also handles access control and can vend scoped,
> temporary storage credentials to each engine. In this workshop, every engine
> uses the same static key for **Garage**, the S3-compatible object store
> running locally in a container.

## 1.3 — Flink ingestion and input preparation

Flink is a stream *and* batch processing engine. Our job reads every prepared
telemetry file and *streams* the rows into Iceberg: the sink commits a new
snapshot at each checkpoint, so the table grows in visible increments while the
job runs. The file source is bounded — once every file has been read the job
finishes on its own. The exact same SQL pointed at a live feed instead of a
directory could run continuously. Here, Flink processes a finite source in
streaming mode.

The ESA channels ship as pickled pandas DataFrames, which Flink can't read
directly, so there's a one-time prep step (`task data:prepare`) that converts
each channel to newline-delimited JSON under `data/prepared/channels/`. Flink's
filesystem connector reads that directory.

The same prep step also converts the dataset's **metadata** — the channel
catalog, the labeled anomaly windows, and the anomaly taxonomy — into
`data/prepared/meta/`. `task flink:job` loads those as three small dimension
tables (`channels`, `labels`, `anomaly_types`) alongside `readings`. Step 2's
views and Step 4's anomaly investigation use these tables.

## 1.4 — Run the ingest

### 1.4.1 — Start the ingestion services

```bash
task up:ingest        # setup garage, polaris, flink — init S3 bucket
```

### 1.4.2 — Prepare the telemetry files

```bash
task data:prepare     # pickled channels -> JSON under data/prepared/
```

### 1.4.3 — Create the Polaris catalog

```bash
task catalog:create   # create the 'workshop' catalog in Polaris
```

### 1.4.4 — Load the Iceberg tables

```bash
task flink:job        # run the ingest job (Flink SQL) — blocks until loaded
```

### 1.4.5 — Inspect the running job and warehouse

While `flink:job` runs:

- **Flink UI** [http://localhost:8081](http://localhost:8081) — watch the job
  read the files and write to the sink, one snapshot per checkpoint.
- **Look at the objects.** The metadata and Parquet files land in Garage:

  ```bash
  docker compose exec garage /garage bucket info warehouse
  ```

## 1.5 — Inspect the ingest SQL

Open the ingest SQL in [`flink/sql/ingest.sql`](../flink/sql/ingest.sql).
One statement defines the
prepared JSON as a table, one defines the Iceberg catalog via Polaris, and one
`INSERT INTO ... SELECT` connects them.

### 1.5.1 — Source metadata columns

Look at the source table and you'll find two columns the JSON doesn't have:

```sql
source_file  STRING           METADATA FROM 'file.path' VIRTUAL,
source_mtime TIMESTAMP_LTZ(3) METADATA FROM 'file.modification-time' VIRTUAL
```

A connector can provide both the record's payload (the fields in each JSON
object) and metadata about its source, such as the file path and modification
time. `METADATA FROM 'file.path'` reads the path from the connector. Each
connector provides its own metadata keys; a Kafka source can provide topic,
partition, offset, and event timestamp in the same way.

`VIRTUAL` means read-only, and it applies to **the table it's declared on** —
here the source, `telemetry_in`. The value can still be copied into a stored
column in the target table:

```sql
-- source: read-only, supplied by the connector
source_file STRING METADATA FROM 'file.path' VIRTUAL

-- target: an ordinary Iceberg column, stored exactly like `channel`
source_file STRING
```

The `INSERT ... SELECT` copies the value into the target. The source metadata
column stores nothing; it supplies a value while reading. Iceberg stores that
value as one of the table's nine ordinary columns.

### 1.5.2 — Load provenance columns

Five of those nine columns describe the load rather than the telemetry.
`source_file` and `source_mtime` come from the metadata columns above;
`run_id`, `ingest_ts` and `ingest_mode` are stamped by `task flink:job` and are
identical for every row of a single run. Together they make two loads of the
same input distinguishable, and let you ask "how many rows came from this file?"
without counting the input by hand. `ingest_mode` records whether the load ran
in streaming or batch mode; both use the same `SELECT`.

## 1.6 — Verify or restore the load

### 1.6.1 — Check the row count

When `task flink:job` returns, the load is done. Confirm the rows are there:

```bash
task rowcount
```

### 1.6.2 — Reload the tables if needed

`flink:job` is a no-op once the tables are loaded — it compares the committed
row count against the prepared input and skips if they match. To redo the load
again, use `task flink:reload`. The load SQL drops and re-creates the
tables, and Polaris deletes the old data files in the background, which slows
catalog operations while it runs. `flink:reload` asks for confirmation first.

### 1.6.3 — Restore a workshop checkpoint

To skip the ingest, use `task checkpoint:restore -- <name>` to restore a
pre-built warehouse, including the Iceberg files and the Polaris catalog.
Ask your instructor for the checkpoint name, then start the stack and query.

Next: [Step 2 — Querying with Trino and Superset](02-query.md)
