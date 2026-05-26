"""engine/refinement/critique_engine.py — structured critique per artifact.

CritiqueEngine reads (CQI, worker_outcome, spec) and emits a Critique
with strengths, weaknesses, and specific refinement targets.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Critique:
    critique_id:        str
    cqi_composite:      float
    strengths:          list      # named dimensions scoring high
    weaknesses:         list      # named dimensions scoring low
    refinement_targets: list      # concrete actionable targets
    one_line:           str
    created_at:         float

    def to_dict(self) -> dict:
        return asdict(self)


class CritiqueEngine:
    """Convert CQI + outcome into a concrete critique."""

    _STRONG = 0.75
    _WEAK   = 0.5

    def __init__(self):
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.critique", self)
        except Exception:
            pass

    def critique(self, cqi, worker_outcome=None, spec=None) -> Critique:
        t0 = time.time()
        dims = {
            "atmosphere":          cqi.atmosphere,
            "emotional_impact":    cqi.emotional_impact,
            "cinematic_intensity": cqi.cinematic_intensity,
            "visual_harmony":      cqi.visual_harmony,
            "pacing_quality":      cqi.pacing_quality,
            "thematic_coherence":  cqi.thematic_coherence,
            "originality":         cqi.originality,
            "memorability":        cqi.memorability,
        }
        strengths = sorted([k for k, v in dims.items() if v >= self._STRONG],
                            key=lambda k: -dims[k])
        weaknesses = sorted([k for k, v in dims.items() if v < self._WEAK],
                             key=lambda k: dims[k])

        targets = self._refinement_targets(dims, spec)
        one_line = self._one_line(cqi.composite, strengths, weaknesses)

        critique = Critique(
            critique_id=f"crit-{uuid.uuid4().hex[:10]}",
            cqi_composite=cqi.composite,
            strengths=strengths[:4],
            weaknesses=weaknesses[:4],
            refinement_targets=targets,
            one_line=one_line,
            created_at=t0,
        )
        self._emit_receipt(critique, (time.time() - t0) * 1000.0)
        return critique

    def _refinement_targets(self, dims: dict, spec) -> list:
        targets: list[str] = []
        if dims["atmosphere"] < self._WEAK:
            targets.append("expand atmosphere field — name the place's weather + light")
        if dims["emotional_impact"] < self._WEAK:
            targets.append("strengthen tone keyword (legendary/dark/serene/etc.)")
        if dims["cinematic_intensity"] < self._WEAK:
            targets.append("align pacing with tone — re-state intent with rhythm keywords")
        if dims["visual_harmony"] < self._WEAK:
            targets.append("specify color palette explicitly")
        if dims["pacing_quality"] < self._WEAK:
            targets.append("storyboard shape needs a clearer rise-then-resolve arc")
        if dims["thematic_coherence"] < self._WEAK:
            targets.append("scenes drift — bind them with a recurring focal noun")
        if dims["originality"] < self._WEAK:
            targets.append("intent leans on operator's defaults — try a novel style")
        if dims["memorability"] < self._WEAK:
            targets.append("add cinematic anchors (architecture, soundtrack, emotion)")
        return targets

    def _one_line(self, composite: float, strengths: list, weaknesses: list) -> str:
        if composite >= 0.85:
            return "Strong composition. Ship as-is or polish narrowly."
        if composite >= 0.65:
            shy = ", ".join(strengths[:2]) if strengths else "core elements"
            soft = ", ".join(weaknesses[:2]) if weaknesses else "—"
            return (f"Solid foundation in {shy}. Lift {soft} for premium impact.")
        if composite >= 0.45:
            soft = ", ".join(weaknesses[:3]) if weaknesses else "—"
            return f"Mid-tier. Major refinement on {soft} required."
        return ("Weak composition. Restate the intent with clearer style + tone "
                "+ atmosphere before re-dispatching.")

    def _emit_receipt(self, c: Critique, dur_ms: float) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="critique:scored",
                executor="CritiqueEngine",
                duration_ms=dur_ms, verified=True, compute_sha256=False,
                evidence={
                    "critique_id": c.critique_id,
                    "cqi_composite": c.cqi_composite,
                    "strength_count": len(c.strengths),
                    "weakness_count": len(c.weaknesses),
                    "target_count":   len(c.refinement_targets),
                },
            )
        except Exception:
            pass


_INSTANCE: Optional[CritiqueEngine] = None


def get_critique_engine() -> CritiqueEngine:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = CritiqueEngine()
    return _INSTANCE
