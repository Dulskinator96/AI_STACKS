"""TASKMASTER Ω — execution / orchestration / verification layer for AI_STACK.

Canonical (BUILD-034): the `kernel/` package remains the deterministic PLAN
compiler; `omega/` is the deterministic EXECUTION orchestrator. They are
complementary layers, not duplicates.

Authority chain:
    USER → kernel.intent_compiler → omega.orchestrator → engine workers
         → artifact_validator → truth ledger → telemetry traces → rooms ui

REALITY LAW: only omega may collapse PARTIAL → RESOLVED, and only after a real
file exists, hash verified, backend READY, and a ledger execution_id exists.

Public surface:
    from omega import TaskmasterKernel, get_kernel
"""
from omega.contracts import (
    TruthState, ExternalState, TaskState,
    KernelTask, TaskResult, KernelRunResult,
    external_for, sha256_file,
)
from omega.dag import DAGNode, KernelDAG, compile_dag
from omega.orchestrator import TaskmasterKernel, get_kernel

__all__ = [
    "TruthState", "ExternalState", "TaskState",
    "KernelTask", "TaskResult", "KernelRunResult",
    "external_for", "sha256_file",
    "DAGNode", "KernelDAG", "compile_dag",
    "TaskmasterKernel", "get_kernel",
]

__version__ = "0.2.0-taskmaster-omega-build034"
