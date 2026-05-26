"""engine/workers/base_worker.py — BUILD-022 base worker contract.

Defines the 9-step worker execution contract. Subclasses implement two
hooks:
  · `_do_execute(request, workspace)` → list[str] of artifact paths
  · `_validate(path)` → ValidationResult

Everything else (workspace, manifest, hash, lineage, preview, export
manifest, READY/FAIL emission) is handled here so every worker has
identical observability semantics.

Reality Enforcement: a worker NEVER returns READY without each artifact
passing _validate(). Subclasses MUST raise on truly missing backends —
the base class catches and converts to FAIL with remediation.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)


# Threshold: workers below this validation score auto-queue refinement
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


class BaseWorker:
    """Worker substrate. Subclass and implement _do_execute + _validate."""

    REALM: str = "misc"
    NAME:  str = "BaseWorker"

    def __init__(self):
        self._instance_id = f"worker-{self.NAME.lower()}-{uuid.uuid4().hex[:6]}"
        self._lock = threading.Lock()
        self._run_count = 0
        self._success_count = 0
        self._fail_count = 0
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register(f"engine.workers.{self.REALM}", self)
        except Exception:
            pass

    # ── Public entry ─────────────────────────────────────────────────
    def execute(self, request: WorkerRequest) -> WorkerOutcome:
        """Run the 9-step contract synchronously. Caller should invoke
        this on a worker thread (DeferredWorkspaceLoader.run)."""
        t0 = time.time()
        with self._lock:
            self._run_count += 1

        # 1. Spawn isolated workspace via ProductionCore
        try:
            from engine.production_core import get_production_core
            core = get_production_core()
            psess = core.start_session(
                intent_text=request.intent_text,
                realm=self.REALM,
                spec_snapshot=self._spec_summary(request.spec),
            )
            workspace = Path(psess.output_dir)
            workspace.mkdir(parents=True, exist_ok=True)
            core.claim(psess)
        except Exception as e:
            return self._fail_outcome(request, t0,
                workspace=Path(__file__).parent,
                error=f"workspace allocation failed: {e}",
                remediation="ensure ProductionCore + ArtifactLineage available")

        outcome = WorkerOutcome(
            worker_id=self._instance_id,
            worker_name=self.NAME,
            realm=self.REALM,
            state="RUNNING",
            intent_text=request.intent_text,
            started_at=t0,
            finished_at=0.0,
            duration_ms=0.0,
            workspace=str(workspace),
            manifest_path=None,
            refinement_pass=request.refinement_pass,
        )
        self._emit("running", outcome)

        # 2. Build execution manifest BEFORE running so failures still have it
        manifest_path = workspace / "manifest.json"
        manifest = self._initial_manifest(request, workspace, psess.session_id)
        try:
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            outcome.manifest_path = str(manifest_path)
        except Exception as e:
            _log.warning("manifest write failed: %s", e)

        # 3. Execute subprocess/tool/API
        try:
            artifact_paths = self._do_execute(request, workspace)
            backend = self._last_backend()
            outcome.backend = backend or ""
        except NotImplementedError as e:
            try: core.release(psess)
            except Exception: pass
            return self._finalize_fail(outcome, manifest, manifest_path,
                                        f"backend not implemented: {e}",
                                        "implement _do_execute for this worker")
        except Exception as e:
            try: core.release(psess)
            except Exception: pass
            return self._finalize_fail(outcome, manifest, manifest_path,
                                        f"execution raised: {e}",
                                        "check backend availability + worker logic")

        # BUILD-023: Enter VALIDATING state explicitly (between execute
        # and per-artifact validate). Receipt + visible state change.
        outcome.state = "VALIDATING"
        self._emit("validating", outcome)

        # 4-5. Verify existence + hash. 6. Register lineage. 7. Preview.
        scores: list[float] = []
        for ap in artifact_paths:
            p = Path(ap)
            if not p.is_file():
                outcome.artifacts.append({
                    "path": str(p), "exists": False,
                    "validation": {"valid": False, "score": 0.0,
                                    "error": "file missing after execute"},
                })
                continue
            size = p.stat().st_size
            sha = self._sha256(p)
            # BUILD-023: Canonical validation now goes through ArtifactValidator
            # for the realm-level rules. The worker's own _validate() is still
            # called as a defensive backstop — both must pass.
            validation = self._canonical_validate(p, request)
            try:
                if validation is None or not isinstance(validation, ValidationResult):
                    validation = ValidationResult(valid=False, score=0.0,
                                                    error="validator returned non-result")
            except Exception:
                pass

            # 6. Register lineage
            try:
                core.register_artifact(psess, str(p), backend or self.NAME)
            except Exception as e:
                _log.debug("lineage register failed: %s", e)

            # 7. Preview registration
            try:
                from engine.preview_registry import get_preview_registry
                get_preview_registry().register_preview(
                    artifact_path=str(p), realm=self.REALM,
                    backend=backend or self.NAME,
                    session_id=psess.session_id,
                )
            except Exception:
                pass

            outcome.artifacts.append({
                "path":       str(p),
                "exists":     True,
                "size_bytes": size,
                "sha256":     sha,
                "backend":    backend or self.NAME,
                "validation": validation.to_dict(),
            })
            if validation.valid:
                scores.append(validation.score)

        # Overall validation: artifacts must exist AND validate
        valid_count = sum(1 for a in outcome.artifacts if a.get("validation", {}).get("valid"))
        overall = (sum(scores) / len(scores)) if scores else 0.0
        outcome.overall_validation_score = round(overall, 3)

        if valid_count == 0:
            # 9. FAIL — no artifact passed validation
            try: core.release(psess)
            except Exception: pass
            return self._finalize_fail(outcome, manifest, manifest_path,
                "no artifact passed validation",
                self._suggest_remediation(outcome))

        # 8. Emit export manifest with full outcome embedded
        manifest["completed_at"] = time.time()
        manifest["duration_ms"]  = (time.time() - t0) * 1000.0
        manifest["artifacts"]    = outcome.artifacts
        manifest["backend"]      = outcome.backend
        manifest["state"]        = "READY"
        manifest["overall_validation_score"] = outcome.overall_validation_score
        try:
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except Exception:
            pass

        # 9. READY state (DEGRADED if some artifacts failed validation)
        if valid_count < len(outcome.artifacts):
            outcome.state = "DEGRADED"
        else:
            outcome.state = "READY"

        # Quality-gate refinement scheduling
        try:
            from engine.quality_gate import get_quality_gate
            qg = get_quality_gate()
            if qg.should_refine(outcome):
                outcome.auto_refine_queued = qg.enqueue_refinement(outcome, request)
        except Exception:
            pass

        outcome.finished_at = time.time()
        outcome.duration_ms = (outcome.finished_at - t0) * 1000.0
        try: core.release(psess)
        except Exception: pass
        with self._lock:
            self._success_count += 1
        self._emit("ready", outcome)
        try:
            core.export(psess)
        except Exception:
            pass
        return outcome

    def execute_async(self, request: WorkerRequest,
                       on_done: Optional[Callable[[WorkerOutcome], None]] = None) -> None:
        """Submit execute() to a worker thread."""
        try:
            from runtime.deferred_loader import DeferredWorkspaceLoader
            DeferredWorkspaceLoader.run(
                lambda: self.execute(request),
                on_done=on_done,
                name=f"{self.NAME}-{uuid.uuid4().hex[:4]}",
            )
        except Exception as e:
            outcome = WorkerOutcome(
                worker_id=self._instance_id, worker_name=self.NAME,
                realm=self.REALM, state="FAIL",
                intent_text=request.intent_text,
                started_at=time.time(), finished_at=time.time(),
                duration_ms=0.0, workspace="", manifest_path=None,
                error=f"deferred loader unavailable: {e}",
            )
            if on_done:
                on_done(outcome)

    # ── Hooks (subclasses implement) ──────────────────────────────────
    def _do_execute(self, request: WorkerRequest, workspace: Path) -> list:
        """Return list of artifact paths produced. Set `self._cur_backend`
        to identify which backend was used. Raise on unrecoverable
        backend unavailability."""
        raise NotImplementedError

    def _validate(self, path: Path) -> ValidationResult:
        """Validate a single artifact. Return ValidationResult."""
        raise NotImplementedError

    # ── Internals (subclasses don't override) ─────────────────────────
    def stats(self) -> dict:
        with self._lock:
            return {
                "name":          self.NAME,
                "realm":         self.REALM,
                "run_count":     self._run_count,
                "success_count": self._success_count,
                "fail_count":    self._fail_count,
            }

    def _spec_summary(self, spec: Any) -> dict:
        if spec is None:
            return {}
        d = {}
        for k in ("style", "tone", "lighting", "composition", "emotion",
                   "ambition", "soundtrack_profile", "color_palette",
                   "architecture_style"):
            if hasattr(spec, k):
                v = getattr(spec, k)
                if v is not None:
                    d[k] = v if not isinstance(v, list) else list(v)
        return d

    def _initial_manifest(self, request: WorkerRequest, workspace: Path,
                            session_id: str) -> dict:
        return {
            "worker_name":       self.NAME,
            "worker_id":         self._instance_id,
            "realm":             self.REALM,
            "session_id":        session_id,
            "intent_text":       request.intent_text,
            "kind":              request.kind,
            "params":            {k: v for k, v in request.params.items()
                                   if isinstance(v, (str, int, float, bool, list, dict))},
            "spec":              self._spec_summary(request.spec),
            "workspace":         str(workspace),
            "refinement_pass":   request.refinement_pass,
            "parent_artifact":   request.parent_artifact,
            "started_at":        time.time(),
            "state":             "RUNNING",
        }

    def _sha256(self, p: Path) -> Optional[str]:
        try:
            h = hashlib.sha256()
            with p.open("rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return None

    def _safe_validate(self, p: Path) -> ValidationResult:
        try:
            return self._validate(p)
        except Exception as e:
            return ValidationResult(valid=False, score=0.0,
                                      error=f"validator raised: {e}")

    def _canonical_validate(self, p: Path, request) -> ValidationResult:
        """BUILD-023: canonical validation flow.

        Calls the ArtifactValidator (single source of truth) for the
        realm-level rules. Also runs the worker's own `_validate` as a
        defensive backstop — both must pass for the artifact to be
        considered valid. Score is the minimum of both.
        """
        canonical = None
        try:
            from engine.artifact_validator import get_artifact_validator
            canonical = get_artifact_validator().validate(
                self.REALM, p,
                intent_text=getattr(request, "intent_text", "") or "",
            )
        except Exception as e:
            canonical = ValidationResult(valid=False, score=0.0,
                                          error=f"ArtifactValidator raised: {e}")
        # Worker's own validator (may be a no-op delegate)
        worker_side = self._safe_validate(p)
        # Both must agree on validity. Score is min. Checks are merged.
        merged_checks = {}
        try:
            merged_checks.update(canonical.checks or {})
        except Exception:
            pass
        try:
            merged_checks.update(worker_side.checks or {})
        except Exception:
            pass
        valid = bool(canonical.valid) and bool(worker_side.valid)
        score = min(float(canonical.score or 0.0),
                    float(worker_side.score or 0.0))
        error = canonical.error or worker_side.error or ""
        return ValidationResult(valid=valid, score=score,
                                  checks=merged_checks, error=error)

    def _last_backend(self) -> str:
        return getattr(self, "_cur_backend", "") or ""

    def _suggest_remediation(self, outcome: WorkerOutcome) -> str:
        # Aggregate validation errors into a concise remediation hint
        msgs: list[str] = []
        for a in outcome.artifacts:
            v = a.get("validation", {}) or {}
            err = v.get("error", "")
            if err and err not in msgs:
                msgs.append(err)
        if msgs:
            return " · ".join(msgs[:3])
        return "no artifact produced; check backend availability"

    def _fail_outcome(self, request: WorkerRequest, t0: float,
                       workspace: Path, error: str,
                       remediation: str) -> WorkerOutcome:
        outcome = WorkerOutcome(
            worker_id=self._instance_id, worker_name=self.NAME,
            realm=self.REALM, state="FAIL",
            intent_text=request.intent_text,
            started_at=t0,
            finished_at=time.time(),
            duration_ms=(time.time() - t0) * 1000.0,
            workspace=str(workspace),
            manifest_path=None,
            error=error,
            remediation=remediation,
            refinement_pass=request.refinement_pass,
        )
        with self._lock:
            self._fail_count += 1
        self._emit("fail", outcome)
        return outcome

    def _finalize_fail(self, outcome: WorkerOutcome, manifest: dict,
                        manifest_path: Path, error: str,
                        remediation: str) -> WorkerOutcome:
        outcome.state = "FAIL"
        outcome.error = error
        outcome.remediation = remediation
        outcome.finished_at = time.time()
        outcome.duration_ms = (outcome.finished_at - outcome.started_at) * 1000.0
        manifest["state"] = "FAIL"
        manifest["error"] = error
        manifest["remediation"] = remediation
        manifest["completed_at"] = time.time()
        manifest["artifacts"] = outcome.artifacts
        try:
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except Exception:
            pass
        with self._lock:
            self._fail_count += 1
        self._emit("fail", outcome)
        return outcome

    def _emit(self, outcome_kind: str, outcome: WorkerOutcome) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task=f"worker:{self.REALM}:{outcome_kind}",
                executor=self.NAME,
                duration_ms=outcome.duration_ms,
                verified=(outcome.state == "READY"),
                compute_sha256=False,
                failure_reason=(outcome.error if outcome.state == "FAIL" else None),
                evidence={
                    "worker_id":          outcome.worker_id,
                    "state":              outcome.state,
                    "backend":            outcome.backend,
                    "artifact_count":     len(outcome.artifacts),
                    "valid_count":        sum(1 for a in outcome.artifacts
                                                if a.get("validation", {}).get("valid")),
                    "overall_score":      outcome.overall_validation_score,
                    "refinement_pass":    outcome.refinement_pass,
                    "auto_refine_queued": outcome.auto_refine_queued,
                    "workspace":          outcome.workspace,
                    "intent_text":        outcome.intent_text[:120],
                },
            )
        except Exception:
            pass
        # BUILD-024: push to live stream bus so UI updates immediately
        try:
            from engine.live_stream import get_live_stream
            get_live_stream().emit_event(f"worker_{outcome_kind}", {
                "worker_id":      outcome.worker_id,
                "worker_name":    outcome.worker_name,
                "realm":          outcome.realm,
                "state":          outcome.state,
                "backend":        outcome.backend,
                "artifact_count": len(outcome.artifacts),
                "overall_score":  outcome.overall_validation_score,
                "intent_text":    outcome.intent_text[:160],
                "duration_ms":    outcome.duration_ms,
                "error":          outcome.error[:200] if outcome.error else "",
            })
        except Exception:
            pass
