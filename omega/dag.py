"""omega.dag — DAG model + compiler.

Transforms a collapsed intent into a directed acyclic graph of execution
tasks. Provides cycle detection and a deterministic topological order. Realm
inference comes from engine.intent_cortex (the EnrichedIntent) — omega NEVER
invents realms the planner did not derive (Section 2: omega NEVER invents plans).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from omega.contracts import KernelTask, new_task_id

_log = logging.getLogger(__name__)

# Realms with a registered worker in engine/workers/__init__.py.
_KNOWN_REALMS = {"image", "video", "audio", "game", "simulation", "code", "cast"}


@dataclass
class DAGNode:
    task:       KernelTask
    visited:    bool = False
    in_stack:   bool = False

    @property
    def task_id(self) -> str:
        return self.task.task_id

    @property
    def depends_on(self) -> list[str]:
        return self.task.depends_on


class KernelDAG:
    """A directed acyclic graph of KernelTasks. Validates acyclicity and yields
    a deterministic execution order."""

    def __init__(self) -> None:
        self._nodes: dict[str, DAGNode] = {}

    def add_task(self, task: KernelTask) -> None:
        if task.task_id in self._nodes:
            raise ValueError(f"duplicate task_id: {task.task_id}")
        self._nodes[task.task_id] = DAGNode(task=task)

    @property
    def tasks(self) -> list[KernelTask]:
        return [n.task for n in self._nodes.values()]

    def __len__(self) -> int:
        return len(self._nodes)

    def validate(self) -> tuple[bool, str]:
        for n in self._nodes.values():
            for dep in n.depends_on:
                if dep not in self._nodes:
                    return False, f"task {n.task_id} depends on unknown task {dep}"
        for n in self._nodes.values():
            n.visited = False
            n.in_stack = False
        cyc = self._find_cycle()
        if cyc:
            return False, f"cycle detected: {' -> '.join(cyc)}"
        return True, "acyclic"

    def _find_cycle(self) -> Optional[list[str]]:
        path: list[str] = []

        def dfs(tid: str) -> Optional[list[str]]:
            node = self._nodes[tid]
            node.visited = True
            node.in_stack = True
            path.append(tid)
            for dep in node.depends_on:
                dn = self._nodes[dep]
                if dn.in_stack:
                    return path[path.index(dep):] + [dep]
                if not dn.visited:
                    res = dfs(dep)
                    if res:
                        return res
            node.in_stack = False
            path.pop()
            return None

        for n in self._nodes.values():
            if not n.visited:
                res = dfs(n.task_id)
                if res:
                    return res
        return None

    def topological_order(self) -> list[KernelTask]:
        indeg: dict[str, int] = {tid: 0 for tid in self._nodes}
        for n in self._nodes.values():
            for _dep in n.depends_on:
                indeg[n.task_id] += 1
        ready = [tid for tid in self._nodes if indeg[tid] == 0]
        order: list[KernelTask] = []
        while ready:
            tid = ready.pop(0)
            order.append(self._nodes[tid].task)
            for other in self._nodes.values():
                if tid in other.depends_on:
                    indeg[other.task_id] -= 1
                    if indeg[other.task_id] == 0:
                        ready.append(other.task_id)
        return order

    def to_list(self) -> list[dict]:
        return [t.to_dict() for t in self.topological_order()]


def plan_realms(enriched: Any) -> list[str]:
    realm = getattr(enriched, "realm", None) or getattr(enriched, "target_pipeline", None)
    if isinstance(realm, str):
        realm = realm.lower().strip()
    realms: list[str] = []
    if realm in _KNOWN_REALMS:
        realms.append(realm)
    return realms


def compile_dag(enriched: Any, *, fallback_realm: Optional[str] = None) -> KernelDAG:
    """Compile an EnrichedIntent into a KernelDAG. If no known realm derives, a
    single node still carries the (unknown) realm so the orchestrator records a
    truthful BLOCKED — never a silent drop or a fabricated realm."""
    text = getattr(enriched, "raw_text", "") or str(enriched)
    realms = plan_realms(enriched)
    if not realms:
        realms = [fallback_realm or (getattr(enriched, "realm", None) or "unknown")]

    dag = KernelDAG()
    for idx, realm in enumerate(realms):
        params = {
            "medium":   getattr(enriched, "medium", None),
            "ambition": getattr(enriched, "ambition", None),
            "style":    getattr(enriched, "style", None),
            "known_realm": realm in _KNOWN_REALMS,
        }
        task = KernelTask(
            task_id=new_task_id(realm, idx),
            realm=realm,
            intent_text=text,
            depends_on=[],
            params=params,
        )
        dag.add_task(task)
    return dag
