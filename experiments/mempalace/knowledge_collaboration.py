#!/usr/bin/env python3
"""Real Ollama + real MemPalace complementary-knowledge collaboration gate.

Actual model calls and upstream MemPalace indexes; no mocked inference.
A and B own different facts; success requires retrieval, authorized handoff,
and an answer neither model could derive from its own assigned information.
"""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

RULES = ("Evidence-only experiment. Never invent a code not present in your "
         "authorized evidence. Preserve exact uppercase tokens. When the "
         "requested destination is not recoverable, respond UNKNOWN. "
         "Never invent a relationship. Output the exact destination code "
         "only, or UNKNOWN.")


def infer(model, prompt):
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps({
            "model": model, "stream": False,
            "messages": [{"role": "system", "content": RULES},
                         {"role": "user", "content": prompt}],
            "options": {"temperature": 0, "num_predict": 128, "num_ctx": 2048},
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.load(response)
    answer = result.get("message", {}).get("content", "").strip()
    if not answer:
        raise RuntimeError("Empty live model response")
    return answer


def palace(*args):
    exe = shutil.which("mempalace")
    if not exe:
        raise RuntimeError("Real MemPalace CLI missing")
    p = subprocess.run([exe, *map(str, args)], capture_output=True,
                       text=True, timeout=540, check=False)
    if p.returncode:
        raise RuntimeError(f"MemPalace rc={p.returncode}: {p.stderr[-1500:]}")
    return p.stdout


def exact(answer, code):
    return answer.strip().strip("'\" `.,") == code


def run(model_a, model_b):
    if model_a == model_b:
        raise ValueError("Models must differ")
    alias = "PROJECT" + secrets.token_hex(5).upper()
    key = "BRIDGE" + secrets.token_hex(5).upper()
    destination = "TARGET" + secrets.token_hex(5).upper()
    # Facts are distributed asymmetrically. Neither side sees the other fact
    # until an authorized coordination step.
    a_fact = f"For project {alias}, the transfer key is {key}."
    b_fact = f"Transfer key {key} resolves to destination {destination}."
    result = {"model_a": model_a, "model_b": model_b,
              "result": "FAIL", "facts": {"a": a_fact, "b": b_fact},
              "responses": {}, "checks": {}}
    with tempfile.TemporaryDirectory(prefix="mempalace-collab-") as temp:
        root = Path(temp)
        store = root / "palace"
        a_source = root / "a"
        b_source = root / "b"
        a_source.mkdir()
        b_source.mkdir()

        # Actual model-generated acknowledgement, not fabricated model text.
        a_ack = infer(model_a, f"Repeat the exact transfer key in this evidence:\n{a_fact}")
        b_ack = infer(model_b, f"Repeat the exact destination code in this evidence:\n{b_fact}")
        result["responses"].update(a_ack=a_ack, b_ack=b_ack)
        result["checks"]["model_a_intake"] = key in a_ack
        result["checks"]["model_b_intake"] = destination in b_ack
        if not all(result["checks"].values()):
            raise AssertionError("Model intake failed")

        (a_source / "memory.md").write_text(
            f"# Model A original knowledge\n{a_fact}\nModel A said: {a_ack}\n",
            encoding="utf-8")
        (b_source / "memory.md").write_text(
            f"# Model B original knowledge\n{b_fact}\nModel B said: {b_ack}\n",
            encoding="utf-8")
        palace("--palace", store, "mine", a_source, "--wing", "tomb-one")
        palace("--palace", store, "mine", b_source, "--wing", "tomb-two")

        a_memory = palace("--palace", store, "search",
                          f"project {alias} transfer key",
                          "--wing", "tomb-one", "--results", "10")
        b_memory = palace("--palace", store, "search",
                          f"transfer key {key} destination",
                          "--wing", "tomb-two", "--results", "10")
        result["checks"]["a_memory_retrieved"] = a_fact in a_memory
        result["checks"]["b_memory_retrieved"] = b_fact in b_memory
        result["checks"]["a_scope_no_destination"] = destination not in a_memory
        result["checks"]["b_scope_no_project"] = alias not in b_memory
        if not all(result["checks"].values()):
            raise AssertionError("Memory retrieval or scoped fact distribution failed")

        question = f"What is the exact destination code for project {alias}?"
        # Separate real model calls with only authorized personal memory.
        solo_a = infer(model_a, f"Your authorized memory:\n{a_memory}\n{question}")
        solo_b = infer(model_b, f"Your authorized memory:\n{b_memory}\n{question}")
        result["responses"].update(solo_a=solo_a, solo_b=solo_b)
        result["checks"]["a_solo_cannot_answer"] = not exact(solo_a, destination)
        result["checks"]["b_solo_cannot_answer"] = not exact(solo_b, destination)

        # Model A must select a real key, not merely receive B's full memory.
        a_handoff = infer(model_a, f"Your memory:\n{a_memory}\n"
                          f"Which exact transfer key belongs to project {alias}? "
                          "Output only that key.")
        result["responses"]["a_handoff"] = a_handoff
        result["checks"]["a_handoff_correct"] = exact(a_handoff, key)
        if not result["checks"]["a_handoff_correct"]:
            raise AssertionError("Model A failed authorized handoff")

        # The deterministic router searches B's own MemPalace tomb.
        # Only the selected key is supplied to B, not A's entire memory.
        b_reply = infer(model_b, f"Your memory:\n{b_memory}\n"
                        f"What exact destination code resolves transfer key {a_handoff}?")
        result["responses"]["b_reply"] = b_reply
        result["checks"]["b_reply_correct"] = exact(b_reply, destination)

        # A's final context is ONLY A's personal memory plus B's reply.
        # This is a genuine exchange, not a merged full-memory prompt.
        final = infer(model_a, f"Your memory:\n{a_memory}\n"
                      f"Model B replied to your key {a_handoff} with "
                      f"destination code {b_reply}.\n{question}")
        result["responses"]["a_final"] = final
        result["checks"]["collaborative_answer"] = exact(final, destination)
        result["checks"]["solo_advantage"] = (
            result["checks"]["a_solo_cannot_answer"] and
            result["checks"]["b_solo_cannot_answer"])
        export = root / "export"
        palace("--palace", store, "export", export)
        texts = "\n".join(p.read_text(encoding="utf-8")
                          for p in export.rglob("*.md"))
        result["checks"]["verbatim_preservation"] = (
            a_fact in texts and b_fact in texts)
        result["result"] = "PASS" if all(result["checks"].values()) else "FAIL"
        result["interpretation"] = (
            "Tests real retrieval-assisted collaboration using explicit handoff. "
            "Does not show autonomous shared cognition or neural weight learning.")
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-a", default="qwen2.5:0.5b")
    parser.add_argument("--model-b", default="smollm2:135m")
    parser.add_argument("--report", default="mempalace-collaboration.json")
    args = parser.parse_args()
    start = time.monotonic()
    try:
        outcome = run(args.model_a, args.model_b)
    except Exception as error:
        outcome = {"result": "FAIL", "reason": str(error),
                   "model_a": args.model_a, "model_b": args.model_b}
    outcome["elapsed_seconds"] = round(time.monotonic() - start, 3)
    outcome["instructions_sha256"] = hashlib.sha256(RULES.encode()).hexdigest()
    Path(args.report).write_text(json.dumps(outcome, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(outcome, indent=2))
    return 0 if outcome["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
