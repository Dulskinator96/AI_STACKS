"""Smoke tests for RepairCoordinator + MaintenanceRuntime end-to-end.

Run: python -m maintenance.tests.smoke_repair_coordinator
"""
from __future__ import annotations

import logging
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maintenance.classifier import Issue, Tier, Severity, make_issue_id
from maintenance.repair_coordinator import RepairCoordinator
from maintenance.receipts import (
    OUTCOME_APPLIED, OUTCOME_DRY_RUN, OUTCOME_REJECTED, OUTCOME_ESCALATED, OUTCOME_UNRESOLVED,
    VALIDATION_VALIDATED, VALIDATION_UNRESOLVED,
)
from maintenance.observers.ui_state import UIStateAgent
from maintenance.runtime import MaintenanceRuntime


logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")


def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _issue(*, tier=Tier.T1, hint="ui_state_resync", conf=0.9) -> Issue:
    return Issue(
        issue_id=make_issue_id("Smoke", "k", "s", salt=str(time.time())),
        observer="Smoke", kind="smoke", tier=tier, severity=Severity.LOW,
        surface="smoke",
        evidence={"x": 1},
        repair_hint=hint, confidence=conf,
    )


def test_t4_is_always_escalated():
    coord = RepairCoordinator()
    out = coord.handle(_issue(tier=Tier.T4, hint="anything", conf=1.0))
    _assert(out.receipt.outcome == OUTCOME_ESCALATED, "T4 must escalate")
    _assert(out.applied is False, "T4 never applies")


def test_t3_is_validate_only():
    coord = RepairCoordinator()
    out = coord.handle(_issue(tier=Tier.T3, hint=None, conf=1.0))
    _assert(out.receipt.outcome == OUTCOME_DRY_RUN, "T3 must be DRY_RUN")
    _assert(out.applied is False, "T3 never applies")


def test_unknown_repair_hint_rejected():
    coord = RepairCoordinator()
    out = coord.handle(_issue(tier=Tier.T1, hint="rm_rf_root", conf=1.0))
    _assert(out.receipt.outcome == OUTCOME_REJECTED, "non-allow-list hint must be rejected")
    _assert(out.applied is False, "rejection means no apply")


def test_low_confidence_marked_unresolved():
    coord = RepairCoordinator()
    out = coord.handle(_issue(tier=Tier.T1, hint="ui_state_resync", conf=0.10))
    _assert(out.receipt.outcome == OUTCOME_UNRESOLVED, "low conf → UNRESOLVED")
    _assert(out.receipt.validation_status == VALIDATION_UNRESOLVED, "UNRESOLVED validation")
    _assert(out.applied is False, "no apply at low confidence")


def test_apply_path_requires_rollback():
    coord = RepairCoordinator()
    # Repair fn returns success but NO rollback path → coordinator must refuse.
    coord.register_repair("ui_state_resync",
                           lambda issue: (True, {"resynced": True}, None))
    out = coord.handle(_issue(tier=Tier.T1, hint="ui_state_resync", conf=0.95))
    _assert(out.receipt.outcome == OUTCOME_UNRESOLVED,
             "missing rollback must collapse to UNRESOLVED")
    _assert(out.applied is False, "no apply without rollback")


def test_apply_path_full_success():
    coord = RepairCoordinator()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".rb") as tf:
        rollback = tf.name
    coord.register_repair("ui_state_resync",
                           lambda issue: (True, {"resynced": True}, rollback))
    coord.register_validator("ui_state_resync",
                              lambda issue, after: after.get("resynced") is True)
    out = coord.handle(_issue(tier=Tier.T1, hint="ui_state_resync", conf=0.95))
    _assert(out.receipt.outcome == OUTCOME_APPLIED, f"expected APPLIED got {out.receipt.outcome}")
    _assert(out.receipt.validation_status == VALIDATION_VALIDATED, "must be VALIDATED")
    _assert(out.applied is True, "applied=True on success")


def test_validator_failure_marks_unresolved():
    coord = RepairCoordinator()
    rb = tempfile.NamedTemporaryFile(delete=False, suffix=".rb").name
    coord.register_repair("ui_state_resync",
                           lambda issue: (True, {"resynced": False}, rb))
    coord.register_validator("ui_state_resync",
                              lambda issue, after: after.get("resynced") is True)
    out = coord.handle(_issue(tier=Tier.T1, hint="ui_state_resync", conf=0.95))
    _assert(out.receipt.outcome == OUTCOME_UNRESOLVED,
             "validator failed → UNRESOLVED (no fabricated success)")


def test_restriction_collapses_to_dry_run():
    coord = RepairCoordinator()
    rb = tempfile.NamedTemporaryFile(delete=False, suffix=".rb").name
    coord.register_repair("ui_state_resync",
                           lambda issue: (True, {"resynced": True}, rb))
    coord.restrict("test_restriction")
    out = coord.handle(_issue(tier=Tier.T1, hint="ui_state_resync", conf=0.95))
    _assert(out.receipt.outcome == OUTCOME_DRY_RUN, "restricted → DRY_RUN")
    _assert(out.applied is False, "restricted never applies")
    coord.restore()


def test_repair_fn_exception_does_not_propagate():
    coord = RepairCoordinator()
    def boom(issue): raise RuntimeError("boom")
    coord.register_repair("ui_state_resync", boom)
    out = coord.handle(_issue(tier=Tier.T1, hint="ui_state_resync", conf=0.95))
    _assert(out.receipt.outcome == OUTCOME_UNRESOLVED, "exception → UNRESOLVED, no raise")


def test_runtime_routes_issues_into_coordinator():
    coord = RepairCoordinator()
    rb = tempfile.NamedTemporaryFile(delete=False, suffix=".rb").name
    coord.register_repair("ui_state_resync",
                           lambda issue: (True, {"resynced": True}, rb))
    coord.register_validator("ui_state_resync",
                              lambda issue, after: after.get("resynced") is True)
    ui = UIStateAgent()
    ui.cadence_seconds = 0.0   # always eligible
    ui.publish_state("tab", observed="A", expected="B")
    rt = MaintenanceRuntime(coord, [ui], tick_seconds=0.0)
    outcomes = rt.tick_once()
    _assert(len(outcomes) == 1, f"expected 1 outcome got {len(outcomes)}")
    _assert(outcomes[0].receipt.outcome == OUTCOME_APPLIED, "should apply")


def test_runtime_lifecycle_start_stop():
    coord = RepairCoordinator()
    rt = MaintenanceRuntime(coord, [], tick_seconds=0.2)
    rt.start()
    time.sleep(0.5)
    _assert(rt.running, "runtime should be running")
    _assert(rt.tick_count >= 1, f"should have ticked at least once, got {rt.tick_count}")
    rt.stop()
    _assert(rt.running is False, "runtime should be stopped")


def main():
    tests = [
        test_t4_is_always_escalated,
        test_t3_is_validate_only,
        test_unknown_repair_hint_rejected,
        test_low_confidence_marked_unresolved,
        test_apply_path_requires_rollback,
        test_apply_path_full_success,
        test_validator_failure_marks_unresolved,
        test_restriction_collapses_to_dry_run,
        test_repair_fn_exception_does_not_propagate,
        test_runtime_routes_issues_into_coordinator,
        test_runtime_lifecycle_start_stop,
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
    print(f"coordinator+runtime smoke: {len(tests) - len(failed)}/{len(tests)} passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
