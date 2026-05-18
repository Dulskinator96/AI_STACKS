"""ui/maintenance_panel.py — 🛡 Maintenance tab.

Surfaces the bounded maintenance layer as a first-class UI:

    * live table of detected issues (observer / tier / severity / kind / surface
      / confidence / status)
    * "Diagnose now" button → forces a one-shot runtime tick
    * per-row "Apply Fix" button — auto-fix via RepairCoordinator for T1/T2 only
    * per-row "Copy PowerShell" button — emits a safe diagnose/repair snippet
      to the clipboard for the user to run in a terminal
    * restriction banner reflecting DriftMonitor's auto-reduction of authority

UI is a pure View per CLAUDE.md §5: no requests / sqlite / subprocess /
Path calls except through the maintenance layer's bounded surface.
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Deque, List, Optional

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QPlainTextEdit, QFrame,
    QSizePolicy, QMessageBox,
)

from maintenance import (
    Issue, Tier, RepairCoordinator, MaintenanceRuntime, REPAIR_ALLOW_LIST,
    RepairOutcome,
)
from maintenance.ps_advisor import format_for_clipboard

_log = logging.getLogger(__name__)


_TIER_COLOR = {
    "T1_COSMETIC":     QColor("#3a8fc8"),
    "T2_OPERATIONAL":  QColor("#f0a030"),
    "T3_LOGIC":        QColor("#6040b8"),
    "T4_SUBSTRATE":    QColor("#c04868"),
}


class MaintenancePanel(QWidget):
    """🛡 MAINTENANCE — autonomous detection · click-to-fix · PowerShell fallback."""

    issue_applied = pyqtSignal(str, str)   # (issue_id, outcome)

    HEADERS = ["Observer", "Tier", "Severity", "Kind", "Surface",
               "Confidence", "Hint", "Status"]

    def __init__(self, coordinator: RepairCoordinator,
                 runtime: MaintenanceRuntime, parent=None):
        super().__init__(parent)
        self._coordinator = coordinator
        self._runtime = runtime
        self._issues: List[Issue] = []
        # User-initiated apply outcomes — merged with runtime outcomes so the
        # table reflects click-to-fix results immediately (the bg ticker only
        # observes; it doesn't surface manually-driven repairs).
        self._user_outcomes: Deque[RepairOutcome] = deque(maxlen=32)
        self._build_ui()
        self._build_timer()

    # ── construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        header = QHBoxLayout()
        title = QLabel("🛡  MAINTENANCE")
        title.setStyleSheet("color: #cce0f0; font-weight: bold; font-size: 14px;")
        header.addWidget(title)
        header.addStretch()
        self._diagnose_btn = QPushButton("Diagnose now")
        self._diagnose_btn.clicked.connect(self._on_diagnose)
        header.addWidget(self._diagnose_btn)
        root.addLayout(header)

        self._banner = QLabel("")
        self._banner.setVisible(False)
        self._banner.setStyleSheet(
            "background: #c04868; color: #fff; padding: 4px 8px; border-radius: 4px;"
        )
        root.addWidget(self._banner)

        self._table = QTableWidget(0, len(self.HEADERS))
        self._table.setHorizontalHeaderLabels(self.HEADERS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(self._table.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(self._table.EditTrigger.NoEditTriggers)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self._table, 3)

        action_row = QHBoxLayout()
        self._apply_btn = QPushButton("Apply Fix to Selected")
        self._apply_btn.clicked.connect(self._on_apply_selected)
        self._copy_btn = QPushButton("Copy PowerShell for Selected")
        self._copy_btn.clicked.connect(self._on_copy_powershell)
        action_row.addWidget(self._apply_btn)
        action_row.addWidget(self._copy_btn)
        action_row.addStretch()
        self._status_label = QLabel("0 issues")
        self._status_label.setStyleSheet("color: #5070a0;")
        action_row.addWidget(self._status_label)
        root.addLayout(action_row)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color: #1e2e5c;")
        root.addWidget(divider)

        det_label = QLabel("Diagnose / Repair preview")
        det_label.setStyleSheet("color: #5070a0;")
        root.addWidget(det_label)
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setPlaceholderText(
            "Select a row to see diagnose / repair commands. "
            "Use 'Apply Fix to Selected' for bounded auto-repair, or "
            "'Copy PowerShell for Selected' to take a manual action."
        )
        self._preview.setStyleSheet(
            "background: #06091c; color: #cce0f0; font-family: Consolas;"
        )
        root.addWidget(self._preview, 2)

        self._table.itemSelectionChanged.connect(self._on_selection_changed)

    def _build_timer(self) -> None:
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(2000)  # 2s UI refresh
        self._tick_timer.timeout.connect(self._refresh_from_runtime)
        self._tick_timer.start()

    # ── data refresh ───────────────────────────────────────────────────────

    def _refresh_from_runtime(self) -> None:
        # Merge runtime tick outcomes with user-initiated apply outcomes.
        # Most-recent-wins on duplicate issue_id, so a manual Apply always
        # overrides the older runtime-observed status.
        merged: dict[str, RepairOutcome] = {}
        for o in self._runtime.last_outcomes:
            merged[o.issue.issue_id] = o
        for o in self._user_outcomes:
            merged[o.issue.issue_id] = o
        outcomes = list(merged.values())
        issues = [o.issue for o in outcomes]
        statuses = {o.issue.issue_id: o.receipt.outcome for o in outcomes}
        self._issues = issues
        self._render_table(statuses)
        self._render_banner()
        self._status_label.setText(f"{len(issues)} issue(s)  ·  tick {self._runtime.tick_count}")

    def _render_banner(self) -> None:
        if self._coordinator.restricted:
            self._banner.setText(
                "⚠  RepairCoordinator RESTRICTED by DriftMonitor — "
                "auto-apply suspended. Manual PowerShell still available."
            )
            self._banner.setVisible(True)
        else:
            self._banner.setVisible(False)

    def _render_table(self, statuses: dict) -> None:
        self._table.setRowCount(len(self._issues))
        for row, issue in enumerate(self._issues):
            cells = [
                issue.observer,
                issue.tier.value,
                issue.severity.value,
                issue.kind,
                issue.surface,
                f"{issue.confidence:.2f}",
                issue.repair_hint or "—",
                statuses.get(issue.issue_id, "?"),
            ]
            for col, val in enumerate(cells):
                it = QTableWidgetItem(str(val))
                if col == 1:
                    c = _TIER_COLOR.get(val)
                    if c is not None:
                        it.setForeground(c)
                self._table.setItem(row, col, it)

    # ── slots ──────────────────────────────────────────────────────────────

    def _on_diagnose(self) -> None:
        self._runtime.tick_once()
        self._refresh_from_runtime()

    def _selected_issue(self) -> Optional[Issue]:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        idx = rows[0].row()
        if 0 <= idx < len(self._issues):
            return self._issues[idx]
        return None

    def _on_selection_changed(self) -> None:
        issue = self._selected_issue()
        if issue is None:
            self._preview.clear()
            return
        self._preview.setPlainText(format_for_clipboard(issue))

    def _on_apply_selected(self) -> None:
        issue = self._selected_issue()
        if issue is None:
            return
        if issue.tier not in (Tier.T1, Tier.T2):
            QMessageBox.information(
                self, "Auto-apply not allowed",
                f"This issue is {issue.tier.value}. The coordinator will not "
                f"auto-apply T3/T4. Use 'Copy PowerShell' instead.",
            )
            return
        if issue.repair_hint not in REPAIR_ALLOW_LIST:
            QMessageBox.information(
                self, "No bounded repair",
                f"No allow-listed repair for hint='{issue.repair_hint}'. "
                f"Use 'Copy PowerShell' for a manual fix.",
            )
            return
        outcome = self._coordinator.handle(issue)
        self._user_outcomes.append(outcome)
        self.issue_applied.emit(issue.issue_id, outcome.receipt.outcome)
        self._refresh_from_runtime()

    def _on_copy_powershell(self) -> None:
        issue = self._selected_issue()
        if issue is None:
            return
        snippet = format_for_clipboard(issue)
        cb = QGuiApplication.clipboard()
        cb.setText(snippet)
        self._status_label.setText(
            f"Copied PowerShell for {issue.issue_id} ({len(snippet)} bytes)"
        )
