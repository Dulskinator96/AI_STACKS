"""omega.tracing — permanent runtime TRACE ENGINE (BUILD-034 Section 3).

For AI operational awareness: colorized trace states, thread-linked events,
file-origin tracking, drift detection, anomaly indexing.
"""
from omega.tracing.trace_contracts import TraceState, TraceEvent, new_trace_id
from omega.tracing.trace_engine import (
    get_tracer, emit, emit_failure, trace_context, current_context, render_recent,
)
from omega.tracing.trace_render import render, enable_ansi_on_windows
from omega.tracing.trace_indexer import index, lookup
from omega.tracing.anomaly_detector import run_drift_scan

__all__ = [
    "TraceState", "TraceEvent", "new_trace_id",
    "get_tracer", "emit", "emit_failure", "trace_context", "current_context",
    "render", "render_recent", "enable_ansi_on_windows",
    "index", "lookup", "run_drift_scan",
]
