# Facilitator scripts

**Attendees need nothing here.** Your key comes on a card; see
[docs/03-chat.md](../../docs/03-chat.md).

These administer the workshop's model project and refuse to run without an admin
credential. They contain no project id, no org name and no credentials — the
project is resolved at run time.

| Script | Purpose |
| --- | --- |
| `list-models.sh` | What models the project can reach; `--check` cross-checks the gateway config. |
| `mint-attendee-keys.sh` | One expiring key per seat. Run the night before or the morning of. |
| `make-handouts.py` | Turn the CSV into per-seat snippets, QR PNGs, a printable sheet and a self-contained `phone.html`. |

## The day before / of

```bash
export LLM_ADMIN_KEY=$(secret get OPEN_AI_ADMIN_KEY)   # an sk-admin-... key
export LLM_PROJECT_NAME="Space Software Summit"        # or LLM_PROJECT_ID

./list-models.sh                             # confirm the lineup
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

Because it does not sync, **split the seat ranges** rather than coordinating:
one facilitator works 01–25, the other 26–50. Two people handed the same seat
both work, but their usage merges in the provider's dashboard and revoking one
revokes both.

Send it to a co-facilitator by **AirDrop** or another device-to-device channel.
Not email, not Slack — that file is 50 live credentials, and those systems keep
copies you cannot delete.

## Expiry, revocation and spend

**Expiry is automatic.** Every key is minted with an expiry set to the cutoff in
`mint-attendee-keys.sh` (`CUTOFF_LOCAL`), so the whole cohort dies at the end of
the workshop whether or not anyone remembers. Minting after the cutoff is
refused rather than producing dead keys. There is no teardown script and none is
needed.

**Revocation is manual, in the provider's dashboard** — delete the service
account for that seat. It is permanent; there is no reversible disable. This is
for the one-off case (a key posted in a public channel), not routine cleanup.

**Spend control is the project's monthly hard limit**, set in the dashboard —
there is no API for it. Two things to know:

- It is **shared across all 50 seats**. One attendee looping requests will
  exhaust it and every other seat starts getting `429
  project_spend_limit_exceeded`. The limit protects the bill, not each other.
- There is **no per-key spend limit** at this provider — limits exist at
  organization and project scope only. Per-key *usage* is visible in the
  dashboard (grouped by the `tmws-NN` service-account name), so you can see who
  spent what after the fact, and act on it manually.

The per-seat cap attendees actually get is LiteLLM's: `/key/generate` with
`max_budget`, which Step 3 teaches. It runs on their own laptop, so it protects
them from surprises rather than protecting the project.

**Rate limits are the control that actually bounds the damage**, because they
cap the burn *rate* with no human in the loop and no reporting delay. The
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
  just above the project's $500 monthly hard limit, so the limit is the real
  backstop and the rate limits absorb bursts without tripping it.
- `chat-latest` gets the headroom because `workshop-default` points at it and it
  is the only model that drives tools on this path. A synchronised Step 5 burst
  ("everyone run the agent now") is ~50 x 8k = 400k tokens in one minute, which
  200k TPM would have throttled. Its RPM is higher too: an agent turn is several
  API calls, one per tool round trip, not one.

If it pinches during the dry run, raise it -- limits are per project and take
effect immediately.

**Do not rely on watching the dashboard.** Usage data backfills on the order of
20-30 minutes (measured: a sliding 2-hour window reported newer data on a later
query with no calls in between). Revoking a key takes about 5 seconds once you
decide to, but by the time a spike is visible it is already 20+ minutes old. The
order of defence is: rate limits (immediate, automatic), then the monthly hard
spend limit (lagging, automatic), then monitoring (lagging, manual).
