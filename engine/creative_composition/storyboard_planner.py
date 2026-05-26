"""engine/creative_composition/storyboard_planner.py — scene breakdown.

Decomposes an intent into a sequence of Scenes. Each Scene carries
beat, focal subject, intended mood, and an estimated duration. The
storyboard is realm-agnostic — workers later translate scenes to
realm-specific artifacts.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

_log = logging.getLogger(__name__)


# Beat templates per pipeline kind (from production_pipeline_engine):
_BEAT_TEMPLATES = {
    "trailer":   ["cold_open", "rising_tension", "stakes_reveal",
                  "climax_montage", "title_drop", "tag_out"],
    "game":      ["world_establishing", "core_loop_intro", "tension_arc",
                  "climactic_encounter", "afterglow"],
    "album":     ["opener", "groove", "anchor", "interlude", "closer"],
    "gallery":   ["primary_hero", "context_wide", "detail_macro"],
    "simulation":["bootstrap", "agent_phase", "interaction_phase", "resolution"],
}


@dataclass(frozen=True)
class Scene:
    scene_id:    str
    beat:        str
    focal:       str         # what the scene is about (subject)
    mood:        str
    duration_s:  float
    notes:       str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Storyboard:
    storyboard_id: str
    pipeline_kind: str
    scenes:        list
    total_duration_s: float
    raw_intent:    str
    created_at:    float

    def to_dict(self) -> dict:
        d = asdict(self)
        d["scenes"] = [s.to_dict() if isinstance(s, Scene) else s
                       for s in self.scenes]
        return d

    def render(self) -> str:
        lines = [f"⌬ Storyboard · {self.pipeline_kind} · "
                 f"{len(self.scenes)} scenes · {self.total_duration_s:.1f}s"]
        for i, s in enumerate(self.scenes, 1):
            lines.append(f"  {i:>2}. [{s.beat}] {s.focal}  ·  {s.mood}  "
                         f"({s.duration_s:.1f}s)")
        return "\n".join(lines)


class StoryboardPlanner:
    """Rule-based scene decomposer. Deterministic, no LLM."""

    def plan(self, intent_text: str, spec, pipeline_kind: str = "gallery") -> Storyboard:
        beats = _BEAT_TEMPLATES.get(pipeline_kind, _BEAT_TEMPLATES["gallery"])
        intent = intent_text or "scene"
        tone = (getattr(spec, "tone", "") or "") if spec else ""
        scenes: list[Scene] = []
        # Per-pipeline scene duration baseline
        per_scene = {
            "trailer":    [3.0, 5.0, 4.0, 6.0, 3.0, 2.0],
            "game":       [6.0, 5.0, 8.0, 7.0, 4.0],
            "album":      [60.0, 90.0, 90.0, 45.0, 70.0],
            "gallery":    [1.0, 1.0, 1.0],
            "simulation": [2.0, 4.0, 6.0, 3.0],
        }.get(pipeline_kind, [1.0] * len(beats))

        for i, beat in enumerate(beats):
            duration = per_scene[i] if i < len(per_scene) else 2.0
            focal = self._focal_for(beat, intent, i)
            mood = self._mood_for(beat, tone)
            scenes.append(Scene(
                scene_id=f"s-{uuid.uuid4().hex[:6]}",
                beat=beat, focal=focal, mood=mood,
                duration_s=duration,
                notes="",
            ))

        sb = Storyboard(
            storyboard_id=f"sb-{uuid.uuid4().hex[:8]}",
            pipeline_kind=pipeline_kind,
            scenes=scenes,
            total_duration_s=sum(s.duration_s for s in scenes),
            raw_intent=intent[:200],
            created_at=time.time(),
        )
        self._emit_receipt(sb)
        return sb

    def _focal_for(self, beat: str, intent: str, idx: int) -> str:
        # Extract a noun phrase from the intent + a beat-specific framing
        terms = [w for w in re.findall(r"[A-Za-z]{4,}", intent.lower())
                 if w not in _STOP]
        focal_word = terms[idx % len(terms)] if terms else "scene"
        framings = {
            "cold_open":          f"silent {focal_word} establishing",
            "rising_tension":     f"{focal_word} under building pressure",
            "stakes_reveal":      f"the stakes of {focal_word}",
            "climax_montage":     f"{focal_word} at peak intensity",
            "title_drop":         f"title over {focal_word}",
            "tag_out":            f"final {focal_word} echo",
            "world_establishing": f"wide world view of {focal_word}",
            "core_loop_intro":    f"player engaging {focal_word}",
            "tension_arc":        f"{focal_word} pressure escalating",
            "climactic_encounter":f"{focal_word} confrontation",
            "afterglow":          f"{focal_word} aftermath",
            "opener":             f"{focal_word} theme statement",
            "groove":             f"{focal_word} sustained pattern",
            "anchor":             f"{focal_word} emotional anchor",
            "interlude":          f"{focal_word} breather passage",
            "closer":             f"{focal_word} resolution",
            "primary_hero":       f"hero composition of {focal_word}",
            "context_wide":       f"wide context for {focal_word}",
            "detail_macro":       f"detail close-up of {focal_word}",
            "bootstrap":          f"world seed for {focal_word}",
            "agent_phase":        f"agents acting on {focal_word}",
            "interaction_phase":  f"agent interactions in {focal_word}",
            "resolution":         f"{focal_word} state resolved",
        }
        return framings.get(beat, f"{focal_word}")

    def _mood_for(self, beat: str, tone: str) -> str:
        if tone:
            return tone
        mood_map = {
            "cold_open": "anticipatory", "rising_tension": "tense",
            "stakes_reveal": "weighty", "climax_montage": "explosive",
            "title_drop": "iconic", "tag_out": "lingering",
            "bootstrap": "neutral", "resolution": "settled",
        }
        return mood_map.get(beat, "neutral")

    def _emit_receipt(self, sb: Storyboard) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="composition:storyboard:planned",
                executor="StoryboardPlanner",
                duration_ms=0.0, verified=True, compute_sha256=False,
                evidence={
                    "storyboard_id": sb.storyboard_id,
                    "pipeline_kind": sb.pipeline_kind,
                    "scene_count":   len(sb.scenes),
                    "total_duration_s": sb.total_duration_s,
                },
            )
        except Exception:
            pass


_STOP = frozenset((
    "the a an and or but of for to with in on at by from as is are was were "
    "be been being have has had do does did will would should could can may "
    "this that these those it its make build create generate get please "
    "into onto upon under over"
).split())
