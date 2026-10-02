# Step 5 — A Telemetry Analysis Agent

We have a lakehouse (Steps 1–2), a chat UI connected to the gateway (Step 3),
and query tools exposed through MCP (Step 4). Now we'll configure a
**LibreChat Agent** with tools to explore telemetry, score possible anomalies,
and create charts. The model selects tools as it works through an investigation.

## 5.1 — Analysis agent architecture

An agent using a tool-calling model and **three MCP servers**:

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

Each server has a separate role. `trino-mcp` provides SQL access without
depending on the ESA dataset. `esa-adb` provides telemetry navigation and
phase-aware detectors. `superset-mcp` creates charts. This lets other projects
reuse the query and charting servers while supplying their own domain tools.
The agent receives tools from all three servers.

## 5.2 — Start the three MCP servers

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

Two security settings affect connections between containers:

1. **DNS-rebinding Host check.** MCP's streamable-http transport only accepts
   `localhost` in the `Host` header by default and returns `421 Misdirected
   Request` otherwise. Our servers reach each other by compose hostname
   (`http://mcp-server:8000`), so we set `host_origin_protection=False` for
   this local workshop stack.
2. **LibreChat SSRF allowlist.** LibreChat v0.8.7 blocks MCP URLs that resolve to
   private IPs unless their domain is allow-listed — hence
   `mcpSettings.allowedDomains: [mcp-server, trino-mcp, superset-mcp]`.

## 5.3 — Check the LibreChat agent configuration

Agents are turned on in `librechat.yaml`:

```yaml
interface:
  agents: true
```

