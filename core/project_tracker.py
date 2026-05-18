"""core/project_tracker.py — shim re-exporting ProjectTracker from DBOMBCENTRAL_WON.

See core/_won_shims.py for the loader.
"""
from __future__ import annotations

from core._won_shims import load_won_module

_mod = load_won_module("project_tracker")
if _mod is None:
    raise ImportError(
        "ProjectTracker unavailable: DBOMBCENTRAL_WON/DBOMBCENTRAL/core/"
        "project_tracker.py not found on disk."
    )

ProjectTracker = _mod.ProjectTracker
