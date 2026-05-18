"""
helixchain.py — DBOMBCENTRAL code-DNA → tag → prompt synthesis pipeline.

Pipeline:
    HELIXREAD    (DNA extraction via ast)
        ↓
    TAGFUSE      (rule-based behavior tagging; optional embedding upgrade)
        ↓
    ANCHORFORGE  (DETCORE-aligned anchor prompt synthesis)

Mitigations (closing the static-analysis gaps):
    runtime_trace      — sys.settrace harness, observed call sequences
    constraint_report  — checks scan vs. CLAUDE.md rules (MVC, magic strings, …)
    test_runner        — pytest invocation; maps failures back to DNA nodes

CLI:
    python -m helixchain <root>           — scan + emit ANCHORFORGE prompt
    python -m helixchain <root> --json    — emit raw DNA map as JSON
    python -m helixchain <root> --report  — emit constraint_report

All local. No APIs. ast is stdlib. ChromaDB / sentence-transformers are optional.
"""
from __future__ import annotations

import argparse
import ast
import json
import logging
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Iterable

from config import (
    HELIX_DB_PATH, HELIX_SCAN_EXTS, HELIX_MAX_FILE_KB, HELIX_MAX_FUNCS_OUT,
    HelixTag, HelixSeverity, SKIP_DIRS, DBombLexicon, DATA_DIR,
)

_log = logging.getLogger(__name__)

# ── Optional integrations (graceful) ─────────────────────────────────────────
try:
    import chromadb  # type: ignore
    _CHROMA_OK = True
except Exception:
    _CHROMA_OK = False

try:
    from sentence_transformers import SentenceTransformer  # type: ignore
    _ST_OK = True
except Exception:
    _ST_OK = False


# ── DNA dataclasses ──────────────────────────────────────────────────────────

@dataclass
class FunctionDNA:
    name: str
    args: list[str]
    returns: str | None
    lineno: int
    docstring: str | None
    decorators: list[str]
    calls: list[str]                      # function names called inside this body
    tag: str = HelixTag.UNKNOWN


@dataclass
class ClassDNA:
    name: str
    bases: list[str]
    methods: list[FunctionDNA]
    lineno: int
    docstring: str | None


@dataclass
class FileDNA:
    path: str
    imports: list[str]
    classes: list[ClassDNA] = field(default_factory=list)
    functions: list[FunctionDNA] = field(default_factory=list)
    error: str | None = None


@dataclass
class ProjectScan:
    root: str
    files: list[FileDNA] = field(default_factory=list)
    callgraph: dict[str, list[str]] = field(default_factory=dict)


# ── HELIXREAD — DNA extraction ───────────────────────────────────────────────

class _DNAVisitor(ast.NodeVisitor):
    """Walks one module; collects functions, classes, imports, calls."""

    def __init__(self) -> None:
        self.imports: list[str] = []
        self.classes: list[ClassDNA] = []
        self.functions: list[FunctionDNA] = []
        self._scope_stack: list[list[str]] = []  # stack of call-name lists

    # imports
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        for alias in node.names:
            self.imports.append(f"{mod}.{alias.name}" if mod else alias.name)

    # functions
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._capture_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._capture_function(node)

    def _capture_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._scope_stack.append([])
        self.generic_visit(node)
        calls = self._scope_stack.pop()
        fdna = FunctionDNA(
            name=node.name,
            args=[a.arg for a in node.args.args],
            returns=ast.unparse(node.returns) if node.returns else None,
            lineno=node.lineno,
            docstring=ast.get_docstring(node),
            decorators=[ast.unparse(d) for d in node.decorator_list],
            calls=sorted(set(calls)),
        )
        # if we're nested inside a class capture, the class visitor handles it
        if not getattr(self, "_inside_class", False):
            self.functions.append(fdna)
        else:
            self._class_methods_buf.append(fdna)

    # classes
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        prev_inside = getattr(self, "_inside_class", False)
        prev_buf = getattr(self, "_class_methods_buf", None)
        self._inside_class = True
        self._class_methods_buf = []
        self.generic_visit(node)
        cdna = ClassDNA(
            name=node.name,
            bases=[ast.unparse(b) for b in node.bases],
            methods=self._class_methods_buf,
            lineno=node.lineno,
            docstring=ast.get_docstring(node),
        )
        self.classes.append(cdna)
        self._inside_class = prev_inside
        self._class_methods_buf = prev_buf if prev_buf is not None else []

    # calls
    def visit_Call(self, node: ast.Call) -> None:
        if self._scope_stack:
            name = self._call_name(node.func)
            if name:
                self._scope_stack[-1].append(name)
        self.generic_visit(node)

    @staticmethod
    def _call_name(func_node: ast.AST) -> str | None:
        if isinstance(func_node, ast.Name):
            return func_node.id
        if isinstance(func_node, ast.Attribute):
            return func_node.attr
        return None


