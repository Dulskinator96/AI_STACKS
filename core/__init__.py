"""core — AI_STACK runtime foundation layer.

Provides cross-cutting infrastructure used by every other module:
  - services    : Service abstract + ServiceRegistry (lifecycle management)
  - (future)    : telemetry, scheduler, memory_facade

Per Stage 2 directive, this package introduces controlled lifecycle ownership
without rewriting individual subsystems — they keep their existing interfaces
and get wrapped by thin Adapter classes registered with the ServiceRegistry.
"""
__all__ = ["services"]
