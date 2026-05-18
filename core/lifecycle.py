"""core/lifecycle.py — bridges state_manager + profiler + Constitution.

Phase 1.4 wiring. Holds the cross-cutting glue so state_manager.py and
profiler.py can stay focused on their single responsibility.

Public surface:
    emit_state_receipt(transition)   — best-effort LAW_3 receipt
    on_boot()                        — call once at process start
    on_ready()                       — call once when UI interactive
    on_shutdown()                    — call once at clean exit; writes
                                        boot_profile_*.json
"""
from __future__ import annotations

import logging
from pathlib import Path

_log = logging.getLogger(__name__)


def emit_state_receipt(transition) -> None:
    """Emit a LAW_3 receipt for a system state transition. Never raises."""
    try:
        import sys
        substrate = Path(__file__).resolve().parent.parent.parent
        if str(substrate) not in sys.path:
            sys.path.append(str(substrate))
        from kernel.constitution import get_constitution
        con = get_constitution()
        con.record_receipt(
            "lifecycle", transition.actor, "state_transition",
            outcome="VALIDATED",
            evidence={
                "from":   transition.from_state.value,
                "to":     transition.to_state.value,
                "reason": transition.reason or "",
            },
        )
    except Exception as e:
        _log.debug("constitution receipt skipped (substrate unavailable): %s", e)


def on_boot() -> None:
    """Call ONCE at process start, before heavy imports."""
    try:
        from core.profiler import get_profiler
        get_profiler().start()
    except Exception as e:
        _log.warning("profiler start failed: %s", e)


def on_ready() -> None:
    """Call just BEFORE app.exec() — marks 'exec_loop_entered' only.

    The canonical 'interactive' mark + READY state transition is fired by
    HistoryDashboard.paintEvent on first paint (Phase A v3 final). That is
    the user-perceived moment of interactivity; placing it here was sensitive
    to processEvents() QTimer drainage timing and produced unstable numbers.
    """
    try:
        from core.profiler import mark
        mark("exec_loop_entered")
    except Exception as e:
        _log.warning("on_ready hooks failed: %s", e)


def on_shutdown() -> None:
    """Call ONCE at clean exit. Emits boot profile to telemetry/."""
    try:
        from core.profiler import get_profiler
        from core.state_manager import transition_to, SystemState
        transition_to(SystemState.SHUTDOWN, reason="clean_exit")
        path = get_profiler().emit_report()
        if path is not None:
            _log.info("boot profile written → %s", path)
    except Exception as e:
        _log.warning("on_shutdown hooks failed: %s", e)
