"""engine/aesthetic_intelligence/aesthetic_reasoner.py — Creative Quality Index.

AestheticReasoner computes the 8-dimension CQI for a given
(spec, composition_plan, worker_outcome) tuple. Replaces simplistic
READY/FAIL with measurable composition quality.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CQI:
    """Creative Quality Index — 8 dimensions + composite."""
    cqi_id:               str
    atmosphere:           float
    emotional_impact:     float
    cinematic_intensity:  float
    visual_harmony:       float
    pacing_quality:       float
    thematic_coherence:   float
    originality:          float
    memorability:         float
    composite:            float        # weighted overall 0..1
    breakdown:            dict = field(default_factory=dict)
    computed_at:          float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def render(self) -> str:
        return (
            f"☼ CQI {self.composite:.2f}\n"
            f"   atmosphere {self.atmosphere:.2f}  emotional {self.emotional_impact:.2f}  "
            f"cinematic {self.cinematic_intensity:.2f}  harmony {self.visual_harmony:.2f}\n"
            f"   pacing {self.pacing_quality:.2f}  thematic {self.thematic_coherence:.2f}  "
            f"original {self.originality:.2f}  memorable {self.memorability:.2f}"
        )


class AestheticReasoner:
    """Compute the CQI for a creative artifact set."""

    def __init__(self):
        from engine.aesthetic_intelligence.visual_harmony      import VisualHarmonyScorer
        from engine.aesthetic_intelligence.emotional_resonance import EmotionalResonanceScorer
        from engine.aesthetic_intelligence.cinematic_rhythm    import CinematicRhythmScorer
        self._harmony  = VisualHarmonyScorer()
        self._emotion  = EmotionalResonanceScorer()
        self._rhythm   = CinematicRhythmScorer()
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.aesthetic_reasoner", self)
        except Exception:
            pass

    def score(self, spec=None, composition_plan=None,
              worker_outcome=None) -> CQI:
        """Compute the CQI. Returns a frozen dataclass. Never raises.

        BUILD-028: visual_harmony now blends real pixel analysis (when
        an image artifact is available) with the spec-level harmony
        score. CQI composite weighting is rebalanced to 35% semantic +
        35% visual + 20% coherence + 10% identity per directive Section 5.
        """
        t0 = time.time()
        breakdown: dict = {}

        # 1. Atmosphere — present + matches palette
        atmosphere = self._atmosphere(spec, breakdown)

        # 2. Emotional impact
        emo_score, emo_b = self._emotion.score(spec)
        breakdown["emotional"] = emo_b
        emotional_impact = emo_score

        # 3. Cinematic intensity
        cin_score, cin_b = self._rhythm.score(
            spec,
            getattr(composition_plan, "cinematic", None) if composition_plan else None,
        )
        breakdown["cinematic"] = cin_b
        cinematic_intensity = cin_score

        # 4. Visual harmony — BUILD-028: blend spec harmony with REAL
        # pixel analysis when an image artifact is available.
        harm_score, harm_b = self._harmony.score(spec)
        breakdown["harmony"] = harm_b
        pixel_score = self._pixel_harmony(worker_outcome, spec, breakdown)
        if pixel_score is not None:
            # 60% pixel, 40% semantic when real pixels available
            visual_harmony = 0.6 * pixel_score + 0.4 * harm_score
            breakdown["harmony"]["pixel_score"] = round(pixel_score, 3)
        else:
            visual_harmony = harm_score

        # 5. Pacing quality
        pacing_quality = self._pacing_quality(spec, composition_plan, breakdown)

        # 6. Thematic coherence — overlap of scene focals
        thematic_coherence = self._thematic_coherence(composition_plan, breakdown)

        # 7. Originality — operator preference deviation
        originality = self._originality(spec, breakdown)

        # 8. Memorability — distinct cinematic elements present
        memorability = self._memorability(spec, composition_plan, breakdown)

        # BUILD-028: bucketed composite per directive Section 5
        # 35% semantic + 35% visual + 20% coherence + 10% identity
        semantic_bucket  = (atmosphere + emotional_impact + thematic_coherence) / 3.0
        visual_bucket    = (visual_harmony + cinematic_intensity + memorability) / 3.0
        coherence_bucket = (pacing_quality + originality) / 2.0
        identity_bucket  = self._identity_alignment(spec, breakdown)

        breakdown["bucket_semantic"]  = round(semantic_bucket, 3)
        breakdown["bucket_visual"]    = round(visual_bucket, 3)
        breakdown["bucket_coherence"] = round(coherence_bucket, 3)
        breakdown["bucket_identity"]  = round(identity_bucket, 3)

        composite = (
            0.35 * semantic_bucket +
            0.35 * visual_bucket +
            0.20 * coherence_bucket +
            0.10 * identity_bucket
        )
        composite = round(max(0.0, min(1.0, composite)), 3)

        cqi = CQI(
            cqi_id=f"cqi-{uuid.uuid4().hex[:10]}",
            atmosphere=round(atmosphere, 3),
            emotional_impact=round(emotional_impact, 3),
            cinematic_intensity=round(cinematic_intensity, 3),
            visual_harmony=round(visual_harmony, 3),
            pacing_quality=round(pacing_quality, 3),
            thematic_coherence=round(thematic_coherence, 3),
            originality=round(originality, 3),
            memorability=round(memorability, 3),
            composite=composite,
            breakdown=breakdown,
            computed_at=t0,
        )
        self._emit_receipt(cqi, (time.time() - t0) * 1000.0)
        return cqi

    # ── Dimension scorers ────────────────────────────────────────────
    def _identity_alignment(self, spec, breakdown) -> float:
        """How well does this composition align with the operator's
        established creative identity? Reads UnifiedCreativeProfile."""
        try:
            from engine.unified_creative_profile import get_unified_profile
            profile = get_unified_profile().compute()
            style = (getattr(spec, "style", "") or "").lower() if spec else ""
            tone  = (getattr(spec, "tone",  "") or "").lower() if spec else ""
            alignment = 0.5
            if style and style in [s.lower() for s in (profile.stylistic_signature or [])]:
                alignment += 0.25
            if tone and tone in [t.lower() for t in (profile.emotional_tendencies or [])]:
                alignment += 0.15
            if profile.aesthetic_confidence > 0.7:
                alignment += 0.05
            breakdown["identity_alignment_components"] = {
                "style_match": style in [s.lower() for s in (profile.stylistic_signature or [])],
                "tone_match":  tone in [t.lower() for t in (profile.emotional_tendencies or [])],
                "confidence":  profile.aesthetic_confidence,
            }
            return min(1.0, alignment)
        except Exception:
            return 0.55   # neutral when profile unavailable

    def _pixel_harmony(self, worker_outcome, spec, breakdown):
        """If any worker artifact is an image, run real pixel analysis."""
        if worker_outcome is None:
            return None
        try:
            from engine.visual_harmony_pixel import get_visual_harmony_pixel
            vhp = get_visual_harmony_pixel()
        except Exception:
            return None
        palette = list(getattr(spec, "color_palette", []) or []) if spec else []
        for art in (getattr(worker_outcome, "artifacts", []) or []):
            if not isinstance(art, dict):
                continue
            path = art.get("path", "")
            if not path or not path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                continue
            try:
                analysis = vhp.analyze(path, spec_palette=palette)
                if analysis is not None:
                    return analysis.pixel_score
            except Exception:
                continue
        return None

    def _atmosphere(self, spec, breakdown) -> float:
        if spec is None:
            return 0.4
        atm = getattr(spec, "atmosphere", "") or ""
        lighting = getattr(spec, "lighting", "") or ""
        palette = list(getattr(spec, "color_palette", []) or [])
        score = 0.4
        if atm:    score += 0.25
        if lighting: score += 0.15
        if palette: score += 0.2
        breakdown["atmosphere_components"] = {
            "atmosphere_set": bool(atm),
            "lighting_set": bool(lighting),
            "palette_size": len(palette),
        }
        return min(1.0, score)

    def _pacing_quality(self, spec, composition_plan, breakdown) -> float:
        if composition_plan is None:
            return 0.5
        scenes = list(getattr(getattr(composition_plan, "storyboard", None),
                                "scenes", []) or [])
        if not scenes:
            return 0.5
        durations = [getattr(s, "duration_s", 0) for s in scenes]
        if not durations:
            return 0.5
        # Good pacing = increasing variance toward climax + final tag
        total = sum(durations)
        if total <= 0:
            return 0.5
        # If durations rise then fall (story shape) → high score
        mid = len(durations) // 2
        rising = sum(durations[:mid+1])
        falling = sum(durations[mid+1:])
        ratio = rising / total
        breakdown["pacing_components"] = {
            "scene_count": len(scenes),
            "total_duration_s": round(total, 2),
            "rising_ratio": round(ratio, 3),
        }
        # Best ratio is ~0.55-0.7 (slight rise toward midpoint)
        if 0.55 <= ratio <= 0.7:
            return 0.9
        if 0.45 <= ratio < 0.55 or 0.7 < ratio <= 0.8:
            return 0.75
        return 0.55

    def _thematic_coherence(self, composition_plan, breakdown) -> float:
        if composition_plan is None:
            return 0.5
        scenes = list(getattr(getattr(composition_plan, "storyboard", None),
                                "scenes", []) or [])
        if len(scenes) < 2:
            return 0.6
        # Overlap of words across scene focals
        word_sets: list[set] = []
        for s in scenes:
            focal = (getattr(s, "focal", "") or "").lower()
            words = set(w for w in focal.split() if len(w) >= 4)
            word_sets.append(words)
        if not word_sets or not any(word_sets):
            return 0.5
        # Average pairwise Jaccard
        n = len(word_sets)
        total_pairs = 0
        total_score = 0.0
        for i in range(n):
            for j in range(i + 1, n):
                u = word_sets[i] | word_sets[j]
                if not u:
                    continue
                jacc = len(word_sets[i] & word_sets[j]) / len(u)
                total_score += jacc
                total_pairs += 1
        avg = (total_score / total_pairs) if total_pairs else 0.5
        breakdown["thematic_jaccard"] = round(avg, 3)
        # Map: jaccard 0.2-0.5 = ideal coherence (not too rigid, not too loose)
        if 0.2 <= avg <= 0.5:
            return 0.85
        if avg > 0.7:
            return 0.5   # too repetitive
        return 0.4 + avg

    def _originality(self, spec, breakdown) -> float:
        """Deviation from operator's prior preferred styles. High deviation
        = original; very high deviation = potential semantic mismatch (cap at 0.85)."""
        if spec is None:
            return 0.5
        style = (getattr(spec, "style", "") or "").lower()
        try:
            from engine.personality_model import get_personality
            snap = get_personality().snapshot()
            top = list(snap.get("top_aesthetic") or [])
            if not top:
                return 0.65   # neutral when no history
            if style in [t.lower() for t in top[:2]]:
                breakdown["originality"] = "matches_top"
                return 0.55   # safe but not original
            if style and style in [t.lower() for t in top]:
                breakdown["originality"] = "matches_tail"
                return 0.7
            breakdown["originality"] = "novel"
            return 0.85
        except Exception:
            return 0.65

    def _memorability(self, spec, composition_plan, breakdown) -> float:
        """Count distinct memorable elements."""
        score = 0.3
        elements = 0
        if spec is not None:
            if getattr(spec, "style", None):              elements += 1
            if getattr(spec, "tone", None):                elements += 1
            if getattr(spec, "lighting", None):            elements += 1
            if getattr(spec, "composition", None):         elements += 1
            if getattr(spec, "emotion", None):             elements += 1
            if getattr(spec, "atmosphere", None):          elements += 1
            if getattr(spec, "soundtrack_profile", None):  elements += 1
            if getattr(spec, "architecture_style", None):  elements += 1
        breakdown["memorability_elements"] = elements
        # Each element worth ~0.08, capped at 1.0
        return min(1.0, score + elements * 0.085)

    def _emit_receipt(self, cqi: CQI, dur_ms: float) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="cqi:scored",
                executor="AestheticReasoner",
                duration_ms=dur_ms, verified=True, compute_sha256=False,
                evidence={
                    "cqi_id":              cqi.cqi_id,
                    "composite":           cqi.composite,
                    "atmosphere":          cqi.atmosphere,
                    "emotional_impact":    cqi.emotional_impact,
                    "cinematic_intensity": cqi.cinematic_intensity,
                    "visual_harmony":      cqi.visual_harmony,
                    "pacing_quality":      cqi.pacing_quality,
                    "thematic_coherence":  cqi.thematic_coherence,
                    "originality":         cqi.originality,
                    "memorability":        cqi.memorability,
                },
            )
        except Exception:
            pass
        # Bus event
        try:
            from engine.live_stream import get_live_stream
            get_live_stream().emit_event("cqi_scored", {
                "cqi_id":    cqi.cqi_id,
                "composite": cqi.composite,
                "atmosphere": cqi.atmosphere,
                "emotional_impact": cqi.emotional_impact,
                "cinematic_intensity": cqi.cinematic_intensity,
                "visual_harmony": cqi.visual_harmony,
                "memorability":   cqi.memorability,
            })
        except Exception:
            pass


_INSTANCE: Optional[AestheticReasoner] = None


def get_aesthetic_reasoner() -> AestheticReasoner:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = AestheticReasoner()
    return _INSTANCE
