"""omega.tracing.trace_contracts — trace state vocabulary + event shape.

For AI operational awareness, not human cosmetics. Every runtime operation is
trace-linkable; no orphan logs (Section 3B).
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class TraceState(str, Enum):
    INFO     = "INFO"
    SUCCESS  = "SUCCESS"
    WARNING  = "WARNING"
    FAILURE  = "FAILURE"
    CRITICAL = "CRITICAL"
    DRIFT    = "DRIFT"
    SHADOW   = "SHADOW"
    REPLAY   = "REPLAY"
    ENTROPY  = "ENTROPY"


# ANSI SGR codes per Section 3A. 256-color for orange/purple.
ANSI: dict[str, str] = {
    "INFO":     "\x1b[36m",        # cyan
    "SUCCESS":  "\x1b[32m",        # green
    "WARNING":  "\x1b[33m",        # yellow
    "FAILURE":  "\x1b[31m",        # red
    "CRITICAL": "\x1b[35m",        # magenta
    "DRIFT":    "\x1b[38;5;208m",  # orange
    "SHADOW":   "\x1b[90m",        # dark gray
    "REPLAY":   "\x1b[34m",        # blue
    "ENTROPY":  "\x1b[38;5;129m",  # purple
}
ANSI_RESET = "\x1b[0m"


def new_trace_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class TraceEvent:
    """A single trace-linked runtime event."""
    ts:           float
    state:        str                       # TraceState value
    message:      str
    trace_id:     Optional[str] = None
    execution_id: Optional[str] = None
    intent_id:    Optional[str] = None
    parent_trace: Optional[str] = None
    worker_id:    Optional[str] = None
    room:         Optional[str] = None
    phase:        Optional[str] = None
    # File origin tracking (Section 3C)
    origin_file:  Optional[str] = None
    origin_line:  Optional[int] = None
    origin_module: Optional[str] = None
    backend:      Optional[str] = None
    dependency_chain: list = field(default_factory=list)
    extra:        dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def tags(self) -> str:
        """Compact link header: [TRACE:..][EXEC:..][ROOM:..][WORKER:..][STATE:..]."""
        parts = [f"[TRACE:{self.trace_id or '----'}]"]
        if self.execution_id:
            parts.append(f"[EXEC:{self.execution_id}]")
        if self.intent_id:
            parts.append(f"[INTENT:{self.intent_id}]")
        if self.room:
            parts.append(f"[ROOM:{self.room}]")
        if self.worker_id:
            parts.append(f"[WORKER:{self.worker_id}]")
        parts.append(f"[STATE:{self.state}]")
        return "".join(parts)

    def to_line(self) -> str:
        line = f"{self.tags()} {self.message}"
        if self.origin_file:
            loc = f"{self.origin_module or self.origin_file}:{self.origin_line}"
            line += f"  @{loc}"
        if self.backend:
            line += f"  backend={self.backend}"
        return line
