"""Smoke tests for the four v1 observers + classifier dataclasses.

Run: python -m maintenance.tests.smoke_observers
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maintenance.classifier import (
    Tier, make_issue_id, REPAIR_ALLOW_LIST,
)
from maintenance.observers.runtime_health import RuntimeHealthAgent
from maintenance.observers.ui_state import UIStateAgent
from maintenance.observers.queue_watch import QueueWatchAgent
from maintenance.observers.drift_monitor import DriftMonitor
from maintenance.observers.execution_integrity import ExecutionIntegrityAgent
from maintenance.observers.process_watch import ProcessWatchAgent
from maintenance.observers.resource_pressure import ResourcePressureAgent
from maintenance.observers.memory_integrity import MemoryIntegrityAgent
from maintenance.repair_coordinator import RepairCoordinator


logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")


def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_issue_id_is_deterministic():
    a = make_issue_id("X", "k", "s")
    b = make_issue_id("X", "k", "s")
    _assert(a == b, "make_issue_id must be deterministic")
    _assert(a.startswith("iss-"), "issue id must have iss- prefix")


def test_classifier_allow_list_is_hardcoded():
    _assert("ui_state_resync" in REPAIR_ALLOW_LIST, "ui_state_resync must be in allow-list")
    _assert("queue_cleanup"   in REPAIR_ALLOW_LIST, "queue_cleanup must be in allow-list")
    _assert("delete_substrate" not in REPAIR_ALLOW_LIST, "substrate mutation must NOT be in allow-list")


def test_runtime_health_empty_log_ok():
    obs = RuntimeHealthAgent()
    issues = obs.safe_scan()
    _assert(isinstance(issues, list), "scan must return list")
    # Either empty (most likely) or T2 issues if user has lots of recent errors;
    # we only assert the contract holds.
    for it in issues:
        _assert(it.tier == Tier.T2, "RuntimeHealthAgent emits T2 issues")


def test_ui_state_agent_detects_mismatch():
    obs = UIStateAgent()
    obs.publish_state("tab_active", observed="🩺 Diagnostics", expected="🏛 Palace")
    issues = obs.safe_scan()
    _assert(len(issues) == 1, f"expected 1 issue, got {len(issues)}")
    it = issues[0]
    _assert(it.tier == Tier.T1, "ui mismatch must be T1")
    _assert(it.repair_hint == "ui_state_resync", "repair_hint must be ui_state_resync")
    _assert(it.confidence >= 0.7, "confidence floor reached")


def test_ui_state_agent_no_expectation_no_issue():
    obs = UIStateAgent()
    obs.publish_state("tab_active", observed="🩺 Diagnostics")
    issues = obs.safe_scan()
    _assert(len(issues) == 0, "no expectation → no issue")


def test_queue_watch_requires_stall_window():
    depth = [40, 40, 40]  # over high_water=32
    obs = QueueWatchAgent(depth_provider=lambda: depth.pop(0) if depth else 0,
                            high_water=32, stall_ticks=3)
    _assert(obs.safe_scan() == [], "tick 1: depth=40 but only 1 over")
    _assert(obs.safe_scan() == [], "tick 2: still only 2 consecutive overs")
    issues = obs.safe_scan()
    _assert(len(issues) == 1, "tick 3: should fire")
    _assert(issues[0].tier == Tier.T2, "queue stall is T2")
    _assert(issues[0].repair_hint == "queue_cleanup", "repair_hint must be queue_cleanup")


def test_queue_watch_resets_on_drop():
    seq = [40, 40, 1, 40]
    obs = QueueWatchAgent(depth_provider=lambda: seq.pop(0) if seq else 0,
                            high_water=32, stall_ticks=3)
    obs.safe_scan(); obs.safe_scan()
    obs.safe_scan()   # drops to 1, counter resets
    issues = obs.safe_scan()
    _assert(issues == [], "counter reset prevents false trigger")


def test_drift_monitor_quiet_when_log_missing():
    coord = RepairCoordinator()
    obs = DriftMonitor(coord)
    issues = obs.safe_scan()
    # No receipts in window → no drift → no issue, no restriction
    _assert(issues == [], "drift monitor must be quiet with no receipts")
    _assert(coord.restricted is False, "coordinator must not be restricted")


def test_all_observers_scan_directly_without_raising():
    """Strict regression guard. safe_scan() swallows everything, which can
    mask real bugs (NameError, AttributeError, etc.). Call scan() directly
    so a future broken observer fails the suite instead of getting silently
    logged."""
    observers = [
        RuntimeHealthAgent(),
        UIStateAgent(),
        QueueWatchAgent(),
        ExecutionIntegrityAgent(),
        ProcessWatchAgent(),
        ResourcePressureAgent(),
        MemoryIntegrityAgent(),
        DriftMonitor(RepairCoordinator()),
    ]
    for obs in observers:
        try:
            issues = obs.scan()
        except Exception as e:
            raise AssertionError(f"{obs.name}.scan() raised {type(e).__name__}: {e}") from e
        _assert(isinstance(issues, list),
                 f"{obs.name}.scan() must return list, got {type(issues).__name__}")


def test_execution_integrity_contract():
    obs = ExecutionIntegrityAgent()
    issues = obs.safe_scan()
    _assert(isinstance(issues, list), "scan must return list")
    for it in issues:
        _assert(it.tier in (Tier.T2, Tier.T3, Tier.T4),
                 f"ExecutionIntegrity emits T2/T3/T4 only, got {it.tier}")
        _assert(it.subsystem in ("stratum", "agents"),
                 f"ExecutionIntegrity issues must tag subsystem stratum/agents, got {it.subsystem!r}")


def test_process_watch_contract():
    obs = ProcessWatchAgent()
    issues = obs.safe_scan()
    _assert(isinstance(issues, list), "scan must return list")
    for it in issues:
        _assert(it.tier == Tier.T2, "ProcessWatch emits T2 only")
        _assert(it.subsystem == "workers", "ProcessWatch tagged workers")
        _assert(it.repair_hint == "temporary_process_restart",
                 "expected temporary_process_restart hint")


def test_resource_pressure_contract():
    obs = ResourcePressureAgent(cpu_threshold=200.0,
                                  memory_threshold=200.0,
                                  disk_threshold=200.0)
    issues = obs.safe_scan()
    _assert(isinstance(issues, list), "scan must return list")
    _assert(issues == [],
             "with impossible thresholds, no issues should fire")


def test_memory_integrity_contract():
    obs = MemoryIntegrityAgent()
    issues = obs.safe_scan()
    _assert(isinstance(issues, list), "scan must return list")
    for it in issues:
        _assert(it.tier in (Tier.T2, Tier.T3),
                 f"MemoryIntegrity emits T2/T3 only, got {it.tier}")
        _assert(it.kind in ("parent_dir_missing", "persistence_stale", "json_corruption"),
                 f"unexpected kind {it.kind!r}")


def main():
    tests = [
        test_issue_id_is_deterministic,
        test_classifier_allow_list_is_hardcoded,
        test_runtime_health_empty_log_ok,
        test_ui_state_agent_detects_mismatch,
        test_ui_state_agent_no_expectation_no_issue,
        test_queue_watch_requires_stall_window,
        test_queue_watch_resets_on_drop,
        test_drift_monitor_quiet_when_log_missing,
        test_all_observers_scan_directly_without_raising,
        test_execution_integrity_contract,
        test_process_watch_contract,
        test_resource_pressure_contract,
        test_memory_integrity_contract,
    ]
    failed = []
    for fn in tests:
        try:
            fn()
            print(f"  OK  {fn.__name__}")
        except AssertionError as e:
            failed.append((fn.__name__, str(e)))
            print(f"  FAIL {fn.__name__}: {e}")
    print()
    print(f"observers smoke: {len(tests) - len(failed)}/{len(tests)} passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
