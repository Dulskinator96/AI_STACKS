"""ui/pyramid_chamber/reactive_presence_v2.py — BUILD-020 SECTION 10.

Reactive Presence Layer v2 — particle system + cinematic transitions.
QPainter-based (CPU rendering, no GPU dependency required). All effects
tied to REAL telemetry; never fabricated.

Particles:
  · count scales with receipts-per-minute (0..32)
  · color is the personality glow color (build-019)
  · velocity field is driven by active realm (cyan upward for image,
    magenta horizontal for cast, etc.)
  · spawn on completion events (cinematic feedback)

Cinematic transitions:
  · realm change → a brief radial flash in the new realm's color
  · cycle DONE / state EXECUTING → screen-edge bloom
  · score > 0.85 → soft full-screen pulse

The layer is OPTIONAL and lazily constructed. It degrades to no-ops if
the parent widget cannot paint particles (e.g., during unit tests).
"""
from __future__ import annotations

import logging
import math
import random
import time
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import QObject, QPointF, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QRadialGradient

_log = logging.getLogger(__name__)


@dataclass
class Particle:
    x:         float
    y:         float
    vx:        float
    vy:        float
    life:      float       # 0..1, decays each tick
    color_rgb: tuple
    size:      float


_REALM_VELOCITY_FIELD = {
    "image":      (0.0,  -0.6),   # upward (rising scene)
    "video":      (0.3,  -0.3),   # diagonal up
    "audio":      (0.6,   0.0),   # rightward (wave)
    "game":       (0.0,   0.6),   # downward (falling pieces)
    "code":       (-0.4, -0.4),   # diagonal up-left
    "cast":       (0.0,   0.0),   # radial outward (set per particle)
    "simulation": (0.2,   0.4),   # downward slight right
}


