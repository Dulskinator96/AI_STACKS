"""
pyramid_ui.py — Apex Layer: Conversational code intelligence UI.

Layout
------
  ┌───────────────────────────────────────────────────────────────────┐
  │  [Project]  [Browse]  [Index Now]  ● STATUS  [GRAPH] [ENSEMBLE]  │
  │  Explored: [chip] [chip] …                                        │
  ├───────────────────────────────┬───────────────────────────────────┤
  │  CONVERSATION  (chat cards)   │  GRAPH ─ or ─ ENSEMBLE PANEL      │
  │                               │  Agent cards / dep graph          │
  ├───────────────────────────────┴───────────────────────────────────┤
  │  [chips]                                                          │
  ├───────────────────────────────────────────────────────────────────┤
  │  depth hint  ╔══════════════════════════╗  [Send]  [Ensemble ▲]  │
  │              ╚══════════════════════════╝                        │
  └───────────────────────────────────────────────────────────────────┘

Standalone:  python pyramid_ui.py [/path/to/project]
"""
from __future__ import annotations

import math
import random
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    QObject,
    Qt,
    QThread,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QKeySequence,
    QPainter,
    QPen,
    QShortcut,
    QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pyramid_index import PyramidIndex, get_index
from pyramid_mind import PyramidMind, CodeAnswer, DisclosureLevel
import logging
_log = logging.getLogger(__name__)

# ── Palette — Pre-Dawn Nautical Twilight ──────────────────────────────────────
# Grounded in real source references:
#   nautical twilight darks:  #051545 #202b7a #2c2b48  (actual sky before light)
#   blue-hour sky blues:      #2C4A73 #29638F #568099  (Retro/Different/Wedgewood Blue)
#   horizon warm glow:        #D98545 Comfort Orange · #F9C06B Crispy amber
#   pre-dawn rose band:       warm magenta at horizon before sun clears

BG      = "#06091c"   # deep navy — dark but blue-present (ref: #051545)
BG2     = "#0a0f28"   # midnight indigo-blue (ref: #202b7a darkened)
BG3     = "#0f1638"   # pre-dawn deep blue (ref: #2c2b48 shifted blue)
BG4     = "#162048"   # rising navy
BORDER  = "#1e2e5c"   # indigo horizon line
FG      = "#cce0f0"   # cold morning air — white with blue cast
FG_DIM  = "#5070a0"   # atmospheric blue-grey (ref: #568099 Wedgewood)
FG_MUTE = "#203060"   # deep muted indigo
BLUE    = "#3a8fc8"   # real sky blue (ref: #29638F Different Blue, #568099)
GREEN   = "#18b896"   # arctic ocean teal
YELLOW  = "#f0a030"   # horizon amber (ref: #D98545 Comfort Orange)
RED     = "#c04868"   # pre-dawn rose — magenta horizon band
PURPLE  = "#6040b8"   # twilight violet-indigo (ref: #2c2b48 purple shifted)
CYAN    = "#2ac4c0"   # cool atmospheric teal
ORANGE  = "#d88040"   # deep ember at edge (ref: #D98545)

# Depth-level colours
_DEPTH_COLOR = {
    DisclosureLevel.GIST:     FG_DIM,
    DisclosureLevel.SYNOPSIS: YELLOW,
    DisclosureLevel.FULL:     PURPLE,
}
_DEPTH_ICON  = {
    DisclosureLevel.GIST:     "◇",
    DisclosureLevel.SYNOPSIS: "◆",
    DisclosureLevel.FULL:     "◈",
}

_FONT = "'Cascadia Code','JetBrains Mono',Consolas,monospace"


# ── HTML helpers ───────────────────────────────────────────────────────────────

def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _ts() -> str:
    return datetime.now().strftime("%H:%M")


def _render_md(text: str) -> str:
    """Markdown subset → HTML for QTextEdit."""
    # Fenced code blocks  ```lang\ncode```
    def _code_block(m):
        lang = m.group(1) or ""
        body = _esc(m.group(2).rstrip())
        lang_tag = (
            f'<span style="color:{FG_MUTE};font-size:10px;'
            f'float:right;padding-right:4px;">{lang}</span>'
            if lang else ""
        )
        return (
            f'<div style="margin:8px 0;">'
            f'{lang_tag}'
            f'<pre style="background:{BG3};color:{CYAN};'
            f'padding:10px 12px;border-radius:6px;'
            f'border-left:3px solid {BLUE};'
            f'font-size:11px;white-space:pre-wrap;'
            f'font-family:{_FONT};margin:0;">{body}</pre></div>'
        )

    text = re.sub(r'```(\w*)\n?(.*?)```', _code_block, text, flags=re.S)

    # Inline code
    text = re.sub(
        r'`([^`\n]+)`',
        lambda m: (
            f'<code style="background:{BG3};color:{CYAN};'
            f'padding:1px 5px;border-radius:3px;font-size:11px;">'
            f'{_esc(m.group(1))}</code>'
        ),
        text,
    )

    # Headers  ## text
    text = re.sub(
        r'^### (.+)$',
        lambda m: f'<p style="color:{FG_DIM};font-size:10px;letter-spacing:1px;margin:6px 0 2px 0;">{_esc(m.group(1)).upper()}</p>',
        text, flags=re.M,
    )
    text = re.sub(
        r'^## (.+)$',
        lambda m: f'<p style="color:{BLUE};font-weight:bold;margin:8px 0 3px 0;">{_esc(m.group(1))}</p>',
        text, flags=re.M,
    )
    text = re.sub(
        r'^# (.+)$',
        lambda m: f'<p style="color:{FG};font-size:14px;font-weight:bold;margin:8px 0 4px 0;">{_esc(m.group(1))}</p>',
        text, flags=re.M,
    )

    # Bold + italic
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<b><i>\1</i></b>', text)
    text = re.sub(r'\*\*(.+?)\*\*',     r'<b>\1</b>',        text)
    text = re.sub(r'\*(.+?)\*',         r'<i>\1</i>',        text)

    # Numbered + bullet lists
    def _list_item(m):
        return (
            f'<div style="margin:2px 0;padding-left:16px;">'
            f'<span style="color:{BLUE};">›</span> {m.group(1)}</div>'
        )

    text = re.sub(r'^\d+\.\s+(.+)$', _list_item, text, flags=re.M)
    text = re.sub(r'^[-*]\s+(.+)$',  _list_item, text, flags=re.M)

    # Newlines
    text = text.replace("\n", "<br>")
    return f'<span style="color:{FG};line-height:1.65;font-size:12px;">{text}</span>'


def _file_chips_html(files: list[str], max_n: int = 5) -> str:
    if not files:
        return ""
    chips = []
    for path in files[:max_n]:
        name = Path(path).name
        ext  = Path(path).suffix.lstrip(".")
        ext_color = {
            "py": BLUE, "js": YELLOW, "ts": CYAN,
            "go": CYAN, "rs": ORANGE, "java": RED,
            "cs": PURPLE, "md": FG_DIM,
        }.get(ext, FG_DIM)
        chips.append(
            f'<span style="background:{BG3};color:{ext_color};'
            f'border:1px solid {BORDER};border-radius:10px;'
            f'padding:1px 8px;font-size:10px;margin-right:4px;">'
            f'{_esc(name)}</span>'
        )
    return " ".join(chips)


def _depth_meter_html(level: DisclosureLevel) -> str:
    bars = []
    for i in range(1, 4):
        active = i <= level.value
        col    = _DEPTH_COLOR[level] if active else BG4
        bars.append(
            f'<span style="background:{col};display:inline-block;'
            f'width:8px;height:8px;border-radius:2px;margin-right:2px;"></span>'
        )
    return "".join(bars)


# ── Force-directed graph ──────────────────────────────────────────────────────

class _Node:
    __slots__ = ("id", "label", "x", "y", "vx", "vy")
    def __init__(self, nid: str):
        self.id    = nid
        self.label = Path(nid).stem[:16]
        self.x     = random.uniform(60, 540)
        self.y     = random.uniform(50, 380)
        self.vx    = 0.0
        self.vy    = 0.0


