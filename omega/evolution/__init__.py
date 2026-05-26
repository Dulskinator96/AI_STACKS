"""omega.evolution — autonomous optimization substrate (BUILD-034 Section 5).

Detect → propose → (rebuild gate). NEVER self-modifies, overwrites verified
code, upgrades deps, or mutates runtime. All improvement flows through:
diagnosis → diff proposal → validation → rebuild → cold boot → verification →
ledger evidence.
"""
from omega.evolution.runtime_inspector import inspect_runtime
from omega.evolution.dependency_health import check_dependencies
from omega.evolution.self_diagnosis import diagnose
from omega.evolution.repair_planner import plan_repairs
from omega.evolution.patch_engine import propose_patches
from omega.evolution.optimization_cycles import run_cycle

__all__ = [
    "inspect_runtime", "check_dependencies", "diagnose",
    "plan_repairs", "propose_patches", "run_cycle",
]
