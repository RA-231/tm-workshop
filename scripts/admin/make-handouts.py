#!/usr/bin/env python3
"""Turn attendee-keys.csv into per-seat handouts.

Produces, for each seat: a paste-ready .env snippet for email or DM, a QR PNG
for printed cards, and a printable contact sheet of all the cards.

    ./make-handouts.py                         # attendee-keys.csv -> handouts/
    ./make-handouts.py --csv other.csv --out /tmp/cards
    ./make-handouts.py --no-qr                 # text snippets only

Everything is generated locally and written 0600 inside a 0700 directory.
Nothing is uploaded: a QR of a live credential IS the credential, so these
files are exactly as sensitive as the CSV they come from.
"""

import argparse
import base64
import csv
import re
import html
import os
import shutil
import subprocess
import sys
from pathlib import Path

SNIPPET = """\
# Workshop credential -- seat {seat}. Expires {expires}.
# Paste these lines into the .env file in the workshop repo.
LLM_API_KEY={key}
LITELLM_MASTER_KEY=sk-workshop
"""

STYLE = """\
body{font:13px/1.4 -apple-system,system-ui,sans-serif;margin:0;padding:12px;background:#fff;color:#111}
h1{font-size:15px;margin:0 0 10px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.card{border:1px solid #bbb;border-radius:6px;padding:10px;text-align:center;page-break-inside:avoid}
.seat{font-size:20px;font-weight:700;margin-bottom:4px}
.exp{font-size:10px;color:#555;margin-top:4px}
img{width:100%;max-width:190px;image-rendering:pixelated}
.warn{font-size:11px;color:#900;margin:6px 0 12px}
@media print{.warn{color:#000}}
"""

PHONE_STYLE = """\
:root{color-scheme:light dark}
body{font:16px/1.5 -apple-system,system-ui,sans-serif;margin:0;padding:16px}
h1{font-size:17px;margin:0 0 2px}
.sub{opacity:.7;font-size:13px;margin:0 0 14px}
.warn{font-size:13px;color:#b91c1c;margin:0 0 14px}
#find{font:inherit;padding:10px 12px;width:100%;box-sizing:border-box;
      border:1px solid #999;border-radius:10px;margin-bottom:14px}
.card{border:1px solid #999;border-radius:12px;padding:14px;margin-bottom:14px;
      text-align:center}
.seat{font-size:26px;font-weight:700}
.exp{font-size:12px;opacity:.7;margin-top:6px}
img{width:100%;max-width:340px;image-rendering:pixelated;background:#fff;
    padding:8px;border-radius:8px}
.done{opacity:.35}
.mark{font:inherit;margin-top:8px;padding:8px 14px;border-radius:8px;
      border:1px solid currentColor;background:transparent;color:inherit}
"""

PHONE_SCRIPT = """\
const KEY='tmws-handed-out';
const state=new Set(JSON.parse(localStorage.getItem(KEY)||'[]'));
function save(){localStorage.setItem(KEY,JSON.stringify([...state]))}
function paint(c){const s=c.dataset.seat;c.classList.toggle('done',state.has(s));
  c.querySelector('.mark').textContent=state.has(s)?'handed out - undo':'mark handed out'}
document.querySelectorAll('.card').forEach(c=>{paint(c);
  c.querySelector('.mark').onclick=()=>{const s=c.dataset.seat;
    state.has(s)?state.delete(s):state.add(s);save();paint(c)}});
document.getElementById('find').oninput=e=>{const q=e.target.value.trim();
  document.querySelectorAll('.card').forEach(c=>{
    c.style.display=(!q||c.dataset.seat.includes(q))?'':'none'})};
"""

REQUIRED_COLUMNS = {"seat", "expires", "api_key"}

# What a card is allowed to contain. Anything else is a bug upstream or
# tampering, and either way must not reach 50 printed QR codes. The prefix is
# deliberately narrow: an admin key (sk-admin-...) administers the whole
# organisation and must never be printable onto a card, so matching a bare
# "sk-" is not good enough.
SEAT_RE = re.compile(r"^[0-9]{1,3}$")
KEY_RE = re.compile(r"^sk-(svcacct|proj)-[A-Za-z0-9_-]{20,400}$")
EXPIRES_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.+-]{5,20}(Z|[0-9]{2}:[0-9]{2})?$")
# The payload is pasted into .env, which scripts/llm-check.sh parses. A newline would inject an extra assignment; $() or backticks
# would execute. None of these can appear in any field.
FORBIDDEN = re.compile(r"[\r\n`$;|&<>\\]")
EXPECTED_KEYS = ("LLM_API_KEY", "LITELLM_MASTER_KEY")


