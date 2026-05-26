"""ui/knowledge_panel.py — 🜂 KNOWLEDGE CORTEX — unified recall surface.

Genesis Engine Organ 3 (Knowledge Cortex). Single query input that searches
ALL available memory backends in parallel:

    * Agent Memory (per-agent episodic + semantic, SQLite)
    * MemPalace (ChromaDB semantic vault)
    * WON daemon recent memory
    * WON pipeline (wp.search / wp.recall)

Each backend gets its own worker thread so the UI never blocks even if one
backend hangs. Empty backends show "(no results)" rather than failing silently.
Failures are receipted via truth.failure_classifier.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QObject, QThread, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

_log = logging.getLogger(__name__)

_BG       = "#0a0420"
_BG2      = "#1a0e3e"
_BORDER   = "#ff2d92"
_TEXT     = "#fff5e0"
_TEXT_DIM = "#ff8eb7"
_ACCENT   = "#ffce28"
_CYAN     = "#28e6ff"


# ── Worker for one backend ────────────────────────────────────────────────

class _BackendSearchSignals(QObject):
    """Signals carrier — QThread.run can't have signals directly."""
    done = pyqtSignal(str, list, str)   # backend_name, results, error_text


class _BackendSearchThread(threading.Thread):
    """Plain Python thread; emits via signals.done from worker thread.
    Qt's queued connection makes UI updates safe."""

    def __init__(self, backend_name: str, fn: Callable, query: str,
                 signals: _BackendSearchSignals):
        super().__init__(name=f"KnowledgeSearch-{backend_name}", daemon=True)
        self.backend_name = backend_name
        self.fn = fn
        self.query = query
        self.signals = signals

    def run(self) -> None:
        try:
            results = self.fn(self.query) or []
            self.signals.done.emit(self.backend_name, list(results), "")
        except Exception as exc:
            try:
                from truth.failure_classifier import report_caught
                report_caught("knowledge_backend_search", exc,
                              executor=f"KnowledgePanel.{self.backend_name}",
                              evidence={"query": (self.query or "")[:120]},
                              severity="info")
            except Exception:
                pass
            self.signals.done.emit(self.backend_name, [], str(exc)[:240])


# ── Main panel ─────────────────────────────────────────────────────────────

