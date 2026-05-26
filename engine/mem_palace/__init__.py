"""engine/mem_palace/ — filesystem-backed EXECUTION LEDGER.

MemPalace records ONLY real worker executions that produced real, validated
files on disk. See memory_store.MemPalace for the governing rules.

    from engine.mem_palace import get_mem_palace, run_boot_check
"""
from engine.mem_palace.memory_store import (
    MemPalace, get_mem_palace,
    STATUS_COMPLETED, STATUS_FAILED, STATUS_UNAVAILABLE,
)
from engine.mem_palace.boot_check import run_boot_check, MemPalaceBootFailure

__all__ = [
    "MemPalace", "get_mem_palace",
    "STATUS_COMPLETED", "STATUS_FAILED", "STATUS_UNAVAILABLE",
    "run_boot_check", "MemPalaceBootFailure",
]
