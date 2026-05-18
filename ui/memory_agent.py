"""ui/memory_agent.py — autonomous memory daemon (extracted from app.py).

Relocated 2026-05-17 per MODULE_DECOMPOSITION_PLAN.md Phase A (Tier 1 pilot).
Behavior preserved verbatim from the original app.py:6850-6918 implementation.

Cross-module references (_MP_BRIDGE_OK, _mp_bridge) are resolved via a late
import inside ``run()`` to break the import cycle introduced by relocating
this class out of app.py.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

_log = logging.getLogger(__name__)


class MemoryAgent(QThread):
    """Autonomous memory daemon. Runs in background — sleeps most of its life.

    Tick schedule:
      every 60s   → emit health() snapshot to UI
      every 10min → prune stale palace locks (>1h old)
      every 30min → mine ~/.stratum/stratum.log tail into palace (if changed)
    """

    health_updated = pyqtSignal(dict)
    status         = pyqtSignal(str)
    pruned         = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        self._last_log_mtime = 0.0

    def stop(self):
        self._running = False
        self.requestInterruption()

    def run(self):
        from app import _MP_BRIDGE_OK, _mp_bridge

        if not _MP_BRIDGE_OK:
            self.status.emit("MemPalace bridge unavailable")
            return
        last_prune = 0.0
        last_mine  = 0.0
        last_health = 0.0
        log_path = Path.home() / ".stratum" / "stratum.log"
        while self._running and not self.isInterruptionRequested():
            now = time.time()
            try:
                if now - last_health > 60:
                    self.health_updated.emit(_mp_bridge.health())
                    last_health = now
                if now - last_prune > 600:
                    pruned = _mp_bridge.prune_stale_locks(older_than_s=3600)
                    if pruned:
                        self.pruned.emit(pruned)
                        self.status.emit(f"pruned {pruned} stale locks")
                    last_prune = now
                if now - last_mine > 1800 and log_path.is_file():
                    try:
                        mtime = log_path.stat().st_mtime
                    except Exception as e:
                        _log.warning(f'caught exception: {e}')
                        mtime = 0.0
                    if mtime > self._last_log_mtime:
                        try:
                            tail = log_path.read_text(encoding="utf-8", errors="replace")[-8000:]
                            if _mp_bridge.mine_text(tail, source="stratum-log"):
                                self._last_log_mtime = mtime
                                self.status.emit("mined log tail")
                        except Exception as e:
                            _log.warning(f'caught exception: {e}')
                    last_mine = now
            except Exception as exc:
                self.status.emit(f"agent error: {exc}")
            for _ in range(20):
                if not self._running or self.isInterruptionRequested():
                    return
                self.msleep(500)
