"""WONHealthAgent — observe WON chaperone state.

READ-ONLY checks against the WON state files written by ``won_daemon``:

    ~/Documents/AI_Monitor/won_notifications.json   (analysis queue)
    ~/Documents/AI_Monitor/won_daemon_state.json    (daemon heartbeat / state)

Surfaces:

    * notifications file present but stale (>1h since last mtime change)
        → T2 retry_safe (daemon may need a kick)
    * notifications queue depth > queue_high_water for stall_ticks ticks
        → T2 non_destructive_sync
    * daemon state file missing or unreadable
        → T3 validate-only (don't auto-repair substrate state)

Tagged subsystem="won" so RepairCoordinator applies the WON CalibrationProfile.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import List

from maintenance.classifier import Issue, Tier, Severity, make_issue_id
from maintenance.observers.base import ReadOnlyObserver

_log = logging.getLogger(__name__)


SAVE_DIR = Path.home() / "Documents" / "AI_Monitor"
NOTIFY_FILE = SAVE_DIR / "won_notifications.json"
DAEMON_STATE_FILE = SAVE_DIR / "won_daemon_state.json"


class WONHealthAgent(ReadOnlyObserver):
    name = "WONHealthAgent"
    cadence_seconds = 60.0

    def __init__(self, *,
                 stale_seconds: float = 3600.0,
                 queue_high_water: int = 50,
                 stall_ticks: int = 3):
        self._stale_s = float(stale_seconds)
        self._high_water = int(queue_high_water)
        self._stall_ticks_required = int(stall_ticks)
        self._consecutive_over = 0

    def _read_notifications(self) -> list:
        if not NOTIFY_FILE.is_file():
            return []
        try:
            data = json.loads(NOTIFY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list): return data
            if isinstance(data, dict) and isinstance(data.get("items"), list):
                return data["items"]
        except Exception as e:
            _log.debug("WON notify read failed: %s", e)
        return []

    def scan(self) -> List[Issue]:
        issues: List[Issue] = []
        now = time.time()

        # 1. Stale daemon — file present but not touched recently
        if NOTIFY_FILE.is_file():
            try:
                mtime = NOTIFY_FILE.stat().st_mtime
            except Exception:
                mtime = 0.0
            age = now - mtime
            if mtime > 0 and age > self._stale_s:
                iid = make_issue_id(self.name, "won_daemon_stale",
                                     str(NOTIFY_FILE),
                                     salt=str(int(now // 600)))
                issues.append(Issue(
                    issue_id=iid, observer=self.name,
                    kind="won_daemon_stale",
                    tier=Tier.T2, severity=Severity.MEDIUM,
                    surface=str(NOTIFY_FILE),
                    evidence={
                        "age_seconds":    age,
                        "stale_threshold": self._stale_s,
                        "notify_file":    str(NOTIFY_FILE),
                    },
                    repair_hint="retry_safe_operation",
                    confidence=0.80,
                    subsystem="won",
                ))

        # 2. Notification queue stall
        notes = self._read_notifications()
        if len(notes) > self._high_water:
            self._consecutive_over += 1
        else:
            self._consecutive_over = 0

        if self._consecutive_over >= self._stall_ticks_required:
            iid = make_issue_id(self.name, "won_queue_stall",
                                 str(NOTIFY_FILE),
                                 salt=str(int(now // 60)))
            issues.append(Issue(
                issue_id=iid, observer=self.name,
                kind="won_queue_stall",
                tier=Tier.T2, severity=Severity.HIGH,
                surface=str(NOTIFY_FILE),
                evidence={
                    "queue_depth":  len(notes),
                    "high_water":   self._high_water,
                    "consecutive_over_ticks": self._consecutive_over,
                },
                repair_hint="non_destructive_sync",
                confidence=0.85,
                subsystem="won",
            ))

        # 3. Daemon state missing / unreadable
        if not DAEMON_STATE_FILE.is_file():
            iid = make_issue_id(self.name, "won_daemon_state_missing",
                                 str(DAEMON_STATE_FILE), salt="")
            issues.append(Issue(
                issue_id=iid, observer=self.name,
                kind="won_daemon_state_missing",
                tier=Tier.T3, severity=Severity.MEDIUM,
                surface=str(DAEMON_STATE_FILE),
                evidence={"path": str(DAEMON_STATE_FILE)},
                repair_hint=None,
                confidence=0.95,
                subsystem="won",
            ))

        return issues
