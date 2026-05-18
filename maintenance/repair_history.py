"""repair_history.py — rolling analysis over telemetry/maintenance_receipts.jsonl.

Read-only. Never mutates the log.

Used by the Cortex to:
    * suppress recursive repair loops on a single fault signature
    * surface fault clusters (kind + surface) trending toward instability
    * report repair success rates per (action, subsystem)

Public surface:

    FaultCluster                 — aggregated stats for one (kind, surface)
    HistoryReport                — top-level snapshot returned by analyze()
    analyze(window_seconds=900)  — read receipts in window, build report
    is_recursive(issue, threshold) — boolean: has this (kind, surface) been
                                      hit > threshold times in the window?
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from maintenance.classifier import Issue
from maintenance.receipts import (
    RECEIPT_LOG,
    OUTCOME_APPLIED, OUTCOME_REJECTED,
    OUTCOME_ESCALATED, OUTCOME_UNRESOLVED,
)

_log = logging.getLogger(__name__)


@dataclass
class FaultCluster:
    issue_kind:      str
    surface:         str
    repair_hint:     Optional[str]
    occurrences:     int = 0
    applied:         int = 0
    unresolved:      int = 0
    rejected:        int = 0
    escalated:       int = 0
    last_seen:       float = 0.0
    first_seen:      float = 0.0
    confidence_avg:  float = 0.0

    @property
    def success_rate(self) -> float:
        if self.occurrences == 0:
            return 0.0
        return self.applied / self.occurrences

    @property
    def is_recurring(self) -> bool:
        return self.occurrences >= 3

    @property
    def is_unstable(self) -> bool:
        # Recurring AND mostly failing
        return self.is_recurring and self.success_rate < 0.5


@dataclass
class HistoryReport:
    window_seconds:   float
    total_receipts:   int
    clusters:         list[FaultCluster] = field(default_factory=list)
    recurring:        list[FaultCluster] = field(default_factory=list)
    unstable:         list[FaultCluster] = field(default_factory=list)
    applied_count:    int = 0
    unresolved_count: int = 0

    def cluster_for(self, kind: str, surface: str) -> Optional[FaultCluster]:
        for c in self.clusters:
            if c.issue_kind == kind and c.surface == surface:
                return c
        return None


def _iter_receipts(window_seconds: float, log_path: Optional[Path] = None) -> Iterable[dict]:
    log_path = log_path or RECEIPT_LOG
    if not log_path.is_file():
        return
    cutoff = time.time() - float(window_seconds)
    try:
        with log_path.open("r", encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    obj = json.loads(ln)
                except Exception:
                    continue
                ts = float(obj.get("timestamp", 0.0))
                if ts >= cutoff:
                    yield obj
    except Exception as e:
        _log.warning("repair_history scan failed: %s", e)


def analyze(window_seconds: float = 900.0,
             log_path: Optional[Path] = None) -> HistoryReport:
    """Build a HistoryReport over the receipts in the rolling window."""
    report = HistoryReport(window_seconds=window_seconds, total_receipts=0)
    by_key: dict[tuple, FaultCluster] = {}

    for obj in _iter_receipts(window_seconds, log_path=log_path):
        report.total_receipts += 1
        # We don't have issue_kind/surface in the Receipt directly — they live
        # in evidence.before or in the receipt's note. Heuristic: derive from
        # action + issue_id. For robust clustering, callers should ensure
        # before-evidence carries the original Issue fields. We use:
        #   key = (note, issue_id-prefix-stable) — fallback only.
        kind = (obj.get("before") or {}).get("kind") or obj.get("action") or "unknown"
        surface = (obj.get("before") or {}).get("surface") or "unknown"
        hint = obj.get("action")
        ts = float(obj.get("timestamp", 0.0))
        conf = float(obj.get("confidence", 0.0))
        outcome = obj.get("outcome", "")

        key = (kind, surface, hint)
        cluster = by_key.get(key)
        if cluster is None:
            cluster = FaultCluster(
                issue_kind=kind, surface=surface, repair_hint=hint,
                first_seen=ts, last_seen=ts, confidence_avg=conf,
            )
            by_key[key] = cluster

        cluster.occurrences += 1
        cluster.last_seen = max(cluster.last_seen, ts)
        cluster.first_seen = min(cluster.first_seen or ts, ts)
        cluster.confidence_avg = (
            (cluster.confidence_avg * (cluster.occurrences - 1) + conf)
            / cluster.occurrences
        )

        if outcome == OUTCOME_APPLIED:
            cluster.applied += 1
            report.applied_count += 1
        elif outcome == OUTCOME_UNRESOLVED:
            cluster.unresolved += 1
            report.unresolved_count += 1
        elif outcome == OUTCOME_REJECTED:
            cluster.rejected += 1
        elif outcome == OUTCOME_ESCALATED:
            cluster.escalated += 1

    report.clusters = sorted(by_key.values(),
                              key=lambda c: c.occurrences, reverse=True)
    report.recurring = [c for c in report.clusters if c.is_recurring]
    report.unstable = [c for c in report.clusters if c.is_unstable]
    return report


def is_recursive(issue: Issue, *, window_seconds: float = 900.0,
                  threshold: int = 5) -> bool:
    """Has this issue's (kind, surface) been touched ≥ threshold times recently?

    Used by the Cortex to suppress recursive repair loops — if a fault keeps
    coming back faster than we can fix it, the right action is to ESCALATE,
    not keep retrying.
    """
    report = analyze(window_seconds=window_seconds)
    cluster = report.cluster_for(issue.kind, issue.surface)
    if cluster is None:
        return False
    return cluster.occurrences >= int(threshold)
