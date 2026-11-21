#!/usr/bin/env python3
"""Stage-1 MemPalace tomb experiment: persistent shared-memory recall.

Requires the genuine MemPalace CLI. No LLM-internal learning is claimed.
Only disposable synthetic memories are used.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time


def cli(*arguments):
    command = [sys.executable, "-m", "mempalace.cli", *map(str, arguments)]
    p = subprocess.run(command, text=True, capture_output=True, timeout=360)
    if p.returncode:
        raise RuntimeError(f"{command!r}: rc={p.returncode}\n{p.stdout}\n{p.stderr}")
    return p.stdout


def assert_contains(haystack, needle, label):
    if needle not in haystack:
        raise AssertionError(f"{label}: exact memory marker absent")


def experiment():
    trial = secrets.token_hex(12)
    with tempfile.TemporaryDirectory(prefix="mempalace-tombs-") as scratch:
        root = Path(scratch)
        palace = root / "memory-store"
        one = root / "tomb-one-source"
        two = root / "tomb-two-source"
        one.mkdir()
        two.mkdir()
        historical = f"FOUNDING_MEMORY_{trial}"
        later = f"PRIVATE_AFTER_MOVE_{secrets.token_hex(12)}"
        # These are synthetic model-identity records, not running LLM processes.
        (one / "shared_history.md").write_text(
            f"# Tomb One shared history\n"
            f"Model A and Model B were present together.\n"
            f"Model B's founding memory is {historical}.\n"
            f"Both model identities were given the same version-1 instructions.\n",
            encoding="utf-8",
        )
        cli("--palace", palace, "mine", one, "--wing", "tomb-one")
        before = cli("--palace", palace, "search",
                     "Model B founding memory", "--wing", "tomb-one", "--results", "10")
        assert_contains(before, historical, "pre-move search")
        # Relocation changes the model's membership. The tomb-one MEMORY
        # remains at its source; do not delete or rewrite prior experience.
        membership = {"model_a": "tomb-one", "model_b": "tomb-two"}
        (two / "model_b_private.md").write_text(
            f"# Tomb Two private post-move experience\nModel B knows {later}.\n",
            encoding="utf-8",
        )
        cli("--palace", palace, "mine", two, "--wing", "tomb-two")
        after = cli("--palace", palace, "search",
                    "Model B founding memory", "--wing", "tomb-one", "--results", "10")
        assert_contains(after, historical, "post-move search")
        if later in after:
            raise AssertionError("private post-move marker leaked into tomb-one search")
        private = cli("--palace", palace, "search",
                      "Model B private post-move experience", "--wing", "tomb-two",
                      "--results", "10")
        assert_contains(private, later, "tomb-two search")
        # Export gives a direct persistence check independent of search ranking.
        export = root / "export"
        cli("--palace", palace, "export", export)
        exported = "\n".join(
            x.read_text(encoding="utf-8") for x in export.rglob("*.md"))
        assert_contains(exported, historical, "verbatim archival export")
        assert_contains(exported, later, "private archival export")
        return {
            "result": "PASS", "stage": "historical-shared-memory",
            "model_processes_moved": False, "model_membership": membership,
            "pre_move_recall": True, "post_move_recall": True,
            "tomb_two_recall": True, "verbatim_export": True,
            "cross_tomb_private_search_leak": False,
            "limitations": "No live LLMs; no claim of weight learning or access-control isolation.",
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    start = time.monotonic()
    try:
        result = experiment()
        result["duration_s"] = round(time.monotonic() - start, 3)
        print(json.dumps(result, indent=2, sort_keys=True))
        if args.report:
            Path(args.report).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        failure = {"result": "FAIL", "reason": str(exc),
                   "duration_s": round(time.monotonic() - start, 3)}
        print(json.dumps(failure, indent=2), file=sys.stderr)
        if args.report:
            Path(args.report).write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
        sys.exit(1)
