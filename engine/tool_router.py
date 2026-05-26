"""engine/tool_router.py — wraps pyramid_tools.ToolRegistry.

Thin façade so PyramidEngine can request tool dispatch without coupling
to the ToolRegistry's specifics. Existing ToolDispatcher (TOOL: directive
parser) continues to work for agents; this is a programmatic entry point
for the engine.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

_log = logging.getLogger(__name__)


class ToolRouter:
    """Programmatic dispatcher for pyramid_tools."""

    def __init__(self):
        self._registry = None
        self._dispatcher = None
        self._available = False
        try:
            from pyramid_tools.registry import ToolRegistry, ToolDispatcher
            self._registry = ToolRegistry
            self._dispatcher = ToolDispatcher
            self._available = True
        except Exception as e:
            _log.debug("pyramid_tools unavailable: %s", e)

    def is_available(self) -> bool:
        return self._available

    def known_tools(self) -> list:
        if not self._available:
            return []
        try:
            return sorted(self._registry.list_tools()) \
                if hasattr(self._registry, "list_tools") else []
        except Exception:
            return []

    def call(self, tool_name: str, **params) -> dict:
        """Synchronous tool call. Returns {ok, value, error, duration_ms}.
        Caller should run this on a worker thread for any non-trivial tool."""
        t0 = time.time()
        if not self._available:
            return {"ok": False, "value": None,
                    "error": "pyramid_tools not available", "duration_ms": 0.0}
        try:
            tool = self._registry.get(tool_name) if hasattr(self._registry, "get") \
                   else self._registry.tools.get(tool_name)
            if tool is None:
                return {"ok": False, "value": None,
                        "error": f"unknown tool: {tool_name}",
                        "duration_ms": (time.time() - t0) * 1000.0}
            result = tool.fn(**params) if hasattr(tool, "fn") else tool(**params)
            self._emit_receipt(tool_name, "OK", (time.time() - t0) * 1000.0, params, result)
            return {"ok": True, "value": result, "error": "",
                    "duration_ms": (time.time() - t0) * 1000.0}
        except Exception as e:
            self._emit_receipt(tool_name, "FAIL", (time.time() - t0) * 1000.0, params, None,
                                error=str(e))
            return {"ok": False, "value": None,
                    "error": str(e), "duration_ms": (time.time() - t0) * 1000.0}

    def _emit_receipt(self, tool_name: str, outcome: str, dur_ms: float,
                       params: dict, result: Any, error: str = "") -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task=f"tool_router:{tool_name}",
                executor="ToolRouter",
                duration_ms=dur_ms,
                verified=(outcome == "OK"),
                compute_sha256=False,
                failure_reason=error if outcome != "OK" else None,
                evidence={
                    "tool":     tool_name,
                    "outcome":  outcome,
                    "param_keys": sorted(list((params or {}).keys())),
                    "result_brief": (str(result)[:200] if result is not None else None),
                },
            )
        except Exception:
            pass
