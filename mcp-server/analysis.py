"""Phase-aware telemetry anomaly detectors for the capstone agent.

Pure functions over raw (timestamps, values) arrays — NO database coupling.
The MCP server's analysis tools pull a window from Trino, call these functions,
and return only the SCORES to the agent; the raw arrays never enter the chat.

Design contract (all four rules matter):
  1. Return SCORES, never boolean flags. The agent decides thresholds.
  2. Inputs are raw arrays: `timestamps` (ISO strings or epoch seconds) and
     `values` (floats). Nothing here knows about Trino/Iceberg.
  3. Phase-awareness is the unlock. The ESA channels are quantized "staircase"
     signals: the value dwells at a discrete level, then steps. Value-only
     detectors drown in that structure. We instead decompose the signal into
     (level, dwell-duration) SEGMENTS and score PHASE (which level, in what
     order) and DURATION (how long each dwell) — not raw value.
  4. Sibling channels are accepted as optional args everywhere plausible, so
     the agent can grow into multivariate reasoning even if unused at first.

Every function returns a JSON-serializable dict of numbers.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

__all__ = ["phase_anomaly_score", "plateau_score", "gap_analysis",
           "stl_residual_score", "cross_channel_correlation", "cadence_score",
           "segment"]


# ── helpers ──────────────────────────────────────────────────────────────────
def _to_epoch(timestamps) -> np.ndarray:
    """Accept ISO-8601 strings ('...T..Z' or '.. ..') or epoch numbers."""
    out = []
    for t in timestamps:
        if isinstance(t, (int, float)):
            out.append(float(t))
            continue
        s = str(t).replace("T", " ").replace("Z", "").strip()
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            dt = datetime.strptime(s[:26], "%Y-%m-%d %H:%M:%S.%f")
        out.append(dt.replace(tzinfo=timezone.utc).timestamp())
    return np.asarray(out, dtype="float64")


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _robust_z(x: np.ndarray):
    """Median/MAD z-scores — resistant to the very outliers we hunt."""
    x = np.asarray(x, dtype="float64")
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med)))
    scale = 1.4826 * mad if mad > 1e-12 else (float(np.std(x)) or 1.0)
    return (x - med) / scale, med, scale


def _infer_level_tol(values: np.ndarray) -> float:
    """A step is a jump bigger than the in-plateau noise. Estimate that noise
    from the small consecutive diffs and set the tolerance a few MADs above it."""
    d = np.abs(np.diff(values))
    nz = d[d > 1e-12]
    if nz.size == 0:
        return 1e-9
    med = float(np.median(nz))
    mad = float(np.median(np.abs(nz - med)))
    return max(med + 5.0 * mad, 1e-9)


def segment(timestamps, values, level_tol: float | None = None) -> list[dict]:
    """Split the signal into constant-level segments (the staircase steps).

    A new segment starts when the value departs the current level by more than
    `level_tol`. Returns one dict per segment with its level, sample span, and
    dwell duration (seconds until the next step). This is the shared primitive
    behind the phase and plateau detectors.
    """
    epoch = _to_epoch(timestamps)
    v = np.asarray(values, dtype="float64")
    n = v.size
    if n == 0:
        return []
    if level_tol is None:
        level_tol = _infer_level_tol(v)

    bounds = [0]
    level = v[0]
    for i in range(1, n):
        if abs(v[i] - level) > level_tol:
            bounds.append(i)
            level = v[i]
        else:
            level = float(np.mean(v[bounds[-1]: i + 1]))
    bounds.append(n)  # sentinel end

    segs = []
    for k in range(len(bounds) - 1):
        s, e = bounds[k], bounds[k + 1] - 1
        start_t = epoch[s]
        # dwell = time from this step to the next step (or end of window)
        nxt = epoch[bounds[k + 1]] if k + 1 < len(bounds) - 1 else epoch[e]
        segs.append(
            {
                "start_idx": int(s),
                "end_idx": int(e),
                "level": float(np.mean(v[s: e + 1])),
                "start_t": float(start_t),
                "end_t": float(epoch[e]),
                "dwell_s": float(max(nxt - start_t, 0.0)),
                "n_samples": int(e - s + 1),
            }
        )
    return segs


# ── detectors ────────────────────────────────────────────────────────────────
def phase_anomaly_score(timestamps, values, sibling_series=None,
                        level_tol: float | None = None, top_k: int = 5) -> dict:
    """Score a channel by PHASE (level/transition rarity) and DURATION (dwell).

    The staircase is decomposed into (level, dwell) segments. Three orthogonal
    score components per segment:
      • dwell_z         — robust z-score of the segment's dwell vs all dwells
      • level_rarity    — how rare this quantized level is in the window
      • transition_rarity — how rare the step into this level is
    The window's `phase_anomaly_score` is the 95th-percentile combined score;
    `worst_segments` lists the top offenders with their timestamps so the agent
    can zoom in. All scores are unitless — the agent sets the alarm threshold.

    `sibling_series`: optional list of {"name","timestamps","values"} for
    related channels; each gets a Pearson correlation on the overlapping window
    (context for multivariate reasoning — low correlation makes a solo step more
    suspicious).
    """
    segs = segment(timestamps, values, level_tol)
    if len(segs) < 2:
        return {"n_segments": len(segs), "phase_anomaly_score": 0.0,
                "note": "too few segments to score phase", "worst_segments": []}

    dwell = np.array([s["dwell_s"] for s in segs])
    levels = np.array([s["level"] for s in segs])
    dwell_z, dwell_med, dwell_scale = _robust_z(dwell)

    # quantize levels to a grid to count level/transition frequencies
    grid = level_tol if level_tol else _infer_level_tol(np.asarray(values, "float64"))
    keys = np.round(levels / max(grid, 1e-9)).astype("int64")
    lvl_freq = {int(k): int(c) for k, c in zip(*np.unique(keys, return_counts=True))}
    n = len(segs)
    level_rarity = np.array([-np.log(lvl_freq[int(k)] / n) for k in keys])

    trans = ["start"] + [f"{keys[i-1]}->{keys[i]}" for i in range(1, n)]
    t_uniq, t_cnt = np.unique(trans, return_counts=True)
    t_freq = {t: int(c) for t, c in zip(t_uniq, t_cnt)}
    transition_rarity = np.array([-np.log(t_freq[t] / n) for t in trans])

    combined = np.abs(dwell_z) + level_rarity + transition_rarity
    order = np.argsort(combined)[::-1][:top_k]
    worst = []
    for i in order:
        s = segs[i]
        worst.append({
            "start": _iso(s["start_t"]), "end": _iso(s["end_t"]),
            "level": round(s["level"], 6), "dwell_s": round(s["dwell_s"], 1),
            "dwell_z": round(float(dwell_z[i]), 2),
            "level_rarity": round(float(level_rarity[i]), 2),
            "transition_rarity": round(float(transition_rarity[i]), 2),
            "combined": round(float(combined[i]), 2),
        })

    sib = []
    if sibling_series:
        base_e = _to_epoch(timestamps)
        base_v = np.asarray(values, "float64")
        for s in sibling_series:
            se = _to_epoch(s["timestamps"])
            sv = np.asarray(s["values"], "float64")
            if se.size >= 2:
                interp = np.interp(base_e, se, sv)
                if np.std(interp) > 1e-12 and np.std(base_v) > 1e-12:
                    corr = float(np.corrcoef(base_v, interp)[0, 1])
                else:
                    corr = 0.0
                sib.append({"name": s.get("name", "sibling"), "pearson_r": round(corr, 3)})

    return {
        "n_segments": n,
        "n_levels": len(lvl_freq),
        "dwell_median_s": round(dwell_med, 1),
        "dwell_mad_scale_s": round(dwell_scale, 1),
        "max_combined_score": round(float(combined.max()), 2),
        "phase_anomaly_score": round(float(np.percentile(combined, 95)), 2),
        "worst_segments": worst,
        "sibling_correlation": sib,
    }


def plateau_score(timestamps, values, level_tol: float | None = None) -> dict:
    """Score how 'stuck' a channel is — abnormally long flat runs.

    A stuck sensor dwells far longer than its typical step cadence. Returns the
    longest plateau (seconds and as a fraction of the window), the count of
    plateaus, and `plateau_score` = longest-run / median-run (how extreme the
    stickiness is). High score ⇒ one run dominates the window.
    """
    segs = segment(timestamps, values, level_tol)
    if not segs:
        return {"n_plateaus": 0, "plateau_score": 0.0}
    dwell = np.array([s["dwell_s"] for s in segs])
    span = float(_to_epoch(timestamps)[-1] - _to_epoch(timestamps)[0]) or 1.0
    longest = float(dwell.max())
    med = float(np.median(dwell)) or 1.0
    idx = int(np.argmax(dwell))
    return {
        "n_plateaus": len(segs),
        "longest_plateau_s": round(longest, 1),
        "longest_plateau_fraction": round(longest / span, 3),
        "median_dwell_s": round(med, 1),
        "plateau_score": round(longest / med, 2),
        "longest_plateau_at": _iso(segs[idx]["start_t"]),
    }


def gap_analysis(timestamps, expected_dt_s: float | None = None) -> dict:
    """Score sampling regularity and data gaps.

    Returns the dominant sample interval, the worst gap (seconds and as a
    multiple of the dominant interval), the fraction of the window lost to gaps,
    and `gap_score` = max_gap / dominant_dt. `expected_dt_s` overrides the
    inferred cadence when the nominal rate is known.
    """
    epoch = _to_epoch(timestamps)
    if epoch.size < 3:
        return {"gap_score": 0.0, "note": "too few points"}
    d = np.diff(epoch)
    dom = float(expected_dt_s or np.median(d))
    dom = dom or 1.0
    max_gap = float(d.max())
    excess = float(np.sum(d[d > 2 * dom] - dom))
    span = float(epoch[-1] - epoch[0]) or 1.0
    idx = int(np.argmax(d))
    return {
        "dominant_dt_s": round(dom, 2),
        "n_samples": int(epoch.size),
        "max_gap_s": round(max_gap, 1),
        "max_gap_ratio": round(max_gap / dom, 1),
        "gap_fraction": round(excess / span, 3),
        "n_gaps_over_2x": int(np.sum(d > 2 * dom)),
        "gap_score": round(max_gap / dom, 2),
        "max_gap_at": _iso(epoch[idx]),
    }


def stl_residual_score(timestamps, values, period: int | None = None,
                       trend_window: int | None = None) -> dict:
    """STL-style trend/seasonal residual scoring on the resampled signal.

    Resamples to a uniform grid at the dominant sample interval, removes a slow
    trend (edge-corrected centered moving average), optionally removes a seasonal
    cycle of `period` samples, and scores the residual with robust (MAD)
    z-scores. High residual z ⇒ the value departed its own trend/season sharply.
    `period`/`trend_window` are in SAMPLES of the resampled grid; omit `period`
    for trend-only detrending. stl_score = max residual z.
    """
    epoch = _to_epoch(timestamps)
    v = np.asarray(values, dtype="float64")
    if epoch.size < 8:
        return {"stl_score": 0.0, "note": "too few points"}
    dt = float(np.median(np.diff(epoch))) or 1.0
    grid = np.arange(epoch[0], epoch[-1] + dt, dt)
    y = np.interp(grid, epoch, v)
    n = y.size
    if trend_window is None:
        trend_window = max(5, (n // 10) | 1)  # odd, ~10% of the window
    if trend_window % 2 == 0:
        trend_window += 1
    ones = np.ones(min(trend_window, n if n % 2 else n - 1))
    counts = np.convolve(np.ones(n), ones, mode="same")
    trend = np.convolve(y, ones, mode="same") / counts  # edge-corrected MA
    detr = y - trend
    seasonal = np.zeros_like(detr)
    if period and 2 <= period < n // 2:
        for p in range(period):
            idx = np.arange(p, n, period)
            seasonal[idx] = np.mean(detr[idx])
        seasonal -= np.mean(seasonal)
    z, _, scale = _robust_z(detr - seasonal)
    az = np.abs(z)
    worst = int(np.argmax(az))
    return {
        "n_resampled": int(n),
        "resampled_dt_s": round(dt, 2),
        "trend_window_samples": int(ones.size),
        "period_samples": int(period) if period else 0,
        "resid_scale": round(float(scale), 6),
        "max_resid_z": round(float(az.max()), 2),
        "n_over_3sigma": int(np.sum(az > 3)),
        "frac_over_3sigma": round(float(np.mean(az > 3)), 4),
        "worst_at": _iso(grid[worst]),
        "stl_score": round(float(az.max()), 2),
    }


def cadence_score(timestamps, expected_dt_s: float | None = None) -> dict:
    """Score sampling regularity: jitter and drift of the inter-sample interval.

    Distinct from gap_analysis (which finds big dropouts) — this measures how
    *steady* the cadence is. Returns the dominant interval, jitter (robust spread
    of intervals / dominant), drift (second-half vs first-half median interval),
    the fraction of intervals within 10% of dominant, and cadence_irregularity =
    jitter + |drift - 1|. Higher ⇒ less regular.
    """
    epoch = _to_epoch(timestamps)
    if epoch.size < 4:
        return {"cadence_irregularity": 0.0, "note": "too few points"}
    d = np.diff(epoch)
    dom = float(expected_dt_s or np.median(d)) or 1.0
    scale = 1.4826 * float(np.median(np.abs(d - np.median(d))))
    jitter = scale / dom
    half = d.size // 2
    drift = (float(np.median(d[half:])) / dom) if half else 1.0
    frac_regular = float(np.mean(np.abs(d - dom) <= 0.1 * dom))
    return {
        "dominant_dt_s": round(dom, 2),
        "n_intervals": int(d.size),
        "jitter": round(jitter, 4),
        "drift_ratio": round(drift, 3),
        "frac_within_10pct": round(frac_regular, 4),
        "cadence_irregularity": round(jitter + abs(drift - 1.0), 4),
    }


def cross_channel_correlation(timestamps, values, sibling_series,
                              max_lag_s: float | None = None) -> dict:
    """Score how well a channel moves with its sibling channels.

    For each sibling, interpolate onto this channel's timestamps and compute the
    Pearson correlation plus the best *lagged* correlation (searching ±max_lag_s).
    A channel that normally tracks its group but decorrelates in a window is
    suspicious. Returns per-sibling {pearson_r, best_lag_s, best_lag_r} and
    decorrelation_score = 1 - max|best_lag_r| over siblings (high ⇒ this channel
    moves independently of its group).
    """
    base_e = _to_epoch(timestamps)
    base_v = np.asarray(values, dtype="float64")
    if not sibling_series or base_e.size < 8 or np.std(base_v) < 1e-12:
        return {"decorrelation_score": 0.0, "siblings": [],
                "note": "need siblings and a varying signal"}
    dt = float(np.median(np.diff(base_e))) or 1.0
    max_lag_n = int(max_lag_s / dt) if max_lag_s else min(20, base_e.size // 5)
    out, best_overall = [], 0.0
    for s in sibling_series:
        se = _to_epoch(s["timestamps"])
        sv = np.asarray(s["values"], dtype="float64")
        if se.size < 2 or np.std(sv) < 1e-12:
            out.append({"name": s.get("name", "sibling"), "pearson_r": 0.0,
                        "best_lag_s": 0.0, "best_lag_r": 0.0})
            continue
        si = np.interp(base_e, se, sv)
        r0 = float(np.corrcoef(base_v, si)[0, 1])
        best_r, best_lag = r0, 0
        for lag in range(-max_lag_n, max_lag_n + 1):
            if lag == 0:
                continue
            a = base_v[max(0, lag): base_v.size + min(0, lag)]
            b = si[max(0, -lag): si.size + min(0, -lag)]
            if a.size < 8 or np.std(a) < 1e-12 or np.std(b) < 1e-12:
                continue
            r = float(np.corrcoef(a, b)[0, 1])
            if abs(r) > abs(best_r):
                best_r, best_lag = r, lag
        out.append({"name": s.get("name", "sibling"), "pearson_r": round(r0, 3),
                    "best_lag_s": round(best_lag * dt, 1), "best_lag_r": round(best_r, 3)})
        best_overall = max(best_overall, abs(best_r))
    return {"decorrelation_score": round(1.0 - best_overall, 3), "siblings": out}


if __name__ == "__main__":
    # Usage / self-test harness: reads {"timestamps":[...],"values":[...],
    # "siblings":[{"name","timestamps","values"}]} from argv[1] and prints scores.
    import json
    import sys

    payload = json.load(open(sys.argv[1]))
    ts, vals = payload["timestamps"], payload["values"]
    sib = payload.get("siblings")
    out = {
        "phase": phase_anomaly_score(ts, vals, sibling_series=sib),
        "plateau": plateau_score(ts, vals),
        "gap": gap_analysis(ts),
        "stl": stl_residual_score(ts, vals),
        "cadence": cadence_score(ts),
    }
    if sib:
        out["cross_channel"] = cross_channel_correlation(ts, vals, sib)
    print(json.dumps(out, indent=2))
