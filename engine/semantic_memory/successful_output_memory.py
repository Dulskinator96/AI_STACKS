"""engine/semantic_memory/successful_output_memory.py — remember what worked."""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)
_PATH = Path(__file__).resolve().parent.parent.parent / "telemetry" / "successful_outputs.jsonl"


_CAP = 200


class SuccessfulOutputMemory:
    """JSONL-backed memory of outputs that scored well (CQI >= 0.75)."""

    def __init__(self):
        self._lock = threading.RLock()
        self._recent: deque = deque(maxlen=_CAP)
        self._rejected_count = 0
        self._load()
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.successful_output_memory", self)
        except Exception:
            pass

    def _load(self) -> None:
        if not _PATH.is_file():
            return
        try:
            with _PATH.open("r", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        self._recent.append(json.loads(line))
                    except Exception:
                        continue
        except Exception as e:
            _log.warning("successful_output load failed: %s", e)

    def record(self, cqi, plan, worker_outcome) -> bool:
        """Record if the CQI composite meets the threshold. Returns True
        if stored."""
        composite = float(getattr(cqi, "composite", 0.0) or 0.0)
        if composite < 0.75:
            with self._lock:
                self._rejected_count += 1
            return False
        entry = {
            "ts":             time.time(),
            "cqi_composite":  composite,
            "atmosphere":     getattr(cqi, "atmosphere", 0.0),
            "emotional_impact": getattr(cqi, "emotional_impact", 0.0),
            "cinematic_intensity": getattr(cqi, "cinematic_intensity", 0.0),
            "visual_harmony":  getattr(cqi, "visual_harmony", 0.0),
            "memorability":    getattr(cqi, "memorability", 0.0),
            "plan_id":         getattr(plan, "plan_id", ""),
            "pipeline_kind":   getattr(plan, "pipeline_kind", ""),
            "raw_intent":      (getattr(plan, "raw_intent", "") or "")[:200],
            "plan_sha":        getattr(plan, "plan_sha", ""),
            "realm":           getattr(worker_outcome, "realm", ""),
            "worker_score":    getattr(worker_outcome, "overall_validation_score", 0.0),
            "backend":         getattr(worker_outcome, "backend", ""),
        }
        with self._lock:
            self._recent.append(entry)
            try:
                _PATH.parent.mkdir(parents=True, exist_ok=True)
                with _PATH.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry) + "\n")
            except Exception as e:
                _log.warning("successful_output persist failed: %s", e)
        return True

    def recent(self, n: int = 20) -> list:
        with self._lock:
            return list(self._recent)[-n:]

    def best(self, n: int = 5) -> list:
        with self._lock:
            ranked = sorted(self._recent, key=lambda e: -e.get("cqi_composite", 0.0))
        return ranked[:n]

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "recorded":  len(self._recent),
                "rejected":  self._rejected_count,
                "best_score": (max(e.get("cqi_composite", 0.0) for e in self._recent)
                                if self._recent else 0.0),
                "avg_score": (sum(e.get("cqi_composite", 0.0) for e in self._recent)
                                 / len(self._recent) if self._recent else 0.0),
            }


_INSTANCE: Optional[SuccessfulOutputMemory] = None


def get_successful_output_memory() -> SuccessfulOutputMemory:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = SuccessfulOutputMemory()
    return _INSTANCE
