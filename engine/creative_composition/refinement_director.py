"""engine/creative_composition/refinement_director.py — refinement strategy.

Selects HOW a composition plan should be refined across realms based on
QualityGate + ProductionGuarantee feedback. Drives the auto-repair loop
with composition-aware corrections (rather than just re-rolling).
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


_REALM_REFINEMENTS = {
    "image":      ["bump_steps", "swap_sampler", "add_detail_lora",
                   "elevate_resolution"],
    "video":      ["increase_duration", "swap_codec", "add_transitions",
                   "tighten_pacing"],
    "audio":      ["raise_intensity", "add_harmonics", "extend_duration",
                   "rebalance_mix"],
    "game":       ["expand_world_lore", "deepen_mechanics", "add_scene_files"],
    "simulation": ["increase_tick_density", "expand_entity_count",
                   "diversify_factions"],
    "code":       ["expand_scaffold", "add_test_suite", "tighten_types"],
    "cast":       ["lengthen_synthesis", "diversify_perspectives",
                   "add_grounded_references"],
}


@dataclass(frozen=True)
class RefinementStrategy:
    strategy_id:   str
    realm:         str
    primary:       str       # the main move
    secondary:     list      # additional moves to layer in
    rationale:     str       # why this strategy
    target_score:  float
    created_at:    float

    def to_dict(self) -> dict:
        return asdict(self)


class RefinementDirector:
    """Picks refinement strategies based on failure category + realm."""

    def select(self, realm: str, failure_category: str,
                previous_score: float) -> RefinementStrategy:
        moves = list(_REALM_REFINEMENTS.get((realm or "").lower(), []))
        # Prefer different moves per failure category
        if failure_category == "low_quality":
            primary = moves[0] if moves else "re_execute"
            secondary = moves[1:3] if len(moves) > 1 else []
            rationale = ("score under threshold — apply the realm's primary "
                         "quality knob plus a secondary detail pass")
        elif failure_category == "semantic_mismatch":
            primary = "reframe_intent_emphasis"
            secondary = moves[:2]
            rationale = ("artifact did not align with intent — re-frame the "
                         "intent emphasis before re-dispatching")
        elif failure_category == "incomplete_generation":
            primary = "re_execute_with_extended_budget"
            secondary = moves[:1]
            rationale = ("incomplete output — extend the budget and retry")
        elif failure_category == "missing_backend":
            primary = "switch_backend"
            secondary = []
            rationale = ("primary backend unavailable — switch to the next "
                         "ready alternative")
        elif failure_category == "tool_failure":
            primary = "switch_backend"
            secondary = ["bump_steps"]
            rationale = ("backend errored — switch and reduce per-pass risk")
        else:
            primary = "re_execute"
            secondary = []
            rationale = "default fallback strategy"

        target = min(0.95, previous_score + 0.15)
        return RefinementStrategy(
            strategy_id=f"ref-{uuid.uuid4().hex[:8]}",
            realm=(realm or "").lower(),
            primary=primary,
            secondary=secondary,
            rationale=rationale,
            target_score=target,
            created_at=time.time(),
        )
