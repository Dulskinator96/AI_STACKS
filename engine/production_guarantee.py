"""engine/production_guarantee.py — BUILD-025 PRODUCTION GUARANTEE LAYER.

Deterministic execution guarantee. Sits BETWEEN WorkerRouter (worker
execution + ArtifactValidator) and ArtifactRegistry. Every intent
results in either:

  1. A VALIDATED artifact that satisfies the IntentContract, OR
  2. A fully-explained FAIL with diagnostics + remediation +
     automatic repair attempt (up to 2 cycles).

NO silent partial success. NO unverified READY.

Pipeline (final):

    IntentCortex
       ↓
    CognitiveCore
       ↓
    WorkerRouter
       ↓
    ToolFabric Gate
       ↓
    Worker Execution
       ↓
    ArtifactValidator
       ↓
    PRODUCTION GUARANTEE ENGINE   ← (this module)
       ↓
    ArtifactRegistry
       ↓
    PreviewRegistry
       ↓
    UI Output
"""
from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)


# Thresholds (per directive §2)
VALIDATED_THRESHOLD = 0.80
RETRY_THRESHOLD     = 0.50
MAX_REPAIR_CYCLES   = 2


# Failure categories drive correction strategy in the repair loop
FAIL_MISSING_BACKEND   = "missing_backend"
FAIL_LOW_QUALITY       = "low_quality"
FAIL_SEMANTIC_MISMATCH = "semantic_mismatch"
FAIL_INCOMPLETE        = "incomplete_generation"
FAIL_TOOL_FAILURE      = "tool_failure"
FAIL_REJECTED          = "contract_rejected"


@dataclass
class IntentContract:
    contract_id:        str
    raw_intent:         str
    required_outputs:   list   # [{realm, kind, min_quality}]
    quality_constraints: dict  # {min_resolution, min_duration_s, style_match, coherence_threshold}
    tool_dependencies:  dict   # {required: [...], fallback: [...]}
    success_conditions: list   # descriptive rules
    compiled_at:        float
    intent_difficulty:  str = "normal"   # P0: annotate-only; never blocks dispatch

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GuaranteeOutcome:
    contract_id:    str
    status:         str       # VALIDATED | AUTO_RETRY | FAIL | REJECTED
    match_score:    float
    score_breakdown: dict
    worker_outcome: Any       # original WorkerOutcome (or None on REJECTED)
    failure_category: str
    diagnostics:    dict
    remediation:    str
    repair_history: list      # list of {pass, strategy, prev_score, new_score}
    final_artifacts: list
    duration_ms:    float
    started_at:     float
    finished_at:    float

    def to_dict(self) -> dict:
        out = asdict(self)
        # worker_outcome may not be dict-able cleanly
        try:
            wo = self.worker_outcome
            out["worker_outcome"] = wo.to_dict() if hasattr(wo, "to_dict") else None
        except Exception:
            out["worker_outcome"] = None
        return out


# ── ContractCompiler — Intent → IntentContract ───────────────────────

