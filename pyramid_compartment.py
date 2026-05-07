"""
pyramid_compartment.py — STRATUM Cognitive OS Coordinator (Pyramid Architecture).

Six-layer cognitive operating architecture:
    1. Interface Layer (Rooms)        ← this module orchestrates
    2. IntentRouter                   ← classifies + routes to a Room
    3. Memory Core (DETBANK / RAG)    ← node-graph linked storage
    4. Code DNA Engine                ← helixchain.py
    5. Reasoning Engine               ← decomposes input → output
    6. Execution + Output Engine      ← executor.py + DocumentRoom

Public API:
    PyramidCompartment.route(text) → Task              — full INPUT → MEMORY pipeline
    PyramidCompartment.enter(room, text) → Task        — bypass router, pick room
    AnalysisRoom / ReasoningRoom / SandboxRoom /
    DocumentRoom / MemoryRoom                          — direct subsystem access

Determinism rules (per spec):
    - Every step records to Task.steps with structured trace
    - No layer collapse: routing, reasoning, execution stay separate
    - No external API calls — purely local engines
    - Memory writes happen ONLY at end-of-pipeline (atomic)

This module is Model-layer per CLAUDE.md §5: NO PyQt6 imports.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import sys
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from config import (
    PYRAMID_DB_PATH, RoomKind, DocFormat, TaskStatus, AR_25_50_TEMPLATE,
    PYRAMID_REASONING_STEPS, DBombLexicon, DATA_DIR,
)

_log = logging.getLogger(__name__)


# ── Task object — structured trace through the Pyramid ──────────────────────

@dataclass
class TaskStep:
    """One step in a Task's structured progression. Every step is traceable."""
    label: str
    detail: str
    ts: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass
class Task:
    """A unit of operator intent flowing through the Pyramid.

    Each Task carries: input text, the Room it was routed to, structured
    reasoning steps, the final output, memory-store identifiers for any
    persisted artifacts, and a status.
    """
    task_id: str
    input_text: str
    room: str = ""
    route_reason: str = ""
    steps: list[TaskStep] = field(default_factory=list)
    output: str = ""
    memory_refs: list[str] = field(default_factory=list)
    status: str = TaskStatus.PENDING
    started_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    finished_at: str = ""

    def step(self, label: str, detail: str = "") -> None:
        self.steps.append(TaskStep(label=label, detail=detail))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _new_task_id() -> str:
    return uuid.uuid4().hex[:12]


# ── Layer 2 — IntentRouter ───────────────────────────────────────────────────

class IntentRouter:
    """Classifies free-text input into a Room. Rule-based; deterministic.

    Returns (room, reason). The router does not execute — only routes.
    """

    _ROUTES: tuple[tuple[str, tuple[str, ...]], ...] = (
        (RoomKind.SANDBOX, (
            "run ", "execute", "exec ", "subprocess", "shell", "pytest",
            "python -m", "test the", "sandbox",
        )),
        (RoomKind.DOCUMENT, (
            "memo", "memorandum", "ar 25-50", "ar25-50", "report on",
            "draft a doc", "document on", "official doc", "write a brief",
            "system brief", "anchor prompt", "generate anchor",
        )),
        (RoomKind.ANALYSIS, (
            "analyze", "scan ", "scan the", "code dna", "extract dna",
            "what does this codebase", "constraint report", "callgraph",
            "tag function", "structural map",
        )),
        (RoomKind.MEMORY, (
            "recall", "what did we", "remember", "look up", "memory",
            "retrieve", "search past", "context for",
        )),
        (RoomKind.REASONING, (
            "decompose", "plan ", "reason about", "step by step",
            "break down", "how should i", "strategy", "design ",
        )),
    )

    def classify(self, text: str) -> tuple[str, str]:
        if not text:
            return (RoomKind.REASONING, "empty input → default to reasoning")
        lower = text.lower()
        for room, keys in self._ROUTES:
            for k in keys:
                if k in lower:
                    return (room, f"matched route key {k!r}")
        return (RoomKind.REASONING, "no specific route key → default reasoning")


# ── Layer 1 — Rooms ──────────────────────────────────────────────────────────

class RoomBase:
    """Abstract Room. Subclasses implement enter(task) and write to task.steps."""
    kind: str = ""

    def enter(self, task: Task) -> Task:  # pragma: no cover — abstract
        raise NotImplementedError


