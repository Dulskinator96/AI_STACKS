"""engine/realm_orchestrator.py — BUILD-020 SECTION 7: REALM ORCHESTRATOR.

Multi-realm coordinator. Sits ABOVE the single-step RealmDispatcher and
coordinates cross-realm execution graphs. Example:

  intent "make a cinematic city trailer" →
    image realm (concept frames) →
    audio realm (soundtrack) →
    video realm (assemble)

The orchestrator decides parallel vs sequential, gathers per-realm
results, and reports a unified RealmOrchestration result back to the
caller.

Builds on `RealmDispatcher.dispatch_step` — does not replace it.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)


@dataclass
class RealmOrchestration:
    orch_id:          str
    intent_text:      str
    started_at:       float
    waves:            list = field(default_factory=list)   # list of [step_results]
    overall_outcome:  str = "PENDING"   # PENDING | OK | DEGRADED | FAIL
    duration_ms:      float = 0.0
    error:            str = ""

    def to_dict(self) -> dict:
        return {
            "orch_id":          self.orch_id,
            "intent_text":      self.intent_text[:200],
            "started_at":       self.started_at,
            "wave_count":       len(self.waves),
            "step_count":       sum(len(w) for w in self.waves),
            "overall_outcome":  self.overall_outcome,
            "duration_ms":      self.duration_ms,
            "error":            self.error,
        }


class RealmOrchestrator:
    """Wave-level parallel dispatch coordinator."""

    def __init__(self):
        self._lock = threading.RLock()
        self._orch_count = 0
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.realm_orchestrator", self)
        except Exception:
            pass

    def orchestrate(self, intent_text: str, graph,
                    on_progress: Optional[Callable[[str, RealmOrchestration], None]] = None,
                    on_complete: Optional[Callable[[RealmOrchestration], None]] = None,
                    log_fn: Optional[Callable[[str], None]] = None) -> RealmOrchestration:
        """Run an ExecutionGraph through the dispatcher with wave-level
        parallelism (steps with no shared dependency run concurrently).
        Returns immediately; actual dispatch is async."""
        t0 = time.time()
        oid = f"orch-{uuid.uuid4().hex[:10]}"
        orch = RealmOrchestration(
            orch_id=oid, intent_text=intent_text or "", started_at=t0,
        )
        with self._lock:
            self._orch_count += 1

        try:
            from runtime.deferred_loader import DeferredWorkspaceLoader
        except Exception as e:
            orch.overall_outcome = "FAIL"
            orch.error = f"deferred_loader missing: {e}"
            if on_complete:
                on_complete(orch)
            return orch

        def _run():
            try:
                waves = self._compute_waves(graph)
                for wave_idx, wave_steps in enumerate(waves):
                    wave_results = self._dispatch_wave(wave_steps, log_fn)
                    orch.waves.append(wave_results)
                    if on_progress:
                        try:
                            on_progress(f"WAVE_{wave_idx}", orch)
                        except Exception:
                            pass

                # Roll up
                all_results = [r for wave in orch.waves for r in wave]
                ok = sum(1 for r in all_results if _outcome(r) == "OK")
                fail = sum(1 for r in all_results if _outcome(r) == "FAIL")
                if fail == 0 and ok == len(all_results):
                    orch.overall_outcome = "OK"
                elif fail < len(all_results) // 2:
                    orch.overall_outcome = "DEGRADED"
                else:
                    orch.overall_outcome = "FAIL"

            except Exception as e:
                orch.overall_outcome = "FAIL"
                orch.error = str(e)
                _log.exception("realm orchestration failed: %s", e)

            orch.duration_ms = (time.time() - t0) * 1000.0
            self._emit_receipt(orch)
            if on_complete:
                try:
                    on_complete(orch)
                except Exception:
                    pass

        DeferredWorkspaceLoader.run(_run, on_done=None, name=f"orch-{oid}")
        return orch

    def _compute_waves(self, graph) -> list:
        """Topological wave decomposition. Steps with no dependency are
        wave 0; steps depending only on wave-0 are wave 1; etc."""
        steps = list(getattr(graph, "steps", []) or [])
        completed: set = set()
        waves: list[list] = []
        remaining = list(steps)
        guard = 0
        while remaining and guard < 32:
            guard += 1
            wave = [s for s in remaining
                    if all(_dep_satisfied(d, completed) for d in (s.inputs or []))]
            if not wave:
                # Cycle or unresolved dep — drop everything remaining into one wave
                wave = remaining[:]
            waves.append(wave)
            for s in wave:
                completed.add(s.step_id)
                completed.add(s.kind)
            remaining = [s for s in remaining if s not in wave]
        return waves

    def _dispatch_wave(self, wave_steps: list, log_fn) -> list:
        """Dispatch all steps in a wave concurrently, await all."""
        try:
            from runtime.singleton_registry import get_registry
            disp = get_registry().get("engine.dispatcher")
        except Exception:
            disp = None
        if disp is None:
            try:
                from engine.realm_dispatcher import RealmDispatcher
                disp = RealmDispatcher()
            except Exception:
                return []

        results: list = []
        events: list = []
        result_lock = threading.Lock()

        for step in wave_steps:
            ev = threading.Event()
            box: dict = {}

            def _done(r, _b=box, _e=ev):
                _b["r"] = r
                _e.set()

            disp.dispatch_step(step, on_done=_done, log_fn=log_fn)
            events.append((ev, box))

        # Wait for all in this wave
        for ev, box in events:
            ev.wait(timeout=120.0)
            r = box.get("r")
            if r is not None:
                with result_lock:
                    results.append(r)
        return results

    def _emit_receipt(self, orch: RealmOrchestration) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="realm_orchestrator:orchestrate",
                executor="RealmOrchestrator",
                duration_ms=orch.duration_ms,
                verified=(orch.overall_outcome == "OK"),
                compute_sha256=False,
                failure_reason=(orch.error if orch.overall_outcome == "FAIL" else None),
                evidence=orch.to_dict(),
            )
        except Exception:
            pass


def _dep_satisfied(dep: str, completed: set) -> bool:
    return dep in completed


def _outcome(r: Any) -> str:
    if hasattr(r, "outcome"):
        return r.outcome
    if isinstance(r, dict):
        return r.get("outcome", "FAIL")
    return "FAIL"


_INSTANCE: Optional[RealmOrchestrator] = None


def get_realm_orchestrator() -> RealmOrchestrator:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = RealmOrchestrator()
    return _INSTANCE
