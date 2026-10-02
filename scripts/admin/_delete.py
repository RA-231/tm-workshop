#!/usr/bin/env python3
"""Delete the service accounts for a seat prefix. Called by delete-attendee-keys.sh.

    _delete.py <project_id> <prefix> [--yes]

Deleting a service account revokes its key immediately and permanently. This
exists for re-minting, not for teardown: the mint script skips seat names that
already exist, so a second mint over a previous one silently produces nothing.
Ordinary end-of-workshop cleanup needs no action -- every key carries its own
expiry.
"""

import json
import os
import sys
import urllib.error
import urllib.request

API = os.environ.get("LLM_API_BASE", "https://api.openai.com/v1")
KEY = os.environ["LLM_ADMIN_KEY"]


def api(method, path):
    req = urllib.request.Request(
        f"{API}{path}", method=method,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode(errors="replace"))


def main():
    project, prefix = sys.argv[1], sys.argv[2]
    assume_yes = "--yes" in sys.argv[3:]

    _, listing = api("GET", f"/organization/projects/{project}/service_accounts?limit=100")
    if "error" in listing:
        raise SystemExit(f"  {listing['error'].get('message', '')[:160]}")

    targets = [s for s in listing.get("data", []) if s["name"].startswith(prefix)]
    if not targets:
        print(f"  nothing to delete: no service accounts start with {prefix!r}")
        return 0

    print(f"  {len(targets)} service account(s) match {prefix!r}:")
    for s in targets[:5]:
        print(f"    {s['name']}")
    if len(targets) > 5:
        print(f"    ... and {len(targets) - 5} more")

    if not assume_yes:
        if not sys.stdin.isatty():
            raise SystemExit("  refusing: not a terminal and --yes not given")
        print()
        print("  This revokes their keys immediately and permanently. Any cards")
        print("  already handed out or printed stop working.")
        if input(f"  Type the prefix ({prefix}) to confirm: ").strip() != prefix:
            raise SystemExit("  aborted")

    failed = 0
    for s in targets:
        code, body = api("DELETE", f"/organization/projects/{project}/service_accounts/{s['id']}")
        ok = code == 200 and body.get("deleted")
        failed += 0 if ok else 1
        print(f"  {'deleted' if ok else 'FAILED '} {s['name']}"
              f"{'' if ok else '  ' + str(body.get('error', {}).get('message', ''))[:80]}")

    # The listing lags behind deletes by a few seconds, so do not re-list and
    # claim success from it -- the per-delete responses above are the evidence.
    print(f"\n  {len(targets) - failed} deleted, {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
