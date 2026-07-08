# Space Telemetry, End to End

**A Space Summit 2026 workshop**: process, store, query, and _talk to_
satellite telemetry using open source tools — Apache Flink, Iceberg, Polaris,
Trino, Superset, Garage, LibreChat, LiteLLM, and a hand-built MCP server on
AWS Bedrock.

We ingest real ESA mission telemetry (the
[ESA Anomaly Dataset](https://zenodo.org/records/15237121)) into an Iceberg
lakehouse with Flink, query it with Trino and Superset, then teach Claude to
explore it through a custom MCP server.

## Prerequisites

- **Docker** (a recent Docker Desktop or Engine; Compose v2)
- **[Task](https://taskfile.dev)** (`brew install go-task` / see taskfile.dev)
- ~8 GB of RAM for Docker and a few GB of free disk
- The workshop AWS credential (handed out at the session) for Steps 3–4

No accounts, no auth, nothing else to install — everything runs in containers.

## Quick start

```bash
git clone <this-repo> && cd tm-tutorial
task setup            # creates .env from the template + local data dirs
task data:download    # ~150 MB workshop subset of the ESA dataset
task up:docs          # the front door: service links + these docs at :4321
```

Then follow the docs, in order — each step's `task` commands are listed in the
doc:

| | Doc | What you'll do |
|---|---|---|
| Step 0 | [The big picture](docs/00-overview.md) | Architecture + the dataset |
| Step 1 | [Ingest](docs/01-ingest.md) | Flink → Iceberg (on Garage), via the Polaris catalog |
| Step 2 | [Query](docs/02-query.md) | Trino, the query planner, views, Superset dashboards |
| ☕ | _break_ | |
| Step 3 | [Chat](docs/03-chat.md) | LibreChat + LiteLLM + Bedrock |
| Step 4 | [MCP](docs/04-mcp-server.md) | Build an MCP server for Trino with FastMCP |
| Step 5 | [Agent](docs/05-agent.md) | Compose trino/esa-adb/superset MCP servers into an analysis agent |

The short version of Step 1–2:

```bash
task up:ingest        # Garage, Polaris (+ Postgres), Flink
task data:prepare     # pickled ESA channels -> JSON for Flink
task catalog:create   # create the 'workshop' catalog in Polaris
task flink:job        # load readings + metadata tables into Iceberg
task up:query         # Trino + Superset (admin / admin)
task trino:views      # create the enrichment / anomaly views
```

`task --list` shows every command. `task up` starts the entire stack at once.

## What lands in the warehouse

- `readings` — the telemetry fact table (`channel, ts, ts_month, value`)
- `channels`, `labels`, `anomaly_types` — the dataset's metadata as dimension
  tables
- Views (`task trino:views`): `readings_enriched` (readings + channel
  metadata), `anomalies` (labeled windows + their type), and
  `labeled_readings` — every reading tagged with whether it falls inside a
  labeled anomaly. That last one is what the Superset anomaly chart and the
  Step 4 MCP investigation are built on.

## If you fall behind

Don't want to wait for the ingest? `task checkpoint:restore -- <name>` drops in
a pre-built warehouse — the Iceberg files **and** the Polaris catalog that
points at them — so you can start the stack and query immediately. Your
instructor will share the checkpoint names (and a mirror URL, below).

## Dataset sizes

```bash
task data:download                # small  ~150 MB — 7 channels, Mission1
task data:download -- medium      # medium ~3.8 GB — all of Mission1
task data:download -- full        # full  ~11.6 GB — all three missions
```

On the conference network, set `DATA_MIRROR=<url>` in `.env` to fetch from the
local mirror instead of Zenodo. The full ESA download is ~11.6 GB; the small
subset pulls just seven channels (plus the metadata) via HTTP range requests.

The ESA Anomaly Dataset is © ESA, licensed
[CC BY 3.0 IGO](https://creativecommons.org/licenses/by/3.0/igo/) —
see [arXiv:2406.17826](https://arxiv.org/abs/2406.17826) for the paper.

## Ports

| Service | URL |
|---|---|
| Docs + service links | http://localhost:4321 |
| Flink UI | http://localhost:8081 |
| Trino | http://localhost:8080 |
| Superset | http://localhost:8088 (admin / admin) |
| Polaris (catalog API) | http://localhost:8181 |
| Garage (S3 API) | http://localhost:3900 |
| LibreChat | http://localhost:3080 |
| LiteLLM | http://localhost:4000 |
| MCP server | http://localhost:8000/mcp |

Polaris's metastore is a Postgres container; it's internal to the stack and
publishes no host port.

## For instructors

- `task checkpoint:save <name>` after finishing each step during prep; host
  the `checkpoints/` directory on the mirror and set `CHECKPOINT_BASE_URL` so
  `checkpoint:restore` can fetch it. A checkpoint captures the Garage volumes
  and the Polaris Postgres volume together, so a restore is complete.
- The Bedrock model IDs in `litellm/config.yaml` must match what the workshop
  AWS account has enabled — verify during prep.
- A hosted deployment of this stack runs on the Intelligent Space Platform for
  attendees who prefer not to install anything.
