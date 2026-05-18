"""UIStateAgent — detect render/state mismatches.

For v1 this observer is a thin shim that watches a small published state
dictionary (e.g. `{"tab_active": "🩺 Diagnostics", "expected": "🏛 Palace"}`)
and reports drift. The directive specifies UI becomes a first-class
telemetry surface; this is the first attachment point.

READ-ONLY: never calls any Qt mutation, never triggers a repaint.
"""
from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional

from maintenance.classifier import Issue, Tier, Severity, make_issue_id
from maintenance.observers.base import ReadOnlyObserver

_log = logging.getLogger(__name__)


class UIStateAgent(ReadOnlyObserver):
    name = "UIStateAgent"
    cadence_seconds = 5.0

    def __init__(self):
        self._lock = threading.Lock()
        self._state: Dict[str, str] = {}
        self._expected: Dict[str, str] = {}

    # ── public publish surface — called by the View layer ──────────────────

    def publish_state(self, key: str, observed: str,
                       expected: Optional[str] = None) -> None:
        with self._lock:
            self._state[key] = observed
            if expected is not None:
                self._expected[key] = expected

    def clear_expectation(self, key: str) -> None:
        with self._lock:
            self._expected.pop(key, None)

    # ── observer contract ──────────────────────────────────────────────────

    def scan(self) -> List[Issue]:
        with self._lock:
            state = dict(self._state)
            expected = dict(self._expected)

        issues: List[Issue] = []
        for key, want in expected.items():
            got = state.get(key)
            if got is None or got == want:
                continue
            iid = make_issue_id(self.name, "ui_state_mismatch", key, salt=got)
            issues.append(Issue(
                issue_id=iid,
                observer=self.name,
                kind="ui_state_mismatch",
                tier=Tier.T1,
                severity=Severity.LOW,
                surface=f"ui:{key}",
                evidence={"observed": got, "expected": want},
                repair_hint="ui_state_resync",
                confidence=0.85,
            ))
        return issues
