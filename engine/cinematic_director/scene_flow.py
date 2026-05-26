"""engine/cinematic_director/scene_flow.py — climax architecture detector.

Finds the climax beat in a pacing curve and validates the build-up shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass(frozen=True)
class FlowAssessment:
    climax_index:    int
    climax_intensity: float
    build_up_shape:  str     # "ideal" | "front_loaded" | "back_loaded" | "flat" | "chaotic"
    issues:          list

    def to_dict(self) -> dict:
        return asdict(self)


class SceneFlow:

    def __init__(self):
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.scene_flow", self)
        except Exception:
            pass

    def assess(self, scene_pacings: list) -> FlowAssessment:
        if not scene_pacings:
            return FlowAssessment(0, 0.0, "flat", ["no scenes"])
        intensities = [sp.intensity for sp in scene_pacings]
        climax_i = max(range(len(intensities)), key=lambda i: intensities[i])
        climax_v = intensities[climax_i]
        n = len(intensities)

        issues: list[str] = []
        # Ideal: climax in middle-late third + monotonic rise to it
        if n < 3:
            shape = "flat"
        else:
            front = intensities[:climax_i]
            back = intensities[climax_i:]
            front_monotonic = all(front[j] <= front[j+1] for j in range(len(front)-1)) if front else True
            back_falls = (back[-1] < climax_v - 0.05) if len(back) > 1 else False
            climax_position = climax_i / max(1, n - 1)
            if 0.5 <= climax_position <= 0.8 and front_monotonic:
                shape = "ideal"
            elif climax_position < 0.3:
                shape = "front_loaded"
                issues.append("climax arrives too early — back half drags")
            elif climax_position > 0.85:
                shape = "back_loaded"
                issues.append("climax saved for the end — no resolution beat")
            elif not front_monotonic:
                shape = "chaotic"
                issues.append("intensity zigzags before the climax")
            else:
                shape = "flat" if (max(intensities) - min(intensities) < 0.15) else "ideal"

        return FlowAssessment(climax_i, climax_v, shape, issues)


_INSTANCE: Optional[SceneFlow] = None


def get_scene_flow() -> SceneFlow:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = SceneFlow()
    return _INSTANCE
