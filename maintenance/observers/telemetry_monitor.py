"""TelemetryMonitorAgent — observe Constitution event log health.

Reads the AI_STACK Constitution event log (LAW_3 receipts and other emissions)
and surfaces two failure modes that indicate broken telemetry plumbing:

    * Telemetry silence — no events, or oldest event older than threshold.
        Suggests event-bus rebinding required.
    * Telemetry flood — events-per-minute exceeds threshold.
        Suggests retry-safe quiesce of a noisy emitter.

Read-only. Never mutates substrate. Never raises from scan().
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import List

from maintenance.classifier import Issue, Tier, Severity, make_issue_id
from maintenance.observers.base import ReadOnlyObserver

_log = logging.getLogger(__name__)


class TelemetryMonitorAgent(ReadOnlyObserver):
    name = "TelemetryMonitorAgent"
    cadence_seconds = 60.0

    def __init__(self,
                 *, window_seconds: float = 600.0,
                 silence_threshold_s: float = 300.0,
                 flood_threshold_per_min: int = 200):
        self._window_s = float(window_seconds)
        self._silence_threshold_s = float(silence_threshold_s)
        self._flood_threshold_per_min = int(flood_threshold_per_min)

    def _recent_events(self) -> list[dict]:
        try:
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
                if float(ev.get("timestamp", 0.0)) >= cutoff:
                    out.append(ev)
            except Exception:
                continue
        return out

    def scan(self) -> List[Issue]:
        try:
            events = self._recent_events()
            now = time.time()
            event_count = len(events)
            events_per_min = event_count / max(self._window_s / 60.0, 1.0)

            oldest_law3_ts = None
            for ev in events:
                if ev.get("law_id") != "LAW_3":
                    continue
                try:
                    ts = float(ev.get("timestamp", 0.0))
                except Exception:
                    continue
                if oldest_law3_ts is None or ts < oldest_law3_ts:
                    oldest_law3_ts = ts
            oldest_event_age_s = (now - oldest_law3_ts) if oldest_law3_ts else self._window_s

            evidence = {
                "event_count":              event_count,
                "events_per_min":           events_per_min,
                "oldest_event_age_s":       oldest_event_age_s,
                "window_seconds":           self._window_s,
                "silence_threshold_s":      self._silence_threshold_s,
                "flood_threshold_per_min":  self._flood_threshold_per_min,
            }

            issues: List[Issue] = []

            if event_count == 0 or oldest_event_age_s > self._silence_threshold_s:
                iid = make_issue_id(self.name, "telemetry_silence",
                                    "constitution.events",
                                    salt=str(int(now // 60)))
                issues.append(Issue(
                    issue_id=iid, observer=self.name,
                    kind="telemetry_silence",
                    tier=Tier.T2, severity=Severity.MEDIUM,
                    surface="constitution.events",
                    evidence=dict(evidence),
                    repair_hint="event_rebinding",
                    confidence=0.80,
                    subsystem="",
                ))

            if events_per_min > self._flood_threshold_per_min:
                iid = make_issue_id(self.name, "telemetry_flood",
                                    "constitution.events",
                                    salt=str(int(now // 60)))
                issues.append(Issue(
                    issue_id=iid, observer=self.name,
                    kind="telemetry_flood",
                    tier=Tier.T2, severity=Severity.MEDIUM,
                    surface="constitution.events",
                    evidence=dict(evidence),
                    repair_hint="retry_safe_operation",
                    confidence=0.75,
                    subsystem="",
                ))

            return issues
        except Exception as e:
            _log.debug("TelemetryMonitorAgent.scan failed: %s", e)
            return []