class CardError(Exception):
    """A row that must not become a QR code."""


def validate_row(row: dict) -> None:
    seat, key, expires = row["seat"], row["api_key"], row["expires"]
    for name, value in (("seat", seat), ("api_key", key), ("expires", expires)):
        if FORBIDDEN.search(value or ""):
            raise CardError(f"{name} contains a forbidden character: {value!r}")
    if not SEAT_RE.match(seat or ""):
        raise CardError(f"seat is not a plain number: {seat!r}")
    if not KEY_RE.match(key or ""):
        raise CardError(f"api_key is not a workshop API key: {key[:12]!r}...")
    if expires and not EXPIRES_RE.match(expires):
        raise CardError(f"expires is not an ISO timestamp: {expires!r}")


def audit_payload(payload: str, row: dict) -> None:
    """Re-read the finished snippet and prove it is exactly what we intended."""
    lines = [ln for ln in payload.splitlines() if ln and not ln.startswith("#")]
    if len(lines) != len(EXPECTED_KEYS):
        raise CardError(f"snippet has {len(lines)} assignments, expected {len(EXPECTED_KEYS)}")
    got = {}
    for line in lines:
        if "=" not in line:
            raise CardError(f"unparseable line: {line!r}")
        k, _, v = line.partition("=")
        if k not in EXPECTED_KEYS:
            raise CardError(f"unexpected variable in snippet: {k!r}")
        got[k] = v
    if got["LLM_API_KEY"] != row["api_key"]:
        raise CardError("token in snippet does not match the CSV")


def verify_qr(path: Path, payload: str) -> bool:
    """Decode the generated QR and compare byte-for-byte with the payload.

    Without this, 'the QR contains only the credential' is an assertion about
    code. With it, it is a measurement of the artifact actually being handed out.
    Returns False when zbarimg is unavailable.
    """
    if not shutil.which("zbarimg"):
        return False
    out = subprocess.run(["zbarimg", "--quiet", "--raw", "-Sbinary", str(path)],
                         capture_output=True)
    decoded = out.stdout.decode(errors="replace")
    if decoded.rstrip("\n") != payload.rstrip("\n"):
        raise CardError(f"QR for {path.name} does not decode back to its payload")
    return True


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default="attendee-keys.csv", type=Path,
                    help="minted credentials (default: attendee-keys.csv)")
    ap.add_argument("--out", default="handouts", type=Path,
                    help="output directory (default: handouts)")
    ap.add_argument("--no-qr", action="store_true", help="skip QR generation")
    return ap.parse_args()


