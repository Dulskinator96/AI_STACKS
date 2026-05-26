"""engine/creative_expansion.py — PHASE 5.

Turn minimal prompts into production-grade specifications.

Strategy:
  · Rule-based by default (deterministic, fast, no LLM dependency)
  · Optional Ollama enrichment when available (recorded as PARTIAL when
    used so the operator knows which fields came from inference vs LLM)

INVARIANT: never drift away from intent. Expansion ADDS detail; it does
not override what the operator already specified.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExpandedSpec:
    """Production-grade specification expanded from EnrichedIntent."""
    intent_id:           str
    raw_text:            str
    medium:              Optional[str]
    realm:               Optional[str]
    style:               Optional[str]
    tone:                Optional[str]
    lighting:            Optional[str]
    composition:         Optional[str]
    emotion:             Optional[str]
    detail_level:        Optional[str]
    ambition:            float
    # Production-grade additions
    architecture_style:  Optional[str]
    atmosphere:          Optional[str]
    weather:             Optional[str]
    soundtrack_profile:  Optional[str]
    camera_style:        Optional[str]
    world_lore:          Optional[str]
    rendering_profile:   Optional[str]
    color_palette:       list = field(default_factory=list)
    expansion_source:    str = "rule_based"   # rule_based | llm | hybrid
    inferred_fields:     list = field(default_factory=list)
    timestamp:           float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# Style → production-grade expansion templates. Each entry contributes
# architecture/atmosphere/weather/soundtrack hints. Rule-based, no LLM.
_STYLE_EXPANSION = {
    "cyberpunk": {
        "architecture_style":  "neo-brutalist megastructures + bioluminescent signage",
        "atmosphere":          "rain-slicked streets, holographic ads, neon haze",
        "weather":             "perpetual drizzle, low-hanging fog",
        "soundtrack_profile":  "synthwave + industrial percussion + low sub bass",
        "camera_style":        "anamorphic lens flare, low-angle wide tracking",
        "world_lore":          "post-corporate dystopia, augmented underclass",
        "rendering_profile":   "8-bit color depth, chromatic aberration, scanlines",
        "color_palette":       ["#ff2d92", "#28e6ff", "#1a0e3e", "#ffce28"],
    },
    "sci-fi": {
        "architecture_style":  "modular alloy structures + arcology spires",
        "atmosphere":          "vast scale, clean lines, distant gas giants",
        "weather":             "thin atmosphere, plasma storms on horizon",
        "soundtrack_profile":  "drone pads + sparse percussion + analog warmth",
        "camera_style":        "slow dolly + wide establishing shots",
        "world_lore":          "interstellar exploration era, ancient relics",
        "rendering_profile":   "physically-based rendering, accurate atmospherics",
        "color_palette":       ["#06091c", "#3a8fc8", "#cce0f0", "#f0a030"],
    },
    "fantasy": {
        "architecture_style":  "carved stone, vaulted timber, moss-overgrown ruins",
        "atmosphere":          "thick forest canopy, glowing motes, ancient magic",
        "weather":             "misty mornings, twilight light shafts",
        "soundtrack_profile":  "celtic strings + choral pad + breathy flute",
        "camera_style":        "handheld + low-key naturalistic light",
        "world_lore":          "lost kingdom, dormant artifact, prophecy",
        "rendering_profile":   "painterly, soft volumetric haze",
        "color_palette":       ["#2a3018", "#a0c060", "#d8b878", "#6040b8"],
    },
    "noir": {
        "architecture_style":  "art-deco metro, brick alleys, smoky offices",
        "atmosphere":          "venetian-blind shadows, cigarette haze",
        "weather":             "rain after dark, wet asphalt reflections",
        "soundtrack_profile":  "lone saxophone + walking bass + brushed drums",
        "camera_style":        "high-contrast B&W, chiaroscuro key light",
        "world_lore":          "corruption, missing person, double-cross",
        "rendering_profile":   "monochrome, hard grain",
        "color_palette":       ["#000", "#fff", "#808080", "#c04848"],
    },
    "horror": {
        "architecture_style":  "decayed gothic, cyclopean masonry, non-Euclidean angles",
        "atmosphere":          "wrongness, glimpsed motion, distant whispers",
        "weather":             "still air, oppressive heat or cold",
        "soundtrack_profile":  "dissonant strings + tape hiss + sub drone",
        "camera_style":        "static long takes + occasional whip-pan",
        "world_lore":          "buried truth, returning evil, sanity erosion",
        "rendering_profile":   "low light, deep shadow, occasional impossible geometry",
        "color_palette":       ["#06090e", "#2a0a1a", "#c04848", "#a08070"],
    },
    "anime": {
        "architecture_style":  "stylized rooftops, cherry blossom courtyards, school halls",
        "atmosphere":          "expressive light, energetic posing",
        "weather":             "dramatic rain, sun rays, sakura flurries",
        "soundtrack_profile":  "j-rock guitars + orchestral swell + emotional vocal",
        "camera_style":        "cel-shaded, hard line, speed lines on action",
        "world_lore":          "coming-of-age stakes, friendship bonds, hidden power",
        "rendering_profile":   "cel-shaded, line-art driven, saturated palette",
        "color_palette":       ["#ff8eb7", "#28e6ff", "#fff5e0", "#ffce28"],
    },
    "synthwave": {
        "architecture_style":  "outrun grid horizons, retrofuturist towers",
        "atmosphere":          "perpetual sunset, palm silhouettes, vapor mist",
        "weather":             "warm dusk, lavender clouds",
        "soundtrack_profile":  "analog synth lead + gated reverb drums + arpeggio",
        "camera_style":        "wide dolly + slow lens flare drift",
        "world_lore":          "1980s never-was, neon nostalgia, chrome dreams",
        "rendering_profile":   "magenta/cyan gradient, scanline overlay, glow",
        "color_palette":       ["#ff2d92", "#28e6ff", "#6040b8", "#ffce28"],
    },
    "painterly": {
        "architecture_style":  "loose impressionist mass, palette-knife structures",
        "atmosphere":          "broken light, atmospheric perspective",
        "weather":             "diffused, atmospheric haze",
        "soundtrack_profile":  "string quartet + woodwind + piano",
        "camera_style":        "wide composition + classical thirds",
        "world_lore":          "pastoral, contemplative, observed moments",
        "rendering_profile":   "visible brushwork, soft edges, broken color",
        "color_palette":       ["#cce0f0", "#f0a030", "#3a8fc8", "#a08070"],
    },
    "cinematic": {
        "architecture_style":  "real-world location-grade detail",
        "atmosphere":          "production-grade depth, intentional lensing",
        "weather":             "weather as character beat",
        "soundtrack_profile":  "orchestral underscore + designed sound",
        "camera_style":        "lens-aware framing + motivated camera move",
        "world_lore":          "grounded stakes, internal arc",
        "rendering_profile":   "filmic, 2.39:1 framing, finished color grade",
        "color_palette":       ["#1a0e3e", "#cce0f0", "#f0a030", "#c04868"],
    },
}

# Tone → emotional/pacing reinforcement
_TONE_REINFORCEMENT = {
    "legendary":   {"soundtrack_intensity": 0.95, "pacing": "rising_then_held"},
    "dark":        {"soundtrack_intensity": 0.75, "pacing": "slow_oppressive"},
    "serene":      {"soundtrack_intensity": 0.30, "pacing": "languid"},
    "intense":     {"soundtrack_intensity": 0.90, "pacing": "driving"},
    "melancholic": {"soundtrack_intensity": 0.45, "pacing": "wistful"},
    "joyful":      {"soundtrack_intensity": 0.70, "pacing": "lifted"},
    "eerie":       {"soundtrack_intensity": 0.55, "pacing": "off-kilter"},
    "playful":     {"soundtrack_intensity": 0.65, "pacing": "syncopated"},
    "mysterious":  {"soundtrack_intensity": 0.50, "pacing": "patient"},
    "emotional":   {"soundtrack_intensity": 0.80, "pacing": "swelling"},
}


class CreativeExpansionLayer:
    """Rule-based expansion (deterministic). Future builds may layer LLM
    on top — when they do, expansion_source flips to 'hybrid' so the
    receipt records which fields came from inference vs language model."""

    def __init__(self):
        self._expansion_count = 0

    def expand(self, enriched_intent, personality=None) -> ExpandedSpec:
        """Expand an EnrichedIntent into a production-grade spec.
        Personality (if provided) biases blank fields to operator-favored
        choices — but never overrides what the operator explicitly stated.
        """
        t0 = time.time()
        ei = enriched_intent
        style = ei.style
        tone  = ei.tone

        # Personality bias: if style/tone were never stated, pull from
        # operator preference vectors. Marks the field as 'inferred'.
        inferred: list[str] = []
        if style is None and personality is not None:
            top = personality.top_preference("aesthetic")
            if top:
                style = top
                inferred.append("style:personality_default")
        if tone is None and personality is not None:
            top = personality.top_preference("tone")
            if top:
                tone = top
                inferred.append("tone:personality_default")

        template = _STYLE_EXPANSION.get(style or "", {})
        tone_pkg = _TONE_REINFORCEMENT.get(tone or "", {})

        architecture = template.get("architecture_style")
        atmosphere   = template.get("atmosphere")
        weather      = template.get("weather")
        soundtrack   = template.get("soundtrack_profile")
        camera       = template.get("camera_style")
        lore         = template.get("world_lore")
        rendering    = template.get("rendering_profile")
        palette      = list(template.get("color_palette", []))

        if soundtrack and tone_pkg.get("pacing"):
            soundtrack = f"{soundtrack} · pacing: {tone_pkg['pacing']}"

        # Lighting / composition fallbacks from style template inference
        # only if they weren't already inferred from the prompt.
        if not template and style is None:
            inferred.append("style:unresolved")

        spec = ExpandedSpec(
            intent_id=f"intent-{int(t0*1000):x}",
            raw_text=ei.raw_text,
            medium=ei.medium,
            realm=ei.realm,
            style=style,
            tone=tone,
            lighting=ei.lighting,
            composition=ei.composition,
            emotion=ei.emotion,
            detail_level=ei.detail_level or ("ultra-high" if ei.ambition > 0.85 else
                                              "high" if ei.ambition > 0.5 else "moderate"),
            ambition=ei.ambition,
            architecture_style=architecture,
            atmosphere=atmosphere,
            weather=weather,
            soundtrack_profile=soundtrack,
            camera_style=camera,
            world_lore=lore,
            rendering_profile=rendering,
            color_palette=palette,
            expansion_source="rule_based",
            inferred_fields=inferred,
            timestamp=t0,
        )
        self._expansion_count += 1
        self._emit_receipt(spec, (time.time() - t0) * 1000.0)
        return spec

    def _emit_receipt(self, spec: ExpandedSpec, dur_ms: float) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="creative_expansion:expand",
                executor="CreativeExpansionLayer",
                duration_ms=dur_ms,
                verified=True,
                compute_sha256=False,
                evidence={
                    "intent_id":        spec.intent_id,
                    "style":            spec.style,
                    "tone":             spec.tone,
                    "medium":           spec.medium,
                    "detail_level":     spec.detail_level,
                    "ambition":         spec.ambition,
                    "expansion_source": spec.expansion_source,
                    "inferred_fields":  spec.inferred_fields,
                    "palette_size":     len(spec.color_palette),
                    "has_architecture": spec.architecture_style is not None,
                    "has_soundtrack":   spec.soundtrack_profile is not None,
                },
            )
        except Exception:
            pass
