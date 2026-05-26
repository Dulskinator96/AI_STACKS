"""engine/coherence/ — BUILD-027A Multi-Modal Coherence Engine.

Cross-realm coherence checks. Ensures soundtrack matches visuals,
palette is consistent across image/video, pacing matches narrative arc.
"""
from engine.coherence.modality_synchronizer import (
    ModalitySynchronizer, get_modality_synchronizer, CoherenceReport,
)

__all__ = ["ModalitySynchronizer", "get_modality_synchronizer", "CoherenceReport"]