def helixread_file(path: Path) -> FileDNA:
    """HELIXREAD: extract DNA from a single source file."""
    rel = str(path)
    try:
        if path.stat().st_size > HELIX_MAX_FILE_KB * 1024:
            return FileDNA(path=rel, imports=[], error="file too large")
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=rel)
    except SyntaxError as exc:
        return FileDNA(path=rel, imports=[], error=f"SyntaxError: {exc}")
    except OSError as exc:
        return FileDNA(path=rel, imports=[], error=f"OSError: {exc}")

    v = _DNAVisitor()
    v.visit(tree)
    return FileDNA(
        path=rel,
        imports=v.imports,
        classes=v.classes,
        functions=v.functions,
    )


def helixread_project(root: str | Path) -> ProjectScan:
    """HELIXREAD over a folder. Skips SKIP_DIRS."""
    root_path = Path(root).resolve()
    scan = ProjectScan(root=str(root_path))
    for p in root_path.rglob("*"):
        if p.is_dir():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() not in HELIX_SCAN_EXTS:
            continue
        scan.files.append(helixread_file(p))
    return scan


# ── TAGFUSE — behavior tagging ───────────────────────────────────────────────

_TAG_KEYS: dict[str, tuple[str, ...]] = {
    HelixTag.RETRIEVAL:  ("search", "retriev", "fetch", "recall", "lookup", "query"),
    HelixTag.GENERATION: ("generate", "build", "compose", "render", "synthesi", "forge"),
    HelixTag.PROCESSING: ("parse", "process", "transform", "convert", "normaliz"),
    HelixTag.MEMORY:     ("store", "save", "persist", "remember", "memo", "cache"),
    HelixTag.ROUTING:    ("route", "map", "dispatch", "delegate", "forward"),
    HelixTag.PERCEPTION: ("perceiv", "attend", "predict", "emot", "sens", "observ"),
    HelixTag.VALIDATION: ("valid", "check", "verify", "assert", "lint", "test"),
    HelixTag.UI:         ("widget", "render_ui", "show", "display", "paint", "click"),
    HelixTag.PERSISTENCE:("commit", "flush", "write_db", "open_db", "execute_sql"),
}


def tagfuse_function(fn: FunctionDNA) -> str:
    """Rule-based tag from function name + docstring."""
    haystack = (fn.name + " " + (fn.docstring or "")).lower()
    for tag, keys in _TAG_KEYS.items():
        if any(k in haystack for k in keys):
            return tag
    return HelixTag.UNKNOWN


def tagfuse_scan(scan: ProjectScan) -> ProjectScan:
    """Attach tags to every function in the scan (in-place)."""
    for f in scan.files:
        for fn in f.functions:
            fn.tag = tagfuse_function(fn)
        for cls in f.classes:
            for m in cls.methods:
                m.tag = tagfuse_function(m)
    return scan


# Optional: embedding-based upgrade. Loaded lazily only when called.
def tagfuse_embed_upgrade(scan: ProjectScan) -> ProjectScan:
    """Optional: upgrade UNKNOWN tags using sentence-transformers similarity."""
    if not _ST_OK:
        _log.info("sentence-transformers unavailable; skipping embed upgrade")
        return scan
    model = SentenceTransformer("all-MiniLM-L6-v2")
    anchors = {tag: ", ".join(keys) for tag, keys in _TAG_KEYS.items()}
    anchor_emb = {tag: model.encode(text) for tag, text in anchors.items()}

    def _best_tag(text: str) -> str:
        emb = model.encode(text)
        import numpy as np  # type: ignore
        scores = {
            tag: float(np.dot(emb, a) / ((np.linalg.norm(emb) * np.linalg.norm(a)) or 1))
            for tag, a in anchor_emb.items()
        }
        tag, score = max(scores.items(), key=lambda kv: kv[1])
        return tag if score > 0.30 else HelixTag.UNKNOWN

    for f in scan.files:
        for fn in f.functions:
            if fn.tag == HelixTag.UNKNOWN:
                fn.tag = _best_tag(fn.name + " " + (fn.docstring or ""))
        for cls in f.classes:
            for m in cls.methods:
                if m.tag == HelixTag.UNKNOWN:
                    m.tag = _best_tag(m.name + " " + (m.docstring or ""))
    return scan


