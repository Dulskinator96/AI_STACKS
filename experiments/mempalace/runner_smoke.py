"""Minimal no-mock runner diagnostic: verifies actual GitHub Actions Python execution.

This script does not test MemPalace or LLMs. It proves that a real GitHub
runner started, executed Python and wrote observable evidence.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from datetime import datetime, timezone


def main():
    source = Path(__file__).read_bytes()
    proc = subprocess.run([sys.executable, "-c", "print(7*6)"],
                          capture_output=True, text=True, timeout=10, check=True)
    if proc.stdout.strip() != "42":
        raise RuntimeError("Python execution returned an incorrect value")
    receipt = {
        "result": "PASS",
        "scope": "actual-python-runner-smoke-only",
        "utc": datetime.now(timezone.utc).isoformat(),
        "github_run_id": os.environ.get("GITHUB_RUN_ID", "NOT_GITHUB_ACTIONS"),
        "github_sha": os.environ.get("GITHUB_SHA", "UNKNOWN"),
        "github_ref": os.environ.get("GITHUB_REF", "UNKNOWN"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "script_sha256": hashlib.sha256(source).hexdigest(),
        "subprocess_result": proc.stdout.strip(),
        "llm_inference": "NOT_TESTED",
        "mempalace_recall": "NOT_TESTED"
    }
    Path("mempalace-runner-smoke.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    if receipt["github_run_id"] == "NOT_GITHUB_ACTIONS":
        raise RuntimeError("Test did not execute in GitHub Actions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
