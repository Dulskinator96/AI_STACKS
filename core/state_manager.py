"""core/state_manager.py — authoritative system state machine.

Phase 1.2 of the Operational Stability plan.

Single source of truth for "what state is DBOMBLOCAL in?". Prevents:
    * UI lying about readiness ("LIVE" badge before workers actually online)
    * agents dispatching while LOADING_MODULES still running
    * false-positive "online" during ERROR_RECOVERY
    * threads drifting across boot phases unobserved

Allowed transitions are hard-coded — caller cannot promote authority by
inventing a new transition graph at runtime.

Each transition emits:
    * Python log line at INFO level
    * Constitution LAW_3 receipt (best-effort, no-op if substrate absent)
    * BootProfiler.mark(<state>) for time correlation
"""
from __future__ import annotations

import enum
import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)


def _resolve_state_dir() -> Path:
    """Return the telemetry dir next to the .exe (frozen) or project root (dev)."""
    try:
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).resolve().parent
        else:
            base = Path(__file__).resolve().parent.parent
        d = base / "telemetry"
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        return Path.home() / ".stratum" / "telemetry"


class SystemState(enum.Enum):
    BOOT             = "BOOT"
    INIT             = "INIT"
    VALIDATING       = "VALIDATING"
    LOADING_MODULES  = "LOADING_MODULES"
    STARTING_AGENTS  = "STARTING_AGENTS"
    READY            = "READY"
    EXECUTING        = "EXECUTING"
    ERROR_RECOVERY   = "ERROR_RECOVERY"
    SHUTDOWN         = "SHUTDOWN"


# Forward edges in the normal happy path
_FORWARD_EDGES = {
    SystemState.BOOT:            {SystemState.INIT, SystemState.ERROR_RECOVERY},
    SystemState.INIT:            {SystemState.VALIDATING, SystemState.ERROR_RECOVERY},
    SystemState.VALIDATING:      {SystemState.LOADING_MODULES, SystemState.ERROR_RECOVERY},
    SystemState.LOADING_MODULES: {SystemState.STARTING_AGENTS, SystemState.ERROR_RECOVERY},
    SystemState.STARTING_AGENTS: {SystemState.READY, SystemState.ERROR_RECOVERY},
    SystemState.READY:           {SystemState.EXECUTING, SystemState.ERROR_RECOVERY,
                                   SystemState.SHUTDOWN},
    SystemState.EXECUTING:       {SystemState.READY, SystemState.ERROR_RECOVERY,
                                   SystemState.SHUTDOWN},
    SystemState.ERROR_RECOVERY:  {SystemState.READY, SystemState.SHUTDOWN},
    SystemState.SHUTDOWN:        set(),    # terminal
}


@dataclass(frozen=True)
class StateTransition:
    from_state: SystemState
    to_state:   SystemState
    timestamp:  float
    reason:     str = ""
    actor:      str = "system_state_manager"


@dataclass
class _ManagerState:
    current:        SystemState = SystemState.BOOT
    transitions:    list = field(default_factory=list)
    prior_session:  Optional[dict] = None  # last state of the prior process, if any


