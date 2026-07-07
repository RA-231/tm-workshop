# Step 0 — The Big Picture

Welcome! Over the next three hours we're going to build a small but real
telemetry platform out of open source parts, then teach an LLM to use it.

## What we're building

```
                    ┌──────────────────────────────────────────────────────────┐
                    │                     your laptop (Docker)                  │
                    │                                                          │
  ESA telemetry     │  ┌──────────┐    ┌─────────────────────┐                 │
  (pickled  ────────┼─►│ prepare  │───►│ Flink               │                 │
   channels)        │  │ (→ JSON) │    │  (batch → Iceberg)  │                 │
                    │  └──────────┘    └──────────┬──────────┘                 │
                    │                     ┌────────┐           │ writes        │
                    │                     │ Polaris│◄──────────┤ metadata      │
                    │                     │(catalog)│          ▼               │
                    │                     └───▲────┘   ┌──────────────┐        │
                    │                         │        │ Garage (S3)   │       │
                    │                         │        │ Iceberg files │       │
                    │                         │        └──────▲───────┘        │
                    │                     ┌───┴────┐          │ reads          │
                    │   ┌──────────┐      │ Trino  │──────────┘                │
                    │   │ Superset │─SQL─►│        │◄─SQL─┐                    │
                    │   └──────────┘      └────────┘      │                    │
                    │                                ┌────┴──────┐             │
                    │   ┌───────────┐    ┌────────┐  │ MCP server│             │
                    │   │ LibreChat │───►│ LiteLLM│  └────▲──────┘             │
                    │   │  (chat UI)│    └───┬────┘       │ MCP               │
                    │   └─────┬─────┘        │            │                    │
                    │         └──────────────┼────────────┘                    │
                    └────────────────────────┼─────────────────────────────────┘
                                             ▼
                                       AWS Bedrock (Claude)
```

## The three acts

**Act 1 — Ingesting data with Flink (Step 1).**
Apache Flink reads the telemetry files and writes them into **Apache
Iceberg** — an open table format that turns a pile of Parquet files in object
storage into a real table with schema, snapshots, and time travel. The files
live in **Garage**, a lightweight S3-compatible object store, and **Apache
Polaris** is the catalog: the service that answers "what tables exist and where
is their current metadata?"

**Act 2 — Querying data with Trino (Step 2).**
**Trino** is a distributed SQL engine that reads Iceberg natively. Anything
that speaks SQL can now analyze the telemetry — we'll use **Apache Superset**
to build charts, and we'll peek at Trino's query planner to understand how
Iceberg's metadata makes queries fast (partition pruning, file skipping).

**Act 3 — Interacting with Trino using MCP (Steps 3–4).**
The **Model Context Protocol (MCP)** is how we hand tools to an LLM. We'll run
**LibreChat** as the chat UI, route model calls through **LiteLLM** to AWS
Bedrock, and then build our own MCP server with **FastMCP** that lets Claude
explore and query the telemetry warehouse — "which channel had the most
anomalous March?" becomes a conversation instead of a SQL session.

## The dataset

We're using the [ESA Anomaly Dataset (ESA-ADB)](https://zenodo.org/records/15237121):
real, curated telemetry from three ESA missions, published in 2024 to give the
anomaly-detection community something better than synthetic benchmarks. It's
224 channels of multi-year time series with labeled anomalies — exactly the
shape of data a real mission ops team works with.

The full download is ~11.6 GB (three mission archives). For the workshop we
use a ~150 MB subset — Mission1's metadata plus seven channels, pulled
straight out of the archive with HTTP range requests (see
`task data:download`). Same schema, less waiting on conference Wi-Fi; every
step also works against a full mission if you re-run it at home
(`task data:download -- medium`).

## Ground rules

- Everything runs in Docker Compose. `task up` and go.
- No authentication anywhere it can be avoided. This is a workshop, not prod.
- If you fall behind, every step has a git tag (`step-1` … `step-4`).
  `git checkout step-2` puts the repo exactly where it should be at the end
  of Step 2. Checkpoint data is downloadable too, so you never have to wait
  for a slow ingest to catch up.

Next: [Step 1 — Ingesting data into Iceberg](01-ingest.md)
