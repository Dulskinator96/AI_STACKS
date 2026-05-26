"""ui/pyramid_chamber/chamber.py — ▲ PYRAMID CHAMBER · the living room.

Per the PYRAMID CHAMBER DIRECTIVE: a single unified cognitive environment
where the central pyramid embodies the runtime state, telemetry panels orbit
it, and the operator can speak intent into the forge to invoke creative
realms.

What is REAL in this MVP (Reality Enforcement Phase 8):
    * CPU% + RSS sampled from psutil
    * SystemStateManager current state + transition count
    * MaintenanceCortex observer count + recent issue count
    * Receipt count = execution_receipts.jsonl line count
    * Pyramid glow intensity scales with CPU% (smoothed)
    * Pyramid pulse rate scales with receipt-emission rate (recent delta)
    * Realm activation routes through actual subsystems (ConvProgramming,
      Theme generation, /cast pyramid_ensemble, external subprocess for
      installed tools)

What is DORMANT and honestly labelled "not yet built":
    * GPU-accelerated particle systems
    * Audio engine
    * DaVinci Resolve scripting bridge (the path is detected; activation
      requires DaVinciResolveScript module + license; this MVP launches
      the app via subprocess when installed)
    * 3D pyramid with orbiting nodes (QPainter 2D only for now)
    * Voice synthesis / STT

Performance discipline (Phase 6):
    * paintEvent does only QPainter — no I/O, no allocations beyond brushes
    * Telemetry sampled in a 1-second QTimer on UI thread but each sample
      is <2ms (psutil non-blocking calls)
    * Repaint requested via self.update() — Qt coalesces
    * Forge input dispatch routes to existing worker thread infrastructure
"""
from __future__ import annotations

import json
import logging
import math
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)

_log = logging.getLogger(__name__)


# ── Realms catalog ────────────────────────────────────────────────────────
# Each realm declares: glyph, label, status_probe, activate_fn (lazy).
# A realm is DORMANT until the operator clicks its gateway button.

REALMS = [
    {
        "id":     "video",
        "glyph":  "▶",
        "label":  "Video Realm",
        "color":  "#ff5722",
        "probe":  ("davinci", lambda: _probe_davinci()),
        "intent_hint": "Describe a cinematic — e.g. cyberpunk tactical intro",
    },
    {
        "id":     "audio",
        "glyph":  "♪",
        "label":  "Audio Realm",
        "color":  "#ffce28",
        "probe":  ("system_tts", lambda: _probe_audio()),
        "intent_hint": "Describe a soundscape — synthwave ambient pad",
    },
    {
        "id":     "image",
        "glyph":  "◐",
        "label":  "Image Realm",
        "color":  "#28e6ff",
        "probe":  ("stable_diffusion", lambda: _probe_sd()),
        "intent_hint": "Describe an image — neon city skyline, raining",
    },
    {
        "id":     "game",
        "glyph":  "◇",
        "label":  "Game Realm",
        "color":  "#a371f7",
        "probe":  ("simcore", lambda: _probe_simcore()),
        "intent_hint": "Describe a game — Space Invaders, 80s arcade",
    },
    {
        "id":     "code",
        "glyph":  "⚒",
        "label":  "CodeForge Realm",
        "color":  "#ff2d92",
        "probe":  ("conv_programming", lambda: _probe_codeforge()),
        "intent_hint": "Describe a change — add timestamp to every chat message",
    },
    {
        "id":     "cast",
        "glyph":  "✦",
        "label":  "Cast — 4 Agents",
        "color":  "#fff5e0",
        "probe":  ("pyramid_ensemble", lambda: _probe_pyramid()),
        "intent_hint": "Ask the four agents — what should I build next?",
    },
]


def _probe_davinci() -> tuple[bool, str]:
    for p in (
        r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe",
        r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve",
    ):
        if Path(p).exists():
            return True, f"DaVinci Resolve found at {p}"
    return False, "DaVinci Resolve not installed at default path"


def _probe_audio() -> tuple[bool, str]:
    try:
        import pyttsx3
        return True, "pyttsx3 TTS available"
    except Exception:
        return False, "pyttsx3 not installed"


def _probe_sd() -> tuple[bool, str]:
    try:
        import imageforge
        return True, "imageforge bridge ready (Stable Diffusion WebUI)"
    except Exception as e:
        return False, f"imageforge unavailable: {e}"


