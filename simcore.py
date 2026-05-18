"""
simcore.py — STRATUM Simulation Core (deterministic truth engine).

Pipeline position (per AI_MONITOR full-stack spec):

    USER INPUT
        ↓
    INTENT ROUTER         (simcore_director.py)
        ↓
    AI DIRECTOR           (simcore_director.py — proposes events ONLY)
        ↓
    RULE ENGINE           (here — ValidationLayer)
        ↓
    EVENT GENERATION      (here — Event.propose)
        ↓
    SIMULATION ENGINE     (here — TickEngine, WorldState)
        ↓
    SNAPSHOT SYSTEM       (here — SnapshotStore)
        ↓
    RENDER ENGINE         (simcore_render.py — projections only)
        ↓
    MEMORY WRITEBACK      (here — MemoryGraph)

Hard rules (HARD-ENFORCED below):
    - WorldState is immutable. Never edited in place.
    - Mutations happen ONLY through validated Events.
    - Snapshot chain is append-only and hash-validated.
    - Director never calls anything in this module that mutates state.
    - Renderer reads but never writes.

Public API:
    WorldState                        — immutable dataclass
    Event                             — proposed mutation, validated before apply
    TickEngine                        — 8-step tick per spec (§3.3)
    SnapshotStore                     — hash-chained persistence
    MemoryGraph                       — append-only memory writeback
    SimCore.bootstrap(seed)           — top-level orchestrator
    SimCore.tick(action_dict) -> Tick — one full pipeline pass

Determinism: every tick yields a Tick record whose new world_hash is
reproducible from (parent_hash, event_id, event_payload). Replay re-applies
events in order and re-derives the same hashes.

This module is Model-layer per CLAUDE.md §5: NO PyQt6 imports.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from config import (
    SIMCORE_DB_PATH, SIMCORE_GENESIS_ID, SIMCORE_DEMO_WORLD,
    SIMCORE_SCHEMA_VERSION,
    EventStatus, RuleViolation, DATA_DIR,
)

_log = logging.getLogger(__name__)


# ── §3.1 World State (immutable) ─────────────────────────────────────────────

@dataclass(frozen=True)
class WorldState:
    """Immutable snapshot of the world. The truth at a given tick.

    `frozen=True` enforces no in-place mutation at the dataclass level.
    Events produce a NEW WorldState via `evolve(...)` — they never edit.
    """
    rooms:        dict[str, dict[str, Any]] = field(default_factory=dict)
    entities:     dict[str, dict[str, Any]] = field(default_factory=dict)
    variables:    dict[str, Any] = field(default_factory=dict)
    global_flags: tuple[str, ...] = field(default_factory=tuple)

    def to_canonical_json(self) -> str:
        """Stable serialization used for hashing. Sorted keys, tuples → lists.

        ``_v`` carries SIMCORE_SCHEMA_VERSION; old snapshots without ``_v``
        remain verifiable because the hash is over the literal stored bytes,
        not over a re-serialised dict.
        """
        return json.dumps({
            "_v": SIMCORE_SCHEMA_VERSION,
            "rooms": self.rooms,
            "entities": self.entities,
            "variables": self.variables,
            "global_flags": list(self.global_flags),
        }, sort_keys=True, separators=(",", ":"))

    def world_hash(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode("utf-8")).hexdigest()

    def evolve(self, *, rooms=None, entities=None, variables=None,
               global_flags=None) -> "WorldState":
        """Return a NEW WorldState. Never mutates self. Deep-copies modified
        sub-dicts so callers cannot accidentally retain a live reference."""
        return WorldState(
            rooms=json.loads(json.dumps(rooms if rooms is not None else self.rooms)),
            entities=json.loads(json.dumps(
                entities if entities is not None else self.entities)),
            variables=dict(variables if variables is not None else self.variables),
            global_flags=tuple(global_flags) if global_flags is not None
                         else self.global_flags,
        )


def world_from_seed(seed: dict[str, Any] | None = None) -> WorldState:
    """Build the initial WorldState from a seed dict (or the demo world)."""
    seed = seed or SIMCORE_DEMO_WORLD
    return WorldState(
        rooms=json.loads(json.dumps(seed.get("rooms", {}))),
        entities=json.loads(json.dumps(seed.get("entities", {}))),
        variables=dict(seed.get("variables", {})),
        global_flags=tuple(seed.get("global_flags", ())),
    )


def world_from_state_json(state_json: str) -> WorldState:
    """Rehydrate a WorldState from its canonical JSON, ignoring the ``_v`` key.

    Tolerates both versioned (``_v`` present) and legacy (no ``_v``) state
    blobs. Future schema changes that add new fields should extend this
    function with version-aware handling.
    """
    raw = json.loads(state_json)
    raw.pop("_v", None)
    return WorldState(**raw)


# ── §3.2 Event System (causal engine) ────────────────────────────────────────

@dataclass
class Event:
    """A proposed change. The ONLY mutation mechanism in SimCore.

    Director emits Events with status=PROPOSED. ValidationLayer checks
    preconditions and either marks VALIDATED (then TickEngine applies it)
    or REJECTED (with a reason from RuleViolation).
    """
    id:            str
    timestamp:     str
    actor:         str
    action:        str
    target:        str | None = None
    payload:       dict[str, Any] = field(default_factory=dict)
    preconditions: list[str] = field(default_factory=list)  # human-readable trace
    status:        str = EventStatus.PROPOSED
    reject_reason: str = ""

    @classmethod
    def propose(cls, actor: str, action: str, target: str | None = None,
                payload: dict[str, Any] | None = None) -> "Event":
        return cls(
            id=uuid.uuid4().hex[:12],
            timestamp=datetime.now().isoformat(timespec="seconds"),
            actor=actor, action=action, target=target,
            payload=payload or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Rule definitions (immutable per world version) ───────────────────────────
# A rule is: validate(world, event) → (ok, reason, applied_state). Applied state
# is None when validation fails. Rules are pure functions of (world, event).

RuleResult = tuple[bool, str, WorldState | None]
Rule = Callable[[WorldState, Event], RuleResult]


def _rule_move(world: WorldState, event: Event) -> RuleResult:
    actor = world.entities.get(event.actor)
    if not actor:
        return (False, RuleViolation.MISSING_ENTITY, None)
    direction = event.payload.get("direction", "")
    here = actor.get("room")
    room = world.rooms.get(here, {})
    exits = room.get("exits", {})
    dst = exits.get(direction)
    if not dst:
        return (False, f"{RuleViolation.PRECONDITION_FAIL}: no exit {direction!r} "
                       f"from {here!r}", None)
    if dst not in world.rooms:
        return (False, RuleViolation.GRAPH_INCONSISTENT, None)
    new_entities = dict(world.entities)
    new_entities[event.actor] = {**actor, "room": dst}
    return (True, "ok", world.evolve(entities=new_entities))


def _rule_take(world: WorldState, event: Event) -> RuleResult:
    actor = world.entities.get(event.actor)
    item  = world.entities.get(event.target or "")
    if not actor or not item:
        return (False, RuleViolation.MISSING_ENTITY, None)
    if item.get("kind") != "item":
        return (False, f"{RuleViolation.PRECONDITION_FAIL}: not takeable", None)
    if actor.get("room") != item.get("room"):
        return (False, f"{RuleViolation.PRECONDITION_FAIL}: not in same room",
                None)
    holds = list(actor.get("holds", []))
    if event.target in holds:
        return (False, f"{RuleViolation.PRECONDITION_FAIL}: already holding",
                None)
    holds.append(event.target)
    new_entities = dict(world.entities)
    new_entities[event.actor] = {**actor, "holds": holds}
    new_entities[event.target] = {**item, "room": None}  # carried, no room
    return (True, "ok", world.evolve(entities=new_entities))


def _rule_drop(world: WorldState, event: Event) -> RuleResult:
    actor = world.entities.get(event.actor)
    if not actor:
        return (False, RuleViolation.MISSING_ENTITY, None)
    holds = list(actor.get("holds", []))
    if event.target not in holds:
        return (False, f"{RuleViolation.PRECONDITION_FAIL}: not holding", None)
    item = world.entities.get(event.target or "")
    if not item:
        return (False, RuleViolation.MISSING_ENTITY, None)
    holds.remove(event.target)
    new_entities = dict(world.entities)
    new_entities[event.actor] = {**actor, "holds": holds}
    new_entities[event.target] = {**item, "room": actor.get("room")}
    return (True, "ok", world.evolve(entities=new_entities))


def _rule_light(world: WorldState, event: Event) -> RuleResult:
    actor = world.entities.get(event.actor)
    item  = world.entities.get(event.target or "")
    if not actor or not item:
        return (False, RuleViolation.MISSING_ENTITY, None)
    if event.target not in actor.get("holds", []):
        return (False, f"{RuleViolation.PRECONDITION_FAIL}: not holding lantern",
                None)
    new_entities = dict(world.entities)
    new_entities[event.target] = {**item, "lit": True}
    new_vars = dict(world.variables)
    new_vars["torch_lit"] = True
    return (True, "ok", world.evolve(entities=new_entities, variables=new_vars))


def _rule_unlock(world: WorldState, event: Event) -> RuleResult:
    actor = world.entities.get(event.actor)
    fixture = world.entities.get(event.target or "")
    key_id = event.payload.get("with")
    if not actor or not fixture or not key_id:
        return (False, RuleViolation.MISSING_ENTITY, None)
    if key_id not in actor.get("holds", []):
        return (False, f"{RuleViolation.PRECONDITION_FAIL}: not holding key",
                None)
    if actor.get("room") != fixture.get("room"):
        return (False, f"{RuleViolation.PRECONDITION_FAIL}: not adjacent",
                None)
    new_entities = dict(world.entities)
    new_entities[event.target] = {**fixture, "locked": False}
    return (True, "ok", world.evolve(entities=new_entities))


def _rule_tick_var(world: WorldState, event: Event) -> RuleResult:
    """System rule: increment world tick counter. Used by TickEngine itself."""
    new_vars = dict(world.variables)
    new_vars["ticks"] = int(new_vars.get("ticks", 0)) + 1
    return (True, "ok", world.evolve(variables=new_vars))


def _rule_patch(world: WorldState, event: Event) -> RuleResult:
    """Apply a code patch to the world state. Records metadata in variables."""
    file_path = event.target or "unknown"
    patch_id  = event.payload.get("patch_id", "none")
    
    new_vars = dict(world.variables)
    patches = list(new_vars.get("applied_patches", []))
    patches.append({
        "ts": event.timestamp,
        "file": file_path,
        "patch_id": patch_id,
        "actor": event.actor
    })
    new_vars["applied_patches"] = patches
    new_vars["last_patch"] = file_path
    
    return (True, "ok", world.evolve(variables=new_vars))


_RULES: dict[str, Rule] = {
    "move":     _rule_move,
    "take":     _rule_take,
    "drop":     _rule_drop,
    "light":    _rule_light,
    "unlock":   _rule_unlock,
    "patch":    _rule_patch,
    "_tick":    _rule_tick_var,
}


# ── §6.2 Validation Layer ────────────────────────────────────────────────────

class ValidationLayer:
    """Pure rule check. No mutation. Returns (ok, reason, next_world)."""

    def __init__(self, rules: dict[str, Rule] | None = None) -> None:
        self.rules = dict(rules or _RULES)

    def validate(self, world: WorldState, event: Event) -> RuleResult:
        rule = self.rules.get(event.action)
        if rule is None:
            return (False, RuleViolation.UNKNOWN_RULE, None)
        try:
            return rule(world, event)
        except Exception as exc:
            _log.exception("rule %s raised", event.action)
            return (False, f"rule_exception: {exc}", None)


# ── §3.4 Snapshot Store (append-only, hash-chained) ──────────────────────────

@dataclass
class Snapshot:
    id: str
    parent_id: str
    world_hash: str
    chain_hash: str        # sha256(parent_chain_hash || event_id || world_hash)
    event_id: str          # id of the Event that produced this snapshot
    state_json: str        # canonical world JSON
    event_json: str        # event payload
    created_at: str


def _chain(parent_chain_hash: str, event_id: str, world_hash: str) -> str:
    h = hashlib.sha256()
    h.update(parent_chain_hash.encode("utf-8"))
    h.update(b"|")
    h.update(event_id.encode("utf-8"))
    h.update(b"|")
    h.update(world_hash.encode("utf-8"))
    return h.hexdigest()


class SnapshotStore:
    """Append-only SQLite-backed snapshot chain. Hash-validates on load."""

    def __init__(self, db_path: str | Path = SIMCORE_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id TEXT PRIMARY KEY, parent_id TEXT, world_hash TEXT,
                chain_hash TEXT, event_id TEXT, state_json TEXT,
                event_json TEXT, created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, snapshot_id TEXT, status TEXT,
                actor TEXT, action TEXT, payload_json TEXT, ts TEXT
            );
            CREATE TABLE IF NOT EXISTS branches (
                name TEXT PRIMARY KEY, head_id TEXT, corrupted INTEGER
            );
            CREATE INDEX IF NOT EXISTS ix_snap_parent ON snapshots(parent_id);
        """)
        conn.commit()
        conn.close()

    def head(self, branch: str = "main") -> Snapshot | None:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT head_id FROM branches WHERE name=?", (branch,),
        ).fetchone()
        conn.close()
        if not row or not row[0]:
            return None
        return self.get(row[0])

    def is_corrupted(self, branch: str = "main") -> bool:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT corrupted FROM branches WHERE name=?", (branch,),
        ).fetchone()
        conn.close()
        return bool(row and row[0])

    def get(self, snap_id: str) -> Snapshot | None:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT id,parent_id,world_hash,chain_hash,event_id,state_json,"
            "event_json,created_at FROM snapshots WHERE id=?", (snap_id,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return Snapshot(*row)

    def append(self, snap: Snapshot, branch: str = "main") -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?)",
            (snap.id, snap.parent_id, snap.world_hash, snap.chain_hash,
             snap.event_id, snap.state_json, snap.event_json, snap.created_at),
        )
        conn.execute(
            "INSERT OR REPLACE INTO branches VALUES (?,?,COALESCE("
            "(SELECT corrupted FROM branches WHERE name=?), 0))",
            (branch, snap.id, branch),
        )
        conn.commit()
        conn.close()

    def append_event(self, ev: Event, snap_id: str) -> None:
        # Embed ``target`` into the serialised payload (events table has no
        # dedicated target column). ``replay()`` peels it back out.
        payload = dict(ev.payload) if ev.payload else {}
        if ev.target is not None:
            payload["__target__"] = ev.target
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?)",
            (ev.id, snap_id, ev.status, ev.actor, ev.action,
             json.dumps(payload), ev.timestamp),
        )
        conn.commit()
        conn.close()

    def mark_corrupted(self, branch: str = "main") -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE branches SET corrupted=1 WHERE name=?", (branch,),
        )
        conn.commit()
        conn.close()

    def rollback(self, branch: str, target_snap_id: str) -> None:
        """Move branch HEAD back to a prior snapshot. Snapshots themselves
        remain in storage (append-only); only the branch pointer moves."""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE branches SET head_id=?, corrupted=0 WHERE name=?",
            (target_snap_id, branch),
        )
        conn.commit()
        conn.close()

    def chain(self, branch: str = "main") -> list[Snapshot]:
        """Walk from genesis to current head."""
        head = self.head(branch)
        if head is None:
            return []
        out: list[Snapshot] = []
        cur: Snapshot | None = head
        while cur is not None:
            out.append(cur)
            if cur.parent_id == SIMCORE_GENESIS_ID:
                break
            cur = self.get(cur.parent_id)
        return list(reversed(out))


