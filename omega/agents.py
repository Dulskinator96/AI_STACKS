"""omega.agents — the Pyramid agent system (DBOMBCENTRAL).

Four CONSTRAINED orchestration roles over the single verified runtime. Not
chatbots. Each delegates into omega.orchestrator + the build-033 engine.

    Strategist  decomposition, planning, DAG synthesis        (read-only plan)
    Analyst     research, contradiction detection, telemetry  (read-only)
    Executor    runtime execution through verified workers     (the only mutator)
    Auditor     entropy detection, replay verification, drift  (read-only)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from omega.contracts import sha256_file
from omega.orchestrator import get_kernel
from omega.paths import omega_telemetry_dir

_log = logging.getLogger(__name__)


class _Agent:
    role: str = "agent"
    capabilities: tuple[str, ...] = ()

    def can(self, action: str) -> bool:
        return action in self.capabilities

    def descriptor(self) -> dict:
        return {"role": self.role, "capabilities": list(self.capabilities),
                "mutates_runtime": isinstance(self, Executor)}


class Strategist(_Agent):
    role = "strategist"
    capabilities = ("plan", "decompose", "synthesize_dag")

    def plan(self, intent_text: str) -> dict:
        result = get_kernel().run(intent_text, dry_run=True)
        d = result.to_dict()
        return {"role": self.role, "intent": intent_text, "enriched": d["enriched"],
                "dag": d["dag"], "task_count": len(d["dag"]),
                "note": "plan only — no execution; hand 'dag' to the Executor to run"}


class Analyst(_Agent):
    role = "analyst"
    capabilities = ("research", "interpret_telemetry", "detect_contradiction")

    def analyze(self) -> dict:
        out: dict[str, Any] = {"role": self.role, "contradictions": []}
        try:
            from engine.tool_fabric import scan_now
            scan = scan_now()
            out["backends"] = {k: getattr(v, "status", str(v)) for k, v in scan.items()}
        except Exception as e:
            out["backends"] = {"error": f"{type(e).__name__}: {e}"}
        try:
            from engine.system_synopsis import generate_synopsis
            syn = generate_synopsis()
            out["system_health"] = syn.get("system_health", {}) if isinstance(syn, dict) else {}
            honesty = syn.get("honesty_report", {}) if isinstance(syn, dict) else {}
            if honesty.get("stubs_detected"):
                out["contradictions"].append({"kind": "stubs_detected",
                                              "count": len(honesty["stubs_detected"])})
            if honesty.get("orphans"):
                out["contradictions"].append({"kind": "orphans",
                                              "count": len(honesty["orphans"])})
        except Exception as e:
            out["system_health"] = {"error": f"{type(e).__name__}: {e}"}
        return out


class Executor(_Agent):
    role = "executor"
    capabilities = ("execute", "run_pipeline")

    def execute(self, intent_text: str) -> dict:
        return {"role": self.role, "run": get_kernel().run(intent_text).to_dict()}


class Auditor(_Agent):
    role = "auditor"
    capabilities = ("audit", "replay_verify", "entropy_score", "drift_analysis")

    def audit(self, run_id: str) -> dict:
        from omega.tracing import emit, TraceState
        path = omega_telemetry_dir() / f"{run_id}.json"
        if not path.is_file():
            return {"role": self.role, "run_id": run_id, "verdict": "NOT_FOUND",
                    "detail": f"no telemetry record at {path}"}
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            return {"role": self.role, "run_id": run_id, "verdict": "UNREADABLE",
                    "detail": f"{type(e).__name__}: {e}"}

        replay: list[dict] = []
        intact = True
        for t in rec.get("tasks", []):
            for a in t.get("artifacts", []):
                claimed = a.get("kernel_sha256")
                current = sha256_file(a.get("path", ""))
                ok = bool(claimed) and current == claimed
                if not ok:
                    intact = False
                replay.append({"path": a.get("path"), "claimed_sha256": claimed,
                               "current_sha256": current, "still_present": current is not None,
                               "unchanged": ok})
        verdict = ("REPLAY_VERIFIED" if intact and replay
                   else "NO_ARTIFACTS" if not replay else "REPLAY_DRIFT")
        try:
            emit(TraceState.REPLAY, f"replay {run_id}: {verdict}", execution_id=None)
        except Exception:
            pass
        return {"role": self.role, "run_id": run_id, "verdict": verdict,
                "original_truth": rec.get("overall_truth"),
                "entropy_class": rec.get("entropy_class"),
                "drift": rec.get("drift", []), "replay": replay}


_AGENTS: dict[str, _Agent] = {
    "strategist": Strategist(),
    "analyst":    Analyst(),
    "executor":   Executor(),
    "auditor":    Auditor(),
}


def get_agent(role: str) -> Optional[_Agent]:
    return _AGENTS.get((role or "").lower())


def list_agents() -> list[dict]:
    return [a.descriptor() for a in _AGENTS.values()]
