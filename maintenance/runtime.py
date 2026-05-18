"""MaintenanceRuntime — bounded autonomous loop.

Single background thread. Wakes once per `tick_seconds` (default 5s), calls
each registered observer at most once per its own ``cadence_seconds``, routes
the resulting Issues into RepairCoordinator.handle().

Bounded by construction:
    * one thread, not a pool — no swarm
    * observers run sequentially within the tick — no parallel orchestration
    * RepairCoordinator is the only mutator — runtime never patches anything
    * runtime never escalates authority — it cannot bypass T3/T4 gating
    * pause()/resume() supported; stop() is final

Public surface:

    rt = MaintenanceRuntime(coordinator, observers=[...])
    rt.start()    # spawns the bg thread
    rt.pause()    # no observer ticks until resume()
    rt.resume()
    rt.stop()     # joins the thread; final
    rt.tick_once()  # synchronous one-shot for tests
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Iterable, List, Optional

from maintenance.classifier import Issue
from maintenance.observers.base import ReadOnlyObserver
from maintenance.repair_coordinator import RepairCoordinator, RepairOutcome

_log = logging.getLogger(__name__)


DEFAULT_TICK_SECONDS = 5.0


class MaintenanceRuntime:

    def __init__(self,
                 coordinator: RepairCoordinator,
                 observers: Iterable[ReadOnlyObserver],
                 *, tick_seconds: float = DEFAULT_TICK_SECONDS):
        self._coordinator = coordinator
        self._observers: List[ReadOnlyObserver] = list(observers)
        self._tick_seconds = float(tick_seconds)
        self._last_run: dict[str, float] = {o.name: 0.0 for o in self._observers}
        self._stop_event = threading.Event()
        self._paused = threading.Event()
        self._paused.clear()       # not paused initially
        self._thread: Optional[threading.Thread] = None
        self._tick_count = 0
        self._last_outcomes: List[RepairOutcome] = []

    # ── lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="MaintenanceRuntime", daemon=True,
        )
        self._thread.start()
        _log.info("MaintenanceRuntime started (tick=%.1fs, observers=%d)",
                   self._tick_seconds, len(self._observers))

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        t = self._thread
        if t is not None:
            t.join(timeout=timeout)
        self._thread = None
        _log.info("MaintenanceRuntime stopped")

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    @property
    def running(self) -> bool:
        return self._thread is not None and not self._stop_event.is_set()

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def last_outcomes(self) -> List[RepairOutcome]:
        return list(self._last_outcomes)

    # ── one tick (also usable from tests) ──────────────────────────────────

    def tick_once(self) -> List[RepairOutcome]:
        if self._paused.is_set():
            return []
        now = time.time()
        produced: List[Issue] = []
        for obs in self._observers:
            cadence = float(getattr(obs, "cadence_seconds", 0.0))
            last = self._last_run.get(obs.name, 0.0)
            if cadence > 0.0 and (now - last) < cadence:
                continue
            self._last_run[obs.name] = now
            issues = obs.safe_scan()
            if issues:
                _log.debug("%s produced %d issue(s)", obs.name, len(issues))
                produced.extend(issues)

        outcomes: List[RepairOutcome] = []
        for issue in produced:
            try:
                outcomes.append(self._coordinator.handle(issue))
            except Exception as exc:
                _log.warning("coordinator.handle raised: %s", exc)

        self._tick_count += 1
        self._last_outcomes = outcomes
        return outcomes

    # ── background loop ────────────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.tick_once()
            except Exception as exc:
                _log.warning("MaintenanceRuntime tick raised: %s", exc)
            # Coarse sleep loop so stop() is responsive
            slept = 0.0
            slice_s = 0.25
            while slept < self._tick_seconds and not self._stop_event.is_set():
                time.sleep(slice_s)
                slept += slice_s
