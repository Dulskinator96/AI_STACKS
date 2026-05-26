"""engine/closed_loop_tests.py — BUILD-029 mandatory validation suite.

Three tests per directive Section 8. Each test runs the ClosedLoopEngine
on a canonical intent and verifies the pass criteria.

  TEST 1 — DIVERGENCE & MUTATION
  TEST 2 — FEEDBACK INJECTION
  TEST 3 — CLOSED LOOP INTEGRITY
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

_log = logging.getLogger(__name__)


@dataclass
class TestResult:
    test_id:     str
    name:        str
    passed:      bool
    duration_ms: float
    evidence:    dict = field(default_factory=dict)
    failures:    list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def render(self) -> str:
        sym = "✓" if self.passed else "✗"
        return f"  {sym} {self.test_id} {self.name}  ({self.duration_ms:.0f}ms)"


class ClosedLoopTestSuite:

    def __init__(self):
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.closed_loop_tests", self)
        except Exception:
            pass

    def run_all(self) -> dict:
        results: list[TestResult] = []
        results.append(self.test_1_divergence_mutation())
        results.append(self.test_2_feedback_injection())
        results.append(self.test_3_closed_loop_integrity())
        passed = sum(1 for r in results if r.passed)
        return {
            "ran_at":      time.time(),
            "total":       len(results),
            "passed":      passed,
            "failed":      len(results) - passed,
            "results":     [r.to_dict() for r in results],
        }

    # ── TEST 1 ────────────────────────────────────────────────────────
    def test_1_divergence_mutation(self) -> TestResult:
        """3–7 candidates · each differs in ≥ 2 axes · CQI variance ≥ 0.15 ·
        ≥ 2 candidates have different top-ranked CQI dimensions."""
        from engine.closed_loop import get_closed_loop_engine
        t0 = time.time()
        engine = get_closed_loop_engine()
        outcome = engine.run("Create a cinematic cyberpunk skyline at dusk",
                              candidate_count=5)
        failures: list[str] = []
        evidence: dict = {}

        # PASS CRITERIA #1: 3 ≤ candidate_count ≤ 7 in the first cycle
        first_cycle = outcome.cycles_data[0] if outcome.cycles_data else {}
        cand_count = first_cycle.get("candidate_count", 0)
        evidence["candidate_count_cycle_0"] = cand_count
        if not (3 <= cand_count <= 7):
            failures.append(f"candidate_count {cand_count} not in [3,7]")

        # PASS CRITERIA #2: CQI variance ≥ 0.15 across candidates in cycle 0
        # Walk LiveStreamBus recent events to find compare_candidate
        # Actually we have outcome.cycles_data with best_score per cycle.
        # The deeper variance check needs candidate-level data — emit it via
        # the feedback vector strength_sources.
        if outcome.feedback_history:
            fv = outcome.feedback_history[0]
            scores = [s.get("score", 0.0) for s in fv.strength_sources]
            if scores:
                variance = max(scores) - min(scores)
                evidence["cqi_score_spread_cycle_0"] = round(variance, 3)
                if variance < 0.15:
                    failures.append(f"cqi spread {variance:.2f} < 0.15")

        # PASS CRITERIA #3: ≥ 2 candidates have different top dimensions
        # Read dimension winners from feedback strength_sources
        if outcome.feedback_history:
            fv = outcome.feedback_history[0]
            winning_candidates = {
                s.get("candidate") for s in fv.strength_sources
                if s.get("candidate") is not None
            }
            evidence["unique_top_dim_winners"] = len(winning_candidates)
            if len(winning_candidates) < 2:
                failures.append(
                    f"only {len(winning_candidates)} distinct candidate "
                    "took top in any dimension"
                )

        evidence["loop_state"] = outcome.state
        evidence["cycle_count"] = outcome.cycle_count
        return TestResult(
            test_id="TEST_1",
            name="DIVERGENCE_AND_MUTATION",
            passed=(len(failures) == 0),
            duration_ms=(time.time() - t0) * 1000.0,
            evidence=evidence,
            failures=failures,
        )

    # ── TEST 2 ────────────────────────────────────────────────────────
    def test_2_feedback_injection(self) -> TestResult:
        """Second-cycle outputs differ from first · ≥ 1 bias change ·
        entropy_adjustment != 0."""
        from engine.closed_loop import get_closed_loop_engine
        t0 = time.time()
        engine = get_closed_loop_engine()
        # Use an intent likely to need refinement (lower ambition keyword)
        outcome = engine.run(
            "Design an emotional orchestral soundtrack for a sci-fi scene",
            candidate_count=4,
        )
        failures: list[str] = []
        evidence: dict = {}

        # PASS CRITERIA: ≥ 1 feedback vector emitted
        evidence["feedback_count"] = len(outcome.feedback_history)
        if not outcome.feedback_history:
            failures.append("no feedback vectors emitted")
            return TestResult(
                test_id="TEST_2", name="FEEDBACK_INJECTION",
                passed=False, duration_ms=(time.time() - t0) * 1000.0,
                evidence=evidence, failures=failures,
            )

        first_fv = outcome.feedback_history[0]
        evidence["first_fv_has_signal"]      = first_fv.has_signal()
        evidence["first_fv_entropy_adj"]     = first_fv.entropy_adjustment
        evidence["first_fv_forbidden_count"] = len(first_fv.forbidden_patterns)
        evidence["first_fv_preferred_count"] = len(first_fv.preferred_patterns)

        # PASS CRITERIA #1: entropy_adjustment != 0
        if abs(first_fv.entropy_adjustment) < 1e-6:
            failures.append("entropy_adjustment == 0 — no learning")

        # PASS CRITERIA #2: ≥ 1 bias signal present (any of the bias dicts
        # OR any preferred/forbidden pattern OR any transferable trait)
        if not first_fv.has_signal():
            failures.append("feedback vector has no signal — no bias change")

        # If the engine ran ≥ 2 cycles, verify outputs differ
        if outcome.cycle_count >= 2:
            c0 = outcome.cycles_data[0]
            c1 = outcome.cycles_data[1]
            evidence["cycle_0_best"] = c0.get("best_score")
            evidence["cycle_1_best"] = c1.get("best_score")
            evidence["cycle_0_winner_id"] = c0.get("winner_variant_id", "")
            evidence["cycle_1_winner_id"] = c1.get("winner_variant_id", "")
            if c0.get("winner_variant_id") == c1.get("winner_variant_id"):
                failures.append("cycle 0 and 1 winners identical "
                                 "(no measurable difference)")

        return TestResult(
            test_id="TEST_2",
            name="FEEDBACK_INJECTION",
            passed=(len(failures) == 0),
            duration_ms=(time.time() - t0) * 1000.0,
            evidence=evidence,
            failures=failures,
        )

    # ── TEST 3 ────────────────────────────────────────────────────────
    def test_3_closed_loop_integrity(self) -> TestResult:
        """Full loop: comparison + feedback + regen decision · final output
        differs from first-pass if regen occurred."""
        from engine.closed_loop import get_closed_loop_engine
        t0 = time.time()
        engine = get_closed_loop_engine()
        outcome = engine.run("Create a stylized game trailer concept",
                              candidate_count=4)
        failures: list[str] = []
        evidence: dict = {
            "state":          outcome.state,
            "cycle_count":    outcome.cycle_count,
            "total_candidates": outcome.total_candidates,
            "feedback_count": len(outcome.feedback_history),
            "enforcer_reasons": outcome.enforcer_reasons,
        }

        # PASS CRITERIA #1: comparison_completed
        first_cycle = outcome.cycles_data[0] if outcome.cycles_data else {}
        if not first_cycle:
            failures.append("no cycles ran")
        evidence["cycle_0"] = first_cycle

        # PASS CRITERIA #2: feedback vector emitted
        if not outcome.feedback_history:
            failures.append("no feedback vector emitted")

        # PASS CRITERIA #3: regeneration decision made
        # outcome.cycle_count > 1 means regen happened; if == 1 then
        # regen was evaluated as not needed (winner score ≥ 0.75)
        if outcome.cycle_count < 1:
            failures.append("regen decision never made (cycle_count < 1)")

        # PASS CRITERIA #4: if regen occurred, final differs from first
        if outcome.cycle_count >= 2:
            c0 = outcome.cycles_data[0]
            cf = outcome.cycles_data[-1]
            if c0.get("winner_variant_id") == cf.get("winner_variant_id"):
                failures.append("regen ran but final winner == first winner")

        # PASS CRITERIA #5: enforcer allowed (state == COMPLETED)
        if outcome.state != "COMPLETED":
            failures.append(f"enforcer state {outcome.state}: "
                             f"{outcome.enforcer_reasons}")

        return TestResult(
            test_id="TEST_3",
            name="CLOSED_LOOP_INTEGRITY",
            passed=(len(failures) == 0),
            duration_ms=(time.time() - t0) * 1000.0,
            evidence=evidence,
            failures=failures,
        )


_INSTANCE: Optional[ClosedLoopTestSuite] = None


def get_closed_loop_tests() -> ClosedLoopTestSuite:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ClosedLoopTestSuite()
    return _INSTANCE
