"""
code_correlator.py — Intent-topology driven code navigation.

Each IntentClass has a predefined topology: which file patterns to open,
which AST node types to surface, and which symbol kinds are relevant.
This is DETERMINISTIC — no embeddings, no keyword search.

Pipeline position: intent_engine → [CodeCorrelator] → proposal_engine
"""
from __future__ import annotations

import ast
import glob
import os
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config import ASTKind, SKIP_DIRS
from intent_engine import IntentClass, IntentResult, IntentTarget

# ── Topology definitions ──────────────────────────────────────────────────────

@dataclass
class IntentTopology:
    """Defines what to pull from the codebase for a given intent."""
    # glob patterns relative to project root (ordered by priority)
    file_patterns:   list[str]
    # AST node types to extract (e.g. "FunctionDef", "ClassDef", "Import")
    symbol_types:    list[str]
    # max files to load fully (rest are header-only)
    max_full_files:  int = 4
    # max lines per file for full content (avoid flooding proposal engine)
    max_lines:       int = 300
    # whether to include imports section
    include_imports: bool = True
    # whether to include docstrings
    include_docs:    bool = True


_TOPOLOGIES: dict[IntentClass, IntentTopology] = {
    IntentClass.CREATE: IntentTopology(
        file_patterns   = ["*.py", "core/*.py", "**/__init__.py"],
        symbol_types    = [ASTKind.CLASS, ASTKind.FUNCTION, ASTKind.IMPORT, ASTKind.IMPORT_FROM],
        max_full_files  = 2,
        include_imports = True,
        include_docs    = True,
    ),
    IntentClass.MODIFY: IntentTopology(
        file_patterns   = ["*.py", "core/*.py"],
        symbol_types    = [ASTKind.FUNCTION, ASTKind.ASYNC_FUNCTION, ASTKind.CLASS],
        max_full_files  = 3,
        max_lines       = 400,
        include_imports = False,
        include_docs    = True,
    ),
    IntentClass.DEBUG: IntentTopology(
        file_patterns   = ["*.py", "**/*.py"],
        symbol_types    = [ASTKind.FUNCTION, ASTKind.ASYNC_FUNCTION,
                           ASTKind.TRY, ASTKind.EXCEPT, ASTKind.RAISE],
        max_full_files  = 4,
        max_lines       = 500,
        include_imports = True,
        include_docs    = False,
    ),
    IntentClass.EXPLAIN: IntentTopology(
        file_patterns   = ["*.py"],
        symbol_types    = [ASTKind.MODULE, ASTKind.CLASS,
                           ASTKind.FUNCTION, ASTKind.ASYNC_FUNCTION],
        max_full_files  = 2,
        max_lines       = 600,
        include_imports = True,
        include_docs    = True,
    ),
    IntentClass.AUDIT: IntentTopology(
        file_patterns   = ["*.py", "**/*.py", "*.json", "*.yaml", "*.yml", "*.env*", "*.cfg"],
        symbol_types    = [ASTKind.FUNCTION, ASTKind.ASYNC_FUNCTION, ASTKind.CLASS,
                           ASTKind.CALL, ASTKind.IMPORT, ASTKind.IMPORT_FROM],
        max_full_files  = 6,
        max_lines       = 500,
        include_imports = True,
        include_docs    = True,
    ),
    IntentClass.RESEARCH: IntentTopology(
        file_patterns   = ["*.py", "*.md", "*.txt"],
        symbol_types    = [ASTKind.MODULE, ASTKind.CLASS],
        max_full_files  = 3,
        max_lines       = 200,
        include_imports = False,
        include_docs    = True,
    ),
    IntentClass.GENERATE: IntentTopology(
        file_patterns   = ["*.py", "core/*.py"],
        symbol_types    = [ASTKind.CLASS, ASTKind.FUNCTION, ASTKind.ASYNC_FUNCTION],
        max_full_files  = 3,
        max_lines       = 300,
        include_imports = True,
        include_docs    = True,
    ),
    IntentClass.REFACTOR: IntentTopology(
        file_patterns   = ["*.py", "**/*.py"],
        symbol_types    = [ASTKind.CLASS, ASTKind.FUNCTION, ASTKind.ASYNC_FUNCTION,
                           ASTKind.IMPORT, ASTKind.IMPORT_FROM],
        max_full_files  = 4,
        max_lines       = 400,
        include_imports = True,
        include_docs    = False,
    ),
    IntentClass.UNKNOWN: IntentTopology(
        file_patterns   = ["*.py"],
        symbol_types    = [ASTKind.CLASS, ASTKind.FUNCTION],
        max_full_files  = 2,
        max_lines       = 200,
        include_imports = False,
        include_docs    = False,
    ),
}


# ── AST extraction ────────────────────────────────────────────────────────────

@dataclass
class SymbolInfo:
    name:       str
    kind:       str           # FunctionDef, ClassDef, etc.
    line_start: int
    line_end:   int
    docstring:  Optional[str] = None
    is_async:   bool          = False
    decorators: list[str]     = field(default_factory=list)
    args:       list[str]     = field(default_factory=list)


def _extract_symbols(source: str, node_types: list[str]) -> list[SymbolInfo]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    results: list[SymbolInfo] = []
    source.splitlines()

    for node in ast.walk(tree):
        kind = type(node).__name__
        if kind not in node_types:
            continue

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node)
            decorators = [ast.unparse(d) for d in node.decorator_list]
            args = [a.arg for a in node.args.args]
            end = getattr(node, "end_lineno", node.lineno)
            results.append(SymbolInfo(
                name       = node.name,
                kind       = kind,
                line_start = node.lineno,
                line_end   = end,
                docstring  = doc,
                is_async   = isinstance(node, ast.AsyncFunctionDef),
                decorators = decorators,
                args       = args,
            ))

        elif isinstance(node, ast.ClassDef):
            doc = ast.get_docstring(node)
            decorators = [ast.unparse(d) for d in node.decorator_list]
            end = getattr(node, "end_lineno", node.lineno)
            results.append(SymbolInfo(
                name       = node.name,
                kind       = "ClassDef",
                line_start = node.lineno,
                line_end   = end,
                docstring  = doc,
                decorators = decorators,
            ))

    return results


