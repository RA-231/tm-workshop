"""A small MCP server that lets an LLM explore and query satellite telemetry in Trino.

Every tool below becomes a capability the model can invoke. The docstrings matter:
they are sent to the model as the tool descriptions, so write them for the model,
not for humans reading the code.

Run locally:   uv run server.py            (HTTP transport on :8000)
Run in stack:  docker compose up mcp-server
"""

import os

import trino
from fastmcp import FastMCP

import analysis

TRINO_HOST = os.environ.get("TRINO_HOST", "localhost")
TRINO_PORT = int(os.environ.get("TRINO_PORT", "8080"))
TRINO_CATALOG = os.environ.get("TRINO_CATALOG", "iceberg")
TRINO_SCHEMA = os.environ.get("TRINO_SCHEMA", "esa_adb")
MAX_ROWS = int(os.environ.get("MAX_ROWS", "500"))
# Analysis tools compute server-side and return only scores, so they can pull a
# far larger window than the row-capped `query` tool without touching the chat.
ANALYSIS_MAX_ROWS = int(os.environ.get("ANALYSIS_MAX_ROWS", "200000"))

mcp = FastMCP("esa-adb")


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


def _fetch_series(channel: str, start: str, end: str):
    """Pull an ordered (timestamps, values) series for a channel window straight
    from Trino. Capped at ANALYSIS_MAX_ROWS — big enough for whole-window
    analysis, and only the computed SCORES ever leave this process (the raw
    arrays never enter the chat)."""
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT to_iso8601(ts), value FROM readings "
            "WHERE channel = ? AND ts BETWEEN CAST(? AS timestamp(6)) "
            "AND CAST(? AS timestamp(6)) ORDER BY ts",
            [channel, start, end],
        )
        rows = cur.fetchmany(ANALYSIS_MAX_ROWS)
    return [r[0] for r in rows], [float(r[1]) for r in rows]


# Generic Trino access (query / list_tables / describe_table) now lives in the
# separate `trino-mcp` server. This server is domain-only: ESA-ADB navigation,
# the phase-aware detectors, and the dataset resources/prompts.


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


@mcp.tool
def list_channels() -> dict:
    """List every telemetry channel with what it measures and its coverage.

    One row per channel: the channel name, its subsystem / physical unit /
    target (from the channel catalog), how many samples it has, and the time
    span covered. Use this first to decide which channel to look at.
    """
    return _run(
        """
        SELECT
            r.channel,
            c.subsystem,
            c.physical_unit,
            c.target,
            count(*)  AS samples,
            min(r.ts) AS first_sample,
            max(r.ts) AS last_sample
        FROM readings r
        LEFT JOIN channels c ON c.channel = r.channel
        GROUP BY r.channel, c.subsystem, c.physical_unit, c.target
        ORDER BY r.channel
        """
    )


@mcp.tool
def readings_around(channel: str, timestamp: str, minutes: int = 60) -> dict:
    """Return the raw signal (ts, value) for a channel in a window around a time.

    This is the unlabeled signal itself — use it to inspect what a channel was
    doing and judge for yourself whether the behavior looks anomalous. It does
    NOT tell you whether the window is labeled as an anomaly.

    Args:
        channel: Channel name, e.g. 'channel_41'.
        timestamp: Center of the window, UTC, 'YYYY-MM-DD HH:MM:SS'
            (an ISO 'T'/'Z' form is also accepted).
        minutes: Half-width of the window in minutes (default 60, max 1440).
    """
    minutes = max(1, min(int(minutes), 1440))
    center = timestamp.replace("T", " ").replace("Z", "").strip()
    return _run(
        """
        SELECT ts, value
        FROM readings
        WHERE channel = ?
          AND ts BETWEEN date_add('minute', ?, CAST(? AS timestamp(6)))
                     AND date_add('minute', ?, CAST(? AS timestamp(6)))
        ORDER BY ts
        """,
        [channel, -minutes, center, minutes, center],
    )


@mcp.tool
def anomalies_for(channel: str) -> dict:
    """GROUND TRUTH: the human-labeled anomaly windows for a channel.

    This returns the dataset's *answer key* — the ESA-labeled anomaly windows
    and their taxonomy (category, class, subclass, locality, ...). Use it to
    investigate a known anomaly or to score detections after the fact. Do NOT
    consult it when the task is to detect anomalies yourself: that is reading
    the answers. For unbiased detection, use channel_summary, readings_around,
    and query over the raw `readings` instead.

    Args:
        channel: Channel name, e.g. 'channel_41'.
    """
    return _run(
        """
        SELECT id, start_time, end_time, category, class_name, subclass,
               dimensionality, locality, length
        FROM anomalies
        WHERE channel = ?
        ORDER BY start_time
        """,
        [channel],
    )


