"""engine/oracle/production_advisor.py — collaborator advisory report.

Reads intent + composition_plan + ambition + CQI + creative_identity
and emits an AdvisoryReport with strengths, gaps, recommendations.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass(frozen=True)
class AdvisoryReport:
    report_id:         str
    ambition_band:     str
    ambition_score:    float
    strengths:         list
    composition_gaps:  list
    recommendations:   list
    capability_risk:   str
    one_line:          str
    created_at:        float

    def to_dict(self) -> dict:
        return asdict(self)


class ProductionAdvisor:

    def __init__(self):
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.production_advisor", self)
        except Exception:
            pass

    def advise(self, intent_text: str, composition_plan=None,
                cqi=None) -> AdvisoryReport:
        t0 = time.time()
        # Ambition
        from engine.oracle.ambition_interpreter import get_ambition_interpreter
        amb = get_ambition_interpreter().assess(intent_text)

        # Pull CQI dimensions if present
        strengths: list[str] = []
        gaps: list[str] = []
        if cqi is not None:
            if cqi.atmosphere >= 0.75:        strengths.append("atmosphere")
            if cqi.emotional_impact >= 0.75:  strengths.append("emotional impact")
            if cqi.cinematic_intensity >= 0.75: strengths.append("cinematic intensity")
            if cqi.visual_harmony >= 0.75:    strengths.append("visual harmony")
            if cqi.memorability >= 0.75:      strengths.append("memorability")

            if cqi.atmosphere < 0.5:        gaps.append("atmosphere is thin — name the place's mood")
            if cqi.emotional_impact < 0.5:  gaps.append("emotional impact is muted — add a tone keyword")
            if cqi.cinematic_intensity < 0.5: gaps.append("cinematic intensity lacks — align pacing with tone")
            if cqi.visual_harmony < 0.5:    gaps.append("visual harmony adrift — declare a palette")
            if cqi.pacing_quality < 0.5:    gaps.append("pacing curve flat — restructure scenes")
            if cqi.thematic_coherence < 0.5: gaps.append("scenes drift thematically — bind with a focal noun")
            if cqi.originality < 0.5:       gaps.append("intent leans on operator defaults — try novel ground")
            if cqi.memorability < 0.5:      gaps.append("output forgettable — add cinematic anchors")

        # Composition-level recommendations
        recommendations: list[str] = []
        if composition_plan is not None:
            sb = getattr(composition_plan, "storyboard", None)
            scenes = list(getattr(sb, "scenes", []) or []) if sb else []
            if amb.band in ("masterwork", "production") and len(scenes) < 4:
                recommendations.append(
                    f"ambition is {amb.band} but storyboard has only {len(scenes)} "
                    f"scenes — consider trailer or game pipeline for richer breakdown"
                )
            aes = getattr(composition_plan, "aesthetic", None)
            if aes is not None:
                if not aes.palette:
                    recommendations.append("no palette set — lock 3-5 hex colors to ensure consistency")
                if not aes.soundtrack:
                    recommendations.append("no soundtrack profile — add a rhythmic anchor (e.g. 'synthwave with sub bass')")

        # Creative identity-aware: recommend novelty if outputs are repeating
        try:
            from engine.semantic_memory.creative_identity import get_creative_identity
            ci = get_creative_identity()
            if ci.top_motifs and len(ci.top_motifs) >= 3:
                recommendations.append(
                    f"recurring motifs {ci.top_motifs[:3]} are part of your signature — "
                    f"lean into them or deliberately depart for novelty"
                )
        except Exception:
            pass

        one_line = self._one_line(amb, cqi, len(gaps))
        report = AdvisoryReport(
            report_id=f"adv-{uuid.uuid4().hex[:8]}",
            ambition_band=amb.band,
            ambition_score=amb.ambition_score,
            strengths=strengths,
            composition_gaps=gaps,
            recommendations=recommendations,
            capability_risk=amb.capability_match,
            one_line=one_line,
            created_at=t0,
        )
        self._emit_receipt(report, (time.time() - t0) * 1000.0)
        self._emit_event(report)
        return report

    def _one_line(self, amb, cqi, gap_count) -> str:
        if cqi is None:
            return f"ambition '{amb.band}'. Submit a composition to receive critique."
        if cqi.composite >= 0.85:
            return f"premium composition aligned with '{amb.band}' ambition. Ship as-is."
        if cqi.composite >= 0.65:
            return (f"solid '{amb.band}' composition. {gap_count} gap(s) "
                    f"identified — address before final delivery.")
        return (f"composition under-delivers on '{amb.band}' ambition. "
                f"{gap_count} structural gap(s) — recommend refinement pass.")

    def _emit_receipt(self, r: AdvisoryReport, dur_ms: float) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="oracle:advisory",
                executor="ProductionAdvisor",
                duration_ms=dur_ms, verified=True, compute_sha256=False,
                evidence={
                    "report_id":     r.report_id,
                    "ambition_band": r.ambition_band,
                    "ambition_score":r.ambition_score,
                    "strength_count":  len(r.strengths),
                    "gap_count":       len(r.composition_gaps),
                    "rec_count":       len(r.recommendations),
                },
            )
        except Exception:
            pass

    def _emit_event(self, r: AdvisoryReport) -> None:
        try:
            from engine.live_stream import get_live_stream
            get_live_stream().emit_event("oracle_advisory", {
                "report_id":      r.report_id,
                "ambition_band":  r.ambition_band,
                "ambition_score": r.ambition_score,
                "one_line":       r.one_line,
                "gap_count":      len(r.composition_gaps),
                "rec_count":      len(r.recommendations),
            })
        except Exception:
            pass


_INSTANCE: Optional[ProductionAdvisor] = None


def get_production_advisor() -> ProductionAdvisor:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ProductionAdvisor()
    return _INSTANCE
