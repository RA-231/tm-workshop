# Step 5 — The Capstone: A Telemetry Analysis Agent

Everything so far has been building to this. We have a lakehouse (Steps 1–2), a
chat UI wired to the gateway (Step 3), and MCP servers that give a model real
capabilities (Step 4). Now we assemble a **LibreChat Agent** that composes them
into something that *works like an analyst*: it **explores** the data, **detects**
anomalies from the signal, and **visualizes** what it finds — deciding for itself
which tool to reach for at each step.

## What we're building

An agent backed by a capable tool-calling model that composes
**three focused MCP servers**:

```
                         ┌──────────────────────────────┐
                         │  LibreChat Agent              │
                         │  (workshop-default model)     │
                         └───────────────┬───────────────┘
                        tools │          │          │ tools
              ┌───────────────┘          │          └────────────────┐
              ▼                          ▼                           ▼
     ┌─────────────────┐      ┌──────────────────────┐     ┌──────────────────┐
     │ trino-mcp        │      │ esa-adb               │     │ superset-mcp     │
     │ (explore)        │      │ (detect)              │     │ (visualize)      │
     │ query/list/desc  │      │ nav + 6 detectors     │     │ intent → charts  │
     └────────┬─────────┘      └──────────┬────────────┘     └────────┬─────────┘
              └──────────► Trino ◄─────────┘                          │
                            │                                Superset ◄┘
                            ▼                                    │
                         Iceberg (esa_adb)  ◄────────────────────┘
```

Why three servers instead of one? **Separation of concerns, and reuse.**
`trino-mcp` is dataset-agnostic (point it at any catalog); `esa-adb` is the
domain layer (telemetry navigation + the phase-aware detectors); `superset-mcp`
is pure visualization. The agent doesn't care — it just sees a menu of tools. But
you can lift `trino-mcp` or `superset-mcp` into a completely different project
unchanged. **Composing small, focused MCP servers is the pattern to internalize.**

## Bring up the servers

```bash
task up:mcp        # builds + starts esa-adb, trino, superset MCP servers; reloads LibreChat
```

LibreChat is already configured to see all three (see
[`librechat/librechat.yaml`](../librechat/librechat.yaml)):

```yaml
mcpServers:
  esa-adb:   { type: streamable-http, url: http://mcp-server:8000/mcp }
  trino:     { type: streamable-http, url: http://trino-mcp:8000/mcp }
  superset:  { type: streamable-http, url: http://superset-mcp:8000/mcp }
```

Two guards had to be cleared to get here, and they're worth knowing because
they'll bite anyone wiring MCP into a container stack:

1. **DNS-rebinding Host check.** MCP's streamable-http transport only accepts
   `localhost` in the `Host` header by default and returns `421 Misdirected
   Request` otherwise. Our servers reach each other by compose hostname
   (`http://mcp-server:8000`), so we set `host_origin_protection=False` (fine on
   a trusted local network).
2. **LibreChat SSRF allowlist.** LibreChat v0.8.7 blocks MCP URLs that resolve to
   private IPs unless their domain is allow-listed — hence
   `mcpSettings.allowedDomains: [mcp-server, trino-mcp, superset-mcp]`.

## Enabling Agents

Agents are turned on in `librechat.yaml`:

```yaml
interface:
  agents: true
```

You can also configure the agent endpoint (`endpoints.agents`) — `recursionLimit`
(the UI's "Max Agent Steps", default 25), `capabilities`, etc. We leave the
defaults, with one note: the built-in **Code Interpreter** capability
(`execute_code`) is LibreChat's *paid, hosted* API (and currently closed to new
signups), which is exactly why our "run analysis" capability lives in MCP servers
instead — no external dependency, and the code runs next to the data.

## Build the agent (LibreChat UI, v0.8.7)

1. Pick **Agents** from the model/endpoint menu, then open the **Agent Builder**
   in the side panel.
2. **Name:** `Telemetry Anomaly Analyst`
3. **Model:** provider **Workshop Models** → **`workshop-default`**. The other
   models in the picker are fine for chat, but not all of them can call tools on
   this path — the alias points at one that can.
4. **Instructions:** paste the methodology prompt below.
5. **Tools → Add Tools:** enable the **esa-adb**, **trino**, and **superset** MCP
   servers. Each appears as one entry you can expand to toggle individual tools.
6. **Save.** To let attendees reuse it, **Share** it (to a group or Public) —
   v0.8.7 has no API to *create* an agent, so sharing one you built is the
   reproducible path.

### Instructions (paste into the builder)