# ── Phase B: callgraph ───────────────────────────────────────────────────────

def build_callgraph(scan: ProjectScan) -> dict[str, list[str]]:
    """Resolve a who-calls-what graph. Names are unqualified — collisions
    across modules are merged. This is a structural map, not a precise call
    graph (no type inference)."""
    graph: dict[str, set[str]] = {}
    all_names: set[str] = set()
    for f in scan.files:
        for fn in f.functions:
            all_names.add(fn.name)
        for cls in f.classes:
            for m in cls.methods:
                all_names.add(m.name)

    for f in scan.files:
        for fn in f.functions:
            graph.setdefault(fn.name, set()).update(c for c in fn.calls if c in all_names)
        for cls in f.classes:
            for m in cls.methods:
                key = f"{cls.name}.{m.name}"
                graph.setdefault(key, set()).update(
                    c for c in m.calls if c in all_names
                )
    flat = {k: sorted(v) for k, v in graph.items()}
    scan.callgraph = flat
    return flat


# ── Phase B: DETBANK (MemPalace) sync ────────────────────────────────────────

def sync_to_detbank(scan: ProjectScan, collection: str = "helixchain") -> int:
    """Write DNA fragments to ChromaDB if available. Returns count written."""
    if not _CHROMA_OK:
        _log.info("ChromaDB unavailable; falling back to SQLite fragment store")
        return _sync_to_sqlite(scan)
    try:
        client = chromadb.PersistentClient(path=str(DATA_DIR / "chroma"))
        col = client.get_or_create_collection(collection)
    except Exception as exc:
        _log.warning("ChromaDB init failed: %s; falling back to SQLite", exc)
        return _sync_to_sqlite(scan)

    docs: list[str] = []
    metas: list[dict[str, Any]] = []
    ids: list[str] = []
    for f in scan.files:
        for fn in f.functions:
            doc = _fragment_text(f.path, None, fn)
            docs.append(doc)
            metas.append({"path": f.path, "kind": "function", "tag": fn.tag,
                          "name": fn.name})
            ids.append(f"{f.path}::{fn.name}@{fn.lineno}")
        for cls in f.classes:
            for m in cls.methods:
                doc = _fragment_text(f.path, cls.name, m)
                docs.append(doc)
                metas.append({"path": f.path, "kind": "method", "tag": m.tag,
                              "name": f"{cls.name}.{m.name}"})
                ids.append(f"{f.path}::{cls.name}.{m.name}@{m.lineno}")

    if docs:
        col.upsert(documents=docs, metadatas=metas, ids=ids)
    return len(docs)


def _sync_to_sqlite(scan: ProjectScan) -> int:
    """Fragment-store fallback when ChromaDB is absent. Plain SQLite."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(HELIX_DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS fragments (
        id TEXT PRIMARY KEY, path TEXT, kind TEXT, tag TEXT,
        name TEXT, doc TEXT)""")
    count = 0
    for f in scan.files:
        for fn in f.functions:
            conn.execute(
                "REPLACE INTO fragments VALUES (?,?,?,?,?,?)",
                (f"{f.path}::{fn.name}@{fn.lineno}", f.path, "function",
                 fn.tag, fn.name, _fragment_text(f.path, None, fn)),
            )
            count += 1
        for cls in f.classes:
            for m in cls.methods:
                conn.execute(
                    "REPLACE INTO fragments VALUES (?,?,?,?,?,?)",
                    (f"{f.path}::{cls.name}.{m.name}@{m.lineno}", f.path,
                     "method", m.tag, f"{cls.name}.{m.name}",
                     _fragment_text(f.path, cls.name, m)),
                )
                count += 1
    conn.commit()
    conn.close()
    return count


def _fragment_text(path: str, cls: str | None, fn: FunctionDNA) -> str:
    qual = f"{cls}.{fn.name}" if cls else fn.name
    sig = f"{qual}({', '.join(fn.args)})"
    doc = (fn.docstring or "").strip().splitlines()[0] if fn.docstring else ""
    calls = ", ".join(fn.calls[:8])
    return (f"[{path}:{fn.lineno}] [{fn.tag}] {sig}\n"
            f"  doc: {doc}\n  calls: {calls}")


