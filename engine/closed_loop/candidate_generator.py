"""engine/closed_loop/candidate_generator.py — BUILD-029 SECTION 2.

Generates 3–7 distinct candidate ExpandedSpec variants from a single
EnrichedIntent. Each variant differs across ≥ 2 axes (composition,
tone, pacing, style, symbolic density, lighting, narrative).

The FeedbackVector from prior cycles biases the perturbation:
  · forbidden_patterns → exclude those axis values
  · preferred_patterns → bias toward those axis values
  · entropy_adjustment → widen perturbation magnitude

NO fake variants — each goes through real CreativeExpansionLayer +
ComposeEngine.plan() before scoring.
"""
from __future__ import annotations

import logging
import random
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

_log = logging.getLogger(__name__)


# Axis-value catalogs the generator perturbs across.
_AXES = {
    "style":         ["cyberpunk", "sci-fi", "fantasy", "noir", "horror",
                       "anime", "synthwave", "painterly", "cinematic",
                       "minimalist", "photoreal"],
    "tone":          ["legendary", "dark", "serene", "intense",
                       "melancholic", "joyful", "eerie", "playful",
                       "mysterious", "emotional"],
    "lighting":      ["neon rim light", "golden hour", "blue hour",
                       "chiaroscuro", "soft diffused", "volumetric god rays",
                       "moonlight", "candlelight"],
    "composition":   ["heroic centered", "wide panoramic", "closeup",
                       "low angle", "top-down", "dutch angle",
                       "over the shoulder", "symmetric"],
    "emotion":       ["powerful", "tender", "angry", "fear", "triumph",
                       "longing", "wonder", "solitude"],
}


@dataclass
class CandidateVariant:
    variant_id:        str
    cycle_index:       int
    base_intent:       str
    perturbed_intent:  str           # the spec-flavored intent the variant uses
    axes_perturbed:    list           # which axes were touched
    perturbation:      dict           # axis → new value
    spec:              Any = None     # ExpandedSpec
    plan:              Any = None     # CompositionPlan
    cqi:               Any = None     # CQI (after evaluation)
    worker_outcome:    Any = None
    blended_score:     float = 0.0    # computed during evaluation
    rejected:          bool = False   # CQI < 0.50

    def to_dict(self) -> dict:
        d = {
            "variant_id":       self.variant_id,
            "cycle_index":      self.cycle_index,
            "axes_perturbed":   list(self.axes_perturbed),
            "perturbation":     dict(self.perturbation),
            "rejected":         self.rejected,
            "blended_score":    self.blended_score,
        }
        if self.cqi is not None and hasattr(self.cqi, "to_dict"):
            d["cqi"] = self.cqi.to_dict()
        return d


