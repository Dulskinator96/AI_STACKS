"""engine/simulation_engine.py — BUILD-020 SECTION 9.

Tactical / environmental / world-state simulation. Wraps simcore (when
present) and adds higher-level coordination:
  · tactical maps (entity positions + trajectories)
  · environmental projection (weather, time-of-day, system state)
  · world-state modeling (entity counts, faction states)
  · operational modeling (mission timelines, resource budgets)

Never fakes simulation — when simcore is unavailable the engine returns
state="UNAVAILABLE" with remediation. When simcore is present, every
simulation tick is real (deterministic world.tick()).
"""
from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

_log = logging.getLogger(__name__)


@dataclass
class WorldState:
    world_id:    str
    seed:        int
    intent_seed: str
    tick_count:  int = 0
    spawned_at:  float = 0.0
    entities:    list = field(default_factory=list)
    environment: dict = field(default_factory=dict)
    last_hash:   str = ""

    def to_dict(self) -> dict:
        return {
            "world_id":    self.world_id,
            "seed":        self.seed,
            "intent_seed": self.intent_seed[:120],
            "tick_count":  self.tick_count,
            "spawned_at":  self.spawned_at,
            "entity_count": len(self.entities),
            "environment": dict(self.environment),
            "last_hash":   self.last_hash,
        }


class SimulationEngine:
    """Tactical + environmental + world-state coordinator."""

    def __init__(self):
        self._worlds: dict[str, WorldState] = {}
        self._lock = threading.RLock()
        self._simcore_ok = self._probe_simcore()
        self._world_engines: dict[str, Any] = {}   # world_id -> simcore.SimCore
        try:
            from runtime.singleton_registry import get_registry
            get_registry().register("engine.simulation", self)
        except Exception:
            pass

    def _probe_simcore(self) -> bool:
        try:
            import simcore  # noqa: F401
            return True
        except Exception:
            return False

    def is_available(self) -> bool:
        return self._simcore_ok

    # ── Public API ────────────────────────────────────────────────────
    def bootstrap_world(self, intent_seed: str,
                          seed: Optional[int] = None) -> Optional[WorldState]:
        """Bootstrap a new world from intent. Returns None if simcore
        is unavailable (caller should check is_available()).
        """
        if not self._simcore_ok:
            self._emit_receipt("unavailable", None, intent_seed)
            return None
        try:
            import simcore
            if seed is None:
                seed = hash(intent_seed) & 0xffff
            engine = simcore.SimCore.bootstrap(seed=seed)
            wid = f"world-{uuid.uuid4().hex[:8]}"
            world = WorldState(
                world_id=wid, seed=int(seed),
                intent_seed=intent_seed or "",
                spawned_at=time.time(),
                environment={
                    "weather":     "calm",
                    "time_of_day": "noon",
                    "tension":     0.5,
                },
                last_hash=(engine.current_world().hash[:16]
                            if hasattr(engine, "current_world") else ""),
            )
            with self._lock:
                self._worlds[wid] = world
                self._world_engines[wid] = engine
            self._emit_receipt("bootstrap", world, intent_seed)
            return world
        except Exception as e:
            _log.warning("bootstrap_world failed: %s", e)
            self._emit_receipt("failed", None, intent_seed, error=str(e))
            return None

    def tick(self, world_id: str, action: dict = None) -> Optional[WorldState]:
        """Advance one simulation tick. Updates the world's environment
        based on the action's intent."""
        with self._lock:
            world = self._worlds.get(world_id)
            engine = self._world_engines.get(world_id)
        if world is None or engine is None:
            return None
        try:
            engine.tick(action or {"action": "observe", "target": "self"})
            world.tick_count += 1
            world.last_hash = (engine.current_world().hash[:16]
                                if hasattr(engine, "current_world") else "")
            # Apply environmental drift on each tick
            self._drift_environment(world)
            self._emit_receipt("tick", world, world.intent_seed)
            return world
        except Exception as e:
            _log.warning("tick failed for %s: %s", world_id, e)
            return world

    def add_entity(self, world_id: str, name: str,
                    position: tuple = (0.0, 0.0),
                    faction: str = "neutral") -> bool:
        """Add a tactical entity to a world (positions + factions, not
        rendered geometry — that's a future build)."""
        with self._lock:
            world = self._worlds.get(world_id)
            if world is None:
                return False
            world.entities.append({
                "name":     name,
                "position": list(position),
                "faction":  faction,
                "added_at": time.time(),
            })
        self._emit_receipt("entity_added", world, world.intent_seed)
        return True

    def project_trajectory(self, world_id: str, entity_name: str,
                            target: tuple, steps: int = 20) -> list:
        """Return a list of (x, y) points from the entity's current
        position to target, divided into `steps` waypoints. Used by
        tactical map overlays."""
        with self._lock:
            world = self._worlds.get(world_id)
            if world is None:
                return []
            ent = next((e for e in world.entities if e["name"] == entity_name), None)
            if ent is None:
                return []
            start = ent["position"]
        if steps <= 0:
            return [tuple(target)]
        dx = (target[0] - start[0]) / steps
        dy = (target[1] - start[1]) / steps
        return [(start[0] + dx * i, start[1] + dy * i) for i in range(steps + 1)]

    def get_world(self, world_id: str) -> Optional[WorldState]:
        with self._lock:
            return self._worlds.get(world_id)

    def list_worlds(self) -> list:
        with self._lock:
            return [w.to_dict() for w in self._worlds.values()]

    def stats(self) -> dict:
        with self._lock:
            return {
                "simcore_available": self._simcore_ok,
                "world_count":       len(self._worlds),
                "total_ticks":       sum(w.tick_count for w in self._worlds.values()),
            }

    # ── Internals ──────────────────────────────────────────────────────
    def _drift_environment(self, world: WorldState) -> None:
        """Deterministic-but-varied environment drift each tick."""
        t = world.tick_count
        # Weather cycles
        cycle = ["calm", "windy", "stormy", "foggy", "clear"]
        if t % 5 == 0:
            world.environment["weather"] = cycle[(t // 5) % len(cycle)]
        # Time-of-day
        tod = ["dawn", "morning", "noon", "afternoon", "dusk", "night"]
        world.environment["time_of_day"] = tod[(t // 3) % len(tod)]
        # Tension drifts
        prev = float(world.environment.get("tension", 0.5))
        delta = math.sin(t * 0.3) * 0.1
        world.environment["tension"] = max(0.0, min(1.0, prev + delta))

    def _emit_receipt(self, outcome: str, world: Optional[WorldState],
                       intent_seed: str, error: str = "") -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task=f"simulation:{outcome}",
                executor="SimulationEngine",
                duration_ms=0.0,
                verified=(outcome in ("bootstrap", "tick", "entity_added")),
                compute_sha256=False,
                failure_reason=(error if error else None),
                evidence={
                    "world_id":     (world.world_id if world else None),
                    "tick_count":   (world.tick_count if world else 0),
                    "entity_count": (len(world.entities) if world else 0),
                    "environment":  (dict(world.environment) if world else {}),
                    "intent_seed":  (intent_seed or "")[:120],
                    "simcore_ok":   self._simcore_ok,
                },
            )
        except Exception:
            pass


_INSTANCE: Optional[SimulationEngine] = None


def get_simulation_engine() -> SimulationEngine:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = SimulationEngine()
    return _INSTANCE
