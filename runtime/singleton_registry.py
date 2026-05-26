"""runtime/singleton_registry.py — RULE 1: RUNTIME IS IMMORTAL.

Holds one-shot references to the kernel substrate. Once a service is
registered, it is never reconstructed. Tab construction, navigation,
and re-init paths must reuse instances through `get(name)` — never
new-up their own.

Tracked services (BUILD-018 directive §RULE 1):
    EventBus · KernelExecutor · ToolRegistry · MemoryCore · ConstraintEngine
    · ConvergenceEngine · TelemetryRecorder · ReceiptPipeline
    · IntentOrchestrator · ObserverRegistry

Plus the existing HOTWIRE phase outputs:
    Constitution · AuthorityController · MaintenanceCortex
    · SystemStateManager · BootValidator

Each `register()` call emits a `runtime_singleton:<name>` receipt that
force-flushes through the truth pipeline (build-018 receipt durability).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)

_REGISTRY_LOCK = threading.RLock()


class RuntimeSingletonRegistry:
    """Thread-safe singleton registry. One process, one instance."""

    _instance: Optional["RuntimeSingletonRegistry"] = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_once()
            return cls._instance

    def _init_once(self) -> None:
        self._services: dict[str, Any] = {}
        self._factories: dict[str, Callable[[], Any]] = {}
        self._registered_at: dict[str, float] = {}
        self._reuse_count: dict[str, int] = {}

    def register(self, name: str, instance: Any) -> Any:
        """Register a fully-constructed service. Re-register is a no-op
        — returns the original instance so callers can safely do:

            cortex = registry.register("maintenance.cortex", build_cortex())
        """
        with _REGISTRY_LOCK:
            if name in self._services:
                self._reuse_count[name] = self._reuse_count.get(name, 0) + 1
                _log.debug("singleton.%s already registered — returning instance (reuse #%d)",
                           name, self._reuse_count[name])
                self._emit_receipt(name, "REUSED", self._reuse_count[name])
                return self._services[name]
            self._services[name] = instance
            self._registered_at[name] = time.time()
            self._reuse_count[name] = 0
            _log.info("singleton.%s registered", name)
            self._emit_receipt(name, "REGISTERED", 0)
            return instance

    def register_lazy(self, name: str, factory: Callable[[], Any]) -> None:
        """Register a factory that builds the service on first `get()`."""
        with _REGISTRY_LOCK:
            if name in self._services or name in self._factories:
                _log.debug("singleton.%s lazy-register skipped — already present", name)
                return
            self._factories[name] = factory
            _log.debug("singleton.%s lazy-registered", name)

    def get(self, name: str) -> Optional[Any]:
        """Return the registered service or None. If only a factory is
        present, build once now and cache."""
        with _REGISTRY_LOCK:
            if name in self._services:
                return self._services[name]
            factory = self._factories.get(name)
            if factory is None:
                return None
        # Build outside the lock to avoid factory deadlock on nested gets.
        try:
            instance = factory()
        except Exception as e:
            _log.warning("singleton.%s lazy build failed: %s", name, e)
            return None
        return self.register(name, instance)

    def has(self, name: str) -> bool:
        with _REGISTRY_LOCK:
            return name in self._services or name in self._factories

    def names(self) -> list[str]:
        with _REGISTRY_LOCK:
            return sorted(set(self._services) | set(self._factories))

    def snapshot(self) -> dict:
        """Return a JSON-safe summary for telemetry / view-model layer."""
        with _REGISTRY_LOCK:
            return {
                "registered": list(self._services.keys()),
                "lazy_pending": [n for n in self._factories if n not in self._services],
                "reuse_counts": dict(self._reuse_count),
                "registered_at": dict(self._registered_at),
            }

    def _emit_receipt(self, name: str, outcome: str, reuse_count: int) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task=f"runtime_singleton:{name}",
                executor="RuntimeSingletonRegistry",
                duration_ms=0.0,
                verified=(outcome in ("REGISTERED", "REUSED")),
                compute_sha256=False,
                evidence={
                    "outcome": outcome,
                    "reuse_count": reuse_count,
                    "registered_at": self._registered_at.get(name, 0.0),
                },
            )
        except Exception:
            pass


def get_registry() -> RuntimeSingletonRegistry:
    return RuntimeSingletonRegistry()
