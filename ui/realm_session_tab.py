"""ui/realm_session_tab.py — BUILD-018 RULE 5: dynamic workspace projection.

A single-purpose tab spawned by DynamicWorkspaceSpawner. Holds:
  · the intent that spawned it
  · the orchestrated ExecutionPlan (rendered read-only)
  · a worker-driven log pane
  · Return-to-Chamber + Close buttons

The tab is isolated from global UI lifecycle — closing it doesn't perturb
the boot tabs. Its worker (if any) honors WorkspaceSession.cancel.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

_log = logging.getLogger(__name__)


REALM_GLYPHS = {
    "video":  "▶",
    "audio":  "♪",
    "image":  "◐",
    "game":   "◇",
    "code":   "⚒",
    "cast":   "✦",
}


class RealmSessionTab(QWidget):
    """Render surface for one WorkspaceSession."""

    log_appended = pyqtSignal(str)
    closed = pyqtSignal(str)        # session_id

    def __init__(self, session, dashboard, parent=None):
        super().__init__(parent)
        self._session = session
        self._dashboard = dashboard
        self._build_ui()
        self.log_appended.connect(self._log_view.appendPlainText)
        # Replay any log lines already captured
        for ln in list(session.log_lines):
            self._log_view.appendPlainText(ln)
        # Drain new lines from the session log every 500ms
        self._tail_timer = QTimer(self)
        self._tail_timer.setInterval(500)
        self._tail_timer.timeout.connect(self._drain_session_log)
        self._tail_timer.start()
        self._last_log_index = len(session.log_lines)

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        glyph = REALM_GLYPHS.get(self._session.realm, "◈")
        banner = QFrame()
        banner.setStyleSheet(
            "QFrame { background:#1a0e3e; border:2px solid #ff2d92;"
            " border-radius:6px; padding:8px; }"
        )
        bl = QHBoxLayout(banner)
        title = QLabel(f"{glyph}  {self._session.realm.upper()}  ·  {self._session.session_id}")
        title.setStyleSheet("color:#ffce28; font-weight:bold; font-size:13px; letter-spacing:2px;")
        bl.addWidget(title)
        bl.addStretch()
        v.addWidget(banner)

        intent_lbl = QLabel(self._session.intent or "(no intent)")
        intent_lbl.setStyleSheet("color:#fff5e0; font-size:12px; padding:4px;")
        intent_lbl.setWordWrap(True)
        v.addWidget(intent_lbl)

        # Plan render
        if self._session.plan is not None:
            plan_text = self._render_plan(self._session.plan)
            plan_view = QPlainTextEdit()
            plan_view.setPlainText(plan_text)
            plan_view.setReadOnly(True)
            plan_view.setMaximumHeight(140)
            plan_view.setStyleSheet(
                "QPlainTextEdit { background:#06091c; color:#28e6ff;"
                " border:1px solid #1e2e5c; border-radius:4px;"
                " font-family:Consolas,monospace; font-size:11px; padding:6px; }"
            )
            v.addWidget(plan_view)

        # Log pane (worker output)
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setStyleSheet(
            "QPlainTextEdit { background:#0a0420; color:#5af26f;"
            " border:1px solid #ff2d92; border-radius:5px;"
            " font-family:Consolas,monospace; font-size:11px; padding:8px; }"
        )
        v.addWidget(self._log_view, 1)

        # Action row
        row = QHBoxLayout()
        ret_btn = QPushButton("⌂  RETURN TO CHAMBER")
        ret_btn.setStyleSheet(
            "QPushButton { background:#162048; color:#28e6ff;"
            " border:1px solid #1e2e5c; border-radius:4px;"
            " padding:6px 14px; font-weight:bold; font-size:11px; }"
            "QPushButton:hover { background:#1e2e5c; }"
        )
        ret_btn.clicked.connect(self._return_to_chamber)
        row.addWidget(ret_btn)
        row.addStretch()
        cancel_btn = QPushButton("⌧  CANCEL WORKER")
        cancel_btn.setStyleSheet(
            "QPushButton { background:#2a1820; color:#f0a030;"
            " border:1px solid #c04868; border-radius:4px;"
            " padding:6px 14px; font-weight:bold; font-size:11px; }"
            "QPushButton:hover { background:#3a2030; color:#fff; }"
        )
        cancel_btn.clicked.connect(self._cancel_worker)
        row.addWidget(cancel_btn)
        close_btn = QPushButton("✕  CLOSE")
        close_btn.setStyleSheet(
            "QPushButton { background:#2a1820; color:#c04868;"
            " border:1px solid #c04868; border-radius:4px;"
            " padding:6px 14px; font-weight:bold; font-size:11px; }"
            "QPushButton:hover { background:#c04868; color:#fff; }"
        )
        close_btn.clicked.connect(self._close_self)
        row.addWidget(close_btn)
        v.addLayout(row)

    def _render_plan(self, plan: Any) -> str:
        try:
            from kernel.intent_orchestrator import render_plan
            return render_plan(plan)
        except Exception:
            return str(plan)

    # ── Slots ────────────────────────────────────────────────────────
    def _drain_session_log(self) -> None:
        try:
            n = len(self._session.log_lines)
            if n > self._last_log_index:
                for ln in self._session.log_lines[self._last_log_index:n]:
                    self._log_view.appendPlainText(ln)
                self._last_log_index = n
        except Exception:
            pass

    def _return_to_chamber(self) -> None:
        try:
            from runtime.singleton_registry import get_registry
            reg = get_registry()
            wf = getattr(reg.get("ui.dashboard"), "_workspace_factory", None)
            if wf is None:
                return
            ci = wf.name_to_index("PyramidChamber")
            if ci is not None:
                dash = reg.get("ui.dashboard")
                if dash is not None and hasattr(dash, "tabs"):
                    dash.tabs.setCurrentIndex(ci)
        except Exception as e:
            _log.debug("return-to-chamber failed: %s", e)

    def _cancel_worker(self) -> None:
        try:
            self._session.cancel.set()
            self._log_view.appendPlainText("[cancel] requested — worker may detach")
        except Exception:
            pass

    def _close_self(self) -> None:
        try:
            from runtime.singleton_registry import get_registry
            from runtime.workspace_spawner import get_workspace_spawner
            dash = get_registry().get("ui.dashboard")
            spawner = get_workspace_spawner()
            spawner.close(self._session.session_id)
            if dash is not None and hasattr(dash, "_close_dynamic_workspace"):
                dash._close_dynamic_workspace(self._session.session_id)
            self.closed.emit(self._session.session_id)
        except Exception as e:
            _log.debug("close-self failed: %s", e)

    @property
    def session(self):
        return self._session
