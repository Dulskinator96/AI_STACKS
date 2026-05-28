"""engine/adaptive_learning.py — BUILD-020 SECTION (organism architecture).

Adaptive learning layer. Observes cognitive cycles and tunes the
personality matrix + cortex defaults. Distinct from PersonalityModel:
PersonalityModel tracks per-intent counters; AdaptiveLearningLayer
tracks higher-order patterns (recurring intent sequences, time-of-day
preferences, refinement triggers).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger(__name__)


from omega.paths import telemetry_root
_LEARNING_PATH = telemetry_root() / "adaptive_learning.json"


@dataclass
class LearningState:
    cycle_count:         int = 0
    avg_score:           float = 0.0
    avg_refinement_rate: float = 0.0
    realm_distribution:  dict = field(default_factory=dict)
    sequential_patterns: dict = field(default_factory=dict)   # ("a","b") -> count
    last_updated:        float = 0.0


class AdaptiveLearningLayer:
    """Higher-order pattern absorption + default tuning."""

    def __init__(self, path: Path = _LEARNING_PATH):
        self._path = path
        self._lock = threading.RLock()
        self._state = self._load()
        self._recent_realms: deque = deque(maxlen=20)
        self._score_ema_alpha = 0.1
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.adaptive_learning", self)
        except Exception:
            pass

    def _load(self) -> LearningState:
        if not self._path.is_file():
            return LearningState()
        try:
            obj = json.loads(self._path.read_text(encoding="utf-8"))
            return LearningState(
                cycle_count=int(obj.get("cycle_count", 0)),
                avg_score=float(obj.get("avg_score", 0.0)),
                avg_refinement_rate=float(obj.get("avg_refinement_rate", 0.0)),
                realm_distribution=dict(obj.get("realm_distribution", {})),
                sequential_patterns=dict(obj.get("sequential_patterns", {})),
                last_updated=float(obj.get("last_updated", 0.0)),
            )
        except Exception as e:
            _log.warning("adaptive_learning load failed: %s", e)
            return LearningState()

    def _persist(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            payload = {
                "cycle_count":         self._state.cycle_count,
                "avg_score":           self._state.avg_score,
                "avg_refinement_rate": self._state.avg_refinement_rate,
                "realm_distribution":  self._state.realm_distribution,
                "sequential_patterns": self._state.sequential_patterns,
                "last_updated":        self._state.last_updated,
            }
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self._path)
        except Exception as e:
            _log.warning("adaptive_learning persist failed: %s", e)

    # ── Public API ────────────────────────────────────────────────────
    def absorb_cycle(self, cycle) -> None:
        """Observe a completed CognitiveCycle and update learning state."""
        with self._lock:
            self._state.cycle_count += 1
            self._state.last_updated = time.time()

            sess = getattr(cycle, "engine_session", None)
            if sess is not None and getattr(sess, "reflection", None) is not None:
                score = float(getattr(sess.reflection, "overall_score", 0.0) or 0.0)
                self._state.avg_score = (
                    (1 - self._score_ema_alpha) * self._state.avg_score +
                    self._score_ema_alpha * score
                )

            realm = getattr(cycle, "chosen_realm", "") or "unknown"
            self._state.realm_distribution[realm] = \
                self._state.realm_distribution.get(realm, 0) + 1

            # Sequential pattern: last realm → this realm
            if self._recent_realms:
                pair = f"{self._recent_realms[-1]}->{realm}"
                self._state.sequential_patterns[pair] = \
                    self._state.sequential_patterns.get(pair, 0) + 1
            self._recent_realms.append(realm)

            # Refinement detection — any followup mentioning "refine"
            followups = getattr(cycle, "reflection_followups", []) or []
            refined = any("refine" in f.lower() or "alternate" in f.lower()
                          for f in followups)
            target = 1.0 if refined else 0.0
            self._state.avg_refinement_rate = (
                (1 - self._score_ema_alpha) * self._state.avg_refinement_rate +
                self._score_ema_alpha * target
            )

            self._persist()
        self._emit_receipt()

    def adapted_default(self, key: str, fallback: Any = None) -> Any:
        """Query an adapted default. Currently supports:
          'preferred_realm' — the most-used realm
          'avg_score' — the running average score
          'refinement_likely' — True if avg_refinement_rate > 0.3
        """
        with self._lock:
            if key == "preferred_realm":
                rd = self._state.realm_distribution
                if not rd:
                    return fallback
                return max(rd.items(), key=lambda kv: kv[1])[0]
            if key == "avg_score":
                return self._state.avg_score
            if key == "refinement_likely":
                return self._state.avg_refinement_rate > 0.3
            if key == "top_sequence":
                sp = self._state.sequential_patterns
                if not sp:
                    return fallback
                return max(sp.items(), key=lambda kv: kv[1])[0]
        return fallback

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cycle_count":         self._state.cycle_count,
                "avg_score":           self._state.avg_score,
                "avg_refinement_rate": self._state.avg_refinement_rate,
                "realm_distribution":  dict(self._state.realm_distribution),
                "top_sequences":       _top(self._state.sequential_patterns, 5),
                "preferred_realm":     self.adapted_default("preferred_realm"),
                "refinement_likely":   self.adapted_default("refinement_likely"),
                "last_updated":        self._state.last_updated,
            }

    def _emit_receipt(self) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="adaptive_learning:absorb",
                executor="AdaptiveLearningLayer",
                duration_ms=0.0,
                verified=True,
                compute_sha256=False,
                evidence=self.snapshot(),
            )
        except Exception:
            pass


def _top(d: dict, n: int) -> list:
    if not d:
        return []
    return [k for k, _ in sorted(d.items(), key=lambda kv: -kv[1])[:n]]


_INSTANCE: Optional[AdaptiveLearningLayer] = None


def get_adaptive_learning() -> AdaptiveLearningLayer:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = AdaptiveLearningLayer()
    return _INSTANCE
