"""QueueWatchAgent — worker-pool depth / stall detection.

Polls a registered ``depth_provider`` callable each tick. If depth stays
above the high-water mark for ``stall_ticks`` consecutive ticks, raises a
T2 operational Issue with repair_hint=queue_cleanup.

READ-ONLY: never drains the queue, never restarts workers. RepairCoordinator
is the only thing allowed to invoke the queue_cleanup repair.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, List, Optional

from maintenance.classifier import Issue, Tier, Severity, make_issue_id
from maintenance.observers.base import ReadOnlyObserver

_log = logging.getLogger(__name__)


class QueueWatchAgent(ReadOnlyObserver):
    name = "QueueWatchAgent"
    cadence_seconds = 10.0

    def __init__(self,
                 depth_provider: Optional[Callable[[], int]] = None,
                 *, high_water: int = 32,
                 stall_ticks: int = 3):
        self._provider = depth_provider
        self._high_water = int(high_water)
        self._stall_ticks_required = int(stall_ticks)
        self._consecutive_over = 0

    def set_provider(self, fn: Callable[[], int]) -> None:
        self._provider = fn

    def scan(self) -> List[Issue]:
        if self._provider is None:
            return []
        try:
            depth = int(self._provider())
        except Exception as e:
            _log.warning("QueueWatchAgent provider raised: %s", e)
            return []

        if depth > self._high_water:
            self._consecutive_over += 1
        else:
            self._consecutive_over = 0
            return []

        if self._consecutive_over < self._stall_ticks_required:
            return []

        iid = make_issue_id(self.name, "queue_stall",
                             "worker_pool", salt=str(int(time.time() // 60)))
        return [Issue(
            issue_id=iid,
            observer=self.name,
            kind="queue_stall",
            tier=Tier.T2,
            severity=Severity.MEDIUM,
            surface="worker_pool",
            evidence={
                "depth":                  depth,
                "high_water":             self._high_water,
                "consecutive_over_ticks": self._consecutive_over,
            },
            repair_hint="queue_cleanup",
            confidence=0.75,
        )]
