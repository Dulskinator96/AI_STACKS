"""
core/services.py — Service contract + central ServiceRegistry.

Stage 2 of the AI_STACK rebuild plan. Establishes unified lifecycle ownership
over the daemon-spawning modules (pulse, memory_manager, harvester) without
rewriting them. Each external module is wrapped by a thin Adapter that
implements the ``Service`` Protocol.

Design constraints (per Reality Enforcement Directive):
  * Adapters are PURE WRAPPERS — they do not duplicate logic from their target
    modules. They only translate the existing start/stop call shape into the
    Service contract.
  * Every method is idempotent — calling start() twice does not double-spawn;
    calling stop() twice does not error.
  * Every call is logged. No silent failures.
  * health() always returns a dict — never raises.
  * Registry shutdown is best-effort: a service that fails to stop is logged
    but does not block subsequent services from stopping.

Public API:
    Service                 - Protocol (duck-typed; not strictly enforced)
    AbstractService         - Concrete base providing default health()/is_running()
    ServiceRegistry         - holds {name: Service}, dispatches lifecycle ops
    get_registry()          - module singleton

    PulseService            - adapter for pulse.start/stop
    MemoryMaintenanceService- adapter for memory_manager.schedule_cleanup/stop_cleanup
    HarvesterService        - adapter for harvester.start_clipboard_harvester/stop_*

Usage:
    from core.services import (
        get_registry, PulseService, MemoryMaintenanceService, HarvesterService,
    )
    reg = get_registry()
    reg.register(PulseService())
    reg.register(MemoryMaintenanceService(interval_hours=24))
    reg.register(HarvesterService(interval_s=30.0))
    # ... app runs ...
    reg.stop_all()
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

_log = logging.getLogger("stratum.core.services")


# ═════════════════════════════════════════════════════════════════════════════
# Service contract
# ═════════════════════════════════════════════════════════════════════════════

class AbstractService:
    """Concrete base. Subclasses override ``_start_impl`` and ``_stop_impl``
    and may override ``_health_extra`` for service-specific telemetry.

    Why a class, not a Protocol: we need to share idempotent start/stop
    bookkeeping (running flag, start timestamp, lock) across all adapters.
    """

    name: str = "abstract"

    def __init__(self):
        self._running: bool = False
        self._started_at: float = 0.0
        self._lock = threading.Lock()
        self._last_error: Optional[str] = None

    # ── Public interface ────────────────────────────────────────────────────
    def start(self) -> bool:
        """Idempotent start. Returns True if running after the call."""
        with self._lock:
            if self._running:
                return True
            try:
                self._start_impl()
                self._running = True
                self._started_at = time.time()
                self._last_error = None
                _log.info("service started: %s", self.name)
                return True
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                _log.exception("service start failed: %s", self.name)
                return False

    def stop(self, timeout: float = 5.0) -> bool:
        """Idempotent stop. Returns True if stopped after the call."""
        with self._lock:
            if not self._running:
                return True
            try:
                self._stop_impl(timeout=timeout)
                self._running = False
                _log.info("service stopped: %s", self.name)
                return True
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                _log.exception("service stop failed: %s", self.name)
                # Best-effort: still mark not-running so subsequent stop() is no-op
                self._running = False
                return False

    def adopt(self) -> None:
        """Mark this service as already-running without invoking _start_impl.

        Used when the underlying module is already started elsewhere (e.g.,
        legacy app.py direct-start blocks) and we only want the registry to
        track it for stop_all() and health() purposes.
        """
        with self._lock:
            if not self._running:
                self._running = True
                self._started_at = time.time()
                _log.info("service adopted: %s (started externally)", self.name)

    def is_running(self) -> bool:
        return self._running

    def health(self) -> dict:
        """Always returns a dict. Never raises."""
        try:
            extra = self._health_extra()
        except Exception as exc:
            extra = {"_health_extra_error": str(exc)}
        return {
            "name":       self.name,
            "running":    self._running,
            "uptime_s":   (time.time() - self._started_at) if self._running else 0.0,
            "last_error": self._last_error,
            **(extra or {}),
        }

    # ── Subclass hooks ──────────────────────────────────────────────────────
    def _start_impl(self) -> None:
        raise NotImplementedError(f"{type(self).__name__}._start_impl")

    def _stop_impl(self, timeout: float) -> None:
        raise NotImplementedError(f"{type(self).__name__}._stop_impl")

    def _health_extra(self) -> dict:
        return {}


# ═════════════════════════════════════════════════════════════════════════════
# Registry
# ═════════════════════════════════════════════════════════════════════════════

class ServiceRegistry:
    """Holds the live set of services. Thread-safe.

    Idempotency: register() of the same-named service replaces the prior
    entry (after stopping it). stop_all() is safe to call multiple times.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._services: dict[str, AbstractService] = {}

    def register(self, service: AbstractService) -> None:
        with self._lock:
            existing = self._services.get(service.name)
            if existing is not None and existing is not service:
                _log.info("registry: replacing existing service '%s'", service.name)
                try:
                    existing.stop(timeout=2.0)
                except Exception:
                    _log.warning("swallowed exception")
            self._services[service.name] = service

    def unregister(self, name: str) -> bool:
        with self._lock:
            svc = self._services.pop(name, None)
        if svc is None:
            return False
        try: svc.stop(timeout=2.0)
        except Exception: _log.warning("swallowed exception")
        return True

    def get(self, name: str) -> Optional[AbstractService]:
        with self._lock:
            return self._services.get(name)

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._services.keys())

    def start_all(self) -> dict[str, bool]:
        """Start every registered service. Returns {name: started?}."""
        with self._lock:
            services = list(self._services.values())
        result: dict[str, bool] = {}
        for svc in services:
            result[svc.name] = svc.start()
        return result

    def stop_all(self, timeout: float = 5.0) -> dict[str, bool]:
        """Stop every registered service. Returns {name: stopped?}.

        Continues through failures — a single service failing to stop does
        not block subsequent shutdowns.
        """
        with self._lock:
            services = list(self._services.values())
        result: dict[str, bool] = {}
        for svc in services:
            result[svc.name] = svc.stop(timeout=timeout)
        return result

    def all_health(self) -> list[dict]:
        """Snapshot of every service's health() output."""
        with self._lock:
            services = list(self._services.values())
        return [svc.health() for svc in services]


