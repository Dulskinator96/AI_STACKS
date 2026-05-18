"""stability_engine.py — pure evaluator of system stability.

DriftMonitor remains the *action* surface (it has authority to restrict the
RepairCoordinator). StabilityEngine is the pure *evaluator*: it consumes a
HistoryReport plus live signals and produces a StabilityReport that callers
can act on.

Priority order (per constitutional directive):
    stability first → coherence second → efficiency third → adaptation fourth

The engine never mutates anything. It surfaces an Authority recommendation
that the Cortex applies via the coordinator's restrict/restore API.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional

from maintenance.repair_history import HistoryReport, analyze


class Authority(enum.Enum):
    FULL       = "FULL"          # all profiles honored at full posture
    REDUCED    = "REDUCED"       # T2 auto-apply gated; T1 still allowed
    SUSPENDED  = "SUSPENDED"     # all auto-apply collapsed to DRY_RUN
    QUARANTINE = "QUARANTINE"    # observers continue; no apply at all


@dataclass(frozen=True)
class StabilityReport:
    """Pure data — no methods that mutate state."""
    overall_score:        float                # 0.0 (collapse) .. 1.0 (calm)
    recommended_authority: Authority
    reasons:              tuple = field(default_factory=tuple)
    recurring_clusters:   int = 0
    unstable_clusters:    int = 0
    applied:              int = 0
    unresolved:           int = 0
    total_receipts:       int = 0
    window_seconds:       float = 900.0


def evaluate(*, window_seconds: float = 900.0,
              report: Optional[HistoryReport] = None,
              unstable_threshold: int = 2,
              unresolved_share_threshold: float = 0.50,
              recurring_threshold: int = 5) -> StabilityReport:
    """Produce a StabilityReport. Reads receipts in window if report omitted."""
    hist = report or analyze(window_seconds=window_seconds)

    reasons: list[str] = []
    score = 1.0

    if hist.unstable:
        if len(hist.unstable) >= unstable_threshold:
            reasons.append(f"unstable_clusters={len(hist.unstable)}≥{unstable_threshold}")
            score -= 0.30

    if hist.total_receipts > 0:
        unresolved_share = hist.unresolved_count / hist.total_receipts
        if unresolved_share > unresolved_share_threshold:
            reasons.append(f"unresolved_share={unresolved_share:.2f}>{unresolved_share_threshold}")
            score -= 0.25

    if len(hist.recurring) >= recurring_threshold:
        reasons.append(f"recurring_clusters={len(hist.recurring)}≥{recurring_threshold}")
        score -= 0.15

    score = max(0.0, min(1.0, score))

    if score >= 0.80:
        auth = Authority.FULL
    elif score >= 0.55:
        auth = Authority.REDUCED
    elif score >= 0.30:
        auth = Authority.SUSPENDED
    else:
        auth = Authority.QUARANTINE

    return StabilityReport(
        overall_score=score,
        recommended_authority=auth,
        reasons=tuple(reasons),
        recurring_clusters=len(hist.recurring),
        unstable_clusters=len(hist.unstable),
        applied=hist.applied_count,
        unresolved=hist.unresolved_count,
        total_receipts=hist.total_receipts,
        window_seconds=hist.window_seconds,
    )
