"""engine/semantic_memory/creative_identity.py — operator's evolved fingerprint.

Composes PersonalityMatrix + MotifTracker + SuccessfulOutputMemory into
a single CreativeIdentity. The Oracle consults this to give personalized
recommendations.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CreativeIdentity:
    identity_id:       str
    top_styles:        list
    top_motifs:        list
    top_palette:       list
    avg_cqi:           float
    interaction_count: int
    avg_ambition:      float
    summary_sentence:  str
    computed_at:       float

    def to_dict(self) -> dict:
        return asdict(self)


class _CreativeIdentityComputer:

    def __init__(self):
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.creative_identity", self)
        except Exception:
            pass

    def compute(self) -> CreativeIdentity:
        top_styles: list = []
        top_palette: list = []
        avg_ambition = 0.6
        interaction_count = 0
        try:
            from engine.personality_matrix import get_personality_matrix
            ms = get_personality_matrix().snapshot()
            top_styles = list(ms.fingerprint.top_styles or [])
            top_palette = list(ms.fingerprint.top_palette or [])
            interaction_count = int(ms.interaction_count or 0)
        except Exception as e:
            _log.debug("personality matrix unavailable: %s", e)
        try:
            from engine.personality_model import get_personality
            pmsnap = get_personality().snapshot()
            avg_ambition = float(pmsnap.get("ambition_avg", 0.6) or 0.6)
        except Exception:
            pass

        top_motifs: list = []
        try:
            from engine.semantic_memory.motif_tracking import get_motif_tracker
            top_motifs = list(get_motif_tracker().top_motifs(5))
        except Exception:
            pass

        avg_cqi = 0.0
        try:
            from engine.semantic_memory.successful_output_memory import get_successful_output_memory
            sm = get_successful_output_memory().snapshot()
            avg_cqi = float(sm.get("avg_score", 0.0) or 0.0)
        except Exception:
            pass

        summary = self._summary(top_styles, top_motifs, avg_cqi, avg_ambition,
                                  interaction_count)
        return CreativeIdentity(
            identity_id=f"id-{int(time.time()*1000):x}",
            top_styles=top_styles[:3],
            top_motifs=top_motifs[:5],
            top_palette=top_palette[:3],
            avg_cqi=round(avg_cqi, 3),
            interaction_count=interaction_count,
            avg_ambition=round(avg_ambition, 3),
            summary_sentence=summary,
            computed_at=time.time(),
        )

    def _summary(self, styles, motifs, avg_cqi, avg_ambition, count) -> str:
        if count < 3:
            return "Creative identity nascent — submit more intents to deepen."
        bits = []
        if styles: bits.append(f"gravitates toward {', '.join(styles[:2])}")
        if motifs: bits.append(f"recurring motifs: {', '.join(motifs[:3])}")
        if avg_ambition > 0.8:
            bits.append("high ambition")
        elif avg_ambition < 0.4:
            bits.append("restrained ambition")
        if avg_cqi > 0.8:
            bits.append("compositions consistently score high")
        return "Operator " + "; ".join(bits) + "." if bits else "Identity in formation."


_INSTANCE: Optional[_CreativeIdentityComputer] = None


def get_creative_identity():
    """Compute the current CreativeIdentity snapshot."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = _CreativeIdentityComputer()
    return _INSTANCE.compute()
