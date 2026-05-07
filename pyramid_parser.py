"""
pyramid_parser.py — Middle Layer: Multi-language parsing and pattern detection.

Supported languages
-------------------
  Python         — stdlib ast (authoritative)
  JavaScript/TSX — regex-based
  Go             — regex-based
  Rust           — regex-based
  Java / C#      — regex-based
  Generic        — keyword heuristics

Each language returns a ParseResult containing:
  symbols  : list[SymInfo]      name/kind/lines/sig/docstring
  xrefs    : list[XRef]         imports + inheritance
  patterns : list[PatternHit]   design patterns + anti-patterns
  metrics  : dict               comment_ratio, avg_fn_length, coupling

Public API
----------
  parse_file(path, source) -> ParseResult
  detect_language(path)    -> str
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class SymInfo:
    name:       str
    kind:       str       # class | function | async_function | method | interface | struct | enum | const
    line_start: int
    line_end:   int
    signature:  str = ""
    docstring:  str = ""
    parent:     str = ""


@dataclass
class XRef:
    from_symbol: str
    to_file:     str
    to_symbol:   str
    kind:        str      # import | inherit | call | use


@dataclass
class PatternHit:
    name:       str
    confidence: float
    evidence:   str


@dataclass
class ParseResult:
    path:       str
    lang:       str
    line_count: int
    symbols:    list[SymInfo]    = field(default_factory=list)
    xrefs:      list[XRef]      = field(default_factory=list)
    patterns:   list[PatternHit] = field(default_factory=list)
    metrics:    dict             = field(default_factory=dict)


# ── Language detection ─────────────────────────────────────────────────────────

_EXT_LANG: dict[str, str] = {
    ".py": "python", ".pyw": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".cs": "csharp",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".c": "c", ".h": "c", ".hpp": "cpp",
    ".rb": "ruby", ".php": "php", ".swift": "swift",
    ".kt": "kotlin", ".scala": "scala",
    ".sh": "shell", ".bash": "shell", ".ps1": "powershell",
    ".sql": "sql", ".md": "markdown",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
}


def detect_language(path: str) -> str:
    return _EXT_LANG.get(Path(path).suffix.lower(), "generic")


# ── Python ─────────────────────────────────────────────────────────────────────

def _parse_python(source: str) -> tuple[list[SymInfo], list[XRef]]:
    symbols: list[SymInfo] = []
    xrefs:   list[XRef]   = []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return symbols, xrefs

    # Imports → xrefs
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                xrefs.append(XRef("", alias.name, "", "import"))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                xrefs.append(XRef("", mod, alias.name, "import"))

    # Top-level symbols + class members
    def _fn_sym(node, parent: str = "") -> SymInfo:
        kind = "async_function" if isinstance(node, ast.AsyncFunctionDef) else (
            "method" if parent else "function"
        )
        doc  = (ast.get_docstring(node) or "")[:200]
        end  = getattr(node, "end_lineno", node.lineno)
        args = ", ".join(a.arg for a in node.args.args if a.arg != "self")
        return SymInfo(
            name=node.name, kind=kind,
            line_start=node.lineno, line_end=end,
            signature=f"def {node.name}({args})",
            docstring=doc, parent=parent,
        )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(_fn_sym(node))

        elif isinstance(node, ast.ClassDef):
            doc   = (ast.get_docstring(node) or "")[:200]
            end   = getattr(node, "end_lineno", node.lineno)
            bases = []
            for b in node.bases:
                try:
                    bases.append(ast.unparse(b))
                except Exception:
                    pass
            sig = f"class {node.name}"
            if bases:
                sig += f"({', '.join(bases)})"
            symbols.append(SymInfo(
                name=node.name, kind="class",
                line_start=node.lineno, line_end=end,
                signature=sig, docstring=doc,
            ))
            for base in bases:
                xrefs.append(XRef(node.name, "", base, "inherit"))
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(_fn_sym(child, parent=node.name))

    return symbols, xrefs


# ── JavaScript / TypeScript ────────────────────────────────────────────────────

_JS_CLASS     = re.compile(r"^(?:export\s+)?(?:abstract\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?", re.M)
_JS_FUNCTION  = re.compile(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)\s*\(([^)]{0,120})\)", re.M)
_JS_ARROW     = re.compile(r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(?([^)=]{0,80})\)?\s*=>", re.M)
_JS_IMPORT    = re.compile(r"""^import\s+(?:[\w\s{},*]+\s+from\s+)?['"]([^'"]+)['"]""", re.M)
_JS_REQUIRE   = re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""")
_TS_INTERFACE = re.compile(r"^(?:export\s+)?interface\s+(\w+)", re.M)
_TS_ENUM      = re.compile(r"^(?:export\s+)?(?:const\s+)?enum\s+(\w+)", re.M)
_TS_TYPE      = re.compile(r"^(?:export\s+)?type\s+(\w+)\s*=", re.M)


