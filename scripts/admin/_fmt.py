#!/usr/bin/env python3
"""JSON formatting helpers for the admin shell scripts.

Lives in its own file rather than inline `python3 -c` strings: those have to be
quoted twice (shell, then Python) and the escaping breaks in ways that only show
up at run time. Reads the API response on stdin, takes a subcommand.
"""

import json
import pathlib
import re
import sys


def _load():
    try:
        return json.load(sys.stdin)
    except Exception:
        sys.exit("  unparseable response from the API")


def _die_on_error(d, note=""):
    if isinstance(d, dict) and "error" in d:
        e = d["error"]
        print(f"  {e.get('code')} - {str(e.get('message'))[:140]}", file=sys.stderr)
        if note:
            print(f"  {note}", file=sys.stderr)
        sys.exit(1)


def cmd_projects():
    d = _load()
    _die_on_error(d)
    for p in d.get("data", []):
        if p.get("status") == "active":
            print(f"  {p['id']}  {p['name']!r}")


def cmd_project_id(want):
    d = _load()
    _die_on_error(d)
    for p in d.get("data", []):
        if p.get("name") == want and p.get("status") == "active":
            print(p["id"])
            return
    sys.exit(1)


def cmd_project_name(want):
    d = _load()
    _die_on_error(d)
    print(next((p["name"] for p in d.get("data", []) if p["id"] == want), "(unknown)"))


def cmd_models():
    d = _load()
    _die_on_error(d)
    rows = d.get("data", [])
    if not rows:
        print("  (none - the project has no per-model rate limits configured)")
        return
    for r in sorted(rows, key=lambda r: r.get("model", "")):
        rpm = r.get("max_requests_per_1_minute")
        tpm = r.get("max_tokens_per_1_minute")
        print(f"  {r.get('model'):<24} rpm={rpm:<8} tpm={tpm}")


def cmd_check(cfg_path):
    """Cross-check model names pinned in the gateway config against the allowlist."""
    d = _load()
    _die_on_error(d)
    allowed = {r.get("model") for r in d.get("data", [])}
    cfg = pathlib.Path(cfg_path).read_text()
    pinned = set()
    for m in re.finditer(r"^\s*model:\s*(\S+)\s*$", cfg, re.M):
        v = m.group(1).strip().strip("\"'")
        # Wildcards and os.environ/ indirection are the point of the dynamic
        # lineup - they are not names to verify.
        if v.startswith("os.environ/") or v.endswith("/*") or v == "*":
            continue
        pinned.add(v.split("/", 1)[-1])
    if not pinned:
        print("  no literal model names in the config - lineup is fully dynamic. ok")
        return
    missing = 0
    for name in sorted(pinned):
        ok = name in allowed
        missing += 0 if ok else 1
        print(f"  {'ok     ' if ok else 'MISSING'}  {name}")
    if missing:
        sys.exit(f"\n  {missing} model(s) in the config are not available to this project.")


COMMANDS = {
    "projects": cmd_projects,
    "project-id": cmd_project_id,
    "project-name": cmd_project_name,
    "models": cmd_models,
    "check": cmd_check,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(f"usage: _fmt.py [{'|'.join(COMMANDS)}] [arg]")
    COMMANDS[sys.argv[1]](*sys.argv[2:])
