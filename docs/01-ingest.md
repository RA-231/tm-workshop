# Step 1 — Ingesting Data into Iceberg with Flink

Goal: raw ESA telemetry files → Flink → an Iceberg table you can query. Along
the way: what a table format actually *is*, and why the catalog matters.

## What Iceberg actually is

Strip away the buzzwords and Iceberg is a **spec for keeping track of files**.
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

Reading a table means: find the current `metadata.json`, follow it to a
snapshot, follow the snapshot to manifests, and read only the data files that
survive your filters. **Writing** means: write new Parquet files, then write
new metadata that includes them, then atomically swap the "current metadata"
pointer. Readers never see a half-finished write — that pointer swap is the
commit.

Two consequences worth pausing on:

1. **Snapshots are free history.** Old metadata still describes the old file
   set — that's time travel and rollback.
2. **Somebody has to own the pointer.** The atomic swap needs a coordinator
   that all writers and readers agree on. That's the catalog.

## The role of Apache Polaris

Polaris is an implementation of the **Iceberg REST catalog** protocol. It's
the small-but-critical service that maps `esa_adb.readings` → "current
metadata file is `v3.metadata.json`" and performs the atomic swap on commit.

Because Flink (writer) and Trino (reader, Step 2) both speak the REST catalog
protocol to the *same* Polaris, they agree on what the table is at every
moment — different engines, zero coordination between them. That handoff is
the whole reason lakehouse architectures work.

> In production, Polaris also handles access control and can vend scoped,
> temporary storage credentials to each engine. We skip that: the warehouse
> lives in **Garage**, a lightweight S3-compatible object store, and every
> engine uses the same static key. One less moving part between you and the
> data — and it means the warehouse is real S3 object storage, exactly like a
> cloud deployment, just running in a container on your laptop.

## Why Flink?

Flink is a stream *and* batch processing engine. Our job reads every prepared
telemetry file and *streams* the rows into Iceberg: the sink commits a new
snapshot at each checkpoint, so the table grows in visible increments while the
job runs. The file source is bounded — once every file has been read the job
finishes on its own. The exact same SQL pointed at a live feed instead of a
directory would simply never end. That's the point: batch is just streaming
over a finite source.

The ESA channels ship as pickled pandas DataFrames, which Flink can't read
directly, so there's a one-time prep step (`task data:prepare`) that converts
each channel to newline-delimited JSON under `data/prepared/channels/`. Flink's
filesystem connector reads that directory.

The same prep step also converts the dataset's **metadata** — the channel
catalog, the labeled anomaly windows, and the anomaly taxonomy — into
`data/prepared/meta/`. `task flink:job` loads those as three small dimension
tables (`channels`, `labels`, `anomaly_types`) alongside `readings`. They're
what make Step 2's views and Step 4's anomaly investigation possible.

## Do it

```bash
task up:ingest        # setup garage, polaris, flink — init S3 bucket
task data:prepare     # pickled channels -> JSON under data/prepared/
task catalog:create   # create the 'workshop' catalog in Polaris
task flink:job        # run the ingest job (Flink SQL) — blocks until loaded
```

While `flink:job` runs:

- **Flink UI** [http://localhost:8081](http://localhost:8081) — watch the job
  read the files and write to the sink, one snapshot per checkpoint.
- **Look at the objects.** The metadata and Parquet files land in Garage:

  ```bash
  docker compose exec garage /garage bucket info warehouse
  ```

  This is the whole trick, in plain sight.

The ingest job is ~40 lines of Flink SQL — open
[`flink/sql/ingest.sql`](../flink/sql/ingest.sql). One statement defines the
prepared JSON as a table, one defines the Iceberg catalog via Polaris, and one
`INSERT INTO ... SELECT` connects them.

### Side-note: metadata columns

Look at the source table and you'll find two columns the JSON doesn't have:

```sql
source_file  STRING           METADATA FROM 'file.path' VIRTUAL,
source_mtime TIMESTAMP_LTZ(3) METADATA FROM 'file.modification-time' VIRTUAL
```

Every record a connector reads carries two kinds of information. There's the
**payload** — the fields inside each JSON object: `channel`, `ts`, `value`. And
there's **what the connector knows about where the record came from**: which
file it was read from, how big that file is, when it was last modified. The
second kind normally gets thrown away.

`METADATA FROM 'file.path'` says: don't parse this out of the record body, ask
the connector for it. Each connector publishes its own keys — a Kafka source
offers topic, partition, offset, event timestamp and headers the same way, so
the idea generalizes well beyond files.

`VIRTUAL` means read-only, and it applies to **the table it's declared on** —
here `telemetry_in`, the source. It says: if you ever used `telemetry_in` as a
sink, you wouldn't supply this column. Since we only ever read from it, that's
close to a formality. The alternative, a *persisted* metadata column, declares
that the connector can write the key back — sensible for a Kafka record
timestamp, impossible for a file's own path.

**`VIRTUAL` has nothing to do with the Iceberg side.** The natural misreading
is that it stops the value reaching Parquet, which is backwards — getting it
into Parquet is the entire point. The two declarations sit at opposite ends of
the job:

```sql
-- source: read-only, from the connector
CREATE TABLE telemetry_in (
    channel STRING, ts STRING, `value` DOUBLE,
    source_file STRING METADATA FROM 'file.path' VIRTUAL
) WITH ('connector' = 'filesystem', ...);

-- target: an ordinary Iceberg column, stored exactly like `channel`
CREATE TABLE polaris.esa_adb.readings (
    channel STRING, ts TIMESTAMP(3), ts_month STRING, `value` DOUBLE,
    source_file STRING
) PARTITIONED BY (ts_month) WITH (...);
```

The `INSERT ... SELECT` is what carries the value across. The metadata column
itself stores nothing — it exists only while reading. Iceberg has no notion of
a metadata column; it just sees nine normal columns.

Which is the point: where a row came from is information the runtime already
has and currently discards. The metadata column is just the declaration that
says keep it. Step 2 picks up what that costs to store — less than you'd
think.

### What the load records about itself

Four of the nine columns describe the load rather than the telemetry:
`source_file` and `source_mtime` come from the metadata columns above, while
`run_id`, `ingest_ts` and `ingest_mode` are stamped by `task flink:job` and
are identical for every row of a single run. That makes two loads of the same
input distinguishable, and lets you ask "how many rows came from this file?"
without counting the input by hand.

`ingest_mode` records whether the load ran in streaming or batch execution
mode. The transform — the `SELECT` — is identical either way; only the
orchestration differs. Recording the mode keeps that claim honest.

## Checkpoint

When `task flink:job` returns, the load is done. Confirm the rows are there:

```bash
task rowcount
```

`flink:job` is a no-op once the tables are loaded — it compares the committed
row count against the prepared input and skips if they match. To redo the load
deliberately, use `task flink:reload`. The load SQL drops and re-creates the
tables, and Polaris deletes the old data files in the background, which slows
every catalog operation while it runs; `flink:reload` prompts first so that is
never a surprise.

Stuck, or don't want to wait for the full ingest?
`task checkpoint:restore -- <name>` drops in a pre-built warehouse — both the
Iceberg files and the Polaris catalog that points at them — so you can start
the stack and query right away, no re-ingest needed. Ask your instructor for
the checkpoint name.

Next: [Step 2 — Querying with Trino and Superset](02-query.md)
