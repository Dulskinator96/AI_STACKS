"""ui/ops_dashboard.py — Live operational state panel.

Surfaces the operational state of DBOMBLOCAL as a single readable Qt panel:

    * System state badge (current SystemState)
    * Boot timing card (newest telemetry/boot_profile_*.json)
    * Stability gauge (maintenance.evaluate_stability)
    * Repair history (maintenance.analyze_history, 15-minute window)
    * State transition log (last 10 from get_state_manager().history())

Pure View per CLAUDE.md §5: no direct sqlite / requests / subprocess. All
subsystem reads are wrapped — this widget NEVER raises on a degraded read,
it shows "unavailable" / "—" instead. Auto-refreshes on a 3-second QTimer.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

_log = logging.getLogger(__name__)


# ── theme (matches maintenance_panel.py) ──────────────────────────────────
_BG = "#06091c"
_FG = "#cce0f0"
_FG_DIM = "#5070a0"
_BORDER = "#1e2e5c"
_GREEN = "#18b896"
_ORANGE = "#f0a030"
_RED = "#c04868"

_STATE_COLOR = {
    "BOOT": "#3a8fc8",
    "INIT": "#3a8fc8",
    "VALIDATING": "#f0a030",
    "LOADING_MODULES": "#f0a030",
    "STARTING_AGENTS": "#f0a030",
    "READY": "#18b896",
    "EXECUTING": "#18b896",
    "ERROR_RECOVERY": "#c04868",
    "SHUTDOWN": "#5070a0",
}

_AUTHORITY_COLOR = {
    "FULL": "#18b896",
    "REDUCED": "#f0a030",
    "SUSPENDED": "#d88040",
    "QUARANTINE": "#c04868",
}


def _card_frame() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.StyledPanel)
    f.setStyleSheet(
        f"QFrame {{ background: {_BG}; color: {_FG}; "
        f"border: 1px solid {_BORDER}; border-radius: 4px; }}"
    )
    return f


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {_FG_DIM}; font-weight: bold; font-size: 11px;")
    return lbl


class OpsDashboardPanel(QWidget):
    """Operational dashboard — is the system alive and well? A pure View."""

    HISTORY_HEADERS = ["Kind", "Surface", "Occurrences", "Success Rate"]
    TRANSITION_HEADERS = ["Time", "From → To", "Reason"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {_BG}; color: {_FG};")
        self._build_ui()
        self._build_timer()
        self.refresh()

    # ── construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Header
        header = QHBoxLayout()
        title = QLabel("OPS DASHBOARD")
        title.setStyleSheet(f"color: {_FG}; font-weight: bold; font-size: 14px;")
        header.addWidget(title)
        header.addStretch()
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self._refresh_btn)
        root.addLayout(header)

        # 1. System state row
        root.addWidget(_section_label("SYSTEM STATE"))
        state_row = QHBoxLayout()
        self._state_badge = QLabel("—")
        self._state_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._state_badge.setMinimumWidth(180)
        self._state_badge.setStyleSheet(
            f"background: {_FG_DIM}; color: {_BG}; "
            f"padding: 6px 12px; border-radius: 4px; font-weight: bold;"
        )
        state_row.addWidget(self._state_badge)
        state_row.addStretch()
        root.addLayout(state_row)

        # 2. Boot timing card
        root.addWidget(_section_label("BOOT TIMING (newest profile)"))
        self._boot_label = QLabel("—")
        self._boot_label.setStyleSheet(
            f"background: {_BG}; color: {_FG}; border: 1px solid {_BORDER}; "
            f"padding: 6px 10px; border-radius: 4px; font-family: Consolas;"
        )
        self._boot_label.setWordWrap(True)
        root.addWidget(self._boot_label)

        # 3. Stability gauge
        root.addWidget(_section_label("STABILITY"))
        stab_row = QHBoxLayout()
        self._stability_bar = QProgressBar()
        self._stability_bar.setRange(0, 100)
        self._stability_bar.setValue(0)
        self._stability_bar.setTextVisible(True)
        self._stability_bar.setFormat("score %p%")
        stab_row.addWidget(self._stability_bar, 3)
        self._authority_badge = QLabel("—")
        self._authority_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._authority_badge.setMinimumWidth(140)
        self._authority_badge.setStyleSheet(
            f"background: {_FG_DIM}; color: {_BG}; "
            f"padding: 4px 8px; border-radius: 4px; font-weight: bold;"
        )
        stab_row.addWidget(self._authority_badge, 1)
        root.addLayout(stab_row)
        self._reasons_label = QLabel("")
        self._reasons_label.setWordWrap(True)
        self._reasons_label.setStyleSheet(f"color: {_FG_DIM}; font-size: 10px;")
        root.addWidget(self._reasons_label)

        # 4. Repair history
        root.addWidget(_section_label("REPAIR HISTORY (15-minute window)"))
        self._history_summary = QLabel("—")
        self._history_summary.setStyleSheet(f"color: {_FG}; font-family: Consolas;")
        root.addWidget(self._history_summary)
        self._history_table = QTableWidget(0, len(self.HISTORY_HEADERS))
        self._history_table.setHorizontalHeaderLabels(self.HISTORY_HEADERS)
        self._history_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._history_table.verticalHeader().setVisible(False)
        self._history_table.setEditTriggers(self._history_table.EditTrigger.NoEditTriggers)
        self._history_table.setMaximumHeight(160)
        self._history_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        root.addWidget(self._history_table)

        # 5. State transition log
        root.addWidget(_section_label("STATE TRANSITIONS (last 10)"))
        self._transition_table = QTableWidget(0, len(self.TRANSITION_HEADERS))
        self._transition_table.setHorizontalHeaderLabels(self.TRANSITION_HEADERS)
        self._transition_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._transition_table.verticalHeader().setVisible(False)
        self._transition_table.setEditTriggers(
            self._transition_table.EditTrigger.NoEditTriggers
        )
        self._transition_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self._transition_table, 1)

        # Footer status
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {_FG_DIM}; font-size: 10px;")
        root.addWidget(self._status_label)

    def _build_timer(self) -> None:
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    # ── refresh ────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        self._refresh_state()
        self._refresh_boot()
        self._refresh_stability()
        self._refresh_history()
        self._refresh_transitions()
        try:
            import time as _t

            self._status_label.setText(
                f"refreshed {_t.strftime('%H:%M:%S', _t.localtime())}"
            )
        except Exception:
            pass

    # 1. system state
    def _refresh_state(self) -> None:
        try:
            from core.state_manager import get_state_manager

            current = get_state_manager().current
            name = getattr(current, "value", str(current))
        except Exception as e:
            _log.debug("ops_dashboard: state read failed: %s", e)
            name = "unavailable"
        color = _STATE_COLOR.get(name, _FG_DIM)
        self._state_badge.setText(name)
        self._state_badge.setStyleSheet(
            f"background: {color}; color: {_BG}; "
            f"padding: 6px 12px; border-radius: 4px; font-weight: bold;"
        )

    # 2. boot timing
    def _refresh_boot(self) -> None:
        try:
            from omega.paths import telemetry_root
            tel_dir = telemetry_root()
            candidates = sorted(tel_dir.glob("boot_profile_*.json"))
            if not candidates:
                self._boot_label.setText("No boot profile captured yet.")
                return
            newest = candidates[-1]
            data = json.loads(newest.read_text(encoding="utf-8"))
            cti = data.get("click_to_interactive_ms")
            rss = data.get("peak_rss_mb")
            phases = data.get("phase_count")
            t0 = data.get("t0_wall_iso", "—")
            cti_s = f"{cti:.1f} ms" if isinstance(cti, (int, float)) else "—"
            rss_s = f"{rss:.1f} MB" if isinstance(rss, (int, float)) else "—"
            self._boot_label.setText(
                f"file: {newest.name}\n"
                f"t0_wall_iso: {t0}\n"
                f"click_to_interactive_ms: {cti_s}    "
                f"peak_rss_mb: {rss_s}    "
                f"phase_count: {phases if phases is not None else '—'}"
            )
        except Exception as e:
            _log.debug("ops_dashboard: boot profile read failed: %s", e)
            self._boot_label.setText("Boot profile unavailable.")

    # 3. stability
    def _refresh_stability(self) -> None:
        try:
            from maintenance import evaluate_stability

            rep = evaluate_stability()
            score = float(getattr(rep, "overall_score", 0.0))
            authority = getattr(rep.recommended_authority, "value",
                                 str(rep.recommended_authority))
            reasons = list(getattr(rep, "reasons", ()) or ())
        except Exception as e:
            _log.debug("ops_dashboard: stability read failed: %s", e)
            self._stability_bar.setValue(0)
            self._stability_bar.setFormat("unavailable")
            self._authority_badge.setText("—")
            self._authority_badge.setStyleSheet(
                f"background: {_FG_DIM}; color: {_BG}; "
                f"padding: 4px 8px; border-radius: 4px; font-weight: bold;"
            )
            self._reasons_label.setText("")
            return

        pct = int(round(score * 100))
        self._stability_bar.setValue(pct)
        self._stability_bar.setFormat(f"score {pct}%")
        if score > 0.8:
            bar_color = _GREEN
        elif score > 0.55:
            bar_color = _ORANGE
        else:
            bar_color = _RED
        self._stability_bar.setStyleSheet(
            f"QProgressBar {{ background: {_BG}; color: {_FG}; "
            f"border: 1px solid {_BORDER}; border-radius: 3px; text-align: center; }} "
            f"QProgressBar::chunk {{ background: {bar_color}; border-radius: 2px; }}"
        )
        self._authority_badge.setText(authority)
        a_color = _AUTHORITY_COLOR.get(authority, _FG_DIM)
        self._authority_badge.setStyleSheet(
            f"background: {a_color}; color: {_BG}; "
            f"padding: 4px 8px; border-radius: 4px; font-weight: bold;"
        )
        if reasons:
            self._reasons_label.setText("reasons: " + "; ".join(str(r) for r in reasons))
        else:
            self._reasons_label.setText("reasons: (none)")

    # 4. repair history
    def _refresh_history(self) -> None:
        try:
            from maintenance import analyze_history

            rep = analyze_history(window_seconds=900)
            total = int(getattr(rep, "total_receipts", 0))
            applied = int(getattr(rep, "applied_count", 0))
            unresolved = int(getattr(rep, "unresolved_count", 0))
            clusters = list(getattr(rep, "clusters", []) or [])[:5]
        except Exception as e:
            _log.debug("ops_dashboard: history read failed: %s", e)
            self._history_summary.setText("Repair history unavailable.")
            self._history_table.setRowCount(0)
            return

        self._history_summary.setText(
            f"total_receipts: {total}    applied: {applied}    unresolved: {unresolved}"
        )
        self._history_table.setRowCount(len(clusters))
        for row, c in enumerate(clusters):
            try:
                kind = str(getattr(c, "issue_kind", "—"))
                surface = str(getattr(c, "surface", "—"))
                occ = int(getattr(c, "occurrences", 0))
                rate = float(getattr(c, "success_rate", 0.0))
            except Exception:
                kind, surface, occ, rate = "—", "—", 0, 0.0
            cells = [kind, surface, str(occ), f"{rate:.2f}"]
            for col, val in enumerate(cells):
                item = QTableWidgetItem(val)
                if col == 3:
                    if rate >= 0.8:
                        item.setForeground(QColor(_GREEN))
                    elif rate >= 0.5:
                        item.setForeground(QColor(_ORANGE))
                    else:
                        item.setForeground(QColor(_RED))
                self._history_table.setItem(row, col, item)

    # 5. transitions
    def _refresh_transitions(self) -> None:
        try:
            from core.state_manager import get_state_manager

            transitions = list(get_state_manager().history())[-10:]
        except Exception as e:
            _log.debug("ops_dashboard: transitions read failed: %s", e)
            self._transition_table.setRowCount(0)
            return

        self._transition_table.setRowCount(len(transitions))
        import time as _t

        for row, tr in enumerate(transitions):
            try:
                ts = float(getattr(tr, "timestamp", 0.0))
                ts_s = _t.strftime("%H:%M:%S", _t.localtime(ts)) if ts else "—"
                f_state = getattr(tr, "from_state", None)
                t_state = getattr(tr, "to_state", None)
                f_name = getattr(f_state, "value", str(f_state))
                t_name = getattr(t_state, "value", str(t_state))
                arrow = f"{f_name} → {t_name}"
                reason = str(getattr(tr, "reason", "") or "")
            except Exception:
                ts_s, arrow, reason = "—", "—", ""
            for col, val in enumerate([ts_s, arrow, reason]):
                self._transition_table.setItem(row, col, QTableWidgetItem(val))
