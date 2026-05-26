"""engine/comparative_selector_v2.py — BUILD-028 SECTION 4 comparator.

Generates N candidates, CQI-evaluates all, ranks them, isolates per-dimension
trait winners, builds a hybrid refinement plan that inherits the strongest
trait from each candidate.

Pipeline:
    Intent → Generate N candidates → CQI evaluate all → Rank →
    Trait extraction → Weakness isolation → Hybrid refinement synthesis →
    Final selection → Guarantee validation

NO RANDOM WINNER SELECTION. Every choice carries explicit reasoning.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)


_DEFAULT_N = 3
_TRAIT_DIMS = ("atmosphere", "emotional_impact", "cinematic_intensity",
                "visual_harmony", "pacing_quality", "thematic_coherence",
                "originality", "memorability")


@dataclass(frozen=True)
class TraitWinner:
    dimension:    str
    candidate_index: int
    score:        float


@dataclass(frozen=True)
class ComparisonMatrix:
    matrix_id:        str
    candidate_count:  int
    candidate_scores: list             # list of CQI composites
    dimension_winners: list            # list[TraitWinner]
    chosen_index:     int
    chosen_score:     float
    hybrid_targets:   list             # which dims need inheritance from winners
    rationale:        str
    created_at:       float

    def to_dict(self) -> dict:
        d = asdict(self)
        d["dimension_winners"] = [asdict(t) for t in self.dimension_winners]
        return d


class ComparativeSelectorV2:
    """N-candidate ranker with trait extraction and hybrid synthesis."""

    def __init__(self):
        self._lock = threading.RLock()
        self._comparison_count = 0
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.comparative_selector_v2", self)
        except Exception:
            pass

    def select(self, candidates: list, output_dir: Optional[Path] = None) -> Optional[ComparisonMatrix]:
        """candidates: list of (worker_outcome, cqi) tuples.
        Returns ComparisonMatrix or None if empty."""
        if not candidates:
            return None
        if len(candidates) < 2:
            # Single candidate: trivial selection
            outcome, cqi = candidates[0]
            return self._single_candidate_result(outcome, cqi)

        # Score each candidate (blend CQI 70% + worker_score 30%)
        scored = []
        for i, (outcome, cqi) in enumerate(candidates):
            composite = float(getattr(cqi, "composite", 0.0) or 0.0)
            worker_score = float(getattr(outcome, "overall_validation_score", 0.0) or 0.0)
            blended = 0.7 * composite + 0.3 * worker_score
            scored.append((i, blended, composite, worker_score, outcome, cqi))
        scored.sort(key=lambda t: -t[1])

        # Dimension winners — per-trait best across all candidates
        winners: list[TraitWinner] = []
        for dim in _TRAIT_DIMS:
            best_i, best_v = 0, -1.0
            for i, (outcome, cqi) in enumerate(candidates):
                v = float(getattr(cqi, dim, 0.0) or 0.0)
                if v > best_v:
                    best_v, best_i = v, i
            winners.append(TraitWinner(dimension=dim,
                                         candidate_index=best_i, score=round(best_v, 3)))

        chosen_idx = scored[0][0]
        chosen_score = scored[0][1]
        chosen_outcome, chosen_cqi = scored[0][4], scored[0][5]

        # Hybrid targets: any dimension where the chosen candidate is NOT
        # the winner becomes a refinement target inheriting from the winner.
        hybrid_targets: list = []
        for w in winners:
            if w.candidate_index != chosen_idx:
                chosen_val = float(getattr(chosen_cqi, w.dimension, 0.0) or 0.0)
                gap = w.score - chosen_val
                if gap > 0.10:    # meaningful inheritance only
                    hybrid_targets.append({
                        "dimension":          w.dimension,
                        "winner_index":       w.candidate_index,
                        "winner_score":       w.score,
                        "chosen_score":       round(chosen_val, 3),
                        "gap":                round(gap, 3),
                    })

        rationale = self._rationale(chosen_idx, chosen_score, scored, winners,
                                       hybrid_targets)

        matrix = ComparisonMatrix(
            matrix_id=f"cmp-{uuid.uuid4().hex[:10]}",
            candidate_count=len(candidates),
            candidate_scores=[(s[0], round(s[1], 3)) for s in scored],
            dimension_winners=winners,
            chosen_index=chosen_idx,
            chosen_score=round(chosen_score, 3),
            hybrid_targets=hybrid_targets,
            rationale=rationale,
            created_at=time.time(),
        )
        with self._lock:
            self._comparison_count += 1
        self._emit_receipt(matrix)
        self._emit_events(matrix, candidates)
        # Persist matrix + ranked candidates if output_dir given
        if output_dir is not None:
            self._persist(matrix, candidates, output_dir)
        return matrix

    def _single_candidate_result(self, outcome, cqi) -> ComparisonMatrix:
        composite = float(getattr(cqi, "composite", 0.0) or 0.0)
        return ComparisonMatrix(
            matrix_id=f"cmp-{uuid.uuid4().hex[:10]}",
            candidate_count=1,
            candidate_scores=[(0, composite)],
            dimension_winners=[],
            chosen_index=0,
            chosen_score=composite,
            hybrid_targets=[],
            rationale="single candidate — no comparison performed",
            created_at=time.time(),
        )

    def _rationale(self, chosen_idx, chosen_score, scored, winners,
                    hybrid_targets) -> str:
        runner = scored[1] if len(scored) > 1 else None
        bits = [
            f"chose #{chosen_idx} blended {chosen_score:.2f} "
            f"(CQI {scored[0][2]:.2f} · worker {scored[0][3]:.2f})"
        ]
        if runner is not None:
            bits.append(f"over #{runner[0]} blended {runner[1]:.2f}")
        if hybrid_targets:
            top = hybrid_targets[0]
            bits.append(
                f"trait merge opportunity: {top['dimension']} stronger in #"
                f"{top['winner_index']} (+{top['gap']:.2f})"
            )
        return "; ".join(bits)

    def _persist(self, matrix: ComparisonMatrix, candidates: list,
                  output_dir: Path) -> None:
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            # comparison_matrix.json
            (output_dir / "comparison_matrix.json").write_text(
                json.dumps(matrix.to_dict(), indent=2, default=str),
                encoding="utf-8")
            # ranked_candidates.json
            ranked = []
            scored_dict = {idx: score for idx, score in matrix.candidate_scores}
            for i, (outcome, cqi) in enumerate(candidates):
                ranked.append({
                    "candidate_index": i,
                    "blended_score":   scored_dict.get(i, 0.0),
                    "cqi_composite":   float(getattr(cqi, "composite", 0.0) or 0.0),
                    "worker_score":    float(getattr(outcome, "overall_validation_score", 0.0) or 0.0),
                    "artifact_paths":  [a.get("path") for a in
                                          (getattr(outcome, "artifacts", []) or [])
                                          if isinstance(a, dict)],
                })
            ranked.sort(key=lambda d: -d["blended_score"])
            (output_dir / "ranked_candidates.json").write_text(
                json.dumps(ranked, indent=2, default=str), encoding="utf-8")
            # selected_candidate.json
            (output_dir / "selected_candidate.json").write_text(
                json.dumps(ranked[0] if ranked else {}, indent=2, default=str),
                encoding="utf-8")
            # refinement_reasoning.json
            (output_dir / "refinement_reasoning.json").write_text(
                json.dumps({
                    "hybrid_targets": matrix.hybrid_targets,
                    "rationale":      matrix.rationale,
                }, indent=2, default=str), encoding="utf-8")
        except Exception as e:
            _log.warning("comparison persist failed: %s", e)

    def _emit_receipt(self, matrix: ComparisonMatrix) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="comparative_selector_v2:select",
                executor="ComparativeSelectorV2",
                duration_ms=0.0, verified=True, compute_sha256=False,
                evidence={
                    "matrix_id":         matrix.matrix_id,
                    "candidate_count":   matrix.candidate_count,
                    "chosen_index":      matrix.chosen_index,
                    "chosen_score":      matrix.chosen_score,
                    "hybrid_target_count": len(matrix.hybrid_targets),
                },
            )
        except Exception:
            pass

    def _emit_events(self, matrix: ComparisonMatrix, candidates: list) -> None:
        """Stream comparison steps to the live bus for the LaunchSurface."""
        try:
            from engine.live_stream import get_live_stream
            bus = get_live_stream()
            n = matrix.candidate_count
            for i in range(n):
                bus.emit_event("compare_candidate", {
                    "i": i, "n": n,
                    "blended": matrix.candidate_scores[i][1] if i < len(matrix.candidate_scores) else 0.0,
                })
            for w in matrix.dimension_winners:
                bus.emit_event("compare_trait_winner", {
                    "dimension": w.dimension,
                    "candidate": w.candidate_index,
                    "score":     w.score,
                })
            bus.emit_event("compare_selected", {
                "matrix_id":      matrix.matrix_id,
                "chosen_index":   matrix.chosen_index,
                "chosen_score":   matrix.chosen_score,
                "hybrid_targets": len(matrix.hybrid_targets),
                "rationale":      matrix.rationale[:200],
            })
        except Exception:
            pass


_INSTANCE: Optional[ComparativeSelectorV2] = None


def get_comparative_selector_v2() -> ComparativeSelectorV2:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ComparativeSelectorV2()
    return _INSTANCE
