-- Views over the telemetry warehouse, created in Trino. Superset and the MCP
-- server both query through Trino, so Trino views serve every consumer.
-- Run with: task trino:views
--
-- These demonstrate the two everyday reasons to make a view: enrich a fact
-- table with dimension metadata, and express a non-trivial join once so
-- everyone reuses it.

-- A single channel, as its own view — the simplest possible "view of a
-- channel". Swap the channel name to make others.
CREATE OR REPLACE VIEW iceberg.esa_adb.channel_41 AS
SELECT ts, ts_month, value
FROM iceberg.esa_adb.readings
WHERE channel = 'channel_41';

-- Every reading, enriched with its channel's catalog metadata (subsystem,
-- physical unit, ...). A plain fact-⋈-dimension join, hidden behind a name.
CREATE OR REPLACE VIEW iceberg.esa_adb.readings_enriched AS
SELECT r.channel, r.ts, r.ts_month, r.value,
       c.subsystem, c.physical_unit, c.group_name, c.target, c.categorical
FROM iceberg.esa_adb.readings r
LEFT JOIN iceberg.esa_adb.channels c ON r.channel = c.channel;

-- The anomaly ground truth: each labeled window with its type. The label times
-- are ISO-8601 UTC strings ("2004-12-01T20:42:15.429Z"); we parse them into
-- plain timestamp(6) values (dropping the 'T'/'Z') so they line up directly
-- with readings.ts, which Iceberg also stores as an un-zoned timestamp.
CREATE OR REPLACE VIEW iceberg.esa_adb.anomalies AS
SELECT l.id, l.channel,
       CAST(replace(replace(l.start_time, 'T', ' '), 'Z', '') AS timestamp(6)) AS start_time,
       CAST(replace(replace(l.end_time,   'T', ' '), 'Z', '') AS timestamp(6)) AS end_time,
       t.class_name, t.subclass, t.category, t.dimensionality, t.locality, t.length
FROM iceberg.esa_adb.labels l
LEFT JOIN iceberg.esa_adb.anomaly_types t ON l.id = t.id;

-- The payoff view: every reading tagged with whether it falls inside a labeled
-- anomaly window for its channel, and which one. This is what Superset colors
-- and what Claude investigates in Step 4.
CREATE OR REPLACE VIEW iceberg.esa_adb.labeled_readings AS
SELECT r.channel, r.ts, r.ts_month, r.value,
       a.id AS anomaly_id, a.category AS anomaly_category,
       (a.id IS NOT NULL) AS is_anomaly
FROM iceberg.esa_adb.readings r
LEFT JOIN iceberg.esa_adb.anomalies a
  ON r.channel = a.channel
 AND r.ts BETWEEN a.start_time AND a.end_time;
