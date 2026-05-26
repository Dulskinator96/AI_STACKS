"""engine/cinematic_director/pacing_engine.py — real time codes per scene.

Computes start_s + end_s + escalation_intensity for every scene in a
storyboard based on the cinematic_profile's pacing.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass(frozen=True)
class ScenePacing:
    scene_id:    str
    beat:        str
    start_s:     float
    end_s:       float
    duration_s:  float
    intensity:   float       # 0..1 — escalation curve sample
    transition_in: str

    def to_dict(self) -> dict:
        return asdict(self)


# Per-pacing escalation curves: function (i, n) → intensity 0..1
def _intensity_for(pacing: str, i: int, n: int) -> float:
    if n <= 1:
        return 0.7
    x = i / max(1, n - 1)   # 0..1
    if pacing == "rising_then_held":
        return min(1.0, x * 1.8) if x < 0.55 else 0.95
    if pacing == "driving":
        return 0.55 + 0.4 * x
    if pacing == "slow_oppressive":
        return 0.35 + 0.3 * x
    if pacing == "languid":
        return 0.3 + 0.2 * math.sin(x * math.pi)
    if pacing == "wistful":
        return 0.4 + 0.15 * math.sin(x * math.pi)
    if pacing == "lifted":
        return 0.5 + 0.4 * x
    if pacing == "off_kilter":
        return 0.4 + 0.3 * abs(math.sin(x * 4))
    if pacing == "syncopated":
        return 0.5 + 0.3 * math.sin(x * 6.28 * 2)
    if pacing == "patient":
        return 0.35 + 0.1 * x
    if pacing == "swelling":
        # Slow rise then fast peak
        return 0.3 + 0.65 * (x ** 1.4)
    if pacing == "measured":
        return 0.5 + 0.2 * math.sin(x * math.pi)
    return 0.5 + 0.3 * x


class PacingEngine:
    """Compute scene-by-scene timing + intensity curve."""

    def __init__(self):
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.pacing_engine", self)
        except Exception:
            pass

    def derive(self, composition_plan) -> list:
        """Return list of ScenePacing for every scene in the plan."""
        if composition_plan is None:
            return []
        sb = getattr(composition_plan, "storyboard", None)
        cin = getattr(composition_plan, "cinematic", None)
        if sb is None or cin is None:
            return []
        scenes = list(getattr(sb, "scenes", []) or [])
        if not scenes:
            return []
        pacing = (getattr(cin, "pacing", "") or "measured").lower()
        transition = (getattr(cin, "transition_style", "") or "cut").lower()

        out: list[ScenePacing] = []
        cursor = 0.0
        n = len(scenes)
        for i, s in enumerate(scenes):
            duration = float(getattr(s, "duration_s", 1.0) or 1.0)
            intensity = _intensity_for(pacing, i, n)
            out.append(ScenePacing(
                scene_id=getattr(s, "scene_id", f"s-{i}"),
                beat=getattr(s, "beat", ""),
                start_s=round(cursor, 3),
                end_s=round(cursor + duration, 3),
                duration_s=round(duration, 3),
                intensity=round(intensity, 3),
                transition_in=transition if i > 0 else "open",
            ))
            cursor += duration
        return out


_INSTANCE: Optional[PacingEngine] = None


def get_pacing_engine() -> PacingEngine:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = PacingEngine()
    return _INSTANCE
