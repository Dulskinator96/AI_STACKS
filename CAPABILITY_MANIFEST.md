# DBOMBLOCAL Capability Manifest

**Generated:** 2026-05-18 by Claude (capability audit + game-tool inventory agents)
**Status:** 60% code-complete · 40% operator-facing

This document answers the operator's standing question: *"what can you do today, what's missing, what's required?"*

---

## What you can do TODAY (WIRED)

| Capability | Surface | Notes |
|---|---|---|
| Send a chat message to WON via Ollama | Chat tab → Send | Threaded; non-blocking |
| Cast the 4-agent pyramid ensemble | Chat tab → ✦ Cast or `/cast <prompt>` | Wired in build-012 |
| Conjour a new app-wide theme | Chat → `/theme <vibe>` | Stable Diffusion-free; pure color synthesis |
| Generate narrative briefs (concept cards, neural maps, voice) | Synthesis Lab tab | Uses synthesis.py + pyttsx3 |
| Browse + search the codebase | Memory & Recall + pyramid_tools | 11 local tools, no API keys |
| Boot validator + maintenance cortex + 11 observers | Background daemon thread | Wired in HOTWIRE Phase 4 |
| State machine transitions with persistence | telemetry/system_state.json | Build-008 |
| Classified failure receipts | telemetry/execution_receipts.jsonl | 45 sites in build-011 |
| Repair detector (AST + log parse) | Threaded background scan every 30s | Build-008 |
| File analysis / brief / summarize / document / recap | Lab tab (Pip-Boy styled) | LabWidget |
| Self-modify code via CodeForge | CodeForge tab → ⚒ FORGE | conv_programming.py engine |

## What exists but is UNWIRED (callable Python, no UI route)

| Capability | Module | Why not wired |
|---|---|---|
| Conscious deliberation (GlobalWorkspace, PersonaState) | `consciousness.py` | No boot-time instantiation; needs ConsciousAgent wrapper |
| Multi-turn agent chatroom (sequential deliberation) | `agent_chatroom.py` | No UI entry point; callable from chat as deep mode |
| Per-agent episodic/semantic memory | `agent_memory.py` | Imported by chatroom only; no recall UI |
| 5-layer Perceptual Engine (attention, predictive coder, somatic markers) | `perceptual_engine.py` | Not instantiated; ready for agent injection |
| RepairCoordinator bounded mutator | `maintenance/repair_coordinator.py` | Cortex wires it but no autonomous trigger loop |
| SimCore deterministic world engine | `simcore.py` + `simcore_director.py` | Pure logic; not connected to UI |
| Dolphin emulator launch | `plugins/graphics_dolphin.py` | Wrapper present; needs tool-registry entry |
| Image generation via Stable Diffusion | `imageforge.py` + `synthesis.py` | Called only from narrative output; no standalone "generate image" button |
| Procreation agent spawner | `procreation.py` | Public API exists; no spawner UI |
| Gemini bridge | `gemini_bridge.py` | Imported, no caller |
| LM Studio bridge as Ollama fallback | `lm_studio.py` | Imported, no failover logic |

## What's MISSING (would need new code)

| Capability | Effort | Notes |
|---|---|---|
| **Dynamic tab spawning at runtime** | 1 day | CRITICAL for "I want to play a game" UX |
| Standalone Tool Registry surface | 4 hours | Tools currently locked inside agent prompts |
| Memory recall panel (search WON memory directly) | 1 day | Per audit's recommended "global search" |
| Creative tools module (`creative_tools/`) | 1 week | image_tools.py, video_tools.py, audio_tools.py (AudioCraft/Bark) |
| Game design agent + asset pipeline | 1 month | New procreation agent spec + creative_tools integration |
| Procedural world generation | 1 month | Extend simcore with Perlin/dungeon generators |
| Multi-modal output dashboard | 2 days | Image+audio+video preview panel |

---

## What to enable next (operator priority order)

1. **Dynamic tab spawn** — once this lands, every other unwired capability becomes 4-hour wirings.
2. **Global search panel** — unifies WON memory + Lab portfolio + DNA + Vault into one query.
3. **Standalone tool surface** — expose pyramid_tools registry as a tab so the operator can call `search_code`, `run_python`, etc. directly without going through an agent prompt.
4. **Conscious mode toggle** — wrap the existing chat with ConsciousAgent so the 4 agents have predictive coding + persona state.
5. **Procreation spawner UI** — operator types a role/goal; the system spawns an agent and reports its DNA.

---

## How the system tells you what it needs

The Oracle (`/cast`, `/theme`, `/conjour`) already supports natural-language probing. Ask:
- `/cast what would it take to make the Lab tab playable as a strategy game?`
- `/cast which unwired modules give us the most leverage right now?`
- `/cast walk me through enabling SimCore`

The 4-agent ensemble will reference this manifest if grounded properly. Drop the manifest text into the next prompt for highest accuracy.

---

**The honest read**: this system is closer to "operating substrate" than "finished app". The bones are remarkable; the wiring is partial. Each connection is a 2-8 hour surgical pass. The directive to "evolve into a cognitive creation environment" is a multi-month arc, not a single rebuild — but every rebuild from here lands one or two more capabilities on the operator-facing surface.