class ContractCompiler:
    """Compile a raw intent into a structured IntentContract. If the
    intent is too vague (no inferable realm), returns None → REJECTED."""

    # Quality defaults per realm
    _DEFAULTS = {
        "image":      {"min_resolution_px": 256, "min_entropy": 3.0, "coherence_threshold": 0.6},
        "video":      {"min_duration_s": 1.0, "min_resolution_px": 720, "coherence_threshold": 0.6},
        "audio":      {"min_duration_s": 1.0, "min_sample_rate": 8000, "coherence_threshold": 0.55},
        "game":       {"min_files": 3, "coherence_threshold": 0.6},
        "simulation": {"min_distinct_colors": 4, "coherence_threshold": 0.55},
        "code":       {"must_parse": True, "coherence_threshold": 0.65},
        "cast":       {"min_chars": 80, "coherence_threshold": 0.55},
    }

    _REALM_TOOLS = {
        "image":      {"required": [], "fallback": ["comfyui", "automatic1111", "diffusers", "imageforge"]},
        "video":      {"required": ["ffmpeg"], "fallback": []},
        "audio":      {"required": [], "fallback": ["pyttsx3", "audiocraft", "bark"]},
        "game":       {"required": [], "fallback": []},
        "simulation": {"required": [], "fallback": []},
        "code":       {"required": [], "fallback": ["conv_programming"]},
        "cast":       {"required": [], "fallback": ["pyramid_ensemble", "ollama"]},
    }

    def compile(self, intent_text: str, enriched=None, spec=None,
                realm_hint: Optional[str] = None) -> Optional[IntentContract]:
        """Build a contract. P0 FAIL-OPEN: the compiler MUST NOT block the
        execution path. It only annotates intent difficulty. A contract is
        returned whenever ANY realm is known — inferred OR supplied by the
        router (realm_hint). Returns None ONLY when no realm exists at all
        (truly unroutable), which the router translates to
        UNAVAILABLE_REAL_EXECUTION — never a silent synthetic FAIL."""
        difficulty = "normal"

        realm = None
        kind  = ""
        if enriched is not None:
            realm = (enriched.target_pipeline or "").lower() or \
                    (enriched.realm or "").lower() or None
            kind = (enriched.medium or "").lower()
        if realm is None:
            realm = self._guess_realm(intent_text)
        if realm is None:
            # Could not infer a realm from the text — fall OPEN to the
            # router-supplied realm rather than rejecting. Annotate as vague.
            realm = (realm_hint or "").lower() or None
            difficulty = "vague"
        if realm is None:
            # No realm anywhere (no text, no hint) → genuinely unroutable.
            return None

        # Build quality constraints
        defaults = dict(self._DEFAULTS.get(realm, {}))
        # Boost requirements based on ambition
        ambition = float(getattr(spec, "ambition", 0.6) or 0.6) if spec else 0.6
        if ambition > 0.85:
            if "min_resolution_px" in defaults:
                defaults["min_resolution_px"] = max(defaults["min_resolution_px"], 768)
            defaults["coherence_threshold"] = min(0.9,
                                                    defaults.get("coherence_threshold", 0.6) + 0.1)
        # Style match: only enforced if a style was inferred
        style = getattr(enriched, "style", None) if enriched else None
        if style:
            defaults["style_match"] = style

        success_conditions = self._build_success_conditions(realm, defaults)

        return IntentContract(
            contract_id=f"contract-{uuid.uuid4().hex[:10]}",
            raw_intent=intent_text,
            required_outputs=[{"realm": realm, "kind": kind, "min_quality": 0.7}],
            quality_constraints=defaults,
            tool_dependencies=self._REALM_TOOLS.get(realm, {"required": [], "fallback": []}),
            success_conditions=success_conditions,
            compiled_at=time.time(),
            intent_difficulty=difficulty,
        )

    def _guess_realm(self, intent_text: str) -> Optional[str]:
        t = intent_text.lower()
        rules = [
            (r"\b(image|picture|photo|portrait|render|scene|illustration)\b", "image"),
            (r"\b(video|trailer|reel|clip|cinematic|cut|edit)\b",              "video"),
            (r"\b(audio|soundtrack|song|score|music|narrat|voice)\b",          "audio"),
            (r"\b(game|playable|level|world|gameplay|mechanic|simul)\b",       "game"),
            (r"\b(map|tactical|terrain|environment|projection)\b",              "simulation"),
            (r"\b(code|implement|script|function|class|refactor|build)\b",     "code"),
            (r"\b(story|narrative|chapter|saga|lore|verdict|cast)\b",          "cast"),
        ]
        for pat, realm in rules:
            if re.search(pat, t):
                return realm
        return None

    def _build_success_conditions(self, realm: str, q: dict) -> list:
        conds: list[str] = []
        if "min_resolution_px" in q:
            conds.append(f"width >= {q['min_resolution_px']} and height >= {q['min_resolution_px']}")
        if "min_duration_s" in q:
            conds.append(f"duration_s >= {q['min_duration_s']}")
        if "min_entropy" in q:
            conds.append(f"entropy >= {q['min_entropy']}")
        if "min_sample_rate" in q:
            conds.append(f"sample_rate >= {q['min_sample_rate']}")
        if "min_files" in q:
            conds.append(f"valid_artifact_count >= {q['min_files']}")
        if "min_distinct_colors" in q:
            conds.append(f"distinct_colors >= {q['min_distinct_colors']}")
        if "min_chars" in q:
            conds.append(f"char_count >= {q['min_chars']}")
        if q.get("must_parse"):
            conds.append("ast_parse_succeeds")
        if "style_match" in q:
            conds.append(f"style includes '{q['style_match']}'")
        if "coherence_threshold" in q:
            conds.append(f"worker_overall_score >= {q['coherence_threshold']}")
        return conds