class AnalysisRoom(RoomBase):
    """Code inspection + DNA extraction. Wraps helixchain."""
    kind = RoomKind.ANALYSIS

    def __init__(self, project_root: str | Path | None = None) -> None:
        self.project_root = Path(project_root or Path(__file__).parent).resolve()

    def enter(self, task: Task) -> Task:
        task.room = self.kind
        task.status = TaskStatus.EXECUTING
        task.step("structure", f"helixread_project({self.project_root})")
        try:
            import helixchain as _helix
            scan = _helix.helixread_project(self.project_root)
            _helix.tagfuse_scan(scan)
            task.step("transformation", "tagfuse_scan applied")
            findings = _helix.constraint_report(scan)
            task.step("validation",
                      f"constraint_report: {len(findings)} findings")
            anchor = _helix.anchorforge(scan, with_callgraph=False)
            task.output = anchor
            task.step("output", f"anchorforge emitted {len(anchor)} chars")
            task.status = TaskStatus.DONE
        except Exception as exc:
            _log.exception("AnalysisRoom failed")
            task.output = f"AnalysisRoom error: {exc}"
            task.status = TaskStatus.FAILED
        return task


class ReasoningRoom(RoomBase):
    """Decomposes input into the canonical 5-step progression:
    input → structure → transformation → validation → output.

    No external LLM call by default — deterministic skeleton. Subclasses can
    override _think() to plug in Ollama / local LLM.
    """
    kind = RoomKind.REASONING

    def enter(self, task: Task) -> Task:
        task.room = self.kind
        task.status = TaskStatus.EXECUTING
        plan: list[str] = []
        for stage in PYRAMID_REASONING_STEPS:
            note = self._think(stage, task.input_text)
            task.step(stage, note)
            plan.append(f"[{stage.upper()}] {note}")
        task.output = "\n".join(plan)
        task.status = TaskStatus.DONE
        return task

    def _think(self, stage: str, text: str) -> str:
        """Deterministic placeholder; override to inject LLM reasoning."""
        return {
            "input": f"received: {text[:140]}",
            "structure": "decompose into known constraints + unknowns",
            "transformation": "apply Pyramid layer mapping",
            "validation": "check traceability + cross-layer consistency",
            "output": "emit structured plan; route to room if action required",
        }.get(stage, "step")


class SandboxRoom(RoomBase):
    """Controlled execution. Two paths:
       - Python source string  → captured stdout via -c
       - Shell command         → subprocess.run with timeout

    Every execution is logged with returncode, stdout tail, stderr tail.
    """
    kind = RoomKind.SANDBOX

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout

    def enter(self, task: Task) -> Task:
        task.room = self.kind
        task.status = TaskStatus.EXECUTING
        task.step("structure", "classify payload as python|shell")
        text = task.input_text.strip()
        try:
            if text.startswith("python:"):
                src = text[len("python:"):].strip()
                proc = subprocess.run(
                    [sys.executable, "-c", src],
                    capture_output=True, text=True, timeout=self.timeout,
                )
            elif text.startswith("shell:"):
                cmd = text[len("shell:"):].strip()
                proc = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True,
                    timeout=self.timeout,
                )
            else:
                task.output = ("SandboxRoom requires prefix: 'python:' or 'shell:'. "
                               f"Received: {text[:60]!r}")
                task.status = TaskStatus.FAILED
                return task
            task.step("transformation", f"executed in {self.timeout}s budget")
            task.step("validation", f"exit_code={proc.returncode}")
            task.output = (
                f"EXIT: {proc.returncode}\n"
                f"STDOUT (tail):\n{proc.stdout[-1200:]}\n"
                f"STDERR (tail):\n{proc.stderr[-600:]}"
            )
            task.step("output", f"{len(task.output)} chars captured")
            task.status = TaskStatus.DONE
        except subprocess.TimeoutExpired:
            task.output = f"SandboxRoom timeout after {self.timeout}s"
            task.status = TaskStatus.FAILED
        except Exception as exc:
            _log.exception("SandboxRoom failed")
            task.output = f"SandboxRoom error: {exc}"
            task.status = TaskStatus.FAILED
        return task


