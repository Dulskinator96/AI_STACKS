"""
sensory_engine.py — AI_MONITOR Sensory Layer.

Pipeline position (sits ABOVE simcore_render, BELOW the UI):

    simcore (truth)
        ↓
    simcore_render (debug projections — ASCII + cue slugs + text)
        ↓
    sensory_engine (THIS — adapter slots for graphics / audio / input /
                    emotion / plugin bridge; default impls delegate to
                    simcore_render so behaviour is unchanged offline)
        ↓
    UI (app.py)

Design rule (per ENGINEERING_CORE.md):
    - Adapters are PROTOCOLS. Default impls are offline-capable, depend only
      on the existing simcore_render and (optionally) perceptual_engine.
    - Real graphics / audio / emulator backends are PLUGINS. They activate
      explicitly via plugins.PluginRegistry. This module never imports a
      plugin SDK at import time.
    - SensoryEngine is a pure read of (WorldState, Event). It NEVER mutates
      simulation state. It cannot bypass simcore.

Public API:
    GraphicsAdapter, AudioAdapter, InputAdapter, EmotionBridge, PluginBridge
        — runtime_checkable Protocols
    DefaultGraphicsAdapter, DefaultAudioAdapter, DefaultInputAdapter,
    DefaultEmotionBridge, DefaultPluginBridge
        — offline-capable defaults
    SensoryFrame
        — bundle of all five outputs for one (world, event) pair
    SensoryEngine
        — top-level aggregator with adapter-swap gates
    default_engine() -> SensoryEngine
        — pre-wired with all five default adapters

This module is Model-layer per CLAUDE.md §5: NO PyQt6 imports.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from simcore import Event, WorldState
from simcore_render import AudioProjector, VisualProjector

_log = logging.getLogger(__name__)


# ── Frame contract (per GAME_MODE.md "FRAME CONTRACT (MANDATORY)") ───────────

class FrameSource:
    """Origin tag for a Frame. Used in metadata.source per GAME_MODE.md."""
    SIMCORE  = "simcore"
    PLUGIN   = "plugin"
    EMULATOR = "emulator"


@runtime_checkable
class Frame(Protocol):
    """Unified output contract. UI consumes Frame objects only — no direct
    rendering bypass allowed. SensoryFrame satisfies this structurally."""
    visual_data: Any   # str | bytes
    audio_data:  Any   # str | bytes | None
    metadata:    dict[str, Any]


def _default_metadata() -> dict[str, Any]:
    return {"source": FrameSource.SIMCORE,
            "timestamp": time.time(),
            "priority": 0}


# ── Adapter Protocols ────────────────────────────────────────────────────────

@runtime_checkable
class GraphicsAdapter(Protocol):
    """Project a WorldState to a visual representation.

    Returns ``str`` for textual / ASCII modes, ``bytes`` for future
    framebuffer-style adapters. Callers must accept both.
    """

    def render(self, world: WorldState) -> str | bytes: ...


@runtime_checkable
class AudioAdapter(Protocol):
    """Map events and ambient state to audio cues.

    Today the default returns slug strings; future plugin adapters may play
    sound. Either way the contract is the same: pure function of inputs.
    """

    def cue(self, event: Event) -> str: ...
    def ambient(self, world: WorldState) -> str: ...


@runtime_checkable
class InputAdapter(Protocol):
    """Translate user input keys into engine action dicts.

    Returns ``None`` for unrecognised keys; never raises.
    """

    def key_to_action(self, key: str) -> Optional[dict[str, Any]]: ...


@runtime_checkable
class EmotionBridge(Protocol):
    """Translate perceptual / cognitive state to output modulation.

    Returns a flat ``dict[str, float]`` of modulation channels. Empty dict
    is the safe default (no modulation). Never mutates its inputs.
    """

    def modulate(self, percept_or_state: Any) -> dict[str, float]: ...


@runtime_checkable
class PluginBridge(Protocol):
    """Gate plugin-backed adapters behind explicit activation."""

    def connect(self, name: str, registry: Any) -> bool: ...


@runtime_checkable
class HapticAdapter(Protocol):
    """Emit haptic pulses. ``pulse`` is fire-and-forget, never raises."""

    def pulse(self, intensity: float, duration_ms: int) -> None: ...


# ── Default Adapters ─────────────────────────────────────────────────────────

class DefaultGraphicsAdapter:
    """ASCII projection — wraps simcore_render.VisualProjector unchanged."""

    def __init__(self) -> None:
        self._proj = VisualProjector()

    def render(self, world: WorldState) -> str:
        return self._proj.project(world)


class DefaultAudioAdapter:
    """Cue-slug audio — wraps simcore_render.AudioProjector unchanged."""

    def __init__(self) -> None:
        self._proj = AudioProjector()

    def cue(self, event: Event) -> str:
        return self._proj.cue_for(event)

    def ambient(self, world: WorldState) -> str:
        return self._proj.ambient_for(world)


class DefaultInputAdapter:
    """Static keyboard → action map.

    Designed for the simcore demo world. Unknown keys return ``None``.
    """

    _KEY_TO_DIRECTION: dict[str, str] = {
        "w": "north", "s": "south", "a": "west",  "d": "east",
        "e": "up",    "q": "down",
    }

    def key_to_action(self, key: str) -> Optional[dict[str, Any]]:
        if not isinstance(key, str) or not key:
            return None
        k = key.strip().lower()
        if k in self._KEY_TO_DIRECTION:
            return {
                "actor":   "player",
                "action":  "move",
                "payload": {"direction": self._KEY_TO_DIRECTION[k]},
            }
        if k == "t":
            return {"actor": "player", "action": "take"}
        if k == "p":
            return {"actor": "player", "action": "drop"}
        if k == "l":
            return {"actor": "player", "action": "light"}
        if k == "u":
            return {"actor": "player", "action": "unlock"}
        return None


class DefaultEmotionBridge:
    """Optional perceptual_engine bridge.

    Per ENGINEERING_CORE.md SAFETY §3 (no assumed dependencies), we look
    up perceptual_engine via ``getattr`` on a soft import; if absent we
    return an empty modulation dict.
    """

    def __init__(self) -> None:
        self._engine_getter = None
        try:
            from perceptual_engine import get_engine  # type: ignore[attr-defined]
            self._engine_getter = get_engine
        except Exception as exc:  # ImportError or any init failure
            _log.debug("perceptual_engine unavailable for EmotionBridge: %s", exc)

    def modulate(self, percept_or_state: Any) -> dict[str, float]:
        if percept_or_state is None:
            return {}
        valence = self._read_float(percept_or_state, "valence")
        arousal = self._read_float(percept_or_state, "arousal")
        if valence is None and arousal is None:
            return {}
        out: dict[str, float] = {}
        if valence is not None:
            out["audio_tone"] = max(-1.0, min(1.0, valence))
        if arousal is not None:
            out["ui_intensity"] = max(0.0, min(1.0, arousal))
        return out

    @staticmethod
    def _read_float(obj: Any, attr: str) -> Optional[float]:
        try:
            v = getattr(obj, attr, None)
            if v is None and isinstance(obj, dict):
                v = obj.get(attr)
            if v is None:
                return None
            return float(v)
        except (TypeError, ValueError):
            return None


class DefaultPluginBridge:
    """Refuse any not-yet-active plugin; succeed only on active plugins.

    The bridge does NOT load the plugin's SDK. It only confirms that the
    plugin is registered AND activated in the supplied registry.
    """

    def connect(self, name: str, registry: Any) -> bool:
        is_active = getattr(registry, "is_active", None)
        if not callable(is_active):
            return False
        try:
            return bool(is_active(name))
        except Exception as exc:
            _log.warning("PluginBridge.connect(%s) failed: %s", name, exc)
            return False


class DefaultHapticAdapter:
    """No-op haptics. Real backends arrive as plugins.

    Logs at debug level so a developer can see the intended pulse without
    any real device. ``pulse`` never raises, never sleeps.
    """

    def pulse(self, intensity: float, duration_ms: int) -> None:
        try:
            i = max(0.0, min(1.0, float(intensity)))
            d = max(0, int(duration_ms))
        except (TypeError, ValueError):
            return
        _log.debug("haptic pulse: intensity=%.2f duration_ms=%d", i, d)


# ── Frame + Engine ──────────────────────────────────────────────────────────

@dataclass
class SensoryFrame:
    """One cycle of sensory output — pure projection of (world, last_event).

    Conforms to the Frame Protocol via the ``visual_data`` / ``audio_data``
    properties below, so any consumer typed against Frame accepts a
    SensoryFrame without conversion (per GAME_MODE.md FRAME CONTRACT).
    """
    visual:     str | bytes = ""
    audio_cue:  str = ""
    ambient:    str = ""
    modulation: dict[str, float] = field(default_factory=dict)
    plugin_status: dict[str, bool] = field(default_factory=dict)
    metadata:   dict[str, Any] = field(default_factory=_default_metadata)

    @property
    def visual_data(self) -> str | bytes:
        return self.visual

    @property
    def audio_data(self) -> str:
        return self.audio_cue


class SensoryEngine:
    """Top-level aggregator. Holds five adapter slots; pure read of state.

    Adapter swap is gated: a candidate must satisfy its Protocol via
    ``isinstance(candidate, ProtocolType)`` (runtime_checkable) before being
    accepted. Failed swaps return ``(False, reason)`` — never raise.
    """

    def __init__(
        self,
        graphics: Optional[GraphicsAdapter] = None,
        audio:    Optional[AudioAdapter]    = None,
        input_:   Optional[InputAdapter]    = None,
        emotion:  Optional[EmotionBridge]   = None,
        plugin:   Optional[PluginBridge]    = None,
        haptic:   Optional[HapticAdapter]   = None,
    ) -> None:
        self.graphics: GraphicsAdapter = graphics or DefaultGraphicsAdapter()
        self.audio:    AudioAdapter    = audio    or DefaultAudioAdapter()
        self.input:    InputAdapter    = input_   or DefaultInputAdapter()
        self.emotion:  EmotionBridge   = emotion  or DefaultEmotionBridge()
        self.plugin:   PluginBridge    = plugin   or DefaultPluginBridge()
        self.haptic:   HapticAdapter   = haptic   or DefaultHapticAdapter()

    # ── adapter swap gates ──────────────────────────────────────────────

    def set_graphics(self, adapter: Any) -> tuple[bool, str]:
        return self._swap("graphics", adapter, GraphicsAdapter)

    def set_audio(self, adapter: Any) -> tuple[bool, str]:
        return self._swap("audio", adapter, AudioAdapter)

    def set_input(self, adapter: Any) -> tuple[bool, str]:
        return self._swap("input", adapter, InputAdapter)

    def set_emotion(self, adapter: Any) -> tuple[bool, str]:
        return self._swap("emotion", adapter, EmotionBridge)

    def set_plugin(self, adapter: Any) -> tuple[bool, str]:
        return self._swap("plugin", adapter, PluginBridge)

    def set_haptic(self, adapter: Any) -> tuple[bool, str]:
        return self._swap("haptic", adapter, HapticAdapter)

    def _swap(self, slot: str, candidate: Any, proto: type) -> tuple[bool, str]:
        if not isinstance(candidate, proto):
            return (False, f"{slot} adapter does not satisfy {proto.__name__}")
        setattr(self, slot, candidate)
        _log.info("sensory adapter swapped: %s → %s", slot,
                  type(candidate).__name__)
        return (True, "ok")

    # ── frame production ────────────────────────────────────────────────

    def frame(
        self,
        world:           WorldState,
        last_event:      Optional[Event] = None,
        percept_or_state: Any = None,
        plugins_to_check: tuple[str, ...] = (),
        plugin_registry:  Any = None,
    ) -> SensoryFrame:
        """One sensory frame. Pure read of inputs."""
        visual    = self.graphics.render(world)
        audio_cue = (self.audio.cue(last_event) if last_event is not None
                     else "silence")
        ambient   = self.audio.ambient(world)
        modulation = self.emotion.modulate(percept_or_state)
        plugin_status: dict[str, bool] = {}
        if plugin_registry is not None:
            for name in plugins_to_check:
                plugin_status[name] = self.plugin.connect(name, plugin_registry)
        # Source defaults to SIMCORE; emulator/plugin-driven frames will
        # override metadata["source"] when they construct a SensoryFrame.
        any_active = any(plugin_status.values()) if plugin_status else False
        source = FrameSource.PLUGIN if any_active else FrameSource.SIMCORE
        return SensoryFrame(
            visual=visual,
            audio_cue=audio_cue,
            ambient=ambient,
            modulation=modulation,
            plugin_status=plugin_status,
            metadata={
                "source":    source,
                "timestamp": time.time(),
                "priority":  0,
            },
        )


def default_engine() -> SensoryEngine:
    """Construct a fully-default SensoryEngine (offline-capable)."""
    return SensoryEngine()


# ── Controlled Loop (per GAME_MODE.md "REAL-TIME EXECUTION MODEL") ───────────

class ControlledLoop:
    """Plugin-lifecycle-scoped tick clock.

    Per GAME_MODE.md:
        - default behavior is EVENT-DRIVEN (no loops)
        - a CONTROLLED LOOP exists ONLY while a specific plugin is active
        - automatically terminates when the plugin stops
        - MUST NOT exist globally

    Design: this class spawns NO thread. It is a sync-pull primitive — the
    consumer drives ticks (e.g. inside a Qt event loop, an asyncio task, or
    a foreground subprocess wait). ``running`` reflects the live activation
    state of the bound plugin, so deactivation mid-iteration ends the loop
    cleanly without an exception.

    Usage:
        with ControlledLoop("dolphin", registry, hz=60) as loop:
            while loop.running:
                frame = engine.frame(...)
                ...
                time.sleep(loop.tick_interval())
    """

    def __init__(self, name: str, registry: Any, hz: int = 60) -> None:
        self.name = name
        self.registry = registry
        self.hz = max(1, int(hz))
        self._entered = False

    def __enter__(self) -> "ControlledLoop":
        is_active = getattr(self.registry, "is_active", None)
        if not callable(is_active) or not is_active(self.name):
            raise RuntimeError(
                f"ControlledLoop refuses to start: plugin {self.name!r} "
                f"is not ACTIVE in the supplied registry"
            )
        self._entered = True
        _log.info("ControlledLoop enter: plugin=%s hz=%d", self.name, self.hz)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._entered = False
        _log.info("ControlledLoop exit: plugin=%s", self.name)
        return False  # do not suppress exceptions

    @property
    def running(self) -> bool:
        """True only while the loop is entered AND the plugin remains active."""
        if not self._entered:
            return False
        is_active = getattr(self.registry, "is_active", None)
        if not callable(is_active):
            return False
        try:
            return bool(is_active(self.name))
        except Exception as exc:
            _log.warning("ControlledLoop.running check failed: %s", exc)
            return False

    def tick_interval(self) -> float:
        """Seconds per tick. ``hz=60`` → ``1/60``."""
        return 1.0 / self.hz
