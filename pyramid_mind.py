"""
pyramid_mind.py — Upper Layer: Conversational code intelligence engine.

Maintains a rolling session: which files/symbols have been discussed,
at what disclosure depth, and the conversation thread.

Disclosure model (progressive)
-------------------------------
  GIST     (1) — first mention: what it does, its pattern, its role
  SYNOPSIS (2) — second visit: how it works, call graph, key logic
  FULL     (3) — explicit request: complete source walk + all deps

Response modes
--------------
  local — deterministic, built from SQLite index (no LLM)
  llm   — Ollama/Mistral with tightly scoped prompt from index data

Public API
----------
  PyramidMind(index, use_llm)
  PyramidMind.ask(query)       -> CodeAnswer
  PyramidMind.clear_session()
  PyramidMind.session_summary() -> str
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

import requests

from pyramid_index import PyramidIndex
from intent_engine import parse_intent, IntentClass

# ── Config ─────────────────────────────────────────────────────────────────────

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral"
TIMEOUT      = 60

# ── Disclosure ────────────────────────────────────────────────────────────────

class DisclosureLevel(IntEnum):
    GIST     = 1
    SYNOPSIS = 2
    FULL     = 3


@dataclass
class DisclosureState:
    level:       DisclosureLevel = DisclosureLevel.GIST
    visit_count: int             = 0
    last_seen:   float           = field(default_factory=time.time)


# ── Session types ─────────────────────────────────────────────────────────────

@dataclass
class ConvTurn:
    query:   str
    answer:  str
    files:   list[str]
    symbols: list[str]
    ts:      float = field(default_factory=time.time)


@dataclass
class CodeAnswer:
    text:              str
    files_touched:     list[str]
    symbols_touched:   list[str]
    disclosure_level:  DisclosureLevel
    source:            str     # "local" | "llm"
    latency_ms:        float = 0.0

    def short_status(self) -> str:
        return (f"{self.disclosure_level.name}  ·  "
                f"{self.latency_ms:.0f}ms  ·  {self.source}")


# ── Mind engine ───────────────────────────────────────────────────────────────

_FULL_TRIGGERS = frozenset({
    "full source", "show me everything", "complete implementation",
    "entire file", "all of", "show all", "full code",
})

_SYNOPSIS_TRIGGERS = frozenset({
    "how does", "how do", "explain in detail", "walk me through",
    "deep dive", "implementation", "internals", "source",
})


class PyramidMind:
    def __init__(self, index: PyramidIndex, use_llm: bool = True):
        self._index      = index
        self._use_llm    = use_llm
        self._history:   list[ConvTurn]              = []
        self._disclosure: dict[str, DisclosureState] = {}

    # ── Public ─────────────────────────────────────────────────────────────────

    def ask(self, query: str) -> CodeAnswer:
        t0 = time.time()

        intent = parse_intent(query)
        files, symbols = self._resolve_scope(intent, query)

        for f in files:
            self._bump(f)

        level = max(
            (self._disclosure[f].level for f in files if f in self._disclosure),
            default=DisclosureLevel.GIST,
        )
        q_low = query.lower()
        if any(t in q_low for t in _FULL_TRIGGERS):
            level = DisclosureLevel.FULL
        elif any(t in q_low for t in _SYNOPSIS_TRIGGERS) and level < DisclosureLevel.SYNOPSIS:
            level = DisclosureLevel.SYNOPSIS

        context = self._build_context(files, symbols, level)

        if self._use_llm and self._ollama_alive():
            text, source = self._llm_response(query, context, level, intent.intent_class)
        else:
            text, source = self._local_response(files, symbols, level)

        self._history.append(ConvTurn(
            query=query, answer=text,
            files=files, symbols=symbols,
        ))

        return CodeAnswer(
            text=text,
            files_touched=files,
            symbols_touched=symbols,
            disclosure_level=level,
            source=source,
            latency_ms=round((time.time() - t0) * 1000, 1),
        )

    def clear_session(self) -> None:
        self._history.clear()
        self._disclosure.clear()

    def session_summary(self) -> str:
        if not self._history:
            return "No conversation yet."
        explored = set()
        for t in self._history:
            explored.update(t.files)
        avg = (sum(ds.level for ds in self._disclosure.values())
               / max(len(self._disclosure), 1))
        return (f"{len(self._history)} turns · "
                f"{len(explored)} file(s) explored · "
                f"avg depth {avg:.1f}/3")

    # ── Scope resolution ───────────────────────────────────────────────────────

    def _resolve_scope(self, intent, query: str) -> tuple[list[str], list[str]]:
        files:   list[str] = []
        symbols: list[str] = []
        seen_f: set[str] = set()
        seen_s: set[str] = set()

        def _add_file(p: str) -> None:
            if p not in seen_f:
                seen_f.add(p)
                files.append(p)

        def _add_sym(n: str) -> None:
            if n not in seen_s:
                seen_s.add(n)
                symbols.append(n)

        # Intent engine targets
        for t in intent.targets:
            if t.path:
                for r in self._index.query_files(pattern=t.path)[:3]:
                    _add_file(r.path)
            if t.symbol:
                for r in self._index.query_symbols(name=t.symbol)[:4]:
                    _add_sym(r.name)
                    _add_file(r.file)

        # Explicit file mentions (x.py, x.ts, etc.)
        for m in re.finditer(r'([\w./\\-]+\.\w{1,5})', query):
            for r in self._index.query_files(pattern=m.group(1))[:2]:
                _add_file(r.path)

        # PascalCase symbol hints
        for m in re.finditer(r'\b([A-Z][a-zA-Z0-9]{2,})\b', query):
            for r in self._index.query_symbols(name=m.group(1))[:2]:
                _add_sym(r.name)
                _add_file(r.file)

        # snake_case function hints
        for m in re.finditer(r'\b([a-z][a-z0-9_]{3,})\b', query):
            word = m.group(1)
            if word in {"what", "does", "show", "explain", "how", "tell",
                        "give", "list", "find", "which", "where", "this",
                        "that", "with", "from", "into", "also", "make"}:
                continue
            for r in self._index.query_symbols(name=word, limit=2):
                _add_sym(r.name)
                _add_file(r.file)

        files   = files[:6]
        symbols = symbols[:10]

        # Fallback: most recently indexed files
        if not files:
            for r in self._index.query_files()[:3]:
                files.append(r.path)

        return files, symbols

    # ── Disclosure tracking ────────────────────────────────────────────────────

    def _bump(self, key: str) -> None:
        if key not in self._disclosure:
            self._disclosure[key] = DisclosureState()
        ds = self._disclosure[key]
        ds.visit_count += 1
        ds.last_seen    = time.time()
        if ds.visit_count >= 2 and ds.level < DisclosureLevel.SYNOPSIS:
            ds.level = DisclosureLevel.SYNOPSIS
        elif ds.visit_count >= 4 and ds.level < DisclosureLevel.FULL:
            ds.level = DisclosureLevel.FULL

    # ── Context builder ────────────────────────────────────────────────────────

    def _build_context(
        self,
        files:   list[str],
        symbols: list[str],
        level:   DisclosureLevel,
    ) -> str:
        parts: list[str] = [f"# Code Context  [depth={level.name}]\n"]

        for path in files[:6]:
            fname = Path(path).name
            fr_list = self._index.query_files(pattern=fname)
            fr = next((r for r in fr_list if r.path == path), None)
            if not fr:
                continue

            parts.append(f"## {fname}  [{fr.lang} · {fr.line_count} lines]")

            file_syms = self._index.symbols_for_file(path)[:20]
            if file_syms:
                parts.append("### Symbols")
                for s in file_syms:
                    line = f"  {s.kind:<16} {s.name}"
                    if s.signature:
                        line += f"  {s.signature[:70]}"
                    if s.docstring and level >= DisclosureLevel.SYNOPSIS:
                        line += f'\n    "{s.docstring[:100]}"'
                    parts.append(line)

            if level >= DisclosureLevel.SYNOPSIS:
                xrefs = self._index.xrefs_of(path)
                imports  = list(dict.fromkeys(
                    Path(x.to_file).name for x in xrefs if x.kind == "import"
                ))[:8]
                inherits = list(dict.fromkeys(
                    x.to_symbol for x in xrefs if x.kind == "inherit"
                ))[:5]
                if imports:
                    parts.append(f"### Imports: {', '.join(imports)}")
                if inherits:
                    parts.append(f"### Inherits: {', '.join(inherits)}")

            pats = self._index.patterns_in(path)
            if pats:
                pat_str = "  ·  ".join(
                    f"{p.pattern} ({p.confidence:.0%})" for p in pats[:5]
                )
                parts.append(f"### Patterns: {pat_str}")

            if level == DisclosureLevel.FULL:
                try:
                    src = Path(path).read_text(encoding="utf-8", errors="replace")
                    snippet = "\n".join(src.splitlines()[:160])
                    parts.append("### Source (first 160 lines)")
                    parts.append("```")
                    parts.append(snippet)
                    parts.append("```")
                except OSError:
                    pass

            parts.append("")

        # Previous conversation (last 3 turns for context chaining)
        if self._history:
            parts.append("## Conversation History")
            for turn in self._history[-3:]:
                parts.append(f"Q: {turn.query[:100]}")
                parts.append(f"A: {turn.answer[:180]}")
                parts.append("")

        return "\n".join(parts)

    # ── LLM response ──────────────────────────────────────────────────────────

    def _ollama_alive(self) -> bool:
        try:
            r = requests.get("http://localhost:11434/api/tags", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    def _llm_response(
        self,
        query:        str,
        context:      str,
        level:        DisclosureLevel,
        intent_class: IntentClass,
    ) -> tuple[str, str]:
        depth_instr = {
            DisclosureLevel.GIST:     (
                "Give a concise high-level answer: what the code does, "
                "its design pattern, and its role in the system."
            ),
            DisclosureLevel.SYNOPSIS: (
                "Give implementation-level detail: how the code works, "
                "key algorithms, what it calls, what calls it."
            ),
            DisclosureLevel.FULL:     (
                "Give a thorough analysis: walk through the source, "
                "all dependencies, entry points, and usage examples."
            ),
        }[level]

        system = (
            "You are STRATUM, a local code intelligence assistant. "
            "Reference specific file names, symbols, and line numbers. "
            "Do not hallucinate symbols not present in the context. "
            "Be direct and precise — no filler. "
            f"Depth: {depth_instr}"
        )
        prompt = f"{context}\n\n---\nUser: {query}"

        try:
            resp = requests.post(
                OLLAMA_URL,
                json={
                    "model":   OLLAMA_MODEL,
                    "prompt":  f"{system}\n\n{prompt}",
                    "stream":  False,
                    "options": {"temperature": 0.1, "num_predict": 900},
                },
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            text = resp.json().get("response", "").strip()
            return text or "[LLM returned empty response]", "llm"
        except Exception as e:
            return f"[LLM unavailable — {e}]", "local"

    # ── Local (no-LLM) response ────────────────────────────────────────────────

    def _local_response(
        self,
        files:   list[str],
        symbols: list[str],
        level:   DisclosureLevel,
    ) -> tuple[str, str]:
        lines = [f"**[Index view · {level.name}]**\n"]

        for path in files[:5]:
            fname = Path(path).name
            lines.append(f"**{fname}**")
            syms = self._index.symbols_for_file(path)[:12]
            for s in syms:
                entry = f"  `{s.kind}` **{s.name}**"
                if s.signature:
                    entry += f"  `{s.signature[:60]}`"
                if s.docstring:
                    entry += f"\n    › {s.docstring[:80]}"
                lines.append(entry)
            pats = self._index.patterns_in(path)
            if pats:
                lines.append("  Patterns: " + ", ".join(
                    p.pattern for p in pats[:4]
                ))
            lines.append("")

        if symbols:
            lines.append(f"Symbols matched: `{'`, `'.join(symbols)}`")

        lines.append("\n_LLM offline — showing raw index data._")
        return "\n".join(lines), "local"
