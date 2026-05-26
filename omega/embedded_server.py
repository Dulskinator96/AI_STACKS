"""omega.embedded_server — host the FastAPI service for the packaged runtime.

BUILD-034 Section 2: the packaged exe hosts its own API. Lesson from frozen
verification: an in-process uvicorn THREAD is GIL-starved by the always-busy
Qt main thread (animations/timers) and never reliably serves. So the GUI
spawns the API as a SEPARATE PROCESS (the same exe in --omega-api mode), which
runs uvicorn on its own interpreter/GIL and serves reliably. The two processes
share the real substrate on disk (ledger + telemetry, frozen-aware paths).

Orphan prevention (Section 6 E3): the API child runs a watchdog that exits the
moment the parent PID disappears; the parent also kills the child atexit.
"""
from __future__ import annotations

import atexit
import logging
import os
import sys
import threading
import time
from typing import Optional

_log = logging.getLogger(__name__)


# ── PID liveness (Windows-aware) ─────────────────────────────────────────────
def _pid_alive(pid: int) -> bool:
    try:
        if os.name == "nt":
            import ctypes
            PROCESS_QUERY_LIMITED = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
            if not h:
                return False
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(h)
            return code.value == 259  # STILL_ACTIVE
        os.kill(pid, 0)
        return True
    except Exception:
        return False


# ── API-only process entry (called from app.py --omega-api) ─────────────────
def run_api_blocking(host: str = "127.0.0.1", port: int = 8077,
                     parent_pid: Optional[int] = None) -> None:
    """Run uvicorn BLOCKING in this process's main thread (no Qt). Used by the
    --omega-api subprocess. A watchdog exits when the parent dies."""
    if parent_pid:
        def _watch():
            while True:
                time.sleep(2)
                if not _pid_alive(parent_pid):
                    os._exit(0)
        threading.Thread(target=_watch, name="omega-api-parent-watch", daemon=True).start()
    try:
        import uvicorn
        from service.api import app
        config = uvicorn.Config(app, host=host, port=port, log_level="warning",
                                loop="asyncio", http="h11", ws="none",
                                lifespan="off", access_log=False,
                                log_config=None, use_colors=False)
        uvicorn.Server(config).run()
    except Exception as e:
        _log.error("omega api process failed: %s: %s", type(e).__name__, e)
        os._exit(1)


# ── GUI side: spawn + readiness probe ───────────────────────────────────────
_state: dict = {"host": None, "port": None, "ready": False, "error": None, "pid": None}
_child = None
_started = False
_lock = threading.Lock()


def _api_child_args(host: str, port: int, parent_pid: int) -> list:
    args = [sys.executable]
    if not getattr(sys, "frozen", False):
        # dev: run app.py in --omega-api mode
        from omega.paths import project_root
        args.append(str(project_root() / "app.py"))
    args += ["--omega-api", "--omega-parent", str(parent_pid),
             "--omega-host", host, "--omega-port", str(port)]
    return args


def spawn_api_process(host: str = "127.0.0.1", port: int = 8077,
                      *, timeout: float = 120.0) -> dict:
    """Spawn the API as a separate process and wait until it actually SERVES
    (external /health), not merely 'started'. Idempotent. Returns the state."""
    global _child, _started
    with _lock:
        if _started:
            return dict(_state)
        _started = True

    import subprocess
    import urllib.request
    _state.update(host=host, port=port)
    try:
        args = _api_child_args(host, port, os.getpid())
        flags = 0x08000000 if os.name == "nt" else 0   # CREATE_NO_WINDOW
        _child = subprocess.Popen(args, creationflags=flags)
        _state["pid"] = _child.pid
    except Exception as e:
        _state["error"] = f"spawn: {type(e).__name__}: {e}"
        return dict(_state)

    atexit.register(_terminate_child)

    deadline = time.time() + timeout
    url = f"http://{host}:{port}/health"
    while time.time() < deadline:
        if _child.poll() is not None:
            _state["error"] = f"api process exited early (code {_child.returncode})"
            return dict(_state)
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    _state["ready"] = True
                    return dict(_state)
        except Exception:
            time.sleep(2)
    _state["error"] = f"api did not serve within {timeout}s"
    return dict(_state)


def _terminate_child() -> None:
    global _child
    try:
        if _child is not None and _child.poll() is None:
            _child.terminate()
    except Exception:
        pass


def api_state() -> dict:
    st = dict(_state)
    st["child_alive"] = bool(_child is not None and _child.poll() is None)
    return st


def stop_embedded_api() -> None:
    _terminate_child()