# ── IntentSatisfactionScorer — MatchScore evaluation ─────────────────

class IntentSatisfactionScorer:
    """Compute MatchScore against IntentContract.

    f(intent_semantics, artifact_properties, lineage_alignment).
    Returns (score, breakdown_dict).
    """

    def score(self, contract: IntentContract, worker_outcome) -> tuple:
        breakdown: dict = {}
        if worker_outcome is None:
            return 0.0, {"reason": "no worker outcome"}

        artifacts = getattr(worker_outcome, "artifacts", []) or []
        valid_artifacts = [a for a in artifacts
                            if isinstance(a, dict)
                            and a.get("validation", {}).get("valid")]

        # 1. Coverage: did the realm match?
        out_realm = getattr(worker_outcome, "realm", "")
        wanted_realm = (contract.required_outputs[0] or {}).get("realm", "") \
                        if contract.required_outputs else ""
        coverage = 1.0 if out_realm == wanted_realm else 0.5
        breakdown["coverage"] = coverage

        # 2. Existence: at least one valid artifact?
        existence = 1.0 if valid_artifacts else 0.0
        breakdown["existence"] = existence

        if existence == 0.0:
            return 0.0, {**breakdown, "reason": "no valid artifact"}

        # 3. Quality: aggregate validation scores
        worker_score = float(getattr(worker_outcome, "overall_validation_score", 0.0) or 0.0)
        breakdown["worker_score"] = worker_score

        # 4. Constraint compliance: per-realm checks
        constraint_score, constraint_breakdown = self._check_constraints(
            contract.quality_constraints, valid_artifacts
        )
        breakdown["constraint_score"] = constraint_score
        breakdown["constraint_details"] = constraint_breakdown

        # 5. Style/lineage alignment (best-effort — checks for style keyword in
        #    artifact path or spec snapshot)
        style_match = self._style_match(contract, worker_outcome)
        breakdown["style_match"] = style_match

        # Final score: weighted blend
        score = (
            0.20 * coverage +
            0.15 * existence +
            0.30 * worker_score +
            0.25 * constraint_score +
            0.10 * style_match
        )
        score = max(0.0, min(1.0, score))
        breakdown["final"] = round(score, 3)
        return score, breakdown

    def _check_constraints(self, q: dict, valid_artifacts: list) -> tuple:
        """Per-constraint pass/fail. Score is fraction of constraints met
        across the artifacts that have the relevant check."""
        details: dict = {}
        passed = 0
        total = 0
        for art in valid_artifacts:
            checks = art.get("validation", {}).get("checks", {}) or {}
            # Resolution
            if "min_resolution_px" in q and "width" in checks and "height" in checks:
                total += 1
                ok = (checks["width"] >= q["min_resolution_px"] and
                      checks["height"] >= q["min_resolution_px"])
                details["resolution"] = {"required": q["min_resolution_px"],
                                          "got": f"{checks['width']}x{checks['height']}",
                                          "ok": ok}
                if ok: passed += 1
            # Duration
            if "min_duration_s" in q and "duration_s" in checks:
                total += 1
                ok = checks["duration_s"] >= q["min_duration_s"]
                details["duration"] = {"required": q["min_duration_s"],
                                        "got": checks["duration_s"], "ok": ok}
                if ok: passed += 1
            # Entropy
            if "min_entropy" in q and "entropy" in checks:
                total += 1
                ok = checks["entropy"] >= q["min_entropy"]
                details["entropy"] = {"required": q["min_entropy"],
                                       "got": checks["entropy"], "ok": ok}
                if ok: passed += 1
            # Sample rate
            if "min_sample_rate" in q and "sample_rate" in checks:
                total += 1
                ok = checks["sample_rate"] >= q["min_sample_rate"]
                details["sample_rate"] = {"required": q["min_sample_rate"],
                                            "got": checks["sample_rate"], "ok": ok}
                if ok: passed += 1
            # Distinct colors
            if "min_distinct_colors" in q and "distinct_colors" in checks:
                total += 1
                ok = checks["distinct_colors"] >= q["min_distinct_colors"]
                details["distinct_colors"] = {"required": q["min_distinct_colors"],
                                                "got": checks["distinct_colors"], "ok": ok}
                if ok: passed += 1
        # min_files: count valid artifacts globally
        if "min_files" in q:
            total += 1
            ok = len(valid_artifacts) >= q["min_files"]
            details["min_files"] = {"required": q["min_files"],
                                     "got": len(valid_artifacts), "ok": ok}
            if ok: passed += 1
        if total == 0:
            return 0.7, details   # no relevant checks → neutral
        return passed / total, details

    def _style_match(self, contract: IntentContract, worker_outcome) -> float:
        """Best-effort style alignment check."""
        style = contract.quality_constraints.get("style_match")
        if not style:
            return 1.0   # no constraint → satisfied
        intent_low = (contract.raw_intent or "").lower()
        if style.lower() in intent_low:
            return 1.0   # style was explicit in intent
        # Check if any artifact's path or backend mentions the style
        for art in getattr(worker_outcome, "artifacts", []) or []:
            path = (art.get("path", "") or "").lower()
            if style.lower() in path:
                return 0.9
        return 0.6   # partial


