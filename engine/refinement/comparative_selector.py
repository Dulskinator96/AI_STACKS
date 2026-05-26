"""engine/refinement/comparative_selector.py — choose best of N variations."""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SelectionResult:
    selection_id:  str
    chosen_index:  int
    chosen_score:  float
    runner_up_index: int
    runner_up_score: float
    rationale:     str
    candidate_scores: list


class ComparativeSelector:
    """Picks the best of N variations using CQI composites."""

    def __init__(self):
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.comparative_selector", self)
        except Exception:
            pass

    def select(self, candidates: list) -> Optional[SelectionResult]:
        """candidates: list of (worker_outcome, cqi) tuples. Returns
        SelectionResult or None if list empty."""
        if not candidates:
            return None
        scores = []
        for i, (outcome, cqi) in enumerate(candidates):
            composite = float(getattr(cqi, "composite", 0.0) or 0.0)
            worker_score = float(getattr(outcome, "overall_validation_score", 0.0) or 0.0)
            blended = 0.7 * composite + 0.3 * worker_score
            scores.append((i, blended, composite, worker_score))
        scores.sort(key=lambda t: -t[1])
        top = scores[0]
        runner = scores[1] if len(scores) > 1 else (top[0], 0.0, 0.0, 0.0)
        rationale = (f"chose #{top[0]} (CQI {top[2]:.2f} · worker {top[3]:.2f} → "
                     f"blended {top[1]:.2f}) over #{runner[0]} blended {runner[1]:.2f}")
        result = SelectionResult(
            selection_id=f"sel-{uuid.uuid4().hex[:8]}",
            chosen_index=top[0],
            chosen_score=top[1],
            runner_up_index=runner[0],
            runner_up_score=runner[1],
            rationale=rationale,
            candidate_scores=[(s[0], s[1]) for s in scores],
        )
        self._emit_receipt(result)
        return result

    def _emit_receipt(self, r: SelectionResult) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="refinement:comparative_selection",
                executor="ComparativeSelector",
                duration_ms=0.0, verified=True, compute_sha256=False,
                evidence={
                    "selection_id":   r.selection_id,
                    "chosen_index":   r.chosen_index,
                    "chosen_score":   r.chosen_score,
                    "candidate_count": len(r.candidate_scores),
                },
            )
        except Exception:
            pass


_INSTANCE: Optional[ComparativeSelector] = None


def get_comparative_selector() -> ComparativeSelector:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ComparativeSelector()
    return _INSTANCE
