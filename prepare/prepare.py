"""Turn the raw ESA-ADB files into JSON that Flink can read.

Two kinds of output, kept in separate directories so the readings ingest
(which globs a whole directory) never trips over the metadata:

    data/prepared/channels/channel_41.json   one {channel, ts, value} per line
    data/prepared/meta/channels.json          the channel catalog
    data/prepared/meta/labels.json            the anomaly windows
    data/prepared/meta/anomaly_types.json     the anomaly taxonomy

Each channel file is a pickled pandas DataFrame (a DatetimeIndex plus one
float32 column); the metadata are small CSVs. Flink's SQL filesystem connector
reads the resulting newline-delimited JSON.

Env knobs:
    DATA_DIR           directory scanned recursively for channels/*.zip + *.csv
    OUT_DIR            where the JSON is written
    LIMIT_PER_CHANNEL  stop after N samples per channel (0 = no limit)
    CHANNELS           comma-separated channel names to include (default: all)
"""

import csv
import json
import logging
import os
import sys
from pathlib import Path

import pandas as pd

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data/raw"))
OUT_DIR = Path(os.environ.get("OUT_DIR", "/data/prepared"))
LIMIT_PER_CHANNEL = int(os.environ.get("LIMIT_PER_CHANNEL", "0"))
ONLY = {c.strip() for c in os.environ.get("CHANNELS", "").split(",") if c.strip()}

# Metadata CSV -> (output name, {CSV header: json key}). The key mapping gives
# clean, SQL-safe column names (e.g. "Physical Unit" -> physical_unit, and
# "Group"/"Class" renamed to avoid reserved words).
META = {
    "channels.csv": ("channels", {
        "Channel": "channel", "Subsystem": "subsystem", "Physical Unit": "physical_unit",
        "Group": "group_name", "Target": "target", "Categorical": "categorical",
    }),
    "labels.csv": ("labels", {
        "ID": "id", "Channel": "channel", "StartTime": "start_time", "EndTime": "end_time",
    }),
    "anomaly_types.csv": ("anomaly_types", {
        "ID": "id", "Class": "class_name", "Subclass": "subclass", "Category": "category",
        "Dimensionality": "dimensionality", "Locality": "locality", "Length": "length",
    }),
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("prepare")


def convert_channel(path: Path, out: Path) -> int:
    df = pd.read_pickle(path)
    if LIMIT_PER_CHANNEL:
        df = df.iloc[:LIMIT_PER_CHANNEL]
    channel = path.stem
    # datetime64[ms] str() gives "2000-03-01T12:00:00.000"; swap the T for a
    # space so Flink's TO_TIMESTAMP parses it with a plain pattern.
    timestamps = df.index.values.astype("datetime64[ms]").astype(str)
    values = df.iloc[:, 0].values
    with out.open("w") as f:
        for ts, value in zip(timestamps, values):
            f.write(json.dumps({"channel": channel, "ts": ts.replace("T", " "), "value": float(value)}))
            f.write("\n")
    return len(df)


def convert_meta(csv_path: Path, keymap: dict, out: Path) -> int:
    with csv_path.open(newline="") as src, out.open("w") as dst:
        n = 0
        for row in csv.DictReader(src):
            dst.write(json.dumps({v: row.get(k, "") for k, v in keymap.items()}))
            dst.write("\n")
            n += 1
    return n


def main() -> int:
    files = sorted(DATA_DIR.rglob("channels/*.zip"))
    if ONLY:
        files = [p for p in files if p.stem in ONLY]
    if not files:
        log.error("no channel files under %s — run `task data:download` first", DATA_DIR)
        return 1

    # 1. Telemetry channels -> prepared/channels/
    chan_out = OUT_DIR / "channels"
    chan_out.mkdir(parents=True, exist_ok=True)
    total = 0
    for path in files:
        n = convert_channel(path, chan_out / f"{path.stem}.json")
        total += n
        log.info("channel %-16s -> %d rows", path.stem, n)
    log.info("prepared %d channels, %d rows total", len(files), total)

    # 2. Metadata CSVs -> prepared/meta/
    meta_out = OUT_DIR / "meta"
    meta_out.mkdir(parents=True, exist_ok=True)
    for filename, (name, keymap) in META.items():
        src = next(DATA_DIR.rglob(filename), None)
        if src is None:
            log.warning("metadata file %s not found — skipping", filename)
            continue
        n = convert_meta(src, keymap, meta_out / f"{name}.json")
        log.info("metadata %-16s -> %d rows", name, n)

    return 0


if __name__ == "__main__":
    sys.exit(main())
