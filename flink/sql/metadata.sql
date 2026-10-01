-- Load the ESA metadata tables (the channel catalog, the anomaly windows, and
-- the anomaly taxonomy) into Iceberg alongside the readings.
-- Submitted with: task flink:job (after ingest.sql)
--
-- These are small, static dimension tables. `task flink:job` drops them
-- metadata-only through the catalog REST API first (scripts/drop-tables.sh),
-- so re-running the load is idempotent. Timestamps in
-- labels are kept as strings here — they're ISO-8601 with a 'Z', which the
-- Trino views parse with from_iso8601_timestamp() when overlaying anomalies
-- onto readings.
SET 'execution.checkpointing.interval' = '5s';
SET 'table.dml-sync' = 'true';

CREATE TABLE channels_in (
    channel STRING, subsystem STRING, physical_unit STRING,
    group_name STRING, target STRING, categorical STRING,
    source_file  STRING           METADATA FROM 'file.path' VIRTUAL,
    source_mtime TIMESTAMP_LTZ(3) METADATA FROM 'file.modification-time' VIRTUAL
) WITH ('connector'='filesystem', 'path'='file:///data/prepared/meta/channels.json', 'format'='json');

CREATE TABLE labels_in (
    id STRING, channel STRING, start_time STRING, end_time STRING,
    source_file  STRING           METADATA FROM 'file.path' VIRTUAL,
    source_mtime TIMESTAMP_LTZ(3) METADATA FROM 'file.modification-time' VIRTUAL
) WITH ('connector'='filesystem', 'path'='file:///data/prepared/meta/labels.json', 'format'='json');

CREATE TABLE anomaly_types_in (
    id STRING, class_name STRING, subclass STRING, category STRING,
    dimensionality STRING, locality STRING, length STRING,
    source_file  STRING           METADATA FROM 'file.path' VIRTUAL,
    source_mtime TIMESTAMP_LTZ(3) METADATA FROM 'file.modification-time' VIRTUAL
) WITH ('connector'='filesystem', 'path'='file:///data/prepared/meta/anomaly_types.json', 'format'='json');

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

CREATE TABLE polaris.esa_adb.channels (
    channel STRING, subsystem STRING, physical_unit STRING,
    group_name STRING, target STRING, categorical STRING,
    source_file STRING, source_mtime TIMESTAMP(3),
    ingest_ts TIMESTAMP(3), run_id STRING, ingest_mode STRING
) WITH ('format-version' = '2');
INSERT INTO polaris.esa_adb.channels SELECT
    channel, subsystem, physical_unit, group_name, target, categorical,
    source_file,
    CAST(source_mtime AS TIMESTAMP(3)) AS source_mtime,
    CAST('${INGEST_TS}' AS TIMESTAMP(3)) AS ingest_ts,
    '${RUN_ID}' AS run_id,
    '${INGEST_MODE}' AS ingest_mode
FROM channels_in;

CREATE TABLE polaris.esa_adb.labels (
    id STRING, channel STRING, start_time STRING, end_time STRING,
    source_file STRING, source_mtime TIMESTAMP(3),
    ingest_ts TIMESTAMP(3), run_id STRING, ingest_mode STRING
) WITH ('format-version' = '2');
INSERT INTO polaris.esa_adb.labels SELECT
    id, channel, start_time, end_time,
    source_file,
    CAST(source_mtime AS TIMESTAMP(3)) AS source_mtime,
    CAST('${INGEST_TS}' AS TIMESTAMP(3)) AS ingest_ts,
    '${RUN_ID}' AS run_id,
    '${INGEST_MODE}' AS ingest_mode
FROM labels_in;

CREATE TABLE polaris.esa_adb.anomaly_types (
    id STRING, class_name STRING, subclass STRING, category STRING,
    dimensionality STRING, locality STRING, length STRING,
    source_file STRING, source_mtime TIMESTAMP(3),
    ingest_ts TIMESTAMP(3), run_id STRING, ingest_mode STRING
) WITH ('format-version' = '2');
INSERT INTO polaris.esa_adb.anomaly_types SELECT
    id, class_name, subclass, category, dimensionality, locality, length,
    source_file,
    CAST(source_mtime AS TIMESTAMP(3)) AS source_mtime,
    CAST('${INGEST_TS}' AS TIMESTAMP(3)) AS ingest_ts,
    '${RUN_ID}' AS run_id,
    '${INGEST_MODE}' AS ingest_mode
FROM anomaly_types_in;