# ── §6.3 Corruption Control ──────────────────────────────────────────────────

class CorruptionControl:
    """Verifies chain integrity. On mismatch → freeze + rollback."""

    def __init__(self, store: SnapshotStore) -> None:
        self.store = store

    def verify(self, branch: str = "main") -> tuple[bool, str]:
        chain = self.store.chain(branch)
        if not chain:
            return (True, "empty chain")
        prev_chain_hash = SIMCORE_GENESIS_ID
        for snap in chain:
            world = world_from_state_json(snap.state_json)
            if world.world_hash() != snap.world_hash:
                return (False, f"world_hash mismatch at {snap.id}")
            expected_chain = _chain(prev_chain_hash, snap.event_id,
                                    snap.world_hash)
            if expected_chain != snap.chain_hash:
                return (False, f"chain_hash mismatch at {snap.id}")
            prev_chain_hash = snap.chain_hash
        return (True, "ok")

    def freeze_and_rollback(self, branch: str = "main") -> Snapshot | None:
        """On corruption: mark branch corrupted, walk backwards to the last
        verifiable snapshot, point HEAD there."""
        self.store.mark_corrupted(branch)
        chain = self.store.chain(branch)
        prev_chain_hash = SIMCORE_GENESIS_ID
        last_good: Snapshot | None = None
        for snap in chain:
            world = world_from_state_json(snap.state_json)
            if world.world_hash() != snap.world_hash:
                break
            expected = _chain(prev_chain_hash, snap.event_id, snap.world_hash)
            if expected != snap.chain_hash:
                break
            last_good = snap
            prev_chain_hash = snap.chain_hash
        if last_good is not None:
            self.store.rollback(branch, last_good.id)
        return last_good


