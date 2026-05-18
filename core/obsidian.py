"""core/obsidian.py — shim re-exporting ObsidianWriter from DBOMBCENTRAL_WON.

See core/_won_shims.py for the loader.
"""
from __future__ import annotations

from core._won_shims import load_won_module

_mod = load_won_module("obsidian")
if _mod is None:
    raise ImportError(
        "ObsidianWriter unavailable: DBOMBCENTRAL_WON/DBOMBCENTRAL/core/"
        "obsidian.py not found on disk."
    )

ObsidianWriter = _mod.ObsidianWriter
