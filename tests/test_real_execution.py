"""tests/test_real_execution.py — P0 REAL-EXECUTION VALIDATION SUITE.

Three tests, all grounded in the filesystem / direct invocation — NEVER in
log strings or status fields.

  TEST 1  REAL ARTIFACT       a real file is created on disk (size > 0, valid)
  TEST 2  ROUTING INTEGRITY   the intent reaches BaseWorker.execute()
  TEST 3  ANTI-SIMULATION     no COMPLETED / CQI without a real file on disk

Run standalone (no pytest needed):
    python tests/test_real_execution.py
Or under pytest:
    pytest tests/test_real_execution.py -q
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.disable(logging.CRITICAL)   # silence engine verbosity; we assert on disk

_AUDIO_INTENT = "generate audio: a short calm ambient drone for 2 seconds"


def test_real_artifact_generation():
    """TEST 1 — a real audio file must exist on disk after a UI-equivalent run."""
    from engine.closed_loop import get_closed_loop_engine
    outcome = get_closed_loop_engine().run(_AUDIO_INTENT, candidate_count=1)

    assert outcome.state == "COMPLETED", f"expected COMPLETED, got {outcome.state}"
    assert outcome.final_artifacts, "no artifacts returned"

    proven = []
    for a in outcome.final_artifacts:
        p = a.get("path", "")
        assert p and os.path.isfile(p), f"artifact path not on disk: {p}"
        assert os.path.getsize(p) > 0, f"artifact is empty: {p}"
        assert a.get("validation", {}).get("valid"), f"artifact failed validation: {p}"
        proven.append((p, os.path.getsize(p)))
    print(f"  TEST 1 PASS — real file(s) on disk: "
          f"{[(os.path.basename(p), b) for p, b in proven]}")


def test_routing_reaches_worker_execute():
    """TEST 2 — the intent MUST reach BaseWorker.execute(). We monkeypatch
    AudioWorker.execute to set a real flag, then confirm it fired."""
    import engine.workers.audio_worker as aw
    fired = {"hit": False}
    original = aw.AudioWorker.execute

    def _spy(self, request):
        fired["hit"] = True
        return original(self, request)

    aw.AudioWorker.execute = _spy
    try:
        from engine.closed_loop import get_closed_loop_engine
        get_closed_loop_engine().run(_AUDIO_INTENT, candidate_count=1)
    finally:
        aw.AudioWorker.execute = original

    assert fired["hit"], "intent did NOT reach AudioWorker.execute() — routing bypassed worker"
    print("  TEST 2 PASS — intent reached BaseWorker.execute() (worker actually ran)")


def test_no_completion_or_cqi_without_file():
    """TEST 3 — anti-simulation. For a no-backend realm the system must NOT
    report COMPLETED, must NOT attach a CQI, and must produce no artifacts.
    For the audio realm, any CQI must be backed by a real file."""
    from engine.closed_loop import get_closed_loop_engine
    eng = get_closed_loop_engine()

    # No real image backend installed on this host → must be honest.
    img = eng.run("an image of a neon city at night", candidate_count=1)
    assert img.state != "COMPLETED", "image realm claimed COMPLETED with no backend"
    assert not img.final_artifacts, "image realm produced phantom artifacts"
    assert img.final_cqi is None, "CQI attached without a real artifact (simulation)"

    # Audio realm → if a CQI exists, a real file MUST exist.
    aud = eng.run(_AUDIO_INTENT, candidate_count=1)
    if aud.final_cqi is not None:
        assert aud.final_artifacts, "CQI present but no artifact (simulation)"
        for a in aud.final_artifacts:
            assert os.path.isfile(a.get("path", "")), "CQI references a non-existent file"

    # The FakeOutcome shim must be gone entirely.
    import engine.closed_loop.loop_engine as le
    assert not hasattr(le, "_FakeOutcome"), "_FakeOutcome simulation shim still present"
    print(f"  TEST 3 PASS — image={img.state}/cqi={img.final_cqi}/arts={len(img.final_artifacts)}; "
          f"no completion or CQI without a real file; _FakeOutcome removed")


_TESTS = [
    ("TEST 1 REAL ARTIFACT", test_real_artifact_generation),
    ("TEST 2 ROUTING INTEGRITY", test_routing_reaches_worker_execute),
    ("TEST 3 ANTI-SIMULATION", test_no_completion_or_cqi_without_file),
]


def main() -> int:
    passed = failed = 0
    for name, fn in _TESTS:
        try:
            print(f"\n▶ {name}")
            fn()
            passed += 1
        except AssertionError as e:
            print(f"  {name} FAIL — {e}")
            failed += 1
        except Exception as e:
            print(f"  {name} ERROR — {type(e).__name__}: {e}")
            failed += 1
    print(f"\n=== RESULT: {passed} passed · {failed} failed (of {len(_TESTS)}) ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
