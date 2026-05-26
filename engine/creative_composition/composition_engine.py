"""engine/creative_composition/composition_engine.py — Phase 1 of every intent.

CompositionEngine consolidates StoryboardPlanner + CinematicLanguage +
AestheticDirector + RefinementDirector into a single CompositionPlan
that workers consult BEFORE generating artifacts.

Composition is the new Phase 1 of every intent — replacing direct
worker dispatch. The plan is signed (sha256 over its rendered text) so
artifact lineage can carry plan_sha to the master package.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

_log = logging.getLogger(__name__)


@dataclass
class CompositionPlan:
    plan_id:           str
    raw_intent:        str
    pipeline_kind:     str
    storyboard:        Any                 # Storyboard
    cinematic:         Any                 # CinematicProfile
    aesthetic:         Any                 # AestheticProfile
    asset_strategy:    dict                # per-realm asset count + ordering
    realm_sequence:    list                # canonical order of realm dispatches
    plan_sha:          str = ""
    created_at:        float = 0.0
    rendered:          str = ""

    def to_dict(self) -> dict:
        return {
            "plan_id":         self.plan_id,
            "raw_intent":      self.raw_intent[:240],
            "pipeline_kind":   self.pipeline_kind,
            "storyboard":      (self.storyboard.to_dict()
                                  if hasattr(self.storyboard, "to_dict") else None),
            "cinematic":       (self.cinematic.to_dict()
                                  if hasattr(self.cinematic, "to_dict") else None),
            "aesthetic":       (self.aesthetic.to_dict()
                                  if hasattr(self.aesthetic, "to_dict") else None),
            "asset_strategy":  dict(self.asset_strategy),
            "realm_sequence":  list(self.realm_sequence),
            "plan_sha":        self.plan_sha,
            "created_at":      self.created_at,
        }

    def render(self) -> str:
        return self.rendered


class CompositionEngine:
    """Composition-first orchestrator. Singleton via engine registry."""

    def __init__(self):
        from engine.creative_composition.storyboard_planner   import StoryboardPlanner
        from engine.creative_composition.cinematic_language   import CinematicLanguage
        from engine.creative_composition.aesthetic_director   import AestheticDirector
        from engine.creative_composition.refinement_director  import RefinementDirector
        from engine.creative_composition.export_mastering     import ExportMastering
        self.storyboard_planner = StoryboardPlanner()
        self.cinematic_language = CinematicLanguage()
        self.aesthetic_director = AestheticDirector()
        self.refinement_director = RefinementDirector()
        self.export_mastering = ExportMastering()
        self._plan_count = 0
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.composition", self)
        except Exception:
            pass

    # ── Public API ────────────────────────────────────────────────────
    def plan(self, intent_text: str, spec=None,
              pipeline_kind: Optional[str] = None) -> CompositionPlan:
        """Compile a composition plan. Cheap, deterministic, sub-50ms."""
        t0 = time.time()
        # Detect pipeline kind if not given
        if pipeline_kind is None:
            pipeline_kind = self._detect_pipeline_kind(intent_text)

        sb = self.storyboard_planner.plan(intent_text, spec, pipeline_kind)
        cin = self.cinematic_language.derive(spec)
        aes = self.aesthetic_director.direct(spec)

        # Asset strategy: per-realm artifact counts
        asset_strategy = self._asset_strategy(pipeline_kind, sb)
        realm_sequence = self._realm_sequence(pipeline_kind)

        rendered = self._render(intent_text, pipeline_kind, sb, cin, aes,
                                  asset_strategy, realm_sequence)
        plan_sha = hashlib.sha256(rendered.encode("utf-8")).hexdigest()[:16]

        plan = CompositionPlan(
            plan_id=f"plan-{uuid.uuid4().hex[:10]}",
            raw_intent=intent_text or "",
            pipeline_kind=pipeline_kind,
            storyboard=sb,
            cinematic=cin,
            aesthetic=aes,
            asset_strategy=asset_strategy,
            realm_sequence=realm_sequence,
            plan_sha=plan_sha,
            created_at=t0,
            rendered=rendered,
        )
        self._plan_count += 1
        self._emit_receipt(plan, (time.time() - t0) * 1000.0)
        self._emit_event(plan)

        # BUILD-027A — Creative Intelligence sweep at composition time:
        # CQI scoring + motif observation + Oracle advisory. All best-effort.
        try:
            from engine.semantic_memory.motif_tracking import get_motif_tracker
            get_motif_tracker().observe(intent_text or "")
        except Exception:
            pass
        try:
            from engine.aesthetic_intelligence.aesthetic_reasoner import get_aesthetic_reasoner
            plan_cqi = get_aesthetic_reasoner().score(spec=spec, composition_plan=plan)
            # Stash on plan for downstream consumers (LaunchSurface, Oracle)
            try:
                object.__setattr__(plan, "cqi", plan_cqi)
            except Exception:
                pass
        except Exception:
            plan_cqi = None
        try:
            from engine.oracle.production_advisor import get_production_advisor
            get_production_advisor().advise(intent_text or "",
                                             composition_plan=plan, cqi=plan_cqi)
        except Exception:
            pass

        return plan

    # ── Helpers ──────────────────────────────────────────────────────
    def _detect_pipeline_kind(self, intent_text: str) -> str:
        t = (intent_text or "").lower()
        if any(k in t for k in ("trailer", "intro", "cinematic", "promo", "reel")):
            return "trailer"
        if any(k in t for k in ("game", "playable", "world", "mechanics", "level")):
            return "game"
        if any(k in t for k in ("album", "ep ", "soundtrack collection")):
            return "album"
        if any(k in t for k in ("gallery", "concept art", "moodboard", "image set")):
            return "gallery"
        if any(k in t for k in ("simulation", "tactical map", "world sim")):
            return "simulation"
        return "gallery"

    def _asset_strategy(self, pipeline_kind: str, sb) -> dict:
        """How many artifacts per realm should this composition produce?"""
        defaults = {
            "trailer":    {"image": len(sb.scenes), "audio": 1, "video": 1},
            "game":       {"game": 1, "simulation": 1, "image": 2, "cast": 1},
            "album":      {"audio": 3},
            "gallery":    {"image": 3},
            "simulation": {"simulation": 2},
        }
        return defaults.get(pipeline_kind, {"image": 1})

    def _realm_sequence(self, pipeline_kind: str) -> list:
        """Canonical execution order. Used by WorkerRouter for multi-realm jobs."""
        sequences = {
            "trailer":    ["image", "audio", "video"],
            "game":       ["game", "simulation", "image", "cast"],
            "album":      ["audio"],
            "gallery":    ["image"],
            "simulation": ["simulation"],
        }
        return sequences.get(pipeline_kind, ["image"])

    def _render(self, intent_text, pipeline_kind, sb, cin, aes,
                 asset_strategy, realm_sequence) -> str:
        lines = [
            f"⌬ COMPOSITION PLAN · {pipeline_kind}",
            f"   intent: {(intent_text or '')[:140]}",
            f"   realm sequence: {' → '.join(realm_sequence)}",
            f"   asset strategy: {asset_strategy}",
            "",
            "── STORYBOARD ─────",
            sb.render(),
            "",
            "── CINEMATIC LANGUAGE ─────",
            cin.render(),
            "",
            "── AESTHETIC DIRECTION ─────",
            aes.render(),
        ]
        return "\n".join(lines)

    def stats(self) -> dict:
        return {"plan_count": self._plan_count}

    def _emit_receipt(self, plan: CompositionPlan, dur_ms: float) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task=f"composition:plan:{plan.pipeline_kind}",
                executor="CompositionEngine",
                duration_ms=dur_ms,
                verified=True, compute_sha256=False,
                evidence={
                    "plan_id":       plan.plan_id,
                    "pipeline_kind": plan.pipeline_kind,
                    "scene_count":   len(plan.storyboard.scenes),
                    "realm_sequence": plan.realm_sequence,
                    "asset_strategy": plan.asset_strategy,
                    "plan_sha":      plan.plan_sha,
                },
            )
        except Exception:
            pass

    def _emit_event(self, plan: CompositionPlan) -> None:
        try:
            from engine.live_stream import get_live_stream
            get_live_stream().emit_event("composition_planned", {
                "plan_id":       plan.plan_id,
                "pipeline_kind": plan.pipeline_kind,
                "scene_count":   len(plan.storyboard.scenes),
                "realm_sequence": plan.realm_sequence,
                "plan_sha":      plan.plan_sha,
            })
        except Exception:
            pass


_INSTANCE: Optional[CompositionEngine] = None


def get_composition_engine() -> CompositionEngine:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = CompositionEngine()
    return _INSTANCE
