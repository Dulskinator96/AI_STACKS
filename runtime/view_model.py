"""runtime/view_model.py — RULE 4: VIEW-MODEL SEPARATION + RULE 8: RECEIPT ISOLATION.

RuntimeStateSnapshot
    Frozen dataclass — JSON-safe runtime state at one instant.
    Built once per projection tick (default 1Hz). UI binds against
    snapshots, never against live orchestration internals.

WorkspaceStateBridge
    QObject thin wrapper that emits Qt signals carrying snapshots.
    Lives in the Qt layer. Tabs connect; runtime emits.

ObserverProjectionLayer
    Aggregates the 11 maintenance observers + recent receipt counts
    into the snapshot. Summarized + throttled — never raw receipts
    pushed to UI. Receipts continue to land on disk via receipt_engine.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeStateSnapshot:
    """JSON-safe snapshot of runtime state at one instant. UI reads,
    never writes."""
    ts:                 float
    state:              str                       # SystemState name
    cpu_percent:        float
    rss_mb:             float
    uptime_s:           float
    observer_count:     int
    observer_outcomes:  dict                      # {observer_name: latest_outcome}
    issue_count:        int
    receipt_count_total: int
    receipt_count_last_minute: int
    registered_services: list                     # capability names
    bootstrap_phases_complete: int                # 0..7
    intent_dispatch_count: int                    # since boot
    workspace_count_active: int                   # dynamic + boot tabs built
    last_intent: str
    last_receipt_task: str

    def to_dict(self) -> dict:
        return asdict(self)


class WorkspaceStateBridge:
    """Qt-aware projection emitter. Lazily imports PyQt6 so the runtime
    package stays Model-layer when no UI is attached.

    Usage:
        bridge = WorkspaceStateBridge()
        bridge.snapshot_ready.connect(my_tab.on_snapshot)
        bridge.start(interval_ms=1000)
    """

    def __init__(self):
        self._timer = None
        self._signals = None
        self._projection = ObserverProjectionLayer()

    def _ensure_qt(self):
        if self._signals is not None:
            return
        try:
            from PyQt6.QtCore import QObject, QTimer, pyqtSignal

            class _Sig(QObject):
                snapshot_ready = pyqtSignal(object)   # RuntimeStateSnapshot
                workspace_event = pyqtSignal(str, dict)   # name, payload

            self._signals = _Sig()
            self._timer_cls = QTimer
        except Exception as e:
            _log.warning("WorkspaceStateBridge Qt unavailable: %s", e)

    def start(self, interval_ms: int = 1000) -> None:
        self._ensure_qt()
        if self._signals is None:
            return
        if self._timer is not None:
            return
        self._timer = self._timer_cls()
        self._timer.timeout.connect(self._tick)
        self._timer.start(interval_ms)
        _log.debug("WorkspaceStateBridge started @ %dms", interval_ms)

    def stop(self) -> None:
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass
            self._timer = None

    def connect_snapshot(self, slot) -> None:
        self._ensure_qt()
        if self._signals is not None:
            self._signals.snapshot_ready.connect(slot)

    def emit_workspace_event(self, name: str, payload: dict) -> None:
        self._ensure_qt()
        if self._signals is not None:
            try:
                self._signals.workspace_event.emit(name, payload)
            except Exception:
                pass

    def _tick(self) -> None:
        try:
            snap = self._projection.build_snapshot()
            self._signals.snapshot_ready.emit(snap)
        except Exception as e:
            _log.debug("WorkspaceStateBridge tick failed: %s", e)


class ObserverProjectionLayer:
    """Builds RuntimeStateSnapshot from runtime state.

    Reads cortex.runtime.last_outcomes (existing pattern), state_manager
    (existing), system metrics, and a small receipts tail. Designed to
    fail-closed — any source missing returns a degraded but valid
    snapshot. Never raises to the caller.
    """

    def __init__(self):
        self._boot_ts = time.time()
        self._receipt_log_path = Path(__file__).resolve().parent.parent / \
            "telemetry" / "execution_receipts.jsonl"
        self._intent_count = 0
        self._workspace_count = 0
        self._last_intent = ""
        self._last_receipt_task = ""

    def increment_intent(self, intent: str) -> None:
        self._intent_count += 1
        self._last_intent = (intent or "")[:80]

    def increment_workspace(self) -> None:
        self._workspace_count += 1

    def build_snapshot(self) -> RuntimeStateSnapshot:
        from runtime.singleton_registry import get_registry
        reg = get_registry()

        cpu = rss = 0.0
        try:
            import psutil
            p = psutil.Process()
            cpu = float(p.cpu_percent(interval=None))
            rss = float(p.memory_info().rss) / (1024 * 1024)
        except Exception:
            pass

        state = "UNKNOWN"
        try:
            sm = reg.get("core.state_manager")
            if sm and hasattr(sm, "current"):
                cur = sm.current
                state = cur.name if hasattr(cur, "name") else str(cur)
        except Exception:
            pass

        observer_outcomes: dict[str, str] = {}
        issue_count = 0
        try:
            cortex = reg.get("maintenance.cortex")
            if cortex and hasattr(cortex, "runtime") and hasattr(cortex.runtime, "last_outcomes"):
                lo = cortex.runtime.last_outcomes or {}
                observer_outcomes = {k: str(v)[:40] for k, v in lo.items()}
                issue_count = sum(
                    1 for v in lo.values()
                    if str(v).lower().startswith(("fail", "error", "degraded"))
                )
        except Exception:
            pass

        receipt_total, receipt_recent, last_task = self._sample_receipts()

        snap = RuntimeStateSnapshot(
            ts=time.time(),
            state=state,
            cpu_percent=cpu,
            rss_mb=rss,
            uptime_s=time.time() - self._boot_ts,
            observer_count=len(observer_outcomes),
            observer_outcomes=observer_outcomes,
            issue_count=issue_count,
            receipt_count_total=receipt_total,
            receipt_count_last_minute=receipt_recent,
            registered_services=sorted(reg.snapshot().get("registered", [])),
            bootstrap_phases_complete=len([
                n for n in reg.names()
                if n.startswith("bootstrap.phase_") and reg.has(n)
            ]),
            intent_dispatch_count=self._intent_count,
            workspace_count_active=self._workspace_count,
            last_intent=self._last_intent,
            last_receipt_task=last_task or self._last_receipt_task,
        )
        self._last_receipt_task = snap.last_receipt_task
        return snap

    def _sample_receipts(self) -> tuple[int, int, str]:
        """Tail receipts file for total count + last-minute count + latest task."""
        try:
            if not self._receipt_log_path.is_file():
                return (0, 0, "")
            # Cheap: count lines + sample tail. Bound work at 200 KB.
            size = self._receipt_log_path.stat().st_size
            offset = max(0, size - 200_000)
            with self._receipt_log_path.open("rb") as fh:
                fh.seek(offset)
                tail = fh.read().decode("utf-8", errors="ignore")
            lines = [ln for ln in tail.splitlines() if ln.strip()]
            # Total: approximate (size/avg_line); we only show recent-window precisely.
            try:
                import json
                cutoff = time.time() - 60.0
                recent = 0
                last_task = ""
                for ln in lines[-200:]:
                    try:
                        obj = json.loads(ln)
                    except Exception:
                        continue
                    ts = float(obj.get("timestamp", 0))
                    if ts >= cutoff:
                        recent += 1
                    last_task = obj.get("task", last_task) or last_task
                return (len(lines), recent, last_task)
            except Exception:
                return (len(lines), 0, "")
        except Exception:
            return (0, 0, "")
