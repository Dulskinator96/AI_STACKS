"""engine/personality_matrix.py — BUILD-020 SECTION 4 (evolution).

PersonalityMatrix extends PersonalityModel with deeper structures:
  · aesthetic_fingerprint — top-3 style/palette/emotion vector
  · emotional_preference_map — emotion ↦ amplitude
  · visual_tendencies — composition + lighting frequencies
  · soundtrack_tendencies — soundtrack_profile fingerprint
  · gameplay_interests — game-realm intents only
  · recurring_thematic_patterns — keyword n-grams (n=2,3)
  · ambition_distribution — histogram, not just running average

The matrix is a READ layer over PersonalityModel. It does not duplicate
the storage; it queries PersonalityModel's snapshot and computes
higher-order summaries on demand.
"""
from __future__ import annotations

import logging
import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional

_log = logging.getLogger(__name__)


@dataclass
class AestheticFingerprint:
    top_styles:    list = field(default_factory=list)
    top_palette:   list = field(default_factory=list)
    top_emotions:  list = field(default_factory=list)
    confidence:    float = 0.0


@dataclass
class MatrixSnapshot:
    fingerprint:                 AestheticFingerprint
    emotional_preference_map:    dict
    visual_tendencies:           dict
    soundtrack_tendencies:       dict
    gameplay_interests:          list
    recurring_thematic_patterns: list
    ambition_distribution:       dict
    interaction_count:           int
    summary_sentence:            str

    def to_dict(self) -> dict:
        return {
            "fingerprint": {
                "top_styles":   list(self.fingerprint.top_styles),
                "top_palette":  list(self.fingerprint.top_palette),
                "top_emotions": list(self.fingerprint.top_emotions),
                "confidence":   self.fingerprint.confidence,
            },
            "emotional_preference_map":    dict(self.emotional_preference_map),
            "visual_tendencies":           dict(self.visual_tendencies),
            "soundtrack_tendencies":       dict(self.soundtrack_tendencies),
            "gameplay_interests":          list(self.gameplay_interests),
            "recurring_thematic_patterns": list(self.recurring_thematic_patterns),
            "ambition_distribution":       dict(self.ambition_distribution),
            "interaction_count":           self.interaction_count,
            "summary_sentence":            self.summary_sentence,
        }


class PersonalityMatrix:
    """READ-ONLY layer over PersonalityModel — derived higher-order vectors."""

    def __init__(self):
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.personality_matrix", self)
        except Exception:
            pass

    def snapshot(self) -> MatrixSnapshot:
        """Build a complete matrix snapshot from PersonalityModel + history."""
        from engine.personality_model import get_personality
        pm = get_personality()
        base = pm.snapshot()

        # Aesthetic fingerprint
        styles = base.get("aesthetic", {}) or {}
        palette = base.get("color", {}) or {}
        emotions = base.get("emotion", {}) or {}
        top_styles  = _top(styles, 3)
        top_palette = _top(palette, 3)
        top_emos    = _top(emotions, 3)
        confidence  = min(1.0, base.get("interaction_count", 0) / 25.0)
        fingerprint = AestheticFingerprint(
            top_styles=top_styles, top_palette=top_palette,
            top_emotions=top_emos, confidence=confidence,
        )

        # Emotional preference map (normalize)
        total_em = sum(emotions.values()) or 1
        emap = {k: round(v / total_em, 3) for k, v in emotions.items()}

        # Visual / soundtrack tendencies — built from history JSONL
        history = self._load_history(pm)
        composition_counter: Counter = Counter()
        soundtrack_counter:  Counter = Counter()
        for entry in history:
            comp = entry.get("composition") or ""
            sp = entry.get("soundtrack") or ""
            if comp:
                composition_counter[comp] += 1
            if sp:
                soundtrack_counter[sp] += 1
        visual = dict(composition_counter.most_common(5))
        soundtrack = dict(soundtrack_counter.most_common(5))

        # Gameplay interests — game-realm intents
        gameplay = [
            entry.get("intent", "")[:80]
            for entry in history
            if entry.get("realm") in ("game", "GAME")
        ][:10]

        # Recurring thematic n-grams
        ngrams = self._extract_ngrams(history, n_low=2, n_high=3, top=10)

        # Ambition distribution (binned)
        amb_dist = self._ambition_distribution(history)

        # Summary sentence — composed from top fields
        summary = self._compose_summary(fingerprint, base)

        return MatrixSnapshot(
            fingerprint=fingerprint,
            emotional_preference_map=emap,
            visual_tendencies=visual,
            soundtrack_tendencies=soundtrack,
            gameplay_interests=gameplay,
            recurring_thematic_patterns=ngrams,
            ambition_distribution=amb_dist,
            interaction_count=base.get("interaction_count", 0),
            summary_sentence=summary,
        )

    # ── Helpers ────────────────────────────────────────────────────────
    def _load_history(self, pm) -> list:
        try:
            return list(getattr(pm, "_history", []) or [])
        except Exception:
            return []

    def _extract_ngrams(self, history: list, n_low: int = 2, n_high: int = 3,
                         top: int = 10) -> list:
        text_blocks = [(e.get("intent", "") or "").lower() for e in history]
        counter: Counter = Counter()
        for block in text_blocks:
            tokens = [t for t in
                      __import__("re").findall(r"[A-Za-z]{3,}", block)
                      if t not in _STOP]
            for n in range(n_low, n_high + 1):
                for i in range(len(tokens) - n + 1):
                    counter[" ".join(tokens[i:i + n])] += 1
        return [phrase for phrase, _ in counter.most_common(top)]

    def _ambition_distribution(self, history: list) -> dict:
        bins = {"0.0-0.3": 0, "0.3-0.6": 0, "0.6-0.85": 0, "0.85-1.0": 0}
        for e in history:
            amb = e.get("ambition")
            if not isinstance(amb, (int, float)):
                continue
            a = float(amb)
            if a < 0.3:
                bins["0.0-0.3"] += 1
            elif a < 0.6:
                bins["0.3-0.6"] += 1
            elif a < 0.85:
                bins["0.6-0.85"] += 1
            else:
                bins["0.85-1.0"] += 1
        return bins

    def _compose_summary(self, fp: AestheticFingerprint, base: dict) -> str:
        if fp.confidence < 0.05:
            return "Operator fingerprint not yet established — submit more intents to deepen."
        bits = []
        if fp.top_styles:
            bits.append(f"prefers {', '.join(fp.top_styles[:2])}")
        if fp.top_palette:
            bits.append(f"palette gravitates toward {', '.join(fp.top_palette[:2])}")
        if fp.top_emotions:
            bits.append(f"emotional anchor: {fp.top_emotions[0]}")
        amb = base.get("ambition_avg", 0.6)
        if amb > 0.8:
            bits.append("ambition is high")
        elif amb < 0.4:
            bits.append("ambition is restrained")
        return "Operator " + "; ".join(bits) + "."


_STOP = frozenset((
    "the a an and or but of for to with in on at by from as is are was were "
    "be been being have has had do does did will would should could can may "
    "this that these those it its make build create"
).split())


def _top(d: dict, n: int) -> list:
    if not d:
        return []
    return [k for k, _ in sorted(d.items(), key=lambda kv: -kv[1])[:n]]


_INSTANCE: Optional[PersonalityMatrix] = None


def get_personality_matrix() -> PersonalityMatrix:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = PersonalityMatrix()
    return _INSTANCE
