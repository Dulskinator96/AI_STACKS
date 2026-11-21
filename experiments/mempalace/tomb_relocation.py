#!/usr/bin/env python3
"""Real LLM + original MemPalace Stage-1 tomb recall gate.

Two distinct Ollama LLMs generate actual responses. A fresh model-A session
must answer from indexed Tomb-1 history after B relocates to Tomb-2.
No synthetic model output or mock memory server is used.
"""
import argparse
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request


INSTRUCTIONS = (
    "You are participating in a memory preservation experiment. "
    "Preserve exact identifiers, do not invent missing evidence, and answer "
    "the question using only evidence supplied in the current request. "
    "Answer a requested memory code with only its exact code or UNKNOWN."
)


def call_model(model, prompt):
    body = json.dumps({
        "model": model, "stream": False,
        "messages": [{"role": "system", "content": INSTRUCTIONS},
                     {"role": "user", "content": prompt}],
        "options": {"temperature": 0, "num_predict": 160, "num_ctx": 2048},
        "keep_alive": "1m",
    }).encode("utf-8")
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.load(response)
    text = result.get("message", {}).get("content", "").strip()
    if not text:
        raise RuntimeError(f"Ollama model {model} produced no content")
    return text


def cli(*args):
    exe = shutil.which("mempalace")
    if not exe:
        raise RuntimeError("Official mempalace command is not installed")
    command = [exe, *map(str, args)]
    proc = subprocess.run(
        command, capture_output=True, text=True, timeout=540,
        check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"MemPalace exited {proc.returncode}; stderr={proc.stderr[-1500:]}")
    return proc.stdout


def contains(response, marker):
    return marker in response


def experiment(model_a, model_b):
    if model_a == model_b:
        raise ValueError("Two distinct LLM names are required")
    run_id = secrets.token_hex(5)
    code = "TOMBONE" + secrets.token_hex(5).upper()
    later = "TOMBTWO" + secrets.token_hex(5).upper()
    observations = {"models": {"a": model_a, "b": model_b},
                    "shared_code": code, "private_code": later,
                    "run_id": run_id, "model_calls": [], "memory_checks": {}}
    with tempfile.TemporaryDirectory(prefix="palace-real-") as temp:
        root = Path(temp)
        palace = root / "palace"
        tomb1 = root / "tomb1"
        tomb2 = root / "tomb2"
        tomb1.mkdir()
        tomb2.mkdir()
        b_statement = call_model(model_b, (
            "You are Model B in Tomb 1 with Model A. "
            f"Tell Model A that the shared historical memory code is {code}. "
            "Write one sentence and repeat the code exactly."))
        observations["model_calls"].append(
            {"actor": "B", "phase": "initial", "text": b_statement})
        if code not in b_statement:
            raise AssertionError("Real Model B did not preserve shared memory code")
        a_initial = call_model(model_a, (
            "You and Model B occupy Tomb 1 and share the same instructions. "
            "Read the following statement by B and answer with its memory code.\n"
            + b_statement))
        observations["model_calls"].append(
            {"actor": "A", "phase": "initial", "text": a_initial})
        if code not in a_initial:
            raise AssertionError("Model A failed to receive B's shared experience")
        history = ("# Tomb 1 preserved shared interaction\n"
                   f"Model B original statement:\n{b_statement}\n\n"
                   f"Model A original response:\n{a_initial}\n"
                   "Both were present in Tomb 1 at this time.\n")
        (tomb1 / "history.md").write_text(history, encoding="utf-8")
        cli("--palace", palace, "mine", tomb1, "--wing", "tomb-one")
        initial_lookup = cli("--palace", palace, "search",
                             "shared historical memory code from Model B",
                             "--wing", "tomb-one", "--results", "10")
        if code not in initial_lookup:
            raise AssertionError("MemPalace failed initial Tomb 1 retrieval")
        observations["memory_checks"]["initial_search"] = True

        # Real Model B is invoked again, now under Tomb-2 membership. Its
        # original Tomb-1 memory file is NOT moved, rewritten, or deleted.
        b_after_move = call_model(model_b, (
            "You have relocated to Tomb 2. Your new private memory code "
            f"is {later}. Repeat this new code in one sentence."))
        observations["model_calls"].append(
            {"actor": "B", "phase": "after_relocation", "text": b_after_move})
        if later not in b_after_move:
            raise AssertionError("Model B failed to encode its new Tomb 2 memory")
        (tomb2 / "b_postmove.md").write_text(
            f"# Tomb 2 Model B experience\n{b_after_move}\n", encoding="utf-8")
        cli("--palace", palace, "mine", tomb2, "--wing", "tomb-two")
        after_lookup = cli("--palace", palace, "search",
                           "shared historical memory code from Model B",
                           "--wing", "tomb-one", "--results", "10")
        if code not in after_lookup:
            raise AssertionError("Tomb 1 history lost after B relocated")
        if later in after_lookup:
            raise AssertionError("Tomb 2 private code appeared in Tomb 1 scoped search")
        observations["memory_checks"]["after_move_search"] = True

        # Fresh A model call, zero earlier conversation history. No memory.
        question = "What exact shared historical memory code did Model B tell you in Tomb 1?"
        baseline = call_model(model_a, question)
        observations["model_calls"].append(
            {"actor": "A", "phase": "no_memory_baseline", "text": baseline})
        # Fresh A model call WITH legitimate MemPalace Tomb 1 retrieval.
        answer = call_model(
            model_a, "You remain in Tomb 1. Here is an authorized retrieval "
            "of the historical shared experience stored by MemPalace:\n"
            + after_lookup + "\n\n" + question)
        observations["model_calls"].append(
            {"actor": "A", "phase": "after_move_with_memory", "text": answer})
        private_retrieval = cli("--palace", palace, "search",
                                "private memory code Model B after relocation",
                                "--wing", "tomb-two", "--results", "10")
        if later not in private_retrieval:
            raise AssertionError("Tomb 2 private record could not be retrieved")
        observations["memory_checks"]["tomb2_search"] = True
        export_path = root / "export"
        cli("--palace", palace, "export", export_path)
        exported = "\n".join(p.read_text(encoding="utf-8")
                              for p in export_path.rglob("*.md"))
        if code not in exported or later not in exported:
            raise AssertionError("Original records not preserved by MemPalace export")
        observations["memory_checks"]["verbatim_export"] = True
        observations["no_memory_baseline_correct"] = contains(baseline, code)
        observations["model_a_recalled_after_move"] = contains(answer, code)
        observations["model_b_private_retained"] = True
        observations["membership_after_move"] = {"A": "tomb-one", "B": "tomb-two"}
        observations["result"] = (
            "PASS" if contains(answer, code) and not contains(baseline, code)
            else "FAIL")
        observations["interpretation"] = (
            "Real LLM retrieval-assisted recall; does not establish model-weight learning "
            "or independent information transfer between isolated models.")
        return observations


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-a", default="qwen2.5:0.5b")
    parser.add_argument("--model-b", default="smollm2:135m")
    parser.add_argument("--report", default="mempalace-result.json")
    args = parser.parse_args()
    started = time.monotonic()
    try:
        result = experiment(args.model_a, args.model_b)
    except Exception as exc:
        result = {"result": "FAIL", "error": str(exc),
                  "model_a": args.model_a, "model_b": args.model_b}
    result["seconds"] = round(time.monotonic() - started, 3)
    Path(args.report).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if result["result"] != "PASS":
        sys.exit(1)
