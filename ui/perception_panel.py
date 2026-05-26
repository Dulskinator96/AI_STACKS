"""ui/perception_panel.py — 📊 PERCEPTION — live observer telemetry.

Genesis Engine Organ 2 (Runtime Perception). Surfaces the 11 MaintenanceCortex
observers as a real-time card grid. Each card shows: observer name, last scan
age, status (green/amber/red), key metric.

Pure View per CLAUDE.md §5: never mutates, never blocks the UI. Data flows from
`cortex.runtime.last_outcomes` via a 2-second QTimer poll on the UI thread.
The cortex itself runs its scan loop in a daemon thread; we only read.
"""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

_log = logging.getLogger(__name__)


# ── Palette (matches TimeSplitters app theme) ─────────────────────────────
_BG       = "#0a0420"
_BG2      = "#1a0e3e"
_BORDER   = "#ff2d92"
_TEXT     = "#fff5e0"
_TEXT_DIM = "#ff8eb7"
_GREEN    = "#28e6ff"   # healthy uses cyan to feel "live"
_AMBER    = "#ffce28"
_RED      = "#ff5722"


def _evidence_metric(observer_name: str, issues) -> str:
    """Extract one salient metric from issue evidence for the card front."""
    if not issues:
        return "—"
    try:
        evidence = (issues[0].evidence or {}) if hasattr(issues[0], "evidence") else {}
    except Exception:
        return "—"
    # Best-effort metric extraction per observer (defensive)
    candidates = (
        "percent", "cpu_percent", "rss_mb", "queue_depth",
        "error_count_in_window", "events_per_min", "avg_latency_ms",
        "rate_per_min", "depth", "count",
    )
    for k in candidates:
        if k in evidence:
            v = evidence[k]
            if isinstance(v, float):
                return f"{v:.1f} {k}"
            return f"{v} {k}"
    return f"{len(issues)} issue{'s' if len(issues) != 1 else ''}"


def _status_color(issues) -> tuple[str, str]:
    """green = no issues, amber = T1/T2, red = T3/T4."""
    if not issues:
        return _GREEN, "✓ healthy"
    for issue in issues:
        try:
            tier_val = str(getattr(issue, "tier", "")).upper()
        except Exception:
            tier_val = ""
        if "T3" in tier_val or "T4" in tier_val:
            return _RED, "⚠ critical"
    return _AMBER, "△ degraded"


