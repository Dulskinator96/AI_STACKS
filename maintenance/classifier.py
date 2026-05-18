"""Issue classification — Tier (authority gate) + Severity + Issue dataclass.

Tier policy is HARD-CODED, not configurable. Substrate cannot escalate its own
authority by re-classifying an issue.
"""
from __future__ import annotations

import enum
import hashlib
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional


class Tier(enum.Enum):
    """Authority gate. Determines what RepairCoordinator may do with an issue."""
    T1 = "T1_COSMETIC"          # UI/render inconsistency      → auto-apply allowed
    T2 = "T2_OPERATIONAL"       # operational degradation      → bounded patch allowed
    T3 = "T3_LOGIC"             # logic inconsistency          → validation only
    T4 = "T4_SUBSTRATE"         # substrate / systemic risk    → escalation only


class Severity(enum.Enum):
    LOW       = "LOW"
    MEDIUM    = "MEDIUM"
    HIGH      = "HIGH"
    CRITICAL  = "CRITICAL"


AUTO_REPAIR_TIERS  = frozenset({Tier.T1, Tier.T2})
VALIDATE_ONLY_TIERS = frozenset({Tier.T3})
ESCALATE_ONLY_TIERS = frozenset({Tier.T4})


REPAIR_ALLOW_LIST = frozenset({
    # T1 — cosmetic / UI
    "ui_state_resync",
    "ui_widget_refresh",
    "stale_cache_invalidation",
    "deterministic_format",
    # T2 — operational (retry-safe / non-destructive)
    "retry_safe_operation",
    "non_destructive_sync",
    "queue_cleanup",
    "event_rebinding",
    "temporary_process_restart",
})


@dataclass(frozen=True)
class Issue:
    """A detected operational defect awaiting classification / repair.

    Issues are produced by READ-ONLY observers. They never carry a patch — the
    patch (if any) is synthesized by RepairCoordinator under its own authority.

    ``subsystem`` selects the CalibrationProfile used for narrowing. When
    empty, the coordinator falls back to its built-in defaults.
    """
    issue_id:     str
    observer:     str               # e.g. "RuntimeHealthAgent"
    kind:         str               # short stable identifier (e.g. "exception.unhandled")
    tier:         Tier
    severity:     Severity
    surface:      str               # human-readable locator ("worker_pool.AskWorker")
    evidence:     dict              # raw observation (timestamps, counts, snippet)
    detected_at:  float = field(default_factory=time.time)
    repair_hint:  Optional[str] = None    # one of REPAIR_ALLOW_LIST, or None
    confidence:   float = 1.0
    subsystem:    str = ""          # "" → default profile; else key into calibration registry

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tier"]     = self.tier.value
        d["severity"] = self.severity.value
        return d


def make_issue_id(observer: str, kind: str, surface: str, *, salt: str = "") -> str:
    """Deterministic id from (observer, kind, surface) — dedupe across ticks."""
    h = hashlib.sha1(f"{observer}|{kind}|{surface}|{salt}".encode("utf-8"))
    return f"iss-{h.hexdigest()[:12]}"


def fresh_issue_id() -> str:
    return f"iss-{uuid.uuid4().hex[:12]}"
