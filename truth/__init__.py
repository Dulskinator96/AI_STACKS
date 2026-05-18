"""truth/ — Execution Receipt envelope.

Phase 1.3 of the Operational Stability plan.

The truth layer answers ONE question for every action:
    "Did X actually happen, with what evidence, with what verifier?"

It is the backbone of:
    * auditability — every action is recorded with provenance
    * debugging   — failures retain enough state to reconstruct
    * agent trust — no fabricated success states
    * automation  — downstream consumers can rely on receipts

This package wraps maintenance.receipts.Receipt (LAW_3) and adds the
canonical Execution Receipt envelope the user's plan specified:

    {
      "task": "...",
      "executor": "...",
      "artifact": "...",
      "verified": true,
      "sha256": "...",
      "duration_ms": 41232,
      "rollback_status": "...",
      "failure_reason": "...",
    }

Unresolved or failed actions remain VISIBLE — no silent dropping.
"""
from truth.receipt_engine import (
    ExecutionReceipt,
    record_execution,
    verify_artifact_sha256,
    EXECUTION_RECEIPTS_LOG,
)

__all__ = [
    "ExecutionReceipt",
    "record_execution",
    "verify_artifact_sha256",
    "EXECUTION_RECEIPTS_LOG",
]
