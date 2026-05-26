"""engine/oracle/ambition_interpreter.py — analyze operator ambition signal."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass(frozen=True)
class AmbitionAssessment:
    ambition_score:    float      # 0..1
    band:              str        # exploratory | crafted | production | masterwork
    drivers:           list       # words / phrases that drove the score
    capability_match:  str        # what the system can realistically deliver

    def to_dict(self) -> dict:
        return asdict(self)


_DRIVERS = [
    (r"\b(legendary|epic|masterpiece|magnum opus|grand|monumental)\b", 0.95, "legendary"),
    (r"\b(cinematic|production[- ]?grade|broadcast|theatrical)\b",     0.85, "production-grade"),
    (r"\b(polished|refined|high[- ]?quality|premium)\b",                0.75, "polished"),
    (r"\b(quick|rough|sketch|draft|prototype)\b",                       0.35, "exploratory"),
    (r"\b(test|demo|sample|placeholder)\b",                             0.20, "test-grade"),
]


class AmbitionInterpreter:

    def __init__(self):
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.ambition_interpreter", self)
        except Exception:
            pass

    def assess(self, intent_text: str) -> AmbitionAssessment:
        t = (intent_text or "").lower()
        score = 0.6
        drivers: list[str] = []
        for pat, val, label in _DRIVERS:
            if re.search(pat, t):
                score = max(score, val) if val > 0.6 else min(score, val)
                drivers.append(label)
        # Length is also a signal: longer intents tend to be more ambitious
        word_count = len(re.findall(r"\w+", t))
        if word_count > 16:
            score = min(1.0, score + 0.05)
            drivers.append(f"long_intent({word_count}w)")

        if score >= 0.85:
            band = "masterwork"
            cap = ("masterwork ambition exceeds rule-based generation alone — "
                   "ensure real backends (ComfyUI/A1111 + ffmpeg + audiocraft) "
                   "are reachable, otherwise outputs will fall short")
        elif score >= 0.70:
            band = "production"
            cap = "production-grade is achievable when image + audio backends READY"
        elif score >= 0.45:
            band = "crafted"
            cap = "crafted outputs achievable with any backend, including procedural"
        else:
            band = "exploratory"
            cap = "exploratory outputs guaranteed via internal fallbacks"

        return AmbitionAssessment(
            ambition_score=round(score, 3),
            band=band,
            drivers=drivers,
            capability_match=cap,
        )


_INSTANCE: Optional[AmbitionInterpreter] = None


def get_ambition_interpreter() -> AmbitionInterpreter:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = AmbitionInterpreter()
    return _INSTANCE
