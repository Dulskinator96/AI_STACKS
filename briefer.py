"""
briefer.py — Application briefing engine.

Scans a project directory and produces a structured ApplicationBrief:
  • Annotated file tree
  • Per-file: purpose, gist, classes, functions, imports, exports, complexity
  • Cross-file dependency graph
  • Entry point detection
  • External dependency catalog
  • Configuration extraction
  • Architecture synthesis

LLM is used ONLY for natural-language summaries (per-file gist + overview).
All structure — symbols, deps, imports, entry points — is deterministic AST/parse.
Per-file summaries are cached by SHA-256 so re-briefs skip unchanged files.

Output renderers: render_markdown(), render_json()
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import requests
import logging
_log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral"
CACHE_PATH   = Path.home() / ".stratum" / "brief_cache.json"

SKIP_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "env", "node_modules",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".eggs",
}
SKIP_EXTS = {".pyc", ".pyo", ".pyd", ".so", ".dll", ".exe", ".ico",
             ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg",
             ".zip", ".tar", ".gz", ".whl"}
TEXT_EXTS  = {".py", ".md", ".txt", ".rst", ".json", ".yaml", ".yml",
              ".toml", ".cfg", ".ini", ".env", ".bat", ".sh", ".ps1",
              ".js", ".ts", ".html", ".css", ".sql"}


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class SymbolBrief:
    name:       str
    kind:       str           # "class", "async def", "def"
    line_start: int
    line_end:   int
    docstring:  Optional[str] = None
    args:       list[str]     = field(default_factory=list)
    decorators: list[str]     = field(default_factory=list)
    methods:    list[str]     = field(default_factory=list)  # for classes


@dataclass
class ModuleBrief:
    path:         str          # absolute
    rel_path:     str          # relative to project root
    line_count:   int
    size_bytes:   int
    file_type:    str          # "python", "config", "doc", "data", "script", "other"
    symbols:      list[SymbolBrief]  = field(default_factory=list)
    imports_local: list[str]         = field(default_factory=list)
    imports_ext:   list[str]         = field(default_factory=list)
    exports:       list[str]         = field(default_factory=list)  # symbols imported by others
    entry_points:  list[str]         = field(default_factory=list)
    config_vars:   list[tuple[str, str]] = field(default_factory=list)  # (name, value/type)
    purpose:       str               = ""
    gist:          str               = ""
    patterns:      list[str]         = field(default_factory=list)
    complexity:    str               = "medium"  # low | medium | high
    summary_cached: bool             = False


@dataclass
class DependencyEdge:
    source: str   # rel_path
    target: str   # rel_path (local) or package name (external)
    kind:   str   # "local" | "external"


@dataclass
class EntryPoint:
    rel_path: str
    symbol:   str
    how:      str   # "__main__", "decorator", "explicit call"


@dataclass
class ExtDep:
    name:      str
    used_by:   list[str]
    purpose:   str = ""


@dataclass
class ConfigVar:
    name:    str
    file:    str
    default: str
    purpose: str = ""


@dataclass
class ApplicationBrief:
    project_root:  str
    project_name:  str
    generated_at:  float
    total_files:   int
    total_lines:   int
    total_bytes:   int
    overview:      str
    architecture:  str
    data_flow:     str
    complexity:    str
    key_patterns:  list[str]
    modules:       list[ModuleBrief]
    dep_edges:     list[DependencyEdge]
    entry_points:  list[EntryPoint]
    ext_deps:      list[ExtDep]
    config_vars:   list[ConfigVar]
    llm_used:      bool = True


# ── SHA-256 cache ──────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            _log.warning(f'caught exception: {e}')
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _hash_file(path: str) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


# ── AST analysis ───────────────────────────────────────────────────────────────

def _classify_complexity(symbols: list[SymbolBrief], line_count: int) -> str:
    if line_count > 400 or len(symbols) > 20:
        return "high"
    if line_count > 150 or len(symbols) > 8:
        return "medium"
    return "low"


def _parse_python(path: str, source: str) -> tuple[list[SymbolBrief], list[str], list[str], list[str], list[tuple[str,str]]]:
    """Returns (symbols, local_imports, ext_imports, entry_points, config_vars)."""
    symbols:      list[SymbolBrief]          = []
    local_imports: list[str]                  = []
    ext_imports:   list[str]                  = []
    entry_points:  list[str]                  = []
    config_vars:   list[tuple[str, str]]      = []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return symbols, local_imports, ext_imports, entry_points, config_vars

    # Imports
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name.split(".")[0]
                ext_imports.append(name)
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if node.level and node.level > 0:
                local_imports.append(f".{node.module or ''}")
            elif mod:
                # Heuristic: local if lowercase single word that looks like a module file
                ext_imports.append(mod)

    # Symbols (top-level only for clarity)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            doc  = ast.get_docstring(node)
            args = [a.arg for a in node.args.args if a.arg != "self"]
            decs = [ast.unparse(d) for d in node.decorator_list]
            end  = getattr(node, "end_lineno", node.lineno)
            symbols.append(SymbolBrief(
                name=node.name, kind=kind,
                line_start=node.lineno, line_end=end,
                docstring=doc, args=args, decorators=decs,
            ))
            # Entry point detection
            if node.name == "main":
                entry_points.append(f"{node.name}() [explicit]")
            for d in decs:
                if any(x in d for x in ("route", "app.", "cli.", "command", "task")):
                    entry_points.append(f"{node.name}() [{d}]")

        elif isinstance(node, ast.ClassDef):
            doc  = ast.get_docstring(node)
            decs = [ast.unparse(d) for d in node.decorator_list]
            end  = getattr(node, "end_lineno", node.lineno)
            methods = [
                n.name for n in ast.walk(node)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name not in ("__init__", "__repr__", "__str__")
            ]
            symbols.append(SymbolBrief(
                name=node.name, kind="class",
                line_start=node.lineno, line_end=end,
                docstring=doc, decorators=decs, methods=methods[:12],
            ))

        elif isinstance(node, ast.Assign):
            # Module-level constant / config var
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    try:
                        val = ast.unparse(node.value)[:60]
                    except Exception:
                        val = "..."
                    config_vars.append((target.id, val))

    # __main__ guard
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            try:
                test = ast.unparse(node.test)
                if "__name__" in test and "__main__" in test:
                    entry_points.append('__name__ == "__main__"')
                    break
            except Exception as e:
                _log.warning(f'caught exception: {e}')

    return symbols, local_imports, ext_imports, entry_points, config_vars


def _detect_local_imports(rel_path: str, ext_imports: list[str], all_rel_paths: set[str]) -> tuple[list[str], list[str]]:
    """Split ext_imports into local vs external by checking if the module file exists in project."""
    local, ext = [], []
    stems = {Path(p).stem: p for p in all_rel_paths}
    for imp in ext_imports:
        stem = imp.lstrip(".")
        if stem in stems:
            local.append(stems[stem])
        else:
            ext.append(imp)
    return local, ext


# ── Non-Python file analysis ───────────────────────────────────────────────────

def _analyze_text_file(path: str, ext: str, source: str) -> tuple[list[tuple[str,str]], str]:
    """Returns (config_vars, file_type)."""
    config_vars: list[tuple[str, str]] = []
    file_type = "other"

    if ext == ".py":
        file_type = "python"

    elif ext in (".json",):
        file_type = "data"
        try:
            data = json.loads(source)
            if isinstance(data, dict):
                config_vars = [(k, type(v).__name__) for k, v in list(data.items())[:20]]
        except Exception as e:
            _log.warning(f'caught exception: {e}')

    elif ext in (".yaml", ".yml"):
        file_type = "config"
        for m in re.finditer(r"^(\w+)\s*:", source, re.M):
            config_vars.append((m.group(1), "yaml-key"))
        config_vars = config_vars[:20]

    elif ext in (".env",) or Path(path).name.startswith(".env"):
        file_type = "config"
        for m in re.finditer(r"^([A-Z_][A-Z0-9_]*)=(.*)$", source, re.M):
            config_vars.append((m.group(1), m.group(2).strip()[:40] or "(empty)"))

    elif ext in (".toml", ".cfg", ".ini"):
        file_type = "config"
        for m in re.finditer(r"^(\w+)\s*=\s*(.*)$", source, re.M):
            config_vars.append((m.group(1), m.group(2).strip()[:40]))
        config_vars = config_vars[:20]

    elif ext in (".md", ".rst", ".txt"):
        file_type = "doc"

    elif ext in (".bat", ".sh", ".ps1"):
        file_type = "script"

    elif ext in (".js", ".ts"):
        file_type = "script"

    elif ext in (".html", ".css"):
        file_type = "ui"

    elif ext == ".sql":
        file_type = "data"

    return config_vars, file_type


# ── LLM summary ───────────────────────────────────────────────────────────────

_MODULE_SYSTEM = (
    "You are a code analyst. Output ONLY valid JSON — no prose, no markdown outside JSON. "
    "Be concise and precise. One sentence for purpose, 2-4 sentences for gist."
)

_ARCH_SYSTEM = (
    "You are a software architect. Output ONLY valid JSON. "
    "Synthesize the module list into a high-level architectural view."
)


def _call_ollama(system: str, prompt: str, timeout: int = 60) -> Optional[str]:
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model":  OLLAMA_MODEL,
                "prompt": system + "\n\n" + prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 512},
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
    except Exception:
        return None


def _extract_json(text: str) -> dict:
    if not text:
        return {}
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    m = re.search(r"(\{.*\})", text, re.S)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except Exception:
        return {}


def _llm_module_summary(module: ModuleBrief) -> tuple[str, str, list[str], str]:
    """Returns (purpose, gist, patterns, complexity)."""
    symbol_lines = "\n".join(
        f"  {s.kind} {s.name}({', '.join(s.args[:4])})"
        + (f" — {s.docstring[:80]}" if s.docstring else "")
        for s in module.symbols[:15]
    )
    config_lines = "\n".join(f"  {k} = {v}" for k, v in module.config_vars[:10])
    prompt = f"""File: {module.rel_path} ({module.line_count} lines, {module.file_type})