def write_private(path: Path, text: str) -> None:
    """Write a file only the owner can read, without a world-readable window."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)


def qr_png_bytes(text: str) -> bytes:
    """Render a QR to memory. Same stdin trick: the credential never hits argv."""
    return subprocess.run(["qrencode", "-o", "-", "-s", "6", "-m", "2", "-l", "M"],
                          input=text.encode(), check=True,
                          stdout=subprocess.PIPE).stdout


def make_qr(text: str, path: Path) -> None:
    """Render a QR without putting the credential in argv.

    qrencode reads the payload from stdin when no STRING argument is given,
    which keeps the token out of `ps` while 50 of these render in a loop. The
    output is byte-identical to passing it as an argument.
    """
    subprocess.run(["qrencode", "-o", str(path), "-s", "6", "-m", "2", "-l", "M"],
                   input=text.encode(), check=True)
    path.chmod(0o600)


def contact_sheet(cards) -> str:
    parts = ["<title>Workshop seat credentials</title>",
             f"<style>{STYLE}</style>",
             "<h1>Workshop seat credentials &mdash; cut along the boxes</h1>",
             "<p class='warn'>Each QR contains a live credential. "
             "Hand to one person; do not leave on a table.</p>",
             "<div class='grid'>"]
    for seat, png, expires in cards:
        img = f"<img src='{html.escape(png)}' alt='seat {html.escape(seat)}'>" if png else "<em>no QR</em>"
        parts.append(
            f"<div class='card'><div class='seat'>{html.escape(seat)}</div>{img}"
            f"<div class='exp'>expires {html.escape(expires or 'end of workshop')}</div></div>")
    parts.append("</div>")
    return "\n".join(parts)


def phone_page(cards_b64) -> str:
    """One self-contained file: QRs embedded, no external references.

    The print sheet references 50 separate PNGs, which does not survive being
    sent to a co-facilitator's phone. This does -- AirDrop it, open it, hold it
    up to the attendee's laptop camera.
    """
    parts = ["<!doctype html><meta charset='utf-8'>",
             "<meta name='viewport' content='width=device-width,initial-scale=1'>",
             "<title>Workshop seat credentials</title>",
             f"<style>{PHONE_STYLE}</style>",
             "<h1>Workshop seat credentials</h1>",
             "<p class='sub'>Hold a code up to the attendee's laptop camera "
             "(they open localhost:4321/creds).</p>",
             "<p class='warn'>These are live credentials. Do not screenshot, "
             "forward, or leave this open on an unlocked phone.</p>",
             "<input id='find' inputmode='numeric' placeholder='jump to seat number'>"]
    for seat, b64, expires in cards_b64:
        parts.append(
            f"<div class='card' data-seat='{html.escape(seat)}'>"
            f"<div class='seat'>{html.escape(seat)}</div>"
            f"<img alt='seat {html.escape(seat)}' src='data:image/png;base64,{b64}'>"
            f"<div class='exp'>expires {html.escape(expires or 'end of workshop')}</div>"
            f"<button class='mark'></button></div>")
    parts.append(f"<script>{PHONE_SCRIPT}</script>")
    return "\n".join(parts)


def main() -> int:
    args = parse_args()
    if not args.csv.is_file():
        sys.exit(f"no such file: {args.csv}")

    with args.csv.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        sys.exit(f"{args.csv} has no rows")
    missing = REQUIRED_COLUMNS - set(rows[0])
    if missing:
        sys.exit(f"{args.csv} is missing column(s): {', '.join(sorted(missing))}")

    want_qr = not args.no_qr
    if want_qr and not shutil.which("qrencode"):
        print("note: qrencode not installed -- text snippets only (brew install qrencode)")
        want_qr = False

    args.out.mkdir(parents=True, exist_ok=True)
    args.out.chmod(0o700)

    # Validate every row BEFORE writing anything. A bad row at position 30 must
    # not leave 29 cards on disk for someone to hand out.
    problems = []
    for row in rows:
        try:
            validate_row(row)
        except CardError as exc:
            problems.append(f"  seat {row.get('seat')!r}: {exc}")
    if problems:
        sys.exit("refusing to generate cards -- nothing written:\n" + "\n".join(problems))

    cards, cards_b64 = [], []
    verified = 0
    for row in rows:
        seat = row["seat"]
        body = SNIPPET.format(seat=seat,
                              expires=row["expires"] or "end of workshop",
                              key=row["api_key"])
        try:
            audit_payload(body, row)
        except CardError as exc:
            sys.exit(f"refusing to generate cards: seat {seat}: {exc}")
        write_private(args.out / f"seat-{seat}.txt", body)
        png = ""
        if want_qr:
            png_path = args.out / f"seat-{seat}.png"
            make_qr(body, png_path)
            try:
                if verify_qr(png_path, body):
                    verified += 1
            except CardError as exc:
                sys.exit(f"refusing: {exc}")
            png = png_path.name
            cards_b64.append((seat, base64.b64encode(qr_png_bytes(body)).decode(), row["expires"]))
        cards.append((seat, png, row["expires"]))

    write_private(args.out / "cards.html", contact_sheet(cards))
    if cards_b64:
        write_private(args.out / "phone.html", phone_page(cards_b64))
    print(f"wrote {len(cards)} snippets{' + QR PNGs' if want_qr else ''} "
          f"and {args.out / 'cards.html'}")
    if cards_b64:
        print(f"{args.out / 'phone.html'} -- self-contained; AirDrop this to a co-facilitator")
    if want_qr:
        if verified == len(cards):
            print(f"verified: all {verified} QR codes decode back to exactly their snippet "
                  f"({len(EXPECTED_KEYS)} variables, nothing else)")
        else:
            print("NOT verified: install zbar (brew install zbar) to decode-check every card")
    print(f"{args.out}/ holds live credentials (0600 in a 0700 dir). Delete after the workshop.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
