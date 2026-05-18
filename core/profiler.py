"""core/profiler.py — runtime boot profiler.

Phase 1.1 of the Operational Stability plan.

Lightweight, additive, zero-risk:
    * mark(phase) records a monotonic timestamp + optional RSS snapshot
    * emit_report() writes telemetry/boot_profile_<utc-iso>.json
    * never raises (best-effort everywhere)

Target metrics surfaced:
    boot_start              — process spawn (T0)
    imports_done            — Python module imports complete
    qapp_ready              — QApplication construction done
    window_constructed      — HistoryDashboard.__init__ returned
    first_tab_ready         — first lazy-built tab finished
    interactive             — UI event loop entered (Layer 2 done)
    agents_ready            — Maintenance Cortex observers started

Each mark also captures:
    elapsed_ms_since_t0     — monotonic delta
    elapsed_ms_since_prev   — delta from previous mark
    rss_mb                  — resident set size (best-effort, psutil-optional)
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from threading import RLock
from typing import Optional

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover - psutil optional
    psutil = None  # type: ignore

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BootMark:
    phase:                 str
    monotonic_s:           float
    wall_clock_iso:        str
    elapsed_ms_since_t0:   float
    elapsed_ms_since_prev: float
    rss_mb:                Optional[float] = None
    note:                  str = ""


@dataclass
class _ProfilerState:
    t0_monotonic:   float = 0.0
    t0_wall:        float = 0.0
    started:        bool = False
    marks:          list = field(default_factory=list)
    last_mark_s:    float = 0.0


class BootProfiler:
    """Singleton — there is exactly one per process."""

    _instance: Optional["BootProfiler"] = None
    _instance_lock = RLock()

    def __init__(self):
        self._state = _ProfilerState()
        self._lock = RLock()
        self._proc = None
        if psutil is not None:
            try:
                self._proc = psutil.Process(os.getpid())
            except Exception:
                self._proc = None

    @classmethod
    def get(cls) -> "BootProfiler":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ── lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        with self._lock:
            if self._state.started:
                return
            self._state.t0_monotonic = time.monotonic()
            self._state.t0_wall = time.time()
            self._state.started = True
            self._state.last_mark_s = self._state.t0_monotonic
            self._state.marks = []
        self.mark("boot_start")

    def mark(self, phase: str, *, note: str = "") -> BootMark:
        with self._lock:
            if not self._state.started:
                # Auto-start if caller forgot — same effect as deferred bootstrap
                self._state.t0_monotonic = time.monotonic()
                self._state.t0_wall = time.time()
                self._state.started = True
                self._state.last_mark_s = self._state.t0_monotonic

            now = time.monotonic()
            elapsed_t0 = (now - self._state.t0_monotonic) * 1000.0
            elapsed_prev = (now - self._state.last_mark_s) * 1000.0
            wall_iso = time.strftime(
                "%Y-%m-%dT%H:%M:%S",
                time.gmtime(self._state.t0_wall + (now - self._state.t0_monotonic)),
            )
            rss_mb = self._rss_mb()

            bm = BootMark(
                phase=phase,
                monotonic_s=now,
                wall_clock_iso=wall_iso,
                elapsed_ms_since_t0=round(elapsed_t0, 2),
                elapsed_ms_since_prev=round(elapsed_prev, 2),
                rss_mb=rss_mb,
                note=note,
            )
            self._state.marks.append(bm)
            self._state.last_mark_s = now
        _log.info("PROFILE %s +%dms (t0+%dms, rss=%sMB) %s",
                   phase, int(bm.elapsed_ms_since_prev), int(bm.elapsed_ms_since_t0),
                   f"{rss_mb:.1f}" if rss_mb is not None else "—",
                   note or "")
        return bm

    def marks(self) -> list:
        with self._lock:
            return list(self._state.marks)

    # ── psutil-best-effort ─────────────────────────────────────────────────

    def _rss_mb(self) -> Optional[float]:
        if self._proc is None:
            return None
        try:
            return self._proc.memory_info().rss / (1024 * 1024)
        except Exception:
            return None

    # ── report emission ────────────────────────────────────────────────────

    def emit_report(self, output_dir: Optional[Path] = None) -> Optional[Path]:
        """Write telemetry/boot_profile_<utc>.json. Returns the path or None.

        When the app is frozen via PyInstaller, ``__file__`` lives inside a
        temporary _MEI* unpack directory that gets wiped at exit. Resolve
        to a stable user-home path instead so the JSON survives the run.
        """
        with self._lock:
            if not self._state.started or not self._state.marks:
                return None
            marks_snapshot = list(self._state.marks)
            t0_wall = self._state.t0_wall

        try:
            if output_dir is None:
                # Frozen exe: write next to the .exe (or to ~/.stratum if
                # the exe path isn't writable). Non-frozen: project telemetry/.
                import sys as _sys
                if getattr(_sys, "frozen", False):
                    exe_parent = Path(_sys.executable).resolve().parent
                    candidate = exe_parent / "telemetry"
                    try:
                        candidate.mkdir(parents=True, exist_ok=True)
                        # Verify writable
                        probe = candidate / ".write_probe"
                        probe.write_text("x", encoding="utf-8")
                        probe.unlink()
                        output_dir = candidate
                    except Exception:
                        output_dir = Path.home() / ".stratum" / "telemetry"
                else:
                    output_dir = Path(__file__).resolve().parent.parent / "telemetry"
            output_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(t0_wall))
            out_path = output_dir / f"boot_profile_{stamp}.json"
            # click_to_interactive_ms — the canonical metric.
            # "interactive" mark is fired by core.lifecycle.on_ready() right
            # before app.exec(); we promote it as the headline number so
            # boot-optimization passes can be compared at a glance.
            click_to_interactive_ms = None
            for m in marks_snapshot:
                if m.phase == "interactive":
                    click_to_interactive_ms = m.elapsed_ms_since_t0
                    break

            phase_table = {m.phase: m.elapsed_ms_since_t0 for m in marks_snapshot}
            payload = {
                "t0_wall_iso":              time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0_wall)
                ),
                "click_to_interactive_ms":  click_to_interactive_ms,
                "marks":                    [asdict(m) for m in marks_snapshot],
                "phase_t0_ms":              phase_table,
                "total_elapsed_ms":         marks_snapshot[-1].elapsed_ms_since_t0,
                "peak_rss_mb":              max(
                    (m.rss_mb for m in marks_snapshot if m.rss_mb is not None),
                    default=None,
                ),
                "phase_count":              len(marks_snapshot),
            }
            out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            _log.info("boot profile written → %s", out_path)
            return out_path
        except Exception as e:
            _log.warning("boot profile emit failed: %s", e)
            return None


def get_profiler() -> BootProfiler:
    return BootProfiler.get()


def mark(phase: str, *, note: str = "") -> BootMark:
    return get_profiler().mark(phase, note=note)
