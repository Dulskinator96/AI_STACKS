"""engine/creative_composition/ — BUILD-026 CREATIVE COMPOSITION ASCENSION.

Composition-first execution layer. Every intent becomes a composition
PLAN before any worker dispatch. The plan is the source of truth for:
  · scene breakdown (StoryboardPlanner)
  · cinematic language (CinematicLanguage)
  · aesthetic direction (AestheticDirector)
  · refinement strategy (RefinementDirector)
  · final mastering (ExportMastering)

Canonical pipeline (build-026):

    Intent → IntentContract → COMPOSITION PLANNING → Scene Breakdown
      → Style/Aesthetic Expansion → Asset Strategy → Realm Coordination
      → Worker Dispatch → Validation → Auto Refinement → Mastering
      → Export Package → Final Validation
"""
from engine.creative_composition.composition_engine import (
    CompositionEngine, get_composition_engine, CompositionPlan,
)
from engine.creative_composition.storyboard_planner import (
    StoryboardPlanner, Scene, Storyboard,
)
from engine.creative_composition.cinematic_language import (
    CinematicLanguage, CinematicProfile,
)
from engine.creative_composition.aesthetic_director import (
    AestheticDirector, AestheticProfile,
)
from engine.creative_composition.refinement_director import (
    RefinementDirector, RefinementStrategy,
)
from engine.creative_composition.export_mastering import (
    ExportMastering, MasterPackage,
)

__all__ = [
    "CompositionEngine", "get_composition_engine", "CompositionPlan",
    "StoryboardPlanner", "Scene", "Storyboard",
    "CinematicLanguage", "CinematicProfile",
    "AestheticDirector", "AestheticProfile",
    "RefinementDirector", "RefinementStrategy",
    "ExportMastering", "MasterPackage",
]
