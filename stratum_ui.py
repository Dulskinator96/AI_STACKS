"""
stratum_ui.py — STRATUM intent-driven interactive UI.

Clean, async PyQt6 interface.  All pipeline work runs on background threads.
Main thread only handles UI updates (never blocks).

Layout:
  ┌─────────────────────────────────────────────────┐
  │  [query input]              [Run]  [Dry Run]     │
  ├──────────────────┬──────────────────────────────┤
  │  INTENT          │  PROPOSAL (JSON)              │
  │  class / targets │  changes list + summary       │
  │  constraints     │  [Approve] [Reject] [Rollback]│
  ├──────────────────┴──────────────────────────────┤
  │  OUTPUT / LOG                                    │
  └─────────────────────────────────────────────────┘
"""
from __future__ import annotations

import json
import os
import sys
from typing import Optional

from PyQt6.QtCore import (
    QObject,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QKeySequence,
    QPalette,
    QShortcut,
    QTextCharFormat,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from stratum_pipeline import (
    PipelineEvent,
    PipelineRun,
    PipelineStage,
    get_pipeline,
)

try:
    from pyramid_ui import PyramidWidget as _PyramidWidget
    _PYRAMID_AVAILABLE = True
except ImportError:
    _PYRAMID_AVAILABLE = False

# ── Palette — Pre-Dawn Nautical Twilight ──────────────────────────────────────

BG       = "#06091c"   # deep navy — dark with blue presence (ref: #051545)
BG2      = "#0a0f28"   # midnight indigo-blue (ref: #202b7a)
BG3      = "#0f1638"   # pre-dawn deep blue (ref: #2c2b48)
BORDER   = "#1e2e5c"   # indigo horizon line
FG       = "#cce0f0"   # cold morning air — white with blue cast
FG_DIM   = "#5070a0"   # atmospheric blue-grey (ref: #568099 Wedgewood Blue)
BLUE     = "#3a8fc8"   # real sky blue (ref: #29638F Different Blue)
GREEN    = "#18b896"   # arctic ocean teal
YELLOW   = "#f0a030"   # horizon amber (ref: #D98545 Comfort Orange)
RED      = "#c04868"   # pre-dawn rose — magenta horizon band
PURPLE   = "#6040b8"   # twilight violet-indigo (ref: #2c2b48)
CYAN     = "#2ac4c0"   # cool atmospheric teal

STAGE_COLOR = {
    PipelineStage.PARSING:     BLUE,
    PipelineStage.CORRELATING: CYAN,
    PipelineStage.PROPOSING:   PURPLE,
    PipelineStage.AWAITING:    YELLOW,
    PipelineStage.EXECUTING:   BLUE,
    PipelineStage.COMPLETE:    GREEN,
    PipelineStage.ERROR:       RED,
    PipelineStage.CANCELLED:   FG_DIM,
}

QSS = f"""
QWidget {{
    background-color: {BG};
    color: {FG};
    font-family: 'Consolas', 'JetBrains Mono', 'Courier New', monospace;
    font-size: 13px;
}}
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 4px;
    color: {FG_DIM};
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}
QPlainTextEdit, QTextEdit {{
    background-color: {BG2};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px;
    color: {FG};
    selection-background-color: #1a3a5e;
}}
QPushButton {{
    background-color: {BG3};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 14px;
    color: {FG};
    min-width: 70px;
}}
QPushButton:hover {{
    background-color: #132038;
    border-color: {BLUE};
}}
QPushButton:pressed {{
    background-color: #090f1c;
}}
QPushButton:disabled {{
    color: {FG_DIM};
    border-color: {BORDER};
}}
QPushButton#run_btn {{
    background-color: #1a6ea8;
    border-color: #3ab8ec;
    color: #d4e8f5;
    font-weight: bold;
}}
QPushButton#run_btn:hover {{
    background-color: #3ab8ec;
}}
QPushButton#approve_btn {{
    background-color: #0f6e58;
    border-color: #1ec8a0;
    color: #d4e8f5;
    font-weight: bold;
}}
QPushButton#approve_btn:hover {{
    background-color: #1ec8a0;
}}
QPushButton#reject_btn {{
    background-color: #6e1e35;
    border-color: #d44f72;
    color: #d4e8f5;
}}
QPushButton#reject_btn:hover {{
    background-color: #a83858;
}}
QLabel#title_label {{
    font-size: 20px;
    font-weight: bold;
    color: {BLUE};
    letter-spacing: 2px;
}}
QLabel#subtitle_label {{
    font-size: 11px;
    color: {FG_DIM};
}}
QSplitter::handle {{
    background-color: {BORDER};
}}
QStatusBar {{
    background-color: {BG2};
    color: {FG_DIM};
    border-top: 1px solid {BORDER};
    font-size: 11px;
}}
"""


# ── Signal bridge (thread-safe UI updates) ────────────────────────────────────

class PipelineSignals(QObject):
    event_received = pyqtSignal(object)   # PipelineEvent


# ── Intent panel ──────────────────────────────────────────────────────────────

class IntentPanel(QGroupBox):
    def __init__(self):
        super().__init__("Intent")
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        self.class_label = QLabel("—")
        self.class_label.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {BLUE};")

        self.conf_label = QLabel("")
        self.conf_label.setStyleSheet(f"color: {FG_DIM}; font-size: 11px;")

        self.targets_box = QPlainTextEdit()
        self.targets_box.setReadOnly(True)
        self.targets_box.setMaximumHeight(90)
        self.targets_box.setPlaceholderText("targets / symbols")

        self.constraints_box = QPlainTextEdit()
        self.constraints_box.setReadOnly(True)
        self.constraints_box.setMaximumHeight(70)
        self.constraints_box.setPlaceholderText("constraints")

        layout.addWidget(self.class_label)
        layout.addWidget(self.conf_label)
        layout.addWidget(QLabel("Targets:"))
        layout.addWidget(self.targets_box)
        layout.addWidget(QLabel("Constraints:"))
        layout.addWidget(self.constraints_box)
        layout.addStretch()

    def set_intent(self, intent_result) -> None:
        self.class_label.setText(intent_result.intent_class.value)
        self.conf_label.setText(
            f"confidence {intent_result.confidence:.0%}"
            + (" ⚠ ambiguous" if intent_result.ambiguous else "")
        )
        targets_text = "\n".join(
            f"  {'📄 ' + t.path if t.path else '⚙ ' + (t.symbol or '?')}"
            + (f"  [{t.confidence:.0%}]" if t.confidence < 1 else "")
            for t in intent_result.targets
        ) or "  (none detected)"
        self.targets_box.setPlainText(targets_text)

        constraints_text = "\n".join(
            f"  {c.kind.value}: {c.value}"
            for c in intent_result.constraints
        ) or "  (none)"
        self.constraints_box.setPlainText(constraints_text)

    def clear(self) -> None:
        self.class_label.setText("—")
        self.conf_label.setText("")
        self.targets_box.clear()
        self.constraints_box.clear()


# ── Proposal panel ────────────────────────────────────────────────────────────

class ProposalPanel(QGroupBox):
    approved  = pyqtSignal()
    rejected  = pyqtSignal()

    def __init__(self):
        super().__init__("Proposal")
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        self.summary_label = QLabel("—")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(f"color: {FG_DIM}; font-size: 11px;")

        self.json_view = QPlainTextEdit()
        self.json_view.setReadOnly(True)
        self.json_view.setPlaceholderText("proposal JSON will appear here")

        btn_row = QHBoxLayout()
        self.approve_btn = QPushButton("Approve")
        self.approve_btn.setObjectName("approve_btn")
        self.approve_btn.setEnabled(False)
        self.reject_btn  = QPushButton("Reject")
        self.reject_btn.setObjectName("reject_btn")
        self.reject_btn.setEnabled(False)
        btn_row.addWidget(self.approve_btn)
        btn_row.addWidget(self.reject_btn)
        btn_row.addStretch()

        self.conf_bar = QLabel("")
        self.conf_bar.setStyleSheet(f"font-size: 11px; color: {FG_DIM};")

        layout.addWidget(self.summary_label)
        layout.addWidget(self.json_view)
        layout.addWidget(self.conf_bar)
        layout.addLayout(btn_row)

        self.approve_btn.clicked.connect(self.approved)
        self.reject_btn.clicked.connect(self.rejected)

    def set_proposal(self, proposal) -> None:
        self.summary_label.setText(proposal.summary)
        pretty = json.dumps(proposal.to_dict(), indent=2)
        self.json_view.setPlainText(pretty)
        conf = proposal.confidence
        color = GREEN if conf >= 0.7 else YELLOW if conf >= 0.4 else RED
        self.conf_bar.setText(f"LLM confidence: {conf:.0%}")
        self.conf_bar.setStyleSheet(f"font-size: 11px; color: {color};")

    def set_awaiting(self, enabled: bool) -> None:
        self.approve_btn.setEnabled(enabled)
        self.reject_btn.setEnabled(enabled)

    def clear(self) -> None:
        self.summary_label.setText("—")
        self.json_view.clear()
        self.conf_bar.setText("")
        self.set_awaiting(False)


# ── Output log ────────────────────────────────────────────────────────────────

class OutputLog(QGroupBox):
    def __init__(self):
        super().__init__("Output")
        layout = QVBoxLayout(self)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

    def append(self, text: str, color: str = FG) -> None:
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)
        cursor.insertText(text + "\n")
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()

    def append_stage(self, event: PipelineEvent) -> None:
        color = STAGE_COLOR.get(event.stage, FG)
        prefix = f"[{event.stage.value}] "
        self.append(prefix + event.message, color)

    def clear_log(self) -> None:
        self.log.clear()


