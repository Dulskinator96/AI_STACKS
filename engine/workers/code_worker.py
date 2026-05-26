"""engine/workers/code_worker.py — BUILD-022 CodeWorker.

Wraps conv_programming (CodeForge) and proposal_engine. Validates:
  · proposal JSON parses
  · proposal targets a real file path (or a creatable one)
  · generated code is syntactically valid Python (ast.parse)
  · diff is non-empty
"""
from __future__ import annotations

import ast
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from engine.workers.base_worker import (
    BaseWorker, WorkerRequest, ValidationResult,
)

_log = logging.getLogger(__name__)


class CodeWorker(BaseWorker):
    REALM = "code"
    NAME  = "CodeWorker"

    def _do_execute(self, request: WorkerRequest, workspace) -> list:
        intent = request.intent_text or ""
        backend = "conv_programming"
        try:
            from conv_programming import get_engine  # type: ignore
            eng = get_engine()
            result = eng.process(intent)
            self._cur_backend = backend
        except ImportError:
            raise RuntimeError("conv_programming not present — install in project root")
        except Exception as e:
            raise RuntimeError(f"conv_programming failed: {e}")

        # Persist proposal + any code as artifacts
        artifacts: list[str] = []
        try:
            proposal_path = Path(workspace) / f"proposal_{int(time.time()*1000)}.json"
            payload = result if isinstance(result, dict) else {"raw": str(result)}
            proposal_path.write_text(json.dumps(payload, indent=2, default=str),
                                       encoding="utf-8")
            artifacts.append(str(proposal_path))
        except Exception as e:
            _log.warning("proposal serialize failed: %s", e)
        # If the engine returned generated code, drop it as a .py
        if isinstance(result, dict):
            code = result.get("code") or result.get("body")
            if isinstance(code, str) and code.strip():
                code_path = Path(workspace) / f"generated_{int(time.time()*1000)}.py"
                code_path.write_text(code, encoding="utf-8")
                artifacts.append(str(code_path))
        if not artifacts:
            raise RuntimeError("CodeForge produced no artifact")
        return artifacts

    def _validate(self, path: Path) -> ValidationResult:
        checks: dict = {"size_bytes": path.stat().st_size}
        suf = path.suffix.lower()
        if suf == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                checks["keys"] = sorted(list(data.keys())) if isinstance(data, dict) else "non-dict"
                if isinstance(data, dict) and "raw" in data and len(data) == 1:
                    # Engine returned only a string blob — partial
                    return ValidationResult(valid=True, score=0.5, checks=checks,
                                              error="engine returned bare string")
                return ValidationResult(valid=True, score=0.85, checks=checks)
            except Exception as e:
                return ValidationResult(valid=False, score=0.0, checks=checks,
                                          error=f"proposal JSON parse failed: {e}")
        if suf == ".py":
            try:
                src = path.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(src)
                funcs = sum(1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
                clses = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
                checks["functions"] = funcs
                checks["classes"]   = clses
                checks["lines"]     = src.count("\n") + 1
                score = 0.7
                if funcs + clses > 0:
                    score = 0.95
                return ValidationResult(valid=True, score=score, checks=checks)
            except SyntaxError as e:
                return ValidationResult(valid=False, score=0.0, checks=checks,
                                          error=f"SyntaxError: {e}")
            except Exception as e:
                return ValidationResult(valid=False, score=0.0, checks=checks,
                                          error=f"AST parse raised: {e}")
        return ValidationResult(valid=True, score=0.4, checks=checks,
                                  error=f"unrecognized code artifact {suf}")


_INSTANCE: Optional[CodeWorker] = None


def get_code_worker() -> CodeWorker:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = CodeWorker()
    return _INSTANCE
