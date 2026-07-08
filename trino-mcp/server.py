"""Generic, dataset-agnostic MCP server over Trino.

Read-only exploration of ANY Trino catalog/schema — no ESA/telemetry specifics
live here. Pair it with a domain server (e.g. esa-adb) that adds dataset-aware
tools and analysis. This is the reusable "data access" layer of the stack.
"""
import os
import re

import trino
from fastmcp import FastMCP

TRINO_HOST = os.environ.get("TRINO_HOST", "localhost")
TRINO_PORT = int(os.environ.get("TRINO_PORT", "8080"))
TRINO_CATALOG = os.environ.get("TRINO_CATALOG", "iceberg")
MAX_ROWS = int(os.environ.get("MAX_ROWS", "1000"))

mcp = FastMCP("trino")

_IDENT = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")


def _ident(name: str) -> str:
    if not _IDENT.fullmatch(name):
        raise ValueError(f"invalid identifier: {name!r}")
    return name


def _run(sql: str) -> dict:
    with trino.dbapi.connect(host=TRINO_HOST, port=TRINO_PORT, user="mcp",
                             catalog=TRINO_CATALOG) as conn:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(MAX_ROWS)
        return {"columns": cols, "rows": [list(r) for r in rows],
                "row_count": len(rows), "truncated": len(rows) == MAX_ROWS}


@mcp.tool
def list_schemas(catalog: str | None = None) -> dict:
    """List the schemas in a Trino catalog (defaults to the configured catalog)."""
    cat = _ident(catalog) if catalog else TRINO_CATALOG
    return _run(f"SHOW SCHEMAS FROM {cat}")


@mcp.tool
def list_tables(schema: str, catalog: str | None = None) -> dict:
    """List the tables and views in a schema."""
    cat = _ident(catalog) if catalog else TRINO_CATALOG
    return _run(f"SHOW TABLES FROM {cat}.{_ident(schema)}")


@mcp.tool
def describe_table(schema: str, table: str, catalog: str | None = None) -> dict:
    """Show a table's columns and types."""
    cat = _ident(catalog) if catalog else TRINO_CATALOG
    return _run(f"DESCRIBE {cat}.{_ident(schema)}.{_ident(table)}")


@mcp.tool
def query(sql: str) -> dict:
    """Run a read-only SQL query (SELECT/SHOW/DESCRIBE/WITH), capped at MAX_ROWS.

    Fully-qualify tables as catalog.schema.table. Prefer aggregation
    (GROUP BY, count, avg) over pulling raw rows.
    """
    if not re.match(r"^\s*(select|show|describe|with)\b", sql, re.IGNORECASE):
        raise ValueError("Only read-only queries (SELECT/SHOW/DESCRIBE/WITH) are allowed.")
    return _run(sql)


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host=os.environ.get("MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("MCP_PORT", "8000")),
        # No-auth workshop on a trusted compose network — see esa-adb server.
        host_origin_protection=False,
    )
