"""A small MCP server that lets an LLM explore and query satellite telemetry in Trino.

Every tool below becomes a capability the model can invoke. The docstrings matter:
they are sent to the model as the tool descriptions, so write them for the model,
not for humans reading the code.

Run locally:   uv run server.py            (HTTP transport on :8000)
Run in stack:  docker compose up mcp-server
"""

import os
import re

import trino
from fastmcp import FastMCP

TRINO_HOST = os.environ.get("TRINO_HOST", "localhost")
TRINO_PORT = int(os.environ.get("TRINO_PORT", "8080"))
TRINO_CATALOG = os.environ.get("TRINO_CATALOG", "iceberg")
TRINO_SCHEMA = os.environ.get("TRINO_SCHEMA", "telemetry")
MAX_ROWS = int(os.environ.get("MAX_ROWS", "500"))

mcp = FastMCP("telemetry-trino")


def _connect() -> trino.dbapi.Connection:
    return trino.dbapi.connect(
        host=TRINO_HOST,
        port=TRINO_PORT,
        user="mcp",
        catalog=TRINO_CATALOG,
        schema=TRINO_SCHEMA,
    )


def _run(sql: str, params: list | None = None) -> dict:
    """Execute a statement and return columns + rows, capped at MAX_ROWS."""
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, params or [])
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(MAX_ROWS)
        return {
            "columns": columns,
            "rows": [list(r) for r in rows],
            "row_count": len(rows),
            "truncated": len(rows) == MAX_ROWS,
        }


@mcp.tool
def list_tables() -> dict:
    """List the telemetry tables available in the Iceberg catalog."""
    return _run(f"SHOW TABLES FROM {TRINO_CATALOG}.{TRINO_SCHEMA}")


@mcp.tool
def describe_table(table: str) -> dict:
    """Show the columns and types of a telemetry table.

    Args:
        table: A table name returned by list_tables, e.g. 'readings'.
    """
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", table):
        raise ValueError(f"invalid table name: {table!r}")
    return _run(f"DESCRIBE {TRINO_CATALOG}.{TRINO_SCHEMA}.{table}")


@mcp.tool
def query(sql: str) -> dict:
    """Run a read-only SQL query against the telemetry warehouse.

    Only SELECT statements are allowed. Results are capped at 500 rows, so
    aggregate (GROUP BY, avg, min, max, count) instead of pulling raw rows
    whenever possible. Timestamps are UTC.

    Example:
        SELECT channel, count(*) AS n, avg(value) AS mean
        FROM readings
        WHERE ts BETWEEN TIMESTAMP '2000-03-01' AND TIMESTAMP '2000-04-01'
        GROUP BY channel
        ORDER BY n DESC
    """
    if not re.match(r"^\s*(select|show|describe|with)\b", sql, re.IGNORECASE):
        raise ValueError("Only read-only queries (SELECT/SHOW/DESCRIBE/WITH) are allowed.")
    return _run(sql)


@mcp.tool
def channel_summary(channel: str) -> dict:
    """Summarize one telemetry channel: time range, sample count, and value statistics.

    A purpose-built tool like this is often more reliable than asking the model
    to write the equivalent SQL itself — that trade-off is the point of Step 4.

    Args:
        channel: Channel name, e.g. 'channel_41'.
    """
    return _run(
        """
        SELECT
            count(*)   AS samples,
            min(ts)    AS first_sample,
            max(ts)    AS last_sample,
            min(value) AS min_value,
            max(value) AS max_value,
            avg(value) AS mean_value,
            stddev(value) AS stddev_value
        FROM readings
        WHERE channel = ?
        """,
        [channel],
    )


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host=os.environ.get("MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("MCP_PORT", "8000")),
    )
