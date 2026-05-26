"""omega.evolution.optimization_cycles — controlled improvement loop.

Orchestrates: diagnose → repair plan → patch proposal → (STOP at rebuild gate).
The cycle NEVER applies changes. It records a cycle artifact under
telemetry/evolution/cycles/ documenting what would be done and what gate must
be crossed (rebuild + cold boot + verification) before anything changes.
"""
from __future__ import annotations

import json
import time
import uuid

from omega.paths import telemetry_root
from omega.evolution.self_diagnosis import diagnose
from omega.evolution.repair_planner import plan_repairs
from omega.evolution.patch_engine import propose_patches


def _cycles_dir():
    d = telemetry_root() / "evolution" / "cycles"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def run_cycle() -> dict:
    """Run one full propose-only optimization cycle and persist the record."""
    diagnosis = diagnose()
    plan = plan_repairs(diagnosis)
    proposals = propose_patches(diagnosis)

    needs_action = diagnosis.get("issue_count", 0) > 0
    record = {
        "cycle_id": f"cycle-{int(time.time())}-{uuid.uuid4().hex[:6]}",
        "ran_at": time.time(),
        "health": diagnosis.get("health"),
        "issue_count": diagnosis.get("issue_count", 0),
        "by_severity": diagnosis.get("by_severity"),
        "repair_steps": plan.get("total_steps"),
        "proposal_set_id": proposals.get("proposal_set_id"),
        "verdict": "REBUILD_REQUIRED" if needs_action else "NO_ACTION_NEEDED",
        "gate": ["diff_proposal", "validation", "rebuild", "cold_boot",
                 "verification", "ledger_evidence"],
        "applied": False,                     # invariant
        "self_mutation": "FORBIDDEN",
    }
    try:
        path = _cycles_dir() / f"{record['cycle_id']}.json"
        path.write_text(json.dumps({**record, "diagnosis": diagnosis,
                                    "plan": plan, "proposals": proposals},
                                   indent=2), encoding="utf-8")
        record["persisted_to"] = str(path)
    except Exception:
        record["persisted_to"] = None
    return record
