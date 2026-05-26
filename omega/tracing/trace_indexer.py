"""omega.tracing.trace_indexer — index traces by linkage id for fast lookup.

Reads the in-memory ring + the persisted JSONL so a discrepancy can be walked
across trace_id / execution_id / intent_id (Section 3B thread linking).
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Optional

from omega.tracing.trace_engine import get_tracer


def _all_events() -> list[dict]:
    tracer = get_tracer()
    events = [e.to_dict() for e in tracer.recent(1000)]
    seen_ts = {(e["ts"], e["message"]) for e in events}
    try:
        with open(tracer.jsonl_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if (d.get("ts"), d.get("message")) not in seen_ts:
                    events.append(d)
    except Exception:
        pass
    return events


def index() -> dict:
    """Build {trace_id|execution_id|intent_id → [events]} + state counts."""
    by_trace: dict = defaultdict(list)
    by_exec: dict = defaultdict(list)
    by_intent: dict = defaultdict(list)
    state_counts: dict = defaultdict(int)
    for e in _all_events():
        state_counts[e.get("state", "INFO")] += 1
        if e.get("trace_id"):
            by_trace[e["trace_id"]].append(e)
        if e.get("execution_id"):
            by_exec[e["execution_id"]].append(e)
        if e.get("intent_id"):
            by_intent[e["intent_id"]].append(e)
    return {
        "total_events": sum(state_counts.values()),
        "state_counts": dict(state_counts),
        "trace_ids": list(by_trace.keys()),
        "execution_ids": list(by_exec.keys()),
        "orphans": [e for e in _all_events() if not e.get("trace_id")],
        "_by_trace": dict(by_trace),
        "_by_exec": dict(by_exec),
        "_by_intent": dict(by_intent),
    }


def lookup(*, trace_id: Optional[str] = None, execution_id: Optional[str] = None,
           intent_id: Optional[str] = None) -> list[dict]:
    idx = index()
    if trace_id:
        return idx["_by_trace"].get(trace_id, [])
    if execution_id:
        return idx["_by_exec"].get(execution_id, [])
    if intent_id:
        return idx["_by_intent"].get(intent_id, [])
    return []
