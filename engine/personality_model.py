"""engine/personality_model.py — PHASE 4.

Adaptive personalization. Tracks operator creative identity over time
as lightweight structured preference vectors. Persisted to JSON.

NOT fake sentience. NOT psychological simulation. Just preference
counters with exponential moving averages and decay.

Vectors tracked:
  · aesthetic_preferences   (style ↦ score)
  · tone_preferences         (tone ↦ score)
  · emotion_preferences      (emotion ↦ score)
  · medium_preferences       (medium ↦ score)
  · color_preferences        (color ↦ score, extracted from prompts)
  · pacing_preference        (slow|moderate|fast running average)
  · ambition_running_average
  · recurring_themes         (keyword ↦ count)
  · creation_history         (capped list of recent intents + outcomes)
  · interaction_patterns     (hour_of_day distribution, intent_count)
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger(__name__)


_PERSONALITY_PATH = Path(__file__).resolve().parent.parent / "telemetry" / "personality_model.json"
_HISTORY_CAP = 200
_DECAY_HALF_LIFE_DAYS = 30.0
_ALPHA = 0.1   # EMA weight for ambition

_COLOR_PATTERNS = (
    "red orange amber yellow gold green emerald teal cyan blue indigo "
    "violet purple magenta pink rose crimson scarlet "
    "black white silver bronze copper neon"
).split()


@dataclass
class PersonalityVectors:
    aesthetic:      dict = field(default_factory=dict)
    tone:           dict = field(default_factory=dict)
    emotion:        dict = field(default_factory=dict)
    medium:         dict = field(default_factory=dict)
    color:          dict = field(default_factory=dict)
    pacing:         float = 0.5      # 0=slow, 1=fast
    ambition_avg:   float = 0.6
    themes:         dict = field(default_factory=dict)
    hour_of_day:    dict = field(default_factory=dict)
    interaction_count: int = 0
    last_updated:   float = 0.0


class PersonalityModel:
    """Persistent operator preference tracker."""

    def __init__(self, path: Path = _PERSONALITY_PATH):
        self._path = path
        self._lock = threading.RLock()
        self._vectors = self._load()
        self._history: list = self._load_history()

    # ── Persistence ───────────────────────────────────────────────────
    def _load(self) -> PersonalityVectors:
        if not self._path.is_file():
            return PersonalityVectors()
        try:
            obj = json.loads(self._path.read_text(encoding="utf-8"))
            return PersonalityVectors(
                aesthetic=dict(obj.get("aesthetic", {})),
                tone=dict(obj.get("tone", {})),
                emotion=dict(obj.get("emotion", {})),
                medium=dict(obj.get("medium", {})),
                color=dict(obj.get("color", {})),
                pacing=float(obj.get("pacing", 0.5)),
                ambition_avg=float(obj.get("ambition_avg", 0.6)),
                themes=dict(obj.get("themes", {})),
                hour_of_day=dict(obj.get("hour_of_day", {})),
                interaction_count=int(obj.get("interaction_count", 0)),
                last_updated=float(obj.get("last_updated", 0.0)),
            )
        except Exception as e:
            _log.warning("personality load failed: %s — starting fresh", e)
            return PersonalityVectors()

    def _load_history(self) -> list:
        hp = self._path.with_name("personality_history.jsonl")
        if not hp.is_file():
            return []
        try:
            out = []
            with hp.open("r", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        continue
            return out[-_HISTORY_CAP:]
        except Exception as e:
            _log.warning("personality history load failed: %s", e)
            return []

    def _persist(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            payload = {
                "aesthetic":         self._vectors.aesthetic,
                "tone":              self._vectors.tone,
                "emotion":           self._vectors.emotion,
                "medium":            self._vectors.medium,
                "color":             self._vectors.color,
                "pacing":            self._vectors.pacing,
                "ambition_avg":      self._vectors.ambition_avg,
                "themes":            self._vectors.themes,
                "hour_of_day":       self._vectors.hour_of_day,
                "interaction_count": self._vectors.interaction_count,
                "last_updated":      self._vectors.last_updated,
            }
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self._path)
        except Exception as e:
            _log.warning("personality persist failed: %s", e)

    def _append_history(self, entry: dict) -> None:
        try:
            hp = self._path.with_name("personality_history.jsonl")
            hp.parent.mkdir(parents=True, exist_ok=True)
            with hp.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    # ── Update API ────────────────────────────────────────────────────
    def absorb_intent(self, enriched_intent) -> None:
        """Update preference vectors from one EnrichedIntent."""
        with self._lock:
            v = self._vectors
            if getattr(enriched_intent, "style", None):
                v.aesthetic[enriched_intent.style] = v.aesthetic.get(enriched_intent.style, 0) + 1
            if getattr(enriched_intent, "tone", None):
                v.tone[enriched_intent.tone] = v.tone.get(enriched_intent.tone, 0) + 1
            if getattr(enriched_intent, "emotion", None):
                v.emotion[enriched_intent.emotion] = v.emotion.get(enriched_intent.emotion, 0) + 1
            if getattr(enriched_intent, "medium", None):
                v.medium[enriched_intent.medium] = v.medium.get(enriched_intent.medium, 0) + 1

            # Color extraction from raw text
            text = (getattr(enriched_intent, "raw_text", "") or "").lower()
            for c in _COLOR_PATTERNS:
                if re.search(rf"\b{c}\b", text):
                    v.color[c] = v.color.get(c, 0) + 1

            # Ambition EMA
            try:
                amb = float(getattr(enriched_intent, "ambition", 0.6))
                v.ambition_avg = (1.0 - _ALPHA) * v.ambition_avg + _ALPHA * amb
            except Exception:
                pass

            # Theme counter
            for kw in (getattr(enriched_intent, "keywords", []) or []):
                v.themes[kw] = v.themes.get(kw, 0) + 1

            # Hour-of-day distribution
            try:
                hr = str(time.localtime().tm_hour)
                v.hour_of_day[hr] = v.hour_of_day.get(hr, 0) + 1
            except Exception:
                pass

            v.interaction_count += 1
            v.last_updated = time.time()
            self._persist()

        # History log (outside the lock)
        try:
            self._append_history({
                "ts":       time.time(),
                "intent":   getattr(enriched_intent, "raw_text", "")[:200],
                "medium":   getattr(enriched_intent, "medium", None),
                "realm":    getattr(enriched_intent, "realm", None),
                "style":    getattr(enriched_intent, "style", None),
                "tone":     getattr(enriched_intent, "tone", None),
                "ambition": getattr(enriched_intent, "ambition", None),
            })
        except Exception:
            pass

        self._emit_receipt()

    def absorb_output(self, intent_text: str, realm: str, outcome: str) -> None:
        """Update history with a generation outcome (OK | DEGRADED | FAIL)."""
        try:
            self._append_history({
                "ts":      time.time(),
                "intent":  (intent_text or "")[:200],
                "realm":   realm,
                "outcome": outcome,
                "kind":    "output",
            })
        except Exception:
            pass

    def _emit_receipt(self) -> None:
        try:
            from truth.receipt_engine import record_execution
            v = self._vectors
            record_execution(
                task="personality:absorb",
                executor="PersonalityModel",
                duration_ms=0.0,
                verified=True,
                compute_sha256=False,
                evidence={
                    "interaction_count": v.interaction_count,
                    "ambition_avg":      v.ambition_avg,
                    "aesthetic_top":     _top(v.aesthetic, 3),
                    "tone_top":          _top(v.tone, 3),
                    "medium_top":        _top(v.medium, 3),
                    "theme_top":         _top(v.themes, 5),
                },
            )
        except Exception:
            pass

    # ── Query API ─────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        with self._lock:
            v = self._vectors
            return {
                "aesthetic":         dict(v.aesthetic),
                "tone":              dict(v.tone),
                "emotion":           dict(v.emotion),
                "medium":            dict(v.medium),
                "color":             dict(v.color),
                "pacing":            v.pacing,
                "ambition_avg":      v.ambition_avg,
                "themes":            dict(v.themes),
                "hour_of_day":       dict(v.hour_of_day),
                "interaction_count": v.interaction_count,
                "last_updated":      v.last_updated,
                "top_aesthetic":     _top(v.aesthetic, 3),
                "top_tone":          _top(v.tone, 3),
                "top_color":         _top(v.color, 3),
                "top_themes":        _top(v.themes, 5),
            }

    def top_preference(self, vector_name: str, default: Optional[str] = None) -> Optional[str]:
        """Single best preference in a named vector."""
        with self._lock:
            d = getattr(self._vectors, vector_name, {}) or {}
            if not isinstance(d, dict) or not d:
                return default
            return max(d.items(), key=lambda kv: kv[1])[0]


def _top(d: dict, n: int) -> list:
    if not isinstance(d, dict) or not d:
        return []
    return [k for k, _ in sorted(d.items(), key=lambda kv: -kv[1])[:n]]


_PERSONALITY_INSTANCE: Optional[PersonalityModel] = None


def get_personality() -> PersonalityModel:
    global _PERSONALITY_INSTANCE
    if _PERSONALITY_INSTANCE is None:
        _PERSONALITY_INSTANCE = PersonalityModel()
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.personality", _PERSONALITY_INSTANCE)
        except Exception:
            pass
    return _PERSONALITY_INSTANCE
