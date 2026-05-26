"""engine.workers.contracts — L0 worker data contracts (truth-layer types).

GOLD PILLAR rule: shared data structures MUST originate at the truth layer, not
the execution layer. This module is a LEAF — it imports ONLY stdlib and nothing
internal. base_worker / artifact_validator / quality_gate import these types
from here, which eliminates the engine.workers import cycles at their source
(no eager cross-module coupling through base_worker).

DO NOT add internal imports to this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# Workers below this validation score auto-queue refinement.
QUALITY_REFINE_THRESHOLD = 0.55


@dataclass
class WorkerRequest:
    intent_text:   str
    spec:          Any
    kind:          str = ""            # subkind: synthesize|narration|trailer etc.
    params:        dict = field(default_factory=dict)
    refinement_pass: int = 0
    parent_artifact: Optional[str] = None    # for refinement runs


@dataclass
class ValidationResult:
    valid:    bool
    score:    float                  # 0..1
    checks:   dict = field(default_factory=dict)   # named check → bool/value
    error:    str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WorkerOutcome:
    worker_id:        str
    worker_name:      str
    realm:            str
    state:            str             # READY | FAIL | DEGRADED
    intent_text:      str
    started_at:       float
    finished_at:      float
    duration_ms:      float
    workspace:        str             # output directory path
    manifest_path:    Optional[str]
    artifacts:        list = field(default_factory=list)    # list of dicts
    backend:          str = ""
    error:            str = ""
    remediation:      str = ""
    refinement_pass:  int = 0
    overall_validation_score: float = 0.0
    auto_refine_queued: bool = False

    def to_dict(self) -> dict:
        return asdict(self)