class KnowledgePanel(QWidget):
    """🜂 Unified Knowledge Cortex recall surface."""

    BACKEND_QUERY_LIMIT = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"KnowledgePanel {{ background: {_BG}; }}")

        self._backends: Dict[str, Callable[[str], List[dict]]] = {}
        self._displays: Dict[str, QTextEdit] = {}
        self._signals = _BackendSearchSignals()
        self._signals.done.connect(self._on_backend_done)
        self._pending: set[str] = set()

        self._register_backends()
        self._build_ui()

    # ── Backend registration ──────────────────────────────────────────────

    def _register_backends(self) -> None:
        """Probe each backend. Register only the ones reachable."""
        # 1. Agent Memory — local SQLite per-agent
        try:
            from agent_memory import get_memory
            from config import AgentID
            def agent_search(q: str) -> list[dict]:
                out: list[dict] = []
                for aid in (AgentID.VALIDATION, AgentID.IMPLEMENTATION,
                             AgentID.PLANNER, AgentID.STRATEGIST,
                             AgentID.SYNTHESIS):
                    try:
                        mem = get_memory(aid)
                    except Exception: continue
                    for kind, accessor in (
                        ("episodic", getattr(mem, "recall_episodic", None)),
                        ("semantic", getattr(mem, "recall_semantic", None)),
                    ):
                        if accessor is None: continue
                        try:
                            rows = accessor(q, limit=4) or []
                            for r in rows:
                                r["_kind"] = kind
                                r["_agent"] = aid
                                out.append(r)
                        except Exception: continue
                return out[: self.BACKEND_QUERY_LIMIT]
            self._backends["Agent Memory"] = agent_search
        except Exception as e:
            _log.debug("knowledge_panel: agent_memory unavailable: %s", e)

        # 2. MemPalace — ChromaDB semantic
        try:
            import mempalace_bridge as mpb
            if getattr(mpb, "is_available", lambda: False)():
                def palace_search(q: str) -> list[dict]:
                    raw = mpb.search(q, n=self.BACKEND_QUERY_LIMIT)
                    return list(raw or [])
                self._backends["MemPalace"] = palace_search
        except Exception as e:
            _log.debug("knowledge_panel: mempalace unavailable: %s", e)

        # 3. WON pipeline (search + recall) — the main process-level memory
        try:
            from pipeline import get_won_pipeline
            def won_search(q: str) -> list[dict]:
                wp = get_won_pipeline()
                if not wp: return []
                try:
                    s = wp.search(q, limit=self.BACKEND_QUERY_LIMIT)
                    if s: return list(s)
                except Exception: pass
                try:
                    return list(wp.recall(limit=self.BACKEND_QUERY_LIMIT))
                except Exception:
                    return []
            self._backends["WON Pipeline"] = won_search
        except Exception as e:
            _log.debug("knowledge_panel: won pipeline unavailable: %s", e)

        # 4. WON Daemon recent (read-only, file-backed)
        try:
            from pathlib import Path
            DAEMON_NOTIFY = Path.home() / "Documents" / "AI_Monitor" / "won_notifications.json"
            def daemon_search(q: str) -> list[dict]:
                if not DAEMON_NOTIFY.is_file(): return []
                try:
                    notes = json.loads(DAEMON_NOTIFY.read_text(encoding="utf-8"))
                except Exception:
                    return []
                if not q.strip():
                    return list(notes[-self.BACKEND_QUERY_LIMIT:])
                lq = q.lower()
                matched = [
                    n for n in notes
                    if lq in (n.get("title", "") + " " + n.get("body", "")).lower()
                ]
                return matched[-self.BACKEND_QUERY_LIMIT:]
            self._backends["WON Daemon Notifications"] = daemon_search
        except Exception as e:
            _log.debug("knowledge_panel: won daemon notifications: %s", e)

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # Title
        title = QLabel("🜂 KNOWLEDGE CORTEX")
        title.setStyleSheet(
            f"color:{_ACCENT}; font-weight:bold; font-size:14px; letter-spacing:3px;"
        )
        root.addWidget(title)
        sub = QLabel(
            "One query · every backend in parallel. Each result lists its source, "
            "timestamp, and an excerpt. No backend can block another; no backend "
            "can block the UI."
        )
        sub.setStyleSheet(f"color:{_TEXT_DIM}; font-size:11px;")
        sub.setWordWrap(True)
        root.addWidget(sub)

        # Search row
        bar = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Recall everything related to…")
        self._input.returnPressed.connect(self._on_recall)
        bar.addWidget(self._input, 1)
        recall_btn = QPushButton("⌕  RECALL")
        recall_btn.setStyleSheet(
            f"background:{_BG2}; color:{_TEXT}; border:1px solid {_ACCENT};"
            f" border-radius:5px; padding:6px 14px; font-weight:bold;"
            f" letter-spacing:2px;"
        )
        recall_btn.clicked.connect(self._on_recall)
        bar.addWidget(recall_btn)
        save_btn = QPushButton("⎇  SAVE")
        save_btn.setToolTip("Contribute the current query as a memory")
        save_btn.setStyleSheet(
            f"background:{_BG2}; color:{_TEXT}; border:1px solid {_CYAN};"
            f" border-radius:5px; padding:6px 14px; font-weight:bold;"
            f" letter-spacing:2px;"
        )
        save_btn.clicked.connect(self._on_save)
        bar.addWidget(save_btn)
        root.addLayout(bar)

        # Result tabs (one per backend)
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            f"QTabBar::tab {{ background:{_BG2}; color:{_TEXT_DIM};"
            f" padding:6px 14px; border:1px solid {_BORDER};"
            f" border-bottom:none; }}"
            f"QTabBar::tab:selected {{ color:{_ACCENT}; }}"
            f"QTabWidget::pane {{ border:1px solid {_BORDER}; }}"
        )
        if not self._backends:
            empty = QLabel(
                "(no memory backends reachable in this build — install "
                "mempalace or run with won pipeline online)"
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color:{_TEXT_DIM}; padding:24px;")
            root.addWidget(empty)
        else:
            for name in self._backends:
                view = QTextEdit()
                view.setReadOnly(True)
                view.setStyleSheet(
                    f"background:{_BG}; color:{_TEXT}; border:none;"
                    " font-family:Consolas,monospace; font-size:10px;"
                )
                view.setPlainText("(type a query and press RECALL)")
                self._displays[name] = view
                self._tabs.addTab(view, name)
            root.addWidget(self._tabs, 1)

    # ── Actions ───────────────────────────────────────────────────────────

    def _on_recall(self) -> None:
        query = self._input.text().strip()
        if not query: return
        for name in self._backends:
            self._displays[name].setPlainText(f"⟳ searching {name}…")
            self._pending.add(name)
        for name, fn in self._backends.items():
            _BackendSearchThread(name, fn, query, self._signals).start()

    def _on_backend_done(self, backend_name: str, results: list, err: str) -> None:
        self._pending.discard(backend_name)
        view = self._displays.get(backend_name)
        if view is None:
            return
        if err and not results:
            view.setPlainText(f"(failed: {err})")
            return
        if not results:
            view.setPlainText("(no results)")
            return
        lines = []
        for i, r in enumerate(results, 1):
            if not isinstance(r, dict):
                lines.append(f"{i}.  {str(r)[:240]}")
                lines.append("")
                continue
            content = (
                r.get("content") or r.get("text") or r.get("body")
                or r.get("value") or r.get("title") or ""
            )
            ts = r.get("ts") or r.get("timestamp") or ""
            source = (
                r.get("source") or r.get("source_file") or r.get("_agent")
                or r.get("wing") or r.get("mode") or ""
            )
            score = r.get("similarity") or r.get("confidence") or r.get("importance")
            score_str = f"  [{score:.2f}]" if isinstance(score, (int, float)) else ""
            snippet = (content or "").replace("\n", " ")[:240]
            lines.append(f"{i}.  [{ts}]  {source}{score_str}")
            if snippet:
                lines.append(f"     {snippet}")
            lines.append("")
        view.setPlainText("\n".join(lines))

    def _on_save(self) -> None:
        """Contribute the current input as a memory entry via WON pipeline."""
        text = self._input.text().strip()
        if not text:
            return
        try:
            from pipeline import get_won_pipeline
            wp = get_won_pipeline()
            if wp:
                wp.contribute(text, source="operator",
                              mode="knowledge_save",
                              tags=["operator_save", "knowledge_panel"])
                self._input.setText("")
                self._input.setPlaceholderText("saved · type next query…")
        except Exception as exc:
            try:
                from truth.failure_classifier import report_caught
                report_caught("knowledge_save", exc,
                              executor="KnowledgePanel._on_save")
            except Exception:
                pass
