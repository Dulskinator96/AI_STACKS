"""engine/aesthetic_intelligence/emotional_resonance.py — emotion impact scoring."""
from __future__ import annotations


_TONE_VALENCE = {
    "legendary":   ( 0.7, 0.9),
    "epic":        ( 0.6, 0.9),
    "intense":     ( 0.3, 0.9),
    "dark":        (-0.4, 0.6),
    "horror":      (-0.7, 0.7),
    "fear":        (-0.6, 0.7),
    "serene":      ( 0.5, 0.2),
    "melancholic": (-0.5, 0.3),
    "joyful":      ( 0.8, 0.6),
    "triumph":     ( 0.9, 0.7),
    "eerie":       (-0.3, 0.4),
    "playful":     ( 0.6, 0.5),
    "mysterious":  (-0.1, 0.4),
    "emotional":   ( 0.0, 0.7),
    "longing":     (-0.3, 0.4),
    "wonder":      ( 0.6, 0.5),
    "solitude":    (-0.4, 0.3),
}


class EmotionalResonanceScorer:
    """Emotional impact = ambition × (tone valence magnitude) + emotion alignment."""

    def score(self, spec) -> tuple:
        breakdown: dict = {}
        tone = (getattr(spec, "tone", "") or "").lower()
        emotion = (getattr(spec, "emotion", "") or "").lower()
        ambition = float(getattr(spec, "ambition", 0.6) or 0.6)

        v, a = _TONE_VALENCE.get(tone, (0.0, 0.5))
        breakdown["tone"] = tone or "none"
        breakdown["tone_valence"] = v
        breakdown["tone_arousal"] = a

        # Resonance = ambition × arousal × |valence| magnitude
        magnitude = (abs(v) + a) / 2.0     # 0..1
        base = 0.4 + 0.4 * ambition + 0.2 * magnitude
        breakdown["ambition"] = ambition

        # Emotion alignment bonus
        if emotion and tone:
            # Both present: a coherent profile
            breakdown["emotion"] = emotion
            base = min(1.0, base + 0.05)
        elif not tone and not emotion:
            base *= 0.7  # bland spec

        return round(min(1.0, max(0.0, base)), 3), breakdown