```
You are a satellite-telemetry anomaly analyst. You have three MCP tool groups:
trino (generic SQL exploration), esa-adb (telemetry navigation + scored anomaly
detectors), and superset (turn intent into charts). Read the about://dataset
resource first if your client exposes it.

The data is anonymized, quantized "staircase" telemetry — raw-value thresholds
are weak; reason about PHASE (which level, in what order) and DURATION (dwell).

Method:
1. Orient: list_channels / channel_summary; note the time span.
2. Detect: run phase_anomaly, plateau, data_gaps, stl_residual, cadence over a
   broad window. Scores are relative — they mean nothing in isolation.
3. Calibrate: score a quiet window from the same channel and compare.
4. Zoom: readings_around the worst segment; describe what physically happened.
5. Corroborate: cross_correlation against sibling channels in the same group.
6. Visualize: anomaly_overlay_chart(channel), then add_to_dashboard; hand back
   the URL so the user can see it.
7. DISCIPLINE: anomalies_for is the labeled ANSWER KEY. Do NOT consult it while
   detecting — only afterward, to grade your findings (hits/misses/false alarms).

Report a ranked list: channel, window, the scores that flagged it vs the nominal
comparison, a phase+duration explanation, the chart URL, and your confidence.
```

## The six detectors — scores, not flags

The `esa-adb` server exposes six anomaly detectors. Each returns **numeric scores,
never booleans**, so *the agent* decides what counts as an alarm by comparing a
suspect window against a nominal one — no hardcoded thresholds.

| Tool | What it scores |
|---|---|
| `phase_anomaly` | unusual level / dwell-duration / transitions (the staircase unlock) |
| `plateau` | abnormally long "stuck" flat runs |
| `data_gaps` | dropouts — worst gap vs the dominant sample interval |
| `stl_residual` | departures from the channel's own trend/season |
| `cadence` | sampling jitter and drift (regularity, not dropouts) |
| `cross_correlation` | decorrelation from sibling channels (multivariate) |

Why phase-awareness is the unlock: on the labeled March-2000 anomaly, `channel_41`
dropped to level ~0.64 (well *inside* its 0.61–0.98 value range, so a value
threshold shrugs) and got stuck there for ~7.6 hours. `phase_anomaly` flags it
with a dwell z-score of ~29; `plateau` and `data_gaps` spike alongside. Phase +
duration sees what value-only detectors can't.

## Three MCP primitives — one server, many clients

MCP has three primitives, and our `esa-adb` server exercises all of them:

- **Tools** — model-invoked actions (the detectors, navigation, charts). Every
  MCP client supports these.
- **Resources** — read-only reference context: `about://dataset` (the
  anonymization briefing), `schema://esa_adb` (data dictionary),
  `catalog://channels` (the channel catalog).
- **Prompts** — canned, parameterized workflows: `investigate_channel(channel)`,
  `triage_window(channel, start, end)`.

**Client caveat:** LibreChat v0.8.7 consumes **tools only** — it ignores resources
and prompts. The *same server* exposes all three to a protocol-complete client:
open `http://localhost:8000/mcp` in **Claude Desktop** or **Claude Code** and the
resources attach to context and the prompts appear as slash-commands. That's the
lesson — the protocol is client-agnostic; build the full surface once.

## Visualize — do-what-I-mean, no Superset API

`superset-mcp` lets the agent *say what it wants* and get back a chart URL,
without ever touching Superset's chart JSON:

```
anomaly_overlay_chart("channel_41")
  → { "url": "http://localhost:8088/explore/?slice_id=1" }
```

Behind that one call the server logs into Superset, registers the
`labeled_readings` view as a dataset, and constructs the (genuinely fiddly)
`params`/`query_context` for a time-series line split by `is_anomaly`. The agent
never sees any of it — that encapsulation *is* the design goal.

## Try it

Open a new chat with the agent and ask:

> *"Investigate channel_41 for anomalies. Work from the signal — don't look at the
> labels until you've committed to your findings, then check yourself. Chart the
> result and give me the link."*

Watch the tool-call trace: `channel_summary` → `phase_anomaly` (broad) → a nominal
comparison → `readings_around` the worst segment → `anomaly_overlay_chart` →
finally `anomalies_for` to grade itself. Three servers, one conversation.

## Gotchas (v0.8.7)

- **Resources/prompts** aren't surfaced by LibreChat — expected; use Claude
  Desktop/Code to see them.
- **Tool-calling** must be validated per model; if a
  model emits malformed calls, try `dropParams` on the custom endpoint or switch
  models. Sonnet is the reliable driver.
- **Agent reproducibility** is by **Share**, not export/import (no create API in
  0.8.7).
- If the tool list looks truncated, note v0.8.7 paginates `tools/list` with an
  aggregate budget — 19 tools across three servers is well within it.

## Where to go from here

- Point `trino-mcp` at a second dataset's schema — the agent explores it with no
  changes. Add domain detectors for it as a sibling to `esa-adb`.
- Grow `superset-mcp` with more chart types, or teach the agent to build a full
  investigation dashboard.
- Add MCP **elicitation**/**sampling**, or run the same servers against Claude
  Desktop / Claude Code — the protocol is the point.

That's the workshop: from raw ESA telemetry to an agent that finds hard-to-spot
anomalies and shows you the picture. 🛰️
