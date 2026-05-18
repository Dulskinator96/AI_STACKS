"""ResourcePressureAgent — host CPU / memory / disk pressure observer.

Best-effort psutil probe. Emits one Issue per breached threshold per tick.
READ-ONLY: never throttles processes, never frees memory, never deletes files.
RepairCoordinator is the only thing allowed to act on these issues.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import List

from maintenance.classifier import Issue, Tier, Severity, make_issue_id
from maintenance.observers.base import ReadOnlyObserver

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover - degrade to no-op
    psutil = None  # type: ignore

_log = logging.getLogger(__name__)


class ResourcePressureAgent(ReadOnlyObserver):
    name = "ResourcePressureAgent"
    cadence_seconds = 45.0

    def __init__(self,
                 cpu_threshold: float = 85.0,
                 memory_threshold: float = 90.0,
                 disk_threshold: float = 95.0):
        self._cpu_threshold = float(cpu_threshold)
        self._mem_threshold = float(memory_threshold)
        self._disk_threshold = float(disk_threshold)
        self._warned_missing = False

    def scan(self) -> List[Issue]:
        if psutil is None:
            if not self._warned_missing:
                _log.debug("ResourcePressureAgent: psutil unavailable, no-op")
                self._warned_missing = True
            return []
        try:
            cpu_pct = float(psutil.cpu_percent(interval=None))
            mem_pct = float(psutil.virtual_memory().percent)
            disk_pct = float(psutil.disk_usage(str(Path.home())).percent)
        except Exception as e:
            _log.warning("ResourcePressureAgent probe failed: %s", e)
            return []

        salt = str(int(time.time() // 60))
        issues: List[Issue] = []

        if cpu_pct >= self._cpu_threshold:
            issues.append(Issue(
                issue_id=make_issue_id(self.name, "cpu_pressure", "host.cpu", salt=salt),
                observer=self.name,
                kind="cpu_pressure",
                tier=Tier.T2,
                severity=Severity.MEDIUM,
                surface="host.cpu",
                evidence={
                    "percent":   cpu_pct,
                    "threshold": self._cpu_threshold,
                    "metric":    "cpu_percent",
                },
                repair_hint="queue_cleanup",
                confidence=0.80,
                subsystem="workers",
            ))

        if mem_pct >= self._mem_threshold:
            issues.append(Issue(
                issue_id=make_issue_id(self.name, "memory_pressure", "host.memory", salt=salt),
                observer=self.name,
                kind="memory_pressure",
                tier=Tier.T2,
                severity=Severity.HIGH,
                surface="host.memory",
                evidence={
                    "percent":   mem_pct,
                    "threshold": self._mem_threshold,
                    "metric":    "memory_percent",
                },
                repair_hint="stale_cache_invalidation",
                confidence=0.85,
                subsystem="workers",
            ))

        if disk_pct >= self._disk_threshold:
            issues.append(Issue(
                issue_id=make_issue_id(self.name, "disk_pressure", "host.disk", salt=salt),
                observer=self.name,
                kind="disk_pressure",
                tier=Tier.T3,
                severity=Severity.HIGH,
                surface="host.disk",
                evidence={
                    "percent":   disk_pct,
                    "threshold": self._disk_threshold,
                    "metric":    "disk_percent",
                },
                repair_hint=None,
                confidence=0.95,
                subsystem="workers",
            ))

        return issues

