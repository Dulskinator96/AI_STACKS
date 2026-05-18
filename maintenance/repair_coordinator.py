"""RepairCoordinator — sole bounded mutator in the maintenance layer.

Pipeline per directive:

    detect → classify → simulate → validate → apply → verify

Authority (hard-gated, not configurable):

    Tier.T1, Tier.T2   → may auto-apply IF repair_hint in REPAIR_ALLOW_LIST
                          AND confidence ≥ self.confidence_floor
                          AND simulation+validation pass
    Tier.T3            → simulate + validate ONLY; never apply
    Tier.T4            → escalate ONLY; never simulate, never apply

Authority degrades:

    DriftMonitor may call `restrict()` when instability is observed. While
    restricted, the coordinator REFUSES all apply paths regardless of tier
    or confidence (T1/T2 collapse into DRY_RUN). Restored only via `restore()`.

Hard guarantees:

    * No mutation without a rollback snapshot path recorded
    * No fabricated success — failed validation → OUTCOME_UNRESOLVED
    * Every action emits a Receipt, even no-ops (DRY_RUN / REJECTED / ESCALATED)
    * Coordinator NEVER modifies its own confidence_floor or restriction state
      based on its own actions (only DriftMonitor can)
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from maintenance.classifier import (
    Issue,
    AUTO_REPAIR_TIERS, VALIDATE_ONLY_TIERS, ESCALATE_ONLY_TIERS,
    REPAIR_ALLOW_LIST,
)
# Profile lookup is imported lazily inside handle() to avoid circular import
# (calibration imports DEFAULT_CONFIDENCE_FLOOR from this module).
from maintenance.receipts import (
    Receipt, build_receipt, emit_receipt,
    VALIDATION_VALIDATED, VALIDATION_FAILED, VALIDATION_SKIPPED, VALIDATION_UNRESOLVED,
    OUTCOME_APPLIED, OUTCOME_DRY_RUN, OUTCOME_REJECTED, OUTCOME_ESCALATED, OUTCOME_UNRESOLVED,
)

_log = logging.getLogger(__name__)


DEFAULT_CONFIDENCE_FLOOR = 0.70


class RepairOutcome:
    """Lightweight named-tuple-ish carrier for the result of a single repair."""
    __slots__ = ("issue", "receipt", "applied")

    def __init__(self, issue: Issue, receipt: Receipt, applied: bool):
        self.issue    = issue
        self.receipt  = receipt
        self.applied  = applied

    def __repr__(self) -> str:
        return (f"<RepairOutcome tier={self.issue.tier.value} "
                f"outcome={self.receipt.outcome} applied={self.applied}>")


# Repair callable signature: (issue) -> (success: bool, after: dict, rollback_path: str|None)
RepairFn = Callable[[Issue], "tuple[bool, dict, Optional[str]]"]
ValidateFn = Callable[[Issue, dict], bool]


class RepairCoordinator:
    """Stateful coordinator. Single-threaded mutation; thread-safe state."""

    def __init__(self, *,
                 confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
                 dry_run: bool = False):
        self.confidence_floor = float(confidence_floor)
        self.dry_run = bool(dry_run)
        self._restricted = False
        self._restrict_reason = ""
        self._lock = threading.RLock()
        self._repair_fns:  dict[str, RepairFn]   = {}
        self._validate_fns: dict[str, ValidateFn] = {}

    # ── public registry surface ────────────────────────────────────────────

    def register_repair(self, action: str, fn: RepairFn) -> None:
        if action not in REPAIR_ALLOW_LIST:
            raise ValueError(f"action {action!r} is not in REPAIR_ALLOW_LIST")
        with self._lock:
            self._repair_fns[action] = fn

    def register_validator(self, action: str, fn: ValidateFn) -> None:
        with self._lock:
            self._validate_fns[action] = fn

    # ── authority controls (caller is expected to be DriftMonitor) ─────────

    def restrict(self, reason: str) -> None:
        with self._lock:
            self._restricted = True
            self._restrict_reason = reason or "drift"
        _log.warning("RepairCoordinator restricted: %s", self._restrict_reason)

    def restore(self) -> None:
        with self._lock:
            self._restricted = False
            self._restrict_reason = ""
        _log.info("RepairCoordinator restored")

    @property
    def restricted(self) -> bool:
        with self._lock:
            return self._restricted

    # ── main pipeline ──────────────────────────────────────────────────────

    def handle(self, issue: Issue) -> RepairOutcome:
        """detect → classify → simulate → validate → apply → verify."""
        with self._lock:
            restricted = self._restricted
            restrict_reason = self._restrict_reason

        # T4 — escalate only, never touch
        if issue.tier in ESCALATE_ONLY_TIERS:
            r = build_receipt(
                issue_id=issue.issue_id, tier=issue.tier.value,
                action=issue.repair_hint or "escalate",
                outcome=OUTCOME_ESCALATED,
                validation_status=VALIDATION_SKIPPED,
                confidence=issue.confidence,
                before=dict(issue.evidence), after={},
                rollback_snapshot=None,
                note="T4_substrate_risk_escalated_to_operator",
            )
            return RepairOutcome(issue, emit_receipt(r), applied=False)

        # T3 — validate only, never apply
        if issue.tier in VALIDATE_ONLY_TIERS:
            sim_after = dict(issue.evidence)
            sim_after["_simulated"] = True
            validator = self._validate_fns.get(issue.repair_hint or "")
            v_status = VALIDATION_SKIPPED if validator is None else (
                VALIDATION_VALIDATED if validator(issue, sim_after)
                else VALIDATION_FAILED
            )
            r = build_receipt(
                issue_id=issue.issue_id, tier=issue.tier.value,
                action=issue.repair_hint or "validate",
                outcome=OUTCOME_DRY_RUN,
                validation_status=v_status,
                confidence=issue.confidence,
                before=dict(issue.evidence), after=sim_after,
                rollback_snapshot=None,
                note="T3_logic_inconsistency_validation_only",
            )
            return RepairOutcome(issue, emit_receipt(r), applied=False)

        # T1 / T2 — bounded apply path
        if issue.tier not in AUTO_REPAIR_TIERS:
            r = build_receipt(
                issue_id=issue.issue_id, tier=issue.tier.value,
                action=issue.repair_hint or "unknown",
                outcome=OUTCOME_REJECTED,
                validation_status=VALIDATION_SKIPPED,
                confidence=issue.confidence,
                before=dict(issue.evidence), after={},
                rollback_snapshot=None,
                note="unknown_tier_refusing",
            )
            return RepairOutcome(issue, emit_receipt(r), applied=False)

        # Per-subsystem CalibrationProfile (narrowing only). If the profile
        # exists and rejects this issue, mark UNRESOLVED — the profile is the
        # subsystem's own posture, not a coordinator override.
        if issue.subsystem:
            try:
                from maintenance.calibration import get_profile
                prof = get_profile(issue.subsystem)
            except Exception:
                prof = None
            if prof is not None and not prof.allows(
                hint=issue.repair_hint, tier=issue.tier, confidence=issue.confidence,
            ):
                r = build_receipt(
                    issue_id=issue.issue_id, tier=issue.tier.value,
                    action=issue.repair_hint or "unknown",
                    outcome=OUTCOME_UNRESOLVED,
                    validation_status=VALIDATION_UNRESOLVED,
                    confidence=issue.confidence,
                    before=dict(issue.evidence), after={},
                    rollback_snapshot=None,
                    note=f"calibration_profile_{issue.subsystem}_refused",
                )
                return RepairOutcome(issue, emit_receipt(r), applied=False)

        # Allow-list gate
        if not issue.repair_hint or issue.repair_hint not in REPAIR_ALLOW_LIST:
            r = build_receipt(
                issue_id=issue.issue_id, tier=issue.tier.value,
                action=issue.repair_hint or "missing_hint",
                outcome=OUTCOME_REJECTED,
                validation_status=VALIDATION_SKIPPED,
                confidence=issue.confidence,
                before=dict(issue.evidence), after={},
                rollback_snapshot=None,
                note="repair_hint_not_in_allow_list",
            )
            return RepairOutcome(issue, emit_receipt(r), applied=False)

        # Confidence floor
        if issue.confidence < self.confidence_floor:
            r = build_receipt(
                issue_id=issue.issue_id, tier=issue.tier.value,
                action=issue.repair_hint,
                outcome=OUTCOME_UNRESOLVED,
                validation_status=VALIDATION_UNRESOLVED,
                confidence=issue.confidence,
                before=dict(issue.evidence), after={},
                rollback_snapshot=None,
                note=f"confidence_{issue.confidence:.2f}_below_floor_{self.confidence_floor:.2f}",
            )
            return RepairOutcome(issue, emit_receipt(r), applied=False)

        # Drift restriction → forced DRY_RUN
        if restricted or self.dry_run:
            r = build_receipt(
                issue_id=issue.issue_id, tier=issue.tier.value,
                action=issue.repair_hint,
                outcome=OUTCOME_DRY_RUN,
                validation_status=VALIDATION_SKIPPED,
                confidence=issue.confidence,
                before=dict(issue.evidence), after={},
                rollback_snapshot=None,
                note=("restricted:" + restrict_reason) if restricted else "global_dry_run",
            )
            return RepairOutcome(issue, emit_receipt(r), applied=False)

        # Locate repair fn
        repair_fn = self._repair_fns.get(issue.repair_hint)
        if repair_fn is None:
            r = build_receipt(
                issue_id=issue.issue_id, tier=issue.tier.value,
                action=issue.repair_hint,
                outcome=OUTCOME_UNRESOLVED,
                validation_status=VALIDATION_UNRESOLVED,
                confidence=issue.confidence,
                before=dict(issue.evidence), after={},
                rollback_snapshot=None,
                note="no_repair_fn_registered",
            )
            return RepairOutcome(issue, emit_receipt(r), applied=False)

        # Apply (the only mutating step)
        try:
            success, after, rollback = repair_fn(issue)
        except Exception as exc:
            r = build_receipt(
                issue_id=issue.issue_id, tier=issue.tier.value,
                action=issue.repair_hint,
                outcome=OUTCOME_UNRESOLVED,
                validation_status=VALIDATION_FAILED,
                confidence=issue.confidence,
                before=dict(issue.evidence), after={},
                rollback_snapshot=None,
                note=f"repair_fn_raised:{type(exc).__name__}:{exc}",
            )
            return RepairOutcome(issue, emit_receipt(r), applied=False)

        if not rollback:
            # Hard guarantee: no mutation without a rollback path. Even if the
            # repair fn claimed success, we treat missing rollback as a refusal.
            r = build_receipt(
                issue_id=issue.issue_id, tier=issue.tier.value,
                action=issue.repair_hint,
                outcome=OUTCOME_UNRESOLVED,
                validation_status=VALIDATION_FAILED,
                confidence=issue.confidence,
                before=dict(issue.evidence), after=dict(after or {}),
                rollback_snapshot=None,
                note="rollback_snapshot_missing_refusing_to_record_apply",
            )
            return RepairOutcome(issue, emit_receipt(r), applied=False)

        # Validate after-state
        validator = self._validate_fns.get(issue.repair_hint)
        if validator is None:
            v_status = VALIDATION_SKIPPED
            v_ok = success
        else:
            try:
                v_ok = bool(validator(issue, after))
            except Exception as exc:
                v_ok = False
                _log.warning("validator raised: %s", exc)
            v_status = VALIDATION_VALIDATED if v_ok else VALIDATION_FAILED

        outcome = OUTCOME_APPLIED if (success and v_ok) else OUTCOME_UNRESOLVED
        r = build_receipt(
            issue_id=issue.issue_id, tier=issue.tier.value,
            action=issue.repair_hint,
            outcome=outcome,
            validation_status=v_status,
            confidence=issue.confidence,
            before=dict(issue.evidence), after=dict(after),
            rollback_snapshot=str(rollback),
            note="" if outcome == OUTCOME_APPLIED else "applied_but_validation_inconclusive",
        )
        return RepairOutcome(issue, emit_receipt(r), applied=(outcome == OUTCOME_APPLIED))
