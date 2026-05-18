"""core/_won_shims.py — bridge between ai-monitor/core and DBOMBCENTRAL_WON.

Background:
    ai-monitor has its own ``core/`` package (services + profiler +
    state_manager + lifecycle). DBOMBCENTRAL_WON ships its own ``core/``
    with memory/brain/obsidian/project_tracker. When ai-monitor/core wins
    on sys.path (which it does for the frozen exe), pipeline.py's
    ``from core.memory import WONMemory`` raises ModuleNotFoundError,
    producing 139 spurious warnings per session.

This module loads the WON files directly via importlib (bypassing the
package machinery so there's no namespace collision) and re-exports
their canonical class symbols. The shim files in core/memory.py,
core/brain.py, core/obsidian.py, core/project_tracker.py defer to this
loader.

Best-effort: if DBOMBCENTRAL_WON isn't on disk (e.g., trimmed exe build),
the import returns None and the shim raises ImportError as before. The
caller in pipeline.py already wraps these imports in try/except.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger(__name__)

# Candidate locations for the WON core/ directory, in priority order.
_HERE = Path(__file__).resolve().parent.parent
_CANDIDATES = [
    _HERE / "DBOMBCENTRAL_WON" / "DBOMBCENTRAL" / "core",
    _HERE.parent / "DBOMBCENTRAL_WON" / "DBOMBCENTRAL" / "core",
]


def _won_core_dir() -> Optional[Path]:
    for p in _CANDIDATES:
        if p.is_dir():
            return p
    return None


_loaded_modules: dict[str, Any] = {}


def load_won_module(module_basename: str) -> Optional[Any]:
    """Load a single .py file from the WON core/ directory via importlib.

    Returns the loaded module object, or None if the file or directory
    is unavailable. Result is cached per process to avoid re-execution.
    """
    if module_basename in _loaded_modules:
        return _loaded_modules[module_basename]
    won_dir = _won_core_dir()
    if won_dir is None:
        _loaded_modules[module_basename] = None
        return None
    pyfile = won_dir / f"{module_basename}.py"
    if not pyfile.is_file():
        _loaded_modules[module_basename] = None
        return None
    # Make sure the WON DBOMBCENTRAL directory is on sys.path so the
    # loaded module's intra-package imports resolve (e.g., core.brain may
    # import sibling core.memory). We add the PARENT of core/ so
    # "from core.memory import X" inside DBOMBCENTRAL resolves correctly
    # IF the won-core ends up being the first `core` found on sys.path.
    # This sys.path adjustment is best-effort; the shim doesn't depend on
    # it for the direct importlib load below.
    won_parent = str(won_dir.parent)
    if won_parent not in sys.path:
        sys.path.append(won_parent)
    try:
        spec = importlib.util.spec_from_file_location(
            f"_won_{module_basename}", str(pyfile),
        )
        if spec is None or spec.loader is None:
            _loaded_modules[module_basename] = None
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _loaded_modules[module_basename] = mod
        _log.debug("WON shim loaded: %s → %s", module_basename, pyfile)
        return mod
    except Exception as exc:
        _log.warning("WON shim load failed for %s: %s", module_basename, exc)
        _loaded_modules[module_basename] = None
        return None
