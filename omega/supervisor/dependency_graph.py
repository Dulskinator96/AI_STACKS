"""omega.supervisor.dependency_graph — internal import dependency graph.

§4 nervous-system artifact. Read-only AST scan over the verified substrate →
telemetry/dependency_graph.json. Reveals the "most fragile dependency chain"
(Phase-2 leverage metric), import cycles (entropy/fragility), and per-module
fan-in/fan-out so every future patch can assess blast radius before editing.

Composes structural truth NOT covered by engine.system_synopsis (which checks
per-file AST validity, not the inter-module edge graph). Degrade-safe.
"""
from __future__ import annotations

import ast
import json
import time
from pathlib import Path
from typing import Optional

from omega.paths import project_root, telemetry_root

_ROOTS = ("omega", "engine", "service", "runtime", "truth", "kernel")
_SKIP = {"__pycache__", "build", "releases", "telemetry", "dist", ".git"}


def _module_name(path: Path, root: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _discover(root: Path) -> dict[str, Path]:
    mods: dict[str, Path] = {}
    for base in _ROOTS:
        d = root / base
        if not d.is_dir():
            continue
        for p in d.rglob("*.py"):
            if any(s in p.parts for s in _SKIP):
                continue
            mods[_module_name(p, root)] = p
    return mods


def _imports(path: Path, pkg: str) -> set[str]:
    """Internal import targets (dotted) from one file."""
    out: set[str] = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in _ROOTS:
                    out.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level and node.level > 0:           # relative import
                base = pkg.rsplit(".", node.level - 1)[0] if "." in pkg else pkg
                mod = f"{base}.{mod}" if mod else base
            if mod and mod.split(".")[0] in _ROOTS:
                out.add(mod)
                for a in node.names:                     # from pkg import submodule
                    out.add(f"{mod}.{a.name}")
    return out


def _resolve(target: str, known: set[str]) -> Optional[str]:
    """Map an import target to the known module it best matches (exact, then
    longest prefix). Returns None if it resolves outside the discovered set."""
    if target in known:
        return target
    parts = target.split(".")
    for i in range(len(parts) - 1, 0, -1):
        cand = ".".join(parts[:i])
        if cand in known:
            return cand
    return None


def _find_cycles(edges: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan-free DFS cycle detection; returns distinct cycles (best-effort)."""
    cycles: list[list[str]] = []
    state: dict[str, int] = {}   # 0=unvisited,1=in-stack,2=done
    stack: list[str] = []

    def dfs(n: str) -> None:
        state[n] = 1
        stack.append(n)
        for m in edges.get(n, ()):
            if state.get(m, 0) == 0:
                dfs(m)
            elif state.get(m) == 1 and m in stack:
                cyc = stack[stack.index(m):] + [m]
                if cyc not in cycles:
                    cycles.append(cyc)
        stack.pop()
        state[n] = 2

    for n in list(edges):
        if state.get(n, 0) == 0:
            dfs(n)
    return cycles[:25]


def build_dependency_graph(*, persist: bool = True) -> dict:
    root = project_root()
    mods = _discover(root)
    known = set(mods)

    edges: dict[str, set[str]] = {m: set() for m in known}
    for m, p in mods.items():
        for tgt in _imports(p, m):
            r = _resolve(tgt, known)
            if r and r != m:
                edges[m].add(r)

    fan_out = {m: len(deps) for m, deps in edges.items()}
    fan_in: dict[str, int] = {m: 0 for m in known}
    for deps in edges.values():
        for d in deps:
            fan_in[d] = fan_in.get(d, 0) + 1

    cycles = _find_cycles(edges)
    entrypoints = {m for m in known if m.endswith("__main__") or m.endswith("__init__")}
    orphans = sorted(m for m in known
                     if fan_in.get(m, 0) == 0 and m not in entrypoints
                     and not m.endswith("__main__"))

    top_fan_in = sorted(fan_in.items(), key=lambda kv: kv[1], reverse=True)[:12]
    top_fan_out = sorted(fan_out.items(), key=lambda kv: kv[1], reverse=True)[:12]

    graph = {
        "generated_at": time.time(),
        "roots": list(_ROOTS),
        "node_count": len(known),
        "edge_count": sum(len(v) for v in edges.values()),
        "cycle_count": len(cycles),
        "cycles": [c for c in cycles],
        "fragile_chains_top_fan_in": [{"module": m, "fan_in": n} for m, n in top_fan_in],
        "top_fan_out": [{"module": m, "fan_out": n} for m, n in top_fan_out],
        "orphan_count": len(orphans),
        "orphans": orphans[:50],
        "graph": {m: sorted(d) for m, d in sorted(edges.items())},
    }
    if persist:
        try:
            (telemetry_root() / "dependency_graph.json").write_text(
                json.dumps(graph, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass
    return graph