def _lineno(source: str, pos: int) -> int:
    return source[:pos].count("\n") + 1


def _parse_js_ts(source: str, lang: str) -> tuple[list[SymInfo], list[XRef]]:
    symbols: list[SymInfo] = []
    xrefs:   list[XRef]   = []

    for m in _JS_CLASS.finditer(source):
        ln   = _lineno(source, m.start())
        base = m.group(2) or ""
        symbols.append(SymInfo(
            name=m.group(1), kind="class",
            line_start=ln, line_end=ln + 40,
            signature=f"class {m.group(1)}" + (f" extends {base}" if base else ""),
        ))
        if base:
            xrefs.append(XRef(m.group(1), "", base, "inherit"))

    for m in _JS_FUNCTION.finditer(source):
        ln = _lineno(source, m.start())
        symbols.append(SymInfo(
            name=m.group(1), kind="function",
            line_start=ln, line_end=ln + 25,
            signature=f"function {m.group(1)}({m.group(2)})",
        ))

    for m in _JS_ARROW.finditer(source):
        ln = _lineno(source, m.start())
        symbols.append(SymInfo(
            name=m.group(1), kind="function",
            line_start=ln, line_end=ln + 10,
            signature=f"{m.group(1)} = ({m.group(2)}) =>",
        ))

    if lang == "typescript":
        for m in _TS_INTERFACE.finditer(source):
            ln = _lineno(source, m.start())
            symbols.append(SymInfo(
                name=m.group(1), kind="interface",
                line_start=ln, line_end=ln + 20,
                signature=f"interface {m.group(1)}",
            ))
        for m in _TS_ENUM.finditer(source):
            ln = _lineno(source, m.start())
            symbols.append(SymInfo(
                name=m.group(1), kind="enum",
                line_start=ln, line_end=ln + 10,
                signature=f"enum {m.group(1)}",
            ))

    for m in _JS_IMPORT.finditer(source):
        xrefs.append(XRef("", m.group(1), "", "import"))
    for m in _JS_REQUIRE.finditer(source):
        xrefs.append(XRef("", m.group(1), "", "import"))

    return symbols, xrefs


# ── Go ────────────────────────────────────────────────────────────────────────

_GO_FUNC         = re.compile(r"^func\s+(?:\(([^)]+)\)\s+)?(\w+)\s*\(([^)]{0,120})\)", re.M)
_GO_TYPE         = re.compile(r"^type\s+(\w+)\s+(struct|interface)\s*\{", re.M)
_GO_IMPORT_BLOCK = re.compile(r'import\s*\(([^)]+)\)', re.S)
_GO_IMPORT_BARE  = re.compile(r'^import\s+"([^"]+)"', re.M)
_GO_STR_LIT      = re.compile(r'"([^"]+)"')


