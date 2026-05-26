"""engine/oracle/ — BUILD-027A Production Collaborator Oracle.

Reads intent + composition_plan + CQI + creative_identity to provide
production guidance: ambition assessment, weak-area diagnosis, asset
recommendations, atmosphere mismatches, cinematic improvements.
"""
from engine.oracle.ambition_interpreter import (
    AmbitionInterpreter, get_ambition_interpreter, AmbitionAssessment,
)
from engine.oracle.production_advisor   import (
    ProductionAdvisor, get_production_advisor, AdvisoryReport,
)

__all__ = [
    "AmbitionInterpreter", "get_ambition_interpreter", "AmbitionAssessment",
    "ProductionAdvisor",   "get_production_advisor",   "AdvisoryReport",
]
