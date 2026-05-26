"""runtime/service_locator.py — RULE 7: CROSS-TAB DECOUPLING.

Tabs request capabilities from the runtime instead of reaching into
sibling tabs. Replaces the prior `getattr(dashboard, '_maint_cortex', None)`
pattern with a contracted, capability-keyed lookup.

Capability names are flat strings keyed by what the consumer wants, not
by what producer happens to hold it today:

    "maintenance.cortex"          — MaintenanceCortex instance
    "maintenance.ui_state"        — UIStateObserver instance
    "kernel.constitution"         — Constitution singleton
    "kernel.event_bus"            — EventBus
    "kernel.authority"            — AuthorityController
    "kernel.dag"                  — RuntimeGraph (ExecutionDAG)
    "kernel.constraint_engine"    — ConstraintEngine
    "kernel.convergence_engine"   — ConvergenceEngine
    "kernel.intent_orchestrator"  — module-level callable orchestrate()
    "truth.receipt_engine"        — module reference
    "core.state_manager"          — SystemStateManager
    "core.bootstrap"              — SystemBootstrap singleton
    "memory.bridge"               — mempalace_bridge module
    "won.pipeline"                — pipeline module
    "intelligence.consciousness"  — ConsciousEnsembleOrchestrator
    "intelligence.ensemble"       — EnsembleOrchestrator
    "ui.dashboard"                — HistoryDashboard (the shell)

Any tab requesting a capability not yet registered receives None and is
expected to render a "service unavailable" state rather than crash.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from runtime.singleton_registry import get_registry

_log = logging.getLogger(__name__)


class RuntimeServiceLocator:
    """Thin façade over RuntimeSingletonRegistry — adds capability
    discovery + miss-tracking so we can surface decoupling violations."""

    def __init__(self):
        self._miss_counts: dict[str, int] = {}

    def resolve(self, capability: str) -> Optional[Any]:
        """Return the service backing `capability` or None."""
        reg = get_registry()
        svc = reg.get(capability)
        if svc is None:
            self._miss_counts[capability] = self._miss_counts.get(capability, 0) + 1
            if self._miss_counts[capability] == 1:
                _log.debug("service_locator miss: %s (unregistered)", capability)
        return svc

    def require(self, capability: str) -> Any:
        """Resolve or raise — for capabilities that must be present."""
        svc = self.resolve(capability)
        if svc is None:
            raise CapabilityNotAvailable(capability)
        return svc

    def announce(self, capability: str, instance: Any) -> Any:
        """Register a capability provider. Mirror of registry.register
        for tabs that DO produce a service (rare — maintenance cortex,
        chamber). Returns the canonical instance."""
        return get_registry().register(capability, instance)

    def miss_report(self) -> dict[str, int]:
        return dict(self._miss_counts)


class CapabilityNotAvailable(RuntimeError):
    """Raised by RuntimeServiceLocator.require() when the requested
    capability is not registered. Tabs should prefer resolve() and a
    graceful empty-state render — require() is for runtime-critical
    paths only (e.g., receipt engine reference)."""
    def __init__(self, capability: str):
        super().__init__(f"capability not available: {capability}")
        self.capability = capability


_LOCATOR_INSTANCE: Optional[RuntimeServiceLocator] = None


def get_service_locator() -> RuntimeServiceLocator:
    global _LOCATOR_INSTANCE
    if _LOCATOR_INSTANCE is None:
        _LOCATOR_INSTANCE = RuntimeServiceLocator()
    return _LOCATOR_INSTANCE
