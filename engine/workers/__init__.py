"""engine/workers/ — BUILD-022 HARD WORKERS.

7 production workers, each implementing the 9-step worker execution
contract:

  1. Spawn isolated workspace
  2. Build execution manifest
  3. Execute subprocess/tool/API
  4. Verify artifact existence
  5. Hash artifact
  6. Register lineage
  7. Emit preview registration
  8. Emit export manifest
  9. Emit READY or FAIL state

Reality Enforcement: NO synthetic READY state. If any validation step
fails, worker enters FAIL with remediation. Lineage preserved.
"""
from engine.workers.base_worker        import BaseWorker, WorkerRequest, WorkerOutcome, ValidationResult
from engine.workers.image_worker       import ImageWorker, get_image_worker
from engine.workers.video_worker       import VideoWorker, get_video_worker
from engine.workers.audio_worker       import AudioWorker, get_audio_worker
from engine.workers.game_worker        import GameWorker, get_game_worker
from engine.workers.simulation_worker  import SimulationWorker, get_simulation_worker
from engine.workers.code_worker        import CodeWorker, get_code_worker
from engine.workers.cast_worker        import CastWorker, get_cast_worker


def get_worker_for_realm(realm: str):
    """Return the worker singleton for a realm name."""
    r = (realm or "").lower()
    if r == "image":      return get_image_worker()
    if r == "video":      return get_video_worker()
    if r == "audio":      return get_audio_worker()
    if r == "game":       return get_game_worker()
    if r == "simulation": return get_simulation_worker()
    if r == "code":       return get_code_worker()
    if r == "cast":       return get_cast_worker()
    return None


__all__ = [
    "BaseWorker", "WorkerRequest", "WorkerOutcome", "ValidationResult",
    "ImageWorker", "get_image_worker",
    "VideoWorker", "get_video_worker",
    "AudioWorker", "get_audio_worker",
    "GameWorker", "get_game_worker",
    "SimulationWorker", "get_simulation_worker",
    "CodeWorker", "get_code_worker",
    "CastWorker", "get_cast_worker",
    "get_worker_for_realm",
]