@mcp.tool
def phase_anomaly(channel: str, start: str, end: str,
                  sibling_channels: list[str] | None = None) -> dict:
    """Phase-aware anomaly SCORES for a channel over a time window.

    These channels are quantized 'staircase' signals, so raw-value thresholds
    miss a lot. This decomposes the window into (level, dwell-duration) segments
    and scores unusual levels, unusual dwell durations, and unusual transitions.
    Returns numbers (higher = more anomalous) plus the worst segments with their
    timestamps. There is NO fixed threshold — decide what counts as an alarm by
    comparing a suspect window against a known-nominal one. Runs against the full
    window in Trino; only the scores come back.

    Args:
        channel: e.g. 'channel_41'.
        start, end: UTC window bounds, 'YYYY-MM-DD HH:MM:SS'.
        sibling_channels: optional related channels (e.g. same group) — each adds
            a Pearson correlation for multivariate context.
    """
    ts, vals = _fetch_series(channel, start, end)
    sibs = []
    for sc in (sibling_channels or []):
        s_ts, s_vals = _fetch_series(sc, start, end)
        sibs.append({"name": sc, "timestamps": s_ts, "values": s_vals})
    return analysis.phase_anomaly_score(ts, vals, sibling_series=sibs or None)


@mcp.tool
def plateau(channel: str, start: str, end: str) -> dict:
    """Score how 'stuck' a channel is over a window (abnormally long flat runs).

    Returns the longest plateau and plateau_score = longest_run / median_run
    (higher = more stuck). Scores only; you set the alarm threshold.
    """
    ts, vals = _fetch_series(channel, start, end)
    return analysis.plateau_score(ts, vals)


@mcp.tool
def data_gaps(channel: str, start: str, end: str) -> dict:
    """Score sampling regularity and data gaps over a window.

    Returns the dominant sample interval, the worst gap, the gap fraction, and
    gap_score = max_gap / dominant_dt. Scores only; you decide what is alarming.
    """
    ts, vals = _fetch_series(channel, start, end)
    return analysis.gap_analysis(ts)


@mcp.tool
def stl_residual(channel: str, start: str, end: str,
                 period_samples: int | None = None) -> dict:
    """STL-style trend/seasonal residual SCORES for a channel over a window.

    Resamples, removes trend (and an optional seasonal cycle of period_samples),
    and robust-z-scores the residual. High max_resid_z / stl_score flags points
    that departed the channel's own trend/season. Scores only — you set the
    threshold by comparing against a nominal window.
    """
    ts, vals = _fetch_series(channel, start, end)
    return analysis.stl_residual_score(ts, vals, period=period_samples)


@mcp.tool
def cadence(channel: str, start: str, end: str) -> dict:
    """Score sampling regularity over a window: jitter, drift, and
    cadence_irregularity (higher = less steady). Complements data_gaps, which
    finds dropouts rather than measuring steadiness. Scores only.
    """
    ts, vals = _fetch_series(channel, start, end)
    return analysis.cadence_score(ts)


@mcp.tool
def cross_correlation(channel: str, start: str, end: str,
                      sibling_channels: list[str]) -> dict:
    """Score how well a channel moves with its sibling channels over a window.

    Returns each sibling's Pearson and best *lagged* correlation, plus a
    decorrelation_score (higher = this channel moved independently of its group,
    often suspicious). Pass siblings from the same group (see list_channels).
    Scores only.
    """
    ts, vals = _fetch_series(channel, start, end)
    sibs = []
    for sc in (sibling_channels or []):
        s_ts, s_vals = _fetch_series(sc, start, end)
        sibs.append({"name": sc, "timestamps": s_ts, "values": s_vals})
    return analysis.cross_channel_correlation(ts, vals, sibs)


