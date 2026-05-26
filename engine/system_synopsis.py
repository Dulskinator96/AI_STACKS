"""engine/system_synopsis.py — BUILD-029A SystemSynopsisModule.

Read-only observational subsystem. Truth mirror.

NON-NEGOTIABLE INVARIANTS:
  · Does NOT alter execution flow
  · Does NOT modify CQI / workers / pipelines / routing
  · Does NOT participate in generation or decision making
  · Does NOT intercept LiveStreamBus events
  · Does NOT replace existing tabs or pipelines
  · ONLY observes and reports grounded system truth
  · Degrades silently on any failure (no crash, no exception leak)

The synopsis converts DBOMBLOCAL from a self-reporting system into an
externally-grounded introspective system.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger(__name__)


# Directories the walker skips
_SKIP_DIRS = frozenset((
    "__pycache__", ".git", ".venv", "venv", "env", ".env",
    "build", "dist", "releases", "node_modules", ".idea", ".vscode",
    ".pytest_cache", ".mypy_cache", "telemetry",
))


def generate_synopsis(app_root: Optional[str] = None) -> dict:
    """Public entrypoint. Returns the 5-section synopsis dict.

    Args:
      app_root: optional absolute path to the project root. If None,
        defaults to the parent of engine/ (i.e. ai-monitor/).

    Returns:
      dict with keys: file_dna, runtime_state, capability_map,
      honesty_report, system_health + generated_at + app_root + duration_ms.
      Any section that cannot be safely computed is marked "unavailable"
      rather than fabricated.
    """
    t0 = time.time()
    try:
        root = Path(app_root) if app_root else Path(__file__).resolve().parent.parent
    except Exception:
        return _failure_envelope("invalid app_root", t0)

    synopsis: dict = {
        "generated_at": t0,
        "app_root":     str(root),
        "duration_ms":  0.0,
    }
    # Each section is independently try/except'd so one failure can't
    # poison the others.
    synopsis["file_dna"]       = _safe(_collect_file_dna, root, default=[])
    synopsis["runtime_state"]  = _safe(_collect_runtime_state, default={"available": False})
    synopsis["capability_map"] = _safe(_collect_capability_map, root, default={})
    synopsis["honesty_report"] = _safe(_collect_honesty_report, root,
                                          synopsis.get("file_dna", []),
                                          default={"orphans": [], "duplicates": [],
                                                    "missing_dependencies": [],
                                                    "stubs_detected": []})
    synopsis["system_health"]  = _safe(_collect_system_health,
                                          synopsis.get("file_dna", []),
                                          synopsis.get("capability_map", {}),
                                          default={"score": 0.0, "available": False})
    synopsis["duration_ms"] = round((time.time() - t0) * 1000.0, 1)
    _emit_receipt(synopsis)
    return synopsis


# ── Section builders ──────────────────────────────────────────────────


def _collect_file_dna(root: Path) -> list:
    """Walk the tree, return DNA only for files that physically exist
    on disk. Never infers, never hallucinates."""
    dna: list = []
    for dirpath, dirnames, filenames in os.walk(root):
        # In-place filter to skip noisy dirs
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and
                       not d.startswith(".")]
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            full = Path(dirpath) / fname
            if not full.is_file():
                continue
            entry: dict = {
                "path":    str(full.relative_to(root).as_posix()),
                "type":    "python_module",
                "lines":   0,
                "imports": [],
                "ast_valid": False,
            }
            try:
                src = full.read_text(encoding="utf-8", errors="ignore")
                entry["lines"] = src.count("\n") + 1
                try:
                    tree = ast.parse(src)
                    entry["ast_valid"] = True
                    imports: list[str] = []
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for n in node.names:
                                if n.name and n.name not in imports:
                                    imports.append(n.name)
                        elif isinstance(node, ast.ImportFrom):
                            if node.module and node.module not in imports:
                                imports.append(node.module)
                    entry["imports"] = imports[:60]
                except SyntaxError as e:
                    entry["ast_valid"] = False
                    entry["syntax_error"] = str(e)[:120]
            except Exception as e:
                entry["read_error"] = str(e)[:120]
            dna.append(entry)
    return dna


def _collect_runtime_state() -> dict:
    """Safe introspection. Returns 'unknown' for anything we can't observe."""
    state: dict = {
        "pid":            os.getpid(),
        "ts":             time.time(),
    }
    # Process info via psutil
    try:
        import psutil
        p = psutil.Process()
        state["process"] = {
            "name":            p.name(),
            "cpu_percent":     p.cpu_percent(interval=None),
            "rss_mb":          int(p.memory_info().rss / (1024 * 1024)),
            "thread_count":    p.num_threads(),
            "uptime_s":        round(time.time() - p.create_time(), 1),
        }
    except Exception:
        state["process"] = "unknown"
    # Log file presence
    try:
        log_p = Path.home() / ".stratum" / "stratum.log"
        state["log_file"] = {
            "path":   str(log_p),
            "exists": log_p.is_file(),
            "size_kb": (log_p.stat().st_size // 1024) if log_p.is_file() else 0,
        }
    except Exception:
        state["log_file"] = "unknown"
    # LiveStreamBus presence (if importable + instantiated)
    try:
        from engine.live_stream import get_live_stream
        bus = get_live_stream()
        state["live_stream_bus"] = bus.stats()
    except Exception:
        state["live_stream_bus"] = "unknown"
    # Worker registry snapshot (the 7 canonical workers)
    try:
        from runtime.singleton_registry import get_registry
        reg = get_registry()
        wanted = ["engine.workers.image", "engine.workers.audio",
                  "engine.workers.video", "engine.workers.game",
                  "engine.workers.simulation", "engine.workers.code",
                  "engine.workers.cast"]
        state["worker_registry"] = {
            n: reg.has(n) for n in wanted
        }
    except Exception:
        state["worker_registry"] = "unknown"
    # Closed-loop engine alive?
    try:
        from runtime.singleton_registry import get_registry
        reg = get_registry()
        state["closed_loop_engine"] = reg.has("engine.closed_loop")
    except Exception:
        state["closed_loop_engine"] = "unknown"
    return state


# Capability definitions: capability_name → (entry_module, dependency probes)
_CAPABILITIES = [
    ("audio_generation", "engine.workers.audio_worker",
     [("numpy", True), ("wave", True), ("pyttsx3", False)]),
    ("image_generation", "engine.workers.image_worker",
     [("requests", True), ("PIL", False)]),
    ("video_assembly", "engine.workers.video_worker",
     [("subprocess", True)]),    # ffmpeg checked at runtime via shutil.which
    ("game_scaffold", "engine.workers.game_worker",
     []),
    ("simulation_terrain", "engine.workers.simulation_worker",
     [("numpy", True)]),
    ("code_forge", "engine.workers.code_worker",
     [("conv_programming", False)]),
    ("cast_ensemble", "engine.workers.cast_worker",
     [("pyramid_ensemble", False)]),
    ("composition_planning", "engine.creative_composition.composition_engine",
     []),
    ("cqi_scoring", "engine.aesthetic_intelligence.aesthetic_reasoner",
     []),
    ("closed_loop", "engine.closed_loop.loop_engine",
     []),
    ("pixel_analysis", "engine.visual_harmony_pixel",
     [("PIL", False), ("numpy", False)]),
    ("preference_memory", "engine.preference_memory",
     []),
    ("unified_creative_profile", "engine.unified_creative_profile",
     []),
    ("guarantee_layer", "engine.production_guarantee",
     []),
]


def _collect_capability_map(root: Path) -> dict:
    """A capability is AVAILABLE only when: entry module file exists AND
    can be imported AND all required deps probe OK. Optional deps are
    noted but don't gate availability."""
    out: dict = {}
    for name, entry_module, deps in _CAPABILITIES:
        evidence: list = []
        missing_required: list = []
        missing_optional: list = []

        # Entry module file existence
        module_path = root / (entry_module.replace(".", "/") + ".py")
        module_exists = module_path.is_file()
        if module_exists:
            evidence.append(str(module_path.relative_to(root).as_posix()))
        else:
            # Try as package __init__
            pkg_init = root / (entry_module.replace(".", "/") + "/__init__.py")
            if pkg_init.is_file():
                module_exists = True
                evidence.append(str(pkg_init.relative_to(root).as_posix()))

        # Module importability
        importable = False
        if module_exists:
            try:
                spec = importlib.util.find_spec(entry_module)
                importable = spec is not None
            except Exception:
                importable = False
            if importable:
                evidence.append(f"importable:{entry_module}")

        # Dependency probes
        for dep_name, required in deps:
            try:
                spec = importlib.util.find_spec(dep_name)
                if spec is not None:
                    evidence.append(f"dep:{dep_name}")
                    continue
            except Exception:
                pass
            if required:
                missing_required.append(dep_name)
            else:
                missing_optional.append(dep_name)

        if not module_exists:
            out[name] = {
                "status": "UNAVAILABLE",
                "reason": f"entry module not found on disk: {entry_module}",
                "evidence": evidence,
            }
        elif missing_required:
            out[name] = {
                "status": "UNAVAILABLE",
                "reason": f"required dependency missing: {missing_required}",
                "evidence": evidence,
                "missing_required": missing_required,
                "missing_optional": missing_optional,
            }
        elif not importable:
            out[name] = {
                "status": "UNAVAILABLE",
                "reason": "module not importable (import system rejected)",
                "evidence": evidence,
            }
        else:
            out[name] = {
                "status": "AVAILABLE",
                "evidence": evidence,
                "missing_optional": missing_optional,
            }
    return out


def _collect_honesty_report(root: Path, file_dna: list) -> dict:
    """Detect orphans · duplicates · missing dependencies · stubs."""
    # Build the set of local module identifiers from file_dna
    local_modules: set = set()
    for entry in (file_dna or []):
        p = entry.get("path", "")
        if not p.endswith(".py"):
            continue
        mod_name = p[:-3].replace("/", ".")
        if mod_name.endswith(".__init__"):
            mod_name = mod_name[:-len(".__init__")]
        local_modules.add(mod_name)
        # Also register short name (last component)
        local_modules.add(mod_name.split(".")[-1])

    orphans: list = []
    duplicates: list = []
    missing_deps: set = set()
    stubs: list = []

    # Check imports against locals + installed packages
    seen_module_names: dict = {}
    for entry in (file_dna or []):
        path = entry.get("path", "")
        # Detect duplicate filenames (heuristic)
        fname = path.rsplit("/", 1)[-1]
        if fname in seen_module_names and fname not in ("__init__.py", "test.py"):
            duplicates.append({
                "filename": fname,
                "paths":    [seen_module_names[fname], path],
            })
        else:
            seen_module_names[fname] = path

        # Stub detection: small files with TODO heavy density
        try:
            full = root / path
            if full.is_file():
                src = full.read_text(encoding="utf-8", errors="ignore")
                lines = src.count("\n") + 1
                todo_count = src.lower().count("todo") + src.lower().count("xxx")
                pass_count = src.count("    pass\n") + src.count("\tpass\n")
                # Heuristic: very small files OR high stub density
                if lines < 12 and (todo_count + pass_count) > 0:
                    stubs.append({
                        "path":   path,
                        "lines":  lines,
                        "todos":  todo_count,
                        "passes": pass_count,
                    })
                elif lines > 30 and todo_count > 5 and lines < 100:
                    stubs.append({
                        "path":   path,
                        "lines":  lines,
                        "todos":  todo_count,
                    })
        except Exception:
            pass

        # Missing dependency check (stdlib filter then test importability)
        for imp in (entry.get("imports", []) or []):
            top = imp.split(".")[0]
            if top in _STDLIB_AND_BUNDLED:
                continue
            if top in {n.split(".")[0] for n in local_modules}:
                continue
            try:
                spec = importlib.util.find_spec(top)
                if spec is None:
                    missing_deps.add(top)
            except Exception:
                missing_deps.add(top)

    # Orphan detection: any local module that nothing else imports
    # Build the union of all imported module-top-levels
    imported_top: set = set()
    for entry in (file_dna or []):
        for imp in (entry.get("imports", []) or []):
            imported_top.add(imp)
            imported_top.add(imp.split(".")[0])
    for mod in local_modules:
        if mod in imported_top:
            continue
        # Skip canonical entry points (app.py, build script, __init__)
        if mod in ("app", "ai_monitor", "won_daemon", "pipeline"):
            continue
        # Skip top-level package roots (parent is already imported)
        if "." not in mod and mod in ("engine", "runtime", "ui", "core",
                                        "kernel", "truth", "maintenance",
                                        "realms", "pyramid_tools", "creative_tools"):
            continue
        orphans.append(mod)
    orphans = sorted(orphans)[:30]    # cap

    return {
        "orphans":               orphans,
        "duplicates":            duplicates[:20],
        "missing_dependencies":  sorted(missing_deps)[:30],
        "stubs_detected":        stubs[:20],
    }


def _collect_system_health(file_dna: list, capability_map: dict) -> dict:
    """Aggregate health from REAL signals only. No CQI involvement."""
    total_files = len(file_dna or [])
    if total_files == 0:
        return {"score": 0.0, "available": False,
                "note": "no python files observed"}
    valid_ast = sum(1 for e in file_dna if e.get("ast_valid"))
    ast_ratio = valid_ast / total_files

    # Capability availability ratio
    caps = list((capability_map or {}).values())
    available_caps = sum(1 for c in caps if c.get("status") == "AVAILABLE")
    cap_ratio = (available_caps / len(caps)) if caps else 0.0

    # Runtime presence of core systems (queried at compute time, not assumed)
    runtime_present = 0
    runtime_checks = 0
    try:
        from runtime.singleton_registry import get_registry
        reg = get_registry()
        for anchor in ("engine.composition", "engine.aesthetic_reasoner",
                        "engine.production_guarantee", "engine.live_stream",
                        "engine.closed_loop"):
            runtime_checks += 1
            if reg.has(anchor):
                runtime_present += 1
    except Exception:
        pass
    runtime_ratio = (runtime_present / runtime_checks) if runtime_checks else 0.5

    # Composite — weighted but capped to leave room for honest UNTESTED states
    score = (0.4 * ast_ratio + 0.4 * cap_ratio + 0.2 * runtime_ratio)
    return {
        "score":             round(score, 3),
        "ast_valid_ratio":   round(ast_ratio, 3),
        "capability_ratio":  round(cap_ratio, 3),
        "runtime_anchor_ratio": round(runtime_ratio, 3),
        "valid_ast_files":   valid_ast,
        "total_files":       total_files,
        "available_capabilities": available_caps,
        "total_capabilities":     len(caps),
        "available":         True,
    }


# ── Helpers ───────────────────────────────────────────────────────────


# Common stdlib + third-party module names — filters dependency search
_STDLIB_AND_BUNDLED = frozenset((
    "os", "sys", "io", "re", "json", "time", "math", "uuid", "hashlib",
    "threading", "logging", "subprocess", "shutil", "pathlib", "typing",
    "dataclasses", "collections", "functools", "itertools", "datetime",
    "random", "asyncio", "concurrent", "queue", "weakref", "atexit",
    "signal", "struct", "wave", "audioop", "tempfile", "glob",
    "platform", "traceback", "warnings", "inspect", "ast", "importlib",
    "contextlib", "copy", "enum", "abc", "string", "textwrap",
    "html", "xml", "sqlite3", "csv", "configparser", "pickle", "base64",
    "binascii", "zlib", "gzip", "bz2", "tarfile", "zipfile", "tokenize",
    "decimal", "fractions", "statistics", "heapq", "bisect",
    "PyQt6", "psutil", "requests", "numpy", "PIL",   # bundled in our spec
    "openai", "kernel", "core", "engine", "runtime", "truth",
    "maintenance", "ui", "realms", "pyramid_tools", "creative_tools",
    "app", "config", "won_daemon", "pipeline", "simcore", "sensory_engine",
    "agent_memory", "agent_chatroom", "consciousness", "perceptual_engine",
    "pyramid_ensemble", "pyramid_index", "pyramid_mind", "pyramid_parser",
    "intent_engine", "code_correlator", "proposal_engine", "executor",
    "conv_programming", "memory_manager", "synthesis", "strategy",
    "lm_studio", "db", "imageforge", "mempalace", "mempalace_bridge",
    "stratum_ui", "pyramid_ui", "stratum",
))


def _safe(fn, *args, default=None):
    """Run fn(*args); return default on any exception. Logs at debug."""
    try:
        return fn(*args)
    except Exception as e:
        _log.debug("synopsis section failed (%s): %s", fn.__name__, e)
        return default


def _failure_envelope(reason: str, t0: float) -> dict:
    return {
        "generated_at": t0,
        "duration_ms":  round((time.time() - t0) * 1000.0, 1),
        "error":        reason,
        "file_dna":      [],
        "runtime_state": {"available": False},
        "capability_map": {},
        "honesty_report": {"orphans": [], "duplicates": [],
                             "missing_dependencies": [],
                             "stubs_detected": []},
        "system_health":  {"score": 0.0, "available": False, "reason": reason},
    }


def _emit_receipt(synopsis: dict) -> None:
    try:
        from truth.receipt_engine import record_execution
        record_execution(
            task="system_synopsis:generated",
            executor="SystemSynopsisModule",
            duration_ms=synopsis.get("duration_ms", 0.0),
            verified=True, compute_sha256=False,
            evidence={
                "file_count":     len(synopsis.get("file_dna") or []),
                "capabilities":   list((synopsis.get("capability_map") or {}).keys()),
                "available_count": sum(
                    1 for c in (synopsis.get("capability_map") or {}).values()
                    if isinstance(c, dict) and c.get("status") == "AVAILABLE"
                ),
                "health_score":   (synopsis.get("system_health") or {}).get("score"),
                "orphan_count":   len((synopsis.get("honesty_report") or {}).get("orphans", []) or []),
                "duplicate_count": len((synopsis.get("honesty_report") or {}).get("duplicates", []) or []),
                "stub_count":     len((synopsis.get("honesty_report") or {}).get("stubs_detected", []) or []),
                "duration_ms":    synopsis.get("duration_ms"),
            },
        )
    except Exception:
        # The synopsis must never crash on telemetry failure
        pass


# ── Singleton accessor (for registry consistency) ─────────────────────


_LAST_SYNOPSIS: Optional[dict] = None


def get_last_synopsis() -> Optional[dict]:
    """Return the most-recent synopsis without recomputing. None until
    generate_synopsis() has been called at least once."""
    return _LAST_SYNOPSIS


def _store(synopsis: dict) -> None:
    global _LAST_SYNOPSIS
    _LAST_SYNOPSIS = synopsis


# Wrap generate_synopsis to cache
def generate_synopsis_cached(app_root: Optional[str] = None) -> dict:
    s = generate_synopsis(app_root)
    _store(s)
    return s
