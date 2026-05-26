"""engine/cognitive_core.py — BUILD-020 SECTION 2: COGNITIVE CORE.

Central orchestration spine. Sits ABOVE PyramidEngine and coordinates:
  · pre-flight (which subsystems are needed for this intent)
  · realm arbitration (when intent could route to multiple realms)
  · workload prioritization (which step runs first; which can defer)
  · context continuity (carry conversation/session state across intents)
  · conflict resolution (when reflection contradicts personality)
  · event routing (everything publishes to kernel.event_bus)

NOT fake sentience. NOT consciousness simulation. The core is a
deterministic coordinator that wires the existing organs together and
emits one canonical receipt per cognitive cycle.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)


PRIORITY_LOW    = 1
PRIORITY_NORMAL = 5
PRIORITY_HIGH   = 9


@dataclass
class CognitiveCycle:
    """One end-to-end cognitive cycle initiated by an operator intent."""
    cycle_id:        str
    intent_text:     str
    started_at:      float
    priority:        int = PRIORITY_NORMAL
    arbitration:     dict = field(default_factory=dict)
    chosen_realm:    str = ""
    pre_flight:      dict = field(default_factory=dict)
    composition_plan: Any = None     # BUILD-026: CompositionPlan
    engine_session:  Any = None      # PyramidEngine.EngineSession
    reflection_followups: list = field(default_factory=list)
    state:           str = "PENDING"  # PENDING|ARBITRATING|COMPOSING|EXECUTING|REFLECTING|DONE|FAILED
    error:           str = ""

    def to_dict(self) -> dict:
        return {
            "cycle_id":      self.cycle_id,
            "intent_text":   self.intent_text[:200],
            "started_at":    self.started_at,
            "priority":      self.priority,
            "chosen_realm":  self.chosen_realm,
            "state":         self.state,
            "error":         self.error,
            "engine_state":  (self.engine_session.state
                              if self.engine_session is not None else None),
        }


class CognitiveCore:
    """Central spine. One instance per process."""

    def __init__(self):
        self._cycles_lock = threading.RLock()
        self._cycles: dict[str, CognitiveCycle] = {}
        self._cycle_history: deque = deque(maxlen=200)
        self._context_stack: deque = deque(maxlen=20)
        self._event_bus = None
        self._tick = 0
        try:
            from kernel.event_bus import get_event_bus
            self._event_bus = get_event_bus()
        except Exception:
            _log.debug("EventBus unavailable to CognitiveCore")

        # Register
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.cognitive_core", self)
        except Exception:
            pass

    # ── Public API ────────────────────────────────────────────────────
    def initiate(self, intent_text: str,
                 priority: int = PRIORITY_NORMAL,
                 on_complete: Optional[Callable[[CognitiveCycle], None]] = None,
                 log_fn: Optional[Callable[[str], None]] = None) -> CognitiveCycle:
        """Initiate a new cognitive cycle. Returns immediately; the cycle
        runs on the worker pool. on_complete is called when state=DONE
        or FAILED."""
        t0 = time.time()
        cid = f"cog-{uuid.uuid4().hex[:10]}"
        cycle = CognitiveCycle(
            cycle_id=cid, intent_text=intent_text or "",
            started_at=t0, priority=priority,
        )
        with self._cycles_lock:
            self._cycles[cid] = cycle
            self._tick += 1

        self._publish("cognitive.cycle.initiated", cycle.to_dict())

        try:
            from runtime.deferred_loader import DeferredWorkspaceLoader
        except Exception as e:
            cycle.state = "FAILED"
            cycle.error = f"deferred_loader missing: {e}"
            self._publish("cognitive.cycle.failed", cycle.to_dict())
            if on_complete:
                on_complete(cycle)
            return cycle

        def _run():
            try:
                # 1. ARBITRATING — pre-flight + realm arbitration
                cycle.state = "ARBITRATING"
                self._publish("cognitive.cycle.arbitrating", cycle.to_dict())
                cycle.arbitration = self._arbitrate(intent_text)
                cycle.chosen_realm = cycle.arbitration.get("realm", "")
                cycle.pre_flight = self._pre_flight(cycle.chosen_realm)

                # 1b. COMPOSING — BUILD-026: composition plan precedes any
                # worker dispatch. The plan is the source of truth for the
                # rest of the cycle.
                cycle.state = "COMPOSING"
                self._publish("cognitive.cycle.composing", cycle.to_dict())
                try:
                    from engine.creative_composition import get_composition_engine
                    from engine.intent_cortex import IntentCortex
                    from engine.creative_expansion import CreativeExpansionLayer
                    from engine.personality_model import get_personality
                    ic = IntentCortex(); ce = CreativeExpansionLayer()
                    enriched = ic.enrich(intent_text)
                    spec = ce.expand(enriched, get_personality())
                    cycle.composition_plan = get_composition_engine().plan(
                        intent_text, spec=spec,
                    )
                    if log_fn:
                        try: log_fn(cycle.composition_plan.render())
                        except Exception: pass
                except Exception as e:
                    _log.debug("composition planning failed: %s", e)
                    cycle.composition_plan = None

                # 2. EXECUTING — hand off to PyramidEngine
                cycle.state = "EXECUTING"
                self._publish("cognitive.cycle.executing", cycle.to_dict())
                done = threading.Event()
                from engine.pyramid_engine import get_engine
                engine = get_engine()

                def _engine_complete(session):
                    cycle.engine_session = session
                    done.set()

                engine.process_intent(intent_text,
                                       on_complete=_engine_complete,
                                       log_fn=log_fn)
                done.wait(timeout=240.0)

                # 3. REFLECTING — apply meta-reflection on top
                cycle.state = "REFLECTING"
                self._publish("cognitive.cycle.reflecting", cycle.to_dict())
                cycle.reflection_followups = self._derive_followups(cycle)

                # 4. ADAPTIVE LEARNING absorption (optional layer)
                self._adaptive_absorb(cycle)

                # 5. Context push
                self._push_context(cycle)

                cycle.state = "DONE"
                self._publish("cognitive.cycle.done", cycle.to_dict())

            except Exception as e:
                cycle.state = "FAILED"
                cycle.error = str(e)
                _log.exception("cognitive cycle %s failed: %s", cid, e)
                self._publish("cognitive.cycle.failed", cycle.to_dict())

            self._emit_receipt(cycle)
            with self._cycles_lock:
                self._cycle_history.append(cycle.to_dict())

            if on_complete:
                try:
                    on_complete(cycle)
                except Exception as e:
                    _log.debug("on_complete raised: %s", e)

        DeferredWorkspaceLoader.run(_run, on_done=None, name=f"cognitive-{cid}")
        return cycle

    def get_cycle(self, cid: str) -> Optional[CognitiveCycle]:
        with self._cycles_lock:
            return self._cycles.get(cid)

    def recent_context(self, n: int = 5) -> list:
        with self._cycles_lock:
            return list(self._context_stack)[-n:]

    def stats(self) -> dict:
        with self._cycles_lock:
            return {
                "active_cycles":   len(self._cycles),
                "history_size":    len(self._cycle_history),
                "context_depth":   len(self._context_stack),
                "tick":            self._tick,
            }

    # ── Internals ──────────────────────────────────────────────────────
    def _arbitrate(self, intent_text: str) -> dict:
        """Pick the canonical realm + classification. Uses IntentCortex
        (already deterministic). Returns a dict with realm, confidence,
        alternates."""
        result: dict = {"realm": "", "confidence": 0.5, "alternates": []}
        try:
            from runtime.singleton_registry import get_registry
            ic = get_registry().get("engine.intent_cortex")
            if ic is None:
                # PyramidEngine hasn't registered its sub-services yet —
                # construct an ephemeral IntentCortex. Cheap; deterministic.
                from engine.intent_cortex import IntentCortex
                ic = IntentCortex()
            enriched = ic.enrich(intent_text)
            realm = enriched.target_pipeline or (enriched.realm or "").lower() or "cast"
            result["realm"] = realm
            # Confidence: 1.0 if both medium AND realm resolved, 0.7 if just one
            score = 0.0
            if enriched.medium is not None:
                score += 0.5
            if enriched.realm is not None:
                score += 0.4
            if enriched.style is not None:
                score += 0.1
            result["confidence"] = round(score, 2)
            # Alternates: realms reachable through related medium hints
            if enriched.medium and enriched.medium not in (realm,):
                result["alternates"].append(enriched.medium)
            return result
        except Exception as e:
            _log.debug("arbitration failed: %s", e)
            return result

    def _pre_flight(self, realm: str) -> dict:
        """Check tool readiness for the chosen realm. Uses ToolFabric."""
        out = {"realm": realm, "ready": [], "degraded": [], "unavailable": []}
        try:
            from runtime.singleton_registry import get_registry
            tf = get_registry().get("engine.tool_fabric")
            if tf is None:
                return out
            relevant = tf.tools_for_realm(realm)
            for tool_name in relevant:
                status = tf.status(tool_name)
                if status == "READY":
                    out["ready"].append(tool_name)
                elif status == "DEGRADED":
                    out["degraded"].append(tool_name)
                else:
                    out["unavailable"].append(tool_name)
        except Exception:
            pass
        return out

    def _derive_followups(self, cycle: CognitiveCycle) -> list:
        """Post-engine meta-reflection. Adds cycle-level suggestions that
        the per-session reflection couldn't see (e.g., 'consider
        spawning a workspace constellation for this intent')."""
        followups: list[str] = []
        sess = cycle.engine_session
        if sess is None:
            return followups
        reflection = getattr(sess, "reflection", None)
        if reflection is None:
            return followups

        overall = getattr(reflection, "overall_score", 0.0) or 0.0
        if overall < 0.5:
            followups.append(
                "Overall score below 0.5 — consider auto-refinement pass or "
                "alternate realm arbitration."
            )
        # If the realm arbitration was low-confidence, hint at clarification
        if cycle.arbitration.get("confidence", 1.0) < 0.5:
            followups.append(
                f"Arbitration confidence {cycle.arbitration.get('confidence')} — "
                f"operator could clarify medium or style for stronger routing."
            )
        # If pre-flight had unavailable tools, surface them
        unavail = cycle.pre_flight.get("unavailable", [])
        if unavail:
            followups.append(
                f"Realm '{cycle.chosen_realm}' has unavailable tools: {unavail}. "
                "WorkspaceFabric will route around them but capability is degraded."
            )
        # Intent suggests a constellation? (e.g., 'movie' implies multiple rooms)
        text = (cycle.intent_text or "").lower()
        if any(kw in text for kw in ("trailer", "movie", "cinematic", "story", "narrative")):
            followups.append(
                "Intent suggests multi-realm production — WorkspaceFabric can "
                "spawn a constellation (screenplay + soundtrack + storyboard + timeline)."
            )
        return followups

    def _adaptive_absorb(self, cycle: CognitiveCycle) -> None:
        """Push the cycle into the AdaptiveLearningLayer. Lazy-imports
        if the singleton isn't registered yet (first-cycle case)."""
        try:
            from runtime.singleton_registry import get_registry
            al = get_registry().get("engine.adaptive_learning")
            if al is None:
                from engine.adaptive_learning import get_adaptive_learning
                al = get_adaptive_learning()
            if al is not None and hasattr(al, "absorb_cycle"):
                al.absorb_cycle(cycle)
        except Exception:
            pass

    def _push_context(self, cycle: CognitiveCycle) -> None:
        with self._cycles_lock:
            self._context_stack.append({
                "cycle_id":     cycle.cycle_id,
                "intent_text":  cycle.intent_text[:160],
                "realm":        cycle.chosen_realm,
                "score":        (cycle.engine_session.reflection.overall_score
                                 if (cycle.engine_session is not None and
                                     cycle.engine_session.reflection is not None)
                                 else None),
                "timestamp":    cycle.started_at,
            })

    def _publish(self, topic: str, payload: dict) -> None:
        if self._event_bus is None:
            return
        try:
            if hasattr(self._event_bus, "publish"):
                self._event_bus.publish(topic, payload)
            elif hasattr(self._event_bus, "emit"):
                self._event_bus.emit(topic, payload)
        except Exception:
            pass

    def _emit_receipt(self, cycle: CognitiveCycle) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task=f"cognitive_core:cycle:{cycle.state.lower()}",
                executor="CognitiveCore",
                duration_ms=(time.time() - cycle.started_at) * 1000.0,
                verified=(cycle.state == "DONE"),
                compute_sha256=False,
                failure_reason=cycle.error if cycle.state == "FAILED" else None,
                evidence={
                    **cycle.to_dict(),
                    "followup_count": len(cycle.reflection_followups),
                    "pre_flight": cycle.pre_flight,
                    "arbitration": cycle.arbitration,
                },
            )
        except Exception:
            pass


_CORE_INSTANCE: Optional[CognitiveCore] = None


def get_cognitive_core() -> CognitiveCore:
    global _CORE_INSTANCE
    if _CORE_INSTANCE is None:
        _CORE_INSTANCE = CognitiveCore()
    return _CORE_INSTANCE
