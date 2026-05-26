"""omega.world_model — L2 World Model (GOLD PILLAR v2).

Probabilistic structure over observed system behavior. NOT a prediction engine:
emits likely-next-state distributions + confidence bounds + known-unknowns under
the standing assumption of incomplete information. Read-only observability.

CLI: python -m omega.world_model
"""
from omega.world_model.state_model import build_world_model

__all__ = ["build_world_model"]
