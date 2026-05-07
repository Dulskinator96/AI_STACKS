"""
pyramid_tools — Agent Tool Registry for STRATUM Pyramid.

Top-tier free tools available to agents. No API keys required.
All tools execute locally and return plain-text results for LLM consumption.

Usage in agent prompts:
    TOOL: search_code | query=EnsembleOrchestrator | pattern=*.py
    TOOL: analyze_ast | file=pyramid_ensemble.py
    TOOL: run_python  | code=print(1+1)
    TOOL: check_syntax| code=def f(): pass
    TOOL: git_log     | n=10
    TOOL: lint_code   | file=app.py

The ToolDispatcher intercepts these lines and returns results inline.
"""
from pyramid_tools.registry import ToolRegistry, ToolDispatcher, get_dispatcher, get_registry

__all__ = ["ToolRegistry", "ToolDispatcher", "get_dispatcher", "get_registry"]
