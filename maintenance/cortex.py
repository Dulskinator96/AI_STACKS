"""maintenance/cortex.py — centralized Maintenance Cortex.

Single source of authority for the maintenance layer. Wraps:

    * RepairCoordinator   (sole mutator, allow-list gated)
    * MaintenanceRuntime  (single-thread observer ticker)
    * StabilityEngine     (pure evaluator)
    * RepairHistory       (rolling fault signature analysis)
    * observers           (read-only signal emitters)

Constitutional posture (per AI_STACK Constitutional Self Optimization Directive):

    centralized — NOT a decentralized swarm
    bounded     — operates above Operational/Intelligence tiers; subordinate
                  to constitutional substrate / dispatch arbitration / failsafe
    coherent    — stability > coherence > efficiency > adaptation
    auditable   — every action emits a Receipt; unresolved stays unresolved

Public surface:

    cortex = MaintenanceCortex.build_default()
    cortex.start()
    cortex.tick_once()
    cortex.stop()
    cortex.stability()  -> StabilityReport
    cortex.recurring_fault(issue) -> bool
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, List, Optional

from maintenance.classifier import Issue
from maintenance.repair_coordinator import RepairCoordinator, RepairOutcome
from maintenance.runtime import MaintenanceRuntime
from maintenance.observers.base import ReadOnlyObserver
from maintenance.observers import (
    RuntimeHealthAgent, UIStateAgent, QueueWatchAgent, DriftMonitor,
    StratumHealthAgent, WONHealthAgent,
    ExecutionIntegrityAgent, ProcessWatchAgent, ResourcePressureAgent,
    MemoryIntegrityAgent, TelemetryMonitorAgent,
)
from maintenance.stability_engine import (
    StabilityReport, Authority, evaluate as evaluate_stability,
)
from maintenance import repair_history

_log = logging.getLogger(__name__)


@dataclass
class CortexConfig:
    tick_seconds:                float = 5.0
    history_window_seconds:      float = 900.0
    recursive_threshold:         int = 5
    auto_adjust_authority:       bool = True


class MaintenanceCortex:
    """Central authority. There is exactly one per ai-monitor process."""

    def __init__(self,
                 coordinator: RepairCoordinator,
                 observers: Iterable[ReadOnlyObserver],
                 *, config: Optional[CortexConfig] = None):
        self._cfg = config or CortexConfig()
        self._coordinator = coordinator
        self._observers: List[ReadOnlyObserver] = list(observers)
        self._runtime = MaintenanceRuntime(
            self._coordinator, self._observers,
            tick_seconds=self._cfg.tick_seconds,
        )

    # ── factory ────────────────────────────────────────────────────────────

    @classmethod
    def build_default(cls, *, ui_state_agent: Optional[UIStateAgent] = None,
                       config: Optional[CortexConfig] = None) -> "MaintenanceCortex":
        coord = RepairCoordinator()
        ui = ui_state_agent or UIStateAgent()
        observers = [
            RuntimeHealthAgent(),
            ui,
            QueueWatchAgent(),
            StratumHealthAgent(),
            WONHealthAgent(),
            ExecutionIntegrityAgent(),
            ProcessWatchAgent(),
            ResourcePressureAgent(),
            MemoryIntegrityAgent(),
            TelemetryMonitorAgent(),
            DriftMonitor(coord),     # drift monitor LAST — observes the rest
        ]
        return cls(coord, observers, config=config)

    # ── lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        self._runtime.start()
        _log.info("MaintenanceCortex started")

    def stop(self) -> None:
        self._runtime.stop()
        _log.info("MaintenanceCortex stopped")

    def pause(self) -> None:
        self._runtime.pause()

    def resume(self) -> None:
        self._runtime.resume()

    def tick_once(self) -> List[RepairOutcome]:
        outcomes = self._runtime.tick_once()
        if self._cfg.auto_adjust_authority:
            self._apply_stability_adjustment()
        return outcomes

    # ── reads ──────────────────────────────────────────────────────────────

    @property
    def coordinator(self) -> RepairCoordinator: return self._coordinator
    @property
    def runtime(self) -> MaintenanceRuntime:    return self._runtime
    @property
    def observers(self) -> List[ReadOnlyObserver]: return list(self._observers)
    @property
    def restricted(self) -> bool:               return self._coordinator.restricted

    def stability(self) -> StabilityReport:
        return evaluate_stability(window_seconds=self._cfg.history_window_seconds)

    def recurring_fault(self, issue: Issue) -> bool:
        return repair_history.is_recursive(
            issue,
            window_seconds=self._cfg.history_window_seconds,
            threshold=self._cfg.recursive_threshold,
        )

    # ── authority adjustment based on StabilityReport ──────────────────────

    def _apply_stability_adjustment(self) -> None:
        try:
            report = self.stability()
        except Exception as e:
            _log.debug("stability eval failed: %s", e)
            return
        rec = report.recommended_authority
        if rec in (Authority.SUSPENDED, Authority.QUARANTINE):
            if not self._coordinator.restricted:
                self._coordinator.restrict(
                    reason=f"cortex_stability_{rec.value}:{';'.join(report.reasons)}"
                )
        elif rec == Authority.FULL:
            if self._coordinator.restricted:
                # DriftMonitor's cooldown will handle restore. We don't force
                # it here to avoid two authorities racing.
                pass
        # REDUCED is informational — coordinator still allowed, but the cortex
        # log records the recommendation. (Tier downgrade per-profile is a
        # future feature; not implemented in v1 to avoid uncontrolled mutation.)


def submit_external_issue(cortex: MaintenanceCortex, issue: Issue) -> RepairOutcome:
    """Route an externally-detected issue through the cortex's coordinator.

    Includes the recursive-fault guard: if this signature has hit threshold
    in the rolling window, the coordinator is asked NOT to apply (escalate).
    """
    if cortex.recurring_fault(issue):
        # Recurrent — force a non-applicable hint so the coordinator records
        # an UNRESOLVED rather than retrying a known-failing repair path.
        issue = Issue(
            issue_id=issue.issue_id, observer=issue.observer, kind=issue.kind,
            tier=issue.tier, severity=issue.severity, surface=issue.surface,
            evidence={**issue.evidence, "recursive_suppression": True},
            repair_hint=None, confidence=issue.confidence,
            subsystem=issue.subsystem,
        )
    return cortex.coordinator.handle(issue)