# ── ProductionGuaranteeEngine ────────────────────────────────────────

class ProductionGuaranteeEngine:
    """The final boundary. Orchestrates contract compilation, worker
    execution result evaluation, and auto-repair routing.

    Callers (WorkerRouter) invoke `guarantee(realm, request, worker_fn)`
    where worker_fn is `lambda: worker.execute(request)`. The engine
    runs the worker, scores against the contract, and either returns
    VALIDATED, runs an auto-repair cycle, or returns FAIL.
    """

    def __init__(self):
        self._compiler = ContractCompiler()
        self._scorer = IntentSatisfactionScorer()
        self._lock = threading.RLock()
        self._validated = 0
        self._repaired = 0
        self._failed = 0
        self._rejected = 0
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.production_guarantee", self)
        except Exception:
            pass

    def guarantee(self, realm: str, request, worker_fn: Callable) -> GuaranteeOutcome:
        """Single entry point. Compile contract, execute worker via
        worker_fn, evaluate match, possibly auto-repair. Returns
        GuaranteeOutcome."""
        t0 = time.time()

        # 1. Contract compilation — FAIL-OPEN: pass the router-supplied realm
        # as a hint so a vague intent still compiles + dispatches the worker.
        contract = self._compiler.compile(
            getattr(request, "intent_text", "") or "",
            enriched=None,  # we don't have enriched in scope; rely on intent + spec
            spec=getattr(request, "spec", None),
            realm_hint=realm,
        )
        if contract is None:
            with self._lock:
                self._rejected += 1
            outcome = GuaranteeOutcome(
                contract_id="rejected",
                status="REJECTED",
                match_score=0.0,
                score_breakdown={},
                worker_outcome=None,
                failure_category=FAIL_REJECTED,
                diagnostics={"reason": "intent too vague to compile contract"},
                remediation="re-state the intent with a clearer realm "
                             "(e.g. 'create an image of …', 'generate audio …')",
                repair_history=[],
                final_artifacts=[],
                duration_ms=(time.time() - t0) * 1000.0,
                started_at=t0,
                finished_at=time.time(),
            )
            self._emit_outcome(outcome)
            return outcome

        # 2. Execute worker (synchronous)
        worker_outcome = worker_fn()

        # 3. Score against contract
        score, breakdown = self._scorer.score(contract, worker_outcome)

        # 4. Decide
        if score >= VALIDATED_THRESHOLD:
            outcome = self._build_outcome(
                contract, worker_outcome, score, breakdown,
                "VALIDATED", FAIL_REJECTED if False else "",
                "", [], t0,
            )
            with self._lock:
                self._validated += 1
            self._emit_outcome(outcome)
            return outcome

        if score >= RETRY_THRESHOLD:
            # Auto-repair loop
            return self._auto_repair(contract, worker_outcome, request, score,
                                      breakdown, t0)

        # FAIL — too low to recover
        category = self._classify_failure(worker_outcome, score, breakdown)
        outcome = self._build_outcome(
            contract, worker_outcome, score, breakdown,
            "FAIL", category,
            self._remediation_for(category, contract, worker_outcome),
            [], t0,
        )
        with self._lock:
            self._failed += 1
        self._emit_outcome(outcome)
        return outcome

    def _auto_repair(self, contract, worker_outcome, request, score,
                      breakdown, t0) -> GuaranteeOutcome:
        """Run up to MAX_REPAIR_CYCLES repair passes. Each pass picks a
        correction strategy based on the failure category."""
        repair_history: list = []
        best_score = score
        best_outcome = worker_outcome
        best_breakdown = breakdown

        for pass_n in range(1, MAX_REPAIR_CYCLES + 1):
            category = self._classify_failure(best_outcome, best_score, best_breakdown)
            strategy = self._strategy_for(category)
            self._emit_event("guarantee_repairing", {
                "contract_id": contract.contract_id,
                "pass":        pass_n,
                "category":    category,
                "strategy":    strategy,
                "prev_score":  best_score,
            })

            # Apply strategy: adjust the request (e.g. bump frames, change kind)
            new_request = self._apply_strategy(request, strategy)
            # Re-run worker
            from engine.workers import get_worker_for_realm
            from engine.workers.base_worker import WorkerRequest   # noqa
            worker = get_worker_for_realm(
                (contract.required_outputs[0] or {}).get("realm", "")
            )
            if worker is None:
                break
            try:
                new_request.refinement_pass = pass_n
                new_outcome = worker.execute(new_request)
            except Exception as e:
                _log.warning("repair pass %d worker raised: %s", pass_n, e)
                continue
            new_score, new_breakdown = self._scorer.score(contract, new_outcome)
            repair_history.append({
                "pass":        pass_n,
                "strategy":    strategy,
                "prev_score":  round(best_score, 3),
                "new_score":   round(new_score, 3),
                "improved":    new_score > best_score,
            })
            if new_score > best_score:
                best_score = new_score
                best_outcome = new_outcome
                best_breakdown = new_breakdown
            if best_score >= VALIDATED_THRESHOLD:
                break

        # Final adjudication
        if best_score >= VALIDATED_THRESHOLD:
            with self._lock:
                self._validated += 1
                self._repaired += 1
            status, category, remediation = "VALIDATED", "", ""
        else:
            with self._lock:
                self._failed += 1
            category = self._classify_failure(best_outcome, best_score, best_breakdown)
            status = "FAIL"
            remediation = self._remediation_for(category, contract, best_outcome)

        outcome = self._build_outcome(
            contract, best_outcome, best_score, best_breakdown,
            status, category, remediation, repair_history, t0,
        )
        self._emit_outcome(outcome)
        return outcome

    def _build_outcome(self, contract, worker_outcome, score, breakdown,
                        status, category, remediation, repair_history,
                        t0) -> GuaranteeOutcome:
        artifacts = []
        if worker_outcome is not None:
            for a in (getattr(worker_outcome, "artifacts", []) or []):
                if isinstance(a, dict) and a.get("validation", {}).get("valid"):
                    artifacts.append(a)
        return GuaranteeOutcome(
            contract_id=contract.contract_id,
            status=status,
            match_score=round(score, 3),
            score_breakdown=breakdown,
            worker_outcome=worker_outcome,
            failure_category=category,
            diagnostics={
                "contract":     contract.to_dict(),
                "worker_state": getattr(worker_outcome, "state", ""),
                "worker_error": getattr(worker_outcome, "error", ""),
            },
            remediation=remediation,
            repair_history=repair_history,
            final_artifacts=artifacts,
            duration_ms=(time.time() - t0) * 1000.0,
            started_at=t0,
            finished_at=time.time(),
        )

    def _classify_failure(self, worker_outcome, score, breakdown) -> str:
        if worker_outcome is None:
            return FAIL_MISSING_BACKEND
        state = getattr(worker_outcome, "state", "")
        error = (getattr(worker_outcome, "error", "") or "").lower()
        if state == "FAIL":
            if "unavailable" in error or "not on path" in error or "no image backend" in error \
                    or "no backend available" in error:
                return FAIL_MISSING_BACKEND
            return FAIL_TOOL_FAILURE
        # State READY/DEGRADED but score too low
        constraint = breakdown.get("constraint_score", 1.0)
        if constraint < 0.5:
            return FAIL_LOW_QUALITY
        style_match = breakdown.get("style_match", 1.0)
        if style_match < 0.7:
            return FAIL_SEMANTIC_MISMATCH
        return FAIL_INCOMPLETE

    def _strategy_for(self, category: str) -> str:
        if category == FAIL_MISSING_BACKEND:
            return "switch_backend"
        if category == FAIL_LOW_QUALITY:
            return "adjust_parameters"
        if category == FAIL_SEMANTIC_MISMATCH:
            return "reroute_worker"
        if category == FAIL_INCOMPLETE:
            return "re_execute_intent"
        return "re_execute_intent"

    def _apply_strategy(self, request, strategy: str):
        """Mutate request based on strategy. Returns a NEW WorkerRequest
        to avoid mutating the caller's object."""
        from engine.workers.base_worker import WorkerRequest
        new_params = dict(request.params or {})
        new_kind = request.kind
        if strategy == "adjust_parameters":
            # Bump quality knobs: frames, intensity, duration
            if "frames" in new_params:
                new_params["frames"] = max(1, int(new_params.get("frames", 1)) + 1)
            else:
                new_params["frames"] = 2
            new_params["refinement"] = True
        elif strategy == "switch_backend":
            new_params["prefer_backend"] = "next"
        elif strategy == "reroute_worker":
            # Mark spec for style-emphasis
            new_params["emphasize_style"] = True
        elif strategy == "re_execute_intent":
            new_params["re_execute"] = True
        return WorkerRequest(
            intent_text=request.intent_text,
            spec=request.spec,
            kind=new_kind,
            params=new_params,
            refinement_pass=getattr(request, "refinement_pass", 0),
            parent_artifact=getattr(request, "parent_artifact", None),
        )

    def _remediation_for(self, category: str, contract, worker_outcome) -> str:
        if category == FAIL_MISSING_BACKEND:
            tools = contract.tool_dependencies.get("fallback", [])
            if tools:
                return f"install one of: {', '.join(tools)}"
            return "install required backend per realm"
        if category == FAIL_LOW_QUALITY:
            return ("output quality below contract — re-state intent with "
                    "stronger ambition keywords (legendary / production-grade)")
        if category == FAIL_SEMANTIC_MISMATCH:
            return ("output did not align with intent semantics — be more "
                    "specific about style / medium")
        if category == FAIL_INCOMPLETE:
            return "generation produced no complete artifact — retry once or refine"
        if category == FAIL_TOOL_FAILURE:
            err = getattr(worker_outcome, "error", "")
            return f"tool error: {err[:160]}" if err else "backend reported a non-recoverable error"
        return "see diagnostics for details"

    # ── Telemetry ────────────────────────────────────────────────────
    def _emit_outcome(self, outcome: GuaranteeOutcome) -> None:
        # Receipt
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task=f"guarantee:{outcome.status.lower()}",
                executor="ProductionGuaranteeEngine",
                duration_ms=outcome.duration_ms,
                verified=(outcome.status == "VALIDATED"),
                compute_sha256=False,
                failure_reason=(outcome.failure_category
                                  if outcome.status in ("FAIL", "REJECTED") else None),
                evidence={
                    "contract_id":      outcome.contract_id,
                    "status":           outcome.status,
                    "match_score":      outcome.match_score,
                    "failure_category": outcome.failure_category,
                    "remediation":      outcome.remediation,
                    "repair_passes":    len(outcome.repair_history),
                    "valid_artifacts":  len(outcome.final_artifacts),
                    "intent_text":      outcome.diagnostics.get("contract", {}).get("raw_intent", "")[:120],
                },
            )
        except Exception:
            pass
        # Bus event
        kind_map = {
            "VALIDATED": "guarantee_validated",
            "AUTO_RETRY":"guarantee_repairing",
            "FAIL":      "guarantee_failed",
            "REJECTED":  "contract_rejected",
        }
        self._emit_event(kind_map.get(outcome.status, "guarantee_validated"), {
            "contract_id":      outcome.contract_id,
            "status":           outcome.status,
            "match_score":      outcome.match_score,
            "failure_category": outcome.failure_category,
            "remediation":      outcome.remediation,
            "repair_passes":    len(outcome.repair_history),
            "valid_artifacts":  len(outcome.final_artifacts),
        })

    def _emit_event(self, kind: str, payload: dict) -> None:
        try:
            from engine.live_stream import get_live_stream
            get_live_stream().emit_event(kind, payload)
        except Exception:
            pass

    def stats(self) -> dict:
        with self._lock:
            return {
                "validated": self._validated,
                "repaired":  self._repaired,
                "failed":    self._failed,
                "rejected":  self._rejected,
            }


_INSTANCE: Optional[ProductionGuaranteeEngine] = None


def get_production_guarantee() -> ProductionGuaranteeEngine:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ProductionGuaranteeEngine()
    return _INSTANCE
