"""Regression lock for the Game Mode contract.

Locks the four operational affordances introduced for GAME_MODE.md:

  1. GAME_MODE.md exists as the authoritative artifact
  2. config.GAME_MODE_PROMPT loads it
  3. Frame contract: SensoryFrame conforms to the Frame Protocol;
     metadata defaults to source=SIMCORE / priority=0 / timestamp=float
  4. ControlledLoop is plugin-lifecycle-scoped and refuses dormant plugins
  5. PluginRegistry exposes the lifecycle state machine

Pure-import test. No Ollama, no network, no subprocesses.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest


_PREAMBLE = "# GAME_MODE"


# ── Source-of-truth file ─────────────────────────────────────────────────────

def test_game_mode_md_exists_and_nonempty():
    import config
    path: Path = config.GAME_MODE_PATH
    assert path.exists(), f"GAME_MODE.md missing at {path}"
    text = path.read_text(encoding="utf-8")
    assert text.strip(), "GAME_MODE.md is empty"
    assert text.startswith(_PREAMBLE)


def test_config_game_mode_prompt_loads():
    import config
    assert isinstance(config.GAME_MODE_PROMPT, str)
    assert config.GAME_MODE_PROMPT.startswith(_PREAMBLE)


def test_game_mode_not_auto_injected_into_engineering_core_sites():
    """Game Mode is opt-in; ENGINEERING_CORE-injected sites must NOT carry it."""
    import proposal_engine, conv_programming
    assert _PREAMBLE not in proposal_engine._SYSTEM_PROMPT
    assert _PREAMBLE not in conv_programming.CODEFORGE_SYSTEM


# ── Frame contract ───────────────────────────────────────────────────────────

def test_frame_protocol_has_required_attrs():
    """Frame Protocol must declare the contract's three fields."""
    from sensory_engine import Frame
    # Protocol fields with type-only declarations live in __annotations__.
    declared = set(Frame.__annotations__.keys())
    assert {"visual_data", "audio_data", "metadata"} <= declared, \
        f"Frame Protocol must declare visual_data/audio_data/metadata; got {declared}"


def test_sensory_frame_satisfies_frame_protocol():
    from sensory_engine import default_engine, Frame
    from simcore import SimCore
    sc = SimCore()
    sc.bootstrap()
    frame = default_engine().frame(sc.current_world())
    assert isinstance(frame, Frame), \
        "SensoryFrame must structurally satisfy Frame Protocol"


def test_sensory_frame_metadata_defaults():
    from sensory_engine import FrameSource, default_engine
    from simcore import SimCore
    sc = SimCore()
    sc.bootstrap()
    frame = default_engine().frame(sc.current_world())
    md = frame.metadata
    assert md["source"] == FrameSource.SIMCORE
    assert md["priority"] == 0
    assert isinstance(md["timestamp"], float)
    assert md["timestamp"] > 0


def test_sensory_frame_visual_data_aliases_visual():
    from sensory_engine import default_engine
    from simcore import SimCore
    sc = SimCore()
    sc.bootstrap()
    frame = default_engine().frame(sc.current_world())
    assert frame.visual_data == frame.visual
    assert frame.audio_data == frame.audio_cue


def test_frame_metadata_source_flips_when_plugin_active():
    """When any plugin reports active, metadata.source becomes PLUGIN."""
    from plugins import default_registry
    from sensory_engine import FrameSource, default_engine
    from simcore import SimCore
    sc = SimCore()
    sc.bootstrap()
    reg = default_registry()
    reg.activate("obsidian", {"vault_path": "/tmp/v"})
    frame = default_engine().frame(
        sc.current_world(),
        plugins_to_check=("obsidian",),
        plugin_registry=reg,
    )
    assert frame.metadata["source"] == FrameSource.PLUGIN


# ── Controlled Loop ──────────────────────────────────────────────────────────

def test_controlled_loop_refuses_dormant_plugin():
    from plugins import default_registry
    from sensory_engine import ControlledLoop
    reg = default_registry()
    with pytest.raises(RuntimeError, match="not ACTIVE"):
        with ControlledLoop("obsidian", reg):
            pytest.fail("ControlledLoop must not enter on dormant plugin")


def test_controlled_loop_runs_while_plugin_active():
    from plugins import default_registry
    from sensory_engine import ControlledLoop
    reg = default_registry()
    reg.activate("obsidian", {"vault_path": "/tmp/v"})
    with ControlledLoop("obsidian", reg, hz=120) as loop:
        assert loop.running
        assert loop.tick_interval() == pytest.approx(1.0 / 120)


def test_controlled_loop_stops_when_plugin_deactivates():
    """Mid-loop deactivation must flip running → False without raising."""
    from plugins import default_registry
    from sensory_engine import ControlledLoop
    reg = default_registry()
    reg.activate("obsidian", {"vault_path": "/tmp/v"})
    iters = 0
    with ControlledLoop("obsidian", reg) as loop:
        while loop.running:
            iters += 1
            if iters == 1:
                reg.deactivate("obsidian")
            if iters > 10:
                pytest.fail("ControlledLoop did not stop after deactivation")
    assert iters == 1


def test_controlled_loop_running_false_outside_context():
    from plugins import default_registry
    from sensory_engine import ControlledLoop
    reg = default_registry()
    reg.activate("obsidian", {"vault_path": "/tmp/v"})
    loop = ControlledLoop("obsidian", reg)
    assert not loop.running  # not entered yet
    with loop:
        assert loop.running
    assert not loop.running  # exited


def test_controlled_loop_safe_on_garbage_registry():
    from sensory_engine import ControlledLoop
    with pytest.raises(RuntimeError):
        with ControlledLoop("anything", object()):
            pass


# ── Plugin lifecycle state machine ───────────────────────────────────────────

def test_plugin_state_unknown_for_unregistered():
    from plugins import PluginState, default_registry
    reg = default_registry()
    assert reg.state("nonexistent") == PluginState.UNKNOWN


def test_plugin_state_dormant_after_register():
    from plugins import PluginState, default_registry
    reg = default_registry()
    assert reg.state("obsidian") == PluginState.DORMANT


def test_plugin_state_active_after_activate():
    from plugins import PluginState, default_registry
    reg = default_registry()
    reg.activate("obsidian", {"vault_path": "/tmp/v"})
    assert reg.state("obsidian") == PluginState.ACTIVE


def test_plugin_state_dormant_after_deactivate():
    from plugins import PluginState, default_registry
    reg = default_registry()
    reg.activate("obsidian", {"vault_path": "/tmp/v"})
    reg.deactivate("obsidian")
    assert reg.state("obsidian") == PluginState.DORMANT


# ── Idle performance: importing sensory_engine + plugins is fast ─────────────

def test_idle_import_is_fast():
    """Per GAME_MODE.md PERFORMANCE GUARANTEE: idle has zero heavy modules."""
    import importlib
    import sys
    for mod in ("sensory_engine", "plugins", "plugins.manifest"):
        sys.modules.pop(mod, None)
    t0 = time.perf_counter()
    importlib.import_module("sensory_engine")
    importlib.import_module("plugins")
    elapsed = time.perf_counter() - t0
    # Loose bound — generous enough to absorb cold-import variance.
    assert elapsed < 1.0, f"idle import took {elapsed:.3f}s; should be < 1.0s"
