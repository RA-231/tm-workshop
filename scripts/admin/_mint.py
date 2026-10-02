#!/usr/bin/env python3
"""Mint one service-account key per seat. Called by mint-attendee-keys.sh.

    _mint.py <project_id> <seats> <expires_epoch> <prefix> <out.csv>

Each seat is a service account named <prefix>-NN. The provider returns the key
value exactly once, so the CSV this writes is the only copy. The key carries its
own expiry, so there is no teardown step: the cohort dies at the cutoff whether
or not anyone remembers to revoke it.
"""

import csv
import datetime
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("LLM_API_BASE", "https://api.openai.com/v1")
KEY = os.environ["LLM_ADMIN_KEY"]


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = json.loads(e.read().decode(errors="replace")).get("error", {})
        raise SystemExit(f"  API error {e.code}: {detail.get('message', '')[:160]}")


def main():
    project, seats, expires_epoch, prefix, out = (
        sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], pathlib.Path(sys.argv[5]))

    ttl = expires_epoch - int(time.time())
    if ttl <= 0:
        raise SystemExit("  the cutoff has already passed; refusing to mint")

    existing = {s["name"]: s["id"] for s in
                api("GET", f"/organization/projects/{project}/service_accounts?limit=100").get("data", [])}

    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["seat", "user", "alias", "credential_id", "expires", "api_key"])
        for i in range(1, seats + 1):
            name = f"{prefix}-{i:02d}"
            if name in existing:
                print(f"  seat {i:02d} -> {name} exists already, skipping "
                      f"(delete it in the dashboard to re-mint)")
                continue
            d = api("POST", f"/organization/projects/{project}/service_accounts",
                    {"name": name, "expires_in_seconds": ttl})
            k = d["api_key"]
            expires = datetime.datetime.fromtimestamp(
                k["expires_at"], datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            w.writerow([f"{i:02d}", name, d["id"], k["id"], expires, k["value"]])
            print(f"  seat {i:02d} -> {name}")
    print(f"\nWrote {out} (mode 0600). This is the ONLY copy of the keys.")


if __name__ == "__main__":
    main()
