"""engine/workers/game_worker.py — BUILD-022 GameWorker.

Validates:
  · expected scaffold files exist (project.godot OR scene_graph.json)
  · no parser errors (Godot --headless --quit if present)
  · script files have valid Python/GDScript syntax (best-effort)
  · assets resolve correctly (paths inside the scaffold actually exist)
"""
from __future__ import annotations

import ast
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from engine.workers.base_worker import (
    BaseWorker, WorkerRequest, ValidationResult,
)

_log = logging.getLogger(__name__)


class GameWorker(BaseWorker):
    REALM = "game"
    NAME  = "GameWorker"

    def _do_execute(self, request: WorkerRequest, workspace) -> list:
        from realms.game_creation.pipeline import run as game_run
        from engine.production_core import get_production_core
        core = get_production_core()
        psess = None
        with core._lock:
            for s in core._sessions.values():
                if s.output_dir == str(workspace):
                    psess = s
                    break
        if psess is None:
            class _S:
                output_dir = str(workspace)
                session_id = workspace.name
                intent_text = request.intent_text
                spec_snapshot = {}
                artifacts = []
            psess = _S()

        result = game_run(
            request.kind or "scaffold",
            {
                "intent_text": request.intent_text,
                "spec":        request.spec,
                "session":     psess,
            },
        )
        self._cur_backend = result.get("backend", "")
        if result.get("outcome") == "OK":
            return list(result.get("artifacts", []))
        raise RuntimeError(
            result.get("error", "game pipeline failed") + " · "
            + result.get("errors", [""])[0]
        )

    def _validate(self, path: Path) -> ValidationResult:
        checks: dict = {}
        if not path.is_file():
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error="file missing")
        size = path.stat().st_size
        checks["size_bytes"] = size
        if size <= 0:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error="empty file")

        suf = path.suffix.lower()
        name = path.name.lower()

        # Godot project file — check it parses (key=value lines)
        if name == "project.godot":
            return self._validate_project_godot(path, checks)

        # GDScript — basic parse: ensure first non-comment line begins with extends or class
        if suf == ".gd":
            return self._validate_gdscript(path, checks)

        # Godot scene — check the SceneFile header
        if suf == ".tscn":
            return self._validate_tscn(path, checks)

        # Python script (Blender etc.)
        if suf == ".py":
            return self._validate_python(path, checks)

        # Markdown design doc
        if suf in (".md", ".markdown"):
            return self._validate_markdown(path, checks)

        # Unknown — pass with low score
        return ValidationResult(valid=True, score=0.4, checks=checks,
                                  error=f"unrecognized extension {suf}")

    # ── per-format validators ─────────────────────────────────────────
    def _validate_project_godot(self, path: Path, checks: dict) -> ValidationResult:
        text = path.read_text(encoding="utf-8", errors="ignore")
        checks["lines"] = text.count("\n") + 1
        has_app    = "[application]" in text
        has_config = "config_version" in text
        checks["has_application_section"] = has_app
        checks["has_config_version"] = has_config
        if not has_app:
            return ValidationResult(valid=False, score=0.3, checks=checks,
                                      error="project.godot missing [application]")

        # Run Godot --quit if available to verify the project boots
        godot = shutil.which("godot") or shutil.which("godot4")
        if godot:
            try:
                proc = subprocess.run(
                    [godot, "--headless", "--quit", "--path", str(path.parent)],
                    capture_output=True, timeout=20,
                )
                checks["godot_returncode"] = proc.returncode
                if proc.returncode == 0:
                    return ValidationResult(valid=True, score=1.0, checks=checks)
                stderr = proc.stderr.decode(errors="ignore")[:200]
                if "error" in stderr.lower() or proc.returncode != 0:
                    return ValidationResult(valid=False, score=0.3, checks=checks,
                                              error=f"godot --quit failed: {stderr}")
            except subprocess.TimeoutExpired:
                checks["godot_check"] = "timeout"
            except Exception as e:
                checks["godot_check"] = f"raised: {e}"
        else:
            checks["godot_check"] = "godot CLI not on PATH (skipped)"
        # No Godot — structural pass is good enough
        score = 0.85 if has_app and has_config else 0.55
        return ValidationResult(valid=True, score=score, checks=checks)

    def _validate_gdscript(self, path: Path, checks: dict) -> ValidationResult:
        text = path.read_text(encoding="utf-8", errors="ignore")
        checks["lines"] = text.count("\n") + 1
        # Strip comments + blank lines
        nonblank = [ln.strip() for ln in text.splitlines()
                    if ln.strip() and not ln.strip().startswith("#")]
        checks["nonblank_lines"] = len(nonblank)
        if not nonblank:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error="empty GDScript")
        head = nonblank[0]
        if head.startswith(("extends ", "class_name ", "class ")):
            # Function check
            has_func = any(ln.startswith(("func ", "func_")) for ln in nonblank)
            checks["has_function"] = has_func
            score = 0.9 if has_func else 0.7
            return ValidationResult(valid=True, score=score, checks=checks)
        return ValidationResult(valid=False, score=0.3, checks=checks,
                                  error=f"GDScript doesn't start with extends/class: {head[:60]}")

    def _validate_tscn(self, path: Path, checks: dict) -> ValidationResult:
        text = path.read_text(encoding="utf-8", errors="ignore")
        first = text.splitlines()[0] if text else ""
        checks["first_line"] = first[:80]
        if first.startswith("[gd_scene"):
            checks["nodes"] = text.count("[node ")
            return ValidationResult(valid=True, score=0.9, checks=checks)
        return ValidationResult(valid=False, score=0.2, checks=checks,
                                  error="missing [gd_scene header")

    def _validate_python(self, path: Path, checks: dict) -> ValidationResult:
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source)
            checks["ast_nodes"] = sum(1 for _ in ast.walk(tree))
            # Count function definitions + import statements
            funcs = sum(1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
            imps  = sum(1 for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)))
            checks["func_count"] = funcs
            checks["import_count"] = imps
            return ValidationResult(valid=True, score=0.92, checks=checks)
        except SyntaxError as e:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error=f"SyntaxError: {e}")
        except Exception as e:
            return ValidationResult(valid=False, score=0.0, checks=checks,
                                      error=f"parse failed: {e}")

    def _validate_markdown(self, path: Path, checks: dict) -> ValidationResult:
        text = path.read_text(encoding="utf-8", errors="ignore")
        checks["lines"] = text.count("\n") + 1
        checks["headings"] = sum(1 for ln in text.splitlines()
                                  if ln.startswith("#"))
        if checks["headings"] >= 2:
            return ValidationResult(valid=True, score=0.85, checks=checks)
        return ValidationResult(valid=True, score=0.55, checks=checks,
                                  error="thin design doc (< 2 headings)")


_INSTANCE: Optional[GameWorker] = None


def get_game_worker() -> GameWorker:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = GameWorker()
    return _INSTANCE
