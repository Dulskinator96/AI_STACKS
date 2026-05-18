"""ExecutionIntegrityAgent — observe TaskRouter / ExecutionOrchestrator lineage.

Read-only checks against the kernel substrate's dispatch trace + Constitution
event log:

    1. Orphan executions — engine.cycle events with no preceding
       task.dispatched within a small window.
    2. Retry storms — same task_id dispatched > burst_threshold times in
       burst_window_seconds.
    3. Recursive execution loops — the same dispatch chain (caller→action)
       repeats > recursion_threshold consecutive times.
    4. Unauthorized direct calls — task.dispatched receipts where actor
       does not match the canonical router subsystem (rare; substrate-level).

Substrate is reached the same way as other observers in this package:
    Path(__file__).resolve().parent.parent.parent.parent → AIBuild/AI_STACK
    from kernel.constitution import get_constitution

If the substrate is unreachable, scan() returns [] (best-effort).
"""
from __future__ import annotations

import json
import logging
import sys
import time
from collections import Counter
from pathlib import Path
from typing import List

from maintenance.classifier import Issue, Tier, Severity, make_issue_id
from maintenance.observers.base import ReadOnlyObserver

_log = logging.getLogger(__name__)


def _substrate_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _trace_log_path() -> Path:
    return _substrate_root() / "trace_log.json"


