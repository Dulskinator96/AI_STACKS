"""runtime/workspace_spawner.py — RULE 5: DYNAMIC ROOM SPAWNING.

Allocates ephemeral workspace sessions from intent. Each session is an
isolated execution container with its own log, cancel signal, and
optional dynamic tab. Sessions never mutate global UI lifecycle state.

Two-step lifecycle:
    spawn(intent, realm, plan) -> WorkspaceSession    # allocates only
    attach_tab(session, dashboard) -> int             # mounts UI

For headless/test paths, spawn() is sufficient — no UI attachment.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)


MAX_DYNAMIC_WORKSPACES = 32


@dataclass
class WorkspaceSession:
    session_id: str
    realm: str
    intent: str
    plan: Any                       # ExecutionPlan or None
    spawned_at: float
    cancel: threading.Event = field(default_factory=threading.Event)
    log_lines: list = field(default_factory=list)
    worker_active: bool = False
    closed: bool = False

    def log(self, line: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.log_lines.append(f"[{ts}] {line}")
        if len(self.log_lines) > 500:
            del self.log_lines[:250]


class DynamicWorkspaceSpawner:
    """Process-global workspace allocator. Thread-safe."""

    def __init__(self, max_active: int = MAX_DYNAMIC_WORKSPACES):
        self._sessions: dict[str, WorkspaceSession] = {}
        self._lock = threading.RLock()
        self._max_active = int(max_active)
        self._spawn_count = 0
        self._refused_count = 0

    def spawn(self, intent: str, realm: str, plan: Any = None) -> Optional[WorkspaceSession]:
        """Allocate a workspace session. Returns None if max reached."""
        with self._lock:
            active = [s for s in self._sessions.values() if not s.closed]
            if len(active) >= self._max_active:
                self._refused_count += 1
                self._emit_refused_receipt(intent, realm, len(active))
                return None
            sid = f"ws-{uuid.uuid4().hex[:10]}"
            session = WorkspaceSession(
                session_id=sid,
                realm=realm,
                intent=intent or "",
                plan=plan,
                spawned_at=time.time(),
            )
            self._sessions[sid] = session
            self._spawn_count += 1
            self._emit_spawn_receipt(session)
            return session

    def close(self, session_id: str) -> None:
        with self._lock:
            s = self._sessions.get(session_id)
            if s is None or s.closed:
                return
            s.closed = True
            try:
                s.cancel.set()
            except Exception:
                pass
            self._emit_close_receipt(s)

    def get(self, session_id: str) -> Optional[WorkspaceSession]:
        with self._lock:
            return self._sessions.get(session_id)

    def active_sessions(self) -> list[WorkspaceSession]:
        with self._lock:
            return [s for s in self._sessions.values() if not s.closed]

    def stats(self) -> dict:
        with self._lock:
            return {
                "spawn_count": self._spawn_count,
                "refused_count": self._refused_count,
                "active_count": len(self.active_sessions()),
                "max_active": self._max_active,
            }

    # ── Receipt helpers ───────────────────────────────────────────
    def _emit_spawn_receipt(self, s: WorkspaceSession) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="tab_spawn",
                executor="DynamicWorkspaceSpawner",
                duration_ms=0.0,
                verified=True,
                compute_sha256=False,
                evidence={
                    "session_id": s.session_id,
                    "realm": s.realm,
                    "intent": s.intent[:160],
                    "has_plan": s.plan is not None,
                    "active_count": len(self.active_sessions()),
                    "spawn_count": self._spawn_count,
                },
            )
        except Exception:
            pass

    def _emit_close_receipt(self, s: WorkspaceSession) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="tab_spawn:close",
                executor="DynamicWorkspaceSpawner",
                duration_ms=(time.time() - s.spawned_at) * 1000.0,
                verified=True,
                compute_sha256=False,
                evidence={
                    "session_id": s.session_id,
                    "realm": s.realm,
                    "worker_was_active": s.worker_active,
                },
            )
        except Exception:
            pass

    def _emit_refused_receipt(self, intent: str, realm: str, active: int) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="tab_spawn:refused",
                executor="DynamicWorkspaceSpawner",
                duration_ms=0.0,
                verified=False,
                compute_sha256=False,
                failure_reason="max_active_reached",
                evidence={
                    "intent": (intent or "")[:160],
                    "realm": realm,
                    "active_count": active,
                    "max_active": self._max_active,
                },
            )
        except Exception:
            pass


_SPAWNER_INSTANCE: Optional[DynamicWorkspaceSpawner] = None


def get_workspace_spawner() -> DynamicWorkspaceSpawner:
    global _SPAWNER_INSTANCE
    if _SPAWNER_INSTANCE is None:
        _SPAWNER_INSTANCE = DynamicWorkspaceSpawner()
        # Make discoverable via service locator.
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("workspace.spawner", _SPAWNER_INSTANCE)
        except Exception:
            pass
    return _SPAWNER_INSTANCE