The agent endpoint (`endpoints.agents`) also supports `recursionLimit`
(the UI's "Max Agent Steps", default 25) and `capabilities`. We use the defaults.
LibreChat's built-in **Code Interpreter** (`execute_code`) uses a paid, hosted
API. The workshop runs analysis in the local MCP servers to keep it alongside
the data.

## 5.4 — Create the analysis agent (LibreChat v0.8.7)

### 5.4.1 — Open the Agent Builder

Pick **Agents** from the model/endpoint menu, then open the **Agent Builder**
in the side panel.

### 5.4.2 — Name the agent

Set **Name** to `Telemetry Anomaly Analyst`.

### 5.4.3 — Select the tool-calling model

Set **Model** to provider **Workshop Models** → **`workshop-default`**. The other
models in the picker can be used for chat, but not all of them can call tools on
this path; the alias points at one that can.

### 5.4.4 — Paste the investigation instructions

Paste the following prompt into **Instructions**:

```
You are a satellite-telemetry anomaly analyst. You have three MCP tool groups:
trino (generic SQL exploration), esa-adb (telemetry navigation + scored anomaly
detectors), and superset (create charts). Read the about://dataset
resource first if your client exposes it.

The data is anonymized, quantized "staircase" telemetry — raw-value thresholds
are weak; reason about PHASE (which level, in what order) and DURATION (dwell).

Method:
1. Orient: list_channels / channel_summary; note the time span.
2. Detect: run phase_anomaly, plateau, data_gaps, stl_residual, cadence over a
   broad window. Scores are relative — they mean nothing in isolation.
3. Calibrate: score a quiet window from the same channel and compare.
4. Zoom: readings_around the worst segment; describe the observed signal changes.
5. Corroborate: cross_correlation against sibling channels in the same group.
6. Visualize: anomaly_overlay_chart(channel), then add_to_dashboard; return
   the URL so the user can see it.
7. Validate: do not call anomalies_for during detection. After recording your
   findings, compare them with the labels (hits, misses, false alarms).

Report a ranked list: channel, window, the scores that flagged it vs the nominal
comparison, a phase+duration explanation, the chart URL, and your confidence.
```

### 5.4.5 — Enable the MCP tools

Under **Tools → Add Tools**, enable the **esa-adb**, **trino**, and **superset**
MCP servers. Each appears as one entry you can expand to toggle individual tools.

### 5.4.6 — Save and share the agent

Select **Save**. To let attendees reuse the agent, **Share** it to a group or
Public. LibreChat v0.8.7 has no API to create an agent, so sharing lets attendees
use the same configuration.

## 5.5 — Anomaly detector scores

The `esa-adb` server exposes six anomaly detectors that return numeric scores.
The agent compares scores from suspect and nominal windows to decide which
findings to report.

| Tool | What it scores |
|---|---|
| `phase_anomaly` | unusual levels, dwell durations, and transitions |
| `plateau` | abnormally long "stuck" flat runs |
| `data_gaps` | dropouts — worst gap vs the dominant sample interval |
| `stl_residual` | departures from the channel's own trend/season |
| `cadence` | sampling jitter and drift (regularity, not dropouts) |
| `cross_correlation` | decorrelation from sibling channels (multivariate) |

In the labeled March-2000 anomaly, `channel_41` dropped to ~0.64 and stayed
there for ~7.6 hours. That value is within its 0.61–0.98 range, so a range
threshold would not identify it. `phase_anomaly` returns a dwell z-score of
~29, with elevated `plateau` and `data_gaps` scores. The duration of the level
change provides evidence that the value alone does not.

## 5.6 — MCP tools, resources, and prompts

The `esa-adb` server exposes MCP tools, resources, and prompts:

- **Tools** — callable functions for detection and telemetry navigation.
- **Resources** — read-only reference context: `about://dataset` (the
  anonymization briefing), `schema://esa_adb` (data dictionary),
  `catalog://channels` (the channel catalog).
- **Prompts** — reusable, parameterized workflows: `investigate_channel(channel)`,
  `triage_window(channel, start, end)`.

**Client caveat:** LibreChat v0.8.7 consumes **tools only** — it ignores resources
and prompts. Connect a client that supports resources and prompts, such as
**Claude Desktop** or **Claude Code**, to `http://localhost:8000/mcp` to use
those features. How they appear depends on the client.

## 5.7 — Chart creation through MCP

`superset-mcp` accepts chart requests and returns chart URLs:

```
anomaly_overlay_chart("channel_41")
  → { "url": "http://localhost:8088/explore/?slice_id=1" }
```

Behind that one call the server logs into Superset, registers the
`labeled_readings` view as a dataset, and constructs the
`params`/`query_context` for a time-series line split by `is_anomaly`. The agent
uses the chart tool without constructing Superset API payloads.

## 5.8 — Run an anomaly investigation

Open a new chat with the agent and ask:

> *"Investigate channel_41 for anomalies. Work from the signal — don't look at the
> labels until you've committed to your findings, then check yourself. Chart the
> result and give me the link."*

Watch the tool-call trace: `channel_summary` → `phase_anomaly` (broad) → a nominal
comparison → `readings_around` the worst segment → `anomaly_overlay_chart` →
finally `anomalies_for` to compare its findings with the labels.

## 5.9 — Troubleshoot LibreChat (v0.8.7)

- **Resources/prompts** aren't surfaced by LibreChat; use Claude
  Desktop/Code to see them.
- **Tool-calling** must be validated per model; if a
  model emits malformed calls, try `dropParams` on the custom endpoint or switch
  models. Use `workshop-default` for the workshop exercises.
- **Agent sharing** uses **Share**; v0.8.7 has no API to create an agent.
- If the tool list looks truncated, note v0.8.7 paginates `tools/list` with an
  aggregate budget — 19 tools across three servers is well within it.

## 5.10 — Extend the agent (optional)

- Configure `trino-mcp` for another dataset and add a server with detectors
  suited to that data.
- Extend `superset-mcp` with more chart types, or configure the agent to build an
  investigation dashboard.
- Add MCP **elicitation**/**sampling**, or run the same servers against Claude
  Desktop / Claude Code.