class SystemStateManager:
    """Singleton — process-wide authority over operational state."""

    _instance: Optional["SystemStateManager"] = None
    _instance_lock = threading.RLock()

    PERSIST_FILE = "system_state.json"

    def __init__(self):
        self._state = _ManagerState()
        self._lock = threading.RLock()
        self._listeners: list[Callable[[StateTransition], None]] = []
        self._persist_path = _resolve_state_dir() / self.PERSIST_FILE
        self._load_prior_session()

    @classmethod
    def get(cls) -> "SystemStateManager":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ── public surface ─────────────────────────────────────────────────────

    @property
    def current(self) -> SystemState:
        with self._lock:
            return self._state.current

    @property
    def is_ready(self) -> bool:
        return self.current in (SystemState.READY, SystemState.EXECUTING)

    @property
    def is_shutdown(self) -> bool:
        return self.current is SystemState.SHUTDOWN

    def history(self) -> list:
        with self._lock:
            return list(self._state.transitions)

    @property
    def prior_session(self) -> Optional[dict]:
        """What state was the previous process in when it last wrote disk?
        None when there is no prior file (first run after delete/install)."""
        with self._lock:
            return self._state.prior_session

    def add_listener(self, fn: Callable[[StateTransition], None]) -> None:
        with self._lock:
            self._listeners.append(fn)

    # ── persistence ────────────────────────────────────────────────────────

    def _load_prior_session(self) -> None:
        """Best-effort: read the prior session's last persisted state for
        operator visibility. Never raises. Does not auto-resume — runtime
        always starts at BOOT and progresses forward."""
        try:
            if not self._persist_path.is_file():
                return
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            self._state.prior_session = {
                "last_state":     data.get("current"),
                "last_reason":    data.get("last_reason", ""),
                "last_timestamp": data.get("last_timestamp"),
                "transition_count": len(data.get("transitions", [])),
                "ended_cleanly":  data.get("ended_cleanly", False),
            }
            _log.info(
                "prior session ended at state=%s clean=%s (%d transitions)",
                self._state.prior_session["last_state"],
                self._state.prior_session["ended_cleanly"],
                self._state.prior_session["transition_count"],
            )
        except Exception as e:
            _log.debug("prior session load failed: %s", e)

    def _persist(self, *, ended_cleanly: bool = False) -> None:
        """Best-effort atomic write of current state + transition history.
        Never raises. Tail-bounded transitions list at 256 entries."""
        try:
            with self._lock:
                transitions_tail = [
                    {
                        "from":  t.from_state.value,
                        "to":    t.to_state.value,
                        "ts":    t.timestamp,
                        "reason": t.reason,
                        "actor":  t.actor,
                    }
                    for t in self._state.transitions[-256:]
                ]
                last = self._state.transitions[-1] if self._state.transitions else None
                payload: dict[str, Any] = {
                    "current":        self._state.current.value,
                    "last_reason":    last.reason if last else "",
                    "last_timestamp": last.timestamp if last else time.time(),
                    "transitions":    transitions_tail,
                    "ended_cleanly":  ended_cleanly,
                    "pid":            os.getpid(),
                }
            tmp = self._persist_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            try:
                tmp.replace(self._persist_path)
            except Exception:
                # Fallback for old Windows that can't atomic-rename over existing
                self._persist_path.write_text(
                    json.dumps(payload, indent=2), encoding="utf-8",
                )
        except Exception as e:
            _log.debug("state persist failed: %s", e)

    # ── transitions ────────────────────────────────────────────────────────

    def transition(self, target: SystemState, *, reason: str = "",
                    actor: str = "system_state_manager") -> bool:
        """Attempt a state transition. Returns True on success.

        REFUSES (False) when the requested edge isn't in _FORWARD_EDGES.
        This is the only way to enforce lifecycle discipline — caller
        cannot skip phases.
        """
        with self._lock:
            current = self._state.current
            allowed = _FORWARD_EDGES.get(current, set())
            if target not in allowed:
                _log.warning(
                    "state transition refused: %s → %s not in allowed set %s",
                    current.value, target.value,
                    sorted(s.value for s in allowed),
                )
                return False
            transition = StateTransition(
                from_state=current, to_state=target,
                timestamp=time.time(),
                reason=reason, actor=actor,
            )
            self._state.current = target
            self._state.transitions.append(transition)
            listeners = list(self._listeners)
        _log.info("STATE %s → %s  (reason=%s actor=%s)",
                   current.value, target.value, reason or "—", actor)

        # Profiler mark + listeners (outside lock to avoid reentrancy)
        try:
            from core.profiler import mark as profiler_mark
            profiler_mark(f"state:{target.value}", note=reason)
        except Exception as e:
            _log.debug("profiler mark failed: %s", e)

        try:
            from core.lifecycle import emit_state_receipt
            emit_state_receipt(transition)
        except Exception as e:
            _log.debug("lifecycle receipt emit failed: %s", e)

        # Truth layer: execution receipt for the transition (Doctrine §3 P1+P5)
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task=f"state_transition:{target.value}",
                executor="SystemStateManager",
                artifact=None,
                duration_ms=0.0,
                verified=True,
                compute_sha256=False,
                evidence={
                    "from":   current.value,
                    "to":     target.value,
                    "reason": reason or "",
                    "actor":  actor,
                },
            )
        except Exception as e:
            _log.debug("state transition receipt emit failed: %s", e)

        # Persist for restart visibility (Doctrine §5 state continuity)
        self._persist(ended_cleanly=(target is SystemState.SHUTDOWN))

        for fn in listeners:
            try:
                fn(transition)
            except Exception as e:
                _log.warning("state listener raised: %s", e)
        return True


def get_state_manager() -> SystemStateManager:
    return SystemStateManager.get()


def transition_to(target: SystemState, *, reason: str = "") -> bool:
    return get_state_manager().transition(target, reason=reason)
