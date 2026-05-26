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
import sys
import time
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)


def _telemetry_dir() -> Path:
    """Persistent telemetry dir next to the .exe (frozen) or project root
    (dev). NEVER _MEIPASS — execution receipts are canonical proof and must
    survive process exit. Mirrors engine/mem_palace/memory_store.py."""
    try:
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).resolve().parent
        else:
            base = Path(__file__).resolve().parent.parent
        d = base / "telemetry"
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        return Path.home() / ".stratum" / "telemetry"


EXECUTION_RECEIPTS_LOG = _telemetry_dir() / "execution_receipts.jsonl"


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


# ── Receipt batching (Build Acceleration Directive item #6) ─────────────
# In-memory buffer + 3s background flush. Reduces per-event file I/O during
# autonomous loop bursts (WON cognition + ui_guard + state transitions).
#
# Durability fix (build-018): boot-critical receipts (bootstrap_phase,
# state_transition, tab_spawn) force-flush immediately so a hang or
# non-graceful exit between buffer ticks cannot strand them. Routine
# receipts (cognition_cycle, ui_guard, etc.) batch as before.
import atexit as _atexit
import threading as _threading

_RECEIPT_BUFFER: list[str] = []
_RECEIPT_LOCK = _threading.Lock()
_RECEIPT_FLUSH_INTERVAL_S = 3.0

# Task prefixes that bypass the 3s batch and write through immediately. Any
# task name starting with one of these strings triggers a synchronous flush
# right after enqueue. Keeps boot/state observability durable even when the
# process hangs or is killed before atexit fires.
_FORCE_FLUSH_PREFIXES = (
    "bootstrap_phase",     # 7-phase HOTWIRE boot
    "state_transition",    # SystemStateManager
    "tab_spawn",           # dynamic workspace spawn (build-018)
    "runtime_singleton",   # RuntimeSingletonRegistry (build-018)
    "workspace_capability", # WorkspaceCapabilityContract (build-018)
    "boot_preflight",      # BootValidator aggregate
    "shutdown",            # any graceful-exit signal
)


def _flush_buffer() -> None:
    """Drain the in-memory buffer to disk in one open/write/close. Safe to
    call from any thread; never raises."""
    with _RECEIPT_LOCK:
        if not _RECEIPT_BUFFER:
            return
        lines = list(_RECEIPT_BUFFER)
        _RECEIPT_BUFFER.clear()
    try:
        EXECUTION_RECEIPTS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with EXECUTION_RECEIPTS_LOG.open("a", encoding="utf-8") as fh:
            for ln in lines:
                fh.write(ln + "\n")
    except Exception as e:
        _log.warning("execution receipt batch flush failed: %s", e)
        # Re-queue on failure so we don't lose the receipts
        with _RECEIPT_LOCK:
            _RECEIPT_BUFFER[:0] = lines


def _flush_thread_loop() -> None:
    import time as _t
    while True:
        try:
            _t.sleep(_RECEIPT_FLUSH_INTERVAL_S)
            _flush_buffer()
        except Exception:
            pass


_FLUSH_THREAD = _threading.Thread(
    target=_flush_thread_loop, name="ReceiptFlush", daemon=True,
)
_FLUSH_THREAD.start()
_atexit.register(_flush_buffer)


def force_flush_receipts() -> int:
    """Public shutdown hook — drain buffer synchronously. Returns the
    count flushed for caller logging. Never raises."""
    with _RECEIPT_LOCK:
        n = len(_RECEIPT_BUFFER)
    _flush_buffer()
    return n


# Best-effort SIGTERM/SIGBREAK handler — Windows taskkill / Ctrl-Break.
# atexit alone misses these; this gives us one more chance to land
# bootstrap_phase + state_transition receipts before the kernel reaps us.
try:
    import signal as _signal
    def _on_signal(signum, frame):
        try:
            _flush_buffer()
        except Exception:
            pass
        # Re-raise default behavior — we don't swallow the signal.
        try:
            _signal.signal(signum, _signal.SIG_DFL)
            import os as _os
            _os.kill(_os.getpid(), signum)
        except Exception:
            pass
    for _sig_name in ("SIGTERM", "SIGBREAK", "SIGINT"):
        _sig = getattr(_signal, _sig_name, None)
        if _sig is not None:
            try:
                _signal.signal(_sig, _on_signal)
            except (ValueError, OSError):
                pass  # Signal not installable from non-main thread
except Exception:
    pass


def _is_critical(task: str) -> bool:
    """Boot/state receipts force-flush — surviving a hang is non-negotiable."""
    return any(task.startswith(p) for p in _FORCE_FLUSH_PREFIXES)


def _append_jsonl(receipt: ExecutionReceipt) -> None:
    """Enqueue receipt for batched flush. Critical receipts (boot/state)
    bypass the batch and write through immediately so they survive a
    process hang or kill before the 3s tick fires."""
    try:
        line = json.dumps(receipt.to_dict(), ensure_ascii=False)
        with _RECEIPT_LOCK:
            _RECEIPT_BUFFER.append(line)
        if _is_critical(receipt.task):
            _flush_buffer()
    except Exception as e:
        _log.warning("execution receipt enqueue failed: %s", e)


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
