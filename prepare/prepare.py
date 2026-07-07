"""Turn the raw ESA-ADB channel files into something Flink can read.

Each channel in the dataset is a pickled pandas DataFrame (a DatetimeIndex
plus one float32 column) inside a zip:

    data/raw/ESA-Mission1/channels/channel_41.zip

Flink's SQL filesystem connector can't read pickles, so this step converts
each channel to newline-delimited JSON, one file per channel:

    data/prepared/channel_41.json      {"channel","ts","value"} per line

That directory is what the Flink ingest job reads (see flink/sql/ingest.sql).

Env knobs:
    DATA_DIR           directory scanned recursively for channels/*.zip
    OUT_DIR            where the .json files are written
    LIMIT_PER_CHANNEL  stop after N samples per channel (0 = no limit)
    CHANNELS           comma-separated channel names to include (default: all)
"""

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("prepare")


def convert(path: Path, out: Path) -> int:
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


def main() -> int:
    files = sorted(DATA_DIR.rglob("channels/*.zip"))
    if ONLY:
        files = [p for p in files if p.stem in ONLY]
    if not files:
        log.error("no channel files under %s — run `task data:download` first", DATA_DIR)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    for path in files:
        n = convert(path, OUT_DIR / f"{path.stem}.json")
        total += n
        log.info("%-16s -> %d rows", path.stem, n)
    log.info("prepared %d channels, %d rows total, into %s", len(files), total, OUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