class ExecutionIntegrityAgent(ReadOnlyObserver):
    name = "ExecutionIntegrityAgent"
    cadence_seconds = 20.0

    def __init__(self, *,
                 burst_window_seconds: float = 60.0,
                 burst_threshold: int = 8,
                 recursion_threshold: int = 5,
                 orphan_window_seconds: float = 5.0):
        self._burst_window = float(burst_window_seconds)
        self._burst_threshold = int(burst_threshold)
        self._recursion_threshold = int(recursion_threshold)
        self._orphan_window = float(orphan_window_seconds)

    # ── substrate readers (best-effort) ────────────────────────────────────

    def _read_trace(self) -> list[dict]:
        p = _trace_log_path()
        if not p.is_file():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list): return data
            if isinstance(data, dict) and isinstance(data.get("trace"), list):
                return data["trace"]
        except Exception as e:
            _log.debug("trace_log read failed: %s", e)
        return []

    def _read_constitution_events(self) -> list[dict]:
        try:
            root = _substrate_root()
            if str(root) not in sys.path:
                sys.path.append(str(root))
            from kernel.constitution import get_constitution
            con = get_constitution()
            snap = con.snapshot(last_n=500)
            return snap.get("events", []) or []
        except Exception as e:
            _log.debug("constitution snapshot unavailable: %s", e)
            return []

    # ── observer contract ──────────────────────────────────────────────────

    def scan(self) -> List[Issue]:
        issues: List[Issue] = []
        trace = self._read_trace()
        events = self._read_constitution_events()
        now = time.time()
        cutoff = now - self._burst_window

        # ── 1. Retry storms (same task_id dispatched repeatedly) ───────────
        task_hits: Counter = Counter()
        for entry in trace:
            try:
                ts = float(entry.get("timestamp", entry.get("ts", 0.0)) or 0.0)
                if ts < cutoff:
                    continue
                tid = entry.get("task_id") or entry.get("action") or "unknown"
                task_hits[tid] += 1
            except Exception:
                continue
        for tid, count in task_hits.items():
            if count >= self._burst_threshold:
                iid = make_issue_id(self.name, "retry_storm",
                                     f"task:{tid}",
                                     salt=str(int(now // 60)))
                issues.append(Issue(
                    issue_id=iid, observer=self.name,
                    kind="retry_storm",
                    tier=Tier.T2, severity=Severity.HIGH,
                    surface=f"taskrouter.{tid}",
                    evidence={
                        "task_id":              tid,
                        "dispatches_in_window": count,
                        "window_seconds":       self._burst_window,
                        "threshold":            self._burst_threshold,
                    },
                    repair_hint="retry_safe_operation",
                    confidence=0.85,
                    subsystem="stratum",
                ))

        # ── 2. Recursive execution loops (same (caller, action) chain) ─────
        chain_runs: Counter = Counter()
        last_chain = None
        run_len = 0
        for entry in trace:
            try:
                ts = float(entry.get("timestamp", entry.get("ts", 0.0)) or 0.0)
                if ts < cutoff:
                    continue
                chain = (entry.get("caller", "?"), entry.get("action", "?"))
                if chain == last_chain:
                    run_len += 1
                else:
                    if last_chain is not None and run_len >= self._recursion_threshold:
                        chain_runs[last_chain] = max(chain_runs[last_chain], run_len)
                    last_chain = chain
                    run_len = 1
            except Exception:
                continue
        if last_chain is not None and run_len >= self._recursion_threshold:
            chain_runs[last_chain] = max(chain_runs[last_chain], run_len)
        for chain, runlen in chain_runs.items():
            caller, action = chain
            iid = make_issue_id(self.name, "recursive_execution",
                                 f"{caller}->{action}",
                                 salt=str(int(now // 60)))
            issues.append(Issue(
                issue_id=iid, observer=self.name,
                kind="recursive_execution",
                tier=Tier.T3, severity=Severity.HIGH,
                surface=f"{caller}->{action}",
                evidence={
                    "caller":               caller,
                    "action":               action,
                    "consecutive_runs":     runlen,
                    "recursion_threshold":  self._recursion_threshold,
                },
                repair_hint=None,
                confidence=0.90,
                subsystem="stratum",
            ))

        # ── 3. Orphan executions: engine.cycle without prior dispatch ──────
        recent_dispatch = []
        recent_cycle = []
        for ev in events:
            try:
                ts = float(ev.get("timestamp", 0.0))
                if ts < cutoff:
                    continue
                action = str(ev.get("action", ""))
                if "task.dispatched" in action or "dispatch" in action.lower():
                    recent_dispatch.append(ts)
                elif "engine.cycle" in action or "cycle" in action.lower():
                    recent_cycle.append(ts)
            except Exception:
                continue
        orphan_cycles = 0
        for c_ts in recent_cycle:
            preceding = [d for d in recent_dispatch
                          if 0.0 <= (c_ts - d) <= self._orphan_window]
            if not preceding:
                orphan_cycles += 1
        if orphan_cycles >= 3:
            iid = make_issue_id(self.name, "orphan_execution",
                                 "engine.cycle",
                                 salt=str(int(now // 60)))
            issues.append(Issue(
                issue_id=iid, observer=self.name,
                kind="orphan_execution",
                tier=Tier.T3, severity=Severity.MEDIUM,
                surface="engine.cycle",
                evidence={
                    "orphan_cycles":   orphan_cycles,
                    "dispatches_seen": len(recent_dispatch),
                    "cycles_seen":     len(recent_cycle),
                    "orphan_window_s": self._orphan_window,
                },
                repair_hint=None,
                confidence=0.85,
                subsystem="stratum",
            ))

        # ── 4. Unauthorized direct calls (T4: never auto-repair) ───────────
        for ev in events:
            try:
                ts = float(ev.get("timestamp", 0.0))
                if ts < cutoff:
                    continue
                action = str(ev.get("action", ""))
                actor = str(ev.get("actor", ""))
                if "dispatch" in action.lower() and actor and actor not in {
                    "TaskRouter", "ExecutionOrchestrator", "kernel",
                    "ControlPlane", "KernelInterface",
                }:
                    iid = make_issue_id(self.name, "unauthorized_dispatch",
                                         f"actor:{actor}",
                                         salt=str(int(now // 60)))
                    issues.append(Issue(
                        issue_id=iid, observer=self.name,
                        kind="unauthorized_dispatch",
                        tier=Tier.T4, severity=Severity.CRITICAL,
                        surface=f"unknown_actor:{actor}",
                        evidence={
                            "actor":  actor,
                            "action": action,
                            "ts":     ts,
                        },
                        repair_hint=None,
                        confidence=0.95,
                        subsystem="agents",
                    ))
                    break   # one is enough — operator must review
            except Exception:
                continue

        return issues