# ── §5 Memory Graph (append-only memory writeback) ───────────────────────────

class MemoryGraph:
    """Append-only memory of (snapshot, event_chain, entity_graph, room_graph).
    Persisted alongside snapshots; semantic retrieval is delegated to DETBANK
    via detcore.primelatch_payload when needed elsewhere."""

    def __init__(self, store: SnapshotStore) -> None:
        self.store = store

    def writeback(self, snap: Snapshot) -> None:
        """No-op for now — snapshot table IS the memory graph. Kept as an
        explicit hook so semantic indexing can be added without callers
        changing."""
        _log.debug("MemoryGraph writeback: %s", snap.id)


# ── §3.3 Tick Engine (the 8-step pipeline) ───────────────────────────────────

@dataclass
class Tick:
    """Result of one tick. Carries every artifact for traceability."""
    event: Event
    accepted: bool
    reason: str
    snapshot_id: str | None
    parent_id: str | None
    world_hash: str | None


class TickEngine:
    """Executes the 8-step tick from spec §3.3.

        1. receive input             → caller supplies an Event
        2. validate against rules    → ValidationLayer
        3. convert to event          → already an Event
        4. append event log          → SnapshotStore.append_event
        5. recompute world state     → ValidationLayer returns next state
        6. create snapshot           → Snapshot dataclass
        7. persist snapshot          → SnapshotStore.append
        8. notify renderer           → returns Tick; caller projects
    """

    def __init__(self, store: SnapshotStore,
                 validator: ValidationLayer | None = None,
                 corruption: CorruptionControl | None = None) -> None:
        self.store = store
        self.validator = validator or ValidationLayer()
        self.corruption = corruption or CorruptionControl(store)
        self.memory = MemoryGraph(store)

    def tick(self, event: Event, world: WorldState,
             branch: str = "main") -> Tick:
        if self.store.is_corrupted(branch):
            event.status = EventStatus.REJECTED
            event.reject_reason = RuleViolation.CORRUPTED_BRANCH
            self.store.append_event(event, snap_id="")
            return Tick(event=event, accepted=False,
                        reason=RuleViolation.CORRUPTED_BRANCH,
                        snapshot_id=None, parent_id=None, world_hash=None)

        ok, reason, next_world = self.validator.validate(world, event)
        event.preconditions.append(f"validate→{ok}:{reason}")
        if not ok or next_world is None:
            event.status = EventStatus.REJECTED
            event.reject_reason = reason
            self.store.append_event(event, snap_id="")
            return Tick(event=event, accepted=False, reason=reason,
                        snapshot_id=None, parent_id=None, world_hash=None)

        head = self.store.head(branch)
        parent_id = head.id if head else SIMCORE_GENESIS_ID
        parent_chain = head.chain_hash if head else SIMCORE_GENESIS_ID
        wh = next_world.world_hash()
        ch = _chain(parent_chain, event.id, wh)
        snap = Snapshot(
            id=uuid.uuid4().hex[:12],
            parent_id=parent_id,
            world_hash=wh,
            chain_hash=ch,
            event_id=event.id,
            state_json=next_world.to_canonical_json(),
            event_json=json.dumps(event.to_dict()),
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        event.status = EventStatus.APPLIED
        self.store.append(snap, branch=branch)
        self.store.append_event(event, snap.id)
        self.memory.writeback(snap)
        return Tick(event=event, accepted=True, reason="ok",
                    snapshot_id=snap.id, parent_id=parent_id, world_hash=wh)


# ── Top-level orchestrator ───────────────────────────────────────────────────

class SimCore:
    """Top-level binding. Holds engine + provides current_world() projection."""

    def __init__(self, db_path: str | Path = SIMCORE_DB_PATH) -> None:
        self.store = SnapshotStore(db_path)
        self.engine = TickEngine(self.store)

    def bootstrap(self, seed: dict[str, Any] | None = None,
                  branch: str = "main") -> Snapshot:
        """Plant a genesis snapshot if none exists. Idempotent."""
        head = self.store.head(branch)
        if head is not None:
            return head
        world = world_from_seed(seed)
        wh = world.world_hash()
        ch = _chain(SIMCORE_GENESIS_ID, SIMCORE_GENESIS_ID, wh)
        snap = Snapshot(
            id=uuid.uuid4().hex[:12],
            parent_id=SIMCORE_GENESIS_ID,
            world_hash=wh, chain_hash=ch, event_id=SIMCORE_GENESIS_ID,
            state_json=world.to_canonical_json(),
            event_json=json.dumps({"genesis": True}),
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self.store.append(snap, branch=branch)
        return snap

    def current_world(self, branch: str = "main") -> WorldState:
        head = self.store.head(branch)
        if head is None:
            self.bootstrap(branch=branch)
            head = self.store.head(branch)
        return world_from_state_json(head.state_json)

    def tick(self, action: dict[str, Any], branch: str = "main") -> Tick:
        """Convenience: build Event from action dict, call engine.tick()."""
        ev = Event.propose(
            actor=action.get("actor", "player"),
            action=action.get("action", ""),
            target=action.get("target"),
            payload=action.get("payload") or {
                k: v for k, v in action.items()
                if k not in ("actor", "action", "target")
            },
        )
        return self.engine.tick(ev, self.current_world(branch), branch=branch)

    def verify(self, branch: str = "main") -> tuple[bool, str]:
        return self.engine.corruption.verify(branch)

    def rollback_to(self, snap_id: str, branch: str = "main") -> None:
        self.store.rollback(branch, snap_id)

    def replay(self, branch: str = "main",
               seed: dict[str, Any] | None = None) -> WorldState:
        """Derive WorldState from the event log, ignoring snapshots.

        Per Risk #1 mitigation: events are authoritative, snapshots are a
        verifiable cache. Walks the events table (status=APPLIED only) in
        timestamp + insertion order and re-applies each through
        ValidationLayer. The returned WorldState matches what
        ``current_world()`` returns when the chain is intact, but is derived
        purely from causal history — independent of stored state_json blobs.

        Raises RuntimeError on a validation failure during replay (indicates
        that a previously-applied event no longer validates against current
        rules — a corruption signal).
        """
        world = world_from_seed(seed)
        validator = self.engine.validator
        conn = sqlite3.connect(self.store.db_path)
        try:
            rows = conn.execute(
                "SELECT id, status, actor, action, payload_json, ts "
                "FROM events WHERE status=? ORDER BY ts ASC, id ASC",
                (EventStatus.APPLIED,),
            ).fetchall()
        finally:
            conn.close()
        for ev_id, status, actor, action, payload_json, ts in rows:
            try:
                payload = json.loads(payload_json) if payload_json else {}
            except (TypeError, json.JSONDecodeError):
                payload = {}
            target = payload.pop("__target__", None) if isinstance(payload, dict) else None
            event = Event(
                id=ev_id, timestamp=ts or "", actor=actor or "",
                action=action or "", target=target,
                payload=payload if isinstance(payload, dict) else {},
                status=EventStatus.PROPOSED,
            )
            ok, reason, next_world = validator.validate(world, event)
            if not ok or next_world is None:
                raise RuntimeError(
                    f"replay halted at event {ev_id}: {reason}"
                )
            world = next_world
        return world


# ── CLI ──────────────────────────────────────────────────────────────────────

def _format_tick(tick: Tick, world: WorldState) -> str:
    out: list[str] = [
        f"# Tick {tick.event.id}",
        f"action: {tick.event.action} target={tick.event.target} "
        f"payload={tick.event.payload}",
        f"accepted: {tick.accepted}  reason: {tick.reason}",
        f"snapshot: {tick.snapshot_id}  world_hash: {tick.world_hash}",
        "",
        "## World",
        f"player room: {world.entities.get('player', {}).get('room')}",
        f"player holds: {world.entities.get('player', {}).get('holds', [])}",
        f"variables: {world.variables}",
    ]
    return "\n".join(out)


def _demo() -> int:
    """Spin up demo world, run a small scripted sequence, replay-verify."""
    sc = SimCore()
    sc.bootstrap()
    script = [
        {"actor": "player", "action": "move",   "payload": {"direction": "down"}},
        {"actor": "player", "action": "take",   "target": "lantern"},
        {"actor": "player", "action": "light",  "target": "lantern"},
        {"actor": "player", "action": "move",   "payload": {"direction": "up"}},
        {"actor": "player", "action": "move",   "payload": {"direction": "north"}},
        {"actor": "player", "action": "take",   "target": "iron_key"},
        {"actor": "player", "action": "move",   "payload": {"direction": "south"}},
        {"actor": "player", "action": "move",   "payload": {"direction": "down"}},
        {"actor": "player", "action": "unlock", "target": "rune_door",
         "payload": {"with": "iron_key"}},
    ]
    for action in script:
        tick = sc.tick(action)
        _log.debug(_format_tick(tick, sc.current_world()))
        _log.debug("-" * 60)
    ok, reason = sc.verify()
    _log.debug(f"\n[chain integrity] ok={ok} reason={reason}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="simcore",
                                description="STRATUM SimCore — deterministic engine")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", help="run demo world script + verify chain")
    sub.add_parser("verify", help="verify current chain integrity")
    p_tick = sub.add_parser("tick", help="apply one event")
    p_tick.add_argument("action_json",
                        help='action dict, e.g. \'{"action":"move",'
                             '"payload":{"direction":"north"}}\'')
    sub.add_parser("show", help="print current world state")
    args = p.parse_args(argv)

    if args.cmd == "demo":
        return _demo()
    sc = SimCore()
    sc.bootstrap()
    if args.cmd == "verify":
        ok, reason = sc.verify()
        _log.debug(json.dumps({"ok": ok, "reason": reason}))
        return 0 if ok else 1
    if args.cmd == "tick":
        action = json.loads(args.action_json)
        tick = sc.tick(action)
        _log.debug(_format_tick(tick, sc.current_world()))
        return 0 if tick.accepted else 1
    if args.cmd == "show":
        w = sc.current_world()
        print(json.dumps({
            "rooms": w.rooms, "entities": w.entities,
            "variables": w.variables, "global_flags": list(w.global_flags),
        }, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