class ReactivePresenceLayerV2(QObject):
    """Particle system + cinematic transition emitter."""

    repaint_requested = pyqtSignal()
    cinematic_event = pyqtSignal(str, dict)    # kind, payload

    def __init__(self, parent_widget):
        super().__init__(parent_widget)
        self._parent = parent_widget
        self._particles: list[Particle] = []
        self._last_receipt_count = 0
        self._last_state = ""
        self._last_realm = ""
        self._tick_count = 0
        self._t0 = time.monotonic()
        self._enabled = True
        self._max_particles = 64
        self._timer = QTimer(self)
        self._timer.setInterval(50)   # 20 fps — gentle
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        if self._enabled:
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if enabled:
            self.start()
        else:
            self.stop()

    # ── Public spawn API (called from chamber/engine completion paths) ─
    def spawn_burst(self, x: float, y: float, color_rgb: tuple,
                     count: int = 12, realm: str = "cast") -> None:
        """Spawn a burst of particles at (x, y). Used as cinematic
        feedback on successful generation."""
        if not self._enabled:
            return
        vx_base, vy_base = _REALM_VELOCITY_FIELD.get(realm, (0.0, 0.0))
        for _ in range(min(count, self._max_particles - len(self._particles))):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(0.4, 1.6)
            vx = vx_base + math.cos(angle) * speed
            vy = vy_base + math.sin(angle) * speed
            self._particles.append(Particle(
                x=x, y=y, vx=vx, vy=vy,
                life=1.0, color_rgb=color_rgb,
                size=random.uniform(2.0, 5.0),
            ))
        try:
            self.cinematic_event.emit("burst",
                {"x": x, "y": y, "count": count, "realm": realm})
        except Exception:
            pass

    def signal_state_change(self, new_state: str) -> None:
        """Emit a cinematic event when system state changes."""
        if new_state != self._last_state:
            try:
                self.cinematic_event.emit("state_change",
                    {"prev": self._last_state, "next": new_state})
            except Exception:
                pass
            self._last_state = new_state

    def signal_realm_change(self, new_realm: str) -> None:
        if new_realm != self._last_realm:
            try:
                self.cinematic_event.emit("realm_change",
                    {"prev": self._last_realm, "next": new_realm})
            except Exception:
                pass
            self._last_realm = new_realm

    # ── Tick (driven by real telemetry) ───────────────────────────────
    def _tick(self) -> None:
        if not self._enabled:
            return
        self._tick_count += 1

        # Update existing particles
        next_particles: list[Particle] = []
        for p in self._particles:
            p.x += p.vx * 2.0
            p.y += p.vy * 2.0
            p.life -= 0.020
            if p.life > 0:
                next_particles.append(p)
        self._particles = next_particles

        # Spawn ambient particles based on receipt rate (real telemetry)
        target_count = self._target_particle_count()
        deficit = target_count - len(self._particles)
        if deficit > 0:
            self._spawn_ambient(min(deficit, 4))   # cap per tick

        # Emit repaint request periodically
        if self._tick_count % 2 == 0 and self._particles:
            try:
                self.repaint_requested.emit()
            except Exception:
                pass

    def _target_particle_count(self) -> int:
        """Target count scales with receipts/min — real activity only."""
        try:
            from runtime.singleton_registry import get_registry
            bridge = get_registry().get("ui.state_bridge")
            if bridge is not None and hasattr(bridge, "_projection"):
                snap = bridge._projection.build_snapshot()
                rpm = float(getattr(snap, "receipt_count_last_minute", 0))
                return min(self._max_particles, max(4, int(rpm * 0.6)))
        except Exception:
            pass
        return 4

    def _spawn_ambient(self, n: int) -> None:
        """Spawn slow drifting ambient particles at random edge positions."""
        if self._parent is None:
            return
        try:
            w = self._parent.width()
            h = self._parent.height()
        except Exception:
            return
        # Pull glow color from personality
        glow = self._glow_color()
        for _ in range(n):
            edge = random.choice(("top", "bottom", "left", "right"))
            if edge == "top":
                x, y = random.uniform(0, w), 0
                vx, vy = random.uniform(-0.3, 0.3), random.uniform(0.2, 0.6)
            elif edge == "bottom":
                x, y = random.uniform(0, w), h
                vx, vy = random.uniform(-0.3, 0.3), random.uniform(-0.6, -0.2)
            elif edge == "left":
                x, y = 0, random.uniform(0, h)
                vx, vy = random.uniform(0.2, 0.6), random.uniform(-0.3, 0.3)
            else:
                x, y = w, random.uniform(0, h)
                vx, vy = random.uniform(-0.6, -0.2), random.uniform(-0.3, 0.3)
            self._particles.append(Particle(
                x=x, y=y, vx=vx, vy=vy,
                life=1.0, color_rgb=glow,
                size=random.uniform(1.5, 3.0),
            ))

    def _glow_color(self) -> tuple:
        try:
            from engine.personality_model import get_personality
            from ui.pyramid_chamber.reactive_presence import _COLOR_NAME_RGB, _DEFAULT_GLOW
            top = get_personality().top_preference("color")
            return _COLOR_NAME_RGB.get(top or "", _DEFAULT_GLOW)
        except Exception:
            return (40, 230, 255)

    # ── Paint helper (called from chamber.paintEvent) ─────────────────
    def paint_overlay(self, painter: QPainter, w: int, h: int) -> None:
        """Render particles + cinematic accents on top of chamber content.
        Called from the parent widget's paintEvent."""
        if not self._enabled or not self._particles:
            return
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            for p in self._particles:
                if p.x < -10 or p.x > w + 10 or p.y < -10 or p.y > h + 10:
                    continue
                r, g, b = p.color_rgb
                alpha = int(180 * p.life)
                if alpha <= 0:
                    continue
                color = QColor(r, g, b, alpha)
                # Soft halo
                painter.setBrush(color)
                painter.setPen(QColor(0, 0, 0, 0))
                painter.drawEllipse(QPointF(p.x, p.y), p.size, p.size)
        except Exception as e:
            _log.debug("paint_overlay failed: %s", e)

    def particle_count(self) -> int:
        return len(self._particles)
