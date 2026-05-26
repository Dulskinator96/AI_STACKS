"""omega.evolution.repair_planner — diagnosis → ordered repair plan.

Read-only / propose-only. Turns ranked issues into a sequenced remediation plan
with explicit validation gates. Produces NO code changes — it plans the route
through diagnosis → diff → validation → rebuild → cold boot → verification.
"""
from __future__ import annotations

# Maps an issue kind/subsystem pattern to a repair strategy. Strategies are
# advisory: they tell the operator (or a later patch cycle) WHAT to do, with the
# mandatory validation gate, never executing it.
_STRATEGY = {
    "duplicated_package": ("rename one package to remove ambiguity",
                           "rebuild + frozen import check"),
    "dangling_lineage":   ("make the producing module write under a frozen-aware "
                           "telemetry dir (not _MEIPASS)", "frozen run + post-exit replay"),
    "unresolved_worker":  ("register/repair the realm worker", "smoke a realm intent"),
    "import_failure":     ("resolve the import error / missing dependency",
                           "import probe + cold boot"),
    "circular_import":    ("break the import cycle (lazy import / move shared types)",
                           "import probe"),
    "subsystem":          ("repair the failing subsystem import", "cold boot self check"),
    "trace.failures":     ("fix the originating file/line surfaced by the failure trace",
                           "re-run the failing intent"),
}


def _strategy_for(issue: dict) -> tuple[str, str]:
    for key, strat in _STRATEGY.items():
        if issue["id"].startswith(key) or issue["subsystem"] == key \
                or issue.get("symptom", "").startswith(key):
            return strat
    return ("manual investigation required", "full validation cycle")


def plan_repairs(diagnosis: dict) -> dict:
    steps = []
    for order, issue in enumerate(diagnosis.get("issues", []), start=1):
        action, validation = _strategy_for(issue)
        steps.append({
            "order": order,
            "issue_id": issue["id"],
            "severity": issue["severity"],
            "subsystem": issue["subsystem"],
            "action": action,
            "validation_gate": validation,
            "risk": "HIGH" if issue["severity"] in ("CRITICAL", "HIGH") else "LOW",
            "auto_apply": False,            # NEVER — rebuild-only doctrine
        })
    return {
        "health": diagnosis.get("health"),
        "total_steps": len(steps),
        "mandatory_pipeline": ["diagnosis", "diff_proposal", "validation",
                               "rebuild", "cold_boot", "verification", "ledger_evidence"],
        "steps": steps,
    }
