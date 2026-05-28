"""engine/preference_memory.py — BUILD-028 operator preference persistence.

Tracks accepted/rejected outputs with per-feature confidence + temporal decay.
Persists to telemetry/preference_memory.json.

NOT hardcoded personality. NOT static templates. Real observational
evidence accumulates over time. Stale preferences decay.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger(__name__)


from omega.paths import telemetry_root
_PATH = telemetry_root() / "preference_memory.json"

# Decay half-life in seconds — preferences halve over this window.
_HALF_LIFE_S = 30 * 86400.0   # 30 days


@dataclass
class PreferenceEntry:
    """One feature observation. Confidence = accumulated EMA over time."""
    feature:        str         # e.g. style, tone, palette_color, lighting
    value:          str         # e.g. cyberpunk, legendary, "#ff2d92", neon_rim
    accepted_count: int = 0
    rejected_count: int = 0
    confidence:     float = 0.0     # 0..1 EMA
    last_event_ts:  float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class PreferenceMemory:
    """JSON-backed preference store with decay."""

    def __init__(self):
        self._lock = threading.RLock()
        self._entries: dict[tuple, PreferenceEntry] = {}
        self._load()
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.preference_memory", self)
        except Exception:
            pass

    def _load(self) -> None:
        if not _PATH.is_file():
            return
        try:
            data = json.loads(_PATH.read_text(encoding="utf-8"))
            for raw in data.get("entries", []):
                key = (raw.get("feature", ""), raw.get("value", ""))
                self._entries[key] = PreferenceEntry(
                    feature=raw.get("feature", ""),
                    value=raw.get("value", ""),
                    accepted_count=int(raw.get("accepted_count", 0)),
                    rejected_count=int(raw.get("rejected_count", 0)),
                    confidence=float(raw.get("confidence", 0.0) or 0.0),
                    last_event_ts=float(raw.get("last_event_ts", 0.0) or 0.0),
                )
        except Exception as e:
            _log.warning("preference_memory load failed: %s", e)

    def _persist(self) -> None:
        try:
            _PATH.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "updated_at": time.time(),
                "half_life_s": _HALF_LIFE_S,
                "entry_count": len(self._entries),
                "entries":     [e.to_dict() for e in self._entries.values()],
            }
            _PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as e:
            _log.warning("preference_memory persist failed: %s", e)

    def _decayed(self, e: PreferenceEntry, now: float) -> float:
        """Confidence after temporal decay since last event."""
        if e.last_event_ts <= 0:
            return e.confidence
        elapsed = max(0.0, now - e.last_event_ts)
        decay = 0.5 ** (elapsed / _HALF_LIFE_S)
        return float(e.confidence * decay)

    # ── Public API ────────────────────────────────────────────────────
    def observe(self, feature: str, value: str, accepted: bool) -> None:
        """Record an observation. accepted=True if the operator's output
        was considered successful (CQI ≥ 0.75 or explicitly approved)."""
        now = time.time()
        key = (feature, value)
        with self._lock:
            e = self._entries.get(key)
            if e is None:
                e = PreferenceEntry(feature=feature, value=value)
                self._entries[key] = e
            # Decay first
            e.confidence = self._decayed(e, now)
            # Update counts + EMA (alpha=0.18)
            if accepted:
                e.accepted_count += 1
                target = 1.0
            else:
                e.rejected_count += 1
                target = 0.0
            e.confidence = (1 - 0.18) * e.confidence + 0.18 * target
            e.last_event_ts = now
            self._persist()

    def absorb_outcome(self, plan, cqi, worker_outcome, accepted: Optional[bool] = None) -> None:
        """Compose features from plan + cqi + outcome. accepted defaults
        to CQI ≥ 0.75."""
        if accepted is None:
            composite = float(getattr(cqi, "composite", 0.0) or 0.0) if cqi else 0.0
            accepted = composite >= 0.75
        # Extract features
        if plan is not None:
            aes = getattr(plan, "aesthetic", None)
            if aes is not None:
                if getattr(aes, "style", ""):
                    self.observe("style", aes.style, accepted)
                if getattr(aes, "emotional_anchor", ""):
                    self.observe("emotion", aes.emotional_anchor, accepted)
                for color in (getattr(aes, "palette", []) or [])[:4]:
                    self.observe("palette_color", color, accepted)
                if getattr(aes, "soundtrack", ""):
                    self.observe("soundtrack_profile", aes.soundtrack, accepted)
            cin = getattr(plan, "cinematic", None)
            if cin is not None:
                if getattr(cin, "pacing", ""):
                    self.observe("pacing", cin.pacing, accepted)
                if getattr(cin, "lighting_grammar", ""):
                    self.observe("lighting", cin.lighting_grammar, accepted)
                if getattr(cin, "composition_grammar", ""):
                    self.observe("composition", cin.composition_grammar, accepted)

    def top_preferences(self, feature: str, n: int = 3,
                          min_confidence: float = 0.4) -> list:
        """Return top-N values for a feature, sorted by decayed confidence."""
        now = time.time()
        with self._lock:
            candidates = [
                (e, self._decayed(e, now))
                for k, e in self._entries.items() if k[0] == feature
            ]
        candidates = [(e, c) for e, c in candidates if c >= min_confidence]
        candidates.sort(key=lambda t: -t[1])
        return [{"value": e.value, "confidence": round(c, 3),
                  "accepted": e.accepted_count, "rejected": e.rejected_count}
                for e, c in candidates[:n]]

    def snapshot(self) -> dict:
        now = time.time()
        with self._lock:
            features: dict[str, list] = defaultdict(list)
            stable = 0
            experimental = 0
            for e in self._entries.values():
                c = self._decayed(e, now)
                features[e.feature].append({
                    "value": e.value, "confidence": round(c, 3),
                    "accepted": e.accepted_count, "rejected": e.rejected_count,
                })
                if (e.accepted_count + e.rejected_count) >= 5:
                    stable += 1
                else:
                    experimental += 1
            for k in features:
                features[k].sort(key=lambda d: -d["confidence"])
        return {
            "entry_count": len(self._entries),
            "stable_count": stable,
            "experimental_count": experimental,
            "features": dict(features),
            "half_life_days": _HALF_LIFE_S / 86400.0,
        }


_INSTANCE: Optional[PreferenceMemory] = None


def get_preference_memory() -> PreferenceMemory:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = PreferenceMemory()
    return _INSTANCE
