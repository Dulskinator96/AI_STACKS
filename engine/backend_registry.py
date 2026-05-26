"""engine/backend_registry.py — BUILD-026 unified backend abstraction.

Every backend (ComfyUI, A1111, FFmpeg, Blender, Godot, Ollama, LMStudio,
Bark, Audiocraft, DaVinci, Unreal, internal modules) is represented as
a BackendCapability with verified flags + measured latency + stability.

NO direct backend calls outside this registry. Workers/probes/audits
all consult `get_backend_registry().capability(name)` for truth.

The registry composes the existing ToolFabric (presence detection) and
ActiveExecutionSubstrate (subprocess invocation). The new value here is
the unified BackendCapability dataclass — a single shape every consumer
can read.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

_log = logging.getLogger(__name__)


@dataclass
class BackendCapability:
    name:                 str
    realms:               list                  # supported realms
    executable_verified:  bool = False          # CLI/path exists OR module importable
    runtime_verified:     bool = False          # actually invocable
    output_verified:      bool = False          # produced a real artifact recently
    latency_ms:           float = 0.0           # avg from ActiveExecutionSubstrate
    stability_score:      float = 0.0           # 0..1; updated on each invocation
    last_probed_at:       float = 0.0
    last_invoked_at:      float = 0.0
    remediation:          str = ""
    detail:               str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# Canonical map: backend_name → supported realms
_BACKEND_REALMS = {
    "comfyui":          ["image"],
    "automatic1111":    ["image"],
    "diffusers":        ["image"],
    "imageforge":       ["image"],
    "ffmpeg":           ["video"],
    "davinci_resolve":  ["video"],
    "blender":          ["game", "image"],
    "godot":            ["game"],
    "unreal":           ["game"],
    "ollama":           ["cast", "code"],
    "lm_studio":        ["cast", "code"],
    "bark":             ["audio"],
    "audiocraft":       ["audio"],
    "pyttsx3":          ["audio"],
    "procedural_audio": ["audio"],
    "simcore":          ["simulation", "game"],
    "conv_programming": ["code"],
    "pyramid_ensemble": ["cast"],
    "git":              ["code"],
    "procedural_simulation": ["simulation"],
}


class BackendRegistry:
    """Unified backend abstraction. Single source of truth."""

    def __init__(self):
        self._capabilities: dict[str, BackendCapability] = {}
        self._lock = threading.RLock()
        # Pre-seed with the canonical list
        for name, realms in _BACKEND_REALMS.items():
            self._capabilities[name] = BackendCapability(
                name=name, realms=list(realms),
            )
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.backend_registry", self)
        except Exception:
            pass

    # ── Public API ────────────────────────────────────────────────────
    def capability(self, name: str) -> Optional[BackendCapability]:
        with self._lock:
            return self._capabilities.get(name)

    def all_capabilities(self) -> list:
        with self._lock:
            return list(self._capabilities.values())

    def for_realm(self, realm: str) -> list:
        realm = (realm or "").lower()
        with self._lock:
            return [c for c in self._capabilities.values()
                    if realm in c.realms]

    def refresh_from_substrate(self) -> None:
        """Pull verified flags + latency from ToolFabric + ActiveExecutionSubstrate."""
        # ToolFabric supplies executable_verified
        tf = None
        try:
            from runtime.singleton_registry import get_registry
            tf = get_registry().get("engine.tool_fabric")
        except Exception:
            pass
        # ActiveExecutionSubstrate supplies latency + last_invoked_at
        aes = None
        try:
            from engine.active_execution_substrate import get_execution_substrate
            aes = get_execution_substrate()
        except Exception:
            pass

        now = time.time()
        with self._lock:
            for name, cap in self._capabilities.items():
                if tf is not None:
                    status = tf.status(name)
                    cap.executable_verified = status in ("READY", "DEGRADED")
                    detail_entry = tf.detail(name)
                    if detail_entry is not None:
                        cap.detail = detail_entry.detail or ""
                        cap.remediation = detail_entry.remediation or ""
                if aes is not None:
                    prof = aes.profile(name)
                    if prof.get("tracked"):
                        cap.latency_ms = float(prof.get("avg_duration_ms", 0.0) or 0.0)
                        cap.runtime_verified = (prof.get("last_error") == "")
                cap.last_probed_at = now
        self._emit_receipt()

    def record_invocation(self, name: str, success: bool,
                            duration_ms: float = 0.0) -> None:
        """Update stability + last_invoked_at on each real backend call."""
        with self._lock:
            cap = self._capabilities.get(name)
            if cap is None:
                return
            cap.last_invoked_at = time.time()
            cap.latency_ms = (cap.latency_ms * 0.7 + duration_ms * 0.3) if cap.latency_ms else duration_ms
            # EMA on stability
            target = 1.0 if success else 0.0
            cap.stability_score = (cap.stability_score * 0.85 + target * 0.15)
            if success:
                cap.runtime_verified = True

    def record_output_verified(self, name: str) -> None:
        """Called when a backend produced a validated artifact."""
        with self._lock:
            cap = self._capabilities.get(name)
            if cap is not None:
                cap.output_verified = True

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "total":             len(self._capabilities),
                "executable_count":  sum(1 for c in self._capabilities.values()
                                          if c.executable_verified),
                "runtime_count":     sum(1 for c in self._capabilities.values()
                                          if c.runtime_verified),
                "output_count":      sum(1 for c in self._capabilities.values()
                                          if c.output_verified),
                "capabilities":      {n: c.to_dict()
                                       for n, c in self._capabilities.items()},
            }

    def _emit_receipt(self) -> None:
        try:
            from truth.receipt_engine import record_execution
            snap = self.snapshot()
            record_execution(
                task="backend_registry:refresh",
                executor="BackendRegistry",
                duration_ms=0.0, verified=True, compute_sha256=False,
                evidence={
                    "total":             snap["total"],
                    "executable_count":  snap["executable_count"],
                    "runtime_count":     snap["runtime_count"],
                    "output_count":      snap["output_count"],
                },
            )
        except Exception:
            pass


_INSTANCE: Optional[BackendRegistry] = None


def get_backend_registry() -> BackendRegistry:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = BackendRegistry()
    return _INSTANCE
