"""Repair receipts — canonical record for every maintenance action.

Each Receipt:
  * repair_id            — uuid, immutable
  * lineage              — list of prior repair_ids it depends on
  * before / after       — evidence snapshots (dict)
  * rollback_snapshot    — path to restorable artifact (or None for read-only ops)
  * confidence           — coordinator's confidence in the validation
  * validation_status    — VALIDATED / FAILED / SKIPPED / UNRESOLVED
  * outcome              — APPLIED / DRY_RUN / REJECTED / ESCALATED / UNRESOLVED

Receipts are appended to telemetry/maintenance_receipts.jsonl AND emitted
through the Constitution event bus (LAW_3) when available.

UNRESOLVED is a first-class outcome. Do NOT collapse it into APPLIED.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)


VALIDATION_VALIDATED   = "VALIDATED"
VALIDATION_FAILED      = "FAILED"
VALIDATION_SKIPPED     = "SKIPPED"
VALIDATION_UNRESOLVED  = "UNRESOLVED"

OUTCOME_APPLIED      = "APPLIED"
OUTCOME_DRY_RUN      = "DRY_RUN"
OUTCOME_REJECTED     = "REJECTED"
OUTCOME_ESCALATED    = "ESCALATED"
OUTCOME_UNRESOLVED   = "UNRESOLVED"


from omega.paths import telemetry_root
RECEIPT_LOG = telemetry_root() / "maintenance_receipts.jsonl"


@dataclass(frozen=True)
class Receipt:
    repair_id:           str
    issue_id:            str
    tier:                str
    actor:               str                # e.g. "RepairCoordinator"
    action:              str                # e.g. "ui_state_resync"
    outcome:             str                # OUTCOME_*
    validation_status:   str                # VALIDATION_*
    confidence:          float
    before:              dict
    after:               dict
    rollback_snapshot:   Optional[str]      # path or None
    lineage:             list = field(default_factory=list)
    timestamp:           float = field(default_factory=time.time)
    note:                str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def fresh_repair_id() -> str:
    return f"rep-{uuid.uuid4().hex[:12]}"


def build_receipt(*, issue_id: str, tier: str, action: str, outcome: str,
                  validation_status: str, before: dict, after: dict,
                  rollback_snapshot: Optional[str] = None,
                  confidence: float = 1.0, lineage: Optional[list] = None,
                  actor: str = "RepairCoordinator",
                  note: str = "") -> Receipt:
    return Receipt(
        repair_id         = fresh_repair_id(),
        issue_id          = issue_id,
        tier              = tier,
        actor             = actor,
        action            = action,
        outcome           = outcome,
        validation_status = validation_status,
        confidence        = confidence,
        before            = before,
        after             = after,
        rollback_snapshot = rollback_snapshot,
        lineage           = lineage or [],
        note              = note,
    )


def _append_jsonl(r: Receipt) -> None:
    try:
        RECEIPT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with RECEIPT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
    except Exception as e:
        _log.warning(f"receipt jsonl append failed: {e}")


def _emit_constitution(r: Receipt) -> None:
    """Best-effort LAW_3 emit through the substrate Constitution.

    No-op if substrate is unavailable. Never raises.
    """
    try:
        import sys
        substrate = Path(__file__).resolve().parent.parent.parent
        if str(substrate) not in sys.path:
            sys.path.append(str(substrate))
        from kernel.constitution import get_constitution
        con = get_constitution()
        con.record_receipt(
            "maintenance", r.actor, r.action, r.outcome,
            {
                "repair_id":         r.repair_id,
                "issue_id":          r.issue_id,
                "tier":              r.tier,
                "validation_status": r.validation_status,
                "confidence":        r.confidence,
                "rollback":          r.rollback_snapshot or "NONE",
            },
            lineage=r.lineage,
        )
        if r.rollback_snapshot:
            con.assert_recoverable("maintenance", r.actor, r.action,
                                    r.rollback_snapshot)
    except Exception as e:
        _log.debug(f"constitution emit unavailable: {e}")


def emit_receipt(r: Receipt) -> Receipt:
    """Append to jsonl + emit LAW_3 through substrate. Returns the receipt."""
    _append_jsonl(r)
    _emit_constitution(r)
    return r