def _parse_go(source: str) -> tuple[list[SymInfo], list[XRef]]:
    symbols: list[SymInfo] = []
    xrefs:   list[XRef]   = []

    for m in _GO_FUNC.finditer(source):
        ln       = _lineno(source, m.start())
        receiver = (m.group(1) or "").strip()
        name     = m.group(2)
        params   = m.group(3)
        kind     = "method" if receiver else "function"
        parent   = ""
        if receiver:
            pm = re.search(r'\*?(\w+)', receiver)
            parent = pm.group(1) if pm else ""
        sig = f"func ({receiver}) {name}({params})" if receiver else f"func {name}({params})"
        symbols.append(SymInfo(name=name, kind=kind,
                               line_start=ln, line_end=ln + 25,
                               signature=sig, parent=parent))

    for m in _GO_TYPE.finditer(source):
        ln   = _lineno(source, m.start())
        kind = "interface" if m.group(2) == "interface" else "struct"
        symbols.append(SymInfo(name=m.group(1), kind=kind,
                               line_start=ln, line_end=ln + 20,
                               signature=f"type {m.group(1)} {m.group(2)}"))

    for block in _GO_IMPORT_BLOCK.finditer(source):
        for s in _GO_STR_LIT.finditer(block.group(1)):
            xrefs.append(XRef("", s.group(1), "", "import"))
    for m in _GO_IMPORT_BARE.finditer(source):
        xrefs.append(XRef("", m.group(1), "", "import"))

    return symbols, xrefs


# ── Rust ──────────────────────────────────────────────────────────────────────

_RUST_FN     = re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(\w+)\s*(?:<[^>]*>)?\s*\(([^)]{0,120})\)", re.M)
_RUST_STRUCT = re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?struct\s+(\w+)", re.M)
_RUST_TRAIT  = re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?trait\s+(\w+)", re.M)
_RUST_IMPL   = re.compile(r"^impl(?:<[^>]*>)?\s+(?:(\w+)\s+for\s+)?(\w+)", re.M)
_RUST_USE    = re.compile(r"^use\s+([^;]+);", re.M)
_RUST_ENUM   = re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?enum\s+(\w+)", re.M)


def _parse_rust(source: str) -> tuple[list[SymInfo], list[XRef]]:
    symbols: list[SymInfo] = []
    xrefs:   list[XRef]   = []

    for m in _RUST_FN.finditer(source):
        ln     = _lineno(source, m.start())
        before = source[max(0, m.start() - 15):m.start() + 5]
        kind   = "async_function" if "async" in before else "function"
        symbols.append(SymInfo(name=m.group(1), kind=kind,
                               line_start=ln, line_end=ln + 20,
                               signature=f"fn {m.group(1)}({m.group(2)})"))

    for m in _RUST_STRUCT.finditer(source):
        ln = _lineno(source, m.start())
        symbols.append(SymInfo(name=m.group(1), kind="struct",
                               line_start=ln, line_end=ln + 20,
                               signature=f"struct {m.group(1)}"))

    for m in _RUST_TRAIT.finditer(source):
        ln = _lineno(source, m.start())
        symbols.append(SymInfo(name=m.group(1), kind="interface",
                               line_start=ln, line_end=ln + 20,
                               signature=f"trait {m.group(1)}"))

    for m in _RUST_ENUM.finditer(source):
        ln = _lineno(source, m.start())
        symbols.append(SymInfo(name=m.group(1), kind="enum",
                               line_start=ln, line_end=ln + 10,
                               signature=f"enum {m.group(1)}"))

    for m in _RUST_USE.finditer(source):
        xrefs.append(XRef("", m.group(1).strip(), "", "import"))

    return symbols, xrefs


# ── Java / C# ─────────────────────────────────────────────────────────────────

_JAVA_CLASS  = re.compile(r"(?:public|private|protected|abstract|\s)+class\s+(\w+)(?:\s+extends\s+(\w+))?", re.M)
_JAVA_IFACE  = re.compile(r"(?:public\s+)?interface\s+(\w+)", re.M)
_JAVA_METHOD = re.compile(r"(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?(?:\w+(?:<[^>]*>)?\s+)+(\w+)\s*\(([^)]{0,120})\)\s*(?:throws\s+\w+\s*)?[{;]", re.M)
_JAVA_IMPORT = re.compile(r"^import\s+(?:static\s+)?([\w.]+(?:\.\*)?);", re.M)
_CS_CLASS    = re.compile(r"(?:public|private|internal|protected|abstract|sealed|\s)+class\s+(\w+)", re.M)
_CS_IFACE    = re.compile(r"(?:public\s+)?interface\s+(I\w+)", re.M)
_CS_METHOD   = re.compile(r"(?:public|private|internal|protected)\s+(?:static\s+)?(?:async\s+)?(?:override\s+)?(?:\w+(?:<[^>]*>)?\s+)+(\w+)\s*\(([^)]{0,120})\)", re.M)
_CS_USING    = re.compile(r"^using\s+(?:static\s+)?(?:\w+\s*=\s*)?([\w.]+);", re.M)


