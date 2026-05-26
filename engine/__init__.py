"""engine/ — PYRAMID ENGINE CONSOLIDATION (BUILD-019).

Central Intent-Centered Creative Intelligence Engine.

This package CONSOLIDATES existing infrastructure into a single coherent
orchestration flow. It does NOT replace:
  · kernel/intent_orchestrator (still the deterministic regex compiler)
  · truth/receipt_engine (still the canonical receipt sink)
  · consciousness.py (ConsciousEnsembleOrchestrator, when present)
  · pyramid_tools.ToolRegistry (still the canonical tool registry)
  · runtime/ (singleton registry, view model, workspace spawner)

Flow:
    Operator Intent
        ↓
    IntentCortex (enrich vague text with tone/style/emotion/medium)
        ↓
    PersonalityModel (apply operator preference vectors)
        ↓
    CreativeExpansionLayer (minimal → production spec)
        ↓
    ExecutionPlanner (spec → ExecutionGraph DAG)
        ↓
    ToolRouter / RealmDispatcher (dispatch atomic tasks)
        ↓
    Realms: image · video · audio · game · code · simulation · cast
        ↓
    OutputRenderer (chamber-formatted result)
        ↓
    ReflectionEngine (critique + refinement hints)
        ↓
    PersonalityModel.absorb (preference update)
"""
from __future__ import annotations

from engine.pyramid_engine     import PyramidEngine, get_engine
from engine.intent_cortex      import IntentCortex, EnrichedIntent
from engine.personality_model  import PersonalityModel, get_personality
from engine.creative_expansion import CreativeExpansionLayer, ExpandedSpec
from engine.execution_planner  import ExecutionPlanner, ExecutionGraph, AtomicStep
from engine.realm_dispatcher   import RealmDispatcher, DispatchResult
from engine.tool_router        import ToolRouter
from engine.reflection_engine  import ReflectionEngine, ReflectionReport
from engine.output_renderer    import OutputRenderer, ChamberOutput
from engine.memory_context_bridge import MemoryContextBridge

# BUILD-020 FULL ORGANISM — additional organ layers
from engine.cognitive_core         import CognitiveCore, get_cognitive_core, CognitiveCycle
from engine.tool_fabric            import ToolFabric, get_tool_fabric, ToolStatus
from engine.workspace_fabric       import WorkspaceFabric, get_workspace_fabric, Constellation
from engine.realm_orchestrator     import RealmOrchestrator, get_realm_orchestrator, RealmOrchestration
from engine.media_generation_layer import MediaGenerationLayer, get_media_generation_layer, GenerationJob
from engine.simulation_engine      import SimulationEngine, get_simulation_engine, WorldState
from engine.adaptive_learning      import AdaptiveLearningLayer, get_adaptive_learning
from engine.diagnostics_layer      import DiagnosticsLayer, get_diagnostics
from engine.personality_matrix     import PersonalityMatrix, get_personality_matrix, MatrixSnapshot

# BUILD-021 ASCENSION PHASE — production substrate
from engine.production_core         import ProductionCore, get_production_core, ProductionSession
from engine.artifact_lineage        import ArtifactLineageTracker, get_artifact_lineage, Artifact
from engine.production_pipeline_engine import (
    ProductionPipelineEngine, get_production_pipeline, PipelineRun,
    PIPELINE_TRAILER, PIPELINE_GAME, PIPELINE_ALBUM, PIPELINE_GALLERY, PIPELINE_SIM,
)
from engine.production_tool_fabric  import (
    ProductionToolFabric, get_production_tool_fabric,
    HardwareCapabilities, CapabilityScore,
)

# BUILD-023 STABILIZATION — canonical pipeline surfaces
from engine.worker_router           import WorkerRouter, get_worker_router, RouteDecision
from engine.artifact_validator      import ArtifactValidator, get_artifact_validator

__all__ = [
    "PyramidEngine", "get_engine",
    "IntentCortex", "EnrichedIntent",
    "PersonalityModel", "get_personality",
    "CreativeExpansionLayer", "ExpandedSpec",
    "ExecutionPlanner", "ExecutionGraph", "AtomicStep",
    "RealmDispatcher", "DispatchResult",
    "ToolRouter",
    "ReflectionEngine", "ReflectionReport",
    "OutputRenderer", "ChamberOutput",
    "MemoryContextBridge",
    # BUILD-020 organism
    "CognitiveCore", "get_cognitive_core", "CognitiveCycle",
    "ToolFabric", "get_tool_fabric", "ToolStatus",
    "WorkspaceFabric", "get_workspace_fabric", "Constellation",
    "RealmOrchestrator", "get_realm_orchestrator", "RealmOrchestration",
    "MediaGenerationLayer", "get_media_generation_layer", "GenerationJob",
    "SimulationEngine", "get_simulation_engine", "WorldState",
    "AdaptiveLearningLayer", "get_adaptive_learning",
    "DiagnosticsLayer", "get_diagnostics",
    "PersonalityMatrix", "get_personality_matrix", "MatrixSnapshot",
    # BUILD-021 ASCENSION PHASE
    "ProductionCore", "get_production_core", "ProductionSession",
    "ArtifactLineageTracker", "get_artifact_lineage", "Artifact",
    "ProductionPipelineEngine", "get_production_pipeline", "PipelineRun",
    "PIPELINE_TRAILER", "PIPELINE_GAME", "PIPELINE_ALBUM",
    "PIPELINE_GALLERY", "PIPELINE_SIM",
    "ProductionToolFabric", "get_production_tool_fabric",
    "HardwareCapabilities", "CapabilityScore",
    # BUILD-023 STABILIZATION
    "WorkerRouter", "get_worker_router", "RouteDecision",
    "ArtifactValidator", "get_artifact_validator",
]
