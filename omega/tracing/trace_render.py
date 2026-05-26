"""omega.tracing.trace_render — ANSI colorization for PowerShell/terminals.

Colors per Section 3A. Enables Windows VT processing so PowerShell renders the
SGR codes instead of printing them literally.
"""
from __future__ import annotations

import os
import sys

from omega.tracing.trace_contracts import ANSI, ANSI_RESET, TraceEvent

_VT_ENABLED = False


def enable_ansi_on_windows() -> bool:
    """Turn on virtual-terminal processing for the active console (idempotent).
    Returns True if ANSI should render."""
    global _VT_ENABLED
    if _VT_ENABLED:
        return True
    if os.name != "nt":
        _VT_ENABLED = True
        return True
    try:
        import ctypes
        k = ctypes.windll.kernel32
        for handle_id in (-11, -12):  # STD_OUTPUT, STD_ERROR
            h = k.GetStdHandle(handle_id)
            mode = ctypes.c_uint32()
            if k.GetConsoleMode(h, ctypes.byref(mode)):
                k.SetConsoleMode(h, mode.value | 0x0004)  # ENABLE_VT_PROCESSING
        _VT_ENABLED = True
    except Exception:
        _VT_ENABLED = False
    return _VT_ENABLED


def render(event: TraceEvent, *, color: bool = True) -> str:
    line = event.to_line()
    if not color:
        return line
    enable_ansi_on_windows()
    code = ANSI.get(event.state, "")
    if not code:
        return line
    return f"{code}{line}{ANSI_RESET}"

# NOTE: render_recent() lives in trace_engine (it needs the ring buffer). Keeping
# this module a pure LEAF view (imports only trace_contracts) breaks the
# trace_render <-> trace_engine import cycle. Layer: L2 view, no upward import.
