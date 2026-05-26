"""engine/reflection_engine.py — PHASE 10.

After generation, evaluate fidelity to intent, aesthetic quality,
cinematic coherence, emotional impact, structural weaknesses. Emits a
ReflectionReport with concrete refinement suggestions.

Rule-based — no LLM dependency. The report scores each dimension on
0..1 from observable evidence (which steps succeeded, which were
UNAVAILABLE, whether the spec fields were honored). When an LLM is
available it can be wired in later via expand_with_llm(); for now the
reflection is deterministic and receipt-backed.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReflectionReport:
    report_id:          str
    intent_id:          str
    graph_id:           str
    fidelity_score:     float       # 0..1 — how closely outputs matched intent
    aesthetic_score:    float       # 0..1
    coherence_score:    float       # 0..1
    impact_score:       float       # 0..1
    structural_score:   float       # 0..1
    overall_score:      float
    suggestions:        list = field(default_factory=list)
    auto_refinements:   list = field(default_factory=list)
    timestamp:          float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def render(self) -> str:
        sym = lambda s: "✓" if s >= 0.8 else "◐" if s >= 0.5 else "✗"
        lines = [
            f"☯ Reflection · {self.report_id} · overall {self.overall_score:.2f}",
            f"   {sym(self.fidelity_score)} fidelity  {self.fidelity_score:.2f}",
            f"   {sym(self.aesthetic_score)} aesthetic {self.aesthetic_score:.2f}",
            f"   {sym(self.coherence_score)} coherence {self.coherence_score:.2f}",
            f"   {sym(self.impact_score)} impact    {self.impact_score:.2f}",
            f"   {sym(self.structural_score)} structure {self.structural_score:.2f}",
        ]
        if self.suggestions:
            lines.append("   suggestions:")
            for s in self.suggestions[:5]:
                lines.append(f"     · {s}")
        return "\n".join(lines)


class ReflectionEngine:
    """Deterministic critique. Pure-Python, no LLM."""

    def reflect(self, spec, graph, dispatch_results: list) -> ReflectionReport:
        """Reflect on an execution. dispatch_results is a list of
        DispatchResult instances (or dicts with the same shape).
        """
        t0 = time.time()
        results = list(dispatch_results or [])
        total = max(1, len(results))
        ok = sum(1 for r in results if _get(r, "outcome") == "OK")
        degraded = sum(1 for r in results if _get(r, "outcome") == "DEGRADED")
        unavail = sum(1 for r in results if _get(r, "outcome") == "UNAVAILABLE")
        failed = sum(1 for r in results if _get(r, "outcome") == "FAIL")

        # Fidelity: how many planned steps actually ran (OK or DEGRADED count)
        fidelity = (ok + 0.5 * degraded) / total

        # Aesthetic: ambition × style_resolution
        ambition = float(getattr(spec, "ambition", 0.6) or 0.6)
        style_resolved = 1.0 if getattr(spec, "style", None) else 0.5
        aesthetic = (ambition * 0.5 + style_resolved * 0.5)
        if "inferred_fields" in getattr(spec, "__dict__", {}):
            # Penalize fields that were operator-unspecified
            inferred = list(getattr(spec, "inferred_fields", []) or [])
            aesthetic *= (1.0 - 0.1 * len(inferred))
        aesthetic = max(0.0, min(1.0, aesthetic))

        # Coherence: low if tone and emotion conflict, low if missing soundtrack on cinematic ambition
        coherence = 0.8
        if getattr(spec, "tone", None) == "joyful" and getattr(spec, "emotion", None) == "fear":
            coherence -= 0.4
        if ambition > 0.85 and not getattr(spec, "soundtrack_profile", None) \
                and getattr(spec, "medium", None) in ("video", "audio"):
            coherence -= 0.2
        coherence = max(0.0, min(1.0, coherence))

        # Impact: ambition + presence of color palette + composition
        impact = ambition * 0.6
        if getattr(spec, "color_palette", None):
            impact += 0.15
        if getattr(spec, "composition", None):
            impact += 0.10
        if getattr(spec, "emotion", None):
            impact += 0.10
        impact = max(0.0, min(1.0, impact))

        # Structure: dispatch outcomes
        structural = 1.0 - (failed / total) - 0.3 * (unavail / total)
        structural = max(0.0, min(1.0, structural))

        overall = (fidelity + aesthetic + coherence + impact + structural) / 5.0

        # Suggestions
        suggestions: list[str] = []
        if fidelity < 0.7:
            suggestions.append(
                f"{failed + unavail}/{total} planned steps did not produce output — "
                "investigate UNAVAILABLE backends and install missing dependencies"
            )
        if aesthetic < 0.6 and not getattr(spec, "style", None):
            suggestions.append(
                "No style was resolved from the prompt. Adding a style word "
                "(cyberpunk, cinematic, painterly, etc.) sharpens generation."
            )
        if coherence < 0.7:
            suggestions.append(
                "Tone/emotion conflict or missing soundtrack on high-ambition spec. "
                "Re-state the intended emotional arc, or specify soundtrack profile."
            )
        if impact < 0.6:
            suggestions.append(
                "Low impact score — try raising ambition keywords (legendary, "
                "production-grade) or specifying composition (heroic centered, low angle)."
            )
        if structural < 0.7:
            for r in results:
                if _get(r, "outcome") in ("FAIL", "UNAVAILABLE"):
                    rem = _get(r, "remediation") or ""
                    if rem:
                        suggestions.append(f"[{_get(r, 'backend')}] {rem}")
        if not suggestions:
            suggestions.append("Generation is coherent. Ready for refinement passes or export.")

        # Auto-refinements (concrete next-step recipes for the engine itself)
        auto: list[str] = []
        if getattr(spec, "soundtrack_profile", None) and getattr(spec, "tone", None) == "legendary":
            auto.append("soundtrack:escalate_at_midpoint")
        if ambition > 0.85 and not getattr(spec, "rendering_profile", None):
            auto.append("rendering:upgrade_to_production_profile")

        report = ReflectionReport(
            report_id=f"rfl-{int(t0*1000):x}",
            intent_id=getattr(spec, "intent_id", ""),
            graph_id=getattr(graph, "graph_id", ""),
            fidelity_score=fidelity,
            aesthetic_score=aesthetic,
            coherence_score=coherence,
            impact_score=impact,
            structural_score=structural,
            overall_score=overall,
            suggestions=suggestions,
            auto_refinements=auto,
            timestamp=t0,
        )
        self._emit_receipt(report, (time.time() - t0) * 1000.0)
        return report

    def _emit_receipt(self, r: ReflectionReport, dur_ms: float) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="reflection:critique",
                executor="ReflectionEngine",
                duration_ms=dur_ms,
                verified=True,
                compute_sha256=False,
                evidence={
                    "report_id":       r.report_id,
                    "intent_id":       r.intent_id,
                    "graph_id":        r.graph_id,
                    "overall_score":   r.overall_score,
                    "fidelity":        r.fidelity_score,
                    "aesthetic":       r.aesthetic_score,
                    "coherence":       r.coherence_score,
                    "impact":          r.impact_score,
                    "structural":      r.structural_score,
                    "suggestion_count": len(r.suggestions),
                    "auto_refinement_count": len(r.auto_refinements),
                },
            )
        except Exception:
            pass


def _get(obj: Any, attr: str, default=None):
    if obj is None:
        return default
    if hasattr(obj, attr):
        return getattr(obj, attr)
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return default
