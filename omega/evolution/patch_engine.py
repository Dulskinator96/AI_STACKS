"""omega.evolution.patch_engine — generate patch PROPOSALS (never apply).

HARD RULE (Section 5): the system MAY detect issues, generate diffs, propose
remediations, create patch plans, and benchmark alternatives. It MAY NOT
self-modify, overwrite verified code, upgrade deps, or mutate runtime. This
module writes proposals to telemetry/evolution/proposals/ ONLY — it never
touches source files.
"""
from __future__ import annotations

import json
import time
import uuid

from omega.paths import telemetry_root
from omega.evolution.self_diagnosis import diagnose
from omega.evolution.repair_planner import plan_repairs


def _proposals_dir():
    d = telemetry_root() / "evolution" / "proposals"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def propose_patches(diagnosis: dict | None = None) -> dict:
    """Produce structured, NON-APPLIED patch proposals for the current issues."""
    diagnosis = diagnosis or diagnose()
    plan = plan_repairs(diagnosis)
    proposals = []
    for step in plan.get("steps", []):
        proposals.append({
            "proposal_id": f"patch-{uuid.uuid4().hex[:8]}",
            "issue_id": step["issue_id"],
            "severity": step["severity"],
            "subsystem": step["subsystem"],
            "proposed_action": step["action"],
            "validation_gate": step["validation_gate"],
            "change_kind": "MANUAL_OR_NEXT_BUILD",
            "applied": False,                 # invariant: always False here
            "auto_apply_forbidden": True,
        })
    record = {
        "proposal_set_id": f"propset-{int(time.time())}-{uuid.uuid4().hex[:6]}",
        "generated_at": time.time(),
        "health": diagnosis.get("health"),
        "proposal_count": len(proposals),
        "mandatory_pipeline": plan.get("mandatory_pipeline"),
        "proposals": proposals,
        "note": "PROPOSE-ONLY. No source modified. Apply only via "
                "diff → validation → rebuild → cold boot → verification → ledger.",
    }
    try:
        path = _proposals_dir() / f"{record['proposal_set_id']}.json"
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        record["persisted_to"] = str(path)
    except Exception:
        record["persisted_to"] = None
    return record
