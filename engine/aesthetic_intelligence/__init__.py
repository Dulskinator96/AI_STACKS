"""engine/aesthetic_intelligence/ — BUILD-027A Aesthetic Intelligence Engine.

Computes the Creative Quality Index (CQI): an 8-dimension aesthetic score
that replaces simplistic READY/FAIL thinking with "meaningful composition"
evaluation. Composed from spec + artifact properties + personality match.

Dimensions:
  · atmosphere
  · emotional_impact
  · cinematic_intensity
  · visual_harmony
  · pacing_quality
  · thematic_coherence
  · originality
  · memorability
"""
from engine.aesthetic_intelligence.aesthetic_reasoner import (
    AestheticReasoner, get_aesthetic_reasoner, CQI,
)
from engine.aesthetic_intelligence.visual_harmony      import VisualHarmonyScorer
from engine.aesthetic_intelligence.emotional_resonance import EmotionalResonanceScorer
from engine.aesthetic_intelligence.cinematic_rhythm    import CinematicRhythmScorer

__all__ = [
    "AestheticReasoner", "get_aesthetic_reasoner", "CQI",
    "VisualHarmonyScorer", "EmotionalResonanceScorer", "CinematicRhythmScorer",
]
