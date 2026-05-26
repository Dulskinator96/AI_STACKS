"""engine/calibration/latency_calibrator.py — per-backend latency profile."""
from __future__ import annotations
import json, logging, time
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)
_PATH = Path(__file__).resolve().parent.parent.parent / "telemetry" / "calibration_latency.json"


class LatencyCalibrator:
    def __init__(self):
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.calibration.latency", self)
        except Exception:
            pass

    def snapshot(self) -> dict:
        try:
            from engine.active_execution_substrate import get_execution_substrate
            aes = get_execution_substrate()
            snap = aes.snapshot()
        except Exception:
            snap = {"profiles": {}}
        snap["sampled_at"] = time.time()
        self._persist(snap)
        return snap

    def fastest_backend(self, realm: str) -> Optional[str]:
        try:
            from engine.backend_registry import get_backend_registry
            caps = get_backend_registry().for_realm(realm)
            caps = [c for c in caps if c.runtime_verified and c.latency_ms > 0]
            if not caps:
                return None
            return min(caps, key=lambda c: c.latency_ms).name
        except Exception:
            return None

    def _persist(self, snap: dict) -> None:
        try:
            _PATH.parent.mkdir(parents=True, exist_ok=True)
            _PATH.write_text(json.dumps(snap, indent=2, default=str),
                              encoding="utf-8")
        except Exception as e:
            _log.debug("latency snapshot persist failed: %s", e)


_INSTANCE: Optional[LatencyCalibrator] = None


def get_latency_calibrator() -> LatencyCalibrator:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = LatencyCalibrator()
    return _INSTANCE
