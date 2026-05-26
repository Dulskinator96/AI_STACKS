"""kernel.contracts — runtime contracts, truth model, execution state model.

Pure stdlib. No engine imports, no heavy deps — this module is trivially
verifiable on its own and defines the vocabulary every other kernel module
speaks.

TRUTH MODEL (dual-layer, inherited from CTES v2):

    INTERNAL (strict reality — never lost, never softened):
        RESOLVED    real validated artifact + linked ledger execution_id
        PARTIAL     produced output but degraded / sub-threshold
        UNRESOLVED  ran but produced nothing verifiable
        FAILED      execution raised / hard error
        BLOCKED     could not run — no backend / no worker / dependency unmet

    EXTERNAL (normalized display only — derived from INTERNAL):
        PRESENT     ← RESOLVED
        LIMITED     ← PARTIAL
        DEFERRED    ← UNRESOLVED | FAILED | BLOCKED

Decision layers MUST read the INTERNAL state. EXTERNAL is for display only.
"""
from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Optional


# ── Truth states ──────────────────────────────────────────────────────────
class TruthState(str, Enum):
    RESOLVED   = "RESOLVED"
    PARTIAL    = "PARTIAL"
    UNRESOLVED = "UNRESOLVED"
    FAILED     = "FAILED"
    BLOCKED    = "BLOCKED"


class ExternalState(str, Enum):
    PRESENT  = "PRESENT"
    LIMITED  = "LIMITED"
    DEFERRED = "DEFERRED"


_INTERNAL_TO_EXTERNAL: dict[TruthState, ExternalState] = {
    TruthState.RESOLVED:   ExternalState.PRESENT,
    TruthState.PARTIAL:    ExternalState.LIMITED,
    TruthState.UNRESOLVED: ExternalState.DEFERRED,
    TruthState.FAILED:     ExternalState.DEFERRED,
    TruthState.BLOCKED:    ExternalState.DEFERRED,
}


def external_for(internal: TruthState) -> ExternalState:
    """Normalize an internal truth state for external display. Never raises;
    unknown states degrade to DEFERRED (the honest 'not present' default)."""
    try:
        return _INTERNAL_TO_EXTERNAL[TruthState(internal)]
    except Exception:
        return ExternalState.DEFERRED


# ── Per-task lifecycle ──────────────────────────────────────────────────────
class TaskState(str, Enum):
    PENDING  = "PENDING"
    ROUTING  = "ROUTING"
    RUNNING  = "RUNNING"
    VERIFIED = "VERIFIED"
    RESOLVED = "RESOLVED"
    FAILED   = "FAILED"
    BLOCKED  = "BLOCKED"
    SKIPPED  = "SKIPPED"


# ── Independent verification primitive (zero-trust) ─────────────────────────
def sha256_file(path: str | Path, chunk: int = 1 << 20) -> Optional[str]:
    """Independently hash a file the kernel claims exists. Returns None if the
    file is absent/unreadable — that None IS the evidence that a claimed
    artifact is not real. Never raises."""
    try:
        p = Path(path)
        if not p.is_file():
            return None
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for block in iter(lambda: fh.read(chunk), b""):
                h.update(block)
        return h.hexdigest()
    except Exception:
        return None


def now_ts() -> float:
    return time.time()


def new_run_id() -> str:
    return f"run-{int(time.time())}-{uuid.uuid4().hex[:8]}"


def new_task_id(realm: str, idx: int) -> str:
    return f"t{idx}-{(realm or 'misc').lower()}-{uuid.uuid4().hex[:6]}"


# ── Verified artifact record ────────────────────────────────────────────────
@dataclass
class ArtifactRecord:
    """An artifact AFTER independent kernel re-verification."""
    path:            str
    exists_on_disk:  bool                      # kernel-checked, not worker-claimed
    size_bytes:      int = 0
    kernel_sha256:   Optional[str] = None      # hashed by the kernel itself
    worker_sha256:   Optional[str] = None      # what the worker reported
    hash_match:      Optional[bool] = None     # True iff both present and equal
    validation_valid: bool = False
    validation_score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# ── DAG task definition (compiled, pre-execution) ───────────────────────────
@dataclass
class KernelTask:
    task_id:     str
    realm:       str
    intent_text: str
    depends_on:  list[str] = field(default_factory=list)
    params:      dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ── Task result (post-execution, with strict truth) ─────────────────────────
@dataclass
class TaskResult:
    task_id:        str
    realm:          str
    state:          TaskState
    truth:          TruthState
    external:       ExternalState
    intent_text:    str
    started_at:     float = 0.0
    finished_at:    float = 0.0
    duration_ms:    float = 0.0
    worker_state:   str = ""                   # READY|FAIL|DEGRADED from worker
    backend:        str = ""
    execution_id:   Optional[str] = None       # ledger linkage (truth anchor)
    ledger_confirmed: bool = False             # row read back from SQLite
    artifacts:      list = field(default_factory=list)  # ArtifactRecord dicts
    error:          str = ""
    remediation:    str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"]    = self.state.value if isinstance(self.state, TaskState) else self.state
        d["truth"]    = self.truth.value if isinstance(self.truth, TruthState) else self.truth
        d["external"] = self.external.value if isinstance(self.external, ExternalState) else self.external
        return d


# ── Whole-run result ────────────────────────────────────────────────────────
@dataclass
class KernelRunResult:
    run_id:        str
    intent_text:   str
    created_at:    float
    enriched:      dict = field(default_factory=dict)     # EnrichedIntent.to_dict()
    dag:           list = field(default_factory=list)      # KernelTask dicts (topo order)
    tasks:         list = field(default_factory=list)      # TaskResult dicts
    overall_truth: TruthState = TruthState.UNRESOLVED
    overall_external: ExternalState = ExternalState.DEFERRED
    confidence:    float = 0.0                              # 0..1, evidence-weighted
    entropy_class: str = "UNKNOWN"                          # DETERMINISTIC|CONVERGENT|DIVERGENT
    drift:         list = field(default_factory=list)       # drift findings
    telemetry_path: Optional[str] = None
    finished_at:   float = 0.0
    duration_ms:   float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["overall_truth"]    = self.overall_truth.value if isinstance(self.overall_truth, TruthState) else self.overall_truth
        d["overall_external"] = self.overall_external.value if isinstance(self.overall_external, ExternalState) else self.overall_external
        return d


# ── Truth aggregation (no optimism: worst real state dominates) ─────────────
_TRUTH_RANK = {
    TruthState.RESOLVED:   4,
    TruthState.PARTIAL:    3,
    TruthState.UNRESOLVED: 2,
    TruthState.FAILED:     1,
    TruthState.BLOCKED:    0,
}


def aggregate_truth(states: list[TruthState]) -> TruthState:
    """Roll up per-task truth into a run-level verdict. A run is only as good
    as its weakest required task: if any task is BLOCKED/FAILED while none
    RESOLVED, the run is not RESOLVED. RESOLVED only when every task RESOLVED."""
    if not states:
        return TruthState.UNRESOLVED
    ranks = [_TRUTH_RANK.get(s, 2) for s in states]
    if all(r == 4 for r in ranks):
        return TruthState.RESOLVED
    if any(r == 4 for r in ranks):
        return TruthState.PARTIAL          # some real output, some not
    # nothing resolved → report the worst real signal
    worst = min(ranks)
    for st, r in _TRUTH_RANK.items():
        if r == worst:
            return st
    return TruthState.UNRESOLVED
