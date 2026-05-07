"""
plugins — AI_MONITOR dormant plugin / extension architecture.

Conforms to ENGINEERING_CORE.md "PLUGIN / EXTENSION ARCHITECTURE":

  1. ALL external integrations are OPTIONAL
  2. PLUGINS EXIST IN DORMANT STATE — no runtime impact when inactive,
     no background execution, no dependency loading
  3. ACTIVATION IS EXPLICIT — user-triggered, config-validated
  4. ISOLATION — failures must remain contained
  5. EXAMPLES — Obsidian, external AI APIs, Unreal, DaVinci Resolve
  6. OFFLINE COMPATIBILITY — system works fully without any plugin

This module declares manifests only. It does NOT import or load any
plugin's third-party SDK. Real activation that would import a plugin's
runtime is the responsibility of an explicit, separately-enabled loader
that is NOT part of this module.

Public API:
    PluginManifest                     — frozen, declarative
    PluginRegistry                     — in-memory registry
    default_registry()                 — pre-populated with the 4 standard
                                         dormant manifests
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

_log = logging.getLogger(__name__)


class PluginState:
    """Lifecycle states per GAME_MODE.md "EMULATION LAYER" §STATE.

    DORMANT     — registered but not active (default after register())
    ACTIVATION  — transient: activate() is in flight (not externally observable)
    ACTIVE      — config validated, in-memory record present
    TERMINATION — transient: deactivate() is in flight (not externally observable)
    UNKNOWN     — name not registered

    ACTIVATION and TERMINATION are documented for completeness but cannot be
    observed by callers because activate()/deactivate() are atomic.
    """
    DORMANT     = "dormant"
    ACTIVATION  = "activation"
    ACTIVE      = "active"
    TERMINATION = "termination"
    UNKNOWN     = "unknown"


@dataclass(frozen=True)
class PluginManifest:
    """Declarative description of an external integration.

    A manifest is metadata only. It does NOT load any code.

    :param name: stable plugin identifier (lowercase, snake_case)
    :param description: one-line human-readable summary
    :param required_config: tuple of config-key names the user must supply
        at activation time (e.g. ``("vault_path",)``, ``("api_key",)``)
    :param version: semver string for the manifest itself
    """
    name:            str
    description:     str
    required_config: tuple[str, ...] = ()
    version:         str = "0.1.0"


class PluginRegistry:
    """In-memory registry of plugin manifests + activation state.

    Activation stores the user-supplied config dict in memory only — it is
    not written to disk and it does NOT cause the plugin's third-party SDK
    to be imported. Real loading is the job of a separately-enabled loader
    that is NOT part of this module.
    """

    def __init__(self) -> None:
        self._manifests: dict[str, PluginManifest] = {}
        self._active:    dict[str, dict[str, str]] = {}

    # ── manifest management ──────────────────────────────────────────────

    def register(self, manifest: PluginManifest) -> None:
        """Register a manifest. Re-registering the same name is rejected."""
        if manifest.name in self._manifests:
            raise ValueError(f"plugin already registered: {manifest.name!r}")
        self._manifests[manifest.name] = manifest

    def manifests(self) -> list[PluginManifest]:
        """Return all registered manifests in registration order."""
        return list(self._manifests.values())

    def get(self, name: str) -> PluginManifest | None:
        return self._manifests.get(name)

    # ── dormancy / activation ────────────────────────────────────────────

    def is_active(self, name: str) -> bool:
        """True only after a successful explicit activation."""
        return name in self._active

    def state(self, name: str) -> str:
        """Return a PluginState string for ``name``.

        Externally observable values: ``ACTIVE``, ``DORMANT``, ``UNKNOWN``.
        ACTIVATION / TERMINATION are transient and not returned by this
        method (activate/deactivate are atomic from the caller's view).
        """
        if name not in self._manifests:
            return PluginState.UNKNOWN
        if name in self._active:
            return PluginState.ACTIVE
        return PluginState.DORMANT

    def activate(self, name: str, config: dict[str, str]
                 ) -> tuple[bool, str]:
        """Explicit activation gate.

        Validates that every key in ``manifest.required_config`` is supplied
        in ``config``. Stores the config in memory on success. Returns
        ``(ok, reason)`` — never raises so that a failed activation can never
        destabilise the host system.
        """
        manifest = self._manifests.get(name)
        if manifest is None:
            return (False, f"unknown plugin: {name!r}")
        missing = [k for k in manifest.required_config if k not in config]
        if missing:
            return (False, f"missing required config: {missing}")
        self._active[name] = dict(config)
        _log.info("plugin activated: %s", name)
        return (True, "ok")

    def deactivate(self, name: str) -> bool:
        """Remove the in-memory activation record. Idempotent."""
        return self._active.pop(name, None) is not None

    def active_config(self, name: str) -> dict[str, str] | None:
        """Return a copy of the activation config, or None if dormant."""
        cfg = self._active.get(name)
        return dict(cfg) if cfg is not None else None


def default_registry() -> PluginRegistry:
    """Build the standard dormant registry — 4 manifests, none active.

    Mutating this returned registry does NOT affect any other caller's
    registry; each call returns a fresh, independent instance.
    """
    from plugins.manifest import STANDARD_MANIFESTS  # local import: no SDK
    reg = PluginRegistry()
    for m in STANDARD_MANIFESTS:
        reg.register(m)
    return reg


def list_standard_plugin_names() -> Iterable[str]:
    """Convenience: names declared by the standard manifest set."""
    from plugins.manifest import STANDARD_MANIFESTS
    return tuple(m.name for m in STANDARD_MANIFESTS)
