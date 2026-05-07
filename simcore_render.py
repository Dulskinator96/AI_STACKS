"""
simcore_render.py — Multi-modal projection layer for SimCore.

Per AI_MONITOR spec §4 (RENDER + INTERFACE CORE):
    "rendering is a projection of WorldState only — no direct state mutation
     allowed. audio is derived from event stream — no independent logic.
     assets are referenced, not generated statefully."

Every projector here is a pure function of (world, last_event/tick). No
caching that could go stale, no callbacks into the engine.

Public API:
    VisualProjector.project(world)           — ASCII room-graph map
    AudioProjector.cue_for(event)            — string cue token per event
    TextureMapper.slug_for(entity)           — asset slug (kind + state)
    TextRenderer.summary(world, last_tick)   — operator-facing summary
    Renderer.project_all(world, last_tick)   — bundle of all four

This module is Model-layer per CLAUDE.md §5: NO PyQt6 imports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config import EventStatus, RenderChannel
from simcore import Event, Tick, WorldState


# ── §4.2 Visual Render Engine — ASCII room graph ─────────────────────────────

class VisualProjector:
    """Projects WorldState as a simple ASCII map: rooms + exits + entities
    in each room. Read-only, deterministic.
    """

    def project(self, world: WorldState) -> str:
        if not world.rooms:
            return "(empty world)"
        # Bucket entities by room
        by_room: dict[str, list[str]] = {}
        for eid, ent in world.entities.items():
            room = ent.get("room")
            if room:
                by_room.setdefault(room, []).append(eid)
            else:
                by_room.setdefault("(carried)", []).append(eid)

        out: list[str] = []
        for rid, room in world.rooms.items():
            name = room.get("name", rid)
            exits = room.get("exits", {})
            ents = ", ".join(by_room.get(rid, [])) or "(empty)"
            out.append(f"+-- {rid}  -  {name}")
            out.append(f"|   entities: {ents}")
            for direction, dst in exits.items():
                out.append(f"|   -> {direction:<6} -> {dst}")
            out.append("+--")
        carried = by_room.get("(carried)", [])
        if carried:
            out.append(f"[carried items: {', '.join(carried)}]")
        return "\n".join(out)


# ── §4.3 Audio Engine — event → cue mapping ──────────────────────────────────

class AudioProjector:
    """Maps an Event to a stable cue string. Cues are slug-style tokens that a
    real audio backend would map to sample files; this layer never plays sound
    itself — that responsibility lives outside the deterministic engine.
    """

    _CUES: dict[str, str] = {
        "move":   "footstep_stone",
        "take":   "item_pickup_chime",
        "drop":   "item_drop_thud",
        "light":  "lantern_flare",
        "unlock": "lock_release_click",
    }
    _AMBIENT: dict[str, str] = {
        "courtyard":  "wind_open_air",
        "great_hall": "hall_low_drone",
        "cellar":     "drip_echo",
    }

    def cue_for(self, event: Event) -> str:
        if event.status == EventStatus.REJECTED:
            return "ui_reject_buzz"
        action = event.action or "_"
        return self._CUES.get(event.action, f"missing_cue:{action}")

    def ambient_for(self, world: WorldState) -> str:
        player = world.entities.get("player", {})
        room = player.get("room")
        if not room:
            return "missing_ambient:_"
        return self._AMBIENT.get(room, f"missing_ambient:{room}")


# ── §4.4 Texture / Asset Engine — entity → asset slug ────────────────────────

class TextureMapper:
    """Returns a stable slug per entity in its current state. Assets are
    referenced by slug; nothing here loads or mutates files.
    """

    def slug_for(self, entity_id: str, entity: dict[str, Any]) -> str:
        kind = entity.get("kind", "unknown")
        if kind == "item" and entity.get("lit"):
            return f"asset/{entity_id}_lit"
        if kind == "fixture" and entity.get("locked") is False:
            return f"asset/{entity_id}_open"
        return f"asset/{entity_id}_{kind}"

    def slugs_for_world(self, world: WorldState) -> dict[str, str]:
        return {eid: self.slug_for(eid, ent)
                for eid, ent in world.entities.items()}


# ── Text Renderer — operator-facing summary ─────────────────────────────────

class TextRenderer:
    """Compact text projection. Used by CLI and by the Pyramid/SimCore tab."""

    def summary(self, world: WorldState, last_tick: Tick | None = None) -> str:
        player = world.entities.get("player", {})
        room_id = player.get("room")
        room = world.rooms.get(room_id, {}) if room_id else {}
        lines = [
            f"WORLD HASH: {world.world_hash()[:12]}",
            f"TICKS:      {world.variables.get('ticks', 0)}",
            f"PLAYER:     {room_id} - {room.get('name', '?')}",
            f"HOLDS:      {', '.join(player.get('holds', [])) or '(empty)'}",
        ]
        if last_tick is not None:
            lines.append(
                f"LAST EVENT: {last_tick.event.action} → "
                f"{'OK' if last_tick.accepted else 'REJECTED: ' + last_tick.reason}"
            )
        return "\n".join(lines)


# ── Aggregate projection ────────────────────────────────────────────────────

@dataclass
class Projection:
    """Bundle of read-only projections produced from one WorldState."""
    visual:   str = ""
    audio_cue: str = ""
    ambient:   str = ""
    textures:  dict[str, str] = field(default_factory=dict)
    text:     str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            RenderChannel.VISUAL:  self.visual,
            RenderChannel.AUDIO:   {"cue": self.audio_cue,
                                    "ambient": self.ambient},
            RenderChannel.TEXTURE: self.textures,
            RenderChannel.TEXT:    self.text,
        }


class Renderer:
    """Bundles all four projectors. Pure read of (world, last_tick)."""

    def __init__(self) -> None:
        self.visual = VisualProjector()
        self.audio = AudioProjector()
        self.texture = TextureMapper()
        self.text = TextRenderer()

    def project_all(self, world: WorldState,
                    last_tick: Tick | None = None) -> Projection:
        return Projection(
            visual=self.visual.project(world),
            audio_cue=(self.audio.cue_for(last_tick.event)
                       if last_tick else "silence"),
            ambient=self.audio.ambient_for(world),
            textures=self.texture.slugs_for_world(world),
            text=self.text.summary(world, last_tick),
        )


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    from simcore import SimCore
    p = argparse.ArgumentParser(prog="simcore_render",
                                description="Render projection of current world")
    p.add_argument("--channel", choices=["all", "visual", "audio",
                                          "texture", "text"],
                   default="all")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    sc = SimCore()
    sc.bootstrap()
    proj = Renderer().project_all(sc.current_world())
    bundle = proj.to_dict()
    if args.channel != "all":
        bundle = {args.channel: bundle[args.channel]}
    if args.json:
        print(json.dumps(bundle, indent=2))
    else:
        for ch, val in bundle.items():
            print(f"=== {ch.upper()} ===")
            if isinstance(val, dict):
                for k, v in val.items():
                    print(f"  {k}: {v}")
            else:
                print(val)
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