# ── Main window ───────────────────────────────────────────────────────────────

class StratumWindow(QMainWindow):
    def __init__(self, project_root: Optional[str] = None):
        super().__init__()
        self.project_root = project_root or os.path.dirname(os.path.abspath(__file__))
        self._current_run: Optional[PipelineRun] = None
        self._signals = PipelineSignals()
        self._signals.event_received.connect(self._handle_event)
        self._pipeline = get_pipeline(self.project_root)
        self._setup_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        self.setWindowTitle("STRATUM")
        self.setMinimumSize(1100, 700)
        self.setStyleSheet(QSS)

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setSpacing(8)
        root_layout.setContentsMargins(12, 12, 12, 8)

        # Title row
        title_row = QHBoxLayout()
        title_lbl = QLabel("STRATUM")
        title_lbl.setObjectName("title_label")
        sub_lbl = QLabel("intent → correlate → propose → execute")
        sub_lbl.setObjectName("subtitle_label")
        title_row.addWidget(title_lbl)
        title_row.addSpacing(12)
        title_row.addWidget(sub_lbl)
        title_row.addStretch()

        if _PYRAMID_AVAILABLE:
            pyramid_btn = QPushButton("▲ PYRAMID")
            pyramid_btn.setFixedWidth(110)
            pyramid_btn.setStyleSheet(
                f"QPushButton{{background:#090f1c;color:{PURPLE};"
                f"border:1px solid {PURPLE};border-radius:4px;"
                f"padding:5px 12px;font-size:12px;font-weight:bold;}}"
                f"QPushButton:hover{{background:{PURPLE};color:{BG};}}"
            )
            pyramid_btn.setToolTip("Open Pyramid Code Intelligence (Ctrl+P)")
            pyramid_btn.clicked.connect(self._open_pyramid)
            title_row.addWidget(pyramid_btn)
            QShortcut(QKeySequence("Ctrl+P"), self).activated.connect(self._open_pyramid)
            self._pyramid_win: Optional[QWidget] = None

        root_layout.addLayout(title_row)

        # Input row
        input_row = QHBoxLayout()
        self.query_input = QPlainTextEdit()
        self.query_input.setMaximumHeight(60)
        self.query_input.setPlaceholderText(
            "Type your intent… e.g. 'debug the WebValidationEngine retry loop' "
            "or 'refactor OperatorProfile to use dataclasses'"
        )
        self.run_btn = QPushButton("Run")
        self.run_btn.setObjectName("run_btn")
        self.run_btn.setFixedWidth(80)
        self.dry_btn = QPushButton("Dry Run")
        self.dry_btn.setFixedWidth(80)
        input_row.addWidget(self.query_input)
        input_row.addWidget(self.run_btn)
        input_row.addWidget(self.dry_btn)
        root_layout.addLayout(input_row)

        # Middle splitter: intent | proposal
        mid_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.intent_panel   = IntentPanel()
        self.proposal_panel = ProposalPanel()
        mid_splitter.addWidget(self.intent_panel)
        mid_splitter.addWidget(self.proposal_panel)
        mid_splitter.setSizes([320, 680])

        # Bottom: output log
        self.output_log = OutputLog()

        # Vertical splitter: middle | log
        v_splitter = QSplitter(Qt.Orientation.Vertical)
        v_splitter.addWidget(mid_splitter)
        v_splitter.addWidget(self.output_log)
        v_splitter.setSizes([380, 280])

        root_layout.addWidget(v_splitter)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        # Shortcuts
        QShortcut(QKeySequence("Ctrl+Return"), self).activated.connect(self._run_pipeline)
        QShortcut(QKeySequence("Ctrl+Shift+Return"), self).activated.connect(self._run_dry)
        QShortcut(QKeySequence("Ctrl+L"), self).activated.connect(self.output_log.clear_log)

        # Connect buttons
        self.run_btn.clicked.connect(self._run_pipeline)
        self.dry_btn.clicked.connect(self._run_dry)
        self.proposal_panel.approved.connect(self._approve)
        self.proposal_panel.rejected.connect(self._reject)

    # ── Pyramid ───────────────────────────────────────────────────────────────

    def _open_pyramid(self) -> None:
        if not _PYRAMID_AVAILABLE:
            return
        if self._pyramid_win and self._pyramid_win.isVisible():
            self._pyramid_win.raise_()
            self._pyramid_win.activateWindow()
            return
        self._pyramid_win = _PyramidWidget(project_root=self.project_root)
        self._pyramid_win.setWindowTitle("STRATUM — Pyramid Code Intelligence")
        self._pyramid_win.resize(1280, 820)
        self._pyramid_win.show()

    # ── Pipeline control ──────────────────────────────────────────────────────

    def _run_pipeline(self) -> None:
        self._start(dry_run=False)

    def _run_dry(self) -> None:
        self._start(dry_run=True)

    def _start(self, dry_run: bool) -> None:
        query = self.query_input.toPlainText().strip()
        if not query:
            self.status_bar.showMessage("Enter a query first.")
            return

        self.intent_panel.clear()
        self.proposal_panel.clear()

        dry_label = " [DRY RUN]" if dry_run else ""
        self.output_log.append(f"\n{'─' * 60}", FG_DIM)
        self.output_log.append(f"⟩ {query}{dry_label}", BLUE)

        self._pipeline.dry_run = dry_run
        self.run_btn.setEnabled(False)
        self.dry_btn.setEnabled(False)

        self._current_run = self._pipeline.run_async(
            query    = query,
            callback = self._on_event,
        )

    def _approve(self) -> None:
        if self._current_run:
            self.proposal_panel.set_awaiting(False)
            self.output_log.append("▶ Approved — executing…", GREEN)
            self._current_run.approve()

    def _reject(self) -> None:
        if self._current_run:
            self.proposal_panel.set_awaiting(False)
            self.output_log.append("✗ Rejected by user.", RED)
            self._current_run.reject()
            self._reset_buttons()

    def _reset_buttons(self) -> None:
        self.run_btn.setEnabled(True)
        self.dry_btn.setEnabled(True)

    # ── Event handling (thread-safe via signal) ───────────────────────────────

    def _on_event(self, event: PipelineEvent) -> None:
        # Called from background thread — emit signal to cross to UI thread
        self._signals.event_received.emit(event)

    def _handle_event(self, event: PipelineEvent) -> None:
        # Called on UI thread
        self.output_log.append_stage(event)
        self.status_bar.showMessage(f"{event.stage.value}: {event.message[:80]}")

        if event.stage == PipelineStage.PARSING and event.data:
            self.intent_panel.set_intent(event.data)

        elif event.stage == PipelineStage.PROPOSING and event.data:
            proposal_result = event.data
            if proposal_result.proposal:
                self.proposal_panel.set_proposal(proposal_result.proposal)

        elif event.stage == PipelineStage.AWAITING:
            self.proposal_panel.set_awaiting(True)
            self.output_log.append(
                "  Waiting for approval. [Approve] to execute · [Reject] to cancel.",
                YELLOW,
            )

        elif event.stage == PipelineStage.COMPLETE:
            run = self._current_run
            if run and run.result:
                r = run.result
                if r.read_only_output:
                    self.output_log.append("\n" + r.read_only_output, FG)
                else:
                    for a in r.applied:
                        col = GREEN if a.success else RED
                        self.output_log.append(
                            f"  [{a.operation}] {a.file}: {a.diff_desc}", col
                        )
                    if r.syntax_errors:
                        for se in r.syntax_errors:
                            self.output_log.append(f"  ⚠ {se}", RED)
                    if r.rollback_path:
                        self.output_log.append(
                            f"  Rollback snapshot: {r.rollback_path}", FG_DIM
                        )
                self.output_log.append(f"✓ {r.summary()}", GREEN)
            self._reset_buttons()

        elif event.stage in (PipelineStage.ERROR, PipelineStage.CANCELLED):
            self._reset_buttons()


# ── Entry point ────────────────────────────────────────────────────────────────

def main(project_root: Optional[str] = None) -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Dark palette baseline (QSS overrides most, but Fusion needs hints)
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window,          QColor(BG))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor(FG))
    palette.setColor(QPalette.ColorRole.Base,            QColor(BG2))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor(BG3))
    palette.setColor(QPalette.ColorRole.Text,            QColor(FG))
    palette.setColor(QPalette.ColorRole.Button,          QColor(BG3))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor(FG))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor("#1a3a5e"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(FG))
    app.setPalette(palette)

    root = project_root or os.path.dirname(os.path.abspath(__file__))
    window = StratumWindow(project_root=root)

    # Try to set icon
    icon_path = os.path.join(root, "stratum_icon.ico")
    if os.path.isfile(icon_path):
        from PyQt6.QtGui import QIcon
        window.setWindowIcon(QIcon(icon_path))

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
