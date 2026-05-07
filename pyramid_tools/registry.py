"""
pyramid_tools/registry.py — Tool registry and dispatcher.

ToolRegistry: maps tool names to callables with metadata.
ToolDispatcher: scans agent output for TOOL: lines, executes them,
                returns annotated results for re-injection into context.

Design principle: tools are deterministic Python functions.
No LLM involvement in tool execution — only in deciding to call them.
This eliminates hallucination from the tool-use layer entirely.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable, Optional

_log = logging.getLogger("stratum.tools")

# ── Tool metadata ─────────────────────────────────────────────────────────────

@dataclass
class ToolDef:
    name:        str
    description: str
    params:      list[str]          # required param names
    fn:          Callable[..., str] # always returns str (tool result)
    example:     str                # how to call it


# ── Registry ──────────────────────────────────────────────────────────────────

class ToolRegistry:
    """Central registry of all available agent tools."""

    def __init__(self):
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool: ToolDef) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[ToolDef]:
        return self._tools.get(name)

    def list_tools(self) -> str:
        """Returns a formatted tool catalog for injection into agent prompts."""
        lines = ["## Available Tools\n",
                 "Call a tool by writing: TOOL: tool_name | param=value | param=value\n"]
        for td in self._tools.values():
            lines.append(f"**{td.name}** — {td.description}")
            lines.append(f"  Params: {', '.join(td.params)}")
            lines.append(f"  Example: {td.example}\n")
        return "\n".join(lines)

    def all_names(self) -> list[str]:
        return list(self._tools.keys())


# ── Dispatcher ────────────────────────────────────────────────────────────────

# Pattern: TOOL: tool_name | key=value | key=value
_TOOL_RE = re.compile(
    r"TOOL:\s*(?P<name>\w+)\s*"
    r"(?:\|\s*(?P<params>[^|\n]+(?:\|[^|\n]+)*))?",
    re.IGNORECASE,
)


class ToolDispatcher:
    """
    Scans text for TOOL: directives, executes them, injects results.

    Usage:
        text_with_results = dispatcher.process(agent_output_text)

    Tool calls are replaced in-place with their results, formatted as:
        [TOOL RESULT: tool_name]
        <result text>
        [/TOOL RESULT]
    """

    def __init__(self, registry: ToolRegistry):
        self._registry = registry

    def process(self, text: str) -> str:
        """Execute all TOOL: directives found in text. Returns annotated text."""
        def replace_match(m: re.Match) -> str:
            name   = m.group("name").lower()
            params = self._parse_params(m.group("params") or "")
            td     = self._registry.get(name)
            if td is None:
                return (
                    f"{m.group(0)}\n"
                    f"[TOOL ERROR: '{name}' not found. "
                    f"Available: {', '.join(self._registry.all_names())}]"
                )
            try:
                result = td.fn(**params)
            except TypeError as e:
                result = f"[TOOL PARAM ERROR: {e}]"
            except Exception as e:
                result = f"[TOOL EXECUTION ERROR: {e}]"
                _log.warning(f"Tool {name} error: {e}")
            return (
                f"{m.group(0)}\n"
                f"[TOOL RESULT: {name}]\n{result}\n[/TOOL RESULT]"
            )

        return _TOOL_RE.sub(replace_match, text)

    @staticmethod
    def _parse_params(raw: str) -> dict[str, str]:
        params: dict[str, str] = {}
        for part in raw.split("|"):
            part = part.strip()
            if "=" in part:
                k, _, v = part.partition("=")
                params[k.strip()] = v.strip()
        return params


# ── Global registry singleton ─────────────────────────────────────────────────

_registry: Optional[ToolRegistry]   = None
_dispatcher: Optional[ToolDispatcher] = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _populate_registry(_registry)
    return _registry


def get_dispatcher() -> ToolDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = ToolDispatcher(get_registry())
    return _dispatcher


def _populate_registry(registry: ToolRegistry) -> None:
    """Wire all tool implementations into the registry at startup."""
    from pyramid_tools.code_tools import (
        tool_search_code, tool_read_file, tool_run_python,
        tool_analyze_ast, tool_check_syntax, tool_git_log,
        tool_diff_files, tool_run_tests, tool_lint_code,
    )
    from pyramid_tools.web_tools import tool_web_search, tool_fetch_url

    registry.register(ToolDef(
        name="search_code",
        description="Search the codebase for a pattern (ripgrep-style, regex ok)",
        params=["query", "pattern"],
        fn=tool_search_code,
        example="TOOL: search_code | query=EnsembleOrchestrator | pattern=*.py",
    ))
    registry.register(ToolDef(
        name="read_file",
        description="Read a file from the project root (optionally slice lines)",
        params=["file"],
        fn=tool_read_file,
        example="TOOL: read_file | file=pyramid_ensemble.py | start=1 | end=50",
    ))
    registry.register(ToolDef(
        name="run_python",
        description="Execute a Python snippet in a sandbox and return stdout",
        params=["code"],
        fn=tool_run_python,
        example="TOOL: run_python | code=print(2**10)",
    ))
    registry.register(ToolDef(
        name="analyze_ast",
        description="Return AST structure (classes, functions, imports) of a file",
        params=["file"],
        fn=tool_analyze_ast,
        example="TOOL: analyze_ast | file=intent_engine.py",
    ))
    registry.register(ToolDef(
        name="check_syntax",
        description="Validate Python syntax of a code snippet",
        params=["code"],
        fn=tool_check_syntax,
        example="TOOL: check_syntax | code=def f(x): return x+1",
    ))
    registry.register(ToolDef(
        name="git_log",
        description="Show recent git commit history",
        params=[],
        fn=tool_git_log,
        example="TOOL: git_log | n=10",
    ))
    registry.register(ToolDef(
        name="diff_files",
        description="Unified diff between two project files",
        params=["file1", "file2"],
        fn=tool_diff_files,
        example="TOOL: diff_files | file1=old_app.py | file2=app.py",
    ))
    registry.register(ToolDef(
        name="run_tests",
        description="Run pytest on a test file or directory",
        params=["path"],
        fn=tool_run_tests,
        example="TOOL: run_tests | path=tests/test_intent_engine.py",
    ))
    registry.register(ToolDef(
        name="lint_code",
        description="Lint a Python file with flake8",
        params=["file"],
        fn=tool_lint_code,
        example="TOOL: lint_code | file=proposal_engine.py",
    ))
    registry.register(ToolDef(
        name="web_search",
        description="DuckDuckGo web search — no API key required",
        params=["query"],
        fn=tool_web_search,
        example="TOOL: web_search | query=Python AST visitor pattern",
    ))
    registry.register(ToolDef(
        name="fetch_url",
        description="Fetch text content from a URL (robots.txt-aware)",
        params=["url"],
        fn=tool_fetch_url,
        example="TOOL: fetch_url | url=https://docs.python.org/3/library/ast.html",
    ))
