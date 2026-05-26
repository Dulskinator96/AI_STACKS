"""runtime/ — BUILD-018 Runtime Separation Substrate.

Codifies the runtime-centric execution model:

  RUNTIME persists independently → UI attaches as detachable projections.

Module map:
    singleton_registry   — RuntimeSingletonRegistry (immortal services)
    service_locator      — RuntimeServiceLocator (capability resolution)
    view_model           — RuntimeStateSnapshot + WorkspaceStateBridge
                            + ObserverProjectionLayer
    workspace_contract   — WorkspaceCapabilityContract
    workspace_spawner    — DynamicWorkspaceSpawner
    deferred_loader      — DeferredWorkspaceLoader (worker-pool wrapper)

Architecture rules enforced here:
  R1 — Runtime is immortal (registry)
  R2 — Tabs are views only (service locator + view model)
  R4 — View-model separation (StateBridge + projection layer)
  R5 — Dynamic room spawning (spawner)
  R7 — Cross-tab decoupling (capability contracts)
  R8 — Receipt isolation (projection layer summarizes only)
"""
from __future__ import annotations

from runtime.singleton_registry import (
    RuntimeSingletonRegistry,
    get_registry,
)
from runtime.service_locator import (
    RuntimeServiceLocator,
    get_service_locator,
)
from runtime.view_model import (
    RuntimeStateSnapshot,
    WorkspaceStateBridge,
    ObserverProjectionLayer,
)
from runtime.workspace_contract import (
    WorkspaceCapabilityContract,
    CapabilityViolation,
)
from runtime.workspace_spawner import (
    DynamicWorkspaceSpawner,
    get_workspace_spawner,
    WorkspaceSession,
)
from runtime.deferred_loader import DeferredWorkspaceLoader

__all__ = [
    "RuntimeSingletonRegistry", "get_registry",
    "RuntimeServiceLocator", "get_service_locator",
    "RuntimeStateSnapshot", "WorkspaceStateBridge", "ObserverProjectionLayer",
    "WorkspaceCapabilityContract", "CapabilityViolation",
    "DynamicWorkspaceSpawner", "get_workspace_spawner", "WorkspaceSession",
    "DeferredWorkspaceLoader",
]
