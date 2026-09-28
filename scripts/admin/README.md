# Facilitator scripts

**Attendees need nothing here.** Your Bedrock key comes on a card; see
[docs/03-chat.md](../../docs/03-chat.md).

These administer IAM in the workshop AWS account and refuse to run without
credentials that can do so. They contain no account ID, no profile name and no
credentials — the account is discovered at run time from `sts:GetCallerIdentity`.

| Script | Purpose |
| --- | --- |
| `mint-attendee-keys.sh` | One expiring Bedrock API key per seat. Run the night before or the morning of. |
| `make-handouts.py` | Turn the CSV into per-seat snippets, QR PNGs, a printable sheet and a self-contained `phone.html`. |
| `show-seat-perms.sh` | Show exactly what one seat's key can and cannot do. |
| `revoke-attendee-keys.sh` | Disable or delete one seat, or tear everything down. |

## The day before / of

```bash
aws sso login --profile <your-profile>       # or however you authenticate
export AWS_PROFILE=<your-profile>            # everything runs against these creds

./mint-attendee-keys.sh --seats 50           # writes attendee-keys.csv (0600)
./make-handouts.py                           # writes handouts/ (0700)
./show-seat-perms.sh tmws-01                 # sanity-check one seat
```

`attendee-keys.csv` and `handouts/` hold live credentials, are created mode
0600/0700, and are gitignored. They are the only copy — AWS will not show a key
again. Delete them after the workshop.

## Handing keys out from a phone

`handouts/phone.html` is one self-contained file — QR codes embedded, no
external references, ~140 KB for 50 seats. Open it on a phone and hold a code
up to the attendee's laptop camera while they have
<http://localhost:4321/creds> open. Tap **mark handed out** to grey out a seat;
that state is per-device (`localStorage`), so it does not sync between
facilitators.

Because it does not sync, **split the seat ranges** rather than coordinating:
one facilitator works 01–25, the other 26–50. Two people handed the same seat
both work, but their usage merges in CloudTrail and revoking one revokes both.

Send it to a co-facilitator by **AirDrop** or another device-to-device channel.
Not email, not Slack — that file is 50 live credentials, and those systems keep
copies you cannot delete. If a phone holding it is lost, run
`./revoke-attendee-keys.sh --all --delete` and re-mint; that is cheaper than
reasoning about what was exposed.

## Validity

Keys are usable only between midnight MST on the day they are minted and the
hard cutoff in `mint-attendee-keys.sh` (`CUTOFF_LOCAL`, currently the last
moment of the workshop day). Both ends are IAM `Deny` conditions on the group,
so they apply no matter who still holds a copy, on top of each key's own
expiry. Minting after the cutoff is refused rather than producing dead keys.

## Afterwards

```bash
./revoke-attendee-keys.sh --seat 07          # disable one seat (reversible)
./revoke-attendee-keys.sh --teardown         # delete keys, users, group
```