class _ObserverCard(QFrame):
    """One card in the perception grid. Click → expand detail."""

    def __init__(self, observer_name: str, on_click, parent=None):
        super().__init__(parent)
        self.observer_name = observer_name
        self._on_click = on_click
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._apply_style(_GREEN)

        self._name = QLabel(observer_name)
        self._name.setStyleSheet(
            f"color:{_TEXT}; font-weight:bold; font-size:11px; letter-spacing:1px;"
            " background: transparent;"
        )
        self._age = QLabel("—")
        self._age.setStyleSheet(f"color:{_TEXT_DIM}; font-size:9px; background: transparent;")
        self._status = QLabel("✓ healthy")
        self._status.setStyleSheet(
            f"color:{_GREEN}; font-weight:bold; font-size:10px; background: transparent;"
        )
        self._metric = QLabel("—")
        self._metric.setStyleSheet(
            f"color:{_TEXT}; font-family:Consolas,monospace; font-size:10px;"
            " background: transparent;"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(3)
        lay.addWidget(self._name)
        lay.addWidget(self._age)
        lay.addWidget(self._status)
        lay.addWidget(self._metric)
        lay.addStretch()

    def _apply_style(self, accent: str) -> None:
        self.setStyleSheet(
            f"_ObserverCard {{ background:{_BG2}; border:1px solid {accent};"
            f" border-radius:6px; }}"
            f"_ObserverCard:hover {{ border:2px solid {_AMBER}; }}"
        )

    def mousePressEvent(self, event) -> None:
        try:
            self._on_click(self.observer_name)
        except Exception:
            pass
        super().mousePressEvent(event)

    def refresh(self, issues, now: float) -> None:
        color, status_text = _status_color(issues)
        self._apply_style(color)
        self._status.setText(status_text)
        self._status.setStyleSheet(
            f"color:{color}; font-weight:bold; font-size:10px; background: transparent;"
        )
        self._metric.setText(_evidence_metric(self.observer_name, issues))
        if issues:
            try:
                ts = float(getattr(issues[0], "detected_at", now))
            except Exception:
                ts = now
            age = now - ts
            if age < 60:    age_str = f"{int(age)}s ago"
            elif age < 3600: age_str = f"{int(age // 60)}m ago"
            else:            age_str = f"{int(age // 3600)}h ago"
            self._age.setText(age_str)
        else:
            self._age.setText("no recent issues")


class PerceptionPanel(QWidget):
    """📊 Live observer telemetry surface."""

    def __init__(self, cortex, parent=None):
        super().__init__(parent)
        self._cortex = cortex
        self._cards: Dict[str, _ObserverCard] = {}
        self._issues_by_obs: Dict[str, list] = defaultdict(list)
        self._selected: Optional[str] = None
        self.setStyleSheet(f"PerceptionPanel {{ background: {_BG}; }}")
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # Header
        header = QHBoxLayout()
        title = QLabel("📊 RUNTIME PERCEPTION")
        title.setStyleSheet(
            f"color:{_AMBER}; font-weight:bold; font-size:14px; letter-spacing:3px;"
        )
        header.addWidget(title)
        header.addStretch()
        refresh_btn = QPushButton("↻ Refresh now")
        refresh_btn.clicked.connect(self._refresh)
        header.addWidget(refresh_btn)
        root.addLayout(header)

        # Health badge
        self._health_badge = QLabel("Health: —")
        self._health_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._health_badge.setStyleSheet(
            f"background:{_BG2}; color:{_TEXT}; padding:10px;"
            f" border:1px solid {_BORDER}; border-radius:6px;"
            " font-weight:bold; font-size:12px; letter-spacing:2px;"
        )
        root.addWidget(self._health_badge)

        # Splitter: cards on top, detail panel on bottom
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Cards grid (scrollable)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ background:{_BG}; border:none; }}"
        )
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setSpacing(6)
        grid.setContentsMargins(0, 0, 0, 0)

        observers = []
        try:
            observers = list(getattr(self._cortex, "observers", []) or [])
        except Exception as e:
            _log.debug("perception_panel: observers unreachable: %s", e)

        if observers:
            for i, obs in enumerate(observers):
                name = getattr(obs, "name", obs.__class__.__name__)
                card = _ObserverCard(name, self._on_card_clicked)
                self._cards[name] = card
                row, col = divmod(i, 3)
                grid.addWidget(card, row, col)
        else:
            grid.addWidget(QLabel("(maintenance cortex not yet initialised)"), 0, 0)

        scroll.setWidget(grid_host)
        splitter.addWidget(scroll)

        # Detail panel
        detail_frame = QFrame()
        detail_frame.setStyleSheet(
            f"QFrame {{ background:{_BG2}; border:1px solid {_BORDER};"
            f" border-radius:6px; }}"
        )
        dl = QVBoxLayout(detail_frame)
        dl.setContentsMargins(8, 6, 8, 6)
        self._detail_header = QLabel("Click an observer card for details")
        self._detail_header.setStyleSheet(
            f"color:{_AMBER}; font-weight:bold; font-size:11px;"
            " background: transparent;"
        )
        dl.addWidget(self._detail_header)
        self._detail_text = QPlainTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setStyleSheet(
            f"background:{_BG}; color:{_TEXT}; border:none;"
            " font-family:Consolas,monospace; font-size:10px;"
        )
        dl.addWidget(self._detail_text)
        splitter.addWidget(detail_frame)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        root.addWidget(splitter)

    # ── Live refresh ──────────────────────────────────────────────────────

    def _refresh(self) -> None:
        now = time.time()
        # Collect issues by observer from runtime.last_outcomes (best-effort)
        self._issues_by_obs.clear()
        try:
            outcomes = list(getattr(self._cortex.runtime, "last_outcomes", []) or [])
            for outcome in outcomes:
                issue = getattr(outcome, "issue", None)
                if issue is None:
                    continue
                obs_name = getattr(issue, "observer", "?")
                self._issues_by_obs[obs_name].append(issue)
        except Exception as e:
            _log.debug("perception_panel: outcome read failed: %s", e)

        # Refresh each card
        for name, card in self._cards.items():
            card.refresh(self._issues_by_obs.get(name, []), now)

        # Health badge totals
        total = len(self._cards)
        healthy = sum(1 for n in self._cards if not self._issues_by_obs.get(n))
        critical = 0
        degraded = 0
        for n in self._cards:
            iss = self._issues_by_obs.get(n, [])
            if not iss: continue
            color, _ = _status_color(iss)
            if color == _RED: critical += 1
            elif color == _AMBER: degraded += 1
        self._health_badge.setText(
            f"Health: {healthy}/{total} ✓   ·   {degraded} △ degraded   ·   "
            f"{critical} ⚠ critical"
        )

        # Re-render detail if a card is selected
        if self._selected:
            self._render_detail(self._selected)

    def _on_card_clicked(self, observer_name: str) -> None:
        self._selected = observer_name
        self._render_detail(observer_name)

    def _render_detail(self, observer_name: str) -> None:
        issues = self._issues_by_obs.get(observer_name, [])
        self._detail_header.setText(f"Detail · {observer_name}")
        if not issues:
            self._detail_text.setPlainText(
                "No issues from this observer in the current scan window.\n\n"
                "(The observer is running; it simply has nothing to report.)"
            )
            return
        lines = []
        for i, issue in enumerate(issues[:6], 1):
            lines.append(f"Issue {i}")
            for attr in ("kind", "tier", "severity", "surface", "confidence",
                          "repair_hint", "detected_at"):
                val = getattr(issue, attr, None)
                if val is None: continue
                lines.append(f"  {attr}: {val}")
            ev = getattr(issue, "evidence", None) or {}
            if ev:
                lines.append("  evidence:")
                for k, v in ev.items():
                    lines.append(f"    {k}: {v}")
            lines.append("")
        self._detail_text.setPlainText("\n".join(lines))
