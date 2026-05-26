"""ui/production_console/console.py — BUILD-022 Production Console panel.

Single top-level Qt widget. Six tabs:
  Production Console (master) →
    · Active Sessions
    · Artifact Gallery
    · Render Queue
    · Preview Wall
    · Tool Fabric
    · Diagnostics

The console is intent-driven — typing an intent at the top dispatches
through the cognitive core → worker. A status strip across the bottom
shows ProductionCore stats + receipt-rate + active worker count.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

_log = logging.getLogger(__name__)


PIP_BG     = "#06091c"
PIP_PANEL  = "#0a0f28"
PIP_BORDER = "#1e2e5c"
PIP_ACCENT = "#28e6ff"
PIP_HOT    = "#ff2d92"
PIP_OK     = "#5af26f"
PIP_WARN   = "#f0a030"
PIP_FAIL   = "#c04868"
PIP_DIM    = "#5070a0"


class ProductionConsolePanel(QWidget):
    """The unified production surface. Lives as the FIRST tab of the
    main dashboard in build-022."""

    def __init__(self, parent_app=None, parent=None):
        super().__init__(parent)
        self.parent_app = parent_app
        self._intent_history: list = []
        self._trace_mode = False
        self.setStyleSheet(f"ProductionConsolePanel {{ background:{PIP_BG}; }}")
        self._build_ui()
        # BUILD-024 — start in primary (LaunchSurface) mode. Trace mode
        # reveals the legacy sub-tabs on toggle.
        self._apply_mode()
        # Periodic refresh ONLY runs while trace mode is open. The
        # LaunchSurface uses LiveStreamBus instead of polling.
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._refresh_all)
        # Defer refresh activation until trace mode is toggled.

    # ── UI build ──────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # BUILD-024 — LaunchSurface is the primary view. The legacy
        # sub-tabs are kept as a trace-mode panel revealed on toggle.
        from ui.production_console.launch_surface import LaunchSurface
        self._launch_surface = LaunchSurface(self)
        self._launch_surface.request_trace_toggle.connect(self._toggle_trace_mode)
        root.addWidget(self._launch_surface, 1)

        # Tab strip with 6 sub-panels (hidden by default until trace mode)
        self._sub_tabs = QTabWidget()
        self._sub_tabs.setStyleSheet(
            f"QTabBar::tab {{ background:{PIP_PANEL}; color:{PIP_DIM};"
            f" padding:6px 14px; border:1px solid {PIP_BORDER}; }}"
            f"QTabBar::tab:selected {{ background:{PIP_BG}; color:{PIP_ACCENT};"
            f" border-bottom:2px solid {PIP_ACCENT}; }}"
            f"QTabWidget::pane {{ border:1px solid {PIP_BORDER};"
            f" background:{PIP_BG}; }}"
        )
        self._sub_tabs.addTab(self._build_sessions_panel(),   "▣  ACTIVE SESSIONS")
        self._sub_tabs.addTab(self._build_gallery_panel(),    "◐  ARTIFACT GALLERY")
        self._sub_tabs.addTab(self._build_queue_panel(),      "⌛  RENDER QUEUE")
        self._sub_tabs.addTab(self._build_preview_panel(),    "◳  PREVIEW WALL")
        self._sub_tabs.addTab(self._build_tool_panel(),       "⚒  TOOL FABRIC")
        self._sub_tabs.addTab(self._build_diagnostics_panel(),"☯  DIAGNOSTICS")
        # Hidden until trace mode toggles.
        self._sub_tabs.setVisible(False)
        root.addWidget(self._sub_tabs, 1)

        # Status strip is owned by the LaunchSurface — kept as a stub here
        # only so legacy `_set_status` / `_refresh_status_strip` paths don't
        # crash. They write to LaunchSurface._status indirectly.
        self._status_strip = QLabel("")
        self._status_strip.setVisible(False)
        root.addWidget(self._status_strip)

    def _btn_style(self, accent: str) -> str:
        return (
            f"QPushButton {{ background:{PIP_PANEL}; color:{accent};"
            f" border:1px solid {accent}; border-radius:4px;"
            f" padding:6px 14px; font-weight:bold; font-size:11px; }}"
            f"QPushButton:hover {{ background:{accent}; color:{PIP_BG}; }}"
        )

    # ── Sub-panels ────────────────────────────────────────────────────
    def _build_sessions_panel(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self._sessions_table = QTableWidget(0, 5)
        self._sessions_table.setHorizontalHeaderLabels(
            ["Session", "Realm", "State", "Artifacts", "Started"]
        )
        self._sessions_table.horizontalHeader().setStretchLastSection(True)
        self._sessions_table.verticalHeader().setVisible(False)
        self._sessions_table.setStyleSheet(self._table_style())
        v.addWidget(self._sessions_table)
        return w

    def _build_gallery_panel(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self._gallery_list = QListWidget()
        self._gallery_list.setStyleSheet(
            f"QListWidget {{ background:{PIP_BG}; color:{PIP_OK};"
            f" border:1px solid {PIP_BORDER};"
            f" font-family:Consolas,monospace; font-size:11px; }}"
            f"QListWidget::item:hover {{ background:{PIP_PANEL}; }}"
        )
        v.addWidget(self._gallery_list)
        return w

    def _build_queue_panel(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self._queue_table = QTableWidget(0, 5)
        self._queue_table.setHorizontalHeaderLabels(
            ["Refine ID", "Realm", "Pass", "Prev Score", "State"]
        )
        self._queue_table.horizontalHeader().setStretchLastSection(True)
        self._queue_table.verticalHeader().setVisible(False)
        self._queue_table.setStyleSheet(self._table_style())
        v.addWidget(self._queue_table)
        return w

    def _build_preview_panel(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self._preview_list = QListWidget()
        self._preview_list.setStyleSheet(
            f"QListWidget {{ background:{PIP_BG}; color:{PIP_ACCENT};"
            f" border:1px solid {PIP_BORDER};"
            f" font-family:Consolas,monospace; font-size:11px; }}"
            f"QListWidget::item:hover {{ background:{PIP_PANEL};"
            f" color:{PIP_OK}; }}"
        )
        v.addWidget(self._preview_list)
        return w

    def _build_tool_panel(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self._tools_table = QTableWidget(0, 4)
        self._tools_table.setHorizontalHeaderLabels(
            ["Tool", "Status", "Where", "Detail"]
        )
        self._tools_table.horizontalHeader().setStretchLastSection(True)
        self._tools_table.verticalHeader().setVisible(False)
        self._tools_table.setStyleSheet(self._table_style())
        v.addWidget(self._tools_table)
        # Hardware row at the bottom
        self._hw_label = QLabel("hardware probe pending…")
        self._hw_label.setStyleSheet(
            f"color:{PIP_DIM}; font-family:Consolas,monospace;"
            f" font-size:11px; padding:6px;"
        )
        v.addWidget(self._hw_label)
        return w

    def _build_diagnostics_panel(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self._diag_view = QPlainTextEdit()
        self._diag_view.setReadOnly(True)
        self._diag_view.setStyleSheet(
            f"QPlainTextEdit {{ background:{PIP_BG}; color:{PIP_OK};"
            f" border:1px solid {PIP_BORDER};"
            f" font-family:Consolas,monospace; font-size:11px;"
            f" padding:8px; }}"
        )
        v.addWidget(self._diag_view)
        return w

    def _table_style(self) -> str:
        return (
            f"QTableWidget {{ background:{PIP_BG}; color:{PIP_OK};"
            f" gridline-color:{PIP_BORDER};"
            f" font-family:Consolas,monospace; font-size:11px; }}"
            f"QHeaderView::section {{ background:{PIP_PANEL};"
            f" color:{PIP_ACCENT}; border:1px solid {PIP_BORDER};"
            f" padding:4px; font-weight:bold; }}"
            f"QTableWidget::item:selected {{ background:{PIP_PANEL}; }}"
        )

    # ── BUILD-024: trace mode ─────────────────────────────────────────
    def _toggle_trace_mode(self) -> None:
        self._trace_mode = not self._trace_mode
        self._apply_mode()

    def _apply_mode(self) -> None:
        """When trace_mode is True, reveal the sub-tabs panel + start
        the polling timer. When False, hide them and stop polling."""
        try:
            self._sub_tabs.setVisible(self._trace_mode)
        except Exception:
            pass
        try:
            if self._trace_mode:
                self._timer.start()
                QTimer.singleShot(100, self._refresh_all)
            else:
                self._timer.stop()
        except Exception:
            pass

    # ── Intent dispatch (legacy — kept for back-compat callers) ──────
    def _dispatch_intent(self) -> None:
        """Legacy entry — LaunchSurface owns intent submission now."""
        try:
            self._launch_surface._on_submit()
        except Exception:
            pass

    # ── Refresh ───────────────────────────────────────────────────────
    def _refresh_all(self) -> None:
        try:
            self._refresh_sessions()
        except Exception as e:
            _log.debug("sessions refresh failed: %s", e)
        try:
            self._refresh_gallery()
        except Exception as e:
            _log.debug("gallery refresh failed: %s", e)
        try:
            self._refresh_queue()
        except Exception as e:
            _log.debug("queue refresh failed: %s", e)
        try:
            self._refresh_previews()
        except Exception as e:
            _log.debug("previews refresh failed: %s", e)
        try:
            self._refresh_tools()
        except Exception as e:
            _log.debug("tools refresh failed: %s", e)
        try:
            self._refresh_diagnostics()
        except Exception as e:
            _log.debug("diagnostics refresh failed: %s", e)
        try:
            self._refresh_status_strip()
        except Exception as e:
            _log.debug("status strip refresh failed: %s", e)

    def _refresh_sessions(self) -> None:
        try:
            from engine.production_core import get_production_core
            core = get_production_core()
            with core._lock:
                sessions = list(core._sessions.values())
        except Exception:
            sessions = []
        sessions.sort(key=lambda s: -s.started_at)
        sessions = sessions[:50]
        self._sessions_table.setRowCount(len(sessions))
        for i, s in enumerate(sessions):
            self._sessions_table.setItem(i, 0, QTableWidgetItem(s.session_id))
            self._sessions_table.setItem(i, 1, QTableWidgetItem(s.realm))
            state_item = QTableWidgetItem(s.state)
            state_item.setForeground(QColor(self._state_color(s.state)))
            self._sessions_table.setItem(i, 2, state_item)
            self._sessions_table.setItem(i, 3,
                QTableWidgetItem(str(len(s.artifacts))))
            self._sessions_table.setItem(i, 4,
                QTableWidgetItem(time.strftime("%H:%M:%S",
                                                time.localtime(s.started_at))))

    def _refresh_gallery(self) -> None:
        try:
            from engine.artifact_lineage import get_artifact_lineage
            lin = get_artifact_lineage()
            artifacts = lin.recent(80)
        except Exception:
            artifacts = []
        self._gallery_list.clear()
        for a in reversed(artifacts):
            name = Path(a.path).name
            line = (f"[{a.realm}] {name}  ·  {a.backend}  ·  "
                    f"{a.size_bytes/1024:.1f} KB  ·  "
                    f"{a.sha256[:12] if a.sha256 else 'no-sha'}")
            item = QListWidgetItem(line)
            item.setToolTip(a.path)
            self._gallery_list.addItem(item)

    def _refresh_queue(self) -> None:
        try:
            from engine.quality_gate import get_quality_gate
            qg = get_quality_gate()
            with qg._lock:
                entries = list(qg._queue) + qg.recent_history(20)
        except Exception:
            entries = []
        self._queue_table.setRowCount(len(entries))
        for i, e in enumerate(entries):
            if hasattr(e, "refine_id"):
                rid = e.refine_id
                realm = e.worker_realm
                passn = e.pass_number
                prev = e.previous_score
                state = e.state
            else:
                rid = e.get("refine_id", "")
                realm = e.get("realm", "")
                passn = e.get("pass_number", "")
                prev = e.get("prev_score", 0.0)
                state = e.get("new_state", "DONE")
            self._queue_table.setItem(i, 0, QTableWidgetItem(rid))
            self._queue_table.setItem(i, 1, QTableWidgetItem(realm))
            self._queue_table.setItem(i, 2, QTableWidgetItem(str(passn)))
            self._queue_table.setItem(i, 3,
                QTableWidgetItem(f"{prev:.2f}" if isinstance(prev, (int, float)) else str(prev)))
            state_item = QTableWidgetItem(str(state))
            state_item.setForeground(QColor(self._state_color(str(state))))
            self._queue_table.setItem(i, 4, state_item)

    def _refresh_previews(self) -> None:
        try:
            from engine.preview_registry import get_preview_registry
            previews = get_preview_registry().recent(60)
        except Exception:
            previews = []
        self._preview_list.clear()
        for prev in previews:
            name = Path(prev.artifact_path).name
            line = f"[{prev.realm}] {prev.preview_kind}  ·  {name}  ·  {prev.backend}"
            item = QListWidgetItem(line)
            item.setToolTip(prev.preview_path or prev.artifact_path)
            self._preview_list.addItem(item)

    def _refresh_tools(self) -> None:
        try:
            from runtime.singleton_registry import get_registry
            tf = get_registry().get("engine.tool_fabric")
            snap = tf.snapshot() if tf is not None else {}
        except Exception:
            snap = {}
        rows = sorted(snap.items())
        self._tools_table.setRowCount(len(rows))
        for i, (name, entry) in enumerate(rows):
            self._tools_table.setItem(i, 0, QTableWidgetItem(name))
            status_item = QTableWidgetItem(entry.get("status", "?"))
            status_item.setForeground(QColor(self._state_color(entry.get("status", ""))))
            self._tools_table.setItem(i, 1, status_item)
            self._tools_table.setItem(i, 2,
                QTableWidgetItem((entry.get("path") or "")[:80]))
            detail = entry.get("detail", "") or entry.get("remediation", "")
            self._tools_table.setItem(i, 3, QTableWidgetItem(detail[:120]))

        # Hardware row
        try:
            from engine.production_tool_fabric import get_production_tool_fabric
            ptf = get_production_tool_fabric()
            hw = ptf.hardware()
            if hw is None:
                self._hw_label.setText("hardware probe pending…")
            else:
                self._hw_label.setText(
                    f"CPU:{hw.cpu_count}  RAM:{hw.ram_mb_total} MB  "
                    f"GPU:{hw.gpu_name or 'none'}  VRAM:{hw.vram_mb_total} MB  "
                    f"CUDA:{hw.cuda_available}"
                )
        except Exception as e:
            self._hw_label.setText(f"hw probe error: {e}")

    def _refresh_diagnostics(self) -> None:
        try:
            from engine.diagnostics_layer import get_diagnostics
            report = get_diagnostics().report()
        except Exception as e:
            self._diag_view.setPlainText(f"diagnostics unavailable: {e}")
            return
        lines: list[str] = []
        lines.append(f"DIAGNOSTICS · {time.strftime('%H:%M:%S')}  "
                     f"({round(report.get('duration_ms', 0), 1)} ms)")
        lines.append("")
        for section in ("maintenance", "convergence", "constraints",
                         "tool_fabric", "workspace", "engine",
                         "cognitive_core", "simulation",
                         "media_generation", "adaptive"):
            s = report.get(section, {})
            avail = s.get("available", False) if isinstance(s, dict) else False
            sym = "✓" if avail else "·"
            lines.append(f"  {sym} {section}")
            if avail and isinstance(s, dict):
                snap = s.get("snapshot") or s.get("stats") or s.get("status") or {}
                if isinstance(snap, dict):
                    for k, v in list(snap.items())[:6]:
                        lines.append(f"      {k}: {v}")
        self._diag_view.setPlainText("\n".join(lines))

    def _refresh_status_strip(self) -> None:
        bits: list[str] = []
        try:
            from engine.production_core import get_production_core
            core = get_production_core()
            stats = core.stats()
            bits.append(f"sessions:{stats['total_sessions']}")
            bits.append(f"in_flight:{stats['in_flight_per_realm']}")
        except Exception:
            pass
        try:
            from engine.artifact_lineage import get_artifact_lineage
            ls = get_artifact_lineage().stats()
            bits.append(f"artifacts:{ls['recent_count']}({ls['total_bytes']//1024} KB)")
        except Exception:
            pass
        try:
            from engine.quality_gate import get_quality_gate
            qs = get_quality_gate().stats()
            bits.append(f"refinements:{qs['queued']}/{qs['dispatched']}/{qs['done']}")
        except Exception:
            pass
        try:
            from engine.preview_registry import get_preview_registry
            ps = get_preview_registry().stats()
            bits.append(f"previews:{ps['count']}")
        except Exception:
            pass
        self._status_strip.setText("  ·  ".join(bits) or "…")

    def _set_status(self, msg: str) -> None:
        self._status_strip.setText(msg)

    # ── Color helpers ─────────────────────────────────────────────────
    def _state_color(self, state: str) -> str:
        s = state.upper()
        if s in ("READY", "OK", "DONE"):       return PIP_OK
        if s in ("RUNNING", "EXECUTING",
                  "DISPATCHED", "QUEUED"):       return PIP_ACCENT
        if s in ("DEGRADED",):                  return PIP_WARN
        if s in ("FAIL", "FAILED", "ABANDONED"): return PIP_FAIL
        if s in ("UNAVAILABLE", "REFINING"):    return PIP_HOT
        return PIP_DIM
