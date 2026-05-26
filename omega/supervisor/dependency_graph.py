"""omega.supervisor.dependency_graph — internal import dependency graph.

§4 nervous-system artifact. Read-only AST scan over the verified substrate →
telemetry/dependency_graph.json.

BUILD-035(B) upgrade — SOFT-EDGE TRACKING + CANONICAL CYCLE CLASSIFICATION:
  · every edge is tagged EAGER (module top-level import = real import-time
    coupling) or LAZY (in-function import = deferred, runtime-safe).
  · cycles are found via Tarjan strongly-connected-components (canonical +
    stable, unlike DFS-representative enumeration), then classified:
      HARD = an import-time cycle (SCC in the EAGER subgraph) — real entropy.
      SOFT = a cycle that only closes through lazy edges — runtime-safe.

Composes structural truth NOT covered by engine.system_synopsis. Degrade-safe.
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


def _imports(path: Path, pkg: str) -> list[tuple[str, bool]]:
    """Return [(dotted_target, is_lazy)]. is_lazy=True when the import sits
    inside a function/method body (deferred); False at module/class top-level."""
    out: list[tuple[str, bool]] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return out

    def visit(node: ast.AST, lazy: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, True)                 # body of a function = lazy
            elif isinstance(child, ast.Import):
                for a in child.names:
                    if a.name.split(".")[0] in _ROOTS:
                        out.append((a.name, lazy))
            elif isinstance(child, ast.ImportFrom):
                mod = child.module or ""
                if child.level and child.level > 0:
                    base = pkg.rsplit(".", child.level - 1)[0] if "." in pkg else pkg
                    mod = f"{base}.{mod}" if mod else base
                if mod and mod.split(".")[0] in _ROOTS:
                    out.append((mod, lazy))
                    for a in child.names:
                        out.append((f"{mod}.{a.name}", lazy))
            else:
                visit(child, lazy)

    visit(tree, False)
    return out


def _resolve(target: str, known: set[str]) -> Optional[str]:
    if target in known:
        return target
    parts = target.split(".")
    for i in range(len(parts) - 1, 0, -1):
        cand = ".".join(parts[:i])
        if cand in known:
            return cand
    return None


def _tarjan_scc(edges: dict[str, set[str]]) -> list[list[str]]:
    """Canonical strongly-connected components (Tarjan). Returns components with
    a real cycle (size>1, or a self-loop)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    counter = [0]
    comps: list[list[str]] = []

    def strong(v: str) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in edges.get(v, ()):  # noqa
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1 or (v in edges.get(v, set())):
                comps.append(sorted(comp))

    import sys as _sys
    _old = _sys.getrecursionlimit()
    _sys.setrecursionlimit(max(_old, 5000))
    try:
        for n in list(edges):
            if n not in index:
                strong(n)
    finally:
        _sys.setrecursionlimit(_old)
    return comps


def build_dependency_graph(*, persist: bool = True) -> dict:
    root = project_root()
    mods = _discover(root)
    known = set(mods)

    edges_all: dict[str, set[str]] = {m: set() for m in known}
    edges_eager: dict[str, set[str]] = {m: set() for m in known}
    for m, p in mods.items():
        for tgt, lazy in _imports(p, m):
            r = _resolve(tgt, known)
            if r and r != m:
                edges_all[m].add(r)
                if not lazy:
                    edges_eager[m].add(r)

    fan_out = {m: len(d) for m, d in edges_all.items()}
    fan_in: dict[str, int] = {m: 0 for m in known}
    for deps in edges_all.values():
        for d in deps:
            fan_in[d] = fan_in.get(d, 0) + 1

    hard = _tarjan_scc(edges_eager)         # real import-time cycles
    allc = _tarjan_scc(edges_all)           # structural cycles incl lazy
    hard_sets = [set(c) for c in hard]
    soft = [c for c in allc if set(c) not in hard_sets]

    entrypoints = {m for m in known if m.endswith("__init__")}
    orphans = sorted(m for m in known
                     if fan_in.get(m, 0) == 0 and m not in entrypoints
                     and not m.endswith("__main__"))
    top_fan_in = sorted(fan_in.items(), key=lambda kv: kv[1], reverse=True)[:12]
    top_fan_out = sorted(fan_out.items(), key=lambda kv: kv[1], reverse=True)[:12]

    eager_edge_count = sum(len(v) for v in edges_eager.values())
    graph = {
        "generated_at": time.time(),
        "roots": list(_ROOTS),
        "node_count": len(known),
        "edge_count": sum(len(v) for v in edges_all.values()),
        "eager_edge_count": eager_edge_count,
        "lazy_edge_count": sum(len(v) for v in edges_all.values()) - eager_edge_count,
        "hard_cycle_count": len(hard),          # import-time cycles (the dangerous ones)
        "soft_cycle_count": len(soft),          # lazy-only cycles (runtime-safe)
        "hard_cycles": hard,
        "soft_cycles": soft,
        "fragile_chains_top_fan_in": [{"module": m, "fan_in": n} for m, n in top_fan_in],
        "top_fan_out": [{"module": m, "fan_out": n} for m, n in top_fan_out],
        "orphan_count": len(orphans),
        "orphans": orphans[:50],
        "graph": {m: sorted(d) for m, d in sorted(edges_all.items())},
    }
    if persist:
        try:
            (telemetry_root() / "dependency_graph.json").write_text(
                json.dumps(graph, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass
    return graph
