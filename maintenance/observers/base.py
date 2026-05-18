"""ReadOnlyObserver — base class for the four v1 observers.

Contract:
    * scan() returns a list[Issue]. May be empty. NEVER mutates anything.
    * scan() must not raise; on internal failure, log + return [].
    * subscribe() optionally registers callbacks against an event bus; the
      base class is fine without one (pull-mode is the default).
"""
from __future__ import annotations

import logging
from typing import List

from maintenance.classifier import Issue

_log = logging.getLogger(__name__)


class ReadOnlyObserver:
    """Pull-mode read-only observer. scan() is the canonical contract."""

    name: str = "ReadOnlyObserver"
    cadence_seconds: float = 5.0

    def scan(self) -> List[Issue]:
        """Return any Issues detected this tick. Default: nothing detected."""
        return []

    # Optional push-mode hook (not required for v1)
    def subscribe(self, bus) -> None:
        """Register listeners on a pub/sub bus. No-op by default."""
        return None

    def safe_scan(self) -> List[Issue]:
        """Wrap scan() so a buggy observer can never crash the runtime."""
        try:
            issues = self.scan() or []
        except Exception as exc:
            _log.warning("%s.scan raised: %s", self.name, exc)
            return []
        # Defensive type check
        out: List[Issue] = []
        for it in issues:
            if isinstance(it, Issue):
                out.append(it)
        return out
