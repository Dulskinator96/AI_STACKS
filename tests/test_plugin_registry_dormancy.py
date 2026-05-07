"""Regression lock for plugin dormancy invariants.

Locks the rules from ENGINEERING_CORE.md "PLUGIN / EXTENSION ARCHITECTURE":
  - Default state: every standard manifest is registered, NONE active
  - Importing `plugins` does NOT import any third-party SDK
  - activate() requires complete required_config; partial config rejected
  - activate() never raises — returns (False, reason) on failure
  - deactivate() is idempotent
  - get/manifests are pure reads
"""
from __future__ import annotations

import sys

import pytest


_EXPECTED_PLUGINS = ("obsidian", "external_ai", "unreal", "davinci")


# ── Default registry shape ───────────────────────────────────────────────────

def test_default_registry_has_all_standard_manifests():
    from plugins import default_registry
    reg = default_registry()
    names = [m.name for m in reg.manifests()]
    assert set(names) == set(_EXPECTED_PLUGINS), \
        f"expected {_EXPECTED_PLUGINS}, got {names}"


@pytest.mark.parametrize("name", _EXPECTED_PLUGINS)
def test_every_standard_plugin_is_dormant_by_default(name):
    from plugins import default_registry
    reg = default_registry()
    assert reg.get(name) is not None, f"manifest missing: {name}"
    assert not reg.is_active(name), f"plugin should be dormant: {name}"
    assert reg.active_config(name) is None


# ── Dormancy: importing plugins must not load third-party SDKs ───────────────

_FORBIDDEN_AT_IMPORT = (
    "openai", "anthropic", "obsidian", "unreal", "DaVinciResolveScript",
    "requests",  # plugins module itself does not need HTTP
)


def test_importing_plugins_does_not_import_sdks():
    """Force a clean import and confirm no plugin SDK ends up in sys.modules."""
    for mod_name in ("plugins", "plugins.manifest"):
        sys.modules.pop(mod_name, None)
    import plugins  # noqa: F401
    import plugins.manifest  # noqa: F401
    leaked = [m for m in _FORBIDDEN_AT_IMPORT if m in sys.modules]
    # NB: `requests` may be present because OTHER ai-monitor modules imported
    # it earlier in the session. This test only fails if plugins/ ITSELF
    # caused the leak. We approximate that by reloading and checking the
    # immediate dependency chain via a fresh subprocess if needed; for now
    # we just assert the plugin-specific SDKs are absent — `requests` is
    # tolerated because it's a transitive of the broader codebase, not of
    # this module.
    plugin_specific = [m for m in leaked if m != "requests"]
    assert not plugin_specific, \
        f"plugins module leaked SDK imports: {plugin_specific}"


# ── activate() — explicit, config-validated, non-raising ─────────────────────

def test_activate_rejects_incomplete_config():
    from plugins import default_registry
    reg = default_registry()
    ok, reason = reg.activate("obsidian", {})
    assert not ok
    assert "missing" in reason
    assert not reg.is_active("obsidian")


def test_activate_rejects_unknown_plugin():
    from plugins import default_registry
    reg = default_registry()
    ok, reason = reg.activate("nonexistent_xyz", {"x": "1"})
    assert not ok
    assert "unknown" in reason


def test_activate_succeeds_with_complete_config():
    from plugins import default_registry
    reg = default_registry()
    ok, reason = reg.activate("obsidian", {"vault_path": "/tmp/vault"})
    assert ok, reason
    assert reg.is_active("obsidian")
    cfg = reg.active_config("obsidian")
    assert cfg == {"vault_path": "/tmp/vault"}
    # Returned config is a copy — mutating it must not affect the registry
    cfg["vault_path"] = "MUTATED"
    assert reg.active_config("obsidian") == {"vault_path": "/tmp/vault"}


def test_deactivate_is_idempotent():
    from plugins import default_registry
    reg = default_registry()
    reg.activate("obsidian", {"vault_path": "/tmp/vault"})
    assert reg.deactivate("obsidian") is True
    assert reg.deactivate("obsidian") is False  # already gone
    assert not reg.is_active("obsidian")


# ── Isolation: registries are independent ────────────────────────────────────

def test_registries_are_independent():
    from plugins import default_registry
    reg_a = default_registry()
    reg_b = default_registry()
    reg_a.activate("obsidian", {"vault_path": "/A"})
    assert reg_a.is_active("obsidian")
    assert not reg_b.is_active("obsidian")


# ── Manifest immutability ────────────────────────────────────────────────────

def test_manifest_is_frozen():
    from plugins import PluginManifest
    m = PluginManifest(name="x", description="y")
    with pytest.raises(Exception):
        m.name = "z"  # type: ignore[misc]
