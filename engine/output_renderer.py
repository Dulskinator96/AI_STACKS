"""engine/output_renderer.py — chamber-formatted output.

Assembles intent + spec + graph + dispatch results + reflection into a
single ChamberOutput object that the Pyramid Chamber log can render
without coupling to engine internals.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChamberOutput:
    output_id:         str
    intent_id:         str
    graph_id:          str
    raw_text:          str
    medium:            Optional[str]
    realm:             str
    style:             Optional[str]
    tone:              Optional[str]
    overall_score:     float
    chamber_lines:     list = field(default_factory=list)   # rendered log lines
    artifact_paths:    list = field(default_factory=list)    # file outputs (if any)
    dispatch_summary:  dict = field(default_factory=dict)    # {outcome: count}
    timestamp:         float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def render(self) -> str:
        return "\n".join(self.chamber_lines)


class OutputRenderer:
    """Compose final ChamberOutput from pipeline artifacts."""

    def render(self, enriched, spec, graph, dispatch_results, reflection) -> ChamberOutput:
        t0 = time.time()
        results = list(dispatch_results or [])
        summary = {"OK": 0, "DEGRADED": 0, "UNAVAILABLE": 0, "FAIL": 0}
        artifacts: list[str] = []
        for r in results:
            outcome = _get(r, "outcome", "FAIL")
            summary[outcome] = summary.get(outcome, 0) + 1
            payload = _get(r, "payload")
            if isinstance(payload, str) and ("/" in payload or "\\" in payload):
                artifacts.append(payload)

        lines: list[str] = []
        lines.append(f"⌬ PYRAMID ENGINE · {enriched.raw_text[:120]}")
        if spec.style or spec.tone or spec.medium:
            lines.append(
                f"  · medium: {spec.medium or '—'}  ·  style: {spec.style or '—'}  ·  tone: {spec.tone or '—'}"
            )
        if spec.architecture_style or spec.atmosphere:
            lines.append(f"  · architecture: {spec.architecture_style or '—'}")
            lines.append(f"  · atmosphere:   {spec.atmosphere or '—'}")
        if spec.soundtrack_profile:
            lines.append(f"  · soundtrack:   {spec.soundtrack_profile}")
        if spec.color_palette:
            lines.append(f"  · palette:      {' '.join(spec.color_palette)}")
        lines.append("")
        lines.append(graph.render())
        lines.append("")
        for r in results:
            kind = _get(r, "kind", "?")
            outcome = _get(r, "outcome", "?")
            backend = _get(r, "backend", "?")
            err = _get(r, "error", "")
            mark = {"OK": "✓", "DEGRADED": "◐", "UNAVAILABLE": "✗", "FAIL": "✗"}.get(outcome, "·")
            line = f"  {mark} [{kind}] via {backend} → {outcome}"
            if err:
                line += f"   ({err[:80]})"
            lines.append(line)
        lines.append("")
        lines.append(reflection.render())

        out = ChamberOutput(
            output_id=f"out-{int(t0*1000):x}",
            intent_id=getattr(spec, "intent_id", ""),
            graph_id=getattr(graph, "graph_id", ""),
            raw_text=enriched.raw_text,
            medium=spec.medium,
            realm=graph.realm,
            style=spec.style,
            tone=spec.tone,
            overall_score=reflection.overall_score,
            chamber_lines=lines,
            artifact_paths=artifacts,
            dispatch_summary=summary,
            timestamp=t0,
        )
        self._emit_receipt(out, (time.time() - t0) * 1000.0)
        return out

    def _emit_receipt(self, out: ChamberOutput, dur_ms: float) -> None:
        try:
            from truth.receipt_engine import record_execution
            record_execution(
                task="output_renderer:render",
                executor="OutputRenderer",
                duration_ms=dur_ms,
                verified=True,
                compute_sha256=False,
                evidence={
                    "output_id":      out.output_id,
                    "intent_id":      out.intent_id,
                    "graph_id":       out.graph_id,
                    "overall_score":  out.overall_score,
                    "realm":          out.realm,
                    "dispatch_summary": out.dispatch_summary,
                    "artifact_count": len(out.artifact_paths),
                    "line_count":     len(out.chamber_lines),
                },
            )
        except Exception:
            pass


def _get(obj: Any, attr: str, default=None):
    if obj is None:
        return default
    if hasattr(obj, attr):
        return getattr(obj, attr)
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return default