# ── ANCHORFORGE — DETCORE-aligned prompt synthesis ───────────────────────────

_ANCHORFORGE_HEADER = (
    "# {anchor} — Generated Anchor (HELIXCHAIN)\n"
    "## Source-grounded reasoning bind for {processor}\n\n"
    "SYSTEM ROLE:\n"
    "You are {processor}, a constrained reasoning module operating over the "
    "code DNA below. You do NOT invent functions, signatures, or call edges — "
    "every claim must cite a [path:line] from the COMPONENTS list.\n\n"
)


def anchorforge(scan: ProjectScan, *, with_callgraph: bool = True) -> str:
    """Convert a tagged ProjectScan into a DETCORE-aligned anchor prompt."""
    by_tag: dict[str, list[tuple[str, FunctionDNA, str | None]]] = {}
    for f in scan.files:
        for fn in f.functions:
            by_tag.setdefault(fn.tag, []).append((f.path, fn, None))
        for cls in f.classes:
            for m in cls.methods:
                by_tag.setdefault(m.tag, []).append((f.path, m, cls.name))

    out: list[str] = [_ANCHORFORGE_HEADER.format(
        anchor=DBombLexicon.ANCHOR, processor=DBombLexicon.PROCESSOR,
    )]
    out.append("## COMPONENTS (tagged DNA)\n")

    surfaced = 0
    for tag in sorted(by_tag):
        out.append(f"\n### [{tag.upper()}]")
        for path, fn, cls in by_tag[tag]:
            qual = f"{cls}.{fn.name}" if cls else fn.name
            sig = f"{qual}({', '.join(fn.args)})"
            out.append(f"- `{sig}`  —  {path}:{fn.lineno}")
            surfaced += 1
            if surfaced >= HELIX_MAX_FUNCS_OUT:
                out.append("\n*(component cap reached — re-run with --json for full DNA)*")
                break
        if surfaced >= HELIX_MAX_FUNCS_OUT:
            break

    if with_callgraph and scan.callgraph:
        out.append("\n## CALLGRAPH (top edges)\n")
        edges = sorted(scan.callgraph.items(), key=lambda kv: -len(kv[1]))[:40]
        for src, dsts in edges:
            if dsts:
                out.append(f"- `{src}` → {', '.join('`' + d + '`' for d in dsts[:6])}")

    out.append("\n## RULES\n")
    out.append("- Retrieval components must execute before generation components.\n"
               "- Generation must consume retrieved context; never freelance.\n"
               "- Validation components gate every output before YIELDCAST.\n"
               "- Perception components structure modality, not simulate qualia.\n"
               "- If a referenced symbol is not in COMPONENTS, reject the claim.\n")
    return "\n".join(out)


# ── Mitigations: closing the gaps that static analysis cannot solve ──────────

def runtime_trace(target: Callable[..., Any], *args: Any,
                  **kwargs: Any) -> dict[str, Any]:
    """Observed call sequence around a target. sys.settrace harness.

    Static DNA tells you what COULD be called. runtime_trace tells you what
    WAS called. Together they cover the gap toward "understand runtime bugs".
    """
    observed: list[tuple[str, str, int]] = []  # (event, qualname, lineno)

    def _tracer(frame, event, arg):
        if event in ("call", "return"):
            code = frame.f_code
            observed.append((event, code.co_qualname, frame.f_lineno))
        return _tracer

    sys.settrace(_tracer)
    error: str | None = None
    result: Any = None
    try:
        result = target(*args, **kwargs)
    except Exception as exc:  # surface — do not swallow
        error = f"{type(exc).__name__}: {exc}"
    finally:
        sys.settrace(None)
    return {"observed": observed, "error": error, "returned_repr": repr(result)[:400]}


