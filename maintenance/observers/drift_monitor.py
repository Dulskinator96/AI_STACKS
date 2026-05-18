"""DriftMonitor — rolling repair-frequency + confidence trend.

Reads the receipts JSONL log (telemetry/maintenance_receipts.jsonl) and
computes two signals over a rolling window:

    repair_rate           — repairs per minute
    failed_validation_pct — share of receipts with FAILED / UNRESOLVED validation

If either crosses its threshold, DriftMonitor:
    1. emits a LAW_4 warning through the Constitution (best-effort)
    2. calls RepairCoordinator.restrict(reason) — collapses T1/T2 to DRY_RUN
    3. emits a T3 Issue describing the drift (validation-only, no auto-repair)

When signals return below threshold for cooldown_ticks consecutive scans,
DriftMonitor calls RepairCoordinator.restore().

DriftMonitor itself is read-only with one explicit exception: it holds
authority over coordinator restriction state, per the directive's
"RepairCoordinator authority auto-reduces under instability conditions."
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import List

from maintenance.classifier import Issue, Tier, Severity, make_issue_id
from maintenance.observers.base import ReadOnlyObserver
from maintenance.receipts import (
    RECEIPT_LOG,
    OUTCOME_APPLIED, OUTCOME_UNRESOLVED,
    VALIDATION_FAILED, VALIDATION_UNRESOLVED,
)

_log = logging.getLogger(__name__)


class DriftMonitor(ReadOnlyObserver):
    name = "DriftMonitor"
    cadence_seconds = 30.0

    def __init__(self, coordinator,
                 *, window_seconds: float = 300.0,
                 repair_rate_per_min_threshold: float = 6.0,
                 failed_pct_threshold: float = 0.50,
                 cooldown_ticks: int = 3):
        self._coordinator = coordinator
        self._window_s = float(window_seconds)
        self._rate_threshold = float(repair_rate_per_min_threshold)
        self._failed_pct_threshold = float(failed_pct_threshold)
        self._cooldown_required = int(cooldown_ticks)
        self._cooldown_count = 0

    # ── receipt log scan ───────────────────────────────────────────────────

    def _recent_receipts(self) -> list[dict]:
        if not RECEIPT_LOG.is_file():
            return []
        cutoff = time.time() - self._window_s
        out: list[dict] = []
        try:
            with RECEIPT_LOG.open("r", encoding="utf-8") as fh:
                for ln in fh:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        obj = json.loads(ln)
                    except Exception:
                        continue
                    if float(obj.get("timestamp", 0.0)) >= cutoff:
                        out.append(obj)
        except Exception as e:
            _log.warning("DriftMonitor receipt scan failed: %s", e)
            return []
        return out

    # ── observer contract ──────────────────────────────────────────────────

    def scan(self) -> List[Issue]:
        receipts = self._recent_receipts()
        if not receipts:
            return self._maybe_restore()

        applied = sum(1 for r in receipts if r.get("outcome") == OUTCOME_APPLIED)
        unresolved = sum(1 for r in receipts if r.get("outcome") == OUTCOME_UNRESOLVED)
        failed_validation = sum(
            1 for r in receipts
            if r.get("validation_status") in (VALIDATION_FAILED, VALIDATION_UNRESOLVED)
        )
        total = len(receipts)
        rate_per_min = (applied + unresolved) / max(self._window_s / 60.0, 1.0)
        failed_pct = (failed_validation / total) if total else 0.0

        drift_triggered = False
        reasons = []
        if rate_per_min > self._rate_threshold:
            drift_triggered = True
            reasons.append(f"repair_rate_{rate_per_min:.2f}_per_min>{self._rate_threshold}")
        if failed_pct > self._failed_pct_threshold:
            drift_triggered = True
            reasons.append(f"failed_pct_{failed_pct:.2f}>{self._failed_pct_threshold}")

        if drift_triggered:
            self._cooldown_count = 0
            reason = "; ".join(reasons)
            self._emit_law4(reason, rate_per_min, failed_pct, total)
            try:
                if not self._coordinator.restricted:
                    self._coordinator.restrict(reason)
            except Exception as e:
                _log.warning("drift restrict call failed: %s", e)

            iid = make_issue_id(self.name, "drift_detected",
                                 "maintenance", salt=str(int(time.time() // 60)))
            return [Issue(
                issue_id=iid,
                observer=self.name,
                kind="drift_detected",
                tier=Tier.T3,
                severity=Severity.HIGH,
                surface="maintenance_runtime",
                evidence={
                    "rate_per_min":        rate_per_min,
                    "failed_pct":          failed_pct,
                    "window_seconds":      self._window_s,
                    "total_receipts_seen": total,
                    "reasons":             reasons,
                },
                repair_hint=None,
                confidence=0.95,
            )]

        return self._maybe_restore()

    def _maybe_restore(self) -> List[Issue]:
        if not self._coordinator.restricted:
            self._cooldown_count = 0
            return []
        self._cooldown_count += 1
        if self._cooldown_count >= self._cooldown_required:
            try:
                self._coordinator.restore()
            except Exception as e:
                _log.warning("drift restore call failed: %s", e)
            self._cooldown_count = 0
        return []

    def _emit_law4(self, reason: str, rate: float, failed_pct: float, total: int) -> None:
        try:
            import sys
            substrate = Path(__file__).resolve().parent.parent.parent.parent
            if str(substrate) not in sys.path:
                sys.path.append(str(substrate))
            from kernel.constitution import get_constitution
            con = get_constitution()
            con.assert_validated(
                "maintenance", self.name, "drift_check",
                assumption=f"repair_rate≤{self._rate_threshold}/min & failed≤{self._failed_pct_threshold}",
                validation=None,   # signals LAW_4 unvalidated → warning
            )
            con.register_calibration_signal(
                "maintenance", "drift_repair_rate_per_min", rate,
                baseline_ref="maintenance_drift_v1",
            )
            con.register_calibration_signal(
                "maintenance", "drift_failed_pct", failed_pct,
                baseline_ref="maintenance_drift_v1",
            )
            _log.warning("LAW_4 drift warning emitted: %s (n=%d)", reason, total)
        except Exception as e:
            _log.debug("LAW_4 emit unavailable: %s", e)
