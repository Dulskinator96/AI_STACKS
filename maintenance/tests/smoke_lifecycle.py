"""Smoke tests for core/profiler, core/state_manager, truth/receipt_engine.

Run: python -m maintenance.tests.smoke_lifecycle
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.profiler import BootProfiler
from core.state_manager import (
    SystemState, SystemStateManager,
)
from truth.receipt_engine import (
    ExecutionReceipt, record_execution,
)


def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _fresh_profiler():
    # Bypass singleton for testing
    BootProfiler._instance = None
    return BootProfiler.get()


def _fresh_state_manager():
    SystemStateManager._instance = None
    return SystemStateManager.get()


def test_profiler_records_marks_in_order():
    p = _fresh_profiler()
    p.start()
    time.sleep(0.01)
    p.mark("phase_a")
    time.sleep(0.01)
    p.mark("phase_b")
    marks = p.marks()
    _assert(len(marks) >= 3, f"expected ≥3 marks, got {len(marks)}")
    _assert(marks[0].phase == "boot_start", "first mark must be boot_start")
    phases = [m.phase for m in marks]
    _assert("phase_a" in phases and "phase_b" in phases, "custom marks recorded")


def test_profiler_emits_report_to_jsonl():
    p = _fresh_profiler()
    p.start()
    p.mark("test_phase")
    with tempfile.TemporaryDirectory() as d:
        out = p.emit_report(Path(d))
        _assert(out is not None and out.is_file(), "report file written")
        import json
        payload = json.loads(out.read_text(encoding="utf-8"))
        _assert(payload["phase_count"] >= 2, "phase_count populated")
        _assert("total_elapsed_ms" in payload, "total_elapsed_ms populated")


def test_state_manager_enforces_allowed_edges():
    sm = _fresh_state_manager()
    _assert(sm.current is SystemState.BOOT, "starts in BOOT")
    _assert(sm.transition(SystemState.INIT), "BOOT → INIT allowed")
    _assert(sm.current is SystemState.INIT, "current advanced to INIT")
    # Invalid: INIT → READY (must go through VALIDATING etc.)
    _assert(not sm.transition(SystemState.READY),
             "INIT → READY must be REFUSED")
    _assert(sm.current is SystemState.INIT, "current unchanged after refusal")


def test_state_manager_supports_full_happy_path():
    sm = _fresh_state_manager()
    seq = [
        SystemState.INIT, SystemState.VALIDATING, SystemState.LOADING_MODULES,
        SystemState.STARTING_AGENTS, SystemState.READY, SystemState.EXECUTING,
        SystemState.READY, SystemState.SHUTDOWN,
    ]
    for tgt in seq:
        _assert(sm.transition(tgt), f"transition to {tgt.value} must succeed")
    _assert(sm.current is SystemState.SHUTDOWN, "ends in SHUTDOWN")
    _assert(sm.is_shutdown, "is_shutdown True at end")


def test_state_manager_shutdown_is_terminal():
    sm = _fresh_state_manager()
    # walk to SHUTDOWN
    for tgt in (SystemState.INIT, SystemState.VALIDATING,
                 SystemState.LOADING_MODULES, SystemState.STARTING_AGENTS,
                 SystemState.READY, SystemState.SHUTDOWN):
        sm.transition(tgt)
    _assert(sm.current is SystemState.SHUTDOWN, "in SHUTDOWN")
    # No further transitions
    _assert(not sm.transition(SystemState.READY),
             "SHUTDOWN → READY must be refused (terminal)")


def test_state_manager_error_recovery_path():
    sm = _fresh_state_manager()
    sm.transition(SystemState.INIT)
    _assert(sm.transition(SystemState.ERROR_RECOVERY),
             "INIT → ERROR_RECOVERY allowed")
    _assert(sm.transition(SystemState.READY),
             "ERROR_RECOVERY → READY allowed")


def test_execution_receipt_records_verified_artifact():
    with tempfile.NamedTemporaryFile(delete=False, mode="w",
                                       suffix=".txt") as tf:
        tf.write("hello world")
        path = tf.name
    receipt = record_execution(
        task="test_artifact",
        executor="smoke",
        artifact=path,
        verified=True,
        evidence={"test": True},
    )
    _assert(isinstance(receipt, ExecutionReceipt), "returns ExecutionReceipt")
    _assert(receipt.sha256 is not None, "sha256 computed")
    _assert(len(receipt.sha256) == 64, "sha256 is hex 64 chars")
    _assert(receipt.verified is True, "verified preserved")


def test_execution_receipt_handles_missing_artifact():
    receipt = record_execution(
        task="missing_artifact_test",
        executor="smoke",
        artifact="/path/that/does/not/exist/anywhere/12345",
        verified=False,
        failure_reason="artifact not found",
    )
    _assert(receipt.sha256 is None, "missing file → sha256 None")
    _assert(receipt.verified is False, "verified=False preserved")
    _assert(receipt.failure_reason == "artifact not found",
             "failure_reason preserved")


def main():
    tests = [
        test_profiler_records_marks_in_order,
        test_profiler_emits_report_to_jsonl,
        test_state_manager_enforces_allowed_edges,
        test_state_manager_supports_full_happy_path,
        test_state_manager_shutdown_is_terminal,
        test_state_manager_error_recovery_path,
        test_execution_receipt_records_verified_artifact,
        test_execution_receipt_handles_missing_artifact,
    ]
    failed = []
    for fn in tests:
        try:
            fn()
            print(f"  OK  {fn.__name__}")
        except AssertionError as e:
            failed.append((fn.__name__, str(e)))
            print(f"  FAIL {fn.__name__}: {e}")
        except Exception as e:
            failed.append((fn.__name__, f"{type(e).__name__}: {e}"))
            print(f"  FAIL {fn.__name__}: {type(e).__name__}: {e}")
    print()
    print(f"lifecycle smoke: {len(tests) - len(failed)}/{len(tests)} passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
