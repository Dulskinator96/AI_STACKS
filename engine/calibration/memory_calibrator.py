"""engine/calibration/memory_calibrator.py — RSS + VRAM headroom."""
from __future__ import annotations
import json, logging, time
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)
_PATH = Path(__file__).resolve().parent.parent.parent / "telemetry" / "calibration_memory.json"


class MemoryCalibrator:
    def __init__(self):
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.calibration.memory", self)
        except Exception:
            pass

    def snapshot(self) -> dict:
        snap = {"t": time.time()}
        try:
            import psutil
            vm = psutil.virtual_memory()
            snap["ram_total_mb"]     = int(vm.total / (1024 * 1024))
            snap["ram_available_mb"] = int(vm.available / (1024 * 1024))
            snap["ram_percent"]      = vm.percent
            p = psutil.Process()
            snap["process_rss_mb"]   = int(p.memory_info().rss / (1024 * 1024))
        except Exception:
            pass
        try:
            from engine.production_tool_fabric import get_production_tool_fabric
            hw = get_production_tool_fabric().hardware()
            if hw is not None:
                snap["vram_total_mb"] = hw.vram_mb_total
                snap["vram_used_mb"]  = hw.vram_mb_used
                snap["gpu_name"]      = hw.gpu_name
        except Exception:
            pass
        self._persist(snap)
        return snap

    def _persist(self, snap: dict) -> None:
        try:
            _PATH.parent.mkdir(parents=True, exist_ok=True)
            _PATH.write_text(json.dumps(snap, indent=2), encoding="utf-8")
        except Exception as e:
            _log.debug("memory snapshot persist failed: %s", e)


_INSTANCE: Optional[MemoryCalibrator] = None


def get_memory_calibrator() -> MemoryCalibrator:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = MemoryCalibrator()
    return _INSTANCE
