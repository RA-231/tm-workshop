#!/usr/bin/env python3
"""Download the ESA Anomaly Dataset (ESA-ADB) — or a workshop-sized slice of it.

Dataset: https://zenodo.org/records/15237121  (CC BY 3.0 IGO, ~11.6 GB total)
Paper:   https://arxiv.org/abs/2406.17826

Sizes (and where each lands by default):
    small   ~150 MB  data/raw     Mission1 metadata + 7 selected channels,
                                  fetched with HTTP range requests (no
                                  full-archive download!). The channel files
                                  are STORED (uncompressed) inside the mission
                                  zip, so we can read the zip's central
                                  directory remotely and pull individual
                                  members.
    medium  ~3.8 GB  data/medium  all of ESA-Mission1.zip
    full   ~11.6 GB  data/full    all three missions

Only data/raw feeds the workshop pipeline. The larger sizes land in their own
directories so they can sit next to the small set without being ingested by
accident; `task data:prepare -- medium` reads data/medium on purpose.

Mirror support for conference networks: set DATA_MIRROR to a base URL hosting
esa-adb-small.tar.gz / the mission zips and everything is fetched from there
instead of Zenodo.

Usage: fetch_esa_adb.py {small|medium|full} [dest_dir]
"""

import io
import os
import shutil
import struct
import subprocess
import sys
import tarfile
import urllib.request
import zlib
from pathlib import Path

RECORD = "15237121"
ZENODO = f"https://zenodo.org/api/records/{RECORD}/files"
MISSIONS = {
    "ESA-Mission1.zip": 3776246073,
    "ESA-Mission2.zip": 4098539932,
    "ESA-Mission3.zip": 3734403444,
}

# Curated Mission1 subset: three tiny channels, three counter channels, and
# one big "interesting" channel (channel_41 appears throughout the docs).
# Total ≈ 145 MB.
SMALL_CHANNELS = ["61", "62", "63", "9", "10", "11", "41"]
SMALL_METADATA = ["channels.csv", "labels.csv", "anomaly_types.csv", "telecommands.csv"]

MIRROR = os.environ.get("DATA_MIRROR", "").rstrip("/")

# Only data/raw is read by the default `task data:prepare`.
DEST = {"small": Path("data/raw"), "medium": Path("data/medium"), "full": Path("data/full")}


def zenodo_url(filename: str) -> str:
    if MIRROR:
        return f"{MIRROR}/{filename}"
    return f"{ZENODO}/{filename}/content"


def get_range(url: str, start: int, end: int) -> bytes:
    req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
    with urllib.request.urlopen(req) as r:
        return r.read()


def remote_size(url: str, fallback: int) -> int:
    req = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
    try:
        with urllib.request.urlopen(req) as r:
            content_range = r.headers.get("Content-Range", "")
            if "/" in content_range:
                return int(content_range.rsplit("/", 1)[1])
    except Exception:
        pass
    return fallback


def central_directory(url: str, total: int) -> dict:
    """Parse a remote zip's central directory via range requests.

    Returns {member_name: (method, crc, compressed_size, uncompressed_size,
    local_header_offset)}.
    """
    tail = get_range(url, max(0, total - 66000), total - 1)
    i = tail.rfind(b"PK\x05\x06")
    if i < 0:
        raise RuntimeError("end-of-central-directory record not found")
    _, _, _, _, n_total, cd_size, cd_offset, _ = struct.unpack("<IHHHHIIH", tail[i : i + 22])
    if cd_offset == 0xFFFFFFFF or n_total == 0xFFFF:  # zip64
        j = tail.rfind(b"PK\x06\x07")
        _, _, z64_off, _ = struct.unpack("<IIQI", tail[j : j + 20])
        z64 = get_range(url, z64_off, z64_off + 55)
        (*_, cd_size, cd_offset) = struct.unpack("<IQHHIIQQQQ", z64)
    cd = get_range(url, cd_offset, cd_offset + cd_size - 1)

    entries, p = {}, 0
    while p + 46 <= len(cd) and cd[p : p + 4] == b"PK\x01\x02":
        (_, _, _, _, method, _, _, crc, csize, usize, fnlen, eflen, clen, _, _, _, lho) = (
            struct.unpack("<IHHHHHHIIIHHHHHII", cd[p : p + 46])
        )
        name = cd[p + 46 : p + 46 + fnlen].decode("utf-8", "replace")
        entries[name] = (method, crc, csize, usize, lho)
        p += 46 + fnlen + eflen + clen
    return entries


