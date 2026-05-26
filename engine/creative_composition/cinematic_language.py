"""engine/creative_composition/cinematic_language.py — camera + composition.

Specifies the cinematic grammar a composition plan operates on:
  · camera_style (wide / close / dolly / handheld / static)
  · lens_personality (anamorphic / spherical / vintage / clinical)
  · pacing (slow_oppressive / driving / measured / lingering / syncopated)
  · transition_style (cut / dissolve / wipe / cinematic_match_cut)
  · composition_grammar (rule_of_thirds / centered_heroic / symmetric / negative_space)

Rule-based — derives from EnrichedIntent + ExpandedSpec.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass(frozen=True)
class CinematicProfile:
    profile_id:          str
    camera_style:        str
    lens_personality:    str
    pacing:              str
    transition_style:    str
    composition_grammar: str
    lighting_grammar:    str
    created_at:          float

    def to_dict(self) -> dict:
        return asdict(self)

    def render(self) -> str:
        return (f"  ▸ camera: {self.camera_style} · lens: {self.lens_personality}\n"
                f"  ▸ pacing: {self.pacing} · transitions: {self.transition_style}\n"
                f"  ▸ composition: {self.composition_grammar} · "
                f"lighting: {self.lighting_grammar}")


class CinematicLanguage:
    """Maps style/tone/ambition → cinematic grammar."""

    def derive(self, spec) -> CinematicProfile:
        style = (getattr(spec, "style", "") or "").lower()
        tone  = (getattr(spec, "tone",  "") or "").lower()
        ambition = float(getattr(spec, "ambition", 0.6) or 0.6)
        composition = (getattr(spec, "composition", "") or "").lower()
        lighting = (getattr(spec, "lighting", "") or "").lower()

        # Camera
        if style in ("cyberpunk", "synthwave"):
            camera = "wide_dolly"
        elif style in ("noir", "horror"):
            camera = "static_long_take"
        elif style in ("anime",):
            camera = "dynamic_speed_lines"
        elif tone in ("intense", "epic", "legendary"):
            camera = "tracking_wide"
        else:
            camera = "measured_wide"

        # Lens
        if style in ("cyberpunk", "sci-fi"):
            lens = "anamorphic_flare"
        elif style == "noir":
            lens = "vintage_spherical"
        elif style == "horror":
            lens = "clinical_wide"
        elif style in ("painterly",):
            lens = "soft_optical"
        else:
            lens = "neutral_spherical"

        # Pacing
        pacing_map = {
            "legendary":   "rising_then_held",
            "intense":     "driving",
            "dark":        "slow_oppressive",
            "serene":      "languid",
            "melancholic": "wistful",
            "joyful":      "lifted",
            "eerie":       "off_kilter",
            "playful":     "syncopated",
            "mysterious":  "patient",
            "emotional":   "swelling",
        }
        pacing = pacing_map.get(tone, "measured")

        # Transitions
        if pacing in ("driving", "rising_then_held"):
            transition = "cinematic_match_cut"
        elif pacing in ("slow_oppressive", "patient"):
            transition = "long_dissolve"
        elif pacing == "syncopated":
            transition = "rhythmic_cut"
        else:
            transition = "cut"

        # Composition grammar
        if composition:
            grammar = composition.replace(" ", "_")
        elif tone in ("legendary", "epic", "triumph"):
            grammar = "heroic_centered"
        elif style == "noir":
            grammar = "negative_space"
        elif style == "minimalist":
            grammar = "symmetric"
        else:
            grammar = "rule_of_thirds"

        # Lighting grammar
        if lighting:
            light = lighting.replace(" ", "_")
        elif style in ("cyberpunk", "synthwave"):
            light = "neon_rim"
        elif style == "noir":
            light = "chiaroscuro"
        elif style == "horror":
            light = "low_key"
        elif style in ("anime", "painterly"):
            light = "stylized_warm"
        elif ambition > 0.85:
            light = "production_filmic"
        else:
            light = "soft_diffused"

        return CinematicProfile(
            profile_id=f"cin-{uuid.uuid4().hex[:8]}",
            camera_style=camera,
            lens_personality=lens,
            pacing=pacing,
            transition_style=transition,
            composition_grammar=grammar,
            lighting_grammar=light,
            created_at=time.time(),
        )
