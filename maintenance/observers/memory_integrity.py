"""MemoryIntegrityAgent — observe persistence artifacts on disk.

READ-ONLY checks against three persistence artifacts:

    ~/.stratum/stratum.log                          (log file)
    ~/Documents/AI_Monitor/won_notifications.json   (WON queue, json)
    ~/.stratum/dna                                  (DNA snapshots directory)

Surfaces per artifact:

    * Missing parent directory                  → T3 validate-only
    * Stale mtime (older than stale_threshold)  → T2 stale_cache_invalidation
    * JSON parse failure (won_notifications)    → T3 validate-only

Never writes, never mutates. Failures inside a per-artifact check are logged
at debug level and never propagate to the caller.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import List, Optional

from maintenance.classifier import Issue, Tier, Severity, make_issue_id
from maintenance.observers.base import ReadOnlyObserver

_log = logging.getLogger(__name__)


STRATUM_LOG_PATH = Path.home() / ".stratum" / "stratum.log"
WON_NOTIFICATIONS_PATH = Path.home() / "Documents" / "AI_Monitor" / "won_notifications.json"
DNA_SNAPSHOTS_DIR = Path.home() / ".stratum" / "dna"


class MemoryIntegrityAgent(ReadOnlyObserver):
    name = "MemoryIntegrityAgent"
    cadence_seconds = 90.0

    def __init__(self, *, stale_threshold_s: float = 7200.0):
        self._stale_s = float(stale_threshold_s)

    @staticmethod
    def _subsystem_for(path: Path) -> str:
        return "won" if path == WON_NOTIFICATIONS_PATH else ""

    def _check_parent_missing(self, path: Path) -> Optional[Issue]:
        parent = path.parent
        if parent.exists():
            return None
        iid = make_issue_id(self.name, "parent_dir_missing", str(path))
        return Issue(
            issue_id=iid, observer=self.name,
            kind="parent_dir_missing",
            tier=Tier.T3, severity=Severity.MEDIUM,
            surface=str(path),
            evidence={
                "path":   str(path),
                "exists": False,
                "parent": str(parent),
            },
            repair_hint=None,
            confidence=0.95,
            subsystem=self._subsystem_for(path),
        )

    def _check_stale(self, path: Path, now: float) -> Optional[Issue]:
        if not path.exists():
            return None
        try:
            mtime = path.stat().st_mtime
        except Exception as e:
            _log.debug("MemoryIntegrityAgent stat failed for %s: %s", path, e)
            return None
        age = now - mtime
        if age <= self._stale_s:
            return None
        iid = make_issue_id(self.name, "persistence_stale", str(path),
                            salt=str(int(now // 600)))
        return Issue(
            issue_id=iid, observer=self.name,
            kind="persistence_stale",
            tier=Tier.T2, severity=Severity.LOW,
            surface=str(path),
            evidence={
                "path":        str(path),
                "exists":      True,
                "mtime":       mtime,
                "age_seconds": age,
            },
            repair_hint="stale_cache_invalidation",
            confidence=0.75,
            subsystem=self._subsystem_for(path),
        )

    def _check_json_corruption(self, path: Path) -> Optional[Issue]:
        if not path.is_file():
            return None
        try:
            json.loads(path.read_text(encoding="utf-8"))
            return None
        except Exception as e:
            _log.debug("MemoryIntegrityAgent json parse failed for %s: %s", path, e)
            iid = make_issue_id(self.name, "json_corruption", str(path))
            try:
                mtime = path.stat().st_mtime
            except Exception:
                mtime = 0.0
            return Issue(
                issue_id=iid, observer=self.name,
                kind="json_corruption",
                tier=Tier.T3, severity=Severity.HIGH,
                surface=str(path),
                evidence={
                    "path":   str(path),
                    "exists": True,
                    "mtime":  mtime,
                    "error":  str(e),
                },
                repair_hint=None,
                confidence=0.95,
                subsystem="won",
            )

    def scan(self) -> List[Issue]:
        issues: List[Issue] = []
        now = time.time()
        watched = (STRATUM_LOG_PATH, WON_NOTIFICATIONS_PATH, DNA_SNAPSHOTS_DIR)

        for path in watched:
            try:
                missing = self._check_parent_missing(path)
                if missing is not None:
                    issues.append(missing)
                stale = self._check_stale(path, now)
                if stale is not None:
                    issues.append(stale)
            except Exception as e:
                _log.debug("MemoryIntegrityAgent check failed for %s: %s", path, e)
                continue

        try:
            corrupt = self._check_json_corruption(WON_NOTIFICATIONS_PATH)
            if corrupt is not None:
                issues.append(corrupt)
        except Exception as e:
            _log.debug("MemoryIntegrityAgent json check failed: %s", e)

        return issues
