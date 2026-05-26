"""engine/execution_planner.py — PHASE 6.

Convert structured intent (ExpandedSpec) into an actionable ExecutionGraph
of AtomicStep nodes with dependencies. The planner decides which tools
are required, which pipelines activate, and the execution order.

Output is a DAG, not a linear plan — steps with no shared dependency
can run in parallel.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AtomicStep:
    """One node in the ExecutionGraph."""
    step_id:     str
    kind:        str          # e.g. "synthesize_image", "render_audio", "assemble_timeline"
    backend:     str          # e.g. "imageforge", "pyttsx3", "ffmpeg", "ollama"
    description: str
    inputs:      list = field(default_factory=list)   # step_ids this step depends on
    parameters:  dict = field(default_factory=dict)
    realm:       str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionGraph:
    graph_id:   str
    intent_id:  str
    raw_text:   str
    realm:      str
    medium:     Optional[str]
    steps:      list             # list[AtomicStep]
    timestamp:  float
    estimated_total_ms: float

    def to_dict(self) -> dict:
        d = asdict(self)
        d["steps"] = [s.to_dict() if isinstance(s, AtomicStep) else s for s in self.steps]
        return d

    def step_count(self) -> int:
        return len(self.steps)

    def render(self) -> str:
        """Human-readable rendering for chamber log."""
        lines = [f"⌬ ExecutionGraph · {self.graph_id} · {self.realm} · {self.step_count()} steps"]
        for i, s in enumerate(self.steps, 1):
            deps = ("← " + ",".join(s.inputs)) if s.inputs else ""
            lines.append(f"  {i:>2}. [{s.kind}] {s.description}  ({s.backend}) {deps}".rstrip())
        lines.append(f"  est. {self.estimated_total_ms:.0f} ms")
        return "\n".join(lines)


class ExecutionPlanner:
    """Decompose an ExpandedSpec into an ExecutionGraph DAG."""

    def plan(self, spec) -> ExecutionGraph:
        t0 = time.time()
        realm = (spec.realm or "").lower() or self._fallback_realm(spec.medium)
        medium = spec.medium

        steps: list[AtomicStep] = self._steps_for_realm(realm, spec)

        if not steps:
            # Fallback: a single "cast" step through ensemble — never empty
            steps = [AtomicStep(
                step_id=_fresh(),
                kind="cast_ensemble",
                backend="pyramid_ensemble",
                description=f"Cast intent through 4-agent ensemble: {spec.raw_text[:80]}",
                inputs=[],
                parameters={"intent": spec.raw_text, "ambition": spec.ambition},
                realm="cast",
            )]
            realm = "cast"

        est_ms = sum(_estimate_step_ms(s) for s in steps)
        graph = ExecutionGraph(
            graph_id=f"graph-{uuid.uuid4().hex[:10]}",
            intent_id=spec.intent_id,
            raw_text=spec.raw_text,
            realm=realm,
            medium=medium,
            steps=steps,
            timestamp=t0,
            estimated_total_ms=est_ms,
        )
        self._emit_receipt(graph, (time.time() - t0) * 1000.0)
        return graph

    # ── Per-realm step recipes ────────────────────────────────────────
    def _steps_for_realm(self, realm: str, spec) -> list:
        if realm == "image":
            return [
                AtomicStep(
                    step_id=_fresh(), kind="probe_imageforge",
                    backend="imageforge", description="Verify imageforge backend reachable",
                    realm=realm,
                ),
                AtomicStep(
                    step_id=_fresh(), kind="synthesize_image",
                    backend="imageforge",
                    description=f"Render: {spec.raw_text[:80]} · {spec.style or 'default'} · {spec.lighting or 'natural'}",
                    parameters={
                        "prompt":      spec.raw_text,
                        "style":       spec.style,
                        "lighting":    spec.lighting,
                        "composition": spec.composition,
                        "detail":      spec.detail_level,
                        "palette":     spec.color_palette,
                    },
                    realm=realm,
                ),
            ]

        if realm == "video":
            return [
                AtomicStep(step_id=_fresh(), kind="probe_davinci", backend="davinci_resolve",
                           description="Probe DaVinci Resolve availability", realm=realm),
                AtomicStep(step_id=_fresh(), kind="generate_script", backend="ollama",
                           description="Generate trailer/scene script from intent",
                           parameters={"intent": spec.raw_text, "tone": spec.tone},
                           realm=realm),
                AtomicStep(step_id=_fresh(), kind="generate_storyboard", backend="imageforge",
                           description="Generate storyboard frames from script",
                           inputs=["script"],
                           parameters={"style": spec.style, "frames": 6},
                           realm=realm),
                AtomicStep(step_id=_fresh(), kind="generate_soundtrack", backend="audiocraft",
                           description=f"Soundtrack: {spec.soundtrack_profile or 'cinematic'}",
                           parameters={"profile": spec.soundtrack_profile, "tone": spec.tone},
                           realm=realm),
                AtomicStep(step_id=_fresh(), kind="assemble_timeline", backend="ffmpeg",
                           description="Assemble storyboard + soundtrack into timeline",
                           inputs=["storyboard", "soundtrack"],
                           realm=realm),
                AtomicStep(step_id=_fresh(), kind="render_export", backend="ffmpeg",
                           description="Render final H.264 export",
                           inputs=["timeline"],
                           realm=realm),
            ]

        if realm == "audio":
            return [
                AtomicStep(step_id=_fresh(), kind="probe_audio", backend="pyttsx3",
                           description="Probe local TTS / audio backends", realm=realm),
                AtomicStep(step_id=_fresh(), kind="synthesize_audio", backend="pyttsx3",
                           description=f"Render audio: {spec.soundtrack_profile or 'speech'}",
                           parameters={"text": spec.raw_text, "tone": spec.tone},
                           realm=realm),
            ]

        if realm == "game":
            return [
                AtomicStep(step_id=_fresh(), kind="probe_simcore", backend="simcore",
                           description="Probe simcore world engine", realm=realm),
                AtomicStep(step_id=_fresh(), kind="bootstrap_world", backend="simcore",
                           description="Bootstrap deterministic simulation world",
                           parameters={"intent": spec.raw_text, "seed_intent": True},
                           realm=realm),
                AtomicStep(step_id=_fresh(), kind="generate_lore", backend="ollama",
                           description=f"World lore: {spec.world_lore or spec.style or 'open'}",
                           realm=realm),
            ]

        if realm == "code":
            return [
                AtomicStep(step_id=_fresh(), kind="probe_codeforge", backend="conv_programming",
                           description="Probe CodeForge engine", realm=realm),
                AtomicStep(step_id=_fresh(), kind="forge_proposal", backend="conv_programming",
                           description=f"Generate code proposal: {spec.raw_text[:80]}",
                           parameters={"intent": spec.raw_text},
                           realm=realm),
                AtomicStep(step_id=_fresh(), kind="validate_proposal", backend="proposal_engine",
                           description="Schema-validate proposal", inputs=["forge"],
                           realm=realm),
            ]

        if realm == "cast" or realm == "narrative":
            return [
                AtomicStep(step_id=_fresh(), kind="cast_ensemble", backend="pyramid_ensemble",
                           description="4-agent ensemble cast (R1 + R2 + synthesis)",
                           parameters={"intent": spec.raw_text, "tone": spec.tone},
                           realm="cast"),
            ]

        # Unknown realm — empty list (caller falls back to cast)
        return []

    def _fallback_realm(self, medium: Optional[str]) -> str:
        if medium in ("image", "video", "audio", "game", "code"):
            return medium
        if medium in ("speech",):
            return "audio"
        if medium in ("simulation",):
            return "game"
        return "cast"

    def _emit_receipt(self, graph: ExecutionGraph, dur_ms: float) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="execution_planner:plan",
                executor="ExecutionPlanner",
                duration_ms=dur_ms,
                verified=True,
                compute_sha256=False,
                evidence={
                    "graph_id":  graph.graph_id,
                    "intent_id": graph.intent_id,
                    "realm":     graph.realm,
                    "medium":    graph.medium,
                    "step_count": graph.step_count(),
                    "step_kinds": [s.kind for s in graph.steps],
                    "estimated_total_ms": graph.estimated_total_ms,
                },
            )
        except Exception:
            pass


def _fresh() -> str:
    return f"s-{uuid.uuid4().hex[:6]}"


_STEP_TIME_HINTS = {
    "probe_imageforge": 50,    "synthesize_image": 8000,
    "probe_davinci":    100,   "generate_script": 6000,
    "generate_storyboard": 12000, "generate_soundtrack": 9000,
    "assemble_timeline": 2000, "render_export":   10000,
    "probe_audio": 50,         "synthesize_audio": 3000,
    "probe_simcore": 30,       "bootstrap_world": 500, "generate_lore": 5000,
    "probe_codeforge": 30,     "forge_proposal": 4000, "validate_proposal": 100,
    "cast_ensemble": 30000,
}


def _estimate_step_ms(step: AtomicStep) -> float:
    return float(_STEP_TIME_HINTS.get(step.kind, 1000))
