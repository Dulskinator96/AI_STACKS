"""ui/production_console — BUILD-022 Production Console.

Single unified production surface. Replaces fragmented tab spam with one
console hosting:
  · Active Sessions   — current production sessions + their state
  · Artifact Gallery  — browse + filter all artifacts by realm
  · Render Queue      — pending workers + refinement passes
  · Preview Wall      — auto-registered previews per artifact
  · Tool Fabric       — live tool status + health + version
  · Diagnostics       — unified diagnostic aggregator
"""
from ui.production_console.console import ProductionConsolePanel
__all__ = ["ProductionConsolePanel"]
