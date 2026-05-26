"""engine/production_tool_fabric.py — BUILD-021 SECTION 10.

ProductionToolFabric extends ToolFabric with GPU/VRAM detection,
performance benchmarking, and per-tool capability scoring. Used by
ProductionCore to pick backends + by CognitiveCore to factor capability
into arbitration confidence.

GPU detection paths:
  · nvidia-smi (CLI) — for NVIDIA cards, parses VRAM total/used
  · pynvml (Python) — if installed, more reliable
  · torch.cuda — if installed, last resort

For non-NVIDIA / no-GPU machines, returns CPU-only capability score.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class HardwareCapabilities:
    gpu_present:        bool
    gpu_vendor:         str          # "nvidia" | "amd" | "intel" | "none"
    gpu_name:           str
    vram_mb_total:      int
    vram_mb_used:       int
    cuda_available:     bool
    cpu_count:          int
    ram_mb_total:       int
    ram_mb_available:   int
    ts:                 float


@dataclass
class CapabilityScore:
    """Per-tool score 0..1. Factors readiness + hardware fit."""
    tool_name:      str
    score:          float
    factors:        dict = field(default_factory=dict)


class ProductionToolFabric:
    """Hardware-aware tool capability scorer. Reads ToolFabric for raw
    status, augments with hardware-fit scoring."""

    def __init__(self):
        self._hardware: Optional[HardwareCapabilities] = None
        self._lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.production_tool_fabric", self)
        except Exception:
            pass
        # Detect hardware async on init
        try:
            from runtime.deferred_loader import DeferredWorkspaceLoader
            DeferredWorkspaceLoader.run(self._refresh_hardware, on_done=None,
                                         name="ptf_hardware_probe")
        except Exception:
            threading.Thread(target=self._refresh_hardware,
                              daemon=True, name="ptf_hardware_probe").start()

    # ── Hardware detection ────────────────────────────────────────────
    def _refresh_hardware(self) -> None:
        with self._refresh_lock:
            self._hardware = self._detect_hardware()

    def _detect_hardware(self) -> HardwareCapabilities:
        gpu_present = False
        gpu_vendor = "none"
        gpu_name = ""
        vram_total = 0
        vram_used = 0
        cuda_available = False

        # nvidia-smi
        smi = shutil.which("nvidia-smi")
        if smi:
            try:
                p = subprocess.run(
                    [smi, "--query-gpu=name,memory.total,memory.used",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, timeout=4,
                )
                if p.returncode == 0:
                    first = p.stdout.decode(errors="ignore").strip().splitlines()[0]
                    parts = [x.strip() for x in first.split(",")]
                    if len(parts) >= 3:
                        gpu_present = True
                        gpu_vendor = "nvidia"
                        gpu_name = parts[0]
                        try: vram_total = int(parts[1])
                        except Exception: pass
                        try: vram_used = int(parts[2])
                        except Exception: pass
            except Exception as e:
                _log.debug("nvidia-smi probe failed: %s", e)

        # torch.cuda
        if not gpu_present:
            try:
                import torch   # type: ignore
                if torch.cuda.is_available():
                    gpu_present = True
                    cuda_available = True
                    gpu_vendor = "nvidia"
                    gpu_name = torch.cuda.get_device_name(0)
                    # VRAM total from torch
                    props = torch.cuda.get_device_properties(0)
                    vram_total = int(props.total_memory / (1024 * 1024))
            except Exception:
                pass
        else:
            try:
                import torch   # type: ignore
                cuda_available = bool(torch.cuda.is_available())
            except Exception:
                pass

        # CPU + RAM via psutil
        cpu_count = 0
        ram_total = ram_avail = 0
        try:
            import psutil
            cpu_count = psutil.cpu_count(logical=True) or 0
            vm = psutil.virtual_memory()
            ram_total = int(vm.total / (1024 * 1024))
            ram_avail = int(vm.available / (1024 * 1024))
        except Exception:
            pass

        return HardwareCapabilities(
            gpu_present=gpu_present, gpu_vendor=gpu_vendor,
            gpu_name=gpu_name, vram_mb_total=vram_total,
            vram_mb_used=vram_used, cuda_available=cuda_available,
            cpu_count=cpu_count, ram_mb_total=ram_total,
            ram_mb_available=ram_avail, ts=time.time(),
        )

    def hardware(self) -> Optional[HardwareCapabilities]:
        with self._lock:
            return self._hardware

    def refresh(self) -> None:
        try:
            from runtime.deferred_loader import DeferredWorkspaceLoader
            DeferredWorkspaceLoader.run(self._refresh_hardware, on_done=None,
                                         name="ptf_hardware_refresh")
        except Exception:
            self._refresh_hardware()

    # ── Capability scoring ────────────────────────────────────────────
    def score(self, tool_name: str) -> CapabilityScore:
        """Returns a 0..1 score for a tool given current readiness +
        hardware fit. Used by ProductionCore to pick best backend."""
        factors: dict[str, Any] = {}
        # Pull base status from ToolFabric
        status = "UNAVAILABLE"
        try:
            from runtime.singleton_registry import get_registry
            tf = get_registry().get("engine.tool_fabric")
            if tf is not None:
                status = tf.status(tool_name)
        except Exception:
            pass
        factors["status"] = status

        if status == "READY":
            base = 1.0
        elif status == "DEGRADED":
            base = 0.55
        elif status == "LIMITED":
            base = 0.40
        else:
            base = 0.0

        # Hardware fit
        hw = self.hardware()
        if hw is not None:
            factors["gpu_present"] = hw.gpu_present
            factors["vram_mb"] = hw.vram_mb_total
            # Image / video tools strongly benefit from VRAM
            if tool_name in ("comfyui", "automatic1111", "diffusers", "imageforge"):
                if hw.vram_mb_total >= 12_000:
                    base = min(1.0, base + 0.0)
                elif hw.vram_mb_total >= 6_000:
                    factors["vram_fit"] = "minimum"
                    base *= 0.85
                else:
                    factors["vram_fit"] = "insufficient"
                    base *= 0.50
            if tool_name in ("audiocraft", "bark"):
                if hw.vram_mb_total >= 8_000:
                    pass
                elif hw.vram_mb_total >= 4_000:
                    base *= 0.85
                else:
                    factors["vram_fit"] = "cpu_only"
                    base *= 0.55
            if tool_name in ("unreal", "blender") and hw.gpu_present:
                base = min(1.0, base + 0.05)

        return CapabilityScore(tool_name=tool_name,
                                score=round(base, 3),
                                factors=factors)

    def best_for_realm(self, realm: str) -> list:
        """Return tools sorted by capability score, descending."""
        try:
            from runtime.singleton_registry import get_registry
            tf = get_registry().get("engine.tool_fabric")
            tools = tf.tools_for_realm(realm) if tf else []
        except Exception:
            tools = []
        scored = [self.score(t) for t in tools]
        scored.sort(key=lambda s: -s.score)
        return scored

    def report(self) -> dict:
        hw = self.hardware()
        return {
            "hardware":  (hw.__dict__ if hw else None),
            "ready_now":  False if hw is None else True,
        }


_INSTANCE: Optional[ProductionToolFabric] = None


def get_production_tool_fabric() -> ProductionToolFabric:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ProductionToolFabric()
    return _INSTANCE
