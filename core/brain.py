"""core/brain.py — shim re-exporting Brain from DBOMBCENTRAL_WON.

See core/_won_shims.py for the loader.
"""
from __future__ import annotations

from core._won_shims import load_won_module

_mod = load_won_module("brain")
if _mod is None:
    raise ImportError(
        "Brain unavailable: DBOMBCENTRAL_WON/DBOMBCENTRAL/core/brain.py "
        "not found on disk."
    )

Brain = _mod.Brain
