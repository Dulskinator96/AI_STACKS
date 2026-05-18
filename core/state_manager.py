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
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

_log = logging.getLogger(__name__)


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
    current:      SystemState = SystemState.BOOT
    transitions:  list = field(default_factory=list)


class SystemStateManager:
    """Singleton — process-wide authority over operational state."""

    _instance: Optional["SystemStateManager"] = None
    _instance_lock = threading.RLock()

    def __init__(self):
        self._state = _ManagerState()
        self._lock = threading.RLock()
        self._listeners: list[Callable[[StateTransition], None]] = []

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

    def add_listener(self, fn: Callable[[StateTransition], None]) -> None:
        with self._lock:
            self._listeners.append(fn)

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