# ── Resources: read-only reference context (the MCP "resources" primitive) ────
# LibreChat v0.8.7 renders tools only, so these are ignored there — but they are
# first-class in Claude Desktop / Claude Code, and they make the server
# protocol-complete. Same server, richer in a protocol-complete client.
@mcp.resource("about://dataset")
def about_dataset() -> str:
    """Briefing on the ESA-ADB telemetry — what it is, how it's anonymized, and
    how to reason about it. Read this first."""
    return (
        "ESA Anomaly Dataset (ESA-ADB), Mission1 subset -- real, anonymized ESA\n"
        "satellite telemetry.\n\n"
        "- Channels are ANONYMIZED, quantized 'staircase' signals: the value\n"
        "  dwells at a discrete level, then steps. Names/units/subsystems are\n"
        "  placeholders (channel_N, physical_unit_N, subsystem_N) with NO public\n"
        "  key -- reason from the signal, not the names.\n"
        "- Metadata: target=YES channels are monitored for anomalies; channels\n"
        "  sharing a group are related and comparable; physical_unit groups\n"
        "  comparable quantities; categorical flags discrete signals.\n"
        "- Detection: value-only thresholds are weak here. Decompose the signal\n"
        "  into (level, dwell-duration) segments and reason about PHASE and\n"
        "  DURATION.\n"
        "- Anomaly categories: Anomaly (alarm), Rare Event (rare-but-nominal,\n"
        "  don't alarm after first sighting), Communication Gap, Invalid segment.\n"
        "- DISCIPLINE: anomalies_for is the human-labeled ANSWER KEY. Don't\n"
        "  consult it while detecting; use it only to grade findings afterward."
    )


@mcp.resource("schema://esa_adb")
def schema_resource() -> str:
    """The warehouse data dictionary: every table/view and its columns."""
    tables = _run(f"SHOW TABLES FROM {TRINO_CATALOG}.{TRINO_SCHEMA}")["rows"]
    lines = [f"catalog {TRINO_CATALOG}, schema {TRINO_SCHEMA}", ""]
    for (t,) in tables:
        cols = _run(f"DESCRIBE {TRINO_CATALOG}.{TRINO_SCHEMA}.{t}")["rows"]
        lines.append(f"- {t}(" + ", ".join(f"{c[0]} {c[1]}" for c in cols) + ")")
    return "\n".join(lines)


@mcp.resource("catalog://channels")
def channels_catalog() -> str:
    """The channel catalog: channel + subsystem / unit / group / target flags."""
    r = _run("SELECT channel, subsystem, physical_unit, group_name, target, "
             "categorical FROM channels ORDER BY channel")
    header = " | ".join(r["columns"])
    body = "\n".join(" | ".join(str(x) for x in row) for row in r["rows"])
    return f"{header}\n{body}"


# ── Prompts: canned, parameterized workflows (the MCP "prompts" primitive) ────
@mcp.prompt
def investigate_channel(channel: str) -> str:
    """Kick off a disciplined anomaly investigation of one channel."""
    return (
        f"Investigate {channel} for anomalies using the telemetry tools.\n"
        f"1. Orient: channel_summary({channel}); note its time span.\n"
        f"2. Scan a broad window with phase_anomaly, plateau, data_gaps,\n"
        f"   stl_residual, cadence. Scores are relative -- they mean nothing\n"
        f"   in isolation.\n"
        f"3. Calibrate: score a quiet window from {channel} and compare.\n"
        f"4. Zoom: readings_around the worst segment; describe what happened.\n"
        f"5. Corroborate: cross_correlation({channel}, siblings from its group).\n"
        f"6. ONLY after committing to a ranked list, call anomalies_for({channel})\n"
        f"   to grade yourself (hits / misses / false alarms).\n"
        f"Report each finding with its time window, the scores that flagged it vs\n"
        f"the nominal comparison, and a phase+duration explanation."
    )


@mcp.prompt
def triage_window(channel: str, start: str, end: str) -> str:
    """Run the full detector suite on one window and summarize vs a baseline."""
    return (
        f"Triage {channel} from {start} to {end}. Run phase_anomaly, plateau,\n"
        f"data_gaps, stl_residual, and cadence on that window, then the same\n"
        f"detectors on an equally long quiet window from {channel} as a baseline.\n"
        f"Summarize which detectors fired, by how much vs baseline, and your best\n"
        f"explanation of the behavior. Do not use anomalies_for."
    )


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host=os.environ.get("MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("MCP_PORT", "8000")),
        # MCP's streamable-http transport does DNS-rebinding protection: by
        # default it only accepts "localhost"/"127.0.0.1" in the Host header and
        # returns 421 Misdirected Request otherwise. LibreChat reaches us over
        # the compose network as http://mcp-server:8000, so that guard blocks it
        # ("Failed to Initialize MCP server"). This is a no-auth workshop on a
        # trusted local network, so we disable the Host/Origin guard -- which
        # also keeps the published :8000 port open for other experiments.
        host_origin_protection=False,
    )
