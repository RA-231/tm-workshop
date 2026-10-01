-- The entire ingest pipeline: prepared JSON files -> Iceberg table.
-- Submitted with: task flink:job
--
-- Flink reads every JSON file under /data/prepared and streams the rows into
-- Iceberg. The Iceberg sink commits a new snapshot at each checkpoint, so the
-- table grows in visible increments while the job runs. The file source is
-- bounded, so once every file is read the job finishes on its own — the exact
-- same SQL against a live feed would simply never end.
SET 'execution.checkpointing.interval' = '5s';
-- block until the load actually finishes, so `task flink:job` returns when done
SET 'table.dml-sync' = 'true';

-- 1. The prepared telemetry, viewed as a table. Nothing is stored here — this
--    just tells Flink how to read the newline-delimited JSON the prepare step
--    wrote (one channel/ts/value object per line).
--    The last two columns are *metadata columns*: their values come from the
--    connector's own knowledge of where each record came from, not from
--    parsing the JSON. VIRTUAL marks them read-only — they are excluded from
--    this table's write side, which is moot here since we only ever read it.
--    Nothing is stored by this declaration — see step 3 for where they land.
CREATE TABLE telemetry_in (
    channel STRING,
    ts      STRING,
    `value` DOUBLE,
    source_file  STRING           METADATA FROM 'file.path' VIRTUAL,
    source_mtime TIMESTAMP_LTZ(3) METADATA FROM 'file.modification-time' VIRTUAL
) WITH (
    'connector' = 'filesystem',
    'path' = 'file:///data/prepared/channels',
    'format' = 'json'
);

-- 2. The Iceberg catalog, served by Polaris over the REST catalog protocol.
--    Trino will connect to the exact same catalog in Step 2. Data files are
--    written straight to Garage (S3) with a static key.
CREATE CATALOG polaris WITH (
    'type' = 'iceberg',
    'catalog-type' = 'rest',
    'uri' = 'http://polaris:8181/api/catalog',
    'warehouse' = 'workshop',
    'credential' = 'root:s3cr3t',
    'scope' = 'PRINCIPAL_ROLE:ALL',
    'io-impl' = 'org.apache.iceberg.aws.s3.S3FileIO',
    's3.endpoint' = 'http://garage:3900',
    's3.path-style-access' = 'true',
    's3.access-key-id' = 'GK31c2f218a2e44f485b94239e',
    's3.secret-access-key' = '7d37d093435a41f2aab8f13c19ba067d9776c90215f56614adad6ece597dbb34',
    'client.region' = 'garage'
);

CREATE DATABASE IF NOT EXISTS polaris.esa_adb;

-- 3. The destination table. Partitioned by month (a 'yyyy-MM' string): the
--    telemetry spans years, so monthly partitions let engines prune big chunks
--    of the table when you filter on time, without creating thousands of tiny
--    daily partitions. The smaller Parquet row group keeps the streaming
--    writer's memory bounded when many partitions are open at once.
-- `task flink:job` drops the tables first, metadata-only, via the catalog's
-- REST API (scripts/drop-tables.sh) — so re-running the load never appends
-- dupes. Flink's own DROP TABLE always demands a purge, which makes Polaris
-- delete every old data file in the background and starve its S3 pool while
-- this very load is trying to commit. A plain CREATE here is deliberate: if
-- the table somehow still exists, fail loudly rather than silently append.
--    The five provenance columns are ordinary Iceberg columns — no METADATA,
--    no VIRTUAL. They record where each row came from and which load wrote it.
CREATE TABLE polaris.esa_adb.readings (
    channel      STRING,
    ts           TIMESTAMP(3),
    ts_month     STRING,
    `value`      DOUBLE,
    source_file  STRING,
    source_mtime TIMESTAMP(3),
    ingest_ts    TIMESTAMP(3),
    run_id       STRING,
    ingest_mode  STRING
) PARTITIONED BY (ts_month) WITH (
    'format-version' = '2',
    'write.parquet.row-group-size-bytes' = '16777216',
    -- Iceberg truncates string bounds to 16 chars by default, which for these
    -- paths is '/data/prepared/c' for every file — identical, so nothing can
    -- prune. Keep the full value so WHERE source_file = '...' skips files.
    'write.metadata.metrics.column.source_file' = 'full'
);

-- 4. Connect them. Reads all the JSON, writes Iceberg, commits per checkpoint.
--    ts_month is just the first 7 characters of the timestamp string, e.g.
--    "2000-01-01 12:00:00.000" -> "2000-01".
--    run_id / ingest_ts / ingest_mode are rendered in by `task flink:job`
--    before this file reaches the SQL client, so every row of one load shares
--    one value. CURRENT_TIMESTAMP would be evaluated per record instead.
INSERT INTO polaris.esa_adb.readings
SELECT
    channel,
    TO_TIMESTAMP(ts, 'yyyy-MM-dd HH:mm:ss.SSS') AS ts,
    SUBSTRING(ts FROM 1 FOR 7) AS ts_month,
    `value`,
    source_file,
    CAST(source_mtime AS TIMESTAMP(3)) AS source_mtime,
    CAST('${INGEST_TS}' AS TIMESTAMP(3)) AS ingest_ts,
    '${RUN_ID}' AS run_id,
    '${INGEST_MODE}' AS ingest_mode
FROM telemetry_in;
