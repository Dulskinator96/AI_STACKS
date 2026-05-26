"""service.api — FastAPI core API over the TASKMASTER Ω runtime (BUILD-034).

Thin transport. Every route delegates into omega.* + the build-033 engine —
no orchestration logic, no second source of truth. The packaged exe hosts this
in-process (omega.embedded_server).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import FastAPI, HTTPException                       # noqa: E402
from pydantic import BaseModel                                   # noqa: E402

from omega.orchestrator import get_kernel                        # noqa: E402
from omega.paths import omega_telemetry_dir                      # noqa: E402
from omega.agents import get_agent, list_agents                  # noqa: E402
from omega.rooms import get_room, list_rooms, shared_runtime     # noqa: E402

app = FastAPI(
    title="TASKMASTER Ω — DBOMBCENTRAL Runtime API",
    version="0.2.0-build034",
    description="Deterministic execution kernel for AI_STACK / DBOMBCENTRAL. "
                "Reality-locked: no claim without ledger + on-disk evidence.",
)


class IntentRequest(BaseModel):
    text: str
    dry_run: bool = False


class AgentRequest(BaseModel):
    intent: Optional[str] = None
    run_id: Optional[str] = None


class RoomActionRequest(BaseModel):
    intent: Optional[str] = None
    run_id: Optional[str] = None
    query: Optional[str] = None
    limit: Optional[int] = None
    n: Optional[int] = None


# ── kernel ────────────────────────────────────────────────────────────────
@app.get("/health")
def health() -> dict:
    return get_kernel().cold_boot_self_check()


@app.get("/boot_check")
def boot_check() -> dict:
    return get_kernel().boot_check()


@app.get("/backends")
def backends() -> dict:
    try:
        from engine.tool_fabric import scan_now
        scan = scan_now()
        return {k: {"status": getattr(v, "status", str(v)),
                    "path": getattr(v, "path", None)} for k, v in scan.items()}
    except Exception as e:
        raise HTTPException(503, f"backend scan unavailable: {type(e).__name__}: {e}")


@app.post("/intent")
def run_intent(req: IntentRequest) -> dict:
    return get_kernel().run(req.text, dry_run=req.dry_run).to_dict()


@app.get("/runs")
def list_runs(limit: int = 20) -> dict:
    files = sorted(omega_telemetry_dir().glob("run-*.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    out = []
    for p in files:
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
            out.append({"run_id": rec.get("run_id"), "intent": rec.get("intent_text"),
                        "truth": rec.get("overall_truth"), "confidence": rec.get("confidence")})
        except Exception:
            continue
    return {"count": len(out), "runs": out}


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    p = omega_telemetry_dir() / f"{run_id}.json"
    if not p.is_file():
        raise HTTPException(404, f"no run telemetry for {run_id}")
    return json.loads(p.read_text(encoding="utf-8"))


@app.get("/ledger/{execution_id}")
def ledger(execution_id: str) -> dict:
    try:
        from engine.mem_palace.memory_store import get_mem_palace
        row = get_mem_palace().get_execution(execution_id)
    except Exception as e:
        raise HTTPException(503, f"ledger unavailable: {type(e).__name__}: {e}")
    if row is None:
        raise HTTPException(404, f"no ledger row for {execution_id}")
    return row


@app.get("/synopsis")
def synopsis() -> dict:
    try:
        from engine.system_synopsis import generate_synopsis
        return generate_synopsis()
    except Exception as e:
        raise HTTPException(503, f"synopsis unavailable: {type(e).__name__}: {e}")


# ── trace engine (Section 3) ────────────────────────────────────────────────
@app.get("/traces")
def traces(n: int = 50) -> dict:
    from omega.tracing import index
    idx = index()
    return {"total_events": idx["total_events"], "state_counts": idx["state_counts"],
            "trace_ids": idx["trace_ids"][:n], "orphan_count": len(idx["orphans"])}


@app.get("/traces/{trace_id}")
def trace_lookup(trace_id: str) -> dict:
    from omega.tracing import lookup
    return {"trace_id": trace_id, "events": lookup(trace_id=trace_id)}


@app.get("/drift")
def drift() -> dict:
    from omega.tracing import run_drift_scan
    return run_drift_scan()


# ── evolution / self-diagnosis (Section 5) ──────────────────────────────────
@app.get("/diagnose")
def diagnose() -> dict:
    from omega.evolution import diagnose as _diag
    return _diag()


@app.post("/optimize")
def optimize() -> dict:
    from omega.evolution import run_cycle
    return run_cycle()


# ── pyramid agents ────────────────────────────────────────────────────────
@app.get("/agents")
def agents() -> dict:
    return {"agents": list_agents()}


@app.post("/agents/{role}")
def agent_dispatch(role: str, req: AgentRequest) -> dict:
    agent = get_agent(role)
    if agent is None:
        raise HTTPException(404, f"no agent role '{role}'")
    r = role.lower()
    if r == "strategist":
        if not req.intent:
            raise HTTPException(422, "strategist requires 'intent'")
        return agent.plan(req.intent)
    if r == "analyst":
        return agent.analyze()
    if r == "executor":
        if not req.intent:
            raise HTTPException(422, "executor requires 'intent'")
        return agent.execute(req.intent)
    if r == "auditor":
        if not req.run_id:
            raise HTTPException(422, "auditor requires 'run_id'")
        return agent.audit(req.run_id)
    raise HTTPException(400, f"role '{role}' has no dispatch mapping")


# ── rooms (DBOMBCENTRAL) ──────────────────────────────────────────────────
@app.get("/rooms")
def rooms() -> dict:
    return {"shared_runtime": shared_runtime(), "rooms": list_rooms()}


@app.get("/rooms/{room_id}")
def room_descriptor(room_id: str) -> dict:
    room = get_room(room_id)
    if room is None:
        raise HTTPException(404, f"no room '{room_id}'")
    return room.descriptor()


@app.post("/rooms/{room_id}/{action}")
def room_action(room_id: str, action: str, req: RoomActionRequest) -> dict:
    room = get_room(room_id)
    if room is None:
        raise HTTPException(404, f"no room '{room_id}'")
    kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
    return room.invoke(action, **kwargs)


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8077, log_level="info")


if __name__ == "__main__":
    main()