Symbols:
{symbol_lines or '  (none)'}

Config/Constants:
{config_lines or '  (none)'}

Local imports: {', '.join(module.imports_local[:8]) or 'none'}
External imports: {', '.join(module.imports_ext[:8]) or 'none'}

Return JSON:
{{
  "purpose": "<one sentence: what this module is for>",
  "gist": "<2-4 sentences: what the code actually does, key behaviours>",
  "patterns": ["<design pattern or technique>"],
  "complexity": "low|medium|high"
}}"""

    raw = _call_ollama(_MODULE_SYSTEM, prompt)
    data = _extract_json(raw or "")
    return (
        data.get("purpose", ""),
        data.get("gist", ""),
        data.get("patterns", []),
        data.get("complexity", module.complexity),
    )


def _llm_architecture_summary(modules: list[ModuleBrief]) -> tuple[str, str, str, list[str]]:
    """Returns (overview, architecture_pattern, data_flow, key_patterns)."""
    lines = "\n".join(
        f"  {m.rel_path} ({m.line_count}ln, {m.file_type}): {m.purpose or '(no summary)'}"
        for m in modules[:30]
    )
    prompt = f"""Application modules:
{lines}

Return JSON:
{{
  "overview": "<1 paragraph: what this application does>",
  "architecture_pattern": "<named pattern, e.g. 'event-driven daemon + async GUI'>",
  "data_flow": "<concise A → B → C flow>",
  "key_patterns": ["<pattern>"]
}}"""

    raw = _call_ollama(_ARCH_SYSTEM, prompt, timeout=90)
    data = _extract_json(raw or "")
    return (
        data.get("overview", ""),
        data.get("architecture_pattern", ""),
        data.get("data_flow", ""),
        data.get("key_patterns", []),
    )


# ── File walker ────────────────────────────────────────────────────────────────

def _walk_project(project_root: str) -> list[tuple[str, str]]:
    """Returns [(abs_path, rel_path)] for all relevant files."""
    results = []
    root = Path(project_root)
    for dirpath, dirs, files in os.walk(root):
        # Prune skip dirs in-place
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for fname in sorted(files):
            ext = Path(fname).suffix.lower()
            if ext in SKIP_EXTS:
                continue
            abs_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(abs_path, root)
            results.append((abs_path, rel_path))
    return results


def _render_tree(modules: list[ModuleBrief], project_name: str) -> str:
    """Renders an annotated ASCII tree."""
    # Group by directory
    by_dir: dict[str, list[ModuleBrief]] = {}
    for m in modules:
        parts = Path(m.rel_path).parts
        d = str(Path(*parts[:-1])) if len(parts) > 1 else "."
        by_dir.setdefault(d, []).append(m)

    lines = [f"{project_name}/"]
    for d in sorted(by_dir.keys()):
        items = by_dir[d]
        if d != ".":
            lines.append(f"├── {d}/")
            prefix = "│   "
        else:
            prefix = ""
        for i, m in enumerate(items):
            fname = Path(m.rel_path).name
            connector = "└── " if i == len(items) - 1 and d != "." else "├── "
            complexity_tag = {"high": "◈", "medium": "◆", "low": "◇"}.get(m.complexity, "")
            purpose_short = (m.purpose[:55] + "…") if len(m.purpose) > 55 else m.purpose
            ln_tag = f"{m.line_count:>5} ln"
            lines.append(f"{prefix}{connector}{fname:<38} {ln_tag}  {complexity_tag}  {purpose_short}")

    return "\n".join(lines)


# ── Main briefer ───────────────────────────────────────────────────────────────

ProgressCallback = Callable[[str, int, int], None]  # (message, current, total)


class Briefer:
    def __init__(self, use_llm: bool = True, model: str = OLLAMA_MODEL):
        self.use_llm = use_llm
        self.model   = model
        self._cache  = _load_cache()

    def brief(
        self,
        project_root: str,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> ApplicationBrief:
        root     = str(Path(project_root).resolve())
        pname    = Path(root).name
        all_files = _walk_project(root)
        all_rel   = {r for _, r in all_files}

        if progress_cb:
            progress_cb("Scanning files…", 0, len(all_files))

        modules: list[ModuleBrief] = []
        total_lines = 0
        total_bytes = 0

        # ── Phase 1: Parse every file ─────────────────────────────────────────
        for idx, (abs_path, rel_path) in enumerate(all_files):
            if progress_cb:
                progress_cb(f"Parsing {rel_path}", idx, len(all_files))

            try:
                stat = os.stat(abs_path)
                size = stat.st_size
            except OSError:
                continue

            ext = Path(abs_path).suffix.lower()
            if ext not in TEXT_EXTS:
                continue

            try:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    source = f.read()
            except OSError:
                continue

            lines = source.count("\n") + 1
            total_lines += lines
            total_bytes += size

            config_vars, file_type = _analyze_text_file(abs_path, ext, source)

            symbols:       list[SymbolBrief]   = []
            local_imports: list[str]            = []
            ext_imports:   list[str]            = []
            entry_points:  list[str]            = []

            if ext == ".py":
                file_type = "python"
                syms, local_raw, ext_raw, eps, cvars = _parse_python(abs_path, source)
                symbols      = syms
                entry_points = eps
                config_vars  = cvars
                # Split local vs external once we have all_rel available
                local_imports, ext_imports = _detect_local_imports(rel_path, ext_raw, all_rel)

            complexity = _classify_complexity(symbols, lines)

            modules.append(ModuleBrief(
                path          = abs_path,
                rel_path      = rel_path,
                line_count    = lines,
                size_bytes    = size,
                file_type     = file_type,
                symbols       = symbols,
                imports_local = local_imports,
                imports_ext   = list(dict.fromkeys(ext_imports)),
                entry_points  = entry_points,
                config_vars   = config_vars,
                complexity    = complexity,
            ))

        # ── Phase 2: Build exports map (what each module exports to others) ───
        export_map: dict[str, set[str]] = {m.rel_path: set() for m in modules}
        for m in modules:
            for dep in m.imports_local:
                if dep in export_map:
                    for s in m.symbols:
                        export_map[dep].add(s.name)

        for m in modules:
            m.exports = sorted(export_map.get(m.rel_path, set()))[:20]

        # ── Phase 3: LLM summaries ────────────────────────────────────────────
        py_modules = [m for m in modules if m.file_type == "python"]
        total_to_summarize = len(py_modules)

        for idx, m in enumerate(py_modules):
            if progress_cb:
                progress_cb(f"Summarizing {m.rel_path}…", idx, total_to_summarize)

            if not self.use_llm:
                m.purpose = f"{m.file_type.title()} module · {len(m.symbols)} symbol(s)"
                continue

            file_hash = _hash_file(m.path)
            cache_key = file_hash

            cached = self._cache.get(cache_key)
            if cached and time.time() - cached.get("cached_at", 0) < 86400 * 7:
                m.purpose         = cached.get("purpose", "")
                m.gist            = cached.get("gist", "")
                m.patterns        = cached.get("patterns", [])
                m.complexity      = cached.get("complexity", m.complexity)
                m.summary_cached  = True
                continue

            purpose, gist, patterns, complexity = _llm_module_summary(m)
            m.purpose    = purpose
            m.gist       = gist
            m.patterns   = patterns
            m.complexity = complexity or m.complexity

            self._cache[cache_key] = {
                "purpose": purpose, "gist": gist,
                "patterns": patterns, "complexity": complexity,
                "cached_at": time.time(),
            }

        _save_cache(self._cache)

        # ── Phase 4: Architecture synthesis ───────────────────────────────────
        if progress_cb:
            progress_cb("Synthesizing architecture…", total_to_summarize, total_to_summarize)

        overview = arch_pattern = data_flow = ""
        key_patterns: list[str] = []

        if self.use_llm and py_modules:
            overview, arch_pattern, data_flow, key_patterns = _llm_architecture_summary(py_modules)

        if not overview:
            overview = f"{pname} — {len(py_modules)} Python modules, {total_lines:,} lines."
        if not arch_pattern:
            arch_pattern = "[INFERRED — LLM unavailable]"

        # ── Phase 5: Dependency edges ─────────────────────────────────────────
        dep_edges: list[DependencyEdge] = []
        for m in modules:
            for dep in m.imports_local:
                dep_edges.append(DependencyEdge(m.rel_path, dep, "local"))
            for dep in m.imports_ext[:6]:
                dep_edges.append(DependencyEdge(m.rel_path, dep, "external"))

        # ── Phase 6: Entry points ─────────────────────────────────────────────
        entry_points_list: list[EntryPoint] = []
        for m in modules:
            for ep in m.entry_points:
                entry_points_list.append(EntryPoint(m.rel_path, ep, ep))

        # ── Phase 7: External dependency catalog ──────────────────────────────
        ext_usage: dict[str, list[str]] = {}
        for m in modules:
            for dep in m.imports_ext:
                ext_usage.setdefault(dep, []).append(m.rel_path)
        ext_deps = [
            ExtDep(name=k, used_by=v)
            for k, v in sorted(ext_usage.items())
            if k not in {"os", "sys", "re", "json", "time", "math", "abc",
                         "typing", "dataclasses", "pathlib", "enum", "io",
                         "threading", "hashlib", "shutil", "tempfile", "ast",
                         "textwrap", "glob", "datetime", "collections", "copy",
                         "__future__"}
        ]

        # ── Phase 8: Config var catalog ───────────────────────────────────────
        all_config: list[ConfigVar] = []
        for m in modules:
            for name, val in m.config_vars:
                all_config.append(ConfigVar(name=name, file=m.rel_path, default=val))

        overall_complexity = "high" if total_lines > 5000 else "medium" if total_lines > 1500 else "low"

        return ApplicationBrief(
            project_root    = root,
            project_name    = pname,
            generated_at    = time.time(),
            total_files     = len(modules),
            total_lines     = total_lines,
            total_bytes     = total_bytes,
            overview        = overview,
            architecture    = arch_pattern,
            data_flow       = data_flow,
            complexity      = overall_complexity,
            key_patterns    = key_patterns,
            modules         = modules,
            dep_edges       = dep_edges,
            entry_points    = entry_points_list,
            ext_deps        = ext_deps,
            config_vars     = all_config,
            llm_used        = self.use_llm,
        )


# ── Markdown renderer ──────────────────────────────────────────────────────────

def render_markdown(brief: ApplicationBrief) -> str:
    ts   = time.strftime("%Y-%m-%d %H:%M", time.localtime(brief.generated_at))
    kb   = brief.total_bytes / 1024
    size = f"{kb:.1f} KB" if kb < 1024 else f"{kb/1024:.1f} MB"
    llm_note = "with LLM summaries" if brief.llm_used else "structure-only (no LLM)"

    lines: list[str] = []
    a = lines.append

    a(f"# APPLICATION BRIEF: {brief.project_name}")
    a(f"> Generated {ts} · {brief.total_files} files · {brief.total_lines:,} lines · {size} · {llm_note}")
    a("")
    a("---")
    a("")
    a("## Overview")
    a(brief.overview or "_No overview generated._")
    a("")
    a("## Architecture")
    a(f"**Pattern:** {brief.architecture or '[UNKNOWN]'}")
    if brief.data_flow:
        a(f"**Data Flow:** {brief.data_flow}")
    a(f"**Overall Complexity:** {brief.complexity.title()}")
    a("")
    a("---")
    a("")
    a("## File Tree")
    a("```")
    a(_render_tree(brief.modules, brief.project_name))
    a("```")
    a("")
    a("_Legend: ◈ high complexity · ◆ medium · ◇ low_")
    a("")
    a("---")
    a("")
    a("## Modules")
    a("")

    for m in brief.modules:
        Path(m.rel_path).name
        a(f"### `{m.rel_path}` [{m.line_count} lines · {m.complexity} complexity · {m.file_type}]")
        if m.purpose:
            a(f"**Purpose:** {m.purpose}")

        if m.imports_local:
            a(f"**Local deps:** {' → '.join(m.imports_local[:8])}")
        if m.imports_ext:
            notable = [x for x in m.imports_ext if x not in {"os","sys","re","json","time"}]
            if notable:
                a(f"**External:** {', '.join(notable[:8])}")
        if m.entry_points:
            a(f"**Entry:** {' | '.join(m.entry_points[:3])}")
        if m.exports:
            a(f"**Exports to other modules:** {', '.join(m.exports[:10])}")

        if m.gist:
            a("")
            a(f"> {m.gist}")

        if m.patterns:
            a("")
            a(f"*Patterns: {', '.join(m.patterns)}*")

        if m.symbols:
            a("")
            a("| Symbol | Kind | Lines | Notes |")
            a("|--------|------|-------|-------|")
            for s in m.symbols[:20]:
                doc_short = (s.docstring[:60] + "…") if s.docstring and len(s.docstring) > 60 else (s.docstring or "")
                args_str  = f"({', '.join(s.args[:4])})" if s.args else "()"
                methods_str = f" · methods: {', '.join(s.methods[:5])}" if s.methods else ""
                a(f"| `{s.name}{args_str}` | {s.kind} | {s.line_start}–{s.line_end} | {doc_short}{methods_str} |")

        if m.config_vars:
            a("")
            a("| Constant | Value |")
            a("|----------|-------|")
            for name, val in m.config_vars[:12]:
                a(f"| `{name}` | `{val}` |")

        a("")

    a("---")
    a("")
    a("## Dependency Graph")
    a("```")
    # Local deps only for readability
    seen_edges: set[tuple[str,str]] = set()
    for e in brief.dep_edges:
        if e.kind == "local" and (e.source, e.target) not in seen_edges:
            seen_edges.add((e.source, e.target))
            src = Path(e.source).stem
            tgt = Path(e.target).stem if not e.target.startswith(".") else e.target
            a(f"  {src} → {tgt}")
    a("```")
    a("")
    a("---")
    a("")
    a("## Entry Points")
    a("")
    a("| File | Symbol | Trigger |")
    a("|------|--------|---------|")
    for ep in brief.entry_points:
        a(f"| `{ep.rel_path}` | `{ep.symbol}` | {ep.how} |")
    if not brief.entry_points:
        a("| (none detected) | — | — |")
    a("")
    a("---")
    a("")
    a("## External Dependencies")
    a("")
    a("| Package | Used By | Count |")
    a("|---------|---------|-------|")
    for dep in sorted(brief.ext_deps, key=lambda d: -len(d.used_by))[:30]:
        used = ", ".join(Path(f).stem for f in dep.used_by[:4])
        if len(dep.used_by) > 4:
            used += f" +{len(dep.used_by)-4}"
        a(f"| `{dep.name}` | {used} | {len(dep.used_by)} |")
    a("")
    a("---")
    a("")
    a("## Configuration & Constants")
    a("")
    a("| Name | File | Value/Type |")
    a("|------|------|------------|")
    seen_cfg: set[str] = set()
    for cv in brief.config_vars[:40]:
        if cv.name not in seen_cfg:
            seen_cfg.add(cv.name)
            a(f"| `{cv.name}` | `{cv.file}` | `{cv.default[:50]}` |")
    a("")
    if brief.key_patterns:
        a("---")
        a("")
        a("## Key Patterns")
        a("")
        for i, p in enumerate(brief.key_patterns, 1):
            a(f"{i}. {p}")
        a("")

    a("---")
    a(f"*STRATUM Application Brief · {ts}*")

    return "\n".join(lines)


def render_json(brief: ApplicationBrief) -> str:
    def _mb(m: ModuleBrief) -> dict:
        return {
            "rel_path":      m.rel_path,
            "line_count":    m.line_count,
            "size_bytes":    m.size_bytes,
            "file_type":     m.file_type,
            "complexity":    m.complexity,
            "purpose":       m.purpose,
            "gist":          m.gist,
            "patterns":      m.patterns,
            "imports_local": m.imports_local,
            "imports_ext":   m.imports_ext,
            "exports":       m.exports,
            "entry_points":  m.entry_points,
            "symbols": [
                {
                    "name":       s.name,
                    "kind":       s.kind,
                    "line_start": s.line_start,
                    "line_end":   s.line_end,
                    "args":       s.args,
                    "docstring":  s.docstring,
                    "decorators": s.decorators,
                    "methods":    s.methods,
                }
                for s in m.symbols
            ],
            "config_vars": [{"name": k, "value": v} for k, v in m.config_vars],
        }

    data = {
        "project_name":   brief.project_name,
        "generated_at":   time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(brief.generated_at)),
        "total_files":    brief.total_files,
        "total_lines":    brief.total_lines,
        "total_bytes":    brief.total_bytes,
        "overview":       brief.overview,
        "architecture":   brief.architecture,
        "data_flow":      brief.data_flow,
        "complexity":     brief.complexity,
        "key_patterns":   brief.key_patterns,
        "modules":        [_mb(m) for m in brief.modules],
        "entry_points":   [{"file": e.rel_path, "symbol": e.symbol, "how": e.how}
                           for e in brief.entry_points],
        "ext_deps":       [{"name": d.name, "used_by": d.used_by}
                           for d in brief.ext_deps],
        "config_vars":    [{"name": c.name, "file": c.file, "default": c.default}
                           for c in brief.config_vars],
        "dep_edges":      [{"source": e.source, "target": e.target, "kind": e.kind}
                           for e in brief.dep_edges],
    }
    return json.dumps(data, indent=2)


# ── Module-level convenience ───────────────────────────────────────────────────

def brief_project(
    project_root: str,
    use_llm: bool = True,
    progress_cb: Optional[ProgressCallback] = None,
) -> ApplicationBrief:
    return Briefer(use_llm=use_llm).brief(project_root, progress_cb=progress_cb)