def _parse_java_cs(source: str, lang: str) -> tuple[list[SymInfo], list[XRef]]:
    symbols: list[SymInfo] = []
    xrefs:   list[XRef]   = []

    cls_pat = _CS_CLASS   if lang == "csharp" else _JAVA_CLASS
    ifc_pat = _CS_IFACE   if lang == "csharp" else _JAVA_IFACE
    mth_pat = _CS_METHOD  if lang == "csharp" else _JAVA_METHOD
    imp_pat = _CS_USING   if lang == "csharp" else _JAVA_IMPORT

    for m in cls_pat.finditer(source):
        ln   = _lineno(source, m.start())
        name = m.group(1)
        base = (m.group(2) if m.lastindex and m.lastindex >= 2 else "") or ""
        symbols.append(SymInfo(name=name, kind="class",
                               line_start=ln, line_end=ln + 50,
                               signature=f"class {name}" + (f" extends {base}" if base else "")))
        if base:
            xrefs.append(XRef(name, "", base, "inherit"))

    for m in ifc_pat.finditer(source):
        ln = _lineno(source, m.start())
        symbols.append(SymInfo(name=m.group(1), kind="interface",
                               line_start=ln, line_end=ln + 30,
                               signature=f"interface {m.group(1)}"))

    for m in mth_pat.finditer(source):
        ln = _lineno(source, m.start())
        symbols.append(SymInfo(name=m.group(1), kind="method",
                               line_start=ln, line_end=ln + 20,
                               signature=f"{m.group(1)}({m.group(2)})"))

    for m in imp_pat.finditer(source):
        xrefs.append(XRef("", m.group(1), "", "import"))

    return symbols, xrefs


# ── Generic fallback ──────────────────────────────────────────────────────────

_GENERIC_FN = re.compile(
    r"(?:^|\s)(?:def|function|func|fn|sub|procedure|method)\s+(\w+)\s*\(",
    re.M | re.I,
)


def _parse_generic(source: str) -> tuple[list[SymInfo], list[XRef]]:
    symbols: list[SymInfo] = []
    for m in _GENERIC_FN.finditer(source):
        ln = _lineno(source, m.start())
        symbols.append(SymInfo(name=m.group(1), kind="function",
                               line_start=ln, line_end=ln + 10))
    return symbols, []


# ── Metrics ───────────────────────────────────────────────────────────────────

def _metrics(source: str, symbols: list[SymInfo]) -> dict:
    lines = source.splitlines()
    total = len(lines)
    comment = sum(
        1 for ln in lines
        if ln.strip().startswith(("#", "//", "/*", " *", "--", ";;", "<!--"))
    )
    blank = sum(1 for ln in lines if not ln.strip())
    fns   = [s for s in symbols if "function" in s.kind or s.kind == "method"]
    avg_fn = (sum(s.line_end - s.line_start for s in fns) / len(fns)
              if fns else 0)
    return {
        "line_count":     total,
        "code_lines":     total - comment - blank,
        "comment_ratio":  round(comment / max(total, 1), 3),
        "blank_ratio":    round(blank / max(total, 1), 3),
        "avg_fn_length":  round(avg_fn, 1),
        "symbol_count":   len(symbols),
        "class_count":    sum(1 for s in symbols if s.kind == "class"),
        "function_count": len(fns),
    }


# ── Pattern detector ──────────────────────────────────────────────────────────

