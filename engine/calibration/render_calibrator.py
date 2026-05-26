"""engine/calibration/render_calibrator.py — UI render pacing observer.

Tracks frame-pacing approximations via QTimer callbacks. The UI
reports tick deltas; the calibrator computes p50 / p95 / max + jitter.
"""
from __future__ import annotations
import json, logging, time
from collections import deque
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)
_PATH = Path(__file__).resolve().parent.parent.parent / "telemetry" / "calibration_render.json"


class RenderCalibrator:
    def __init__(self):
        self._deltas = deque(maxlen=600)
        self._last_t = None
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.calibration.render", self)
        except Exception:
            pass

    def record_tick(self) -> None:
        """UI calls this from its main QTimer (cheap, sub-microsecond)."""
        now = time.perf_counter()
        if self._last_t is not None:
            self._deltas.append((now - self._last_t) * 1000.0)
        self._last_t = now

    def snapshot(self) -> dict:
        deltas = list(self._deltas)
        snap: dict = {"t": time.time(), "samples": len(deltas)}
        if deltas:
            sorted_d = sorted(deltas)
            snap["p50_ms"] = sorted_d[len(sorted_d) // 2]
            snap["p95_ms"] = sorted_d[int(len(sorted_d) * 0.95)]
            snap["max_ms"] = max(deltas)
            snap["avg_ms"] = sum(deltas) / len(deltas)
        self._persist(snap)
        return snap

    def _persist(self, snap: dict) -> None:
        try:
            _PATH.parent.mkdir(parents=True, exist_ok=True)
            _PATH.write_text(json.dumps(snap, indent=2), encoding="utf-8")
        except Exception as e:
            _log.debug("render snapshot persist failed: %s", e)


_INSTANCE: Optional[RenderCalibrator] = None


def get_render_calibrator() -> RenderCalibrator:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = RenderCalibrator()
    return _INSTANCE
