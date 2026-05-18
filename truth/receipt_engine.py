"""truth/receipt_engine.py — canonical Execution Receipt envelope.

Records "did X actually happen" with sha256-verifiable evidence.

Storage:
    telemetry/execution_receipts.jsonl
    (append-only; one ExecutionReceipt per line)

Also emits a parallel LAW_3 receipt through the substrate Constitution
(best-effort, no-op if substrate unreachable).

Public surface:
    record_execution(...)              — record an action with verification
    verify_artifact_sha256(path)       — utility: compute SHA-256 of a file
    ExecutionReceipt                   — dataclass envelope
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)


EXECUTION_RECEIPTS_LOG = (
    Path(__file__).resolve().parent.parent / "telemetry" / "execution_receipts.jsonl"
)


@dataclass(frozen=True)
class ExecutionReceipt:
    receipt_id:       str
    task:             str
    executor:         str
    artifact:         Optional[str]       # path / identifier
    sha256:           Optional[str]       # of artifact, if file
    verified:         bool
    duration_ms:      float
    timestamp:        float
    rollback_status:  Optional[str] = None
    failure_reason:   Optional[str] = None
    evidence:         dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _fresh_id() -> str:
    return f"exec-{uuid.uuid4().hex[:12]}"


def verify_artifact_sha256(path: str | Path) -> Optional[str]:
    """Compute SHA-256 of a file. Returns None on any failure."""
    p = Path(path)
    if not p.is_file():
        return None
    try:
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        _log.warning("sha256 verify failed for %s: %s", p, e)
        return None


def _append_jsonl(receipt: ExecutionReceipt) -> None:
    try:
        EXECUTION_RECEIPTS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with EXECUTION_RECEIPTS_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(receipt.to_dict(), ensure_ascii=False) + "\n")
    except Exception as e:
        _log.warning("execution receipt append failed: %s", e)


def _emit_constitution(receipt: ExecutionReceipt) -> None:
    """Best-effort LAW_3 emit through the substrate. Never raises."""
    try:
        import sys
        substrate = Path(__file__).resolve().parent.parent.parent
        if str(substrate) not in sys.path:
            sys.path.append(str(substrate))
        from kernel.constitution import get_constitution
        con = get_constitution()
        outcome = "VALIDATED" if receipt.verified else (
            "UNRESOLVED" if receipt.failure_reason is None else "FAILED"
        )
        con.record_receipt(
            "truth", receipt.executor, receipt.task, outcome,
            {
                "receipt_id":      receipt.receipt_id,
                "artifact":        receipt.artifact or "NONE",
                "sha256":          receipt.sha256 or "NONE",
                "duration_ms":     receipt.duration_ms,
                "rollback_status": receipt.rollback_status or "NONE",
                "failure_reason":  receipt.failure_reason or "",
            },
        )
    except Exception as e:
        _log.debug("constitution emit skipped: %s", e)


def record_execution(*, task: str, executor: str,
                      artifact: Optional[str] = None,
                      duration_ms: float = 0.0,
                      verified: bool = False,
                      compute_sha256: bool = True,
                      rollback_status: Optional[str] = None,
                      failure_reason: Optional[str] = None,
                      evidence: Optional[dict] = None) -> ExecutionReceipt:
    """Record one execution with provenance + verification.

    If `artifact` is a file path and `compute_sha256=True`, the SHA-256
    is computed before the receipt is written.
    """
    sha = None
    if artifact and compute_sha256:
        sha = verify_artifact_sha256(artifact)

    receipt = ExecutionReceipt(
        receipt_id=_fresh_id(),
        task=task,
        executor=executor,
        artifact=artifact,
        sha256=sha,
        verified=bool(verified),
        duration_ms=float(duration_ms),
        timestamp=time.time(),
        rollback_status=rollback_status,
        failure_reason=failure_reason,
        evidence=evidence or {},
    )
    _append_jsonl(receipt)
    _emit_constitution(receipt)
    _log.info("EXEC %s by %s → verified=%s artifact=%s",
               task, executor, verified, artifact or "—")
    return receipt