def _probe_simcore() -> tuple[bool, str]:
    try:
        import simcore
        return True, "simcore deterministic engine ready"
    except Exception as e:
        return False, f"simcore unavailable: {e}"


def _probe_codeforge() -> tuple[bool, str]:
    try:
        import conv_programming
        return True, "CodeForge engine ready"
    except Exception as e:
        return False, f"CodeForge unavailable: {e}"


def _probe_pyramid() -> tuple[bool, str]:
    try:
        import pyramid_ensemble
        return True, "pyramid_ensemble (4 agents + synthesis) ready"
    except Exception as e:
        return False, f"pyramid_ensemble unavailable: {e}"


# ── The central pyramid renderer ──────────────────────────────────────────

class PyramidCore(QWidget):
    """Software-rendered central pyramid. Reactive to CPU + receipt rate."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 360)
        self._cpu_smooth = 0.0
        self._pulse_phase = 0.0
        self._pulse_rate = 1.0   # Hz; scales with receipt activity
        self._last_receipt_count = 0
        self._receipts_per_min = 0.0
        self._state_name = "BOOT"
        self._observer_count = 0
        self._issue_count = 0
        # BUILD-019 PHASE 9 — Reactive Presence overrides. When the layer
        # is alive, these take precedence over the cpu-derived defaults.
        self._presence_glow_rgb = None     # (r, g, b) | None
        self._presence_state_rgb = None    # (r, g, b) | None
        self._presence_pulse = None        # float 0..1 | None
        self._presence_realm_glyph = ""    # active workspace realm glyph

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(50)  # 20 fps — gentle, GPU-safe
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start()

    def feed_telemetry(self, *, cpu: float, state: str,
                       observers: int, issues: int, receipts: int) -> None:
        # smooth cpu
        self._cpu_smooth = 0.6 * self._cpu_smooth + 0.4 * cpu
        self._state_name = state
        self._observer_count = observers
        self._issue_count = issues
        # estimate receipts-per-min from delta
        delta = max(0, receipts - self._last_receipt_count)
        self._last_receipt_count = receipts
        # called by ChamberPanel at 1Hz, so delta == receipts-per-sec
        self._receipts_per_min = 0.7 * self._receipts_per_min + 0.3 * (delta * 60.0)
        # pulse rate scales with rpm (clamped 0.5-3 Hz)
        rpm = self._receipts_per_min
        self._pulse_rate = max(0.5, min(3.0, 0.6 + rpm / 30.0))
        self.update()

    def _tick(self) -> None:
        self._pulse_phase = (self._pulse_phase + 0.05 * self._pulse_rate) % (2 * math.pi)
        self.update()

    def apply_presence(self, payload: dict) -> None:
        """BUILD-019 PHASE 9 — accept a ReactivePresenceLayer payload and
        update overrides. Called on UI thread @ 10 Hz. Cheap."""
        try:
            self._presence_glow_rgb = payload.get("glow_color") or None
            self._presence_state_rgb = payload.get("state_color") or None
            pr = payload.get("pulse_rate")
            if isinstance(pr, (int, float)):
                # Blend with the existing receipts-driven rate so neither
                # source dominates.
                self._pulse_rate = max(0.4, min(3.0,
                    0.5 * self._pulse_rate + 0.5 * float(pr)))
            self._presence_realm_glyph = payload.get("realm_glyph", "") or ""
        except Exception:
            pass

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w = self.width()
            h = self.height()
            cx = w / 2
            cy = h / 2

            # Background radial glow — intensity scales with CPU.
            # BUILD-019 PHASE 9: when the ReactivePresenceLayer is alive,
            # its personality-driven glow color overrides the cpu-derived
            # cyan/magenta default.
            load = max(0.0, min(1.0, self._cpu_smooth / 100.0))
            glow = QRadialGradient(QPointF(cx, cy), max(w, h) * 0.7)
            if self._presence_glow_rgb is not None:
                r, g, b = self._presence_glow_rgb
                # Still bias toward magenta on heavy CPU
                r = int(r + (0xff - r) * load * 0.6)
                g = int(g + (0x2d - g) * load * 0.6)
                b = int(b + (0x92 - b) * load * 0.6)
            else:
                # Cyan when idle, magenta under load (legacy default)
                r = int(0x28 + (0xff - 0x28) * load)
                g = int(0xe6 + (0x2d - 0xe6) * load)
                b = int(0xff + (0x92 - 0xff) * load)
            pulse = 0.45 + 0.35 * (0.5 + 0.5 * math.sin(self._pulse_phase))
            glow.setColorAt(0.0, QColor(r, g, b, int(180 * pulse)))
            glow.setColorAt(0.55, QColor(r, g, b, int(40 * pulse)))
            glow.setColorAt(1.0, QColor(10, 4, 32, 0))
            p.setBrush(QBrush(glow))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, cy), w * 0.45, h * 0.45)

            # Pyramid — 4 stacked triangle layers, each rotated and scaled.
            # Outer is dimmest, inner is brightest.
            for layer in range(4):
                size_frac = 0.42 - layer * 0.08
                half_base = w * size_frac
                height_px = h * (size_frac * 1.15)
                layer_alpha = 70 + layer * 50
                layer_color = QColor(r, g, b, layer_alpha)

                # Slight rotation per layer for that orbiting feel
                p.save()
                p.translate(cx, cy + height_px * 0.15)
                p.rotate(math.sin(self._pulse_phase + layer * 0.4) * 6.0)
                # Triangle apex up
                from PyQt6.QtGui import QPolygonF
                poly = QPolygonF([
                    QPointF(0,           -height_px * 0.85),
                    QPointF(-half_base,   height_px * 0.15),
                    QPointF( half_base,   height_px * 0.15),
                ])
                pen = QPen(QColor(255, 245, 224, layer_alpha + 60))
                pen.setWidth(2)
                p.setPen(pen)
                p.setBrush(QBrush(layer_color))
                p.drawPolygon(poly)
                p.restore()

            # Apex glyph — small bright dot at the top of the inner pyramid
            apex_y = cy + h * 0.42 * 0.15 - h * 0.42 * 1.15 * 0.85
            apex_size = 4 + 2 * (0.5 + 0.5 * math.sin(self._pulse_phase * 1.5))
            p.setBrush(QBrush(QColor(255, 245, 224, 220)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, apex_y), apex_size, apex_size)

            # Center text — current state, small caps
            state_font = QFont("Consolas", 10, QFont.Weight.Bold)
            p.setFont(state_font)
            p.setPen(QColor(255, 245, 224, 200))
            text_rect = QRectF(0, cy + h * 0.22, w, 24)
            p.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter,
                        f"STATE · {self._state_name}")

            # Sub-line — observer count and receipt activity
            sub_font = QFont("Consolas", 8)
            p.setFont(sub_font)
            p.setPen(QColor(255, 142, 183, 180))
            text_rect2 = QRectF(0, cy + h * 0.28, w, 16)
            p.drawText(
                text_rect2, Qt.AlignmentFlag.AlignHCenter,
                f"{self._observer_count} observers · {self._issue_count} issues · "
                f"{self._receipts_per_min:.0f} receipts/min",
            )
        finally:
            p.end()


# ── Telemetry side panel ──────────────────────────────────────────────────

class TelemetryWall(QFrame):
    """Right-side floating panel showing structured runtime numbers."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "TelemetryWall { background:#1a0e3e; border:1px solid #ff2d92;"
            " border-radius:8px; padding:8px; }"
        )
        self.setMinimumWidth(220)

        title = QLabel("◈  TELEMETRY")
        title.setStyleSheet(
            "color:#ffce28; font-weight:bold; font-size:11px; letter-spacing:3px;"
            " background: transparent;"
        )
        self._cpu = QLabel("CPU —")
        self._rss = QLabel("RSS —")
        self._state = QLabel("STATE —")
        self._observers = QLabel("Observers —")
        self._issues = QLabel("Issues —")
        self._receipts = QLabel("Receipts —")
        self._uptime = QLabel("Uptime —")
        for lbl in (self._cpu, self._rss, self._state, self._observers,
                    self._issues, self._receipts, self._uptime):
            lbl.setStyleSheet(
                "color:#fff5e0; font-family:Consolas,monospace; font-size:11px;"
                " background: transparent;"
            )

        lay = QVBoxLayout(self)
        lay.setSpacing(6)
        lay.addWidget(title)
        lay.addWidget(self._cpu)
        lay.addWidget(self._rss)
        lay.addWidget(self._state)
        lay.addWidget(self._observers)
        lay.addWidget(self._issues)
        lay.addWidget(self._receipts)
        lay.addWidget(self._uptime)
        lay.addStretch()

    def update_telemetry(self, *, cpu: float, rss_mb: float, state: str,
                          observers: int, issues: int, receipts: int,
                          uptime_s: float) -> None:
        self._cpu.setText(f"CPU         {cpu:5.1f} %")
        self._rss.setText(f"RSS         {rss_mb:6.1f} MB")
        self._state.setText(f"STATE       {state}")
        self._observers.setText(f"Observers   {observers}")
        self._issues.setText(f"Issues      {issues}")
        self._receipts.setText(f"Receipts    {receipts}")
        mins = int(uptime_s // 60)
        secs = int(uptime_s % 60)
        self._uptime.setText(f"Uptime      {mins:02d}m {secs:02d}s")


# ── Forge / realm gateway ─────────────────────────────────────────────────

class RealmGateway(QFrame):
    """Bottom strip of realm buttons + intent input + send."""

    def __init__(self, on_intent, parent=None):
        super().__init__(parent)
        self._on_intent = on_intent
        self.setStyleSheet(
            "RealmGateway { background:#0a0420; border:1px solid #ff2d92;"
            " border-radius:8px; padding:8px; }"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        title = QLabel("✶  CREATIVE REALMS  ·  pick a domain, speak the intent")
        title.setStyleSheet(
            "color:#ffce28; font-weight:bold; font-size:11px; letter-spacing:2px;"
            " background: transparent;"
        )
        lay.addWidget(title)

        # Realm gateway buttons row
        realm_row = QHBoxLayout()
        realm_row.setSpacing(6)
        self._buttons = {}
        self._active_realm: Optional[dict] = None
        for realm in REALMS:
            btn = QPushButton(f"{realm['glyph']}  {realm['label']}")
            btn.setStyleSheet(
                f"QPushButton {{ background:#1a0e3e; color:#fff5e0;"
                f" border:2px solid {realm['color']}; border-radius:6px;"
                f" padding:6px 10px; font-weight:bold; font-size:11px;"
                f" letter-spacing:1px; }}"
                f"QPushButton:hover {{ background:{realm['color']}; color:#0a0420; }}"
                f"QPushButton:checked {{ background:{realm['color']}; color:#0a0420; }}"
            )
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked, r=realm: self._select_realm(r))
            realm_row.addWidget(btn)
            self._buttons[realm["id"]] = btn
        realm_row.addStretch()
        lay.addLayout(realm_row)

        self._status = QLabel("◯ select a realm — its status will probe live")
        self._status.setStyleSheet(
            "color:#ff8eb7; font-size:10px; padding:2px;"
            " background: transparent;"
        )
        lay.addWidget(self._status)

        # Intent input row
        intent_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText(
            "Speak the intent — select a realm above and press Send"
        )
        self._input.setStyleSheet(
            "QLineEdit { background:#1a0e3e; color:#fff5e0;"
            " border:1px solid #ff2d92; border-radius:5px;"
            " padding:6px 8px; font-size:12px; }"
        )
        self._input.returnPressed.connect(self._send)
        intent_row.addWidget(self._input, 1)

        send_btn = QPushButton("⊳  SEND")
        send_btn.setStyleSheet(
            "QPushButton { background:#ffce28; color:#1a0e3e; border:none;"
            " border-radius:5px; padding:7px 18px; font-weight:bold;"
            " letter-spacing:2px; }"
            "QPushButton:hover { background:#fff5e0; }"
        )
        send_btn.clicked.connect(self._send)
        intent_row.addWidget(send_btn)
        lay.addLayout(intent_row)

    def _select_realm(self, realm: dict) -> None:
        # Toggle off others
        for rid, btn in self._buttons.items():
            if rid != realm["id"]:
                btn.setChecked(False)
        self._active_realm = realm
        self._input.setPlaceholderText(realm["intent_hint"])
        # Probe lazily
        try:
            available, msg = realm["probe"][1]()
            mark = "✓" if available else "◯"
            color = "#28e6ff" if available else "#ff8eb7"
            self._status.setText(f"{mark} {realm['label']} — {msg}")
            self._status.setStyleSheet(
                f"color:{color}; font-size:10px; padding:2px;"
                " background: transparent;"
            )
        except Exception as e:
            self._status.setText(f"✗ probe failed: {e}")

    def _send(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        if self._active_realm is None:
            self._status.setText("◯ select a realm above first")
            return
        self._input.clear()
        try:
            self._on_intent(self._active_realm, text)
        except Exception as e:
            self._status.setText(f"✗ dispatch failed: {e}")


# ── Top-level chamber ─────────────────────────────────────────────────────

class PyramidChamberPanel(QWidget):
    """▲ The Pyramid Chamber — the living unified room."""

    # BUILD-018 RULE 5 — dispatched intent + plan flow up to dashboard so
    # it can decide whether to spawn a dedicated workspace tab. Chamber
    # never imports HistoryDashboard — strict upward signal.
    realm_dispatched = pyqtSignal(str, str, object)   # realm_id, intent, plan

    def __init__(self, parent_app, parent=None):
        super().__init__(parent)
        self.parent_app = parent_app
        self._boot_t0 = time.monotonic()
        self._receipts_path = self._find_receipts_path()
        self.setStyleSheet(
            "PyramidChamberPanel { background:#0a0420; }"
        )
        self._build_ui()

        # Telemetry tick @ 1Hz on UI thread — each call is <2ms
        self._telemetry_timer = QTimer(self)
        self._telemetry_timer.setInterval(1000)
        self._telemetry_timer.timeout.connect(self._refresh_telemetry)
        self._telemetry_timer.start()
        QTimer.singleShot(50, self._refresh_telemetry)

        # BUILD-019 PHASE 9 — Reactive Presence Layer. Ambient pulse
        # animations driven by REAL telemetry (CPU%, receipt rate, state).
        try:
            from ui.pyramid_chamber.reactive_presence import ReactivePresenceLayer
            self._presence = ReactivePresenceLayer(self)
            self._presence.presence_tick.connect(self._on_presence_tick)
            self._presence.start()
        except Exception as _pl_e:
            self._presence = None
            _log = logging.getLogger(__name__) if 'logging' in dir() else None
            if _log is not None:
                _log.debug("ReactivePresenceLayer unavailable: %s", _pl_e)

        # BUILD-019/020 — Eager-build the entire organism on first chamber
        # construction so the first intent dispatch has no cold-start cost.
        # Worker thread; never blocks paint.
        try:
            from runtime.deferred_loader import DeferredWorkspaceLoader
            def _warmup_organism():
                from engine.pyramid_engine        import get_engine
                from engine.cognitive_core        import get_cognitive_core
                from engine.tool_fabric           import get_tool_fabric
                from engine.workspace_fabric      import get_workspace_fabric
                from engine.realm_orchestrator    import get_realm_orchestrator
                from engine.media_generation_layer import get_media_generation_layer
                from engine.simulation_engine     import get_simulation_engine
                from engine.adaptive_learning     import get_adaptive_learning
                from engine.diagnostics_layer     import get_diagnostics
                from engine.personality_matrix    import get_personality_matrix
                get_engine()
                get_cognitive_core()
                get_tool_fabric()
                get_workspace_fabric()
                get_realm_orchestrator()
                get_media_generation_layer()
                get_simulation_engine()
                get_adaptive_learning()
                get_diagnostics()
                get_personality_matrix()
            DeferredWorkspaceLoader.run(
                _warmup_organism, on_done=None, name="organism_warmup",
            )
        except Exception:
            pass

        # BUILD-020 SECTION 10 — Reactive Presence Layer v2 (particle
        # system). Lives ON TOP of v1 (which still drives the pyramid's
        # glow color). v2 paints particles + cinematic bursts.
        try:
            from ui.pyramid_chamber.reactive_presence_v2 import ReactivePresenceLayerV2
            self._presence_v2 = ReactivePresenceLayerV2(self)
            self._presence_v2.repaint_requested.connect(self.update)
            self._presence_v2.start()
            # Forward state changes from v1 → v2 so cinematic events fire
            if getattr(self, "_presence", None) is not None:
                self._presence.presence_tick.connect(self._forward_presence_to_v2)
        except Exception as _pv2_e:
            self._presence_v2 = None

    def _on_presence_tick(self, payload: dict) -> None:
        """Forward reactive payload to PyramidCore for glow modulation.
        Cheap — just a couple of attribute writes + an update() request."""
        try:
            core = getattr(self, "_pyramid", None)
            if core is not None and hasattr(core, "apply_presence"):
                core.apply_presence(payload)
        except Exception:
            pass

    def _forward_presence_to_v2(self, payload: dict) -> None:
        """Forward v1 presence tick into v2 so it can detect state/realm
        changes and fire cinematic events."""
        try:
            v2 = getattr(self, "_presence_v2", None)
            if v2 is None:
                return
            sc = payload.get("state_color")
            if sc:
                # Use the state color tuple as a proxy state identifier
                v2.signal_state_change(str(sc))
            rg = payload.get("realm_glyph", "")
            if rg:
                v2.signal_realm_change(rg)
        except Exception:
            pass

    def _find_receipts_path(self) -> Optional[Path]:
        try:
            import sys as _sys
            if getattr(_sys, "frozen", False):
                base = Path(_sys.executable).resolve().parent
            else:
                base = Path(__file__).resolve().parents[2]
            p = base / "telemetry" / "execution_receipts.jsonl"
            return p
        except Exception:
            return None

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # Banner
        banner = QFrame()
        banner.setStyleSheet(
            "QFrame { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            " stop:0 #1a0e3e, stop:0.5 #ff2d92, stop:1 #1a0e3e);"
            " border:2px solid #ffce28; border-radius:8px; }"
        )
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(14, 6, 14, 6)
        title = QLabel("▲  PYRAMID CHAMBER  ·  the living cognitive room")
        title.setStyleSheet(
            "color:#fff5e0; font-weight:bold; font-size:14px;"
            " letter-spacing:3px; background: transparent;"
        )
        bl.addWidget(title)
        bl.addStretch()
        root.addWidget(banner)

        # Body splitter: pyramid + telemetry wall
        body = QSplitter(Qt.Orientation.Horizontal)
        self._pyramid = PyramidCore(self)
        body.addWidget(self._pyramid)
        self._telemetry_wall = TelemetryWall(self)
        body.addWidget(self._telemetry_wall)
        body.setStretchFactor(0, 4)
        body.setStretchFactor(1, 1)
        root.addWidget(body, 1)

        # Realm gateway at bottom
        self._gateway = RealmGateway(self._on_realm_intent, self)
        root.addWidget(self._gateway)

        # Chamber log
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumHeight(120)
        self._log_view.setStyleSheet(
            "QPlainTextEdit { background:#0a0420; color:#fff5e0;"
            " border:1px solid #ff2d92; border-radius:5px;"
            " font-family:Consolas,monospace; font-size:10px; padding:6px; }"
        )
        self._log_view.setPlaceholderText("Chamber log — dispatch results land here")
        root.addWidget(self._log_view)

    # ── Telemetry refresh ─────────────────────────────────────────────────

    def _refresh_telemetry(self) -> None:
        cpu = 0.0
        rss_mb = 0.0
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=None)
            rss_mb = psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
        except Exception: pass

        state = "BOOT"
        try:
            from core.state_manager import get_state_manager
            sm = get_state_manager()
            state = sm.current.value if hasattr(sm.current, "value") else str(sm.current)
        except Exception: pass

        observers = 0
        issues = 0
        try:
            from core.bootstrap import get_bootstrap
            cortex = get_bootstrap().get_maintenance_cortex()
            if cortex is not None:
                observers = len(getattr(cortex, "observers", []) or [])
                try:
                    outcomes = list(getattr(cortex.runtime, "last_outcomes", []) or [])
                    issues = len(outcomes)
                except Exception:
                    pass
        except Exception: pass

        receipts = self._count_receipts()
        uptime = time.monotonic() - self._boot_t0

        self._telemetry_wall.update_telemetry(
            cpu=cpu, rss_mb=rss_mb, state=state,
            observers=observers, issues=issues,
            receipts=receipts, uptime_s=uptime,
        )
        self._pyramid.feed_telemetry(
            cpu=cpu, state=state, observers=observers,
            issues=issues, receipts=receipts,
        )

    def _count_receipts(self) -> int:
        if self._receipts_path is None or not self._receipts_path.is_file():
            return 0
        try:
            # Fast line count — read in chunks, count newlines. For the
            # current size (~30KB) it's well under 1ms.
            with self._receipts_path.open("rb") as fh:
                return sum(1 for _ in fh)
        except Exception:
            return 0

    # ── Realm dispatch ────────────────────────────────────────────────────

    def _log(self, line: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self._log_view.appendPlainText(f"[{ts}] {line}")

    def _on_realm_intent(self, realm: dict, intent: str) -> None:
        """Route an intent through the PYRAMID ENGINE (build-019).

        Replaces the inline per-realm dispatch with a unified call into
        the central engine. The engine handles:
          IntentCortex → CreativeExpansion → ExecutionPlanner →
          RealmDispatcher → ReflectionEngine → OutputRenderer →
          PersonalityModel absorption.

        Chamber stays as the surface — it emits the realm_dispatched
        signal up to the dashboard so a dedicated workspace tab still
        spawns, and it streams the engine's progress into the log.
        """
        self._log(f"✶ {realm['label']}  ▸  {intent}")

        # ── PYRAMID ORGANISM entry point (BUILD-020) ───────────────────
        # Route through the CognitiveCore spine. The core handles realm
        # arbitration, pre-flight tool checks, engine handoff, reflection
        # meta-followups, and adaptive learning absorption.
        try:
            from engine.cognitive_core import get_cognitive_core
            cog = get_cognitive_core()
        except Exception as e:
            self._log(f"  (cognitive_core unavailable — {e}; falling back to direct engine)")
            cog = None

        # Kernel pre-pass — still useful for the upward signal payload
        plan = None
        try:
            from kernel.intent_orchestrator import orchestrate
            plan = orchestrate(intent)
        except Exception:
            pass

        rid = realm["id"]

        # BUILD-018 RULE 5 — emit upward BEFORE dispatch so the dashboard
        # can spawn a dedicated workspace tab in parallel.
        try:
            self.realm_dispatched.emit(rid, intent, plan)
        except Exception:
            pass

        # BUILD-020 — check if intent warrants a workspace constellation
        # (movie/game/soundtrack/etc. with ambition keywords) and spawn
        # it through the WorkspaceFabric. The constellation runs PARALLEL
        # to the engine pipeline.
        try:
            from engine.workspace_fabric import get_workspace_fabric
            wf = get_workspace_fabric()
            if wf.should_spawn_constellation(intent):
                constellation = wf.spawn_constellation(intent, plan=plan)
                if constellation is not None:
                    self._log(
                        f"  ✦ constellation '{constellation.pattern}' "
                        f"spawned ({len(constellation.sessions)} rooms)"
                    )
        except Exception as e:
            self._log(f"  (workspace_fabric unavailable — {e})")

        # Cognitive-core driven dispatch
        if cog is not None:
            try:
                def _on_complete(cycle):
                    try:
                        sess = cycle.engine_session
                        if cycle.state == "DONE" and sess is not None \
                                and getattr(sess, "final_output", None) is not None:
                            for ln in sess.final_output.chamber_lines:
                                self._log(ln)
                        elif cycle.state == "FAILED":
                            self._log(f"  ✗ cognitive cycle FAILED: {cycle.error}")
                        # Meta-followups from the cognitive core
                        for fu in cycle.reflection_followups[:3]:
                            self._log(f"  ◇ {fu}")
                    except Exception:
                        pass

                cog.initiate(intent, on_complete=_on_complete, log_fn=self._log)
                return
            except Exception as e:
                self._log(f"  (cognitive_core pipeline failed — {e}; using kernel render)")

        # Fallback path — direct engine call when cognitive_core unavailable
        try:
            from engine.pyramid_engine import get_engine
            engine = get_engine()
            engine.process_intent(intent, log_fn=self._log)
            return
        except Exception:
            pass

        # Fallback (only if engine unavailable AND kernel render was wanted)
        try:
            from kernel.intent_orchestrator import render_plan
            if plan is not None:
                self._log(render_plan(plan))
        except Exception:
            pass

        if rid == "code":
            # Route to CodeForge via WON request directly through the engine
            try:
                from conv_programming import get_engine
                eng = get_engine()
                # Submit on a worker thread so we don't block the chamber
                hd = getattr(self.parent_app, "dashboard", None)
                if hd is not None and hasattr(hd, "_run_in_thread"):
                    def _run():
                        try:
                            return eng.process(intent)
                        except Exception as e:
                            return {"error": str(e)}
                    def _done(result):
                        if isinstance(result, dict) and "error" in result:
                            self._log(f"  ✗ CodeForge: {result['error']}")
                        else:
                            self._log(f"  ⚒ CodeForge response logged — switch to ◈ CodeForge tab to review")
                    hd._run_in_thread(_run, on_done=_done)
                else:
                    self._log("  ✗ no worker thread available")
            except Exception as e:
                self._log(f"  ✗ {e}")
            return

        if rid == "cast":
            # Route through the existing pyramid_ensemble
            try:
                from pyramid_ensemble import EnsembleOrchestrator
                hd = getattr(self.parent_app, "dashboard", None)
                def _run():
                    try:
                        eo = EnsembleOrchestrator()
                        return {"verdict": eo.run(intent)}
                    except Exception as e:
                        return {"error": str(e)}
                def _done(r):
                    if isinstance(r, dict) and "error" in r:
                        self._log(f"  ✗ Cast failed: {r['error']}")
                    else:
                        verdict = r.get("verdict") if isinstance(r, dict) else str(r)
                        snippet = (verdict or "")[:200].replace("\n", " ")
                        self._log(f"  ✦ {snippet}")
                if hd is not None and hasattr(hd, "_run_in_thread"):
                    hd._run_in_thread(_run, on_done=_done)
            except Exception as e:
                self._log(f"  ✗ {e}")
            return

        if rid == "image":
            try:
                from imageforge import get_engine
                hd = getattr(self.parent_app, "dashboard", None)
                def _run():
                    try:
                        eng = get_engine()
                        out = eng.synthesize(intent, style="cinematic")
                        return {"out": str(out)}
                    except Exception as e:
                        return {"error": str(e)}
                def _done(r):
                    if isinstance(r, dict) and "error" in r:
                        self._log(f"  ✗ image: {r['error']}")
                    else:
                        self._log(f"  ◐ image queued — output: {r.get('out')}")
                if hd is not None and hasattr(hd, "_run_in_thread"):
                    hd._run_in_thread(_run, on_done=_done)
            except Exception as e:
                self._log(f"  ✗ {e}")
            return

        if rid == "audio":
            try:
                import pyttsx3
                hd = getattr(self.parent_app, "dashboard", None)
                def _run():
                    try:
                        eng = pyttsx3.init()
                        eng.say(intent)
                        eng.runAndWait()
                        return {"ok": True}
                    except Exception as e:
                        return {"error": str(e)}
                def _done(r):
                    if isinstance(r, dict) and "error" in r:
                        self._log(f"  ✗ audio: {r['error']}")
                    else:
                        self._log("  ♪ audio rendered via pyttsx3")
                if hd is not None and hasattr(hd, "_run_in_thread"):
                    hd._run_in_thread(_run, on_done=_done)
            except Exception as e:
                self._log(f"  ✗ {e}")
            return

        if rid == "game":
            # Game realm — for now: bootstrap simcore and log world hash
            try:
                import simcore
                hd = getattr(self.parent_app, "dashboard", None)
                def _run():
                    try:
                        world = simcore.SimCore.bootstrap(seed=hash(intent) & 0xffff)
                        h = world.current_world().hash[:16]
                        return {"hash": h, "seed": hash(intent) & 0xffff}
                    except Exception as e:
                        return {"error": str(e)}
                def _done(r):
                    if isinstance(r, dict) and "error" in r:
                        self._log(f"  ✗ game: {r['error']}")
                    else:
                        self._log(f"  ◇ simcore world seeded — hash={r['hash']} seed={r['seed']}")
                        self._log("    Full game generation pipeline is the next build target")
                if hd is not None and hasattr(hd, "_run_in_thread"):
                    hd._run_in_thread(_run, on_done=_done)
            except Exception as e:
                self._log(f"  ✗ {e}")
            return

        if rid == "video":
            # Video realm — DaVinci Resolve. Honest behavior: detect, launch
            # the app if found, but no scripting bridge yet.
            try:
                available, msg = _probe_davinci()
                if not available:
                    self._log(f"  ◯ video realm dormant — {msg}. Install DaVinci Resolve to activate.")
                    return
                self._log(f"  ▶ launching DaVinci Resolve…")
                resolve_path = (
                    r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe"
                )
                subprocess.Popen([resolve_path], shell=False)
                self._log("    Resolve launched. Scripting bridge (Python API)"
                          " is a future build pass — the room will be the"
                          " orchestration surface for it then.")
            except Exception as e:
                self._log(f"  ✗ video realm: {e}")
            return
