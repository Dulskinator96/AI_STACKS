"""engine/live_stream.py — BUILD-024 live event stream bus.

Process-wide Qt signal channel for worker/router/cognitive_core to push
live events into the reactive surface. Replaces polling with push.

The LiveStreamBus is a QObject singleton that:
  · receives `emit_event(kind, payload)` from any thread (queued connection)
  · re-emits `event_received(dict)` signal on the UI thread
  · maintains a bounded ring buffer for late subscribers (60 events)

Event kinds (canonical):
  · intent_received       — operator just submitted an intent
  · worker_running        — worker started executing
  · worker_validating     — worker entered VALIDATING state
  · worker_ready          — worker produced valid artifact(s)
  · worker_fail           — worker produced no valid artifact
  · artifact_registered   — new artifact landed in lineage
  · preview_registered    — preview generated for a new artifact
  · gate_denied           — WorkerRouter gate refused dispatch
  · system_pulse          — periodic heartbeat (1Hz from chamber)
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)


class LiveStreamBus:
    """Process-wide event bus. Qt-aware but degrades gracefully when Qt
    is not available (e.g., unit tests)."""

    _MAX_BUFFER = 120

    def __init__(self):
        self._buffer: deque = deque(maxlen=self._MAX_BUFFER)
        self._lock = threading.Lock()
        self._subscribers: list = []
        self._signals = None
        try:
            from PyQt6.QtCore import QObject, pyqtSignal
            class _Sig(QObject):
                event_received = pyqtSignal(dict)
            self._signals = _Sig()
        except Exception:
            _log.debug("Qt not available — LiveStreamBus running headless")
        # Register
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.live_stream", self)
        except Exception:
            pass

    def emit_event(self, kind: str, payload: Optional[dict] = None) -> None:
        """Push an event into the stream. Safe from any thread."""
        event = {
            "kind":    kind,
            "ts":      time.time(),
            "payload": dict(payload or {}),
        }
        with self._lock:
            self._buffer.append(event)
            subs = list(self._subscribers)
        # Qt signal: queued auto-cross-thread
        if self._signals is not None:
            try:
                self._signals.event_received.emit(event)
            except Exception:
                pass
        # Direct subscribers (non-Qt callers)
        for cb in subs:
            try:
                cb(event)
            except Exception:
                pass

    def subscribe(self, callback: Callable[[dict], None]) -> None:
        """Register a non-Qt subscriber."""
        with self._lock:
            self._subscribers.append(callback)

    def connect_qt(self, slot) -> None:
        """Connect a Qt slot to the event_received signal."""
        if self._signals is None:
            return
        try:
            self._signals.event_received.connect(slot)
        except Exception as e:
            _log.debug("connect_qt failed: %s", e)

    def recent(self, n: int = 30, kind: Optional[str] = None) -> list:
        with self._lock:
            buf = list(self._buffer)
        if kind:
            buf = [e for e in buf if e["kind"] == kind]
        return buf[-n:]

    def stats(self) -> dict:
        with self._lock:
            return {
                "buffer_size":   len(self._buffer),
                "buffer_cap":    self._MAX_BUFFER,
                "subscriber_count": len(self._subscribers),
            }


_INSTANCE: Optional[LiveStreamBus] = None


def get_live_stream() -> LiveStreamBus:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = LiveStreamBus()
    return _INSTANCE
