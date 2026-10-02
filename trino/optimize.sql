-- Compact the warehouse's small files. Run with: task trino:optimize
--
-- The streaming ingest commits a snapshot at every checkpoint, so each
-- partition ends up split across many small files — one per checkpoint that
-- touched it. (Check for yourself: SELECT count(*), avg(file_size_in_bytes)
-- FROM iceberg.esa_adb."readings$files".) Lots of small files means more
-- splits, more open-file overhead, and fatter manifests for every reader.
--
-- `EXECUTE optimize` rewrites files below file_size_threshold into fewer,
-- larger ones. It's a normal Iceberg commit: it adds a new snapshot and leaves
-- the pre-compaction files in place as non-current data, so time travel and the
-- readings$snapshots history still work. It does NOT purge anything, so it
-- won't touch the Polaris catalog's file-cleanup path. To reclaim the old
-- files' space later, a separate `EXECUTE expire_snapshots` would be the tool.
--
-- Optional and idempotent: re-running once the files are already large is a
-- cheap no-op.

ALTER TABLE iceberg.esa_adb.readings      EXECUTE optimize(file_size_threshold => '128MB');
ALTER TABLE iceberg.esa_adb.channels      EXECUTE optimize(file_size_threshold => '128MB');
ALTER TABLE iceberg.esa_adb.labels        EXECUTE optimize(file_size_threshold => '128MB');
ALTER TABLE iceberg.esa_adb.anomaly_types EXECUTE optimize(file_size_threshold => '128MB');
