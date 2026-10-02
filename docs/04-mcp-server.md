# Step 4 — Build an MCP Server for Trino

We have a telemetry warehouse and a chat UI connected to a model. This step
adds query tools using the Model Context Protocol (MCP), a standard for
exposing tools to clients. Tools are functions with typed inputs and outputs.

## 4.1 — Tool operations and query restrictions

With an MCP server, the model can request data as it works through a question:

- The model selects tools to list tables, inspect schemas, and run queries.
  It can use the results to revise a query or choose another tool.
- The server restricts queries to read-only statements and caps result sizes.
  Its query check rejects statements such as `DROP TABLE`.

## 4.2 — Inspect the MCP server implementation

Open [`mcp-server/server.py`](../mcp-server/server.py), which uses
[FastMCP](https://gofastmcp.com). A minimal example:

```python
from fastmcp import FastMCP

mcp = FastMCP("telemetry-trino")

@mcp.tool
def query(sql: str) -> dict:
    """Run a read-only SQL query against the telemetry warehouse. ..."""
    ...

mcp.run(transport="http", host="0.0.0.0", port=8000)
```

When defining a tool:

1. **Define a function.** FastMCP turns the signature into a JSON
   schema and the docstring into the tool description.
2. **Describe its intended use.** The model reads the docstring to decide when
   and how to call your tool. `query`'s docstring tells the model to aggregate rather
   than pull raw rows. Check how it uses that guidance.
3. **Choose the scope.** `channel_summary` runs a fixed SQL statement, while
   `query` lets the model write SQL. A fixed query reduces opportunities for
   SQL errors; a general query tool supports more questions. Compare how the
   model uses each.

## 4.3 — Start and connect the MCP server

### 4.3.1 — Start the server

```bash
task up:mcp        # builds and starts the server, registers it in LibreChat
```

### 4.3.2 — Enable the server in LibreChat

LibreChat discovers the server through `librechat/librechat.yaml`:

```yaml
mcpServers:
  telemetry:
    type: streamable-http
    url: http://mcp-server:8000/mcp
```

Reload LibreChat (`docker compose restart librechat`), open a new chat, and
enable the **telemetry** MCP server in the tools menu.

## 4.4 — Query the warehouse through chat

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
describe schemas, and revise SQL. Inspect the queries and their results.

## 4.5 — Extend and review the tools

### 4.5.1 — Add a channel-list tool

Add a `list_channels()` tool that returns distinct channel names and their
sample counts. Restart the server and check how the model uses it.

### 4.5.2 — Add an anomaly-window tool

The `labels` and `anomaly_types` tables and the `labeled_readings` view are
already in the warehouse (Step 2). Add an `anomalies_for(channel)` tool that
returns a channel's anomaly windows and their categories, so the model can
call it instead of writing the join each time. Then ask the model to investigate
an anomaly: what did the channel do in the hour around it?

### 4.5.3 — Review the query restrictions

Read the read-only check in `query` and consider what else a production server
would need, such as row-level authorization, query timeouts, and cost caps.

## 4.6 — Additional MCP uses (optional)

- Point the MCP server at your own mission's data lake.
- Add MCP **resources** (read-only context like schema docs) and **prompts**
  (reusable analysis workflows). FastMCP supports both.
- Run the same server against Claude Desktop, Claude Code, or any other MCP
  client.