def _extract_imports(source: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            names = ", ".join(a.name for a in node.names)
            imports.append(f"from {node.module or '.'} import {names}")
    return imports


# ── File resolution ───────────────────────────────────────────────────────────

@dataclass
class FileContext:
    path:        str
    content:     str                # full or truncated content
    symbols:     list[SymbolInfo]
    imports:     list[str]
    line_count:  int
    truncated:   bool = False


def _resolve_files(
    project_root: str,
    topology: IntentTopology,
    targets: list[IntentTarget],
) -> list[str]:
    """
    Returns ordered list of absolute file paths to load, targets first.
    """
    root = Path(project_root)
    found: list[str] = []
    seen:  set[str]  = set()

    # Explicit target files first
    for t in targets:
        if t.path:
            candidates = [
                str(root / t.path),
                str(root / (t.path + ".py")) if not t.path.endswith(".py") else None,
                t.path if os.path.isabs(t.path) else None,
            ]
            for c in candidates:
                if c and os.path.isfile(c) and c not in seen:
                    found.append(c)
                    seen.add(c)

    # Topology-driven glob
    for pattern in topology.file_patterns:
        for path in sorted(glob.glob(str(root / pattern), recursive=True)):
            if path not in seen and os.path.isfile(path):
                # Skip __pycache__, venv, node_modules
                if any(skip in path for skip in SKIP_DIRS):
                    continue
                found.append(path)
                seen.add(path)

    return found


def _load_file(path: str, max_lines: int) -> tuple[str, bool]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        truncated = len(lines) > max_lines
        content = "".join(lines[:max_lines])
        return content, truncated
    except OSError:
        return "", False


# ── Correlation result ─────────────────────────────────────────────────────────

@dataclass
class CorrelationResult:
    intent_class:  IntentClass
    topology:      IntentTopology
    files:         list[FileContext]
    project_root:  str
    total_symbols: int = 0

    def get_symbol(self, name: str) -> Optional[SymbolInfo]:
        for fc in self.files:
            for s in fc.symbols:
                if s.name == name:
                    return s
        return None

    def get_file(self, path: str) -> Optional[FileContext]:
        for fc in self.files:
            if fc.path == path or Path(fc.path).name == path:
                return fc
        return None

    def to_context_block(self) -> str:
        """Compact text block for the proposal engine's context slot."""
        lines = [f"# Codebase Context — Intent: {self.intent_class.value}\n"]
        for fc in self.files:
            rel = os.path.relpath(fc.path, self.project_root)
            trunc_note = f" [truncated at {len(fc.content.splitlines())} lines]" if fc.truncated else ""
            lines.append(f"## {rel}{trunc_note}")

            if fc.imports:
                lines.append("### imports")
                lines.extend(f"  {imp}" for imp in fc.imports[:12])

            if fc.symbols:
                lines.append("### symbols")
                for s in fc.symbols:
                    async_tag = "async " if s.is_async else ""
                    dec_tag   = f"  @{s.decorators[0]}" if s.decorators else ""
                    lines.append(
                        f"  {s.kind}:{dec_tag} {async_tag}{s.name}"
                        f"  [L{s.line_start}-{s.line_end}]"
                        + (f'  "{textwrap.shorten(s.docstring, 60)}"' if s.docstring else "")
                    )

            lines.append("### source")
            lines.append("```python")
            lines.append(fc.content.rstrip())
            lines.append("```\n")

        return "\n".join(lines)


# ── Public API ─────────────────────────────────────────────────────────────────

class CodeCorrelator:
    def __init__(self, project_root: str):
        self.project_root = str(Path(project_root).resolve())

    def correlate(self, intent: IntentResult) -> CorrelationResult:
        topology = _TOPOLOGIES.get(intent.intent_class, _TOPOLOGIES[IntentClass.UNKNOWN])
        paths    = _resolve_files(self.project_root, topology, intent.targets)

        file_contexts: list[FileContext] = []
        total_symbols = 0

        for i, path in enumerate(paths):
            full = i < topology.max_full_files
            if full:
                content, truncated = _load_file(path, topology.max_lines)
            else:
                # Header-only: imports + symbol list, no body
                content, _ = _load_file(path, 30)
                truncated = True

            if not content:
                continue

            symbols = _extract_symbols(content, topology.symbol_types)
            imports = _extract_imports(content) if topology.include_imports else []

            # Strip docstrings from content if topology says not to include
            if not topology.include_docs and content:
                # keep content as-is; docstrings are surfaced via SymbolInfo only
                pass

            file_contexts.append(FileContext(
                path       = path,
                content    = content,
                symbols    = symbols,
                imports    = imports,
                line_count = content.count("\n") + 1,
                truncated  = truncated,
            ))
            total_symbols += len(symbols)

        return CorrelationResult(
            intent_class  = intent.intent_class,
            topology      = topology,
            files         = file_contexts,
            project_root  = self.project_root,
            total_symbols = total_symbols,
        )


_correlator: Optional[CodeCorrelator] = None

def get_correlator(project_root: Optional[str] = None) -> CodeCorrelator:
    global _correlator
    if _correlator is None or project_root:
        root = project_root or os.path.dirname(os.path.abspath(__file__))
        _correlator = CodeCorrelator(root)
    return _correlator
