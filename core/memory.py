"""core/memory.py — shim re-exporting WONMemory from DBOMBCENTRAL_WON.

See core/_won_shims.py for the loader. This file exists ONLY so
``from core.memory import WONMemory`` (used by pipeline.py and other
WON callers) resolves correctly when ai-monitor/core wins on sys.path.
"""
from __future__ import annotations

from core._won_shims import load_won_module

_mod = load_won_module("memory")
if _mod is None:
    raise ImportError(
        "WONMemory unavailable: DBOMBCENTRAL_WON/DBOMBCENTRAL/core/memory.py "
        "not found on disk. Install / restore the WON package."
    )

WONMemory = _mod.WONMemory
