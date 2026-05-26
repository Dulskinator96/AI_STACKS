"""engine/aesthetic_intelligence/cinematic_rhythm.py — pacing + escalation scoring."""
from __future__ import annotations


class CinematicRhythmScorer:
    """Score the cinematic profile's rhythm. Higher when pacing matches tone."""

    _GOOD_PAIRS = {
        ("driving",            "intense"),
        ("driving",            "epic"),
        ("rising_then_held",   "legendary"),
        ("rising_then_held",   "triumph"),
        ("slow_oppressive",    "dark"),
        ("slow_oppressive",    "horror"),
        ("languid",            "serene"),
        ("wistful",            "melancholic"),
        ("lifted",             "joyful"),
        ("off_kilter",         "eerie"),
        ("syncopated",         "playful"),
        ("patient",            "mysterious"),
        ("swelling",           "emotional"),
    }

    def score(self, spec, cinematic_profile=None) -> tuple:
        breakdown: dict = {}
        tone = (getattr(spec, "tone", "") or "").lower()
        pacing = (getattr(cinematic_profile, "pacing", "") or "").lower() \
                  if cinematic_profile is not None else ""

        breakdown["pacing"] = pacing or "none"
        breakdown["tone"] = tone or "none"

        if not pacing:
            return 0.5, breakdown

        if (pacing, tone) in self._GOOD_PAIRS:
            breakdown["match"] = "ideal"
            return 0.92, breakdown
        if not tone:
            breakdown["match"] = "neutral"
            return 0.65, breakdown
        breakdown["match"] = "mismatched"
        return 0.45, breakdown