def extract_member(url: str, entries: dict, name: str, out: Path) -> None:
    """Fetch one zip member by range request and write it decompressed.

    Written via a .part file, so a file under the final name is always
    complete — fetch_small relies on that to skip what is already there."""
    method, crc, csize, usize, lho = entries[name]
    header = get_range(url, lho, lho + 29)
    fnlen, eflen = struct.unpack("<HH", header[26:30])
    data_start = lho + 30 + fnlen + eflen
    data = get_range(url, data_start, data_start + csize - 1)

    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.name + ".part")
    if method == 0:  # stored
        part.write_bytes(data)
    elif method == 8:  # deflate
        part.write_bytes(zlib.decompress(data, -15))
    elif method == 9:  # deflate64 — python can't; wrap it and let `unzip` do it
        unzip_deflate64(name, method, crc, csize, usize, data, part)
    else:
        raise RuntimeError(f"unsupported compression method {method} for {name}")
    part.rename(out)
    print(f"  {out}  ({out.stat().st_size:,} bytes)")


def unzip_deflate64(name, method, crc, csize, usize, data, out: Path) -> None:
    """Build a one-member zip around raw compressed bytes and shell out to
    `unzip`, which (unlike Python's zipfile) supports Deflate64."""
    fn = os.path.basename(name).encode()
    lfh = struct.pack("<IHHHHHIIIHH", 0x04034B50, 45, 0, method, 0, 0x21, crc, csize, usize, len(fn), 0) + fn
    cd = (
        struct.pack(
            "<IHHHHHHIIIHHHHHII", 0x02014B50, 45, 45, 0, method, 0, 0x21, crc, csize, usize,
            len(fn), 0, 0, 0, 0, 0, 0,
        )
        + fn
    )
    eocd = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 1, 1, len(cd), len(lfh) + len(data), 0)
    tmp = out.with_suffix(out.suffix + ".wrap.zip")
    tmp.write_bytes(lfh + data + cd + eocd)
    try:
        with out.open("wb") as f:
            subprocess.run(["unzip", "-p", str(tmp)], stdout=f, check=True)
    finally:
        tmp.unlink()


def download_file(url: str, out: Path) -> None:
    """Download to a .part file and rename it on success, so an interrupted
    download never leaves a truncated file under the final name."""
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.name + ".part")
    print(f"downloading {url} -> {out}")
    with urllib.request.urlopen(url) as r, part.open("wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done / total:6.1%}  ({done:,} / {total:,} bytes)", end="", flush=True)
    print()
    part.rename(out)


def fetch_small(dest: Path) -> None:
    members = [f"ESA-Mission1/{m}" for m in SMALL_METADATA]
    members += [f"ESA-Mission1/channels/channel_{c}.zip" for c in SMALL_CHANNELS]
    # Checked before any network access, so a copy from the workshop USB
    # drive needs no download at all.
    missing = [m for m in members if not (dest / m).exists()]
    if not missing:
        print(f"small dataset already present under {dest}/ — nothing to download")
        return

    if MIRROR:
        # A conference mirror hosts the subset as a single tarball.
        tarball = dest / "esa-adb-small.tar.gz"
        download_file(f"{MIRROR}/esa-adb-small.tar.gz", tarball)
        with tarfile.open(tarball) as tf:
            tf.extractall(dest)
        tarball.unlink()
        return

    url = zenodo_url("ESA-Mission1.zip")
    total = remote_size(url, MISSIONS["ESA-Mission1.zip"])
    print("reading remote zip directory of ESA-Mission1.zip ...")
    entries = central_directory(url, total)

    expected = sum(entries[m][2] for m in missing)
    print(f"fetching {len(missing)} members (~{expected / 1e6:,.0f} MB) via range requests")
    for m in missing:
        extract_member(url, entries, m, dest / m)


def fetch_mission(dest: Path, filename: str) -> None:
    # The archive is kept after extracting, so a re-run skips the multi-GB
    # download and the zip can be copied to a DATA_MIRROR.
    archive = dest / filename
    if not archive.exists():
        download_file(zenodo_url(filename), archive)
    if shutil.which("unzip") is None:
        sys.exit("`unzip` is required to extract the mission archives — please install it")
    print(f"extracting {archive} ...")
    subprocess.run(["unzip", "-q", "-o", str(archive), "-d", str(dest)], check=True)


def main() -> None:
    size = sys.argv[1] if len(sys.argv) > 1 else "small"
    if size not in DEST:
        sys.exit(f"unknown size {size!r} — use small, medium, or full")
    dest = Path(sys.argv[2]) if len(sys.argv) > 2 else DEST[size]
    dest.mkdir(parents=True, exist_ok=True)

    if size == "small":
        fetch_small(dest)
    elif size == "medium":
        fetch_mission(dest, "ESA-Mission1.zip")
    else:
        for filename in MISSIONS:
            fetch_mission(dest, filename)

    print(f"\ndone. data is under {dest}/")


if __name__ == "__main__":
    main()
