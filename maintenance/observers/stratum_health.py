"""StratumHealthAgent — observe STRATUM self-healing pipeline calibration.

Reads the Constitution event log (LAW_10 calibration signals emitted by
``implementer_loop.TelemetryRecorder``) and surfaces degradation:

    * sustained refine_latency_ms above threshold      → T2 retry_safe
    * deterministic_hit rate decay over rolling window → T3 validate-only
    * patch_applied/refine_outcome failure spike       → T2 retry_safe

Tagged subsystem="stratum" so RepairCoordinator narrows authority via the
``stratum`` CalibrationProfile.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import List

from maintenance.classifier import Issue, Tier, Severity, make_issue_id
from maintenance.observers.base import ReadOnlyObserver

_log = logging.getLogger(__name__)


class StratumHealthAgent(ReadOnlyObserver):
    name = "StratumHealthAgent"
    cadence_seconds = 30.0

    def __init__(self,
                 *, refine_latency_threshold_ms: float = 2_000.0,
                 deterministic_hit_floor: float = 0.40,
                 window_seconds: float = 300.0):
        self._latency_threshold = float(refine_latency_threshold_ms)
        self._hit_floor = float(deterministic_hit_floor)
        self._window_s = float(window_seconds)

    def _recent_signals(self) -> list[dict]:
        try:
            import sys
            substrate = Path(__file__).resolve().parent.parent.parent.parent
            if str(substrate) not in sys.path:
                sys.path.append(str(substrate))
            from kernel.constitution import get_constitution
            con = get_constitution()
            snap = con.snapshot(last_n=500)
        except Exception as e:
            _log.debug("constitution snapshot unavailable: %s", e)
            return []
        cutoff = time.time() - self._window_s
        out: list[dict] = []
        for ev in snap.get("events", []):
            try:
                if ev.get("law_id") != "LAW_10":
                    continue
                if float(ev.get("timestamp", 0.0)) < cutoff:
                    continue
                if not str(ev.get("subsystem", "")).startswith("intelligence.implementer"):
                    continue
                out.append(ev)
            except Exception:
                continue
        return out

    def scan(self) -> List[Issue]:
        signals = self._recent_signals()
        if not signals:
            return []

        latency_vals: list[float] = []
        det_hits = 0
        det_total = 0
        applied_fail = 0
        applied_total = 0

        for ev in signals:
            ev_metric = (ev.get("evidence") or {}).get("metric", "")
            ev_value  = (ev.get("evidence") or {}).get("value", None)
            if ev_metric == "refine_latency_ms" and isinstance(ev_value, (int, float)):
                latency_vals.append(float(ev_value))
            elif ev_metric == "deterministic_hit":
                det_total += 1
                if ev_value in (1, 1.0, True): det_hits += 1
            elif ev_metric == "patch_applied":
                applied_total += 1
                if ev_value in (0, 0.0, False): applied_fail += 1

        issues: List[Issue] = []

        if latency_vals:
            avg_lat = sum(latency_vals) / len(latency_vals)
            if avg_lat > self._latency_threshold:
                iid = make_issue_id(self.name, "refine_latency_high",
                                     "stratum.implementer",
                                     salt=str(int(time.time() // 60)))
                issues.append(Issue(
                    issue_id=iid, observer=self.name,
                    kind="refine_latency_high",
                    tier=Tier.T2, severity=Severity.MEDIUM,
                    surface="stratum.implementer.refine",
                    evidence={
                        "avg_latency_ms":  avg_lat,
                        "samples":         len(latency_vals),
                        "threshold_ms":    self._latency_threshold,
                        "window_seconds":  self._window_s,
                    },
                    repair_hint="retry_safe_operation",
                    confidence=0.85,
                    subsystem="stratum",
                ))

        if det_total >= 5:
            hit_rate = det_hits / det_total
            if hit_rate < self._hit_floor:
                iid = make_issue_id(self.name, "deterministic_hit_decay",
                                     "stratum.implementer.refine",
                                     salt=str(int(time.time() // 300)))
                issues.append(Issue(
                    issue_id=iid, observer=self.name,
                    kind="deterministic_hit_decay",
                    tier=Tier.T3, severity=Severity.HIGH,
                    surface="stratum.implementer.refine",
                    evidence={
                        "hit_rate":        hit_rate,
                        "hits":            det_hits,
                        "total":           det_total,
                        "floor":           self._hit_floor,
                    },
                    repair_hint=None,
                    confidence=0.90,
                    subsystem="stratum",
                ))

        if applied_total >= 3 and (applied_fail / applied_total) > 0.50:
            iid = make_issue_id(self.name, "patch_apply_failure_spike",
                                 "stratum.implementer.integrate",
                                 salt=str(int(time.time() // 60)))
            issues.append(Issue(
                issue_id=iid, observer=self.name,
                kind="patch_apply_failure_spike",
                tier=Tier.T2, severity=Severity.HIGH,
                surface="stratum.implementer.integrate",
                evidence={
                    "fail":   applied_fail,
                    "total":  applied_total,
                    "ratio":  applied_fail / applied_total,
                },
                repair_hint="retry_safe_operation",
                confidence=0.80,
                subsystem="stratum",
            ))

        return issues
