# Step 4 — Build an MCP Server for Trino

We have a warehouse full of telemetry and a chat UI wired to a model. The last
piece is teaching the model to *use* the warehouse. That's what the Model
Context Protocol (MCP) does: it's a standard way to hand an LLM a set of
tools — functions it can call, with typed inputs and outputs.

## Why not just paste SQL results into the chat?

You could. But an MCP server gives the model *agency with guardrails*:

- The model decides **which** tool to call, **when**, and **how often** —
  it can list tables, look at a schema, run a query, notice the answer is
  wrong, and refine. That loop is where the magic is.
- You decide **what's possible**. Our server only permits read-only queries
  and caps result sizes. The model can't `DROP TABLE`, even if asked nicely.

## The server

Open [`mcp-server/server.py`](../mcp-server/server.py). The whole thing is
~150 lines using [FastMCP](https://gofastmcp.com). The essence:

```python
from fastmcp import FastMCP

mcp = FastMCP("telemetry-trino")

@mcp.tool
def query(sql: str) -> dict:
    """Run a read-only SQL query against the telemetry warehouse. ..."""
    ...

mcp.run(transport="http", host="0.0.0.0", port=8000)
```

Three things to internalize:

1. **A tool is just a function.** FastMCP turns the signature into a JSON
   schema and the docstring into the tool description.
2. **Docstrings are prompts.** The model reads them to decide when and how to
   call your tool. `query`'s docstring tells the model to aggregate rather
   than pull raw rows — watch it obey.
3. **Specific beats general.** `channel_summary` does one thing with a fixed,
   correct SQL statement. Compare how the model behaves with it vs. writing
   its own SQL through `query`. Purpose-built tools are more reliable;
   general tools are more flexible. Real MCP server design is choosing that
   mix.

## Run it

```bash
task up:mcp        # builds and starts the server, registers it in LibreChat
```

LibreChat discovers the server through `librechat/librechat.yaml`:

```yaml
mcpServers:
  telemetry:
    type: streamable-http
    url: http://mcp-server:8000/mcp
```

Reload LibreChat (`docker compose restart librechat`), open a new chat, and
enable the **telemetry** MCP server in the tools menu.

## Try it

Ask the model things that require multi-step tool use:

- *"What tables and views are available, and what does the readings table
  look like?"*
- *"Summarize channel_41. Anything unusual about its value range?"*
- *"Which channel has the most samples in March 2000? Show a monthly count
  for that channel across the whole year."*
- *"Using labeled_readings, how many anomaly windows does channel_41 have, and
  what's the average value inside anomalies vs outside?"*
- *"Pick one labeled anomaly on channel_41 and show me the readings in the hour
  around it."*

Watch the tool-call panel in LibreChat: you'll see the model list tables,
describe schemas, and iterate on SQL — the same workflow a human analyst
follows.

## Exercises

1. **Add a tool** `list_channels()` that returns distinct channel names and
   their sample counts. Restart the server and see the model start using it.
2. **Add an anomaly tool.** The `labels` and `anomaly_types` tables and the
   `labeled_readings` view are already in the warehouse (Step 2). Add an
   `anomalies_for(channel)` tool that returns a channel's anomaly windows and
   their categories, so the model reaches for it directly instead of writing
   the join each time. Then ask the model to *investigate* an anomaly: what did
   the channel do in the hour around it?
3. **Break it on purpose.** Remove the read-only check from `query` and ask
   the model to clean up the warehouse. (Kidding. Don't. But do read the
   check and think about what else a production server would need: row-level
   auth, query timeouts, cost caps.)

## Where to go from here

- Point the MCP server at your own mission's data lake.
- Add MCP **resources** (read-only context like schema docs) and **prompts**
  (canned analysis workflows) — FastMCP supports both.
- Run the same server against Claude Desktop, Claude Code, or any other MCP
  client — that's the point of a protocol.
