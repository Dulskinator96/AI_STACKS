"""engine/pyramid_engine.py — PHASE 2: CENTRAL ENGINE.

Composes IntentCortex · PersonalityModel · CreativeExpansionLayer ·
ExecutionPlanner · RealmDispatcher · ReflectionEngine · OutputRenderer ·
MemoryContextBridge · ToolRouter into one orchestration flow.

Single public entry point:
    engine.process_intent(text, on_progress=..., on_complete=...)

`process_intent` is asynchronous — the heavy work (memory recall,
dispatch, reflection) all runs through DeferredWorkspaceLoader so the
UI thread is never blocked.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)


@dataclass
class EngineSession:
    """Per-intent state held by the engine while a pipeline runs."""
    session_id:        str
    raw_text:          str
    started_at:        float
    enriched:          Any = None        # EnrichedIntent
    spec:              Any = None        # ExpandedSpec
    graph:             Any = None        # ExecutionGraph
    memory_context:    dict = field(default_factory=dict)
    dispatch_results:  list = field(default_factory=list)
    reflection:        Any = None        # ReflectionReport
    final_output:      Any = None        # ChamberOutput
    state:             str = "INITIATED" # INITIATED | ENRICHED | EXPANDED | PLANNED | DISPATCHING | REFLECTING | DONE | FAILED
    error:             str = ""

    def to_dict(self) -> dict:
        return {
            "session_id":  self.session_id,
            "raw_text":    self.raw_text,
            "started_at":  self.started_at,
            "state":       self.state,
            "error":       self.error,
            "step_count":  (self.graph.step_count() if self.graph is not None
                             and hasattr(self.graph, "step_count") else 0),
            "dispatch_count": len(self.dispatch_results),
            "overall_score": (self.reflection.overall_score
                               if self.reflection is not None else None),
        }


class PyramidEngine:
    """Central Intent-Centered Creative Intelligence Engine."""

    def __init__(self):
        from engine.intent_cortex      import IntentCortex
        from engine.personality_model  import get_personality
        from engine.creative_expansion import CreativeExpansionLayer
        from engine.execution_planner  import ExecutionPlanner
        from engine.realm_dispatcher   import RealmDispatcher
        from engine.tool_router        import ToolRouter
        from engine.reflection_engine  import ReflectionEngine
        from engine.output_renderer    import OutputRenderer
        from engine.memory_context_bridge import MemoryContextBridge

        self.intent_cortex    = IntentCortex()
        self.personality      = get_personality()
        self.expansion        = CreativeExpansionLayer()
        self.planner          = ExecutionPlanner()
        self.dispatcher       = RealmDispatcher()
        self.tool_router      = ToolRouter()
        self.reflection       = ReflectionEngine()
        self.output_renderer  = OutputRenderer()
        self.memory_bridge    = MemoryContextBridge()

        self._active_sessions: dict[str, EngineSession] = {}
        self._sessions_lock = threading.Lock()
        self._total_processed = 0

        self._register_self()

    def _register_self(self) -> None:
        try:
            from runtime.singleton_registry import get_registry
            reg = get_registry()
            reg.register("engine.pyramid", self)
            reg.register("engine.intent_cortex", self.intent_cortex)
            reg.register("engine.expansion", self.expansion)
            reg.register("engine.planner", self.planner)
            reg.register("engine.dispatcher", self.dispatcher)
            reg.register("engine.reflection", self.reflection)
            reg.register("engine.output_renderer", self.output_renderer)
            reg.register("engine.tool_router", self.tool_router)
            reg.register("engine.memory_bridge", self.memory_bridge)
        except Exception:
            pass

    # ── Public API ────────────────────────────────────────────────────
    def process_intent(self, text: str,
                        on_progress: Optional[Callable[[str, EngineSession], None]] = None,
                        on_complete: Optional[Callable[[EngineSession], None]] = None,
                        log_fn: Optional[Callable[[str], None]] = None) -> EngineSession:
        """Submit one intent through the full pipeline.

        Returns the EngineSession synchronously (state=INITIATED). All
        heavy work happens on worker threads. on_progress fires at each
        state transition; on_complete fires with state=DONE or FAILED.
        """
        t0 = time.time()
        sid = f"engine-{int(t0*1000):x}"
        session = EngineSession(
            session_id=sid,
            raw_text=text or "",
            started_at=t0,
        )
        with self._sessions_lock:
            self._active_sessions[sid] = session

        def _emit(state: str):
            session.state = state
            if log_fn:
                try: log_fn(f"engine ▸ {state}")
                except Exception: pass
            if on_progress:
                try: on_progress(state, session)
                except Exception as e:
                    _log.debug("on_progress raised: %s", e)

        # Hand off to the worker pipeline.
        try:
            from runtime.deferred_loader import DeferredWorkspaceLoader
        except Exception as e:
            session.state = "FAILED"
            session.error = f"deferred_loader missing: {e}"
            if on_complete:
                on_complete(session)
            return session

        def _pipeline():
            try:
                # 1. ENRICHED — intent_cortex
                session.enriched = self.intent_cortex.enrich(session.raw_text)
                _emit("ENRICHED")

                # 2. memory context (best-effort)
                try:
                    session.memory_context = self.memory_bridge.recall(
                        session.raw_text, limit=5
                    )
                except Exception:
                    session.memory_context = {}

                # 3. EXPANDED — creative_expansion layered on personality
                session.spec = self.expansion.expand(session.enriched, self.personality)
                _emit("EXPANDED")

                # 4. PLANNED — execution_planner
                session.graph = self.planner.plan(session.spec)
                _emit("PLANNED")

                # 5. DISPATCHING — realm_dispatcher (parallel where deps allow,
                #    but most graphs are small — sequential is fine for v1).
                _emit("DISPATCHING")
                self._dispatch_all(session, log_fn)

                # 6. REFLECTING — reflection_engine
                session.reflection = self.reflection.reflect(
                    session.spec, session.graph, session.dispatch_results
                )
                _emit("REFLECTING")

                # 7. RENDERED — output_renderer
                session.final_output = self.output_renderer.render(
                    session.enriched, session.spec, session.graph,
                    session.dispatch_results, session.reflection,
                )

                # 8. PERSONALITY UPDATE — absorb the intent + outcome
                try:
                    self.personality.absorb_intent(session.enriched)
                    overall_outcome = "OK" if session.reflection.overall_score >= 0.6 \
                                      else "DEGRADED"
                    self.personality.absorb_output(
                        session.raw_text, session.graph.realm, overall_outcome
                    )
                except Exception:
                    pass

                session.state = "DONE"
                self._total_processed += 1
                self._emit_session_receipt(session, success=True)

            except Exception as e:
                session.state = "FAILED"
                session.error = str(e)
                _log.exception("engine pipeline failed: %s", e)
                self._emit_session_receipt(session, success=False)

            if on_complete:
                try: on_complete(session)
                except Exception as e:
                    _log.debug("on_complete raised: %s", e)

            with self._sessions_lock:
                # Keep the session around for one minute then drop, so other
                # surfaces (chamber log, dashboards) can query it briefly.
                threading.Timer(
                    60.0, lambda: self._drop_session(sid)
                ).start()

        DeferredWorkspaceLoader.run(_pipeline, on_done=None, name=f"engine-{sid}")
        return session

    def _dispatch_all(self, session: EngineSession, log_fn) -> None:
        """Sequential dispatch with per-step receipts. Each backend's
        availability is probed first inside RealmDispatcher._execute."""
        for step in session.graph.steps:
            done = threading.Event()
            box: dict = {}

            def _on_done(result, _box=box, _done=done):
                _box["r"] = result
                _done.set()

            self.dispatcher.dispatch_step(step, on_done=_on_done, log_fn=log_fn)
            done.wait(timeout=60.0)
            r = box.get("r")
            if r is None:
                # Timeout: synthesize a FAIL result so the planner can see it
                from engine.realm_dispatcher import DispatchResult
                r = DispatchResult(
                    step_id=step.step_id, kind=step.kind, backend=step.backend,
                    realm=step.realm, outcome="FAIL",
                    error="dispatch timeout (60s)",
                    remediation="audit backend availability + raise step timeout if intentional",
                )
            session.dispatch_results.append(r)

    def _drop_session(self, sid: str) -> None:
        with self._sessions_lock:
            self._active_sessions.pop(sid, None)

    def session(self, sid: str) -> Optional[EngineSession]:
        with self._sessions_lock:
            return self._active_sessions.get(sid)

    def stats(self) -> dict:
        with self._sessions_lock:
            return {
                "total_processed":   self._total_processed,
                "active_sessions":   len(self._active_sessions),
                "session_states":    {s.session_id: s.state
                                      for s in self._active_sessions.values()},
            }

    def _emit_session_receipt(self, session: EngineSession, success: bool) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task=f"pyramid_engine:session:{session.state.lower()}",
                executor="PyramidEngine",
                duration_ms=(time.time() - session.started_at) * 1000.0,
                verified=success,
                compute_sha256=False,
                failure_reason=session.error if not success else None,
                evidence=session.to_dict(),
            )
        except Exception:
            pass


_ENGINE_INSTANCE: Optional[PyramidEngine] = None


def get_engine() -> PyramidEngine:
    global _ENGINE_INSTANCE
    if _ENGINE_INSTANCE is None:
        _ENGINE_INSTANCE = PyramidEngine()
    return _ENGINE_INSTANCE
