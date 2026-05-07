"""
stratum_pipeline.py — Top-level pipeline coordinator.

Wires: Intent → Correlate → Propose → (user approval) → Execute

This module is UI-agnostic. The UI calls run_pipeline() and receives
streamed status events via a callback. Execution only happens on explicit
user approval — the pipeline never auto-applies changes.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from code_correlator import CodeCorrelator, CorrelationResult, get_correlator
from executor import Executor, ExecutionResult
from intent_engine import IntentResult, parse_intent
from proposal_engine import Proposal, ProposalEngine, ProposalResult, get_engine


# ── Pipeline event system ─────────────────────────────────────────────────────

class PipelineStage(str, Enum):
    PARSING     = "PARSING"
    CORRELATING = "CORRELATING"
    PROPOSING   = "PROPOSING"
    AWAITING    = "AWAITING"     # waiting for user approval
    EXECUTING   = "EXECUTING"
    COMPLETE    = "COMPLETE"
    ERROR       = "ERROR"
    CANCELLED   = "CANCELLED"


@dataclass
class PipelineEvent:
    stage:   PipelineStage
    message: str
    data:    Any = None             # IntentResult | CorrelationResult | Proposal | ExecutionResult


EventCallback = Callable[[PipelineEvent], None]


# ── Pipeline run ──────────────────────────────────────────────────────────────

@dataclass
class PipelineRun:
    query:       str
    project_root: str
    run_id:      str = field(default_factory=lambda: f"run_{int(time.time()*1000)}")

    # Populated as pipeline advances
    intent:      Optional[IntentResult]     = None
    correlation: Optional[CorrelationResult] = None
    proposal:    Optional[ProposalResult]   = None
    result:      Optional[ExecutionResult]  = None

    # Control
    _approval_event: threading.Event = field(default_factory=threading.Event)
    _approved:       bool            = False
    _cancelled:      bool            = False

    def approve(self) -> None:
        self._approved = True
        self._approval_event.set()

    def reject(self) -> None:
        self._approved = False
        self._cancelled = True
        self._approval_event.set()

    def wait_for_approval(self, timeout: float = 120.0) -> bool:
        self._approval_event.wait(timeout=timeout)
        return self._approved

    def to_summary(self) -> dict:
        return {
            "run_id":      self.run_id,
            "query":       self.query,
            "intent":      self.intent.to_dict() if self.intent else None,
            "proposal":    self.proposal.proposal.to_dict() if (self.proposal and self.proposal.proposal) else None,
            "result":      {
                "success":      self.result.success,
                "summary":      self.result.summary(),
                "duration":     self.result.duration,
                "rolled_back":  self.result.rolled_back,
            } if self.result else None,
        }


# ── Pipeline ──────────────────────────────────────────────────────────────────

class StratumPipeline:
    def __init__(self, project_root: Optional[str] = None, dry_run: bool = False):
        self.project_root = project_root or os.path.dirname(os.path.abspath(__file__))
        self.dry_run      = dry_run
        self._correlator  = get_correlator(self.project_root)
        self._proposal_engine = get_engine()
        self._executor    = Executor(self.project_root, dry_run=dry_run)

    def _emit(self, cb: Optional[EventCallback], stage: PipelineStage,
              msg: str, data: Any = None) -> None:
        if cb:
            try:
                cb(PipelineEvent(stage=stage, message=msg, data=data))
            except Exception:
                pass

    def run_async(
        self,
        query:    str,
        callback: Optional[EventCallback] = None,
        timeout:  float = 120.0,
    ) -> PipelineRun:
        """
        Starts the pipeline on a background thread.
        Returns the PipelineRun immediately.
        Call run.approve() or run.reject() from the UI thread.
        """
        run = PipelineRun(query=query, project_root=self.project_root)
        t = threading.Thread(
            target=self._run_pipeline,
            args=(run, callback, timeout),
            daemon=True,
            name=f"stratum-pipeline-{run.run_id}",
        )
        t.start()
        return run

    def _run_pipeline(
        self,
        run:      PipelineRun,
        callback: Optional[EventCallback],
        timeout:  float,
    ) -> None:
        try:
            # Stage 1: Intent parsing (fast, no I/O)
            self._emit(callback, PipelineStage.PARSING, "Parsing intent…")
            run.intent = parse_intent(run.query)

            if run.intent.clarification_needed:
                self._emit(callback, PipelineStage.ERROR,
                           run.intent.clarification_needed, run.intent)
                return

            self._emit(callback, PipelineStage.PARSING,
                       f"Intent: {run.intent.intent_class.value} "
                       f"(confidence {run.intent.confidence:.0%})",
                       run.intent)

            # Stage 2: Code correlation (file I/O + AST)
            self._emit(callback, PipelineStage.CORRELATING, "Correlating codebase…")
            run.correlation = self._correlator.correlate(run.intent)
            self._emit(callback, PipelineStage.CORRELATING,
                       f"Loaded {len(run.correlation.files)} file(s), "
                       f"{run.correlation.total_symbols} symbol(s)",
                       run.correlation)

            # Stage 3: Proposal generation (LLM call — can be slow)
            self._emit(callback, PipelineStage.PROPOSING,
                       "Generating proposal (LLM)…")
            run.proposal = self._proposal_engine.generate(
                intent      = run.intent,
                correlation = run.correlation,
            )

            if not run.proposal.success:
                self._emit(callback, PipelineStage.ERROR,
                           f"Proposal failed: {run.proposal.error}", run.proposal)
                return

            p = run.proposal.proposal
            self._emit(callback, PipelineStage.PROPOSING,
                       f"Proposal: {len(p.changes)} change(s) · "
                       f"confidence {p.confidence:.0%}"
                       + (" [read-only]" if p.is_read_only() else ""),
                       run.proposal)

            # Stage 4: Await user approval (unless read-only)
            if p.is_read_only():
                run.approve()  # auto-approve explain/research
            else:
                self._emit(callback, PipelineStage.AWAITING,
                           "Awaiting approval…", run.proposal)
                approved = run.wait_for_approval(timeout=timeout)
                if not approved or run._cancelled:
                    self._emit(callback, PipelineStage.CANCELLED,
                               "Proposal rejected by user.")
                    return

            # Stage 5: Execute
            self._emit(callback, PipelineStage.EXECUTING, "Executing…")
            run.result = self._executor.execute(p)

            if run.result.success:
                msg = run.result.summary()
                if run.result.read_only_output:
                    msg = run.result.read_only_output
                self._emit(callback, PipelineStage.COMPLETE, msg, run.result)
            else:
                self._emit(callback, PipelineStage.ERROR,
                           run.result.error or "Execution failed", run.result)

        except Exception as e:
            self._emit(callback, PipelineStage.ERROR, f"Pipeline error: {e}")


# ── Module-level convenience ──────────────────────────────────────────────────

_pipeline: Optional[StratumPipeline] = None

def get_pipeline(project_root: Optional[str] = None, dry_run: bool = False) -> StratumPipeline:
    global _pipeline
    if _pipeline is None or project_root:
        _pipeline = StratumPipeline(project_root=project_root, dry_run=dry_run)
    return _pipeline
