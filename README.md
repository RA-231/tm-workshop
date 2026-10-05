# Space Telemetry, End to End

**A Space Summit 2026 workshop**: process, store, query, and analyze satellite
telemetry using open source tools — [Apache Flink](https://flink.apache.org/),
[Iceberg](https://iceberg.apache.org/), [Polaris](https://polaris.apache.org/),
[Trino](https://trino.io/), [Superset](https://superset.apache.org/),
[Garage](https://garagehq.deuxfleurs.fr/),
[LibreChat](https://www.librechat.ai/), [LiteLLM](https://www.litellm.ai/), and
a custom [MCP](https://modelcontextprotocol.io/) server connected to an
OpenAI-compatible model gateway.

We ingest real ESA mission telemetry (the
[ESA Anomaly Dataset](https://zenodo.org/records/15237121)) into an Iceberg
lakehouse with Flink, query it with Trino and Superset, then give a model tools
to explore it through an MCP server.

## Prerequisites

1. **[Docker](https://docs.docker.com/get-started/docker-overview/)** (a recent
   Docker Desktop or Engine; [Compose v2](https://docs.docker.com/compose/))
2. **[Task](https://taskfile.dev)** (`brew install go-task` / see taskfile.dev)
3. ~8 GB of RAM for Docker and a few GB of free disk
4. The workshop model key (handed out on a card at the session) for Steps 3–5

We recommend that you stop any servers, containers or clusters that use common localhost ports for the duration of this workshop.

The services run in containers. The chat step uses a workshop model key and a
LibreChat account you create locally.

**On Windows?** The workshop is built and rehearsed on macOS, and the setup
scripts assume a Unix shell. [WINDOWS.md](WINDOWS.md) covers running it under
WSL2 and the rough edges you may hit — untested, but it's the fastest path we
know of.

## Quick start

The setup actions are documented in [0.4 — Set up your laptop](docs/00-overview.md#04--set-up-your-laptop).

```bash
git clone <this-repo> && cd tm-tutorial
# create .env from the template + local data dirs
task setup
# ~150 MB workshop subset of the ESA dataset
task data:download
# service links + these docs at :4321
task up:docs
```

Follow the docs in order. Each section has a reference such as **2.4 — Create
charts in Superset**, and each action has a reference such as **2.4.4 — Chart
the labeled anomalies**. If you need help, give the number and name, the command
or screen you're using, and any error message.

| | Doc | What you'll do |
|---|---|---|
| Step 0 | [Overview](http://localhost:4321/overview) | Architecture + the dataset |
| Step 1 | [Ingest](http://localhost:4321/ingest) | Flink → Iceberg (on Garage), via the Polaris catalog |
| Step 2 | [Query](http://localhost:4321/query) | Trino, the query planner, views, Superset dashboards |
| ☕ | _break_ | |
| Step 3 | [Chat](http://localhost:4321/chat) | LibreChat + LiteLLM + the model gateway |
| Step 4 | [MCP](http://localhost:4321/mcp-server) | Build an MCP server for Trino with [FastMCP](https://gofastmcp.com) |
| Step 5 | [Agent](http://localhost:4321/agent) | Connect the trino/esa-adb/superset MCP servers to an analysis agent |

### If you fall behind

Use `task checkpoint:restore -- <name>` to restore a pre-built warehouse from
`data/checkpoints/`, including the Iceberg files and the Polaris catalog. The
restore replaces your own warehouse and stops Garage and Polaris while it runs.
Start the services again with `task up:ingest` and `task up:query`, then query
without repeating the ingest. Your instructor will share the checkpoint names
and a mirror URL.

### Ports

Please ensure you have no existing services running using these ports.

| Service | URL |
|---|---|
| Docs + service links | http://localhost:4321 |
| Presenter slides | http://localhost:4321/slides/ |
| Credential scanner | http://localhost:4321/creds/ |
| Flink UI | http://localhost:8081 |
| Trino | http://localhost:8080 |
| Superset | http://localhost:8088 (admin / admin) |
| Polaris (catalog API) | http://localhost:8181 |
| Garage (S3 API) | http://localhost:3900 |
| LibreChat | http://localhost:3080 |
| LiteLLM | http://localhost:4000 |
| MCP server | http://localhost:8000/mcp |

Polaris's metastore is a [Postgres](https://www.postgresql.org/) container;
it's internal to the stack and publishes no host port.

### [CLICK TO BEGIN GUIDED WORKSHOP](http://localhost:4321)

---

## ↑ ↑ ↓ ↓ ← → ← → B A

Shortcut to Lesson 3 if you're in a hurry

```bash
# Garage, Polaris (+ Postgres), Flink
task up:ingest
# pickled ESA channels -> JSON for Flink
task data:prepare
# create the 'workshop' catalog in Polaris
task catalog:create
# load readings + metadata tables into Iceberg
task flink:job
# Trino + Superset (admin / admin)
task up:query
# create the enrichment / anomaly views
task trino:views
```

`task --list` shows every command. `task up` starts the entire stack at once.
`task flink:job` skips itself once the data is loaded — `task flink:reload`
forces a fresh load.

### Tables and views

1. `readings` — the telemetry fact table (`channel, ts, ts_month, value`)
2. `channels`, `labels`, `anomaly_types` — the dataset's metadata as dimension
   tables
3. Views (`task trino:views`): `readings_enriched` (readings + channel
   metadata), `anomalies` (labeled windows + their type), and
   `labeled_readings` — every reading tagged with whether it falls inside a
   labeled anomaly. The Superset anomaly chart and the Step 4 MCP investigation
   use this view.

### Dataset sizes

```bash
# small  ~150 MB — 7 channels, Mission1
task data:download
# medium ~3.8 GB — all of Mission1
task data:download -- medium
# full  ~11.6 GB — all three missions
task data:download -- full
```

On the conference network, set `DATA_MIRROR=<url>` in `.env` to fetch from the
local mirror instead of Zenodo. The full ESA download is ~11.6 GB; the small
subset pulls just seven channels (plus the metadata) via HTTP range requests.

The ESA Anomaly Dataset is © ESA, licensed
[CC BY 3.0 IGO](https://creativecommons.org/licenses/by/3.0/igo/) —
see [arXiv:2406.17826](https://arxiv.org/abs/2406.17826) for the paper.

### For instructors

1. **Slides:** `task slides` → http://localhost:4321/slides/. A single
   self-contained HTML deck (`site/public/slides/index.html`) covering Steps 0–5
   — no build, no network, so it also works opened straight off disk. `?` lists
   the controls; `p` opens a presenter window with speaker notes, the next
   slide, and a timer; `o` is the overview grid for jumping around.
2. `task checkpoint:save -- <name>` after finishing each step during prep. Run
   `docker compose stop` first so the snapshot is consistent. Checkpoints are
   saved to `data/checkpoints/`; host that directory on the mirror and set
   `CHECKPOINT_BASE_URL` so `checkpoint:restore` can fetch it. A checkpoint
   captures the Garage volumes and the Polaris Postgres volume together, so a
   restore is complete.
3. The gateway discovers the models available to the workshop key each time it
   starts; `litellm/config.yaml` does not list model IDs. Run `task llm:check`
   during prep to see the list and confirm `WORKSHOP_DEFAULT_MODEL` is still
   available.
