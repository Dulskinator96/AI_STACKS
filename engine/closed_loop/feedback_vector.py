"""engine/closed_loop/feedback_vector.py — BUILD-029 SECTION 4.

The FeedbackVector is emitted after every comparative selection and
MUST modify the next generation cycle. NOT optional. NOT advisory.

Shape:
{
  "composition_bias": {grammar_name: delta},
  "tone_bias":        {tone_name: delta},
  "pacing_bias":      {pacing_name: delta},
  "style_bias":       {style_name: delta},
  "entropy_adjustment": float,        # 0..1, higher = more candidate divergence
  "forbidden_patterns": [str, ...],    # axes the next cycle must avoid
  "preferred_patterns": [str, ...],    # axes the next cycle should emphasize
}
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass(frozen=True)
class FeedbackVector:
    vector_id:           str
    composition_bias:    dict
    tone_bias:           dict
    pacing_bias:         dict
    style_bias:          dict
    entropy_adjustment:  float
    forbidden_patterns:  list
    preferred_patterns:  list
    strength_sources:    list   # which axes are working well
    failure_sources:     list   # which axes are weak
    transferable_traits: list   # successful traits to inherit next cycle
    removal_targets:     list   # traits to strip next cycle
    created_at:          float
    cycle_index:         int    # 0-based; which generation cycle produced this

    def to_dict(self) -> dict:
        return asdict(self)

    def render(self) -> str:
        return (
            f"📡 FeedbackVector (cycle {self.cycle_index}) entropy={self.entropy_adjustment:+.2f}\n"
            f"   preferred: {self.preferred_patterns[:4]}\n"
            f"   forbidden: {self.forbidden_patterns[:4]}\n"
            f"   transferable: {self.transferable_traits[:4]}\n"
            f"   removal: {self.removal_targets[:4]}"
        )

    def has_signal(self) -> bool:
        """True if this vector carries any directive that would actually
        modify the next cycle. A zero vector is a sign of no learning."""
        return bool(
            self.composition_bias or
            self.tone_bias or
            self.pacing_bias or
            self.style_bias or
            abs(self.entropy_adjustment) > 1e-6 or
            self.forbidden_patterns or
            self.preferred_patterns or
            self.transferable_traits or
            self.removal_targets
        )


def get_zero_feedback() -> FeedbackVector:
    """Initial state before any cycle has run."""
    return FeedbackVector(
        vector_id=f"fv-zero-{uuid.uuid4().hex[:6]}",
        composition_bias={}, tone_bias={}, pacing_bias={}, style_bias={},
        entropy_adjustment=0.0,
        forbidden_patterns=[], preferred_patterns=[],
        strength_sources=[], failure_sources=[],
        transferable_traits=[], removal_targets=[],
        created_at=time.time(),
        cycle_index=0,
    )
