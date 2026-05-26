"""engine/closed_loop/loop_engine.py — P0 WORKER-FIRST EXECUTION SPINE.

Canonical chain (NON-NEGOTIABLE):

    INTENT → ROUTER → WORKER EXECUTION → ARTIFACT → VALIDATION → CQI (post-hoc)

There is NO pre-execution scoring, NO simulated candidate generation, and
NO FakeOutcome. CQI / comparison / feedback are computed ONLY from real
worker outputs that already exist on the filesystem.

Behaviour:
  · Every run() invokes WorkerRouter.route() at least once.
  · If a real artifact is produced  → state COMPLETED + CQI computed post-hoc.
  · If the worker ran but produced nothing despite a backend → state FAILED.
  · If no backend exists for the realm → state UNAVAILABLE (explicit, honest).
  · Regeneration happens ONLY when a REAL artifact scores below the refine
    threshold AND a backend is present — each regeneration is another REAL
    worker execution (bounded).
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

_log = logging.getLogger(__name__)


# CQI causal control (post-hoc, over REAL artifacts only)
_REFINE_BELOW = 0.75      # below this → regenerate (real) if backend present
_LOCK_TRAITS  = 0.85      # at/above → good enough, lock and stop
_MAX_ATTEMPTS = 4         # hard cap on real worker executions per intent
_MAX_REGEN    = 2         # regenerations beyond the first attempt

_READY_STATES = ("READY", "DEGRADED")


@dataclass
class LoopOutcome:
    loop_id:          str
    intent_text:      str
    state:            str            # COMPLETED | FAILED | UNAVAILABLE
    realm:            str = ""
    final_artifacts:  list = field(default_factory=list)   # real file dicts
    final_cqi:        Optional[float] = None
    cqi_breakdown:    dict = field(default_factory=dict)
    attempts:         int = 0
    backend_available: bool = True
    remediation:      str = ""
    worker_outcome:   Any = None     # the selected real WorkerOutcome
    output_contract:  list = field(default_factory=list)   # §5 valid output tokens
    started_at:       float = 0.0
    finished_at:      float = 0.0

    def to_dict(self) -> dict:
        return {
            "loop_id":           self.loop_id,
            "intent_text":       self.intent_text[:200],
            "state":             self.state,
            "realm":             self.realm,
            "final_artifacts":   self.final_artifacts,
            "final_cqi":         self.final_cqi,
            "cqi_breakdown":     self.cqi_breakdown,
            "attempts":          self.attempts,
            "backend_available": self.backend_available,
            "remediation":       self.remediation,
            "output_contract":   self.output_contract,
            "started_at":        self.started_at,
            "finished_at":       self.finished_at,
            "duration_ms":       (self.finished_at - self.started_at) * 1000.0
                                   if self.finished_at and self.started_at else 0.0,
        }


class ClosedLoopEngine:
    """Single canonical entry for intent execution. Worker-first."""

    def __init__(self):
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.closed_loop", self)
        except Exception:
            pass

    def run(self, intent_text: str, candidate_count: int = 1) -> LoopOutcome:
        """Execute the intent through the real worker pipeline. Blocking —
        wrap in DeferredWorkspaceLoader for async UI dispatch.

        `candidate_count` is the MAX number of real worker executions to
        spend (clamped to [1, _MAX_ATTEMPTS]). Extra executions are only
        spent when a real artifact scores below the refine threshold.
        """
        from engine.worker_router import get_worker_router
        from engine.workers.base_worker import WorkerRequest
        from engine.intent_cortex import IntentCortex
        from engine.creative_expansion import CreativeExpansionLayer
        from engine.personality_model import get_personality

        t0 = time.time()
        loop_id = f"loop-{uuid.uuid4().hex[:10]}"
        cap = max(1, min(int(candidate_count or 1), _MAX_ATTEMPTS))

        outcome = LoopOutcome(loop_id=loop_id, intent_text=intent_text or "",
                               state="RUNNING", started_at=t0)

        # ── 1. INTENT enrichment → realm + spec (no scoring here) ──────────
        enriched = IntentCortex().enrich(intent_text)
        realm = (getattr(enriched, "target_pipeline", None)
                 or (getattr(enriched, "realm", None) or "").lower()
                 or "cast")
        outcome.realm = realm
        try:
            spec = CreativeExpansionLayer().expand(enriched, get_personality())
        except Exception:
            spec = enriched   # EnrichedIntent exposes style/tone/etc. defensively

        self._emit_event("closed_loop_started", {
            "loop_id": loop_id, "intent_text": (intent_text or "")[:160],
            "realm": realm,
        })

        router = get_worker_router()

        best_outcome = None
        best_cqi = None
        best_composite = -1.0
        backend_available = True

        # ── 2. WORKER-FIRST execution loop (real artifacts only) ───────────
        attempt = 0
        regens = 0
        while attempt < cap:
            attempt += 1
            request = WorkerRequest(
                intent_text=intent_text or "",
                spec=spec,
                kind=(getattr(enriched, "medium", "") or ""),
                params={"loop_id": loop_id, "attempt": attempt},
                refinement_pass=regens,
            )

            # REAL execution — router runs the worker through the guarantee
            # layer (which now fails OPEN). Worker emits worker_* bus events.
            worker_outcome = router.route(realm, request)
            state = getattr(worker_outcome, "state", "FAIL")
            real_arts = self._real_artifacts(worker_outcome)

            # Explicit backend-absence detection (rule 4c)
            err = (getattr(worker_outcome, "error", "") or "")
            if "UNAVAILABLE_REAL_EXECUTION" in err:
                backend_available = False
                outcome.remediation = getattr(worker_outcome, "remediation", "") or err
                break

            if state in _READY_STATES and real_arts:
                # ── 3. POST-HOC CQI — computed from the REAL artifact ──────
                cqi, composite = self._post_hoc_cqi(spec, worker_outcome)
                self._emit_cqi(loop_id, attempt, cqi, composite, real_arts)

                if composite > best_composite:
                    best_outcome = worker_outcome
                    best_cqi = cqi
                    best_composite = composite

                self._emit_event("closed_loop_cycle_complete", {
                    "loop_id": loop_id, "cycle": attempt - 1,
                    "candidate_count": 1, "best_score": round(composite, 3),
                    "needs_regen": composite < _REFINE_BELOW,
                })

                # ── 4. Regeneration decision (over REAL output) ────────────
                if composite >= _LOCK_TRAITS:
                    break                       # good enough — stop spending
                if composite >= _REFINE_BELOW:
                    break                       # acceptable — no regen needed
                if regens >= _MAX_REGEN:
                    break                       # bounded
                regens += 1
                continue                        # regenerate (real execution)
            else:
                # Worker ran but produced no valid artifact. Not a backend
                # absence (that broke above). Record and stop.
                outcome.remediation = (getattr(worker_outcome, "remediation", "")
                                        or "worker produced no valid artifact")
                if best_outcome is None:
                    best_outcome = worker_outcome
                break

        # ── 5. FINAL SELECTION — real artifact or explicit unavailability ──
        outcome.attempts = attempt
        outcome.backend_available = backend_available
        outcome.worker_outcome = best_outcome

        final_arts = self._real_artifacts(best_outcome)
        if final_arts:
            outcome.state = "COMPLETED"
            outcome.final_artifacts = final_arts
            outcome.final_cqi = round(best_composite, 3) if best_composite >= 0 else None
            outcome.cqi_breakdown = (getattr(best_cqi, "breakdown", {}) or {}) if best_cqi else {}
            # POST-HOC metrics: attach CQI to the REAL ledger entry created by
            # the WorkerRouter hook. Never creates a CQI-only memory row.
            try:
                from engine.mem_palace.memory_store import get_mem_palace
                exec_id = getattr(best_outcome, "_mem_execution_id", None)
                if exec_id and best_cqi is not None:
                    get_mem_palace().attach_metrics(exec_id, best_cqi)
            except Exception:
                pass
        elif not backend_available:
            outcome.state = "UNAVAILABLE"
        else:
            outcome.state = "FAILED"

        outcome.finished_at = time.time()
        outcome.output_contract = self._build_output_contract(outcome)
        self._emit_completion(outcome)
        self._emit_output_contract(outcome)
        self._emit_receipt(outcome)
        return outcome

    # ── §5 OUTPUT CONTRACT — the ONLY valid output tokens ──────────────
    def _build_output_contract(self, outcome: LoopOutcome) -> list:
        """Emit only the five legal output types, each tied to real files."""
        tokens: list = []
        if outcome.state == "COMPLETED" and outcome.final_artifacts:
            for a in outcome.final_artifacts:
                p = a.get("path", "")
                tokens.append(f"FILE_CREATED: {p}")
                tokens.append(f"VALIDATED: {p}")
            wn = getattr(outcome.worker_outcome, "worker_name", None) or "worker"
            tokens.append(f"WORKER_COMPLETED: {wn}")
        elif outcome.state == "UNAVAILABLE":
            tokens.append(f"UNAVAILABLE: {outcome.remediation or ('no backend for realm ' + outcome.realm)}")
        else:  # FAILED (or any non-completed, non-unavailable)
            tokens.append(f"FAILED: {outcome.remediation or 'no valid artifact produced'}")
        return tokens

    def _emit_output_contract(self, outcome: LoopOutcome) -> None:
        self._emit_event("output_contract", {
            "loop_id": outcome.loop_id,
            "realm": outcome.realm,
            "tokens": outcome.output_contract,
        })

    # ── Internals ──────────────────────────────────────────────────────
    def _real_artifacts(self, worker_outcome) -> list:
        """Return only artifacts that EXIST on disk and passed validation."""
        if worker_outcome is None:
            return []
        out = []
        for a in (getattr(worker_outcome, "artifacts", []) or []):
            if isinstance(a, dict) and a.get("exists") \
                    and a.get("validation", {}).get("valid") \
                    and a.get("size_bytes", 0) > 0:
                out.append(a)
        return out

    def _post_hoc_cqi(self, spec, worker_outcome):
        """Compute CQI from the REAL worker outcome. Secondary metadata —
        never gates execution. Returns (CQI|None, composite_float)."""
        try:
            from engine.aesthetic_intelligence.aesthetic_reasoner import get_aesthetic_reasoner
            cqi = get_aesthetic_reasoner().score(
                spec=spec, composition_plan=None, worker_outcome=worker_outcome)
            composite = float(getattr(cqi, "composite", 0.0) or 0.0)
            return cqi, composite
        except Exception as e:
            _log.debug("post-hoc CQI failed: %s", e)
            # Fall back to the worker's own validation score as the metric.
            comp = float(getattr(worker_outcome, "overall_validation_score", 0.0) or 0.0)
            return None, comp

    def _emit_cqi(self, loop_id, attempt, cqi, composite, real_arts):
        if cqi is None:
            return
        try:
            self._emit_event("cqi_scored", {
                "loop_id": loop_id, "attempt": attempt,
                "composite": round(composite, 3),
                "atmosphere": round(getattr(cqi, "atmosphere", 0.0), 3),
                "emotional_impact": round(getattr(cqi, "emotional_impact", 0.0), 3),
                "cinematic_intensity": round(getattr(cqi, "cinematic_intensity", 0.0), 3),
                "visual_harmony": round(getattr(cqi, "visual_harmony", 0.0), 3),
                "memorability": round(getattr(cqi, "memorability", 0.0), 3),
                "artifact": real_arts[0].get("path", "") if real_arts else "",
                "post_hoc": True,
            })
        except Exception:
            pass

    def _emit_completion(self, outcome: LoopOutcome) -> None:
        if outcome.state == "COMPLETED":
            self._emit_event("closed_loop_completed", {
                "loop_id": outcome.loop_id,
                "realm": outcome.realm,
                "attempts": outcome.attempts,
                "winning_score": outcome.final_cqi,
                "artifact_count": len(outcome.final_artifacts),
            })
        elif outcome.state == "UNAVAILABLE":
            self._emit_event("closed_loop_unavailable", {
                "loop_id": outcome.loop_id, "realm": outcome.realm,
                "remediation": outcome.remediation[:200],
            })
        else:
            self._emit_event("closed_loop_failed", {
                "loop_id": outcome.loop_id, "realm": outcome.realm,
                "remediation": outcome.remediation[:200],
            })

    def _emit_event(self, kind: str, payload: dict) -> None:
        try:
            from engine.live_stream import get_live_stream
            get_live_stream().emit_event(kind, payload)
        except Exception:
            pass

    def _emit_receipt(self, outcome: LoopOutcome) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task=f"closed_loop:run:{outcome.state.lower()}",
                executor="ClosedLoopEngine",
                duration_ms=(outcome.finished_at - outcome.started_at) * 1000.0
                              if outcome.finished_at and outcome.started_at else 0.0,
                verified=(outcome.state == "COMPLETED"),
                compute_sha256=False,
                evidence={
                    "loop_id":         outcome.loop_id,
                    "state":           outcome.state,
                    "realm":           outcome.realm,
                    "attempts":        outcome.attempts,
                    "artifact_count":  len(outcome.final_artifacts),
                    "final_cqi":       outcome.final_cqi,
                    "backend":         outcome.backend_available,
                    "intent_text":     outcome.intent_text[:120],
                },
            )
        except Exception:
            pass


_INSTANCE: Optional[ClosedLoopEngine] = None


def get_closed_loop_engine() -> ClosedLoopEngine:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ClosedLoopEngine()
    return _INSTANCE
