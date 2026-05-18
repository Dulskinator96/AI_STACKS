"""Per-subsystem calibration profiles.

Different subsystems demand different repair postures:

    config       — read-only / advisory; never auto-repair (T3 only)
    stratum      — self-healing pipeline; bounded auto-repair on retry-safe
    won          — chaperone; bounded auto-repair on stale cache + retry
    ui           — cosmetic; aggressive auto-repair OK
    workers      — operational; bounded queue cleanup
    agents       — cognitive; never auto-repair, escalate only (T4 default)

A CalibrationProfile narrows (never widens) the RepairCoordinator's posture.
It can:
    * raise the confidence floor for this subsystem
    * restrict the allow-list to a subset
    * downgrade auto-applicable tiers to validate-only

It can NEVER:
    * lower the confidence floor below DEFAULT_CONFIDENCE_FLOOR
    * add hints that aren't in REPAIR_ALLOW_LIST
    * upgrade T3/T4 to auto-apply
    * skip rollback / validation requirements

This file is additive: if no profile is registered for an Issue's subsystem,
the default coordinator behavior applies (DEFAULT_CONFIDENCE_FLOOR + full
REPAIR_ALLOW_LIST). Existing code paths are unchanged.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import FrozenSet, Optional

from maintenance.classifier import Tier, REPAIR_ALLOW_LIST
from maintenance.repair_coordinator import DEFAULT_CONFIDENCE_FLOOR


@dataclass(frozen=True)
class CalibrationProfile:
    """Narrowing-only profile for a subsystem.

    Hard invariants enforced at construction:
        * confidence_floor >= DEFAULT_CONFIDENCE_FLOOR
        * allowed_hints  ⊆ REPAIR_ALLOW_LIST
        * auto_apply_tiers ⊆ {T1, T2}
    """
    subsystem:           str
    confidence_floor:    float = DEFAULT_CONFIDENCE_FLOOR
    allowed_hints:       FrozenSet[str] = field(default_factory=lambda: frozenset(REPAIR_ALLOW_LIST))
    auto_apply_tiers:    FrozenSet[Tier] = field(default_factory=lambda: frozenset({Tier.T1, Tier.T2}))
    notes:               str = ""

    def __post_init__(self):
        if self.confidence_floor < DEFAULT_CONFIDENCE_FLOOR:
            raise ValueError(
                f"profile {self.subsystem!r} cannot lower floor below "
                f"DEFAULT_CONFIDENCE_FLOOR={DEFAULT_CONFIDENCE_FLOOR}"
            )
        bad_hints = set(self.allowed_hints) - set(REPAIR_ALLOW_LIST)
        if bad_hints:
            raise ValueError(
                f"profile {self.subsystem!r} contains hints not in "
                f"REPAIR_ALLOW_LIST: {sorted(bad_hints)}"
            )
        bad_tiers = set(self.auto_apply_tiers) - {Tier.T1, Tier.T2}
        if bad_tiers:
            raise ValueError(
                f"profile {self.subsystem!r} cannot promote tiers to auto-apply: "
                f"{sorted(t.value for t in bad_tiers)}"
            )

    def allows(self, *, hint: Optional[str], tier: Tier, confidence: float) -> bool:
        if confidence < self.confidence_floor:
            return False
        if tier not in self.auto_apply_tiers:
            return False
        if not hint or hint not in self.allowed_hints:
            return False
        return True


# ── Default subsystem profiles (narrowing only) ────────────────────────────

DEFAULT_PROFILES: dict[str, CalibrationProfile] = {
    "config":  CalibrationProfile(
        subsystem="config",
        confidence_floor=0.99,
        allowed_hints=frozenset(),     # config is advisory only
        auto_apply_tiers=frozenset(),  # never auto-apply
        notes="config.py is single source of truth — no auto-repair",
    ),
    "stratum": CalibrationProfile(
        subsystem="stratum",
        confidence_floor=0.80,
        allowed_hints=frozenset({
            "retry_safe_operation",
            "stale_cache_invalidation",
            "event_rebinding",
        }),
        auto_apply_tiers=frozenset({Tier.T2}),
        notes="STRATUM self-healing pipeline — bounded retry/cache only",
    ),
    "won":     CalibrationProfile(
        subsystem="won",
        confidence_floor=0.75,
        allowed_hints=frozenset({
            "retry_safe_operation",
            "stale_cache_invalidation",
            "non_destructive_sync",
        }),
        auto_apply_tiers=frozenset({Tier.T2}),
        notes="WON chaperone — bounded retry/sync only",
    ),
    "ui":      CalibrationProfile(
        subsystem="ui",
        confidence_floor=DEFAULT_CONFIDENCE_FLOOR,
        allowed_hints=frozenset({
            "ui_state_resync",
            "ui_widget_refresh",
            "deterministic_format",
        }),
        auto_apply_tiers=frozenset({Tier.T1}),
        notes="UI cosmetic repair — T1 only",
    ),
    "workers": CalibrationProfile(
        subsystem="workers",
        confidence_floor=0.75,
        allowed_hints=frozenset({
            "queue_cleanup",
            "temporary_process_restart",
        }),
        auto_apply_tiers=frozenset({Tier.T2}),
        notes="Worker pool — bounded cleanup/restart only",
    ),
    "agents":  CalibrationProfile(
        subsystem="agents",
        confidence_floor=0.99,
        allowed_hints=frozenset(),
        auto_apply_tiers=frozenset(),
        notes="Cognitive agents — no auto-repair, escalate only",
    ),
}


# ── Thread-safe registry ───────────────────────────────────────────────────

_registry_lock = threading.RLock()
_profiles: dict[str, CalibrationProfile] = dict(DEFAULT_PROFILES)


def register_profile(profile: CalibrationProfile) -> None:
    with _registry_lock:
        _profiles[profile.subsystem] = profile


def get_profile(subsystem: str) -> Optional[CalibrationProfile]:
    with _registry_lock:
        return _profiles.get(subsystem)


def all_profiles() -> dict[str, CalibrationProfile]:
    with _registry_lock:
        return dict(_profiles)
