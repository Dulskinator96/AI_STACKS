"""Regression lock for sensory_engine.

Asserts the contract:
  - Default engine builds with no args, on a stock Python install
  - Graphics/audio outputs match the underlying simcore_render projectors
    (proves the wrap doesn't drift over time)
  - InputAdapter never raises on unknown / empty keys
  - EmotionBridge tolerates None, missing fields, non-numeric values
  - PluginBridge refuses dormant plugins, accepts active ones
  - Adapter swap rejects non-conforming candidates without raising
  - SensoryEngine.frame() is pure (does not mutate world / event)
"""
from __future__ import annotations

import pytest


# ── Construction ─────────────────────────────────────────────────────────────

def test_default_engine_builds():
    from sensory_engine import default_engine, SensoryEngine
    eng = default_engine()
    assert isinstance(eng, SensoryEngine)


def test_default_engine_emits_frame_for_demo_world():
    from sensory_engine import default_engine
    from simcore import SimCore
    sc = SimCore()
    sc.bootstrap()
    frame = default_engine().frame(sc.current_world())
    assert isinstance(frame.visual, str) and frame.visual
    assert frame.audio_cue == "silence"  # no last_event passed
    assert isinstance(frame.ambient, str)
    assert frame.modulation == {}
    assert frame.plugin_status == {}


# ── Graphics + audio match simcore_render ────────────────────────────────────

def test_default_graphics_matches_visual_projector():
    from sensory_engine import DefaultGraphicsAdapter
    from simcore import SimCore
    from simcore_render import VisualProjector
    sc = SimCore()
    sc.bootstrap()
    world = sc.current_world()
    assert DefaultGraphicsAdapter().render(world) == VisualProjector().project(world)


def test_default_audio_matches_audio_projector():
    from sensory_engine import DefaultAudioAdapter
    from simcore import Event
    from simcore_render import AudioProjector
    ev = Event.propose(actor="player", action="move",
                       payload={"direction": "north"})
    assert DefaultAudioAdapter().cue(ev) == AudioProjector().cue_for(ev)


# ── Input adapter ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad_key", ["", "  ", "ZZ", "ctrl+x", "\n"])
def test_input_adapter_rejects_unknown_keys(bad_key):
    from sensory_engine import DefaultInputAdapter
    assert DefaultInputAdapter().key_to_action(bad_key) is None


@pytest.mark.parametrize("key,direction", [
    ("w", "north"), ("a", "west"), ("s", "south"), ("d", "east"),
    ("e", "up"),    ("q", "down"),
])
def test_input_adapter_maps_movement(key, direction):
    from sensory_engine import DefaultInputAdapter
    action = DefaultInputAdapter().key_to_action(key)
    assert action == {
        "actor": "player", "action": "move",
        "payload": {"direction": direction},
    }


def test_input_adapter_handles_non_string():
    from sensory_engine import DefaultInputAdapter
    assert DefaultInputAdapter().key_to_action(None) is None  # type: ignore[arg-type]
    assert DefaultInputAdapter().key_to_action(42) is None    # type: ignore[arg-type]


# ── Emotion bridge ───────────────────────────────────────────────────────────

def test_emotion_bridge_handles_none():
    from sensory_engine import DefaultEmotionBridge
    assert DefaultEmotionBridge().modulate(None) == {}


def test_emotion_bridge_reads_dict():
    from sensory_engine import DefaultEmotionBridge
    out = DefaultEmotionBridge().modulate({"valence": 0.5, "arousal": 0.8})
    assert out["audio_tone"] == 0.5
    assert out["ui_intensity"] == 0.8


def test_emotion_bridge_clamps_values():
    from sensory_engine import DefaultEmotionBridge
    out = DefaultEmotionBridge().modulate({"valence": 99.0, "arousal": -5.0})
    assert out["audio_tone"] == 1.0
    assert out["ui_intensity"] == 0.0


def test_emotion_bridge_skips_non_numeric():
    from sensory_engine import DefaultEmotionBridge
    out = DefaultEmotionBridge().modulate({"valence": "garbage", "arousal": None})
    assert out == {}


# ── Plugin bridge ────────────────────────────────────────────────────────────

def test_plugin_bridge_refuses_dormant_plugins():
    from plugins import default_registry
    from sensory_engine import DefaultPluginBridge
    reg = default_registry()
    assert DefaultPluginBridge().connect("obsidian", reg) is False


def test_plugin_bridge_accepts_active_plugins():
    from plugins import default_registry
    from sensory_engine import DefaultPluginBridge
    reg = default_registry()
    ok, _ = reg.activate("obsidian", {"vault_path": "/tmp/v"})
    assert ok
    assert DefaultPluginBridge().connect("obsidian", reg) is True


def test_plugin_bridge_safe_on_garbage_registry():
    from sensory_engine import DefaultPluginBridge
    assert DefaultPluginBridge().connect("anything", None) is False
    assert DefaultPluginBridge().connect("anything", object()) is False


# ── Adapter swap gates ───────────────────────────────────────────────────────

def test_adapter_swap_rejects_nonconforming():
    from sensory_engine import default_engine
    eng = default_engine()
    ok, reason = eng.set_graphics(object())
    assert not ok
    assert "GraphicsAdapter" in reason


def test_adapter_swap_accepts_conforming():
    from sensory_engine import default_engine, DefaultGraphicsAdapter
    eng = default_engine()
    new_adapter = DefaultGraphicsAdapter()
    ok, _ = eng.set_graphics(new_adapter)
    assert ok
    assert eng.graphics is new_adapter


# ── Purity: frame() must not mutate inputs ───────────────────────────────────

def test_frame_does_not_mutate_world():
    import json
    from sensory_engine import default_engine
    from simcore import SimCore
    sc = SimCore()
    sc.bootstrap()
    world = sc.current_world()
    before = world.to_canonical_json()
    default_engine().frame(world)
    after = world.to_canonical_json()
    assert before == after, "SensoryEngine.frame() mutated WorldState"
    assert json.loads(before) == json.loads(after)


# ── Plugin checks roll into the frame ────────────────────────────────────────

def test_frame_includes_plugin_status_when_requested():
    from plugins import default_registry
    from sensory_engine import default_engine
    from simcore import SimCore
    sc = SimCore()
    sc.bootstrap()
    reg = default_registry()
    reg.activate("obsidian", {"vault_path": "/tmp/v"})
    frame = default_engine().frame(
        sc.current_world(),
        plugins_to_check=("obsidian", "unreal"),
        plugin_registry=reg,
    )
    assert frame.plugin_status == {"obsidian": True, "unreal": False}
