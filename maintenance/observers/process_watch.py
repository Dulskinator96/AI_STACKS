"""ProcessWatchAgent — python process count / RSS pressure detection.

Reads, best-effort, the current python process count + total RSS via psutil.
If either exceeds its threshold for ``stall_ticks`` consecutive ticks, raises
a T2 operational Issue with repair_hint=temporary_process_restart.

READ-ONLY: never kills, never restarts. RepairCoordinator is the only thing
allowed to invoke the temporary_process_restart repair.
"""
from __future__ import annotations

import logging
import time
from typing import List

from maintenance.classifier import Issue, Tier, Severity, make_issue_id
from maintenance.observers.base import ReadOnlyObserver

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover - optional dep
    psutil = None  # type: ignore

_log = logging.getLogger(__name__)


class ProcessWatchAgent(ReadOnlyObserver):
    name = "ProcessWatchAgent"
    cadence_seconds = 30.0

    def __init__(self,
                 *, max_python_processes: int = 12,
                 total_rss_mb: int = 4096,
                 stall_ticks: int = 2):
        self._max_python = int(max_python_processes)
        self._max_rss_mb = int(total_rss_mb)
        self._stall_ticks_required = int(stall_ticks)
        self._consecutive_over = 0
        self._missing_logged = False

    def scan(self) -> List[Issue]:
        if psutil is None:
            if not self._missing_logged:
                _log.debug("ProcessWatchAgent: psutil unavailable, scan() is a no-op")
                self._missing_logged = True
            return []

        try:
            py_count = 0
            total_rss = 0
            for proc in psutil.process_iter(["name", "memory_info"]):
                info = proc.info or {}
                nm = (info.get("name") or "").lower()
                if "python" in nm:
                    py_count += 1
                mem = info.get("memory_info")
                if mem is not None:
                    total_rss += int(getattr(mem, "rss", 0) or 0)
            total_rss_mb = total_rss // (1024 * 1024)
        except Exception as e:
            _log.warning("ProcessWatchAgent scan failed: %s", e)
            return []

        over = (py_count > self._max_python) or (total_rss_mb > self._max_rss_mb)
        if over:
            self._consecutive_over += 1
        else:
            self._consecutive_over = 0
            return []

        if self._consecutive_over < self._stall_ticks_required:
            return []

        iid = make_issue_id(self.name, "python_process_pressure",
                            "process_pool", salt=str(int(time.time() // 60)))
        return [Issue(
            issue_id=iid,
            observer=self.name,
            kind="python_process_pressure",
            tier=Tier.T2,
            severity=Severity.MEDIUM,
            surface="process_pool",
            evidence={
                "python_process_count":    py_count,
                "total_rss_mb":            total_rss_mb,
                "max_python_processes":    self._max_python,
                "max_total_rss_mb":        self._max_rss_mb,
                "consecutive_over_ticks":  self._consecutive_over,
            },
            repair_hint="temporary_process_restart",
            confidence=0.75,
            subsystem="workers",
        )]

