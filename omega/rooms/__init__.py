"""omega.rooms — DBOMBCENTRAL unified room registry (BUILD-034 Section 4).

Rooms are FILTERED orchestration surfaces over ONE runtime: same ledger, same
telemetry, same execution pipeline, same backend registry, same truth engine.
Rooms only alter permissions / views / orchestration mode / tool exposure —
never the runtime, never memory, never the truth model.

    Research   Analyst    read telemetry / synopsis / memory / traces
    Plan       Strategist decompose intent → DAG (no execution)
    Learn      Analyst    inspect learned preference / semantic memory
    Summarize  Analyst    synthesize recent runs into a digest
    Execute    Executor   real execution through verified workers (mutator)
    Replay     Auditor    replay-verify + drift on a past run
    Build      —          self-diagnosis + patch proposal (propose-only)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from omega.agents import get_agent, _AGENTS
from omega.orchestrator import get_kernel
from omega.paths import omega_telemetry_dir, ledger_db

_log = logging.getLogger(__name__)


def shared_runtime() -> dict:
    """Identity of the single shared substrate every room operates over."""
    return {
        "kernel_id": id(get_kernel()),
        "agents": list(_AGENTS.keys()),
        "ledger_db": str(ledger_db()),
        "telemetry_dir": str(omega_telemetry_dir()),
        "shares": {"ledger": True, "telemetry": True, "execution_pipeline": True,
                   "backend_registry": True, "truth_engine": True},
    }


@dataclass
class Room:
    room_id:       str
    title:         str
    primary_agent: Optional[str]
    mode:          str                      # orchestration mode
    description:   str
    _actions:      dict[str, Callable[..., dict]] = field(default_factory=dict, repr=False)

    @property
    def actions(self) -> list[str]:
        return list(self._actions.keys())

    def descriptor(self) -> dict:
        return {"room_id": self.room_id, "title": self.title,
                "primary_agent": self.primary_agent, "mode": self.mode,
                "description": self.description, "actions": self.actions,
                "shared_runtime": True}

    def invoke(self, action: str, **kwargs) -> dict:
        fn = self._actions.get(action)
        if fn is None:
            return {"room": self.room_id, "error": "unknown action", "available": self.actions}
        try:
            payload = fn(**kwargs)
        except TypeError as e:
            return {"room": self.room_id, "action": action, "error": f"bad arguments: {e}"}
        except Exception as e:
            return {"room": self.room_id, "action": action,
                    "error": f"{type(e).__name__}: {e}"}
        return {"room": self.room_id, "action": action, "result": payload}


# ── action handlers (delegate into shared agents / kernel / substrate) ──────
def _a_research() -> dict:
    return get_agent("analyst").analyze()


def _a_traces(n: int = 50) -> dict:
    try:
        from omega.tracing import index
        idx = index()
        return {"total_events": idx["total_events"], "state_counts": idx["state_counts"],
                "trace_ids": idx["trace_ids"][:n], "orphan_count": len(idx["orphans"])}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def _a_memory_search(query: str = "", n: int = 8) -> dict:
    try:
        import mempalace_bridge as mp
        if not mp.is_available():
            return {"available": False, "note": "external MemPalace offline"}
        return {"available": True, "query": query, "hits": mp.search(query, n=n)}
    except Exception as e:
        return {"available": False, "error": f"{type(e).__name__}: {e}"}


def _a_plan(intent: str = "") -> dict:
    return get_agent("strategist").plan(intent)


def _a_learn() -> dict:
    out: dict[str, Any] = {}
    try:
        from engine.preference_memory import get_preference_memory  # type: ignore
        pm = get_preference_memory()
        out["preference_memory"] = getattr(pm, "snapshot", lambda: "no snapshot()")()
    except Exception as e:
        out["preference_memory"] = {"error": f"{type(e).__name__}: {e}"}
    return out


def _a_execute(intent: str = "") -> dict:
    return get_agent("executor").execute(intent)


def _a_replay(run_id: str = "") -> dict:
    return get_agent("auditor").audit(run_id)


def _a_summarize(limit: int = 10) -> dict:
    runs = []
    try:
        files = sorted(omega_telemetry_dir().glob("run-*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
        for p in files:
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
                runs.append({"run_id": rec.get("run_id"), "intent": rec.get("intent_text"),
                             "truth": rec.get("overall_truth"), "confidence": rec.get("confidence")})
            except Exception:
                continue
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    return {"total": len(runs),
            "resolved": sum(1 for r in runs if r["truth"] == "RESOLVED"), "runs": runs}


def _a_build_diagnose() -> dict:
    """Build/rebuild room: self-diagnosis + drift + patch proposals (propose-only)."""
    out: dict[str, Any] = {}
    try:
        from omega.evolution import diagnose
        out["diagnosis"] = diagnose()
    except Exception as e:
        out["diagnosis"] = {"error": f"{type(e).__name__}: {e}"}
    try:
        from omega.tracing import run_drift_scan
        out["drift"] = run_drift_scan()
    except Exception as e:
        out["drift"] = {"error": f"{type(e).__name__}: {e}"}
    return out


def _a_build_propose() -> dict:
    try:
        from omega.evolution import propose_patches
        return propose_patches()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


_ROOMS: dict[str, Room] = {
    "research": Room("research", "Research Room", "analyst", "observe",
                     "Read telemetry, synopsis, memory, and traces; surface contradictions.",
                     {"research": _a_research, "traces": _a_traces, "memory_search": _a_memory_search}),
    "plan": Room("plan", "Plan Room", "strategist", "plan",
                 "Decompose an intent into a verified execution DAG (no execution).",
                 {"plan": _a_plan}),
    "learn": Room("learn", "Learn Room", "analyst", "observe",
                  "Inspect learned preference / semantic memory.",
                  {"learn": _a_learn, "research": _a_research}),
    "summarize": Room("summarize", "Summarize Room", "analyst", "observe",
                      "Synthesize recent kernel runs into a digest.",
                      {"summarize": _a_summarize}),
    "execute": Room("execute", "Execute Room", "executor", "execute",
                    "Execute an intent through verified workers (produces real artifacts).",
                    {"execute": _a_execute}),
    "replay": Room("replay", "Replay Room", "auditor", "verify",
                   "Replay-verify a past run: re-hash artifacts, report drift.",
                   {"replay": _a_replay}),
    "build": Room("build", "Build Room", None, "diagnose",
                  "Self-diagnosis, drift scan, and patch proposals (propose-only, no mutation).",
                  {"diagnose": _a_build_diagnose, "propose": _a_build_propose}),
}


def get_room(room_id: str) -> Optional[Room]:
    return _ROOMS.get((room_id or "").lower())


def list_rooms() -> list[dict]:
    return [r.descriptor() for r in _ROOMS.values()]
