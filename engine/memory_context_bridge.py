"""engine/memory_context_bridge.py — wraps memory backends for intent context.

Queries agent_memory + mempalace at intent submission so the operator's
prior creations inform the current expansion. Worker-pool only; UI never
blocks on memory recall.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

_log = logging.getLogger(__name__)


class MemoryContextBridge:
    """Aggregate memory-recall over all available backends."""

    def __init__(self):
        self._agent_memory_ok = self._probe_agent_memory()
        self._mempalace_ok = self._probe_mempalace()

    def _probe_agent_memory(self) -> bool:
        try:
            import agent_memory  # noqa: F401
            return True
        except Exception:
            return False

    def _probe_mempalace(self) -> bool:
        try:
            import mempalace  # noqa: F401
            return True
        except Exception:
            return False

    def recall(self, query: str, limit: int = 5) -> dict:
        """Synchronous recall — runs on caller's thread. Return shape:
            {"agent_memory": [...], "mempalace": [...], "total": int}
        Never raises."""
        t0 = time.time()
        out = {"agent_memory": [], "mempalace": [], "total": 0}
        if self._agent_memory_ok:
            try:
                import agent_memory as am
                if hasattr(am, "recall_global"):
                    out["agent_memory"] = list(am.recall_global(query, limit=limit) or [])[:limit]
            except Exception as e:
                _log.debug("agent_memory recall failed: %s", e)
        if self._mempalace_ok:
            try:
                import mempalace
                if hasattr(mempalace, "search"):
                    out["mempalace"] = list(mempalace.search(query, limit=limit) or [])[:limit]
                elif hasattr(mempalace, "searcher"):
                    out["mempalace"] = list(
                        mempalace.searcher.search(query, limit=limit) or []
                    )[:limit]
            except Exception as e:
                _log.debug("mempalace recall failed: %s", e)
        out["total"] = len(out["agent_memory"]) + len(out["mempalace"])
        self._emit_receipt(query, out, (time.time() - t0) * 1000.0)
        return out

    def recall_async(self, query: str, on_done, limit: int = 5) -> None:
        """Worker-pool wrapper around recall(). Calls on_done(result_dict)."""
        try:
            from runtime.deferred_loader import DeferredWorkspaceLoader
            DeferredWorkspaceLoader.run(
                lambda: self.recall(query, limit=limit),
                on_done=on_done,
                name="memory_recall",
            )
        except Exception:
            t = threading.Thread(
                target=lambda: on_done(self.recall(query, limit=limit)),
                daemon=True, name="memory_recall_fallback",
            )
            t.start()

    def _emit_receipt(self, query: str, result: dict, dur_ms: float) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="memory_context:recall",
                executor="MemoryContextBridge",
                duration_ms=dur_ms,
                verified=True,
                compute_sha256=False,
                evidence={
                    "query":             (query or "")[:120],
                    "agent_memory_hits": len(result.get("agent_memory", [])),
                    "mempalace_hits":    len(result.get("mempalace", [])),
                    "total":             result.get("total", 0),
                    "agent_memory_ok":   self._agent_memory_ok,
                    "mempalace_ok":      self._mempalace_ok,
                },
            )
        except Exception:
            pass