def _detect_patterns(source: str, symbols: list[SymInfo]) -> list[PatternHit]:
    hits:     list[PatternHit] = []
    src_low   = source.lower()
    names     = {s.name.lower() for s in symbols}
    fn_names  = {s.name.lower() for s in symbols
                 if "function" in s.kind or s.kind == "method"}

    # Singleton
    if (("_instance" in src_low or "_singleton" in src_low)
            and any("instance" in n for n in fn_names)):
        hits.append(PatternHit("Singleton", 0.80,
                               "_instance field + get_instance pattern"))

    # Factory
    if (any("factory" in n for n in names)
            or sum(1 for n in fn_names if n.startswith(("create_", "make_", "build_"))) >= 2):
        ev = next((n for n in names if "factory" in n), "create_*/make_* functions")
        hits.append(PatternHit("Factory", 0.75, ev))

    # Observer / EventBus
    ev_signals = sum(
        1 for n in fn_names
        if any(x in n for x in ("subscribe", "on_", "emit", "dispatch", "publish",
                                "notify", "listen", "fire", "trigger"))
    )
    if ev_signals >= 2:
        hits.append(PatternHit("Observer/EventBus", 0.80,
                               f"{ev_signals} subscribe/emit/notify functions"))

    # Repository / DAO
    if any(any(x in n for x in ("repository", "repo", "dao", "store", "gateway"))
           for n in names):
        ev = next((n for n in names
                   if any(x in n for x in ("repository", "repo", "dao"))), "data-access class")
        hits.append(PatternHit("Repository", 0.85, ev))

    # Builder
    builder_fns = [n for n in fn_names
                   if n.startswith("with_") or n.startswith("set_") or n == "build"]
    if len(builder_fns) >= 3:
        hits.append(PatternHit("Builder", 0.75,
                               f"chain: {', '.join(list(builder_fns)[:4])}"))

    # Command
    if (any("command" in n for n in names)
            and any(n in fn_names for n in ("execute", "undo", "redo"))):
        hits.append(PatternHit("Command", 0.80, "Command class + execute/undo"))

    # Strategy
    if (any("strategy" in n for n in names)
            or sum(1 for n in fn_names if "strategy" in n) >= 2):
        hits.append(PatternHit("Strategy", 0.70, "strategy naming pattern"))

    # Decorator (Python-style heavy usage)
    dec_count = source.count("\n@")
    if dec_count >= 4:
        hits.append(PatternHit("Decorator", 0.70, f"{dec_count} decorator applications"))

    # MVC/MVP
    mvc = sum(1 for n in names
              if any(x in n for x in ("model", "view", "controller", "presenter")))
    if mvc >= 2:
        hits.append(PatternHit("MVC/MVP", 0.70, f"{mvc} MVC-role names"))

    # Async-heavy
    async_count = src_low.count("async ") + src_low.count("await ")
    if async_count >= 6:
        hits.append(PatternHit("Async-heavy", 0.90,
                               f"{async_count} async/await uses"))

    # Anti-pattern: bare except swallow
    swallow = (source.count("except Exception: pass")
               + source.count("except:\n    pass")
               + source.count("except Exception:\n    pass"))
    if swallow >= 2:
        hits.append(PatternHit("AntiPattern:ErrorSuppression", 0.85,
                               f"{swallow} swallowed exceptions"))

    # Anti-pattern: magic strings
    string_lits = re.findall(r'"([^"\\]{4,30})"', source)
    unique_magic = {s for s in string_lits
                    if not s.startswith(("http", "//", "#", "\\n", "    "))}
    if len(unique_magic) > 25:
        hits.append(PatternHit("AntiPattern:MagicStrings", 0.65,
                               f"{len(unique_magic)} inline string literals"))

    return hits


# ── Dispatcher ────────────────────────────────────────────────────────────────

def parse_file(path: str, source: str) -> ParseResult:
    lang       = detect_language(path)
    line_count = source.count("\n") + 1

    if lang == "python":
        symbols, xrefs = _parse_python(source)
    elif lang in ("javascript", "typescript"):
        symbols, xrefs = _parse_js_ts(source, lang)
    elif lang == "go":
        symbols, xrefs = _parse_go(source)
    elif lang == "rust":
        symbols, xrefs = _parse_rust(source)
    elif lang in ("java", "csharp"):
        symbols, xrefs = _parse_java_cs(source, lang)
    else:
        symbols, xrefs = _parse_generic(source)

    patterns = _detect_patterns(source, symbols)
    met      = _metrics(source, symbols)

    return ParseResult(
        path=path, lang=lang, line_count=line_count,
        symbols=symbols, xrefs=xrefs, patterns=patterns, metrics=met,
    )