class GraphCanvas(QWidget):
    """Graph of project files. Nodes are stationary (no physics jitter); an
    'active' node — one currently being processed by a Pyramid agent / tool —
    pulses with a colored glow ring. State per node: idle → active → idle."""

    node_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(260, 260)
        self._nodes:    dict[str, _Node]      = {}
        self._edges:    list[tuple[str, str]] = []
        self._hovered:  Optional[str]         = None
        self._selected: Optional[str]         = None
        self._highlighted: set[str]           = set()
        self._active:   set[str]              = set()   # node IDs mid-tool
        self._glow_phase = 0.0                          # pulse animation [0,1)
        self._timer     = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)
        self.setMouseTracking(True)

    # ── Public API ──────────────────────────────────────────────────────────
    def set_active(self, node_id: str, active: bool = True) -> None:
        """Mark a node as currently mid-tool-execution. Glows while active."""
        if active:
            self._active.add(node_id)
        else:
            self._active.discard(node_id)
        self.update()

    def clear_active(self) -> None:
        self._active.clear()
        self.update()

    def set_graph(self, adjacency: dict[str, list[str]]) -> None:
        all_ids: set[str] = set()
        edges: list[tuple[str, str]] = []
        for src, dsts in adjacency.items():
            all_ids.add(src)
            for dst in dsts:
                all_ids.add(dst)
                edges.append((src, dst))
        sampled = sorted(all_ids)[:60]
        existing = set(self._nodes.keys())
        for nid in list(self._nodes.keys()):
            if nid not in sampled:
                del self._nodes[nid]
        for nid in sampled:
            if nid not in self._nodes:
                self._nodes[nid] = _Node(nid)
        self._edges = [(s, d) for s, d in edges
                       if s in self._nodes and d in self._nodes][:120]
        # Re-arrange whenever the node set changes — nodes are stationary,
        # so we want a deterministic layout instead of random init positions.
        if existing != set(self._nodes.keys()):
            self._arrange_circle()
        self.update()

    def highlight_files(self, paths: list[str]) -> None:
        self._highlighted = set(paths)
        self.update()

    def _arrange_circle(self) -> None:
        cx, cy = self.width() / 2, self.height() / 2
        r = min(cx, cy) * 0.70
        nodes = list(self._nodes.values())
        for i, node in enumerate(nodes):
            angle = 2 * math.pi * i / max(len(nodes), 1)
            node.x = cx + r * math.cos(angle)
            node.y = cy + r * math.sin(angle)

    def _tick(self) -> None:
        # Nodes are stationary — _arrange_circle() places them once and they
        # stay there (no jiggle). Only animation tick is the glow pulse for
        # nodes in the 'active' state.
        if not self._nodes:
            return
        if self._active:
            self._glow_phase = (self._glow_phase + 0.06) % 1.0
            self.update()

    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(BG2))

        if not self._nodes:
            p.setPen(QColor(FG_MUTE))
            p.setFont(QFont("Consolas", 10))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "No project indexed\nSelect a directory above")
            p.end()
            return

        # Edges — highlighted edges brighter
        highlighted_set = {
            (s, d) for s, d in self._edges
            if s in self._highlighted or d in self._highlighted
        }
        for s_id, d_id in self._edges:
            if s_id not in self._nodes or d_id not in self._nodes:
                continue
            a, b = self._nodes[s_id], self._nodes[d_id]
            if (s_id, d_id) in highlighted_set:
                p.setPen(QPen(QColor(BLUE), 1.5))
            else:
                p.setPen(QPen(QColor(BORDER), 1))
            p.drawLine(int(a.x), int(a.y), int(b.x), int(b.y))

        # Nodes
        font = QFont("Consolas", 8)
        p.setFont(font)
        fm = QFontMetrics(font)

        # Pulse amplitude derived from glow_phase: a smooth in-out cosine.
        pulse = 0.5 * (1.0 - math.cos(self._glow_phase * 2.0 * math.pi))

        for node in self._nodes.values():
            sel  = node.id == self._selected
            hov  = node.id == self._hovered
            hi   = node.id in self._highlighted
            act  = node.id in self._active
            r    = 22 if sel else (20 if hi else 16)

            # ── Active glow ring ────────────────────────────────────────────
            # Cyan halo painted slightly outside the node, alpha-pulsed.
            if act:
                glow_r     = r + int(8 + 6 * pulse)
                glow_alpha = int(70 + 100 * pulse)
                glow_col   = QColor(CYAN)
                glow_col.setAlpha(glow_alpha)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(glow_col, 3))
                p.drawEllipse(
                    int(node.x - glow_r), int(node.y - glow_r),
                    glow_r * 2, glow_r * 2,
                )

            col = QColor(PURPLE if sel else (CYAN if hov else (BLUE if hi else BG4)))
            p.setBrush(col)
            border_col = QColor(CYAN if act else (BLUE if hi or sel else BG3))
            p.setPen(QPen(border_col, 2))
            p.drawEllipse(int(node.x - r), int(node.y - r), r * 2, r * 2)
            label = node.label
            lw    = fm.horizontalAdvance(label)
            p.setPen(QColor(FG if sel or hov or hi or act else FG_DIM))
            p.drawText(int(node.x - lw // 2), int(node.y + 4), label)

        p.end()

    def mouseMoveEvent(self, ev) -> None:
        pos = ev.position()
        prev = self._hovered
        self._hovered = None
        for node in self._nodes.values():
            if math.hypot(pos.x() - node.x, pos.y() - node.y) < 22:
                self._hovered = node.id
                break
        if self._hovered != prev:
            self.update()
            if self._hovered:
                self.setToolTip(Path(self._hovered).name)
            else:
                self.setToolTip("")

    def mousePressEvent(self, ev) -> None:
        pos = ev.position()
        for node in self._nodes.values():
            if math.hypot(pos.x() - node.x, pos.y() - node.y) < 22:
                self._selected = node.id
                self.node_clicked.emit(node.id)
                self.update()
                return

    def resizeEvent(self, ev) -> None:
        self._arrange_circle()
        super().resizeEvent(ev)


# ── Worker threads ─────────────────────────────────────────────────────────────

class IndexWorker(QObject):
    progress = pyqtSignal(str, int, int)
    finished = pyqtSignal(dict)

    def __init__(self, index: PyramidIndex, force: bool = False):
        super().__init__()
        self._idx   = index
        self._force = force

    def run(self) -> None:
        stats = self._idx.scan(
            progress_cb=lambda m, c, t: self.progress.emit(m, c, t),
            force=self._force,
        )
        self.finished.emit(stats)


class AskWorker(QObject):
    answered = pyqtSignal(object)

    def __init__(self, mind: PyramidMind, query: str):
        super().__init__()
        self._mind  = mind
        self._query = query

    def run(self) -> None:
        self.answered.emit(self._mind.ask(self._query))


# ── Suggestion bar ────────────────────────────────────────────────────────────

class SuggestionBar(QWidget):
    triggered = pyqtSignal(str)

    _DEFAULT = [
        "Synopsis of this project",
        "What design patterns are used?",
        "Show dependency architecture",
        "What are the entry points?",
        "Find async-heavy files",
        "Explain the pipeline",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 2, 0, 2)
        self._layout.setSpacing(6)
        self._buttons: list[QPushButton] = []
        self.set_suggestions(self._DEFAULT)

    def set_suggestions(self, suggestions: list[str]) -> None:
        for btn in self._buttons:
            btn.deleteLater()
        self._buttons.clear()
        for text in suggestions:
            btn = self._make_chip(text)
            self._layout.addWidget(btn)
            self._buttons.append(btn)
        self._layout.addStretch()

    def _make_chip(self, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(24)
        btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        btn.setStyleSheet(
            f"QPushButton{{background:{BG3};color:{FG_DIM};"
            f"border:1px solid {BORDER};border-radius:12px;"
            f"padding:1px 12px;font-size:11px;font-family:{_FONT};}}"
            f"QPushButton:hover{{background:{BG4};color:{FG};"
            f"border-color:{BLUE};}}"
        )
        btn.clicked.connect(lambda _, t=text: self.triggered.emit(t))
        return btn

    def update_context_chip(self, fname: str) -> None:
        if self._buttons:
            text = f"Explain {fname}"
            last = self._buttons[-1]
            last.setText(text)
            try:
                last.clicked.disconnect()
            except Exception as e:
                _log.warning(f'caught exception: {e}')
            last.clicked.connect(lambda _, t=text: self.triggered.emit(t))


# ── Session breadcrumb ────────────────────────────────────────────────────────

class BreadcrumbBar(QWidget):
    """Horizontal trail of explored files — updates as conversation progresses."""

    file_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(24)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        lbl = QLabel("Explored:")
        lbl.setStyleSheet(f"color:{FG_MUTE};font-size:10px;")
        self._layout.addWidget(lbl)
        self._layout.addStretch()
        self._files: list[str] = []

    def add_file(self, path: str) -> None:
        if path in self._files:
            return
        self._files.append(path)
        # Remove stretch, add chip, re-add stretch
        item = self._layout.takeAt(self._layout.count() - 1)
        name = Path(path).name
        btn  = QPushButton(name)
        btn.setFixedHeight(20)
        btn.setStyleSheet(
            f"QPushButton{{background:{BG2};color:{BLUE};"
            f"border:1px solid {BORDER};border-radius:10px;"
            f"padding:0px 8px;font-size:10px;font-family:{_FONT};}}"
            f"QPushButton:hover{{border-color:{BLUE};color:{FG};}}"
        )
        btn.clicked.connect(lambda _, p=path: self.file_clicked.emit(p))
        self._layout.addWidget(btn)
        self._layout.addStretch()

    def clear(self) -> None:
        self._files.clear()
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        lbl = QLabel("Explored:")
        lbl.setStyleSheet(f"color:{FG_MUTE};font-size:10px;")
        self._layout.addWidget(lbl)
        self._layout.addStretch()


# ── Chat view ─────────────────────────────────────────────────────────────────

class ChatView(QTextEdit):
    """QTextEdit subclass with message management and typing indicator."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setStyleSheet(
            f"QTextEdit{{background:{BG};color:{FG};"
            f"border:none;padding:12px 8px;"
            f"font-size:12px;font-family:{_FONT};}}"
        )
        self._typing_block = False
        self._dot_timer    = QTimer(self)
        self._dot_timer.timeout.connect(self._animate_dots)
        self._dot_phase    = 0

    # ── Message types ──────────────────────────────────────────────────────────

    def add_user(self, text: str) -> None:
        ts = _ts()
        html = (
            f'<div style="margin:10px 0 4px 0;padding:10px 14px 10px 14px;'
            f'background:{BG2};'
            f'border-left:3px solid {BLUE};'
            f'border-radius:0 6px 6px 0;">'
            # header
            f'<div style="display:flex;margin-bottom:6px;">'
            f'<span style="color:{BLUE};font-size:10px;font-weight:bold;'
            f'letter-spacing:1px;">YOU</span>'
            f'<span style="color:{FG_MUTE};font-size:10px;margin-left:8px;">{ts}</span>'
            f'</div>'
            # body
            f'<span style="color:{FG};font-size:12px;line-height:1.5;">'
            f'{_esc(text)}</span>'
            f'</div>'
        )
        self.append(html)
        self._scroll_bottom()

    def add_thinking(self) -> None:
        self._dot_phase = 0
        self._typing_block = True
        self._dot_timer.start(400)
        html = (
            f'<div id="thinking" style="margin:4px 0;padding:8px 14px;'
            f'background:{BG};border-left:3px solid {FG_MUTE};'
            f'border-radius:0 6px 6px 0;color:{FG_DIM};font-size:11px;">'
            f'<span style="color:{FG_MUTE};font-size:10px;font-weight:bold;'
            f'letter-spacing:1px;">STRATUM</span>'
            f'&nbsp;&nbsp;'
            f'<span id="dots">●&nbsp;&nbsp;○&nbsp;&nbsp;○</span>'
            f'&nbsp; <span style="color:{FG_MUTE};">analyzing…</span>'
            f'</div>'
        )
        self.append(html)
        self._scroll_bottom()

    def _animate_dots(self) -> None:
        if not self._typing_block:
            self._dot_timer.stop()
            return
        self._dot_phase = (self._dot_phase + 1) % 3
        # Replace last block's dots - find and update cursor
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        # We can't easily update mid-HTML in QTextEdit, so just append a new tiny block
        # (The thinking block stays but we also let the timer run — will be replaced)

    def remove_thinking(self) -> None:
        self._typing_block = False
        self._dot_timer.stop()
        # Remove the last appended thinking block by selecting from end back
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        doc = self.document()
        # Find and remove the last block that contains "analyzing…"
        block = doc.lastBlock()
        while block.isValid():
            if "analyzing" in block.text() or "STRATUM" in block.text():
                # Delete from block start to end of next block
                c = QTextCursor(block)
                c.select(QTextCursor.SelectionType.BlockUnderCursor)
                c.removeSelectedText()
                break
            block = block.previous()

    def add_stratum(self, answer: CodeAnswer) -> None:
        self.remove_thinking()
        ts         = _ts()
        level      = answer.disclosure_level
        lv_color   = _DEPTH_COLOR[level]
        lv_icon    = _DEPTH_ICON[level]
        depth_bars = _depth_meter_html(level)
        file_chips = _file_chips_html(answer.files_touched)
        body       = _render_md(answer.text)

        sym_line = ""
        if answer.symbols_touched:
            syms = ", ".join(
                f'<code style="background:{BG3};color:{CYAN};'
                f'padding:0 4px;border-radius:3px;font-size:10px;">'
                f'{_esc(s)}</code>'
                for s in answer.symbols_touched[:6]
            )
            sym_line = (
                f'<div style="margin-top:4px;margin-bottom:2px;">'
                f'<span style="color:{FG_MUTE};font-size:10px;">symbols: </span>'
                f'{syms}</div>'
            )

        src_dot = (
            f'<span style="color:{GREEN};" title="Ollama/Mistral">⬤</span>'
            if answer.source == "llm" else
            f'<span style="color:{FG_MUTE};" title="local index">⬤</span>'
        )

        html = (
            # Card
            f'<div style="margin:4px 0 10px 0;padding:0;'
            f'border-left:3px solid {lv_color};'
            f'border-radius:0 6px 6px 0;'
            f'background:{BG2};">'

            # Header strip
            f'<div style="padding:8px 14px 6px 14px;'
            f'border-bottom:1px solid {BORDER};">'
            f'<span style="color:{lv_color};font-size:10px;font-weight:bold;'
            f'letter-spacing:1px;">STRATUM</span>'
            f'&nbsp;&nbsp;'
            f'{depth_bars}'
            f'&nbsp;<span style="color:{lv_color};font-size:10px;">{lv_icon} {level.name}</span>'
            f'<span style="color:{FG_MUTE};font-size:10px;margin-left:8px;">{ts}</span>'
            f'&nbsp;&nbsp;{src_dot}'
            f'<span style="color:{FG_MUTE};font-size:10px;"> {answer.latency_ms:.0f}ms</span>'
            f'</div>'

            # File chips (if any)
            + (
                f'<div style="padding:5px 14px 0 14px;">{file_chips}</div>'
                if file_chips else ""
            )
            + (
                f'<div style="padding:2px 14px 0 14px;">{sym_line}</div>'
                if sym_line else ""
            )

            # Body
            + f'<div style="padding:10px 14px 12px 14px;">{body}</div>'

            + '</div>'
        )
        self.append(html)
        self._scroll_bottom()

    def add_system(self, text: str) -> None:
        html = (
            f'<div style="margin:4px 0;padding:6px 12px;'
            f'border:1px dashed {BORDER};border-radius:6px;'
            f'background:{BG};'
            f'color:{FG_DIM};font-size:11px;">'
            f'{_render_md(text)}'
            f'</div>'
        )
        self.append(html)
        self._scroll_bottom()

    def add_separator(self) -> None:
        self.append(
            f'<div style="border-top:1px solid {BORDER};margin:10px 0;"></div>'
        )

    def _scroll_bottom(self) -> None:
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())


# ── Holographic progress bar ──────────────────────────────────────────────────

class HoloBar(QWidget):
    """
    Animated holographic progress bar.
    Paints a shifting multi-stop gradient clipped to the filled region.
    Call start_animation() / stop_animation() to control shimmer.
    """

    # Full iridescent spectrum — vivid, saturated, electric
    _STOPS = [
        "#00ffe0",  # electric cyan-green
        "#00b8ff",  # electric sky blue
        "#7000ff",  # deep electric violet
        "#ff00aa",  # hot magenta
        "#ff6600",  # electric orange
        "#ffcc00",  # electric gold
        "#00ffe0",  # electric cyan-green (seamless loop)
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value   = 0
        self._maximum = 9
        self._offset  = 0.0
        self.setFixedHeight(10)
        self.setMinimumWidth(60)
        self._timer = QTimer(self)
        self._timer.setInterval(25)         # 40 fps
        self._timer.timeout.connect(self._tick)

    def setValue(self, v: int) -> None:
        self._value = max(0, min(v, self._maximum))
        self.update()

    def setRange(self, mn: int, mx: int) -> None:
        self._maximum = max(mx, 1)
        self.update()

    def start_animation(self) -> None:
        self._timer.start()

    def stop_animation(self) -> None:
        self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._offset = (self._offset + 0.007) % 1.0
        self.update()

    def paintEvent(self, _event) -> None:
        from PyQt6.QtGui import QPainter, QLinearGradient, QPainterPath

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r    = h / 2.0

        # Track background
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(BG3))
        painter.drawRoundedRect(0, 0, w, h, r, r)

        fill_w = int(w * self._value / self._maximum)
        if fill_w <= 1:
            painter.end()
            return

        # Gradient spans 3× bar width; animate by shifting left
        grad_w = float(w * 3)
        shift  = self._offset * grad_w
        grad   = QLinearGradient(-shift, 0.0, grad_w - shift, 0.0)
        n      = len(self._STOPS) - 1
        for i, hex_col in enumerate(self._STOPS):
            grad.setColorAt(i / n, QColor(hex_col))

        # Glow pass — semi-transparent halo painted slightly outside fill rect
        glow_grad = QLinearGradient(-shift, 0.0, grad_w - shift, 0.0)
        for i, hex_col in enumerate(self._STOPS):
            c = QColor(hex_col)
            c.setAlpha(90)
            glow_grad.setColorAt(i / n, c)
        painter.setOpacity(0.55)
        painter.fillRect(-3, -3, fill_w + 6, h + 6, glow_grad)
        painter.setOpacity(1.0)

        # Main fill clipped to rounded rect
        path = QPainterPath()
        path.addRoundedRect(0.0, 0.0, float(fill_w), float(h), r, r)
        painter.setClipPath(path)
        painter.fillRect(0, 0, fill_w, h, grad)
        painter.end()


# ── Consciousness + Ensemble optional import ──────────────────────────────────

_ENSEMBLE_OK  = False
_CONSCIOUS_OK = False

try:
    from consciousness import (
        get_conscious_orchestrator,
    )
    from pyramid_ensemble import (
        EnsembleEvent,
        EnsembleResult,
        EventKind,
        Perception,
    )
    _CONSCIOUS_OK = True
    _ENSEMBLE_OK  = True
except ImportError:
    try:
        from pyramid_ensemble import (
            EnsembleEvent,
            EnsembleResult,
            EventKind,
            Perception,
            get_orchestrator,
        )
        _ENSEMBLE_OK = True
    except ImportError:
        pass


# ── Ensemble worker ───────────────────────────────────────────────────────────

class EnsembleWorker(QObject):
    """Runs EnsembleOrchestrator in a thread and emits Qt signals."""
    event_received = pyqtSignal(object)   # EnsembleEvent
    finished       = pyqtSignal(object)   # EnsembleResult

    def __init__(self, query: str, code_context: str, model: str = "mistral"):
        super().__init__()
        self._query   = query
        self._context = code_context
        self._model   = model

    def run(self) -> None:
        if not _ENSEMBLE_OK:
            return
        if _CONSCIOUS_OK:
            orch = get_conscious_orchestrator(self._model)
        else:
            orch = get_orchestrator(self._model)   # type: ignore[name-defined]
        _captured: list = []

        def _cb(event):
            self.event_received.emit(event)
            if event.kind == EventKind.ENSEMBLE_DONE and event.result is not None:
                _captured.append(event.result)

        t = orch.run_async(self._query, self._context, _cb)
        t.join()

        # Emit persona states after run so UI can reflect evolved body-states
        if _CONSCIOUS_OK and hasattr(orch, "get_persona_states"):
            self.finished.emit(_captured[0] if _captured else None)
        else:
            self.finished.emit(_captured[0] if _captured else None)


# ── Agent card ────────────────────────────────────────────────────────────────

class AgentCard(QFrame):
    """Single-agent live status card inside EnsemblePanel."""

    _COLORS = {
        "validation":     "#18b896",   # arctic teal
        "implementation": "#3a8fc8",   # sky blue
        "planner":        "#f0a030",   # horizon amber
        "strategist":     "#6040b8",   # twilight violet
        "synthesis":      "#d88040",   # deep ember
    }

    def __init__(self, agent_id: str, agent_name: str, agent_emoji: str,
                 parent=None):
        super().__init__(parent)
        self._agent_id = agent_id
        self._color    = self._COLORS.get(agent_id, FG_DIM)

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            f"AgentCard{{background:{BG2};border:1px solid {BORDER};"
            f"border-radius:6px;padding:4px;}}"
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        # Header row
        hdr = QHBoxLayout()
        hdr.setSpacing(6)

        self._emoji_lbl = QLabel(agent_emoji)
        self._emoji_lbl.setStyleSheet(f"font-size:16px;color:{self._color};")
        hdr.addWidget(self._emoji_lbl)

        self._name_lbl = QLabel(agent_name.upper())
        self._name_lbl.setStyleSheet(
            f"color:{self._color};font-size:10px;font-weight:bold;"
            f"letter-spacing:1px;"
        )
        hdr.addWidget(self._name_lbl, stretch=1)

        # Round dots
        self._r1_dot = QLabel("R1")
        self._r2_dot = QLabel("R2")
        for dot in (self._r1_dot, self._r2_dot):
            dot.setFixedSize(22, 16)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setStyleSheet(
                f"color:{FG_MUTE};font-size:9px;background:{BG3};"
                f"border-radius:3px;"
            )
        hdr.addWidget(self._r1_dot)
        hdr.addWidget(self._r2_dot)

        lay.addLayout(hdr)

        # Confidence bar
        self._conf_bar = QProgressBar()
        self._conf_bar.setRange(0, 100)
        self._conf_bar.setValue(0)
        self._conf_bar.setFixedHeight(4)
        self._conf_bar.setTextVisible(False)
        self._conf_bar.setStyleSheet(
            f"QProgressBar{{background:{BG3};border-radius:2px;border:none;}}"
            f"QProgressBar::chunk{{background:{self._color};border-radius:2px;}}"
        )
        lay.addWidget(self._conf_bar)

        # Findings
        self._findings = QTextEdit()
        self._findings.setReadOnly(True)
        self._findings.setMinimumHeight(70)
        self._findings.setMaximumHeight(180)
        self._findings.setStyleSheet(
            f"QTextEdit{{background:{BG3};color:{FG};border:none;"
            f"font-size:11px;padding:4px;border-radius:4px;}}"
        )
        lay.addWidget(self._findings)

        # Handoffs
        self._handoff_bar = QHBoxLayout()
        self._handoff_bar.setSpacing(4)
        self._handoff_wrap = QWidget()
        self._handoff_wrap.setLayout(self._handoff_bar)
        self._handoff_wrap.hide()
        lay.addWidget(self._handoff_wrap)

        # Persona state row (consciousness layer — curiosity + energy)
        persona_row = QHBoxLayout()
        persona_row.setSpacing(4)

        curiosity_lbl = QLabel("⬡")
        curiosity_lbl.setStyleSheet(f"color:{YELLOW};font-size:8px;")
        persona_row.addWidget(curiosity_lbl)

        self._curiosity_bar = QProgressBar()
        self._curiosity_bar.setRange(0, 100)
        self._curiosity_bar.setValue(50)
        self._curiosity_bar.setFixedHeight(3)
        self._curiosity_bar.setTextVisible(False)
        self._curiosity_bar.setStyleSheet(
            f"QProgressBar{{background:{BG3};border:none;border-radius:1px;}}"
            f"QProgressBar::chunk{{background:{YELLOW};border-radius:1px;}}"
        )
        persona_row.addWidget(self._curiosity_bar, stretch=1)

        energy_lbl = QLabel("⬡")
        energy_lbl.setStyleSheet(f"color:{CYAN};font-size:8px;")
        persona_row.addWidget(energy_lbl)

        self._energy_bar = QProgressBar()
        self._energy_bar.setRange(0, 100)
        self._energy_bar.setValue(100)
        self._energy_bar.setFixedHeight(3)
        self._energy_bar.setTextVisible(False)
        self._energy_bar.setStyleSheet(
            f"QProgressBar{{background:{BG3};border:none;border-radius:1px;}}"
            f"QProgressBar::chunk{{background:{CYAN};border-radius:1px;}}"
        )
        persona_row.addWidget(self._energy_bar, stretch=1)

        self._creative_badge = QLabel("")
        self._creative_badge.setStyleSheet(
            "color:#ff00aa;font-size:9px;font-weight:bold;"
        )
        self._creative_badge.hide()
        persona_row.addWidget(self._creative_badge)

        lay.addLayout(persona_row)

        self._status = QLabel("idle")
        self._status.setStyleSheet(f"color:{FG_MUTE};font-size:9px;")
        lay.addWidget(self._status)

    def set_thinking(self, round_num: int) -> None:
        dot = self._r1_dot if round_num == 1 else self._r2_dot
        dot.setStyleSheet(
            f"color:{BG};font-size:9px;background:{self._color};"
            f"border-radius:3px;"
        )
        self._status.setText(f"thinking  R{round_num}…")
        self._findings.setHtml(
            f'<span style="color:{FG_DIM};font-style:italic;">analyzing…</span>'
        )

    def set_done(self, perception: "Perception") -> None:
        # Round dot done
        dot = self._r1_dot if perception.round == 1 else self._r2_dot
        dot.setStyleSheet(
            f"color:{BG};font-size:9px;background:{GREEN};"
            f"border-radius:3px;"
        )
        self._conf_bar.setValue(int(perception.confidence * 100))
        self._findings.setHtml(_render_md(perception.findings))
        self._status.setText(
            f"done  ·  {perception.latency_ms:.0f}ms  ·  conf {perception.confidence:.0%}"
        )
        # Handoff chips
        while self._handoff_bar.count():
            item = self._handoff_bar.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if perception.handoffs:
            for h in perception.handoffs[:4]:
                chip = QLabel(h[:50])
                chip.setWordWrap(False)
                chip.setStyleSheet(
                    f"background:{BG4};color:{YELLOW};"
                    f"font-size:9px;border-radius:8px;padding:1px 7px;"
                    f"border:1px solid {BORDER};"
                )
                self._handoff_bar.addWidget(chip)
            self._handoff_bar.addStretch()
            self._handoff_wrap.show()

    def set_error(self, msg: str) -> None:
        self._status.setText(f"error: {msg[:60]}")
        self._findings.setHtml(
            f'<span style="color:{RED};">⚠ {_esc(msg[:200])}</span>'
        )

    def set_persona_state(self, curiosity: float, energy: float) -> None:
        """Update the consciousness body-state bars."""
        self._curiosity_bar.setValue(int(curiosity * 100))
        self._energy_bar.setValue(int(energy * 100))
        if curiosity > 0.70:
            self._curiosity_bar.setStyleSheet(
                f"QProgressBar{{background:{BG3};border:none;border-radius:1px;}}"
                f"QProgressBar::chunk{{background:#ff6600;border-radius:1px;}}"
            )
        else:
            self._curiosity_bar.setStyleSheet(
                f"QProgressBar{{background:{BG3};border:none;border-radius:1px;}}"
                f"QProgressBar::chunk{{background:{YELLOW};border-radius:1px;}}"
            )

    def set_creative_signal(self, active: bool) -> None:
        """Flash the creative signal badge when prediction error was high."""
        if active:
            self._creative_badge.setText("⚡")
            self._creative_badge.show()
        else:
            self._creative_badge.hide()

    def reset(self) -> None:
        for dot in (self._r1_dot, self._r2_dot):
            dot.setStyleSheet(
                f"color:{FG_MUTE};font-size:9px;background:{BG3};border-radius:3px;"
            )
        self._conf_bar.setValue(0)
        self._findings.clear()
        self._status.setText("idle")
        self._handoff_wrap.hide()
        self._creative_badge.hide()


# ── Ensemble panel ────────────────────────────────────────────────────────────

_AGENT_DEFS = [
    ("validation",     "Validation",     "✓"),
    ("implementation", "Implementation", "💻"),
    ("planner",        "Planner",        "📋"),
    ("strategist",     "Strategist",     "🧭"),
]


class EnsemblePanel(QWidget):
    """Right-side panel showing 4 agent cards + synthesis + round progress."""

    run_requested = pyqtSignal(str)    # query string

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    # 4 agents × 2 rounds + 1 synthesis
    _TOTAL_STEPS = 9

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self._steps_done = 0

        # Header row
        hdr = QHBoxLayout()
        hdr.setSpacing(6)
        lbl = QLabel("ENSEMBLE")
        lbl.setStyleSheet(
            f"color:{FG_MUTE};font-size:10px;letter-spacing:1px;"
        )
        hdr.addWidget(lbl, stretch=1)

        self._step_lbl = QLabel("")
        self._step_lbl.setStyleSheet(f"color:{FG_MUTE};font-size:10px;")
        hdr.addWidget(self._step_lbl)

        self._round_lbl = QLabel("●  idle")
        self._round_lbl.setStyleSheet(f"color:{FG_MUTE};font-size:10px;")
        hdr.addWidget(self._round_lbl)
        lay.addLayout(hdr)

        # Holographic progress bar
        self._progress = HoloBar()
        self._progress.setRange(0, self._TOTAL_STEPS)
        self._progress.setValue(0)
        lay.addWidget(self._progress)

        # Agent cards — 2 × 2 grid
        grid_top = QHBoxLayout()
        grid_top.setSpacing(6)
        grid_bot = QHBoxLayout()
        grid_bot.setSpacing(6)

        self._cards: dict[str, AgentCard] = {}
        for i, (aid, aname, emoji) in enumerate(_AGENT_DEFS):
            card = AgentCard(aid, aname, emoji)
            self._cards[aid] = card
            (grid_top if i < 2 else grid_bot).addWidget(card)

        lay.addLayout(grid_top)
        lay.addLayout(grid_bot)

        # Synthesis block
        synth_lbl = QLabel("SYNTHESIS")
        synth_lbl.setStyleSheet(
            f"color:{FG_MUTE};font-size:10px;letter-spacing:1px;margin-top:4px;"
        )
        lay.addWidget(synth_lbl)

        self._synthesis = QTextEdit()
        self._synthesis.setReadOnly(True)
        self._synthesis.setMinimumHeight(90)
        self._synthesis.setMaximumHeight(220)
        self._synthesis.setPlaceholderText("Synthesis will appear here after all agents complete…")
        self._synthesis.setStyleSheet(
            f"QTextEdit{{background:{BG2};color:{FG};"
            f"border:1px solid {BORDER};border-radius:6px;"
            f"font-size:11px;padding:6px;}}"
        )
        lay.addWidget(self._synthesis)

        # Sources list
        self._sources_lbl = QLabel("")
        self._sources_lbl.setWordWrap(True)
        self._sources_lbl.setStyleSheet(f"color:{FG_DIM};font-size:9px;")
        lay.addWidget(self._sources_lbl)

        # Conflict notice
        self._conflict_lbl = QLabel("")
        self._conflict_lbl.setWordWrap(True)
        self._conflict_lbl.setStyleSheet(f"color:{YELLOW};font-size:9px;")
        lay.addWidget(self._conflict_lbl)

        # Strange loop meta-insight (visible only when creative signals fire)
        self._meta_wrap = QWidget()
        meta_lay = QVBoxLayout(self._meta_wrap)
        meta_lay.setContentsMargins(0, 2, 0, 0)
        meta_lay.setSpacing(2)

        meta_hdr = QLabel("⚡  STRANGE LOOP — META-INSIGHT")
        meta_hdr.setStyleSheet(
            "color:#ff00aa;font-size:9px;font-weight:bold;letter-spacing:1px;"
        )
        meta_lay.addWidget(meta_hdr)

        self._meta_insight = QTextEdit()
        self._meta_insight.setReadOnly(True)
        self._meta_insight.setFixedHeight(56)
        self._meta_insight.setStyleSheet(
            f"QTextEdit{{background:{BG3};color:#e0c0f0;"
            f"border:1px solid #6040b8;border-radius:4px;"
            f"font-size:10px;padding:4px;font-style:italic;}}"
        )
        meta_lay.addWidget(self._meta_insight)
        self._meta_wrap.hide()
        lay.addWidget(self._meta_wrap)

        lay.addStretch()

    def handle_event(self, event: "EnsembleEvent") -> None:
        kind = event.kind

        if kind == EventKind.ROUND_START:
            msg = event.message or ""
            # Strange loop meta-insight arrives as a ROUND_START with "Meta-insight:" prefix
            if "Meta-insight:" in msg:
                insight = msg.split("Meta-insight:", 1)[-1].strip()
                self._meta_insight.setPlainText(insight)
                self._meta_wrap.show()
            elif "Strange loop" in msg:
                self._round_lbl.setText("⚡  Reflecting")
                self._round_lbl.setStyleSheet("color:#ff00aa;font-size:10px;")
            else:
                label = f"●  Round {event.round}" if event.round else f"●  {msg[:40]}"
                self._round_lbl.setText(label)
                self._round_lbl.setStyleSheet(f"color:{BLUE};font-size:10px;")

        elif kind == EventKind.AGENT_START:
            card = self._cards.get(event.agent_id)
            if card:
                card.set_thinking(event.round)
            # Glow all currently-highlighted nodes — they're the files this
            # agent is reasoning over. Cleared on AGENT_DONE / ENSEMBLE_DONE.
            try:
                for nid in self._graph._highlighted:
                    self._graph.set_active(nid, True)
            except Exception as e:
                _log.warning(f'caught exception: {e}')

        elif kind == EventKind.AGENT_DONE:
            card = self._cards.get(event.agent_id)
            if card and event.perception:
                card.set_done(event.perception)
            # Light the freshly-touched files; cap with clear on ENSEMBLE_DONE.
            try:
                if event.perception and event.perception.files_touched:
                    for f in event.perception.files_touched:
                        self._graph.set_active(f, True)
            except Exception as e:
                _log.warning(f'caught exception: {e}')
                # Reflect updated persona state if consciousness layer is active
                if _CONSCIOUS_OK:
                    try:
                        orch = get_conscious_orchestrator()
                        states = orch.get_persona_states()
                        ps = states.get(event.agent_id)
                        if ps:
                            card.set_persona_state(ps.curiosity, ps.energy)
                    except Exception as e:
                        _log.warning(f'caught exception: {e}')
            self._steps_done += 1
            self._progress.setValue(self._steps_done)
            self._step_lbl.setText(f"{self._steps_done}/{self._TOTAL_STEPS}")

        elif kind == EventKind.AGENT_ERROR:
            card = self._cards.get(event.agent_id)
            if card:
                card.set_error(event.message)
            self._steps_done += 1
            self._progress.setValue(self._steps_done)
            self._step_lbl.setText(f"{self._steps_done}/{self._TOTAL_STEPS}")

        elif kind == EventKind.PACKET_STORED:
            # Creative signal: packet emitted right after AGENT_DONE
            # Check if the workspace had a creative broadcast for this agent
            if _CONSCIOUS_OK and event.agent_id:
                try:
                    orch = get_conscious_orchestrator()
                    active = orch._workspace._active
                    for b in active:
                        if b.agent_id == event.agent_id and b.creative_signal:
                            card = self._cards.get(event.agent_id)
                            if card:
                                card.set_creative_signal(True)
                            break
                except Exception as e:
                    _log.warning(f'caught exception: {e}')

        elif kind == EventKind.SYNTH_START:
            self._round_lbl.setText("●  Synthesizing")
            self._round_lbl.setStyleSheet(f"color:{ORANGE};font-size:10px;")
            self._synthesis.setHtml(
                f'<span style="color:{FG_DIM};font-style:italic;">synthesizing…</span>'
            )

        elif kind == EventKind.SYNTH_DONE:
            if event.perception:
                self._synthesis.setHtml(_render_md(event.perception.findings))
            self._steps_done = self._TOTAL_STEPS
            self._progress.setValue(self._TOTAL_STEPS)
            self._step_lbl.setText(f"{self._TOTAL_STEPS}/{self._TOTAL_STEPS}")

        elif kind == EventKind.CONFLICT:
            existing = self._conflict_lbl.text()
            self._conflict_lbl.setText(
                (existing + "\n" if existing else "") + f"⚡ {event.message[:120]}"
            )

        elif kind == EventKind.ENSEMBLE_DONE:
            self._round_lbl.setText("●  done")
            self._round_lbl.setStyleSheet(f"color:{GREEN};font-size:10px;")
            try: self._graph.clear_active()
            except Exception: pass

    def handle_result(self, result: "EnsembleResult") -> None:
        if result is None:
            return
        # Show conflicts
        if result.conflicts:
            parts = [f"⚡ {a}: {reason[:80]}" for a, reason in result.conflicts[:3]]
            self._conflict_lbl.setText("\n".join(parts))
        # Collect sources from PlannerAgent perceptions
        sources: list[str] = []
        for p in result.perceptions:
            if p.agent_id == "planner":
                for h in p.handoffs[:3]:
                    if "http" in h:
                        sources.append(h[:100])
        if sources:
            self._sources_lbl.setText("Sources: " + "  ·  ".join(sources))

    def reset(self) -> None:
        for card in self._cards.values():
            card.reset()
        self._synthesis.clear()
        self._sources_lbl.setText("")
        self._conflict_lbl.setText("")
        self._meta_wrap.hide()
        self._meta_insight.clear()
        self._round_lbl.setText("●  idle")
        self._round_lbl.setStyleSheet(f"color:{FG_MUTE};font-size:10px;")
        self._steps_done = 0
        self._progress.stop_animation()
        self._progress.setValue(0)
        self._step_lbl.setText("")


# ── Depth hint label ──────────────────────────────────────────────────────────

class DepthHint(QLabel):
    """Shows predicted disclosure depth for current session state."""

    def __init__(self, parent=None):
        super().__init__("depth: GIST", parent)
        self._set(DisclosureLevel.GIST)

    def _set(self, level: DisclosureLevel) -> None:
        col  = _DEPTH_COLOR[level]
        icon = _DEPTH_ICON[level]
        self.setText(f"next response: {icon} {level.name}")
        self.setStyleSheet(
            f"color:{col};font-size:10px;font-family:{_FONT};"
            f"background:{BG2};border:1px solid {BORDER};"
            f"border-radius:4px;padding:2px 8px;"
        )

    def update_from_mind(self, mind: Optional[PyramidMind]) -> None:
        if not mind:
            return
        # Heuristic: if session has turns, bump hint
        n = len(mind._history)
        if n == 0:
            self._set(DisclosureLevel.GIST)
        elif n == 1:
            self._set(DisclosureLevel.SYNOPSIS)
        else:
            self._set(DisclosureLevel.FULL)


# ── Main widget ───────────────────────────────────────────────────────────────

class PyramidWidget(QWidget):
    """
    Self-contained Pyramid code intelligence widget.
    Embed:   tab_widget.addTab(PyramidWidget(), "Pyramid")
    Launch:  python pyramid_ui.py [/path/to/project]
    """

    def __init__(self, parent=None, project_root: Optional[str] = None):
        super().__init__(parent)
        self._index:           Optional[PyramidIndex] = None
        self._mind:            Optional[PyramidMind]  = None
        self._index_thread:    Optional[QThread]      = None
        self._ask_thread:      Optional[QThread]      = None
        self._ensemble_thread: Optional[QThread]      = None
        self._project_root:    str                    = project_root or ""
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_changes)
        self._poll_timer.setInterval(3500)

        self._build_ui()
        self.setStyleSheet(
            f"QWidget{{background:{BG};color:{FG};"
            f"font-family:{_FONT};font-size:12px;}}"
            f"QScrollBar:vertical{{background:{BG2};width:6px;border:none;}}"
            f"QScrollBar::handle:vertical{{background:{BORDER};border-radius:3px;}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}"
        )

        if project_root:
            self._load_project(project_root)

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(0)

        # ── Top bar ────────────────────────────────────────────────────────────
        top = QHBoxLayout()
        top.setSpacing(6)
        top.setContentsMargins(0, 0, 0, 6)

        self._path_label = QLabel("No project loaded")
        self._path_label.setStyleSheet(f"color:{FG_DIM};font-size:11px;")
        self._path_label.setMinimumWidth(180)
        top.addWidget(self._path_label, stretch=1)

        browse = self._make_btn("Browse…", BORDER, FG, 72)
        browse.clicked.connect(self._browse)
        top.addWidget(browse)

        self._idx_btn = self._make_btn("Index Now", BLUE, BG, 84)
        self._idx_btn.setEnabled(False)
        self._idx_btn.clicked.connect(self._start_index)
        top.addWidget(self._idx_btn)

        self._badge = QLabel("●  OFFLINE")
        self._badge.setStyleSheet(f"color:{FG_DIM};font-size:11px;")
        top.addWidget(self._badge)

        top.addStretch()

        stats_btn = self._make_btn("Stats", BG3, FG_DIM, 50)
        stats_btn.clicked.connect(self._show_stats)
        top.addWidget(stats_btn)

        clear_btn = self._make_btn("Clear", BG3, FG_DIM, 50)
        clear_btn.clicked.connect(self._clear)
        top.addWidget(clear_btn)

        root.addLayout(top)

        # ── Breadcrumb ─────────────────────────────────────────────────────────
        self._breadcrumb = BreadcrumbBar()
        self._breadcrumb.file_clicked.connect(self._query_file)
        root.addWidget(self._breadcrumb)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{BORDER};margin:4px 0;")
        root.addWidget(sep)

        # ── Main splitter: chat | graph ────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(f"QSplitter::handle{{background:{BORDER};width:1px;}}")

        # Chat pane
        chat_pane = QWidget()
        cl = QVBoxLayout(chat_pane)
        cl.setContentsMargins(0, 0, 6, 0)
        cl.setSpacing(0)

        chat_lbl = QLabel("CONVERSATION")
        chat_lbl.setStyleSheet(
            f"color:{FG_MUTE};font-size:10px;letter-spacing:1px;margin-bottom:4px;"
        )
        cl.addWidget(chat_lbl)

        self._chat = ChatView()
        cl.addWidget(self._chat)
        splitter.addWidget(chat_pane)

        # Right panel — toggle header + stacked widget
        right_pane = QWidget()
        rl = QVBoxLayout(right_pane)
        rl.setContentsMargins(6, 0, 0, 0)
        rl.setSpacing(4)

        # Toggle header
        panel_hdr = QHBoxLayout()
        panel_hdr.setSpacing(0)

        self._btn_graph = self._make_toggle_btn("GRAPH", active=True)
        self._btn_graph.clicked.connect(lambda: self._toggle_panel(0))
        panel_hdr.addWidget(self._btn_graph)

        self._btn_ensemble = self._make_toggle_btn("ENSEMBLE", active=False)
        self._btn_ensemble.clicked.connect(lambda: self._toggle_panel(1))
        panel_hdr.addWidget(self._btn_ensemble)
        panel_hdr.addStretch()
        rl.addLayout(panel_hdr)

        # Stacked: index 0 = graph, index 1 = ensemble
        self._right_stack = QStackedWidget()

        self._graph = GraphCanvas()
        self._graph.node_clicked.connect(self._on_node_click)
        self._right_stack.addWidget(self._graph)          # index 0

        self._ensemble_panel = EnsemblePanel()
        self._right_stack.addWidget(self._ensemble_panel) # index 1
        self._right_stack.setCurrentIndex(0)

        rl.addWidget(self._right_stack)
        splitter.addWidget(right_pane)

        splitter.setSizes([640, 380])
        root.addWidget(splitter, stretch=1)

        # ── Thin separator ─────────────────────────────────────────────────────
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color:{BORDER};margin:4px 0;")
        root.addWidget(sep2)

        # ── Suggestion chips ───────────────────────────────────────────────────
        chips_scroll = QScrollArea()
        chips_scroll.setFixedHeight(34)
        chips_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        chips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        chips_scroll.setStyleSheet(f"border:none;background:{BG};")
        self._chips = SuggestionBar()
        chips_scroll.setWidget(self._chips)
        chips_scroll.setWidgetResizable(True)
        self._chips.triggered.connect(self._inject)
        root.addWidget(chips_scroll)

        # ── Input area ─────────────────────────────────────────────────────────
        inp_row = QHBoxLayout()
        inp_row.setSpacing(8)
        inp_row.setContentsMargins(0, 6, 0, 0)

        # Left: depth hint + textarea
        inp_col = QVBoxLayout()
        inp_col.setSpacing(3)

        self._depth_hint = DepthHint()
        inp_col.addWidget(self._depth_hint)

        self._input = QPlainTextEdit()
        self._input.setFixedHeight(56)
        self._input.setPlaceholderText(
            "Ask anything about your codebase…   Ctrl+Enter to send"
        )
        self._input.setStyleSheet(
            f"QPlainTextEdit{{background:{BG2};color:{FG};"
            f"border:1px solid {BORDER};border-radius:6px;"
            f"padding:8px 10px;font-size:12px;}}"
            f"QPlainTextEdit:focus{{border-color:{BLUE};}}"
        )
        inp_col.addWidget(self._input)
        inp_row.addLayout(inp_col)

        # Right: Send + Ensemble buttons
        btn_col = QVBoxLayout()
        btn_col.setSpacing(4)

        send = QPushButton("Send")
        send.setFixedSize(64, 34)
        send.setStyleSheet(
            f"QPushButton{{background:{BLUE};color:{BG};"
            f"border:none;border-radius:6px;"
            f"font-size:12px;font-weight:bold;}}"
            f"QPushButton:hover{{background:#79b8ff;}}"
            f"QPushButton:pressed{{background:#388bfd;}}"
        )
        send.clicked.connect(self._send)
        btn_col.addWidget(send)

        self._ens_btn = QPushButton("Ensemble ▲")
        self._ens_btn.setFixedSize(88, 34)
        self._ens_btn.setEnabled(_ENSEMBLE_OK)
        self._ens_btn.setToolTip(
            "Run all 4 agents on this query" if _ENSEMBLE_OK
            else "pyramid_ensemble not available"
        )
        self._ens_btn.setStyleSheet(
            f"QPushButton{{background:{BG2};color:{PURPLE};"
            f"border:1px solid {PURPLE};border-radius:6px;"
            f"font-size:11px;}}"
            f"QPushButton:hover{{background:{BG3};}}"
            f"QPushButton:pressed{{background:{BG4};}}"
            f"QPushButton:disabled{{color:{FG_MUTE};border-color:{BORDER};}}"
        )
        self._ens_btn.clicked.connect(self._send_ensemble)
        btn_col.addWidget(self._ens_btn)

        inp_row.addLayout(btn_col)
        root.addLayout(inp_row)

        # ── Status bar ─────────────────────────────────────────────────────────
        self._status = QLabel("Ready")
        self._status.setStyleSheet(
            f"color:{FG_MUTE};font-size:10px;margin-top:3px;"
        )
        root.addWidget(self._status)

        # Keyboard shortcuts
        sc = QShortcut(QKeySequence("Ctrl+Return"), self._input)
        sc.activated.connect(self._send)
        QShortcut(QKeySequence("Ctrl+L"), self).activated.connect(self._clear)
        QShortcut(QKeySequence("Ctrl+E"), self).activated.connect(self._send_ensemble)

    # ── Project management ─────────────────────────────────────────────────────

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select Project Directory",
            self._project_root or str(Path.home()),
        )
        if path:
            self._load_project(path)

    def _load_project(self, root: str) -> None:
        self._project_root = root
        display = root if len(root) < 55 else "…" + root[-52:]
        self._path_label.setText(f"  {display}")
        self._index = get_index(root)
        self._mind  = PyramidMind(self._index)
        self._idx_btn.setEnabled(True)
        self._set_badge("IDLE", YELLOW)
        self._chat.add_system(
            f"**Project:** `{Path(root).name}`  ·  `{root}`\n"
            f"Auto-indexing…"
        )
        self._start_index()

    # ── Indexing ───────────────────────────────────────────────────────────────

    def _start_index(self, force: bool = False) -> None:
        if not self._index or self._index_thread:
            return
        self._idx_btn.setEnabled(False)
        self._set_badge("INDEXING", BLUE)

        self._index_thread = QThread()
        self._index_worker = IndexWorker(self._index, force=force)
        self._index_worker.moveToThread(self._index_thread)
        self._index_thread.started.connect(self._index_worker.run)
        self._index_worker.progress.connect(self._on_progress)
        self._index_worker.finished.connect(self._on_indexed)
        self._index_worker.finished.connect(self._index_thread.quit)
        self._index_thread.finished.connect(self._index_thread.deleteLater)
        self._index_thread.finished.connect(
            lambda: setattr(self, '_index_thread', None)
        )
        self._index_thread.start()

    def _on_progress(self, msg: str, cur: int, tot: int) -> None:
        self._status.setText(f"Indexing  {cur}/{tot}  —  {msg}")

    def _on_indexed(self, stats: dict) -> None:
        self._idx_btn.setEnabled(True)
        self._set_badge("LIVE", GREEN)
        s = self._index.stats() if self._index else {}
        self._status.setText(
            f"Indexed  {stats['total']} files  ·  "
            f"+{stats['added']} new  ·  {stats['updated']} updated"
        )
        self._chat.add_system(
            f"Index ready:  **{s.get('files', 0)}** files  ·  "
            f"**{s.get('symbols', 0)}** symbols  ·  "
            f"**{s.get('patterns', 0)}** patterns detected"
        )
        if self._index:
            self._graph.set_graph(self._index.dependency_graph())
            self._index.watch(interval_s=8.0)
        self._poll_timer.start()

    def _poll_changes(self) -> None:
        if not self._index:
            return
        changed = self._index.flush_pending()
        if changed:
            self._graph.set_graph(self._index.dependency_graph())
            self._status.setText(f"Live  —  {len(changed)} file(s) reindexed")

    # ── Query ──────────────────────────────────────────────────────────────────

    def _send(self) -> None:
        query = self._input.toPlainText().strip()
        if not query:
            return
        if not self._mind:
            self._chat.add_system("Load a project first.")
            return
        if self._ask_thread:
            self._chat.add_system("Still thinking…")
            return
        self._input.clear()
        self._chat.add_user(query)
        self._chat.add_thinking()
        self._status.setText("Analyzing…")

        self._ask_thread = QThread()
        self._ask_worker = AskWorker(self._mind, query)
        self._ask_worker.moveToThread(self._ask_thread)
        self._ask_thread.started.connect(self._ask_worker.run)
        self._ask_worker.answered.connect(self._on_answer)
        self._ask_worker.answered.connect(self._ask_thread.quit)
        self._ask_thread.finished.connect(self._ask_thread.deleteLater)
        self._ask_thread.finished.connect(
            lambda: setattr(self, '_ask_thread', None)
        )
        self._ask_thread.start()

    def _on_answer(self, answer: CodeAnswer) -> None:
        self._chat.add_stratum(answer)
        self._status.setText(answer.short_status())
        self._depth_hint.update_from_mind(self._mind)
        # Update breadcrumb
        for path in answer.files_touched:
            self._breadcrumb.add_file(path)
        # Highlight graph nodes
        self._graph.highlight_files(answer.files_touched)
        # Update suggestion chips
        if answer.files_touched:
            self._chips.update_context_chip(Path(answer.files_touched[0]).name)

    def _on_node_click(self, node_id: str) -> None:
        fname = Path(node_id).name
        self._input.setPlainText(f"Explain {fname}")
        self._send()

    def _query_file(self, path: str) -> None:
        fname = Path(path).name
        self._input.setPlainText(f"Explain {fname}")
        self._send()

    def _inject(self, text: str) -> None:
        self._input.setPlainText(text)
        self._input.setFocus()

    # ── Stats / session ────────────────────────────────────────────────────────

    def _show_stats(self) -> None:
        if not self._index:
            self._chat.add_system("No project loaded.")
            return
        s  = self._index.stats()
        ms = self._mind.session_summary() if self._mind else "—"
        self._chat.add_system(
            f"**Index**  {s['files']} files  ·  {s['symbols']} symbols  ·  "
            f"{s['xrefs']} xrefs  ·  {s['patterns']} patterns  ·  "
            f"{s['dirty']} dirty\n"
            f"**Session**  {ms}"
        )

    def _clear(self) -> None:
        if self._mind:
            self._mind.clear_session()
        self._chat.clear()
        self._breadcrumb.clear()
        self._depth_hint.update_from_mind(None)
        self._chat.add_system("Session cleared.")

    # ── Panel toggle ───────────────────────────────────────────────────────────

    def _toggle_panel(self, index: int) -> None:
        self._right_stack.setCurrentIndex(index)
        active_style = (
            f"QPushButton{{background:{BG3};color:{FG};"
            f"border:1px solid {BORDER};border-radius:4px 4px 0 0;"
            f"font-size:10px;padding:3px 10px;letter-spacing:1px;}}"
        )
        idle_style = (
            f"QPushButton{{background:{BG2};color:{FG_MUTE};"
            f"border:1px solid {BORDER};border-radius:4px 4px 0 0;"
            f"font-size:10px;padding:3px 10px;letter-spacing:1px;}}"
            f"QPushButton:hover{{background:{BG3};}}"
        )
        self._btn_graph.setStyleSheet(active_style if index == 0 else idle_style)
        self._btn_ensemble.setStyleSheet(active_style if index == 1 else idle_style)

    # ── Ensemble ───────────────────────────────────────────────────────────────

    def _send_ensemble(self) -> None:
        query = self._input.toPlainText().strip()
        if not query:
            return
        if not _ENSEMBLE_OK:
            self._chat.add_system("pyramid_ensemble not available.")
            return
        if self._ensemble_thread:
            self._chat.add_system("Ensemble already running…")
            return

        self._input.clear()
        self._toggle_panel(1)
        self._ensemble_panel.reset()
        self._ensemble_panel._progress.start_animation()
        self._chat.add_user(query)
        self._chat.add_system("Launching ensemble — 4 agents across 2 rounds…")
        self._status.setText("Ensemble running…")
        self._ens_btn.setEnabled(False)

        code_ctx = ""
        if self._mind and self._mind._history:
            last = self._mind._history[-1]
            code_ctx = last.answer[:1200]

        self._ensemble_thread = QThread()
        self._ensemble_worker = EnsembleWorker(query, code_ctx)
        self._ensemble_worker.moveToThread(self._ensemble_thread)
        self._ensemble_thread.started.connect(self._ensemble_worker.run)
        self._ensemble_worker.event_received.connect(self._on_ensemble_event)
        self._ensemble_worker.finished.connect(self._on_ensemble_done)
        self._ensemble_worker.finished.connect(self._ensemble_thread.quit)
        self._ensemble_thread.finished.connect(self._ensemble_thread.deleteLater)
        self._ensemble_thread.finished.connect(
            lambda: setattr(self, '_ensemble_thread', None)
        )
        self._ensemble_thread.start()

    def _on_ensemble_event(self, event: "EnsembleEvent") -> None:
        self._ensemble_panel.handle_event(event)
        if event.kind == EventKind.AGENT_DONE and event.perception:
            p = event.perception
            self._status.setText(
                f"{p.agent_emoji} {p.agent_name}  R{p.round}  ·  "
                f"{p.latency_ms:.0f}ms  ·  conf {p.confidence:.0%}"
            )

    def _on_ensemble_done(self, result: "EnsembleResult") -> None:
        self._ensemble_panel._progress.stop_animation()
        self._ens_btn.setEnabled(_ENSEMBLE_OK)
        if result is None:
            self._chat.add_system("Ensemble failed — no result returned.")
            self._status.setText("Ensemble error")
            return
        self._ensemble_panel.handle_result(result)
        # Post synthesis to chat
        if result.synthesis:
            from pyramid_mind import CodeAnswer, DisclosureLevel
            synth_answer = CodeAnswer(
                text=result.synthesis.findings,
                files_touched=[],
                symbols_touched=[],
                disclosure_level=DisclosureLevel.FULL,
                source="ensemble",
                latency_ms=result.total_ms,
            )
            self._chat.add_stratum(synth_answer)
        self._status.setText(
            f"Ensemble done  ·  {result.total_ms:.0f}ms  ·  "
            f"{len(result.conflicts)} conflict(s)"
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _set_badge(self, text: str, color: str) -> None:
        self._badge.setText(f"●  {text}")
        self._badge.setStyleSheet(f"color:{color};font-size:11px;")

    @staticmethod
    def _make_btn(text: str, bg: str, fg: str, w: int = 80) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedWidth(w)
        btn.setStyleSheet(
            f"QPushButton{{background:{bg};color:{fg};"
            f"border:1px solid {BORDER};border-radius:5px;"
            f"padding:5px 8px;font-size:11px;}}"
            f"QPushButton:hover{{background:{BG4};}}"
            f"QPushButton:disabled{{color:{FG_MUTE};}}"
        )
        return btn

    @staticmethod
    def _make_toggle_btn(text: str, active: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(24)
        style_active = (
            f"QPushButton{{background:{BG3};color:{FG};"
            f"border:1px solid {BORDER};border-radius:4px 4px 0 0;"
            f"font-size:10px;padding:3px 10px;letter-spacing:1px;}}"
        )
        style_idle = (
            f"QPushButton{{background:{BG2};color:{FG_MUTE};"
            f"border:1px solid {BORDER};border-radius:4px 4px 0 0;"
            f"font-size:10px;padding:3px 10px;letter-spacing:1px;}}"
            f"QPushButton:hover{{background:{BG3};}}"
        )
        btn.setStyleSheet(style_active if active else style_idle)
        return btn


# ── Standalone entry ──────────────────────────────────────────────────────────

def run_standalone(project_root: Optional[str] = None) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    w   = PyramidWidget(project_root=project_root)
    w.setWindowTitle("STRATUM  ▲  Pyramid Code Intelligence")
    w.resize(1300, 840)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_standalone(sys.argv[1] if len(sys.argv) > 1 else None)
