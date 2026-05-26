"""omega.supervisor — BUILD_SUPERVISOR (BUILD-035 §9).

Supervised build/runtime lifecycle: orphan + stale-state cleanup, environment
verification, deterministic build orchestration, frozen verification, drift /
regression comparison, and crash-bundle generation. Compresses the dev cycle
while preserving the reality law (nothing PASSes without real execution +
artifact + hash + ledger + survival).

CLI: python -m omega.supervisor {status|clean|env|build|verify|cycle}
"""
from omega.supervisor.hygiene import (
    scan_processes, clean_processes, scan_stale_telemetry,
)
from omega.supervisor.environment import verify_environment
from omega.supervisor.build_supervisor import BuildSupervisor, get_supervisor

__all__ = [
    "scan_processes", "clean_processes", "scan_stale_telemetry",
    "verify_environment", "BuildSupervisor", "get_supervisor",
]
