"""engine/calibration/artifact_consistency.py — per-backend output stability.

Tracks whether a given backend produces consistently-validated outputs.
A backend is considered consistent if its rolling success rate across
recent invocations is above a threshold (default 0.7).
"""
from __future__ import annotations
import json, logging, time
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)
_PATH = Path(__file__).resolve().parent.parent.parent / "telemetry" / "calibration_consistency.json"


class ArtifactConsistency:
    def __init__(self):
        self._outcomes: dict = defaultdict(lambda: deque(maxlen=20))
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.calibration.consistency", self)
        except Exception:
            pass

    def record_outcome(self, backend: str, valid: bool) -> None:
        self._outcomes[backend].append(1 if valid else 0)

    def consistency_score(self, backend: str) -> Optional[float]:
        outs = self._outcomes.get(backend)
        if not outs:
            return None
        return sum(outs) / len(outs)

    def snapshot(self) -> dict:
        snap: dict = {"t": time.time(), "backends": {}}
        for b, outs in self._outcomes.items():
            if not outs:
                continue
            snap["backends"][b] = {
                "samples":  len(outs),
                "success":  sum(outs),
                "score":    sum(outs) / len(outs),
            }
        self._persist(snap)
        return snap

    def _persist(self, snap: dict) -> None:
        try:
            _PATH.parent.mkdir(parents=True, exist_ok=True)
            _PATH.write_text(json.dumps(snap, indent=2), encoding="utf-8")
        except Exception as e:
            _log.debug("consistency snapshot persist failed: %s", e)


_INSTANCE: Optional[ArtifactConsistency] = None


def get_artifact_consistency() -> ArtifactConsistency:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ArtifactConsistency()
    return _INSTANCE
