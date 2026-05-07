"""
plugins.graphics_dolphin — Dolphin Emulator GraphicsAdapter shell.

Conforms to GAME_MODE.md "EMULATION LAYER (PLUGIN-DRIVEN)":

  STATE: DORMANT      — no process, no memory, no SDK loaded
  STATE: ACTIVATION   — subprocess.Popen(dolphin_exe, ISO); attached
  STATE: ACTIVE       — render() returns the latest captured frame
  STATE: TERMINATION  — process killed, file handles released, idle

This module is a SHELL. Importing it does not start Dolphin, does not allocate
emulator memory, and does not require Dolphin to be installed. Tests can
exercise the lifecycle against a fake executable. Real frame capture (shared
memory ring buffer or named pipe) is the user's next opt-in step.

Public API:
    DolphinGraphicsAdapter(dolphin_exe, iso_path)
        .start()  → (ok, reason)
        .stop()   → idempotent
        .render(world) → bytes | str         (GraphicsAdapter Protocol)
        .is_running   → bool

Failure isolation:
    - All subprocess errors are caught; render() falls back to ASCII so a
      crashed Dolphin never crashes the host.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from typing import Any, Optional

from simcore import WorldState
from simcore_render import VisualProjector

_log = logging.getLogger(__name__)


class DolphinGraphicsAdapter:
    """Subprocess-sandboxed GraphicsAdapter for Dolphin Emulator."""

    def __init__(self, dolphin_exe: str, iso_path: str) -> None:
        self.dolphin_exe = str(dolphin_exe)
        self.iso_path    = str(iso_path)
        self._proc:    Optional[subprocess.Popen[bytes]] = None
        self._lock     = threading.Lock()
        self._fallback = VisualProjector()
        self._latest_frame: Optional[bytes] = None
        self._started_at: float = 0.0

    # ── lifecycle ───────────────────────────────────────────────────────

    def start(self) -> tuple[bool, str]:
        """Launch Dolphin as a sandboxed subprocess. Idempotent."""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return (True, "already running")
            if not os.path.exists(self.dolphin_exe):
                return (False, f"dolphin_exe not found: {self.dolphin_exe}")
            if not os.path.exists(self.iso_path):
                return (False, f"iso_path not found: {self.iso_path}")
            try:
                self._proc = subprocess.Popen(
                    [self.dolphin_exe, "--exec", self.iso_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._started_at = time.time()
                _log.info("DolphinGraphicsAdapter started pid=%s", self._proc.pid)
                return (True, "started")
            except OSError as exc:
                self._proc = None
                _log.warning("DolphinGraphicsAdapter start failed: %s", exc)
                return (False, f"OS error: {exc}")

    def stop(self) -> bool:
        """Stop Dolphin cleanly. Idempotent. Never raises."""
        with self._lock:
            if self._proc is None:
                return False
            try:
                if self._proc.poll() is None:
                    self._proc.terminate()
                    try:
                        self._proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self._proc.kill()
                        self._proc.wait(timeout=5)
            except Exception as exc:
                _log.warning("DolphinGraphicsAdapter stop error: %s", exc)
            finally:
                self._proc = None
                self._latest_frame = None
            return True

    @property
    def is_running(self) -> bool:
        proc = self._proc
        return proc is not None and proc.poll() is None

    # ── GraphicsAdapter Protocol ────────────────────────────────────────

    def render(self, world: WorldState) -> bytes | str:
        """Return latest framebuffer if active, else ASCII fallback.

        Real frame capture (shared memory / named pipe) is the user's next
        explicit integration step — not part of this shell. Until then,
        ``render`` returns the fallback projection so callers receive a
        valid, non-crashing frame at all times.
        """
        if self.is_running and self._latest_frame is not None:
            return self._latest_frame
        return self._fallback.project(world)

    # ── frame ingest hook (used by future capture pipeline) ────────────

    def _ingest_frame(self, frame: bytes) -> None:
        """Internal: accept a raw framebuffer from the capture pipeline."""
        with self._lock:
            self._latest_frame = bytes(frame)
