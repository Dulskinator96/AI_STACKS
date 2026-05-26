"""engine/refinement/iterative_refiner.py — composition-aware refinement.

Wraps the existing QualityGate/AutoRepairLoop with CQI-driven decisions.
On sub-threshold CQI, generates targeted refinement parameters from
the CritiqueEngine's refinement_targets.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

_log = logging.getLogger(__name__)


_CQI_REFINE_THRESHOLD = 0.65


class IterativeRefiner:
    """Composition-aware refinement coordinator."""

    def __init__(self):
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.iterative_refiner", self)
        except Exception:
            pass

    def should_refine(self, cqi) -> bool:
        if cqi is None:
            return False
        return float(getattr(cqi, "composite", 0.0)) < _CQI_REFINE_THRESHOLD

    def derive_params(self, critique) -> dict:
        """Translate critique.refinement_targets into worker parameter
        adjustments. Returns dict to merge into WorkerRequest.params."""
        params: dict = {"refinement": True}
        for target in (getattr(critique, "refinement_targets", []) or []):
            t = (target or "").lower()
            if "atmosphere" in t:
                params["emphasize_atmosphere"] = True
            if "tone keyword" in t:
                params["emphasize_tone"] = True
            if "pacing" in t:
                params["pacing_lift"] = 0.2
            if "color palette" in t:
                params["lock_palette"] = True
            if "storyboard" in t:
                params["redo_storyboard"] = True
            if "focal noun" in t:
                params["bind_focal_noun"] = True
            if "novel style" in t:
                params["explore_style"] = True
            if "cinematic anchors" in t:
                params["add_cinematic_anchors"] = True
        return params

    def _emit_receipt(self, params: dict) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="refinement:params_derived",
                executor="IterativeRefiner",
                duration_ms=0.0, verified=True, compute_sha256=False,
                evidence={"param_keys": sorted(params.keys())},
            )
        except Exception:
            pass


_INSTANCE: Optional[IterativeRefiner] = None


def get_iterative_refiner() -> IterativeRefiner:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = IterativeRefiner()
    return _INSTANCE