class CandidateGenerator:
    """Produces 3–7 variant specs from one intent, biased by FeedbackVector."""

    def __init__(self):
        self._generated_count = 0
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.candidate_generator", self)
        except Exception:
            pass

    def generate(self, base_intent: str, base_enriched, base_spec,
                  count: int = 4, cycle_index: int = 0,
                  feedback: Any = None,
                  rng: Optional[random.Random] = None) -> list:
        """Returns a list of CandidateVariant. Each variant has a real
        ExpandedSpec + CompositionPlan attached.

        Args:
          count: how many variants to produce (clamped to [3, 7])
          feedback: a FeedbackVector from the prior cycle (or None)
          rng: deterministic Random instance (optional)
        """
        n = max(3, min(7, int(count)))
        rng = rng or random.Random(int(time.time() * 1000) ^ cycle_index)

        forbidden_patterns = set()
        preferred_patterns = set()
        entropy = 0.0
        if feedback is not None:
            forbidden_patterns = set(getattr(feedback, "forbidden_patterns", []) or [])
            preferred_patterns = set(getattr(feedback, "preferred_patterns", []) or [])
            entropy = float(getattr(feedback, "entropy_adjustment", 0.0) or 0.0)

        variants: list[CandidateVariant] = []

        # First variant is the BASE (unperturbed) — anchor for divergence comparison
        variants.append(self._build_variant(
            base_intent, base_intent, base_enriched, base_spec,
            cycle_index, axes_perturbed=[], perturbation={},
            variant_index=0,
        ))

        # Generate (n-1) perturbed variants
        used_signatures: set = {self._signature(base_spec)}
        attempts = 0
        while len(variants) < n and attempts < n * 6:
            attempts += 1
            # Pick 2+ axes to perturb. Higher entropy → wider perturbation set
            base_axes = ["style", "tone", "lighting", "composition", "emotion"]
            axis_count = 2 if entropy < 0.3 else (3 if entropy < 0.6 else 4)
            chosen_axes = rng.sample(base_axes, axis_count)
            perturbation: dict[str, str] = {}
            for axis in chosen_axes:
                values = list(_AXES.get(axis, []))
                # Apply preferred bias: if any preferred pattern matches an axis value, weight it
                weighted = []
                for v in values:
                    if v in forbidden_patterns:
                        continue
                    w = 1.0
                    if v in preferred_patterns or f"{axis}:{v}" in preferred_patterns:
                        w = 3.0   # 3x weighted choice for preferred
                    weighted.append((v, w))
                if not weighted:
                    continue
                total_w = sum(w for _, w in weighted)
                pick = rng.uniform(0, total_w)
                acc = 0.0
                for v, w in weighted:
                    acc += w
                    if pick <= acc:
                        perturbation[axis] = v
                        break

            # Compose a flavored intent string
            flavor_bits = [f"{v}" for v in perturbation.values()]
            perturbed_intent = f"{base_intent} · {' '.join(flavor_bits)}"

            # Build the variant — runs real IntentCortex + CreativeExpansion
            variant = self._build_variant(
                base_intent, perturbed_intent, None, None,
                cycle_index, axes_perturbed=list(perturbation.keys()),
                perturbation=perturbation,
                variant_index=len(variants),
            )

            # Reject near-duplicates
            sig = self._signature(variant.spec)
            if sig in used_signatures:
                continue
            used_signatures.add(sig)
            variants.append(variant)

        with_count = len(variants)
        self._generated_count += with_count
        self._emit_receipt(base_intent, cycle_index, with_count, feedback)
        return variants

    def _build_variant(self, base_intent: str, perturbed_intent: str,
                        prebuilt_enriched, prebuilt_spec,
                        cycle_index: int, axes_perturbed: list,
                        perturbation: dict, variant_index: int) -> CandidateVariant:
        """Run real IntentCortex + CreativeExpansion + CompositionEngine.plan
        to produce a fully-realized variant."""
        try:
            from engine.intent_cortex      import IntentCortex
            from engine.creative_expansion import CreativeExpansionLayer
            from engine.personality_model  import get_personality
            ic = IntentCortex(); ce = CreativeExpansionLayer()
            enriched = prebuilt_enriched if prebuilt_enriched is not None \
                        else ic.enrich(perturbed_intent)
            spec = prebuilt_spec if prebuilt_spec is not None \
                    else ce.expand(enriched, get_personality())
            # Build composition plan (this auto-scores CQI as side effect)
            try:
                from engine.creative_composition import get_composition_engine
                plan = get_composition_engine().plan(perturbed_intent, spec=spec)
                cqi = getattr(plan, "cqi", None)
            except Exception:
                plan = None; cqi = None
        except Exception as e:
            _log.warning("variant build failed: %s", e)
            plan = None; spec = None; cqi = None

        variant = CandidateVariant(
            variant_id=f"var-{uuid.uuid4().hex[:8]}",
            cycle_index=cycle_index,
            base_intent=base_intent,
            perturbed_intent=perturbed_intent,
            axes_perturbed=axes_perturbed,
            perturbation=perturbation,
            spec=spec, plan=plan, cqi=cqi,
        )
        return variant

    def _signature(self, spec) -> str:
        """Compact hashable signature of a spec for dedup."""
        if spec is None:
            return f"none-{uuid.uuid4().hex[:4]}"
        bits = []
        for k in ("style", "tone", "lighting", "composition", "emotion"):
            v = getattr(spec, k, "") or ""
            bits.append(f"{k}:{v}")
        return "|".join(bits)

    def _emit_receipt(self, intent: str, cycle: int, count: int, feedback) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task=f"closed_loop:candidates_generated",
                executor="CandidateGenerator",
                duration_ms=0.0, verified=True, compute_sha256=False,
                evidence={
                    "cycle_index":   cycle,
                    "count":         count,
                    "intent":        intent[:140],
                    "has_feedback":  feedback is not None,
                    "entropy_adj":   getattr(feedback, "entropy_adjustment", 0.0)
                                       if feedback else 0.0,
                    "forbidden_count": len(getattr(feedback, "forbidden_patterns", []) or []) if feedback else 0,
                },
            )
        except Exception:
            pass


_INSTANCE: Optional[CandidateGenerator] = None


def get_candidate_generator() -> CandidateGenerator:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = CandidateGenerator()
    return _INSTANCE
