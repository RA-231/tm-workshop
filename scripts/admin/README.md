# Facilitator scripts

These scripts are for facilitators. Attendees receive a key on a card; see
[docs/03-chat.md](../../docs/03-chat.md).

The scripts administer the workshop's model project and require an admin
credential. The project is resolved at runtime; project IDs, organization names,
and credentials are supplied externally.

| Script | Purpose |
| --- | --- |
| `list-models.sh` | What models the project can reach; `--check` cross-checks the gateway config. |
| `mint-attendee-keys.sh` | One expiring key per seat. Run the night before or the morning of. |
| `make-handouts.py` | Turn the CSV into per-seat snippets, QR PNGs, a printable sheet and a self-contained `phone.html`. |

## Before the workshop

```bash
export LLM_ADMIN_KEY=$(secret get OPEN_AI_ADMIN_KEY)   # an sk-admin-... key
export LLM_PROJECT_NAME="Space Software Summit"        # or LLM_PROJECT_ID

./list-models.sh                             # confirm available models
./mint-attendee-keys.sh --seats 50           # writes attendee-keys.csv (0600)
./make-handouts.py                           # writes handouts/ (0700)
```

`attendee-keys.csv` and `handouts/` hold live credentials, are created mode
0600/0700, and are gitignored. They are the only copy — the provider shows a key
once. Delete them after the workshop.

## Handing keys out from a phone

`handouts/phone.html` is one self-contained file — QR codes embedded, no
external references, ~140 KB for 50 seats. Open it on a phone and hold a code
up to the attendee's laptop camera while they have
<http://localhost:4321/creds> open. Tap **mark handed out** to grey out a seat;
that state is per-device (`localStorage`), so it does not sync between
facilitators.

Assign separate seat ranges to each facilitator, such as 01–25 and 26–50.
If two attendees receive the same seat's key, their usage is combined in the
provider's dashboard, and revoking the key affects both.

Transfer it to a co-facilitator using **AirDrop** or another device-to-device
channel. Avoid email or Slack: the file contains 50 live credentials, and those
services may retain copies.

## Expiry, revocation and spend

**Expiry is automatic.** Every key is minted with an expiry set to the cutoff in
`mint-attendee-keys.sh` (`CUTOFF_LOCAL`). All keys expire at the end of the
workshop, and the script refuses to mint keys after the cutoff. Expiry does not
require a teardown script.

**Revocation is manual, in the provider's dashboard** — delete the service
account for that seat. It is permanent; there is no reversible disable. This is
for the one-off case (a key posted in a public channel), not routine cleanup.

**Spend control is the project's monthly hard limit**, set in the dashboard —
there is no API for it:

- It is **shared across all 50 seats**. One attendee looping requests will
  exhaust it and every other seat starts getting `429
  project_spend_limit_exceeded`.
- There is **no per-key spend limit** at this provider — limits exist at
  organization and project scope only. Per-key *usage* is visible in the
  dashboard (grouped by the `tmws-NN` service-account name), so you can see who
  spent what after the fact, and act on it manually.

Attendees can set a per-key budget in LiteLLM using `/key/generate` with
`max_budget`, as described in Step 3. This controls their local usage; it does
not enforce a project-wide per-seat budget.

**Rate limits cap request and token throughput** automatically. The
project's per-model limits were lowered from the defaults on 2026-10-01:

| model | RPM | TPM | ceiling at ~$12/M tokens |
| --- | --- | --- | --- |
| *(provider default)* | 5000 | 2-4M each, 10M total | ~$120/min |
| `chat-latest` (= `workshop-default`) | 1000 | 600k | $7.21/min |
| the other three | 500 | 200k each | $2.40/min each |
| **total now** | | **1.2M** | **$14.42/min** |

Sizing is driven by the AI segment being ~40 minutes, so usage is dense rather
than spread across a day:

- Expected: 50 attendees x ~15 turns. At chat-weight turns (~1.5k tokens) that
  is ~1.1M tokens (~$13); at agent turns carrying MCP tool results (~8k tokens)
  it is ~6M (~$72).
- Worst case, everything saturated for the full 40 minutes: ~$577. That sits
  just above the project's $500 monthly hard limit, so the limit is the
  spending cap. The rate limits constrain throughput during bursts.
- `chat-latest` has a higher limit because `workshop-default` points at it and it
  is the only model that drives tools on this path. A synchronised Step 5 burst
  ("everyone run the agent now") is ~50 x 8k = 400k tokens in one minute, which
  200k TPM would have throttled. Its RPM is higher too: an agent turn is several
  API calls, one per tool round trip, not one.

If requests are throttled during the dry run, review the limits. Changes apply
per project and take effect immediately.

**Do not rely on watching the dashboard.** Usage data backfills on the order of
20-30 minutes (measured: a sliding 2-hour window reported newer data on a later
query with no calls in between). Revoking a key takes about 5 seconds once you
decide to, but a visible usage spike may already be 20+ minutes old. Rate limits
act immediately; the monthly spend limit and manual monitoring depend on
delayed usage reporting.
