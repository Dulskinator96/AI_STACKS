"""engine/refinement/ — BUILD-027A Iterative Refinement Engine.

Generate → Critique → Score → Compare → Refine → Re-score → Finalize.

CritiqueEngine produces structured critique per artifact set. The
IterativeRefiner wraps the existing QualityGate/AutoRepairLoop with
composition-aware refinement strategies.
"""
from engine.refinement.critique_engine    import CritiqueEngine, get_critique_engine, Critique
from engine.refinement.iterative_refiner  import IterativeRefiner, get_iterative_refiner
from engine.refinement.comparative_selector import ComparativeSelector, get_comparative_selector

__all__ = [
    "CritiqueEngine", "get_critique_engine", "Critique",
    "IterativeRefiner", "get_iterative_refiner",
    "ComparativeSelector", "get_comparative_selector",
]
