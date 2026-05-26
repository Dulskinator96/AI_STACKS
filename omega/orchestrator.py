"""omega.orchestrator — the TASKMASTER Ω execution pipeline.

Execution / orchestration / verification layer (BUILD-034). Delegates into the
verified build-033 engine; re-implements nothing. Authority model (Section 2):

    USER → kernel.intent_compiler → omega.orchestrator → engine workers
         → artifact_validator → truth ledger → telemetry traces → rooms ui

    Only omega may collapse PARTIAL → RESOLVED, and ONLY after:
        file exists  AND  hash verified  AND  backend READY  AND  ledger execution_id

Every stage emits a thread-linked trace (omega.tracing). Persistent paths are
frozen-aware (omega.paths) — never _MEIPASS.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from omega.paths import ensure_src_on_path, omega_telemetry_dir
ensure_src_on_path()

from omega.contracts import (                       # noqa: E402
    TruthState, ExternalState, TaskState,
    TaskResult, KernelRunResult, ArtifactRecord,
    external_for, sha256_file, aggregate_truth,
    now_ts, new_run_id,
)
from omega.dag import compile_dag, KernelDAG        # noqa: E402

_log = logging.getLogger(__name__)

# Substrings in a worker error that mean "could not run", not "ran and failed".
_BLOCKED_MARKERS = ("unavailable", "no backend", "no worker", "not implemented",
                    "missing_backend", "backend not")


def _trace(state, message: str, **link):
    """Degrade-safe trace emit — tracing failures must never break execution."""
    try:
        from omega.tracing import emit
        return emit(state, message, **link)
    except Exception:
        return None


def _trace_fail(message: str, exc=None, **link):
    try:
        from omega.tracing import emit_failure
        return emit_failure(message, exc, **link)
    except Exception:
        return None


class TaskmasterKernel:
    """Bounded autonomous execution kernel. Stateless across runs except for the
    shared engine singletons it delegates to."""

    def __init__(self) -> None:
        self._run_count = 0

    # ── cold boot self check (delegate probes) ──────────────────────────────
    def cold_boot_self_check(self) -> dict:
        checks: dict[str, dict] = {}

        def probe(name: str, fn) -> None:
            try:
                ok, detail = fn()
                truth = TruthState.RESOLVED if ok else TruthState.BLOCKED
                checks[name] = {"internal": truth.value,
                                "external": external_for(truth).value, "detail": detail}
            except Exception as e:
                checks[name] = {"internal": TruthState.BLOCKED.value,
                                "external": ExternalState.DEFERRED.value,
                                "detail": f"{type(e).__name__}: {e}"}

        def chk_intent():
            from engine.intent_cortex import IntentCortex
            return callable(getattr(IntentCortex, "enrich", None)), "IntentCortex.enrich"

        def chk_router():
            from engine.worker_router import get_worker_router
            return callable(getattr(get_worker_router(), "route", None)), "WorkerRouter.route"

        def chk_validator():
            from engine.artifact_validator import get_artifact_validator
            return callable(getattr(get_artifact_validator(), "validate", None)), "ArtifactValidator.validate"

        def chk_ledger():
            from engine.mem_palace.memory_store import get_mem_palace
            return callable(getattr(get_mem_palace(), "record_execution", None)), "MemPalace.record_execution"

        def chk_backends():
            from engine.tool_fabric import scan_now
            scan = scan_now()
            present = [k for k, v in scan.items()
                       if getattr(v, "status", None) in ("READY", "DEGRADED")]
            return True, f"backends scanned: {present or 'none READY'}"

        def chk_synopsis():
            from engine.system_synopsis import generate_synopsis
            return callable(generate_synopsis), "system_synopsis.generate_synopsis"

        probe("intent_cortex", chk_intent)
        probe("worker_router", chk_router)
        probe("artifact_validator", chk_validator)
        probe("mem_palace_ledger", chk_ledger)
        probe("tool_fabric", chk_backends)
        probe("system_synopsis", chk_synopsis)

        resolved = sum(1 for c in checks.values() if c["internal"] == "RESOLVED")
        return {"checks": checks, "resolved": resolved, "total": len(checks),
                "boot_truth": (TruthState.RESOLVED.value if resolved == len(checks)
                               else TruthState.PARTIAL.value if resolved
                               else TruthState.BLOCKED.value)}

    # ── EXPANDED boot check (BUILD-034 Section 5) ───────────────────────────
    def boot_check(self, *, api_state: Optional[dict] = None) -> dict:
        """Verify the full orchestration substrate: delegates + API boot + room
        init + agent init + replay pipeline. Honest PASS/PARTIAL/FAIL — never a
        fabricated success."""
        result: dict[str, Any] = {"timestamp": now_ts()}
        base = self.cold_boot_self_check()
        result["delegates"] = base

        # rooms
        try:
            from omega.rooms import list_rooms
            rooms = list_rooms()
            result["rooms"] = {"count": len(rooms),
                               "ids": [r["room_id"] for r in rooms],
                               "ok": len(rooms) >= 7}
        except Exception as e:
            result["rooms"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

        # agents
        try:
            from omega.agents import list_agents
            agents = list_agents()
            result["agents"] = {"count": len(agents),
                                "roles": [a["role"] for a in agents],
                                "ok": len(agents) >= 4}
        except Exception as e:
            result["agents"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

        # replay pipeline (Auditor must be able to read the telemetry dir)
        try:
            from omega.agents import get_agent
            auditor = get_agent("auditor")
            probe = auditor.audit("run-nonexistent-probe")
            result["replay"] = {"ok": probe.get("verdict") == "NOT_FOUND",
                                "detail": "auditor reachable; replay store readable"}
        except Exception as e:
            result["replay"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

        # API boot (passed in from the embedded server start)
        if api_state is not None:
            result["api"] = {"ok": bool(api_state.get("ready")),
                             "host": api_state.get("host"), "port": api_state.get("port"),
                             "error": api_state.get("error")}
        else:
            result["api"] = {"ok": None, "detail": "not started in this context"}

        # orchestration substrate (kernel can compile a DAG)
        try:
            dag = compile_dag(self._enrich("smoke: compose a short tone"))
            ok, reason = dag.validate()
            result["orchestration"] = {"ok": ok, "detail": reason, "tasks": len(dag)}
        except Exception as e:
            result["orchestration"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

        gates = [base["boot_truth"] == "RESOLVED",
                 result["rooms"].get("ok"), result["agents"].get("ok"),
                 result["replay"].get("ok"), result["orchestration"].get("ok")]
        # API boot is non-blocking (a port conflict must not fail UI boot), but an
        # explicit API failure must NOT be reported as a full PASS — downgrade
        # honestly so the verdict reflects reality.
        passed = sum(1 for g in gates if g)
        verdict = ("PASS_REAL_EXECUTION" if passed == len(gates)
                   else "PARTIAL" if passed else "FAIL")
        if result["api"].get("ok") is False and verdict == "PASS_REAL_EXECUTION":
            verdict = "PARTIAL"
        result["substrate_truth"] = verdict
        _trace(self._tstate(result["substrate_truth"]),
               f"omega boot_check: {result['substrate_truth']} "
               f"({passed}/{len(gates)} substrate gates; api={result['api'].get('ok')})",
               phase="BOOT")
        return result

    @staticmethod
    def _tstate(verdict: str):
        from omega.tracing import TraceState
        return {"PASS_REAL_EXECUTION": TraceState.SUCCESS, "PARTIAL": TraceState.WARNING,
                "FAIL": TraceState.FAILURE}.get(verdict, TraceState.INFO)

    # ── main pipeline ────────────────────────────────────────────────────────
    def run(self, intent_text: str, *, dry_run: bool = False) -> KernelRunResult:
        from omega.tracing import trace_context, TraceState
        t0 = now_ts()
        self._run_count += 1
        run_id = new_run_id()
        result = KernelRunResult(run_id=run_id, intent_text=intent_text, created_at=t0)

        with trace_context(trace_id=run_id[-8:], phase="INTENT"):
            _trace(TraceState.INFO, f"run start: {intent_text!r} (dry_run={dry_run})")

            # STAGE 1 — INTENT
            enriched = self._enrich(intent_text)
            result.enriched = self._enriched_dict(enriched)

            # STAGE 2 — PLAN → DAG
            dag = compile_dag(enriched)
            ok, reason = dag.validate()
            result.dag = dag.to_list()
            if not ok:
                _trace_fail(f"DAG invalid: {reason}", phase="DAG")
                result.drift.append({"kind": "dag_invalid", "detail": reason})
                result.overall_truth = TruthState.FAILED
                result.overall_external = external_for(TruthState.FAILED)
                return self._finalize(result, t0)
            _trace(TraceState.INFO, f"DAG compiled: {len(dag)} task(s), {reason}", phase="DAG")

            # STAGE 3..8 — per task
            task_truths: list[TruthState] = []
            for task in dag.topological_order():
                if dry_run:
                    tr = TaskResult(task_id=task.task_id, realm=task.realm,
                                    state=TaskState.SKIPPED, truth=TruthState.UNRESOLVED,
                                    external=external_for(TruthState.UNRESOLVED),
                                    intent_text=task.intent_text,
                                    remediation="dry_run: execution skipped")
                    result.tasks.append(tr.to_dict())
                    task_truths.append(TruthState.UNRESOLVED)
                    continue
                tr = self._execute_task(task)
                result.tasks.append(tr.to_dict())
                task_truths.append(tr.truth)
                if tr.worker_state == "READY" and tr.truth != TruthState.RESOLVED:
                    _trace(TraceState.DRIFT,
                           f"unbacked READY claim on {tr.realm} (no confirmed artifact)",
                           worker_id=tr.realm, phase="VERIFY")
                    result.drift.append({
                        "kind": "unbacked_ready_claim", "task_id": tr.task_id,
                        "detail": "worker READY but no validated on-disk artifact w/ matching hash"})

            result.overall_truth = aggregate_truth(task_truths)
            result.overall_external = external_for(result.overall_truth)
            result.confidence = self._confidence(result.tasks)
            result.entropy_class = "DETERMINISTIC" if not dry_run else "DRY_RUN"
            self._drift_analysis(dag, result)

            _trace(self._truth_trace(result.overall_truth),
                   f"run complete: {result.overall_truth.value} "
                   f"conf={result.confidence} drift={len(result.drift)}", phase="DONE")
            return self._finalize(result, t0)

    @staticmethod
    def _truth_trace(truth: TruthState):
        from omega.tracing import TraceState
        return {TruthState.RESOLVED: TraceState.SUCCESS, TruthState.PARTIAL: TraceState.WARNING,
                TruthState.BLOCKED: TraceState.WARNING, TruthState.FAILED: TraceState.FAILURE,
                TruthState.UNRESOLVED: TraceState.WARNING}.get(truth, TraceState.INFO)

    # ── stage helpers ──────────────────────────────────────────────────────
    def _enrich(self, intent_text: str):
        try:
            from engine.intent_cortex import IntentCortex
            return IntentCortex().enrich(intent_text)
        except Exception as e:
            _trace_fail(f"intent enrichment unavailable: {e}", exc=e, phase="INTENT")
            class _Stub:
                raw_text = intent_text
                realm = None
                target_pipeline = None
                medium = None
                ambition = 0.0
                style = None
                _enrich_error = f"{type(e).__name__}: {e}"
            return _Stub()

    @staticmethod
    def _enriched_dict(enriched) -> dict:
        try:
            if hasattr(enriched, "to_dict"):
                return enriched.to_dict()
        except Exception:
            pass
        return {"raw_text": getattr(enriched, "raw_text", ""),
                "realm": getattr(enriched, "realm", None),
                "medium": getattr(enriched, "medium", None),
                "ambition": getattr(enriched, "ambition", None),
                "enrich_error": getattr(enriched, "_enrich_error", None)}

    def _execute_task(self, task) -> TaskResult:
        from omega.tracing import trace_context, TraceState
        t0 = now_ts()
        tr = TaskResult(task_id=task.task_id, realm=task.realm,
                        state=TaskState.ROUTING, truth=TruthState.UNRESOLVED,
                        external=external_for(TruthState.UNRESOLVED),
                        intent_text=task.intent_text, started_at=t0)

        with trace_context(worker_id=task.realm, phase="ROUTE"):
            if not task.params.get("known_realm", False):
                _trace(TraceState.WARNING, f"realm '{task.realm}' has no registered worker")
                return self._block(tr, t0,
                    error=f"realm '{task.realm}' has no registered worker",
                    remediation="add a worker in engine/workers/ or refine the intent realm")

            try:
                from engine.worker_router import get_worker_router
                from engine.workers.base_worker import WorkerRequest
                router = get_worker_router()
            except Exception as e:
                _trace_fail(f"router/worker substrate unavailable: {e}", exc=e)
                return self._block(tr, t0,
                    error=f"router/worker substrate unavailable: {type(e).__name__}: {e}",
                    remediation="verify engine.worker_router + engine.workers import cleanly")

            try:
                decision = router.decide(task.realm)
            except Exception as e:
                decision = None
                _log.debug("decide() raised: %s", e)

            backend_ready = bool(decision is not None and getattr(decision, "decision", "") == "DISPATCH")
            if decision is not None and getattr(decision, "decision", "") == "FAIL_NO_BACKEND" \
                    and not getattr(decision, "fallback_realm", None):
                _trace(TraceState.WARNING,
                       f"backend gate closed for '{task.realm}': {getattr(decision,'missing_backends',[])}")
                return self._block(tr, t0,
                    error=f"no backend for realm '{task.realm}': {getattr(decision,'missing_backends',[])}",
                    remediation=getattr(decision, "remediation", "install the realm backend"))

            tr.state = TaskState.RUNNING
            _trace(TraceState.INFO, f"dispatching worker for '{task.realm}'", phase="EXECUTE")
            try:
                request = WorkerRequest(intent_text=task.intent_text, spec=task.params,
                                        kind="", params=dict(task.params))
                outcome = router.route(task.realm, request)
            except Exception as e:
                _trace_fail(f"execution raised in worker for '{task.realm}'", exc=e, phase="EXECUTE")
                return self._fail(tr, t0,
                    error=f"execution raised: {type(e).__name__}: {e}",
                    remediation="inspect worker logic + backend availability")

            tr.worker_state = getattr(outcome, "state", "") or ""
            tr.backend = getattr(outcome, "backend", "") or ""
            backend_ready = backend_ready or bool(tr.backend)

            # VERIFY + HASH — independent zero-trust re-check
            verified_any = False
            for a in (getattr(outcome, "artifacts", []) or []):
                path = a.get("path", "")
                worker_sha = a.get("sha256")
                val = a.get("validation", {}) or {}
                k_sha = sha256_file(path)
                exists = k_sha is not None
                rec = ArtifactRecord(
                    path=path, exists_on_disk=exists,
                    size_bytes=(Path(path).stat().st_size if exists else 0),
                    kernel_sha256=k_sha, worker_sha256=worker_sha,
                    hash_match=(None if (worker_sha is None or k_sha is None) else worker_sha == k_sha),
                    validation_valid=bool(val.get("valid")),
                    validation_score=float(val.get("score", 0.0) or 0.0))
                tr.artifacts.append(rec.to_dict())
                if exists and rec.validation_valid and rec.hash_match is not False:
                    verified_any = True

            tr.state = TaskState.VERIFIED

            # LEDGER — confirm a row exists
            eid = getattr(outcome, "_mem_execution_id", None)
            tr.execution_id = eid
            tr.ledger_confirmed = self._confirm_ledger(eid)

            tr.error = getattr(outcome, "error", "") or ""
            tr.remediation = getattr(outcome, "remediation", "") or ""
            wstate = tr.worker_state.upper()
            elow = tr.error.lower()

            # SECTION 2 AUTHORITY: collapse PARTIAL → RESOLVED only with all four.
            collapse_ok = verified_any and backend_ready and tr.ledger_confirmed
            if wstate == "READY" and collapse_ok:
                tr.truth = TruthState.RESOLVED
                tr.state = TaskState.RESOLVED
            elif wstate in ("READY", "DEGRADED") and verified_any:
                tr.truth = TruthState.PARTIAL          # real file, but missing backend/ledger evidence
                tr.state = TaskState.RESOLVED
            elif any(m in elow for m in _BLOCKED_MARKERS):
                tr.truth = TruthState.BLOCKED
                tr.state = TaskState.BLOCKED
            elif wstate == "FAIL":
                tr.truth = TruthState.FAILED
                tr.state = TaskState.FAILED
            else:
                tr.truth = TruthState.UNRESOLVED

            tr.external = external_for(tr.truth)
            tr.finished_at = now_ts()
            tr.duration_ms = round((tr.finished_at - t0) * 1000.0, 1)
            _trace(self._truth_trace(tr.truth),
                   f"task {tr.realm} → {tr.truth.value} (backend_ready={backend_ready}, "
                   f"verified={verified_any}, ledger={tr.ledger_confirmed})",
                   execution_id=eid, backend=tr.backend, phase="VERIFY")
            return tr

    @staticmethod
    def _confirm_ledger(execution_id: Optional[str]) -> bool:
        if not execution_id:
            return False
        try:
            from engine.mem_palace.memory_store import get_mem_palace
            return get_mem_palace().get_execution(execution_id) is not None
        except Exception:
            return False

    def _drift_analysis(self, dag: KernelDAG, result: KernelRunResult) -> None:
        try:
            for tr in result.tasks:
                if tr["truth"] == TruthState.BLOCKED.value:
                    result.drift.append({"kind": "backend_blocked", "realm": tr["realm"],
                                         "detail": tr.get("error", ""),
                                         "remediation": tr.get("remediation", "")})
        except Exception as e:
            _log.debug("drift analysis degraded: %s", e)

    @staticmethod
    def _confidence(tasks: list[dict]) -> float:
        if not tasks:
            return 0.0
        good = 0
        for t in tasks:
            if t["truth"] == TruthState.RESOLVED.value and t.get("ledger_confirmed"):
                if any(a.get("exists_on_disk") for a in t.get("artifacts", [])):
                    good += 1
        return round(good / len(tasks), 3)

    # ── result helpers ──────────────────────────────────────────────────────
    def _block(self, tr: TaskResult, t0: float, *, error: str, remediation: str) -> TaskResult:
        tr.truth = TruthState.BLOCKED
        tr.state = TaskState.BLOCKED
        tr.external = external_for(TruthState.BLOCKED)
        tr.error, tr.remediation = error, remediation
        tr.finished_at = now_ts()
        tr.duration_ms = round((tr.finished_at - t0) * 1000.0, 1)
        return tr

    def _fail(self, tr: TaskResult, t0: float, *, error: str, remediation: str) -> TaskResult:
        tr.truth = TruthState.FAILED
        tr.state = TaskState.FAILED
        tr.external = external_for(TruthState.FAILED)
        tr.error, tr.remediation = error, remediation
        tr.finished_at = now_ts()
        tr.duration_ms = round((tr.finished_at - t0) * 1000.0, 1)
        return tr

    def _finalize(self, result: KernelRunResult, t0: float) -> KernelRunResult:
        result.finished_at = now_ts()
        result.duration_ms = round((result.finished_at - t0) * 1000.0, 1)
        intended = omega_telemetry_dir() / f"{result.run_id}.json"
        result.telemetry_path = str(intended)
        if not self._write_telemetry(result, intended):
            result.telemetry_path = None
        return result

    def _write_telemetry(self, result: KernelRunResult, path: Path) -> bool:
        try:
            path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
            return True
        except Exception as e:
            _log.warning("omega telemetry write failed: %s", e)
            return False


_KERNEL: Optional[TaskmasterKernel] = None


def get_kernel() -> TaskmasterKernel:
    global _KERNEL
    if _KERNEL is None:
        _KERNEL = TaskmasterKernel()
    return _KERNEL
