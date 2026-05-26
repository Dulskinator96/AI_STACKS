"""engine/semantic_memory/ — BUILD-027A Creative Identity Memory.

Extends PersonalityModel/Matrix with motif tracking + successful/rejected
output memory. The creative fingerprint persists across sessions so
outputs become personalized over time.
"""
from engine.semantic_memory.motif_tracking          import MotifTracker, get_motif_tracker
from engine.semantic_memory.successful_output_memory import (
    SuccessfulOutputMemory, get_successful_output_memory,
)
from engine.semantic_memory.creative_identity       import (
    CreativeIdentity, get_creative_identity,
)

__all__ = [
    "MotifTracker", "get_motif_tracker",
    "SuccessfulOutputMemory", "get_successful_output_memory",
    "CreativeIdentity", "get_creative_identity",
]
