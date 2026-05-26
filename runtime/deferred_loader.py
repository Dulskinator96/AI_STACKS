"""runtime/deferred_loader.py — worker-pool helper for off-thread work.

Thin wrapper around the dashboard's `_run_in_thread(fn, on_done=...)`
that exposes the same shape without coupling to HistoryDashboard. Used
by LazyWorkspaceFactory and DynamicWorkspaceSpawner so heavy work never
runs on the UI thread (RULE 6 — UI THREAD PURITY).

When the runtime registry has `ui.dashboard` registered, prefers its
worker. Otherwise falls back to a plain threading.Thread daemon.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)


class DeferredWorkspaceLoader:

    @staticmethod
    def run(fn: Callable[[], Any],
            on_done: Optional[Callable[[Any], None]] = None,
            name: str = "deferred") -> None:
        """Run `fn` on a worker thread. If `on_done` is given, it is
        invoked with the result. Exceptions in `fn` are caught and
        passed to `on_done` as a dict with key 'error'.
        """
        try:
            from runtime.singleton_registry import get_registry
            dash = get_registry().get("ui.dashboard")
            if dash is not None and hasattr(dash, "_run_in_thread"):
                dash._run_in_thread(fn, on_done=on_done)
                return
        except Exception:
            pass

        def _wrap():
            try:
                result = fn()
            except Exception as e:
                _log.warning("deferred '%s' raised: %s", name, e)
                result = {"error": str(e)}
            if on_done is not None:
                try:
                    on_done(result)
                except Exception as e:
                    _log.warning("deferred '%s' on_done raised: %s", name, e)

        t = threading.Thread(target=_wrap, name=f"deferred-{name}", daemon=True)
        t.start()