# Module-level singleton
_registry = ServiceRegistry()


def get_registry() -> ServiceRegistry:
    return _registry


# ═════════════════════════════════════════════════════════════════════════════
# Adapters (Stage 2 cautious slice — 3 services)
# ═════════════════════════════════════════════════════════════════════════════

class PulseService(AbstractService):
    """Wraps ``pulse.start()`` / ``pulse.stop()``. Already symmetric in the
    underlying module — this adapter just plugs it into the registry."""

    name = "pulse"

    def __init__(self):
        super().__init__()
        self._engine: Any = None

    def _start_impl(self) -> None:
        import pulse as _pulse
        self._engine = _pulse.start()

    def _stop_impl(self, timeout: float) -> None:
        import pulse as _pulse
        _pulse.stop()
        self._engine = None

    def _health_extra(self) -> dict:
        engine = self._engine
        if engine is None:
            return {"engine": None}
        # PulseEngine has no formal health API; expose its truthiness.
        return {"engine_present": engine is not None}


class MemoryMaintenanceService(AbstractService):
    """Wraps ``memory_manager.schedule_cleanup()`` / ``stop_cleanup()``.

    The MaintenanceScheduler inside memory_manager is itself idempotent
    (introduced in the Stage 1 reconstruction earlier this session) — this
    adapter forwards both calls and surfaces tick_count as telemetry.
    """

    name = "memory_maintenance"

    def __init__(self, interval_hours: int = 24):
        super().__init__()
        self.interval_hours = interval_hours
        self._thread: Optional[threading.Thread] = None

    def _start_impl(self) -> None:
        import memory_manager as _mm
        self._thread = _mm.schedule_cleanup(interval_hours=self.interval_hours)

    def _stop_impl(self, timeout: float) -> None:
        import memory_manager as _mm
        _mm.stop_cleanup(timeout=timeout)
        self._thread = None

    def _health_extra(self) -> dict:
        try:
            import memory_manager as _mm
            sched = getattr(_mm, "_scheduler", None)
            return {
                "interval_hours": self.interval_hours,
                "tick_count":     getattr(sched, "_tick_count", 0) if sched else 0,
                "thread_alive":   bool(self._thread and self._thread.is_alive()),
            }
        except Exception as exc:
            return {"telemetry_error": str(exc)}


class HarvesterService(AbstractService):
    """Wraps ``harvester.start_clipboard_harvester()`` / ``stop_clipboard_harvester()``.

    The harvester polls the clipboard for capture-worthy content. Adapter
    forwards the interval setting and surfaces the harvester instance state
    as telemetry."""

    name = "harvester"

    def __init__(self, interval_s: float = 30.0):
        super().__init__()
        self.interval_s = interval_s
        self._instance: Any = None

    def _start_impl(self) -> None:
        import harvester as _h
        self._instance = _h.start_clipboard_harvester(interval_s=self.interval_s)

    def _stop_impl(self, timeout: float) -> None:
        import harvester as _h
        _h.stop_clipboard_harvester()
        self._instance = None

    def _health_extra(self) -> dict:
        inst = self._instance
        if inst is None:
            return {"instance": None, "interval_s": self.interval_s}
        return {
            "instance_present": True,
            "interval_s":       self.interval_s,
            "captured_count":   getattr(inst, "captured", None),
        }


__all__ = [
    "AbstractService", "ServiceRegistry", "get_registry",
    "PulseService", "MemoryMaintenanceService", "HarvesterService",
]
