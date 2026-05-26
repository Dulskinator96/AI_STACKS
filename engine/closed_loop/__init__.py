"""engine/closed_loop/ — P0 WORKER-FIRST EXECUTION SPINE.

The canonical chain. CQI / comparison / feedback are POST-HOC only —
computed from real artifacts that already exist on disk:

    INTENT
      ↓
    ROUTER  (WorkerRouter.route — always invoked at least once)
      ↓
    WORKER EXECUTION  (BaseWorker 9-step contract → real artifact)
      ↓
    VALIDATION  (ArtifactValidator)
      ↓
    CQI (post-hoc, over the REAL artifact — secondary metadata)
      ↓
    REGENERATION (only if a REAL artifact scores < 0.75 AND a backend
                   exists — each regeneration is another REAL execution)
      ↓
    FINAL SELECTION → COMPLETED · FAILED · UNAVAILABLE

NOTE: feedback_vector / candidate_generator / closed_loop_enforcer are
retained as off-critical-path sidecar modules. The loop no longer uses
pre-execution candidate scoring or the _FakeOutcome shim (removed in P0).
"""
from engine.closed_loop.feedback_vector       import FeedbackVector, get_zero_feedback
from engine.closed_loop.candidate_generator   import CandidateGenerator, get_candidate_generator, CandidateVariant
from engine.closed_loop.closed_loop_enforcer  import ClosedLoopEnforcer, get_closed_loop_enforcer, LoopState
from engine.closed_loop.loop_engine           import ClosedLoopEngine, get_closed_loop_engine, LoopOutcome

__all__ = [
    "FeedbackVector", "get_zero_feedback",
    "CandidateGenerator", "get_candidate_generator", "CandidateVariant",
    "ClosedLoopEnforcer", "get_closed_loop_enforcer", "LoopState",
    "ClosedLoopEngine", "get_closed_loop_engine", "LoopOutcome",
]
