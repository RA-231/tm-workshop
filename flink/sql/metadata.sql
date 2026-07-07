-- Load the ESA metadata tables (the channel catalog, the anomaly windows, and
-- the anomaly taxonomy) into Iceberg alongside the readings.
-- Submitted with: task flink:job (after ingest.sql)
--
-- These are small, static dimension tables. We DROP + recreate them so the
-- load is idempotent (re-running never appends duplicates). Timestamps in
-- labels are kept as strings here — they're ISO-8601 with a 'Z', which the
-- Trino views parse with from_iso8601_timestamp() when overlaying anomalies
-- onto readings.
SET 'execution.checkpointing.interval' = '5s';
SET 'table.dml-sync' = 'true';

CREATE TABLE channels_in (
    channel STRING, subsystem STRING, physical_unit STRING,
    group_name STRING, target STRING, categorical STRING
) WITH ('connector'='filesystem', 'path'='file:///data/prepared/meta/channels.json', 'format'='json');

CREATE TABLE labels_in (
    id STRING, channel STRING, start_time STRING, end_time STRING
) WITH ('connector'='filesystem', 'path'='file:///data/prepared/meta/labels.json', 'format'='json');

CREATE TABLE anomaly_types_in (
    id STRING, class_name STRING, subclass STRING, category STRING,
    dimensionality STRING, locality STRING, length STRING
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

CREATE DATABASE IF NOT EXISTS polaris.telemetry;

DROP TABLE IF EXISTS polaris.telemetry.channels;
CREATE TABLE polaris.telemetry.channels (
    channel STRING, subsystem STRING, physical_unit STRING,
    group_name STRING, target STRING, categorical STRING
) WITH ('format-version' = '2');
INSERT INTO polaris.telemetry.channels SELECT * FROM channels_in;

DROP TABLE IF EXISTS polaris.telemetry.labels;
CREATE TABLE polaris.telemetry.labels (
    id STRING, channel STRING, start_time STRING, end_time STRING
) WITH ('format-version' = '2');
INSERT INTO polaris.telemetry.labels SELECT * FROM labels_in;

DROP TABLE IF EXISTS polaris.telemetry.anomaly_types;
CREATE TABLE polaris.telemetry.anomaly_types (
    id STRING, class_name STRING, subclass STRING, category STRING,
    dimensionality STRING, locality STRING, length STRING
) WITH ('format-version' = '2');
INSERT INTO polaris.telemetry.anomaly_types SELECT * FROM anomaly_types_in;
