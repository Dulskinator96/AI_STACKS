"""omega.tracing.trace_engine — the permanent runtime trace bus.

Thread-linked, origin-tracked, persisted. Every emit inherits the active
trace context (contextvars) so no log is an orphan (Section 3B). On WARNING+
the originating file/line/module is captured automatically (Section 3C).
"""
from __future__ import annotations

import contextvars
import inspect
import json
import os
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from typing import Optional

from omega.paths import telemetry_root
from omega.tracing.trace_contracts import TraceEvent, TraceState, new_trace_id

# Active link context — emits inherit these automatically.
_CTX: contextvars.ContextVar[dict] = contextvars.ContextVar("omega_trace_ctx", default={})

_RING_MAX = 1000
_THIS_FILE = os.path.normcase(os.path.abspath(__file__))


def _traces_dir():
    d = telemetry_root() / "traces"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


class TraceEngine:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ring: list[TraceEvent] = []
        self._jsonl = _traces_dir() / f"trace_{time.strftime('%Y%m%d')}.jsonl"
        self._echo = self._want_echo()

    @staticmethod
    def _want_echo() -> bool:
        # Echo colorized traces to stderr when attached to a console and not
        # explicitly silenced. Frozen windowed exe has no console → no echo.
        if os.environ.get("OMEGA_TRACE_ECHO") == "0":
            return False
        try:
            return sys.stderr is not None and sys.stderr.isatty()
        except Exception:
            return False

    # ── origin capture ────────────────────────────────────────────────────
    def _capture_origin(self) -> tuple[Optional[str], Optional[int], Optional[str]]:
        """Walk the stack to the first frame OUTSIDE the tracing package."""
        try:
            for fr in inspect.stack()[2:]:
                fn = os.path.normcase(os.path.abspath(fr.filename))
                if fn == _THIS_FILE:
                    continue
                if os.sep + "omega" + os.sep + "tracing" + os.sep in fn:
                    continue
                mod = inspect.getmodule(fr.frame)
                modname = getattr(mod, "__name__", None)
                # shorten to repo-relative-ish path
                short = fr.filename
                return short, fr.lineno, modname
        except Exception:
            pass
        return None, None, None

    # ── emit ──────────────────────────────────────────────────────────────
    def emit(self, state, message: str, *, capture_origin: Optional[bool] = None,
             **linkage) -> TraceEvent:
        st = state.value if isinstance(state, TraceState) else str(state)
        ctx = dict(_CTX.get() or {})
        ctx.update({k: v for k, v in linkage.items() if v is not None})

        # auto-capture origin on WARNING and worse, or when asked
        if capture_origin is None:
            capture_origin = st in ("WARNING", "FAILURE", "CRITICAL", "DRIFT", "SHADOW")
        of, ol, om = self._capture_origin() if capture_origin else (None, None, None)

        ev = TraceEvent(
            ts=time.time(), state=st, message=message,
            trace_id=ctx.get("trace_id"), execution_id=ctx.get("execution_id"),
            intent_id=ctx.get("intent_id"), parent_trace=ctx.get("parent_trace"),
            worker_id=ctx.get("worker_id"), room=ctx.get("room"),
            phase=ctx.get("phase") or linkage.get("phase"),
            origin_file=of, origin_line=ol, origin_module=om,
            backend=ctx.get("backend") or linkage.get("backend"),
            dependency_chain=linkage.get("dependency_chain", []) or [],
            extra=linkage.get("extra", {}) or {},
        )
        with self._lock:
            self._ring.append(ev)
            if len(self._ring) > _RING_MAX:
                self._ring = self._ring[-_RING_MAX:]
            try:
                with self._jsonl.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(ev.to_dict()) + "\n")
            except Exception:
                pass
        if self._echo:
            try:
                from omega.tracing.trace_render import render
                print(render(ev), file=sys.stderr)
            except Exception:
                pass
        return ev

    def emit_failure(self, message: str, exc: Optional[BaseException] = None,
                     **linkage) -> TraceEvent:
        """FAILURE with the originating file/line pulled from the exception's
        deepest frame (Section 3C)."""
        of = ol = om = None
        if exc is not None:
            tb = exc.__traceback__
            last = None
            while tb is not None:
                last = tb
                tb = tb.tb_next
            if last is not None:
                of = last.tb_frame.f_code.co_filename
                ol = last.tb_lineno
                om = last.tb_frame.f_globals.get("__name__")
            linkage.setdefault("extra", {})["exception"] = f"{type(exc).__name__}: {exc}"
        ev = self.emit(TraceState.FAILURE, message, capture_origin=(exc is None), **linkage)
        if of:
            ev.origin_file, ev.origin_line, ev.origin_module = of, ol, om
        return ev

    # ── query ───────────────────────────────────────────────────────────────
    def recent(self, n: int = 50) -> list[TraceEvent]:
        with self._lock:
            return list(self._ring[-n:])

    def by_trace(self, trace_id: str) -> list[TraceEvent]:
        with self._lock:
            return [e for e in self._ring if e.trace_id == trace_id]

    def by_execution(self, execution_id: str) -> list[TraceEvent]:
        with self._lock:
            return [e for e in self._ring if e.execution_id == execution_id]

    @property
    def jsonl_path(self) -> str:
        return str(self._jsonl)


_ENGINE: Optional[TraceEngine] = None
_ENGINE_LOCK = threading.Lock()


def get_tracer() -> TraceEngine:
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = TraceEngine()
    return _ENGINE


def emit(state, message: str, **linkage) -> TraceEvent:
    return get_tracer().emit(state, message, **linkage)


def emit_failure(message: str, exc: Optional[BaseException] = None, **linkage) -> TraceEvent:
    return get_tracer().emit_failure(message, exc, **linkage)


def render_recent(n: int = 50, *, color: bool = True) -> str:
    """Render the last n ring events. Lives here (not trace_render) because it
    needs the ring buffer; keeps trace_render a pure leaf view (cycle-free)."""
    from omega.tracing.trace_render import render
    return "\n".join(render(e, color=color) for e in get_tracer().recent(n))


@contextmanager
def trace_context(**linkage):
    """Bind link fields for all emits in this scope (thread/task-safe)."""
    cur = dict(_CTX.get() or {})
    cur.update({k: v for k, v in linkage.items() if v is not None})
    if not cur.get("trace_id"):
        cur["trace_id"] = new_trace_id()
    token = _CTX.set(cur)
    try:
        yield cur["trace_id"]
    finally:
        _CTX.reset(token)


def current_context() -> dict:
    return dict(_CTX.get() or {})
