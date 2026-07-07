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
CREATE TABLE telemetry_in (
    channel STRING,
    ts      STRING,
    `value` DOUBLE
) WITH (
    'connector' = 'filesystem',
    'path' = 'file:///data/prepared',
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

CREATE DATABASE IF NOT EXISTS polaris.telemetry;

-- 3. The destination table. Partitioned by month (a 'yyyy-MM' string): the
--    telemetry spans years, so monthly partitions let engines prune big chunks
--    of the table when you filter on time, without creating thousands of tiny
--    daily partitions. The smaller Parquet row group keeps the streaming
--    writer's memory bounded when many partitions are open at once.
CREATE TABLE IF NOT EXISTS polaris.telemetry.readings (
    channel  STRING,
    ts       TIMESTAMP(3),
    ts_month STRING,
    `value`  DOUBLE
) PARTITIONED BY (ts_month) WITH (
    'format-version' = '2',
    'write.parquet.row-group-size-bytes' = '16777216'
);

-- 4. Connect them. Reads all the JSON, writes Iceberg, commits per checkpoint.
--    ts_month is just the first 7 characters of the timestamp string, e.g.
--    "2000-01-01 12:00:00.000" -> "2000-01".
INSERT INTO polaris.telemetry.readings
SELECT
    channel,
    TO_TIMESTAMP(ts, 'yyyy-MM-dd HH:mm:ss.SSS') AS ts,
    SUBSTRING(ts FROM 1 FOR 7) AS ts_month,
    `value`
FROM telemetry_in;
