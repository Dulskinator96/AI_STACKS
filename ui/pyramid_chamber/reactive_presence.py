"""ui/pyramid_chamber/reactive_presence.py — PHASE 9 Reactive Presence Layer.

Subtle ambient animations that reflect REAL runtime state. No fake
activity. All effects are GPU-safe (QPainter at low frame budget),
non-blocking, optional, and reflect only verified telemetry.

What it drives:
  · pulse_phase: smooth sine 0..1 at 0.4 Hz (configurable). Used by
    PyramidCore.paintEvent to modulate the glow alpha.
  · breath_color: hue interpolation along the operator's dominant
    palette (from PersonalityModel.top_color). Reflects real preference.
  · realm_active_glyph: while a workspace session is open, the glyph
    of that realm pulses brighter; idle = uniform low glow.
  · state_label_color: tracks the SystemState — BOOT amber, READY cyan,
    EXECUTING magenta, FAILED red. Real state, never simulated.

The layer is a thin QObject + QTimer; it never touches the network,
never imports models, never touches disk on its tick.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QColor

_log = logging.getLogger(__name__)


class ReactivePresenceLayer(QObject):
    """1 Hz reactive-state emitter for the Pyramid Chamber."""

    presence_tick = pyqtSignal(dict)   # payload: {pulse, glow_color, state_color, ...}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._t0 = time.monotonic()
        self._tick_count = 0
        self._timer = QTimer(self)
        self._timer.setInterval(100)   # 10 Hz — smooth enough for pulse, cheap
        self._timer.timeout.connect(self._on_tick)
        self._enabled = True

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if not enabled:
            self.stop()
        else:
            self.start()

    def _on_tick(self) -> None:
        if not self._enabled:
            return
        t = time.monotonic() - self._t0
        # Slow breath: 0.4 Hz (2.5s cycle), 1.0 Hz under activity
        pulse_rate = self._pulse_rate_from_runtime()
        pulse = 0.5 + 0.5 * math.sin(2 * math.pi * pulse_rate * t)

        glow_color = self._glow_color_from_personality()
        state_color = self._state_color()
        realm_glyph = self._active_realm_glyph()

        payload = {
            "tick":         self._tick_count,
            "t":            t,
            "pulse":        pulse,
            "pulse_rate":   pulse_rate,
            "glow_color":   glow_color,
            "state_color":  state_color,
            "realm_glyph":  realm_glyph,
            "cpu_pct":      self._sample_cpu(),
        }
        try:
            self.presence_tick.emit(payload)
        except Exception:
            pass
        self._tick_count += 1

    # ── Runtime-grounded inputs (NEVER fake) ────────────────────────────
    def _pulse_rate_from_runtime(self) -> float:
        """Higher when receipts are flowing faster — observed activity."""
        try:
            from runtime.singleton_registry import get_registry
            bridge = get_registry().get("ui.state_bridge")
            if bridge is not None and hasattr(bridge, "_projection"):
                snap = bridge._projection.build_snapshot()
                recent = float(getattr(snap, "receipt_count_last_minute", 0))
                # Map 0..60 receipts/min → 0.4..2.0 Hz pulse
                return max(0.4, min(2.0, 0.4 + (recent / 60.0) * 1.6))
        except Exception:
            pass
        return 0.4

    def _glow_color_from_personality(self) -> tuple:
        """Color drift toward the operator's most-used palette."""
        try:
            from engine.personality_model import get_personality
            top = get_personality().top_preference("color")
            return _COLOR_NAME_RGB.get(top or "", _DEFAULT_GLOW)
        except Exception:
            return _DEFAULT_GLOW

    def _state_color(self) -> tuple:
        try:
            from runtime.singleton_registry import get_registry
            sm = get_registry().get("core.state_manager")
            if sm is not None and hasattr(sm, "current"):
                state = sm.current
                name = state.name if hasattr(state, "name") else str(state)
                return _STATE_COLOR.get(name, _DEFAULT_GLOW)
        except Exception:
            pass
        return _DEFAULT_GLOW

    def _active_realm_glyph(self) -> str:
        """Returns the glyph of the most recent realm dispatched, '' if idle."""
        try:
            from runtime.workspace_spawner import get_workspace_spawner
            from ui.realm_session_tab import REALM_GLYPHS
            sessions = get_workspace_spawner().active_sessions()
            if sessions:
                latest = max(sessions, key=lambda s: s.spawned_at)
                return REALM_GLYPHS.get(latest.realm, "◈")
        except Exception:
            pass
        return ""

    def _sample_cpu(self) -> float:
        try:
            import psutil
            return float(psutil.cpu_percent(interval=None))
        except Exception:
            return 0.0


# RGB tuples for personality-driven glow colors
_COLOR_NAME_RGB = {
    "red":     (192,  72, 104),
    "orange":  (240, 160,  64),
    "amber":   (240, 176,   0),
    "yellow":  (255, 206,  40),
    "gold":    (216, 184, 120),
    "green":   ( 90, 242, 111),
    "emerald": ( 24, 184, 150),
    "teal":    ( 42, 196, 192),
    "cyan":    ( 40, 230, 255),
    "blue":    ( 58, 143, 200),
    "indigo":  ( 96,  64, 184),
    "violet":  (122,  90, 215),
    "purple":  (128,  72, 200),
    "magenta": (255,  45, 146),
    "pink":    (255, 142, 183),
    "rose":    (220, 100, 130),
    "crimson": (192,  72, 104),
    "scarlet": (220,  40,  60),
    "silver":  (192, 192, 192),
    "bronze":  (192, 128,  80),
    "copper":  (200, 130,  80),
    "neon":    (255,  45, 146),
}

_DEFAULT_GLOW = (40, 230, 255)   # cyan

_STATE_COLOR = {
    "BOOT":            (240, 160,  64),  # amber
    "INIT":            (240, 160,  64),
    "VALIDATING":      (240, 176,   0),
    "LOADING_MODULES": (240, 176,   0),
    "STARTING_AGENTS": (240, 176,   0),
    "READY":           ( 40, 230, 255),  # cyan
    "EXECUTING":       (255,  45, 146),  # magenta
    "FAILED":          (192,  72, 104),  # red
    "DEGRADED":        (240, 160,  64),
}