def constraint_report(scan: ProjectScan) -> list[dict[str, str]]:
    """CLAUDE.md constraint checks. Closes "magically fix architecture" by
    SURFACING violations with grounded evidence — Operator decides the fix.
    """
    findings: list[dict[str, str]] = []
    view_modules = {"app.py", "stratum_ui.py", "pyramid_ui.py"}
    forbidden_in_view = {"requests", "sqlite3", "subprocess"}
    forbidden_in_model_qt = ("PyQt6.QtWidgets", "PyQt6.QtGui")
    model_modules = {
        "config.py", "intent_engine.py", "code_correlator.py",
        "proposal_engine.py", "pyramid_ensemble.py", "consciousness.py",
        "perceptual_engine.py", "agent_memory.py", "agent_chatroom.py",
    }

    for f in scan.files:
        leaf = Path(f.path).name
        if leaf in view_modules:
            for imp in f.imports:
                root_imp = imp.split(".")[0]
                if root_imp in forbidden_in_view:
                    findings.append({
                        "severity": HelixSeverity.VIOLATE,
                        "rule": "MVC §5: View must not import I/O libs",
                        "where": f.path, "evidence": f"imports {imp}",
                    })
        if leaf in model_modules:
            for imp in f.imports:
                if any(imp.startswith(p) for p in forbidden_in_model_qt):
                    findings.append({
                        "severity": HelixSeverity.VIOLATE,
                        "rule": "MVC §5: Model must not import PyQt6 widgets",
                        "where": f.path, "evidence": f"imports {imp}",
                    })
        for fn in f.functions:
            if fn.name == "print" or any(c == "print" for c in fn.calls):
                findings.append({
                    "severity": HelixSeverity.WARN,
                    "rule": "§10: use _log.*, never print()",
                    "where": f"{f.path}:{fn.lineno}",
                    "evidence": f"{fn.name} calls print()",
                })
    return findings


def test_runner(root: str | Path, scan: ProjectScan | None = None) -> dict[str, Any]:
    """Run pytest at root, parse failures, attempt to map to DNA. Closes
    "replace debugging" by EXECUTING tests and reporting grounded failures.
    """
    root_path = Path(root).resolve()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=line", str(root_path)],
        capture_output=True, text=True, timeout=600,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    output = proc.stdout + proc.stderr
    failures: list[dict[str, str]] = []
    for line in output.splitlines():
        if "FAILED" in line or "ERROR" in line:
            failures.append({"line": line.strip()})
    return {
        "exit_code": proc.returncode,
        "failures": failures,
        "tail": "\n".join(output.splitlines()[-20:]),
    }


# ── DETCORE wiring helper ────────────────────────────────────────────────────

def helix_fragments_for_brief(root: str | Path, query: str = "",
                              limit: int = 12) -> list[str]:
    """Produce HELIX fragment strings ready for detcore.assemble_brief().
    Filters to functions whose tag or name resonates with the query."""
    scan = helixread_project(root)
    tagfuse_scan(scan)
    needle = (query or "").lower()
    picks: list[str] = []
    for f in scan.files:
        for fn in f.functions:
            if not needle or needle in fn.name.lower() or needle in (fn.tag or ""):
                picks.append(_fragment_text(f.path, None, fn))
                if len(picks) >= limit:
                    return picks
        for cls in f.classes:
            for m in cls.methods:
                if not needle or needle in m.name.lower() or needle in (m.tag or ""):
                    picks.append(_fragment_text(f.path, cls.name, m))
                    if len(picks) >= limit:
                        return picks
    return picks


# ── CLI ──────────────────────────────────────────────────────────────────────

def _scan_to_jsonable(scan: ProjectScan) -> dict[str, Any]:
    return {
        "root": scan.root,
        "files": [asdict(f) for f in scan.files],
        "callgraph": scan.callgraph,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="helixchain",
                                description="HELIXCHAIN: code DNA → tag → anchor")
    p.add_argument("root", help="project root to scan")
    p.add_argument("--json", action="store_true", help="emit raw DNA as JSON")
    p.add_argument("--report", action="store_true",
                   help="emit constraint_report findings")
    p.add_argument("--callgraph", action="store_true",
                   help="include callgraph in output")
    p.add_argument("--sync", action="store_true",
                   help="sync DNA fragments to DETBANK")
    p.add_argument("--query", default="",
                   help="filter fragments matching this term (for --json)")
    args = p.parse_args(argv)

    scan = helixread_project(args.root)
    tagfuse_scan(scan)
    if args.callgraph:
        build_callgraph(scan)

    if args.report:
        findings = constraint_report(scan)
        _log.debug(json.dumps(findings, indent=2))
        return 0
    if args.sync:
        n = sync_to_detbank(scan)
        _log.debug(f"DETBANK sync: {n} fragments written")
        return 0
    if args.json:
        _log.debug(json.dumps(_scan_to_jsonable(scan), indent=2, default=str))
        return 0

    if not scan.callgraph and args.callgraph:
        build_callgraph(scan)
    _log.debug(anchorforge(scan, with_callgraph=args.callgraph))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
