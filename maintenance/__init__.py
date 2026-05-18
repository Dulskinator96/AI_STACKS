"""maintenance/ — bounded autonomous stability & repair layer (v1).

Architecture posture (per AUTONOMOUS STABILITY & REPAIR DIRECTIVE 2026-05-17):

  Immune system, NOT unrestricted self-modifying intelligence.
  Observers READ-ONLY. RepairCoordinator is the SOLE bounded mutator.

Pipeline:
  detect → classify → simulate → validate → apply → verify

Authority gates:
  T1 (cosmetic/UI)        → auto-apply allowed
  T2 (operational degrad) → bounded patch allowed (allow-list only)
  T3 (logic inconsistency) → validation only; no auto-apply
  T4 (substrate risk)      → escalation only; no auto-apply, no validation simulation

All actions emit LAW_3 receipts. Drift triggers LAW_4 warning + authority
auto-reduction. Unresolved states REMAIN unresolved (no fabrication).
"""
from maintenance.classifier import Tier, Severity, Issue, REPAIR_ALLOW_LIST
from maintenance.receipts import Receipt, build_receipt, emit_receipt
from maintenance.repair_coordinator import RepairCoordinator, RepairOutcome
from maintenance.runtime import MaintenanceRuntime
from maintenance.calibration import (
    CalibrationProfile, register_profile, get_profile, all_profiles,
    DEFAULT_PROFILES,
)
from maintenance.stability_engine import (
    StabilityReport, Authority, evaluate as evaluate_stability,
)
from maintenance.repair_history import (
    FaultCluster, HistoryReport, analyze as analyze_history, is_recursive,
)
from maintenance.cortex import MaintenanceCortex, CortexConfig, submit_external_issue

__all__ = [
    "Tier", "Severity", "Issue", "REPAIR_ALLOW_LIST",
    "Receipt", "build_receipt", "emit_receipt",
    "RepairCoordinator", "RepairOutcome",
    "MaintenanceRuntime",
    "CalibrationProfile", "register_profile", "get_profile", "all_profiles",
    "DEFAULT_PROFILES",
    "StabilityReport", "Authority", "evaluate_stability",
    "FaultCluster", "HistoryReport", "analyze_history", "is_recursive",
    "MaintenanceCortex", "CortexConfig", "submit_external_issue",
]