class DocumentRoom(RoomBase):
    """Structured document emitter.

    Parses task.input_text expecting either:
       - JSON dict with keys per format (preferred, deterministic)
       - Free text with 'format: <kind>' marker; fields are best-effort

    Supported formats:
       - DocFormat.AR_25_50      memorandum (Army Regulation 25-50)
       - DocFormat.SYSTEM_BRIEF  operator-facing summary
       - DocFormat.REPORT        generic structured report
       - DocFormat.ANCHOR        DETCORE-aligned anchor via HELIXCHAIN
    """
    kind = RoomKind.DOCUMENT

    def enter(self, task: Task) -> Task:
        task.room = self.kind
        task.status = TaskStatus.EXECUTING
        try:
            spec = self._parse_spec(task.input_text)
        except Exception as exc:
            task.output = f"DocumentRoom parse error: {exc}"
            task.status = TaskStatus.FAILED
            return task

        fmt = spec.get("format", DocFormat.SYSTEM_BRIEF)
        task.step("structure", f"format={fmt}")
        try:
            if fmt == DocFormat.AR_25_50:
                doc = self._render_ar_25_50(spec)
            elif fmt == DocFormat.SYSTEM_BRIEF:
                doc = self._render_system_brief(spec)
            elif fmt == DocFormat.REPORT:
                doc = self._render_report(spec)
            elif fmt == DocFormat.ANCHOR:
                doc = self._render_anchor(spec)
            else:
                task.output = f"unsupported format: {fmt}"
                task.status = TaskStatus.FAILED
                return task
            task.step("transformation", f"rendered {fmt}")
            task.step("validation", self._validate(fmt, doc))
            task.output = doc
            task.step("output", f"{len(doc)} chars")
            task.status = TaskStatus.DONE
        except Exception as exc:
            _log.exception("DocumentRoom render failed")
            task.output = f"DocumentRoom render error: {exc}"
            task.status = TaskStatus.FAILED
        return task

    @staticmethod
    def _parse_spec(text: str) -> dict[str, Any]:
        text = text.strip()
        if text.startswith("{"):
            return json.loads(text)
        spec: dict[str, Any] = {}
        for line in text.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                spec[k.strip().lower()] = v.strip()
        if "format" not in spec:
            spec["format"] = DocFormat.SYSTEM_BRIEF
        return spec

    @staticmethod
    def _render_ar_25_50(spec: dict[str, Any]) -> str:
        body_paragraphs: list[str] = []
        if isinstance(spec.get("paragraphs"), list):
            for i, para in enumerate(spec["paragraphs"], start=1):
                body_paragraphs.append(f"{i}. {para}")
        elif spec.get("body"):
            for i, para in enumerate(str(spec["body"]).split("\n\n"), start=1):
                if para.strip():
                    body_paragraphs.append(f"{i}. {para.strip()}")
        body = "\n\n".join(body_paragraphs) or "1. (no body provided)"
        poc = spec.get("poc", "")
        poc_block = (
            f"{len(body_paragraphs)+1 if body_paragraphs else 2}. "
            f"The point of contact for this memorandum is {poc}."
        ) if poc else ""
        return AR_25_50_TEMPLATE.format(
            office_symbol=spec.get("office_symbol", "[OFFICE SYMBOL]"),
            date=spec.get("date", datetime.now().strftime("%d %B %Y").upper()),
            recipient=spec.get("recipient", "[RECIPIENT]"),
            subject=spec.get("subject", "[SUBJECT]"),
            body=body,
            poc_block=poc_block,
            signature_block=spec.get("signature_block", "[SIGNATURE BLOCK]"),
        )

    @staticmethod
    def _render_system_brief(spec: dict[str, Any]) -> str:
        title = spec.get("title", "STRATUM SYSTEM BRIEF")
        ts = datetime.now().isoformat(timespec="seconds")
        sections = spec.get("sections") or {
            "purpose": spec.get("purpose", ""),
            "state":   spec.get("state",   ""),
            "next":    spec.get("next",    ""),
        }
        lines = [f"# {title}", f"_Generated {ts}_", ""]
        if isinstance(sections, dict):
            for key, val in sections.items():
                lines.append(f"## {key.upper()}")
                lines.append(str(val).strip() or "(none)")
                lines.append("")
        else:
            lines.append(str(sections))
        return "\n".join(lines)

    @staticmethod
    def _render_report(spec: dict[str, Any]) -> str:
        title = spec.get("title", "REPORT")
        body = spec.get("body", "(no body provided)")
        return f"# {title}\n\n{body}\n"

    @staticmethod
    def _render_anchor(spec: dict[str, Any]) -> str:
        try:
            import helixchain as _helix
            root = spec.get("root", str(Path(__file__).parent))
            scan = _helix.helixread_project(root)
            _helix.tagfuse_scan(scan)
            if spec.get("callgraph"):
                _helix.build_callgraph(scan)
            return _helix.anchorforge(scan, with_callgraph=bool(spec.get("callgraph")))
        except Exception as exc:
            return f"# ANCHORFORGE ERROR\n{exc}\n"

    @staticmethod
    def _validate(fmt: str, doc: str) -> str:
        checks: list[str] = []
        if fmt == DocFormat.AR_25_50:
            for header in ("MEMORANDUM FOR", "SUBJECT:"):
                if header not in doc:
                    checks.append(f"missing {header}")
            if not checks:
                checks.append("AR 25-50 structural headers present")
        else:
            checks.append(f"length ok ({len(doc)} chars)")
        return "; ".join(checks)


