"""superset-mcp: a do-what-I-mean visualization server over Apache Superset.

The agent states visualization INTENT with plain arguments; this server hides
the Superset REST API entirely — auth (JWT + CSRF + session), dataset
registration, and the verbose, version-specific chart `params`/`query_context`
that Superset actually requires — and hands back a clickable chart or dashboard
URL. The agent never constructs Superset form-data.
"""
import json
import os

import requests
from fastmcp import FastMCP

BASE = os.environ.get("SUPERSET_URL", "http://superset:8088")
USER = os.environ.get("SUPERSET_USER", "admin")
PW = os.environ.get("SUPERSET_PASSWORD", "admin")
DB_NAME = os.environ.get("SUPERSET_DB_NAME", "Trino (Iceberg telemetry)")
PUBLIC_URL = os.environ.get("SUPERSET_PUBLIC_URL", "http://localhost:8088")
DEFAULT_SCHEMA = os.environ.get("SUPERSET_SCHEMA", "esa_adb")

mcp = FastMCP("superset")


# ── Superset REST client (auth + CSRF + session live here, once) ─────────────
class Superset:
    def __init__(self):
        self._s: requests.Session | None = None

    def _session(self) -> requests.Session:
        if self._s is not None:
            return self._s
        s = requests.Session()
        s.headers["Referer"] = BASE  # Superset CSRF checks same-origin Referer
        tok = s.post(f"{BASE}/api/v1/security/login",
                     json={"username": USER, "password": PW,
                           "provider": "db", "refresh": True},
                     timeout=30).json()["access_token"]
        s.headers["Authorization"] = f"Bearer {tok}"
        s.headers["X-CSRFToken"] = s.get(
            f"{BASE}/api/v1/security/csrf_token/", timeout=30).json()["result"]
        self._s = s
        return s

    def get(self, path):
        r = self._session().get(BASE + path, timeout=60)
        r.raise_for_status()
        return r.json()

    def post(self, path, body):
        r = self._session().post(BASE + path, json=body, timeout=60)
        if not r.ok:
            raise RuntimeError(f"POST {path} -> {r.status_code}: {r.text[:400]}")
        return r.json()

    def put(self, path, body):
        r = self._session().put(BASE + path, json=body, timeout=60)
        if not r.ok:
            raise RuntimeError(f"PUT {path} -> {r.status_code}: {r.text[:400]}")
        return r.json()


sup = Superset()


def _db_id() -> int:
    for d in sup.get("/api/v1/database/?q=(page_size:100)")["result"]:
        if d["database_name"] == DB_NAME:
            return d["id"]
    raise RuntimeError(f"Superset database {DB_NAME!r} not found")


def _find_dataset(schema: str, table: str):
    for r in sup.get("/api/v1/dataset/?q=(page_size:100)")["result"]:
        if r["table_name"] == table and r.get("schema") == schema:
            return r["id"]
    return None


def _adhoc_metric(column: str, aggregate: str) -> dict:
    agg = aggregate.upper()
    return {"expressionType": "SIMPLE", "column": {"column_name": column},
            "aggregate": agg, "label": f"{agg}({column})"}


def _build_timeseries(dataset_id, time_col, metric, groupby, filters, time_grain):
    """Return (form_data, query_context) for an echarts time-series line chart —
    the part of Superset that's genuinely painful to get right."""
    adhoc_filters = [{"expressionType": "SIMPLE", "subject": c, "operator": "==",
                      "comparator": v, "clause": "WHERE"} for c, v in filters]
    fd = {
        "datasource": f"{dataset_id}__table",
        "viz_type": "echarts_timeseries_line",
        "x_axis": time_col,
        "time_grain_sqla": time_grain,
        "metrics": [metric],
        "groupby": groupby,
        "adhoc_filters": adhoc_filters,
        "row_limit": 10000,
        "x_axis_sort_asc": True,
        "truncate_metric": True,
    }
    qc = {
        "datasource": {"id": dataset_id, "type": "table"},
        "force": False,
        "queries": [{
            "columns": [{"columnType": "BASE_AXIS", "sqlExpression": time_col,
                         "label": time_col, "expressionType": "SQL",
                         "timeGrain": time_grain}] + list(groupby),
            "metrics": [metric],
            "series_columns": list(groupby),
            "orderby": [],
            "row_limit": 10000,
            "filters": [{"col": c, "op": "==", "val": v} for c, v in filters],
            "extras": {"time_grain_sqla": time_grain} if time_grain else {},
            "annotation_layers": [],
        }],
        "form_data": fd,
        "result_type": "full",
        "result_format": "json",
    }
    return fd, qc


