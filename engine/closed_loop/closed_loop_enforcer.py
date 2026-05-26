"""engine/closed_loop/closed_loop_enforcer.py — BUILD-029 SECTION 6.

Verifies before final output:
  · generation_count >= 3
  · comparison_completed == True
  · feedback_vector_applied == True
  · regeneration_evaluated_if_needed == True

If ANY fails → OUTPUT BLOCKED + LOOP must restart.

Reality Enforcement: the enforcer DOES NOT auto-restart. It returns an
explicit allowed/blocked decision; callers (ClosedLoopEngine) handle
the restart. This keeps responsibility explicit + receipts auditable.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class LoopState:
    loop_id:                str
    intent_text:            str
    generation_count:       int = 0       # total candidates produced across cycles
    cycle_count:            int = 0       # how many full cycles have run
    comparison_completed:   bool = False
    feedback_vector_applied: bool = False  # at least one cycle was biased by prior FV
    regeneration_evaluated: bool = False   # the decision to regen was made (yes or no)
    locked_traits:          list = field(default_factory=list)  # CQI ≥ 0.85 trait locks
    rejected_count:         int = 0       # candidates with CQI < 0.50
    cycles:                 list = field(default_factory=list)   # per-cycle data
    started_at:             float = 0.0
    finished_at:            float = 0.0
    final_winner_id:        str = ""

    def to_dict(self) -> dict:
        # Don't serialize raw cycle payloads (may contain non-JSON objects)
        return {
            "loop_id":                self.loop_id,
            "intent_text":            self.intent_text[:200],
            "generation_count":       self.generation_count,
            "cycle_count":            self.cycle_count,
            "comparison_completed":   self.comparison_completed,
            "feedback_vector_applied":self.feedback_vector_applied,
            "regeneration_evaluated": self.regeneration_evaluated,
            "locked_trait_count":     len(self.locked_traits),
            "rejected_count":         self.rejected_count,
            "cycle_count_tracked":    len(self.cycles),
            "started_at":             self.started_at,
            "finished_at":            self.finished_at,
            "duration_ms":            (self.finished_at - self.started_at) * 1000.0
                                        if self.finished_at and self.started_at else 0.0,
            "final_winner_id":        self.final_winner_id,
        }


class ClosedLoopEnforcer:
    """Verifies the 4 invariants before allowing final output."""

    def __init__(self):
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.closed_loop_enforcer", self)
        except Exception:
            pass

    def verify(self, state: LoopState) -> tuple:
        """Return (allowed: bool, reasons: list[str])."""
        reasons: list[str] = []
        if state.generation_count < 3:
            reasons.append(f"generation_count {state.generation_count} < 3")
        if not state.comparison_completed:
            reasons.append("comparison_completed == False")
        if not state.feedback_vector_applied:
            # First-cycle exception: if cycle_count is 1, feedback application
            # is not yet possible because there's nothing to feed back FROM.
            # But the vector MUST have been EMITTED — that's what feedback
            # _applied flag tracks: either applied to a next cycle OR no next
            # cycle was needed and the vector was emitted as final-state.
            reasons.append("feedback_vector_applied == False")
        if not state.regeneration_evaluated:
            reasons.append("regeneration_evaluated == False")
        allowed = len(reasons) == 0
        self._emit_receipt(state, allowed, reasons)
        return allowed, reasons

    def _emit_receipt(self, state: LoopState, allowed: bool, reasons: list) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task=f"closed_loop:enforcer:{'allow' if allowed else 'block'}",
                executor="ClosedLoopEnforcer",
                duration_ms=0.0,
                verified=allowed,
                compute_sha256=False,
                failure_reason=("; ".join(reasons) if not allowed else None),
                evidence={
                    **state.to_dict(),
                    "block_reasons": reasons,
                },
            )
        except Exception:
            pass


_INSTANCE: Optional[ClosedLoopEnforcer] = None


def get_closed_loop_enforcer() -> ClosedLoopEnforcer:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ClosedLoopEnforcer()
    return _INSTANCE
