"""engine/unified_creative_profile.py — BUILD-028 SECTION 7 consolidation.

Collapses 6 fragmented aesthetic-state sources into ONE canonical fingerprint:
  · PersonalityModel        — interaction counters
  · PersonalityMatrix       — aesthetic fingerprint
  · MotifTracker            — recurring motifs
  · SuccessfulOutputMemory  — what scored ≥ 0.75
  · PreferenceMemory        — accepted/rejected feature stats with decay
  · CreativeIdentity        — derived summary

The system stops maintaining fragmented aesthetic state. Every consumer
reads UnifiedCreativeProfile.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)


_PATH = Path(__file__).resolve().parent.parent / "telemetry" / "creative_profile.json"


@dataclass(frozen=True)
class UnifiedCreativeProfile:
    profile_id:             str
    stylistic_signature:    list           # top styles (canonical names)
    emotional_tendencies:   list           # top tones
    motif_persistence:      list           # top motifs
    pacing_preference:      str
    cinematic_identity:     str            # synthesized identity statement
    atmosphere_identity:    str
    refinement_history:     dict           # {avg_passes, success_rate}
    aesthetic_confidence:   float          # 0..1 confidence in the fingerprint
    interaction_count:      int
    summary:                str
    computed_at:            float

    def to_dict(self) -> dict:
        return asdict(self)


class _UnifiedCreativeProfileComputer:

    def __init__(self):
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.unified_creative_profile", self)
        except Exception:
            pass

    def compute(self) -> UnifiedCreativeProfile:
        # 1. PersonalityMatrix → fingerprint
        fp_styles: list = []
        fp_palette: list = []
        fp_emotions: list = []
        interaction_count = 0
        try:
            from engine.personality_matrix import get_personality_matrix
            ms = get_personality_matrix().snapshot()
            fp_styles = list(ms.fingerprint.top_styles or [])
            fp_palette = list(ms.fingerprint.top_palette or [])
            fp_emotions = list(ms.fingerprint.top_emotions or [])
            interaction_count = int(ms.interaction_count or 0)
        except Exception as e:
            _log.debug("personality matrix unavailable: %s", e)

        # 2. MotifTracker
        motifs: list = []
        try:
            from engine.semantic_memory.motif_tracking import get_motif_tracker
            motifs = list(get_motif_tracker().top_motifs(5))
        except Exception:
            pass

        # 3. SuccessfulOutputMemory
        avg_success_score = 0.0
        success_count = 0
        try:
            from engine.semantic_memory.successful_output_memory import get_successful_output_memory
            sm = get_successful_output_memory().snapshot()
            avg_success_score = float(sm.get("avg_score", 0.0) or 0.0)
            success_count = int(sm.get("recorded", 0) or 0)
        except Exception:
            pass

        # 4. PreferenceMemory — most-trusted feature values
        pacing_pref = ""
        atmo_pref = ""
        try:
            from engine.preference_memory import get_preference_memory
            pm = get_preference_memory()
            pacing_top = pm.top_preferences("pacing", n=1)
            if pacing_top:
                pacing_pref = pacing_top[0]["value"]
            lighting_top = pm.top_preferences("lighting", n=1)
            if lighting_top:
                atmo_pref = lighting_top[0]["value"]
            # If style preferences from PM differ from fingerprint, blend in
            style_top = pm.top_preferences("style", n=3)
            for s in style_top:
                if s["value"] not in [x.lower() for x in fp_styles]:
                    fp_styles.append(s["value"])
        except Exception:
            pass

        # 5. PersonalityModel ambition (for confidence shaping)
        avg_ambition = 0.6
        try:
            from engine.personality_model import get_personality
            pmsnap = get_personality().snapshot()
            avg_ambition = float(pmsnap.get("ambition_avg", 0.6) or 0.6)
        except Exception:
            pass

        # 6. Refinement history — pull from QualityGate
        refinement_history: dict = {"avg_passes": 0.0, "success_rate": 0.0}
        try:
            from engine.quality_gate import get_quality_gate
            qs = get_quality_gate().stats()
            done = int(qs.get("done", 0) or 0)
            queued = int(qs.get("queued", 0) or 0)
            total = done + queued + int(qs.get("abandoned", 0) or 0)
            if total > 0:
                refinement_history["success_rate"] = round(done / total, 3)
                refinement_history["avg_passes"] = round(done / max(1, success_count), 2)
        except Exception:
            pass

        # Confidence = ramp of interaction count + success count
        # Stable confidence at 25+ interactions or 8+ successes
        confidence = min(1.0, max(interaction_count / 25.0, success_count / 8.0))

        # Identity statements
        cin_identity = self._cinematic_identity(fp_styles, motifs, pacing_pref)
        atm_identity = self._atmosphere_identity(fp_styles, atmo_pref, fp_palette)
        summary      = self._summary(fp_styles, motifs, avg_ambition,
                                      avg_success_score, interaction_count,
                                      confidence)

        profile = UnifiedCreativeProfile(
            profile_id=f"profile-{int(time.time()*1000):x}",
            stylistic_signature=fp_styles[:3],
            emotional_tendencies=fp_emotions[:3],
            motif_persistence=motifs[:5],
            pacing_preference=pacing_pref or "—",
            cinematic_identity=cin_identity,
            atmosphere_identity=atm_identity,
            refinement_history=refinement_history,
            aesthetic_confidence=round(confidence, 3),
            interaction_count=interaction_count,
            summary=summary,
            computed_at=time.time(),
        )
        self._persist(profile)
        self._emit_receipt(profile)
        return profile

    def _cinematic_identity(self, styles, motifs, pacing) -> str:
        if not styles and not motifs:
            return "unsettled"
        bits = []
        if styles: bits.append(f"{styles[0]}-leaning")
        if pacing and pacing != "—": bits.append(f"{pacing} pacing")
        if motifs: bits.append(f"motif: {motifs[0]}")
        return ", ".join(bits) or "developing"

    def _atmosphere_identity(self, styles, atmo_pref, palette) -> str:
        if not styles:
            return "neutral"
        bits = []
        if atmo_pref: bits.append(atmo_pref)
        if palette: bits.append(f"palette gravitates to {palette[0]}")
        return ", ".join(bits) or styles[0]

    def _summary(self, styles, motifs, avg_ambition, avg_success,
                  count, confidence) -> str:
        if confidence < 0.15:
            return ("Creative profile nascent — submit more compositions to "
                    "stabilize the fingerprint.")
        bits = []
        if styles: bits.append(f"prefers {', '.join(styles[:2])}")
        if motifs: bits.append(f"recurring motifs: {', '.join(motifs[:3])}")
        if avg_ambition > 0.8:
            bits.append("high ambition")
        elif avg_ambition < 0.4:
            bits.append("restrained ambition")
        if avg_success > 0.8:
            bits.append("compositions consistently score high")
        return "Operator " + "; ".join(bits) + "." if bits else "Profile forming."

    def _persist(self, profile: UnifiedCreativeProfile) -> None:
        try:
            _PATH.parent.mkdir(parents=True, exist_ok=True)
            _PATH.write_text(json.dumps(profile.to_dict(), indent=2),
                              encoding="utf-8")
        except Exception as e:
            _log.warning("unified profile persist failed: %s", e)

    def _emit_receipt(self, p: UnifiedCreativeProfile) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="unified_creative_profile:computed",
                executor="UnifiedCreativeProfile",
                artifact=str(_PATH),
                duration_ms=0.0, verified=True, compute_sha256=False,
                evidence={
                    "profile_id":        p.profile_id,
                    "confidence":        p.aesthetic_confidence,
                    "interaction_count": p.interaction_count,
                    "top_styles":        p.stylistic_signature,
                    "top_motifs":        p.motif_persistence,
                    "pacing_preference": p.pacing_preference,
                },
            )
        except Exception:
            pass


_INSTANCE: Optional[_UnifiedCreativeProfileComputer] = None


def get_unified_profile() -> _UnifiedCreativeProfileComputer:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = _UnifiedCreativeProfileComputer()
    return _INSTANCE