class MemoryRoom(RoomBase):
    """DETBANK retrieval. Delegates to the existing WON pipeline if present;
    otherwise scans the HELIX SQLite fragment store."""
    kind = RoomKind.MEMORY

    def enter(self, task: Task) -> Task:
        task.room = self.kind
        task.status = TaskStatus.EXECUTING
        task.step("structure", f"recall query: {task.input_text[:100]}")
        results = self._recall(task.input_text)
        task.step("transformation", f"{len(results)} fragments returned")
        task.step("validation", "fragments are read-only — no inference applied")
        task.output = "\n\n---\n\n".join(results) if results else \
                      "DETBANK: no fragments matched"
        task.step("output", f"{len(task.output)} chars")
        task.status = TaskStatus.DONE if results else TaskStatus.DONE
        return task

    @staticmethod
    def _recall(query: str, limit: int = 5) -> list[str]:
        # Try DETCORE adapter first (uses live WON pipeline)
        try:
            import detcore as _dc
            text, count = _dc.primelatch_payload(limit=limit)
            if text:
                return [text]
        except Exception as exc:
            _log.debug("MemoryRoom DETCORE adapter unavailable: %s", exc)

        # Fallback: scan HELIXCHAIN SQLite fragment store
        from config import HELIX_DB_PATH
        try:
            if not Path(HELIX_DB_PATH).exists():
                return []
            conn = sqlite3.connect(HELIX_DB_PATH)
            cur = conn.cursor()
            like = f"%{query.lower()}%" if query else "%"
            cur.execute(
                "SELECT doc FROM fragments WHERE LOWER(doc) LIKE ? LIMIT ?",
                (like, limit),
            )
            rows = [r[0] for r in cur.fetchall()]
            conn.close()
            return rows
        except Exception as exc:
            _log.warning("MemoryRoom SQLite fallback failed: %s", exc)
            return []


# ── Layer 3 — Memory Core (node-graph linked task storage) ───────────────────

