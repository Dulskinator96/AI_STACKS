"""
pyramid_tools/code_tools.py — Local code intelligence tools.

All tools are free, no API key required, execute entirely locally.
Each returns a plain-text string suitable for LLM context injection.
"""
from __future__ import annotations

import ast
import difflib
import os
import re
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from config import DATA_DIR, SANDBOX_TIMEOUT, SKIP_DIRS, ASTKind

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ── search_code ───────────────────────────────────────────────────────────────

def tool_search_code(query: str, pattern: str = "*.py", **_) -> str:
    """
    Search codebase for a regex/literal pattern using Python's re module.
    Falls back to subprocess ripgrep if available (faster on large codebases).
    Returns up to 30 matching lines with file:line context.
    """
    # Try ripgrep first
    try:
        result = subprocess.run(
            ["rg", "--no-heading", "-n", "--glob", pattern, query, str(_PROJECT_ROOT)],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        if result.returncode in (0, 1):
            lines = result.stdout.strip().splitlines()[:30]
            if lines:
                return "\n".join(lines)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Pure-Python fallback
    results: list[str] = []
    try:
        rx = re.compile(query, re.IGNORECASE)
    except re.error:
        rx = re.compile(re.escape(query), re.IGNORECASE)

    for root, dirs, files in os.walk(_PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in files:
            if not _match_glob(fname, pattern):
                continue
            fpath = Path(root) / fname
            try:
                for i, line in enumerate(fpath.read_text(encoding="utf-8",
                                                          errors="replace").splitlines(), 1):
                    if rx.search(line):
                        rel = fpath.relative_to(_PROJECT_ROOT)
                        results.append(f"{rel}:{i}: {line.rstrip()}")
                        if len(results) >= 30:
                            break
            except OSError:
                continue
        if len(results) >= 30:
            break

    return "\n".join(results) if results else f"No matches for '{query}' in {pattern}"


def _match_glob(name: str, pattern: str) -> bool:
    import fnmatch
    return fnmatch.fnmatch(name, pattern.lstrip("*/"))


# ── read_file ─────────────────────────────────────────────────────────────────

def tool_read_file(file: str, start: str = "1", end: str = "80", **_) -> str:
    """Read a project file, optionally slicing by line range."""
    path = _resolve(file)
    if path is None:
        return f"File not found: {file}"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        s = max(0, int(start) - 1)
        e = min(len(lines), int(end))
        numbered = [f"{s+i+1:4d}  {l}" for i, l in enumerate(lines[s:e])]
        header = f"# {path.relative_to(_PROJECT_ROOT)}  (lines {s+1}–{e})\n"
        return header + "\n".join(numbered)
    except Exception as exc:
        return f"Error reading {file}: {exc}"


def _resolve(name: str) -> Path | None:
    candidates = [
        _PROJECT_ROOT / name,
        _PROJECT_ROOT / (name + ".py"),
        Path(name),
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


# ── run_python ────────────────────────────────────────────────────────────────

def tool_run_python(code: str, **_) -> str:
    """Execute a Python snippet in an isolated subprocess. Returns stdout/stderr."""
    try:
        ast.parse(code)
    except SyntaxError as e:
        return f"Syntax error before execution: {e}"

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(code)
        tmp_path = tmp.name

    try:
        proc = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True, text=True,
            timeout=SANDBOX_TIMEOUT,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        out = proc.stdout[:800]
        err = proc.stderr[:400] if proc.returncode != 0 else ""
        return (out + ("\nSTDERR:\n" + err if err else "")).strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Timed out after {SANDBOX_TIMEOUT}s"
    except Exception as exc:
        return f"Execution error: {exc}"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ── analyze_ast ───────────────────────────────────────────────────────────────

def tool_analyze_ast(file: str, **_) -> str:
    """Return a structured AST summary: imports, classes, functions with line numbers."""
    path = _resolve(file)
    if path is None:
        return f"File not found: {file}"
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree   = ast.parse(source)
    except SyntaxError as e:
        return f"Syntax error in {file}: {e}"
    except OSError as exc:
        return f"Cannot read {file}: {exc}"

    sections: list[str] = [f"# AST: {path.name}\n"]

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imports.append(f"import {a.name}")
        elif isinstance(node, ast.ImportFrom):
            names = ", ".join(a.name for a in node.names)
            imports.append(f"from {node.module or '.'} import {names}")
    if imports:
        sections.append("## Imports\n" + "\n".join(imports[:20]))

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            doc = ast.get_docstring(node) or ""
            end = getattr(node, "end_lineno", node.lineno)
            methods = [
                f"    {ASTKind.FUNCTION} {n.name}({', '.join(a.arg for a in n.args.args)}) "
                f"[L{n.lineno}]"
                for n in ast.walk(node)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            sections.append(
                f"\n## class {node.name}  [L{node.lineno}-{end}]\n"
                + (f"  \"{textwrap.shorten(doc, 80)}\"\n" if doc else "")
                + "\n".join(methods[:20])
            )

    standalone_fns = [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not any(
            isinstance(p, ast.ClassDef) and n in ast.walk(p)
            for p in ast.walk(tree)
            if isinstance(p, ast.ClassDef)
        )
    ]
    if standalone_fns:
        fn_lines = []
        for n in standalone_fns[:15]:
            doc  = ast.get_docstring(n) or ""
            args = ", ".join(a.arg for a in n.args.args)
            end  = getattr(n, "end_lineno", n.lineno)
            fn_lines.append(
                f"  def {n.name}({args})  [L{n.lineno}-{end}]"
                + (f'  "{textwrap.shorten(doc, 60)}"' if doc else "")
            )
        sections.append("\n## Module-level functions\n" + "\n".join(fn_lines))

    return "\n".join(sections)


# ── check_syntax ──────────────────────────────────────────────────────────────

def tool_check_syntax(code: str, **_) -> str:
    """Validate Python syntax. Returns OK or the error with line number."""
    try:
        ast.parse(code)
        return "Syntax OK"
    except SyntaxError as e:
        return f"SyntaxError at line {e.lineno}: {e.msg}\n  {e.text or ''}"


# ── git_log ───────────────────────────────────────────────────────────────────

def tool_git_log(n: str = "10", **_) -> str:
    """Return recent git commit history from the project root."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(_PROJECT_ROOT), "log",
             f"--max-count={int(n)}", "--oneline", "--no-decorate"],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        return proc.stdout.strip() or "No git history found"
    except FileNotFoundError:
        return "git not available"
    except Exception as exc:
        return f"git log error: {exc}"


# ── diff_files ────────────────────────────────────────────────────────────────

def tool_diff_files(file1: str, file2: str, **_) -> str:
    """Produce a unified diff between two project files."""
    p1, p2 = _resolve(file1), _resolve(file2)
    if p1 is None:
        return f"File not found: {file1}"
    if p2 is None:
        return f"File not found: {file2}"
    try:
        a = p1.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        b = p2.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        diff = list(difflib.unified_diff(a, b, fromfile=file1, tofile=file2))[:80]
        return "".join(diff) or "Files are identical"
    except OSError as exc:
        return f"Diff error: {exc}"


# ── run_tests ─────────────────────────────────────────────────────────────────

def tool_run_tests(path: str = "tests", **_) -> str:
    """Run pytest on a path. Returns summary output."""
    target = _PROJECT_ROOT / path
    if not target.exists():
        return f"Path not found: {path}"
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(target), "-v", "--tb=short", "-q"],
            capture_output=True, text=True, timeout=60,
            cwd=str(_PROJECT_ROOT),
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        return (proc.stdout + proc.stderr)[:1200].strip()
    except subprocess.TimeoutExpired:
        return "pytest timed out after 60s"
    except Exception as exc:
        return f"pytest error: {exc}"


# ── lint_code ─────────────────────────────────────────────────────────────────

def tool_lint_code(file: str, **_) -> str:
    """Run flake8 on a project file. Returns lint issues."""
    path = _resolve(file)
    if path is None:
        return f"File not found: {file}"
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "flake8", "--max-line-length=100",
             "--extend-ignore=E203,W503", str(path)],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        out = (proc.stdout + proc.stderr).strip()
        return out or "No lint issues found"
    except FileNotFoundError:
        return "flake8 not installed (pip install flake8)"
    except Exception as exc:
        return f"flake8 error: {exc}"