def _create_timeseries(dataset_id, time_col, metric_column, aggregate,
                       dimension, filter_column, filter_value, time_grain, title):
    metric = _adhoc_metric(metric_column, aggregate)
    groupby = [dimension] if dimension else []
    filters = [(filter_column, filter_value)] if filter_column and filter_value is not None else []
    name = title or f"{aggregate}({metric_column}) over {time_col}"
    fd, qc = _build_timeseries(dataset_id, time_col, metric, groupby, filters, time_grain)
    res = sup.post("/api/v1/chart/", {
        "slice_name": name, "viz_type": "echarts_timeseries_line",
        "datasource_id": dataset_id, "datasource_type": "table",
        "params": json.dumps(fd), "query_context": json.dumps(qc),
    })
    cid = res["id"]
    return {"chart_id": cid, "name": name,
            "url": f"{PUBLIC_URL}/explore/?slice_id={cid}"}


def _stack_layout(charts: list[dict]) -> dict:
    """Minimal dashboard position_json: each chart in its own full-width row."""
    pos = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [],
                    "parents": ["ROOT_ID"]},
    }
    for i, ch in enumerate(charts, 1):
        row, comp = f"ROW-{i}", f"CHART-{i}"
        pos["GRID_ID"]["children"].append(row)
        pos[row] = {"type": "ROW", "id": row, "children": [comp],
                    "meta": {"background": "BACKGROUND_TRANSPARENT"},
                    "parents": ["ROOT_ID", "GRID_ID"]}
        pos[comp] = {"type": "CHART", "id": comp, "children": [],
                     "meta": {"chartId": ch["chart_id"], "width": 12, "height": 50,
                              "sliceName": ch.get("name", "")},
                     "parents": ["ROOT_ID", "GRID_ID", row]}
    return pos


# ── Intent tools ─────────────────────────────────────────────────────────────
@mcp.tool
def list_datasets() -> dict:
    """List the datasets that can be charted (id + schema.table)."""
    return {"datasets": [{"id": r["id"], "name": f"{r.get('schema')}.{r['table_name']}"}
                         for r in sup.get("/api/v1/dataset/?q=(page_size:100)")["result"]]}


@mcp.tool
def ensure_dataset(table: str, schema: str | None = None) -> dict:
    """Make a Trino table/view chartable in Superset (idempotent).

    Returns its dataset id — pass that id to the chart tools. Use this to chart a
    view like 'labeled_readings' that isn't registered yet.
    """
    schema = schema or DEFAULT_SCHEMA
    existing = _find_dataset(schema, table)
    if existing:
        return {"dataset_id": existing, "created": False, "table": f"{schema}.{table}"}
    ds = sup.post("/api/v1/dataset/",
                  {"database": _db_id(), "schema": schema, "table_name": table})
    return {"dataset_id": ds["id"], "created": True, "table": f"{schema}.{table}"}


@mcp.tool
def timeseries_chart(dataset_id: int, time_col: str = "ts",
                     metric_column: str = "value", aggregate: str = "AVG",
                     dimension: str | None = None,
                     filter_column: str | None = None,
                     filter_value: str | None = None,
                     time_grain: str | None = "P1D",
                     title: str | None = None) -> dict:
    """Create a time-series line chart and return its Superset URL.

    Aggregate `metric_column` (default AVG(value)) over `time_col` at `time_grain`
    (ISO-8601 duration, e.g. 'PT1H', 'P1D'); optionally split series by
    `dimension` and filter with `filter_column`=`filter_value`. Get a dataset_id
    from list_datasets/ensure_dataset.
    """
    return _create_timeseries(dataset_id, time_col, metric_column, aggregate,
                              dimension, filter_column, filter_value, time_grain, title)


@mcp.tool
def anomaly_overlay_chart(channel: str, time_grain: str | None = "PT1H") -> dict:
    """The payoff visualization: a channel's value over time, split by whether
    each point falls inside a labeled anomaly (is_anomaly).

    Ensures the labeled_readings view is registered, filters to `channel`, and
    splits the series by is_anomaly so anomalous stretches stand out. Returns the
    chart URL.
    """
    ds = ensure_dataset("labeled_readings")["dataset_id"]
    return _create_timeseries(ds, "ts", "value", "AVG", "is_anomaly",
                              "channel", channel, time_grain,
                              f"{channel}: value over time by is_anomaly")


@mcp.tool
def add_to_dashboard(chart_ids: list[int], title: str) -> dict:
    """Create a dashboard titled `title` holding the given charts (stacked
    full-width) and return its URL."""
    charts = []
    for cid in chart_ids:
        meta = sup.get(f"/api/v1/chart/{cid}")["result"]
        charts.append({"chart_id": cid, "name": meta.get("slice_name", "")})
    dash = sup.post("/api/v1/dashboard/", {"dashboard_title": title})
    did = dash["id"]
    sup.put(f"/api/v1/dashboard/{did}",
            {"position_json": json.dumps(_stack_layout(charts))})
    for cid in chart_ids:
        sup.put(f"/api/v1/chart/{cid}", {"dashboards": [did]})
    return {"dashboard_id": did, "url": f"{PUBLIC_URL}/superset/dashboard/{did}/"}


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host=os.environ.get("MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("MCP_PORT", "8000")),
        host_origin_protection=False,
    )
