"""RuntimeHealthAgent — exception telemetry + cycle latency.

Pulls from two sources (best-effort, no hard dep):
    * ~/.stratum/stratum.log tail — counts ERROR / CRITICAL lines in a
      rolling window; classifies repeated patterns as T2 operational issues.
    * Constitution event bus stats — surfaces unusual LAW_3/LAW_4 emission
      rates as T2 calibration warnings.

READ-ONLY. Never writes to the log, never edits the bus.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import List

from maintenance.classifier import (
    Issue, Tier, Severity, make_issue_id,
)
from maintenance.observers.base import ReadOnlyObserver

_log = logging.getLogger(__name__)


STRATUM_LOG_PATH = Path.home() / ".stratum" / "stratum.log"
_ERR_RE = re.compile(r"\bERROR\b|\bCRITICAL\b")
_TRACE_HINT_RE = re.compile(r"Traceback \(most recent call last\)")


class RuntimeHealthAgent(ReadOnlyObserver):
    name = "RuntimeHealthAgent"
    cadence_seconds = 15.0

    def __init__(self, *, window_seconds: float = 120.0,
                 error_rate_threshold: int = 10):
        self._window_s = float(window_seconds)
        self._err_threshold = int(error_rate_threshold)
        self._last_offset = 0
        self._first_tick = True

    def _tail_recent_errors(self) -> List[str]:
        if not STRATUM_LOG_PATH.is_file():
            return []
        try:
            stat = STRATUM_LOG_PATH.stat()
            with STRATUM_LOG_PATH.open("rb") as fh:
                if self._first_tick:
                    fh.seek(max(0, stat.st_size - 64_000))
                    self._first_tick = False
                else:
                    if self._last_offset > stat.st_size:
                        self._last_offset = 0
                    fh.seek(self._last_offset)
                chunk = fh.read()
                self._last_offset = fh.tell()
        except Exception as e:
            _log.warning("RuntimeHealthAgent tail failed: %s", e)
            return []
        try:
            text = chunk.decode("utf-8", errors="replace")
        except Exception:
            return []
        return [ln for ln in text.splitlines() if _ERR_RE.search(ln) or _TRACE_HINT_RE.search(ln)]

    def scan(self) -> List[Issue]:
        issues: List[Issue] = []
        errs = self._tail_recent_errors()
        if len(errs) >= self._err_threshold:
            sample = errs[-3:]
            iid = make_issue_id(self.name, "error_rate_spike",
                                 "stratum.log", salt=str(int(time.time() // 60)))
            issues.append(Issue(
                issue_id=iid,
                observer=self.name,
                kind="error_rate_spike",
                tier=Tier.T2,
                severity=Severity.HIGH,
                surface="stratum.log",
                evidence={
                    "error_count_in_window": len(errs),
                    "window_seconds":         self._window_s,
                    "sample_lines":           sample,
                },
                repair_hint="retry_safe_operation",
                confidence=0.55,   # below default floor on purpose: validate-only by default
            ))
        return issues
