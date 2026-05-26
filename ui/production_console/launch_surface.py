"""ui/production_console/launch_surface.py — BUILD-024 Reactive Launch Surface.

Single coherent reactive primary view. Designed for instant paint
(<300ms target), continuous breathing background tied to real CPU, and
sub-50ms keystroke acknowledgment.

Layout:
  ┌─────────────────────────────────────────────────────────┐
  │  ◇ DBOMBLOCAL · awake                          [trace]  │
  ├─────────────────────────────────────────────────────────┤
  │  intent input — always interactive                      │
  ├──────────────────────────────────────┬──────────────────┤
  │  output stream (live)                │ artifact preview │
  │                                       │                  │
  │                                       │                  │
  ├──────────────────────────────────────┴──────────────────┤
  │  minimal status: 3 sessions · 7 artifacts · 1.2 KB/s    │
  └─────────────────────────────────────────────────────────┘

Behaviors:
- Constructor returns in <50ms (no blocking imports beyond Qt)
- Subscribes to LiveStreamBus on QTimer.singleShot(0, …) — not in __init__
- Per-keystroke pulse in the intent field via textChanged
- Breathing background driven by ReactivePresenceLayer v1 (already running)
- Streams worker events into output area via Qt queued signal
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QColor, QPalette, QFont, QPainter, QBrush
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)

_log = logging.getLogger(__name__)


# Pip-Boy palette (consistent with build-020 chamber)
BG       = "#06091c"
BG2      = "#0a0f28"
BORDER   = "#1e2e5c"
ACCENT   = "#28e6ff"
ACCENT2  = "#ff2d92"
OK       = "#5af26f"
WARN     = "#f0a030"
FAIL     = "#c04868"
DIM      = "#5070a0"


class LaunchSurface(QWidget):
    """The primary reactive surface. Lives inside ProductionConsolePanel
    as the default view (trace mode reveals sub-tabs).
    """

    request_trace_toggle = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stream_subscribed = False
        self._keystroke_count = 0
        self._intent_submitted_count = 0
        self.setStyleSheet(f"LaunchSurface {{ background:{BG}; }}")
        self._build_ui()
        # Defer ALL non-essential work to first paint so the window
        # appears instantly (PHASE 1 directive).
        QTimer.singleShot(0, self._post_paint_init)

    # ── UI build (cheap; <50ms construction) ──────────────────────────
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)

        # ── Top bar ──
        top = QHBoxLayout()
        title = QLabel("◇  DBOMBLOCAL  ·  awake")
        title.setStyleSheet(
            f"color:{ACCENT}; font-weight:bold; font-size:14px;"
            f" letter-spacing:3px;"
        )
        top.addWidget(title)
        top.addStretch()
        # BUILD-029A — SYSTEM SYNOPSIS button (read-only truth mirror)
        self._synopsis_btn = QPushButton("⌬ SYNOPSIS")
        self._synopsis_btn.setToolTip(
            "Run the SystemSynopsisModule — read-only observation of file DNA, "
            "runtime state, capability map, honesty report, and system health. "
            "Does NOT alter execution flow."
        )
        self._synopsis_btn.setStyleSheet(self._btn_style(ACCENT))
        self._synopsis_btn.clicked.connect(self._open_synopsis)
        top.addWidget(self._synopsis_btn)

        # Trace toggle (collapsed sub-tabs revealed only here)
        self._trace_btn = QPushButton("⌗ TRACE")
        self._trace_btn.setToolTip(
            "Reveal worker logs, validation chains, backend diagnostics. "
            "Hidden by default per BUILD-024 directive."
        )
        self._trace_btn.setStyleSheet(self._btn_style(DIM))
        self._trace_btn.clicked.connect(self.request_trace_toggle)
        top.addWidget(self._trace_btn)
        root.addLayout(top)

        # ── Intent input ──
        self._intent_edit = QLineEdit()
        self._intent_edit.setPlaceholderText(
            "what shall we make? — workers will execute real backends and validate every artifact"
        )
        self._intent_edit.setStyleSheet(
            f"QLineEdit {{ background:{BG}; color:{OK};"
            f" border:2px solid {ACCENT}; border-radius:6px;"
            f" padding:10px 14px; font-family:Consolas,monospace;"
            f" font-size:13px; }}"
            f"QLineEdit:focus {{ border:2px solid {ACCENT2}; }}"
        )
        self._intent_edit.textChanged.connect(self._on_keystroke)
        self._intent_edit.returnPressed.connect(self._on_submit)
        # Acknowledgment pulse bar — sits flush under the intent edit,
        # animates briefly on each keystroke
        self._ack_bar = QFrame()
        self._ack_bar.setFixedHeight(2)
        self._ack_bar.setStyleSheet(
            f"QFrame {{ background:{BG2}; border-radius:1px; }}"
        )
        root.addWidget(self._intent_edit)
        root.addWidget(self._ack_bar)

        # ── Body: output stream | artifact preview ──
        body = QSplitter(Qt.Orientation.Horizontal)
        body.setHandleWidth(2)
        body.setStyleSheet(
            f"QSplitter::handle {{ background:{BORDER}; }}"
        )

        # Output stream
        self._stream_view = QPlainTextEdit()
        self._stream_view.setReadOnly(True)
        self._stream_view.setPlaceholderText(
            "live output stream — worker events arrive here"
        )
        self._stream_view.setStyleSheet(
            f"QPlainTextEdit {{ background:{BG}; color:{OK};"
            f" border:1px solid {BORDER}; border-radius:6px;"
            f" font-family:Consolas,monospace; font-size:11px;"
            f" padding:10px; }}"
        )
        body.addWidget(self._stream_view)

        # Artifact preview
        self._preview_panel = _ArtifactPreviewPanel()
        body.addWidget(self._preview_panel)

        body.setStretchFactor(0, 3)
        body.setStretchFactor(1, 2)
        root.addWidget(body, 1)

        # ── Status strip ──
        self._status = QLabel("waking up…")
        self._status.setStyleSheet(
            f"color:{DIM}; font-family:Consolas,monospace; font-size:11px;"
            f" padding:4px 0px;"
        )
        root.addWidget(self._status)

    def _btn_style(self, color: str) -> str:
        return (
            f"QPushButton {{ background:{BG2}; color:{color};"
            f" border:1px solid {color}; border-radius:4px;"
            f" padding:5px 12px; font-weight:bold; font-size:10px; }}"
            f"QPushButton:hover {{ background:{color}; color:{BG}; }}"
        )

    # ── Phase 2/3 — subscribe to runtime AFTER first paint ────────────
    def _post_paint_init(self) -> None:
        """Wire live runtime signals. Runs on the UI thread but is
        called via QTimer.singleShot(0, …) so the first paint is done
        before any of this happens."""
        if self._stream_subscribed:
            return
        # Live event bus
        try:
            from engine.live_stream import get_live_stream
            bus = get_live_stream()
            bus.connect_qt(self._on_live_event)
            self._stream_subscribed = True
        except Exception as e:
            _log.debug("live_stream subscribe failed: %s", e)
        # Status strip refresh tick — cheap (1Hz)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._refresh_status_strip)
        self._status_timer.start()
        # Acknowledge the system is awake
        self._append_stream(f"⌬ awake · {time.strftime('%H:%M:%S')}")
        # First status fill
        QTimer.singleShot(150, self._refresh_status_strip)

    # ── BUILD-029A — SystemSynopsisModule launcher ────────────────────
    def _open_synopsis(self) -> None:
        """Run SystemSynopsisModule on a worker thread + show the result.
        Never blocks UI; never crashes if the module fails."""
        try:
            from runtime.deferred_loader import DeferredWorkspaceLoader
            from engine.system_synopsis import generate_synopsis_cached
        except Exception as e:
            self._append_stream(f"  ✗ synopsis launcher unavailable: {e}")
            return

        self._append_stream(f"  {time.strftime('%H:%M:%S')}  ⌬ generating synopsis…")

        def _run():
            try:
                return generate_synopsis_cached()
            except Exception as e:
                return {"error": f"synopsis generation failed: {e}"}

        def _done(result):
            try:
                self._show_synopsis_dialog(result)
            except Exception as e:
                self._append_stream(f"  ✗ synopsis display failed: {e}")

        DeferredWorkspaceLoader.run(_run, on_done=_done, name="system_synopsis")

    def _show_synopsis_dialog(self, synopsis: dict) -> None:
        """Open a modal dialog with the synopsis JSON. Read-only."""
        import json
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QPlainTextEdit, QPushButton
        dlg = QDialog(self)
        dlg.setWindowTitle("⌬  SYSTEM SYNOPSIS — read-only truth mirror")
        dlg.resize(900, 620)
        v = QVBoxLayout(dlg)
        # Compact summary line
        from PyQt6.QtWidgets import QLabel
        try:
            fc = len(synopsis.get("file_dna") or [])
            cap_total = len((synopsis.get("capability_map") or {}))
            cap_avail = sum(1 for c in (synopsis.get("capability_map") or {}).values()
                              if isinstance(c, dict) and c.get("status") == "AVAILABLE")
            health = ((synopsis.get("system_health") or {}).get("score") or 0.0)
            hr = synopsis.get("honesty_report") or {}
            orph = len(hr.get("orphans") or [])
            dup  = len(hr.get("duplicates") or [])
            stubs= len(hr.get("stubs_detected") or [])
            missing = len(hr.get("missing_dependencies") or [])
            summary = (f"files: {fc}  ·  capabilities: {cap_avail}/{cap_total}  ·  "
                       f"health: {health:.2f}  ·  orphans: {orph}  ·  dup: {dup}  ·  "
                       f"stubs: {stubs}  ·  missing-deps: {missing}  ·  "
                       f"{synopsis.get('duration_ms', 0):.0f}ms")
        except Exception:
            summary = "synopsis computed"
        lbl = QLabel(summary)
        lbl.setStyleSheet(f"color:{ACCENT}; font-family:Consolas,monospace; "
                          f"font-size:11px; padding:6px;")
        v.addWidget(lbl)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setStyleSheet(
            f"QPlainTextEdit {{ background:{BG}; color:{OK};"
            f" border:1px solid {BORDER}; border-radius:5px;"
            f" font-family:Consolas,monospace; font-size:10px; padding:8px; }}"
        )
        try:
            view.setPlainText(json.dumps(synopsis, indent=2, default=str))
        except Exception as e:
            view.setPlainText(f"display error: {e}")
        v.addWidget(view, 1)
        close = QPushButton("close")
        close.setStyleSheet(self._btn_style(DIM))
        close.clicked.connect(dlg.accept)
        v.addWidget(close)
        dlg.exec()

    # ── Keystroke acknowledgment ──────────────────────────────────────
    def _on_keystroke(self, text: str) -> None:
        """Per-keystroke micro-acknowledgment. Lightweight: just color
        the ack bar briefly."""
        self._keystroke_count += 1
        # Color the ack bar — pulse intensity by recent keystroke rate
        try:
            self._ack_bar.setStyleSheet(
                f"QFrame {{ background:{ACCENT}; border-radius:1px; }}"
            )
            # Fade back to base after 220ms
            QTimer.singleShot(220, self._reset_ack)
        except Exception:
            pass

    def _reset_ack(self) -> None:
        try:
            self._ack_bar.setStyleSheet(
                f"QFrame {{ background:{BG2}; border-radius:1px; }}"
            )
        except Exception:
            pass

    # ── Intent submission ─────────────────────────────────────────────
    def _on_submit(self) -> None:
        text = self._intent_edit.text().strip()
        if not text:
            return
        self._intent_edit.clear()
        self._intent_submitted_count += 1
        ts = time.strftime("%H:%M:%S")
        self._append_stream(f"▸ {ts}  intent:  {text[:120]}")
        # Push to LiveStreamBus so any subscriber sees it
        try:
            from engine.live_stream import get_live_stream
            get_live_stream().emit_event("intent_received", {
                "text": text,
                "submission_count": self._intent_submitted_count,
            })
        except Exception:
            pass
        # BUILD-029: dispatch through ClosedLoopEngine — every intent
        # MUST execute the full INTENT → BIAS → GENERATE × N → CQI →
        # COMPARE → FEEDBACK → REGEN → SELECT → GUARANTEE loop.
        try:
            from engine.closed_loop import get_closed_loop_engine
            from runtime.deferred_loader import DeferredWorkspaceLoader
            engine = get_closed_loop_engine()
            # Run async — bus events stream to this surface
            DeferredWorkspaceLoader.run(
                lambda: engine.run(text, candidate_count=4),
                on_done=None,
                name="closed_loop_intent",
            )
        except Exception as e:
            # P0: ClosedLoopEngine → WorkerRouter is the SINGLE execution
            # path. No alternate path may report a completion without real
            # worker execution. Surface the dispatch failure explicitly —
            # never fall back to a non-worker (scoring-only) responder.
            self._append_stream(
                f"  ✗ UNAVAILABLE_REAL_EXECUTION: dispatch failed: {e}")

    # ── Live event handler ────────────────────────────────────────────
    def _on_live_event(self, event: dict) -> None:
        """Bus event arrived. Append to stream and update preview if
        a new artifact landed."""
        kind = event.get("kind", "")
        payload = event.get("payload", {})
        ts = time.strftime("%H:%M:%S")

        if kind == "worker_running":
            self._append_stream(
                f"  {ts}  worker {payload.get('worker_name','?')} ▸ RUNNING "
                f"realm={payload.get('realm','?')}"
            )
        elif kind == "worker_validating":
            self._append_stream(
                f"  {ts}  worker {payload.get('worker_name','?')} ▸ VALIDATING"
            )
        elif kind == "worker_ready":
            self._append_stream(
                f"  {ts}  ✓ {payload.get('worker_name','?')} READY · "
                f"score {payload.get('overall_score','?')} · "
                f"{payload.get('artifact_count',0)} artifact(s)"
            )
        elif kind == "worker_fail":
            err = (payload.get('error') or '')[:140]
            self._append_stream(
                f"  {ts}  ✗ {payload.get('worker_name','?')} FAIL · {err}"
            )
        elif kind == "intent_received":
            pass     # already logged on submit
        elif kind == "artifact_registered":
            self._append_stream(
                f"  {ts}  ◐ artifact: {payload.get('realm','?')} · "
                f"{payload.get('size_bytes',0)//1024} KB"
            )
            self._preview_panel.refresh_to_latest()
        elif kind == "preview_registered":
            self._preview_panel.refresh_to_latest()
        elif kind == "gate_denied":
            self._append_stream(
                f"  {ts}  ⊥ gate refused realm={payload.get('realm','?')} · "
                f"{payload.get('remediation','no remediation')[:120]}"
            )
        # BUILD-029 — Closed Loop events
        elif kind == "closed_loop_started":
            self._append_stream(
                f"  {ts}  🜂 closed-loop opened · '{payload.get('intent_text','')[:80]}'"
            )
        elif kind == "closed_loop_bias_injected":
            entropy = payload.get('entropy_adjustment', 0.0)
            if payload.get('has_signal'):
                self._append_stream(
                    f"  {ts}  ◈ bias injected (cycle {payload.get('cycle','?')}) "
                    f"entropy {entropy:+.2f}"
                )
            else:
                self._append_stream(
                    f"  {ts}  ◈ cycle {payload.get('cycle','?')} · no prior bias"
                )
        elif kind == "closed_loop_cycle_complete":
            regen = " · regen" if payload.get('needs_regen') else ""
            self._append_stream(
                f"  {ts}  ⌬ cycle {payload.get('cycle','?')} · "
                f"{payload.get('candidate_count','?')} candidates · "
                f"best {payload.get('best_score','?')}{regen}"
            )
        elif kind == "closed_loop_completed":
            self._append_stream(
                f"  {ts}  ✦ loop complete · {payload.get('cycle_count','?')} cycles · "
                f"{payload.get('total_candidates','?')} candidates · "
                f"winner {payload.get('winning_score','?')} · "
                f"locked traits {payload.get('locked_traits',0)}"
            )
        elif kind == "closed_loop_blocked":
            self._append_stream(
                f"  {ts}  ⊥ loop BLOCKED · {payload.get('reasons',[])}"
            )
        # BUILD-028 — Comparative Intelligence events
        elif kind == "compare_candidate":
            i = int(payload.get('i', 0)) + 1
            n = payload.get('n', '?')
            self._append_stream(
                f"  {ts}  ◇ comparing candidate {i}/{n}  ·  blended "
                f"{payload.get('blended','?')}"
            )
        elif kind == "compare_trait_winner":
            ci = int(payload.get('candidate', 0)) + 1
            self._append_stream(
                f"  {ts}  ◇ {payload.get('dimension','?')} strongest in "
                f"candidate {ci}  ({payload.get('score','?')})"
            )
        elif kind == "compare_selected":
            ci = int(payload.get('chosen_index', 0)) + 1
            self._append_stream(
                f"  {ts}  ◆ selected candidate {ci} · "
                f"score {payload.get('chosen_score','?')} · "
                f"hybrid_targets {payload.get('hybrid_targets',0)}"
            )
            rat = payload.get('rationale', '')
            if rat:
                self._append_stream(f"      → {rat[:200]}")
        elif kind == "noncanonical_warning":
            self._append_stream(
                f"  {ts}  ⚠ noncanonical layer(s) detected: "
                f"{payload.get('count',0)} · {payload.get('layers',[])}"
            )
        # BUILD-027A — Creative Intelligence events
        elif kind == "cqi_scored":
            self._append_stream(
                f"  {ts}  ☼ CQI {payload.get('composite','?')} · "
                f"atmos {payload.get('atmosphere','?')} · "
                f"emo {payload.get('emotional_impact','?')} · "
                f"cinematic {payload.get('cinematic_intensity','?')} · "
                f"harmony {payload.get('visual_harmony','?')} · "
                f"memorable {payload.get('memorability','?')}"
            )
        elif kind == "oracle_advisory":
            line = payload.get("one_line", "")
            self._append_stream(
                f"  {ts}  ◯ Oracle [{payload.get('ambition_band','?')} "
                f"{payload.get('ambition_score','?')}] · "
                f"gaps:{payload.get('gap_count',0)} recs:{payload.get('rec_count',0)}"
            )
            if line:
                self._append_stream(f"      → {line[:160]}")
        # BUILD-026 — Creative Composition events
        elif kind == "composition_planned":
            self._append_stream(
                f"  {ts}  ⌬ composition · {payload.get('pipeline_kind','?')} · "
                f"{payload.get('scene_count','?')} scenes · "
                f"realms: {' → '.join(payload.get('realm_sequence',[]))}"
            )
        elif kind == "master_package_ready":
            self._append_stream(
                f"  {ts}  ◆ master package · {payload.get('artifact_count',0)} artifacts · "
                f"score {payload.get('package_score','?')} · "
                f"per-realm {payload.get('per_realm_counts',{})}"
            )
        # BUILD-025 — Production Guarantee Layer events
        elif kind == "guarantee_validated":
            self._append_stream(
                f"  {ts}  ✓ GUARANTEED · score {payload.get('match_score','?')} · "
                f"{payload.get('valid_artifacts',0)} artifact(s)"
                + (f" · {payload.get('repair_passes',0)} repair pass(es)"
                   if payload.get('repair_passes',0) > 0 else "")
            )
        elif kind == "guarantee_repairing":
            self._append_stream(
                f"  {ts}  ⟳ repair pass {payload.get('pass','?')} · "
                f"category={payload.get('category','?')} · "
                f"strategy={payload.get('strategy','?')}"
            )
        elif kind == "guarantee_failed":
            self._append_stream(
                f"  {ts}  ✗ GUARANTEE FAILED · score {payload.get('match_score','?')} · "
                f"category={payload.get('failure_category','?')}"
            )
            rem = payload.get('remediation','')
            if rem:
                self._append_stream(f"      → remediation: {rem[:140]}")
        elif kind == "contract_rejected":
            self._append_stream(
                f"  {ts}  ⊘ contract rejected · "
                f"{payload.get('remediation','')[:140]}"
            )
        else:
            # Unknown event — silently ignore (no clutter in primary view)
            pass

    def _append_stream(self, line: str) -> None:
        try:
            self._stream_view.appendPlainText(line)
            # Cap stream depth: keep last ~400 lines
            doc = self._stream_view.document()
            if doc.blockCount() > 500:
                cursor = self._stream_view.textCursor()
                cursor.movePosition(cursor.MoveOperation.Start)
                for _ in range(100):
                    cursor.select(cursor.SelectionType.LineUnderCursor)
                    cursor.removeSelectedText()
                    cursor.deleteChar()
        except Exception:
            pass

    # ── Status strip ──────────────────────────────────────────────────
    def _refresh_status_strip(self) -> None:
        bits: list[str] = []
        try:
            from engine.production_core import get_production_core
            stats = get_production_core().stats()
            bits.append(f"sessions:{stats['total_sessions']}")
        except Exception:
            pass
        try:
            from engine.artifact_lineage import get_artifact_lineage
            ls = get_artifact_lineage().stats()
            bits.append(f"artifacts:{ls['recent_count']}·{ls['total_bytes']//1024}KB")
        except Exception:
            pass
        try:
            from engine.worker_router import get_worker_router
            rs = get_worker_router().stats()
            bits.append(f"routes:{rs['route_count']}·dispatch:{rs['dispatch_count']}")
        except Exception:
            pass
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=None)
            bits.append(f"cpu:{cpu:.0f}%")
        except Exception:
            pass
        bits.append(f"keystrokes:{self._keystroke_count}")
        bits.append(f"intents:{self._intent_submitted_count}")
        self._status.setText("   ·   ".join(bits) or "…")


class _ArtifactPreviewPanel(QFrame):
    """Right-side artifact preview. Shows the most recent artifact's
    preview (thumbnail / waveform summary / text excerpt). Auto-refreshes
    when LaunchSurface signals a new artifact landed."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet(
            f"_ArtifactPreviewPanel {{ background:{BG2};"
            f" border:1px solid {BORDER}; border-radius:6px; }}"
        )
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(6)
        title = QLabel("◐  LATEST ARTIFACT")
        title.setStyleSheet(
            f"color:{ACCENT2}; font-weight:bold; font-size:11px;"
            f" letter-spacing:2px;"
        )
        v.addWidget(title)
        self._meta_lbl = QLabel("waiting for first artifact…")
        self._meta_lbl.setStyleSheet(
            f"color:{DIM}; font-family:Consolas,monospace; font-size:11px;"
        )
        self._meta_lbl.setWordWrap(True)
        v.addWidget(self._meta_lbl)
        self._excerpt = QPlainTextEdit()
        self._excerpt.setReadOnly(True)
        self._excerpt.setStyleSheet(
            f"QPlainTextEdit {{ background:{BG}; color:{OK};"
            f" border:1px solid {BORDER}; border-radius:4px;"
            f" font-family:Consolas,monospace; font-size:10px;"
            f" padding:6px; }}"
        )
        v.addWidget(self._excerpt, 1)

    def refresh_to_latest(self) -> None:
        try:
            from engine.preview_registry import get_preview_registry
            recent = get_preview_registry().recent(1)
            if not recent:
                return
            p = recent[0]
            name = Path(p.artifact_path).name
            self._meta_lbl.setText(
                f"[{p.realm}]  {name}  ·  {p.preview_kind}  ·  {p.backend}"
            )
            # Render the per-kind summary
            summary = p.summary or {}
            if p.preview_kind == "thumbnail":
                line_set = [
                    f"path: {p.artifact_path}",
                    f"original size: {summary.get('original_width')}x{summary.get('original_height')}",
                    f"thumbnail: {p.preview_path or '(inline)'}",
                ]
            elif p.preview_kind == "waveform":
                env = summary.get("peak_envelope") or []
                line_set = [
                    f"sample_rate: {summary.get('sample_rate')} Hz",
                    f"channels: {summary.get('channels')}",
                    f"duration: {summary.get('duration_s')} s",
                    "envelope (64 buckets, 0..1):",
                    " ".join(f"{v:.2f}" for v in env[:32]),
                    " ".join(f"{v:.2f}" for v in env[32:64]),
                ]
            elif p.preview_kind == "symbol_summary":
                syms = summary.get("symbols") or []
                line_set = [
                    f"lines: {summary.get('line_count')}",
                    f"symbols ({len(syms)}):",
                    *[f"  {s}" for s in syms[:20]],
                    "",
                    "head:",
                    summary.get("head", "")[:600],
                ]
            elif p.preview_kind == "text_excerpt":
                line_set = [
                    f"chars: {summary.get('char_count','?')}",
                    f"keys: {summary.get('json_keys','—')}" if 'json_keys' in summary else "",
                    "",
                    summary.get("excerpt", "")[:1200],
                ]
            elif p.preview_kind == "poster_frame":
                line_set = [
                    f"poster: {p.preview_path or '—'}",
                    f"extracted at: {summary.get('extracted_at', 0)} s",
                ]
            else:
                line_set = [str(summary)[:1200]]
            self._excerpt.setPlainText("\n".join(line_set))
        except Exception as e:
            self._meta_lbl.setText(f"preview refresh error: {e}")