class MemoryCore:
    """Persists Tasks as linked nodes. Schema:
        tasks(id, input, room, status, started_at, finished_at, output)
        steps(task_id, idx, label, detail, ts)
        links(src_task, dst_task, relation)   — node-graph edges
    """

    def __init__(self, db_path: str | Path = PYRAMID_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, input TEXT, room TEXT, status TEXT,
                started_at TEXT, finished_at TEXT, output TEXT
            );
            CREATE TABLE IF NOT EXISTS steps (
                task_id TEXT, idx INTEGER, label TEXT, detail TEXT, ts TEXT,
                PRIMARY KEY (task_id, idx)
            );
            CREATE TABLE IF NOT EXISTS links (
                src_task TEXT, dst_task TEXT, relation TEXT,
                PRIMARY KEY (src_task, dst_task, relation)
            );
        """)
        conn.commit()
        conn.close()

    def store(self, task: Task) -> str:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "REPLACE INTO tasks VALUES (?,?,?,?,?,?,?)",
            (task.task_id, task.input_text, task.room, task.status,
             task.started_at, task.finished_at, task.output),
        )
        conn.execute("DELETE FROM steps WHERE task_id=?", (task.task_id,))
        for i, s in enumerate(task.steps):
            conn.execute(
                "INSERT INTO steps VALUES (?,?,?,?,?)",
                (task.task_id, i, s.label, s.detail, s.ts),
            )
        conn.commit()
        conn.close()
        task.memory_refs.append(f"task:{task.task_id}")
        return task.task_id

    def link(self, src: str, dst: str, relation: str) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT OR IGNORE INTO links VALUES (?,?,?)",
                     (src, dst, relation))
        conn.commit()
        conn.close()

    def recall(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        like = f"%{query.lower()}%" if query else "%"
        rows = conn.execute(
            "SELECT id, room, status, started_at, output FROM tasks "
            "WHERE LOWER(input) LIKE ? OR LOWER(output) LIKE ? "
            "ORDER BY started_at DESC LIMIT ?",
            (like, like, limit),
        ).fetchall()
        conn.close()
        return [
            {"id": r[0], "room": r[1], "status": r[2],
             "started_at": r[3], "output_preview": (r[4] or "")[:200]}
            for r in rows
        ]


# ── Top-level Compartment ────────────────────────────────────────────────────

class PyramidCompartment:
    """Cognitive OS coordinator. Drives the full INPUT → MEMORY pipeline.

    Determinism: route once, execute once, persist once. No retries.
    Traceability: every step lands in Task.steps and is written to MemoryCore.
    """

    def __init__(self, project_root: str | Path | None = None,
                 sandbox_timeout: int = 30) -> None:
        self.router = IntentRouter()
        self.rooms: dict[str, RoomBase] = {
            RoomKind.ANALYSIS:  AnalysisRoom(project_root),
            RoomKind.REASONING: ReasoningRoom(),
            RoomKind.SANDBOX:   SandboxRoom(timeout=sandbox_timeout),
            RoomKind.DOCUMENT:  DocumentRoom(),
            RoomKind.MEMORY:    MemoryRoom(),
        }
        self.memory = MemoryCore()

    def route(self, text: str) -> Task:
        """Full pipeline: classify → enter Room → persist."""
        task = Task(task_id=_new_task_id(), input_text=text)
        room_kind, reason = self.router.classify(text)
        task.room = room_kind
        task.route_reason = reason
        task.status = TaskStatus.ROUTED
        task.step("route", f"{room_kind} ({reason})")
        room = self.rooms[room_kind]
        task = room.enter(task)
        task.finished_at = datetime.now().isoformat(timespec="seconds")
        self.memory.store(task)
        return task

    def enter(self, room_kind: str, text: str) -> Task:
        """Bypass router; pick the room directly."""
        if room_kind not in self.rooms:
            raise ValueError(f"unknown room: {room_kind}")
        task = Task(task_id=_new_task_id(), input_text=text)
        task.room = room_kind
        task.route_reason = "direct entry"
        task.status = TaskStatus.ROUTED
        task.step("route", f"{room_kind} (direct)")
        task = self.rooms[room_kind].enter(task)
        task.finished_at = datetime.now().isoformat(timespec="seconds")
        self.memory.store(task)
        return task


# ── CLI ──────────────────────────────────────────────────────────────────────

def _format_task(task: Task) -> str:
    out: list[str] = []
    out.append(f"# Pyramid Task {task.task_id}")
    out.append(f"Room: **{task.room}** · Status: **{task.status}**")
    out.append(f"Route reason: {task.route_reason}")
    out.append("")
    out.append("## Steps")
    for i, s in enumerate(task.steps, start=1):
        out.append(f"{i}. [{s.label}] {s.detail}")
    out.append("")
    out.append("## Output")
    out.append(task.output)
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="pyramid_compartment",
        description="STRATUM Cognitive OS Coordinator — Pyramid Architecture",
    )
    p.add_argument("input", nargs="?", default="",
                   help="free-text input (router decides Room)")
    p.add_argument("--room", choices=[
        RoomKind.ANALYSIS, RoomKind.REASONING, RoomKind.SANDBOX,
        RoomKind.DOCUMENT, RoomKind.MEMORY,
    ], help="bypass router; enter a specific Room")
    p.add_argument("--root", default=None,
                   help="project root for AnalysisRoom (default: this folder)")
    p.add_argument("--json", action="store_true", help="emit Task JSON")
    p.add_argument("--recall", default="",
                   help="recall past tasks matching this query, then exit")
    args = p.parse_args(argv)

    pc = PyramidCompartment(project_root=args.root)

    if args.recall:
        rows = pc.memory.recall(args.recall)
        print(json.dumps(rows, indent=2))
        return 0

    if not args.input:
        p.error("input is required (or use --recall)")

    task = (pc.enter(args.room, args.input) if args.room
            else pc.route(args.input))

    if args.json:
        print(json.dumps(task.to_dict(), indent=2))
    else:
        print(_format_task(task))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
