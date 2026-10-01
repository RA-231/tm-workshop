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
