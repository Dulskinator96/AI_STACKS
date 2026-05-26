"""engine/calibration/performance_calibrator.py — overall runtime perf."""
from __future__ import annotations
import json, logging, time
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)
_PATH = Path(__file__).resolve().parent.parent.parent / "telemetry" / "calibration_performance.json"


class PerformanceCalibrator:
    def __init__(self):
        self._t0 = time.time()
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.calibration.performance", self)
        except Exception:
            pass

    def snapshot(self) -> dict:
        snap = {"t": time.time(), "uptime_s": time.time() - self._t0}
        try:
            import psutil
            p = psutil.Process()
            snap["cpu_percent"]    = p.cpu_percent(interval=None)
            snap["rss_mb"]         = p.memory_info().rss / (1024 * 1024)
            snap["thread_count"]   = p.num_threads()
        except Exception:
            pass
        try:
            from engine.worker_router import get_worker_router
            snap["router"] = get_worker_router().stats()
        except Exception:
            pass
        try:
            from engine.artifact_lineage import get_artifact_lineage
            snap["artifacts"] = get_artifact_lineage().stats()
        except Exception:
            pass
        self._persist(snap)
        return snap

    def _persist(self, snap: dict) -> None:
        try:
            _PATH.parent.mkdir(parents=True, exist_ok=True)
            _PATH.write_text(json.dumps(snap, indent=2), encoding="utf-8")
        except Exception as e:
            _log.debug("performance snapshot persist failed: %s", e)


_INSTANCE: Optional[PerformanceCalibrator] = None


def get_performance_calibrator() -> PerformanceCalibrator:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = PerformanceCalibrator()
    return _INSTANCE
