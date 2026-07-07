# Space Telemetry, End to End

**A Space Summit 2026 workshop**: process, store, query, and *talk to*
satellite telemetry using open source tools — Apache Pulsar, Flink, Iceberg,
Polaris, Trino, Superset, LibreChat, LiteLLM, and a hand-built MCP server on
AWS Bedrock.

We ingest real ESA mission telemetry (the
[ESA Anomaly Dataset](https://zenodo.org/records/15237121)) into an Iceberg
lakehouse with Flink, query it with Trino and Superset, then teach Claude to
explore it through a custom MCP server.

## Prerequisites

- **Docker** (a recent Docker Desktop or Engine; Compose v2)
- **[Task](https://taskfile.dev)** (`brew install go-task` / see taskfile.dev)
- ~8 GB of RAM for Docker and ~5 GB of free disk
- The workshop AWS credential (handed out at the session) for Steps 3–4

No accounts, no auth, nothing else to install — everything runs in
containers.

## Quick start

```bash
git clone <this-repo> && cd tm-tutorial
task setup            # creates .env from the template
task data:download    # ~150 MB workshop subset of the ESA dataset
task up:ingest        # start Pulsar, Polaris, Flink  (Step 1 begins here)
```

Then follow the docs, in order:

| | Doc | What you'll do |
|---|---|---|
| Step 0 | [The big picture](docs/00-overview.md) | Architecture + the dataset |
| Step 1 | [Ingest](docs/01-ingest.md) | Pulsar → Flink → Iceberg, via Polaris |
| Step 2 | [Query](docs/02-query.md) | Trino, the query planner, Superset dashboards |
| ☕ | *break* | |
| Step 3 | [Chat](docs/03-chat.md) | LibreChat + LiteLLM + Bedrock |
| Step 4 | [MCP](docs/04-mcp-server.md) | Build an MCP server for Trino with FastMCP |

`task --list` shows every available command.

## If you fall behind

Every step is tagged. `git checkout step-2` puts the repo exactly where it
should be at the end of Step 2, and `task checkpoint:restore -- step-2`
fetches a pre-built warehouse so you don't have to re-run the ingest. Jump
back in whenever.

| Tag | State |
|---|---|
| `step-0` | Repo scaffold, data downloaded |
| `step-1` | Telemetry streaming into Iceberg |
| `step-2` | Trino + Superset querying it |
| `step-3` | LibreChat talking to Bedrock |
| `step-4` | MCP server wired into LibreChat |

## Dataset sizes

```bash
task data:download                # small  ~150 MB — 7 channels, Mission1
task data:download -- medium      # medium ~3.8 GB — all of Mission1
task data:download -- full        # full  ~11.6 GB — all three missions
```

On the conference network, set `DATA_MIRROR=<url>` in `.env` to fetch from
the local mirror instead of Zenodo.

The ESA Anomaly Dataset is © ESA, licensed
[CC BY 3.0 IGO](https://creativecommons.org/licenses/by/3.0/igo/) —
see [arXiv:2406.17826](https://arxiv.org/abs/2406.17826) for the paper.

## Ports

| Service | URL |
|---|---|
| Flink UI | http://localhost:8081 |
| Trino | http://localhost:8080 |
| Superset | http://localhost:8088 (admin / admin) |
| Polaris | http://localhost:8181 |
| Pulsar admin | http://localhost:8084 |
| Garage (S3) | http://localhost:3900 |
| LibreChat | http://localhost:3080 |
| LiteLLM | http://localhost:4000 |
| MCP server | http://localhost:8000/mcp |

## For instructors

- `scripts/checkpoint.sh save step-N` after finishing each step during prep;
  host `checkpoints/` on the mirror and set `CHECKPOINT_BASE_URL`.
- The Bedrock model IDs in `litellm/config.yaml` must match what the workshop
  AWS account has enabled — verify during prep.
- A hosted deployment of this stack runs on the Intelligent Space Platform
  for attendees who prefer not to install anything.
