"""TASKMASTER Ω CLI self-test — `python -m omega [intent text]`.

No args → cold boot + expanded boot_check + audio/image self-test matrix +
a drift scan + a self-diagnosis. With args → run that single intent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from omega.orchestrator import get_kernel  # noqa: E402


def _print_run(label: str, result) -> None:
    d = result.to_dict()
    print(f"\n=== RUN [{label}] {d['run_id']} ===")
    print(f"  intent     : {d['intent_text']}")
    print(f"  overall    : {d['overall_truth']}  (external={d['overall_external']})")
    print(f"  confidence : {d['confidence']}   entropy={d['entropy_class']}")
    for t in d["tasks"]:
        print(f"  task {t['realm']:<10} {t['truth']:<10} worker={t['worker_state'] or '-':<8} "
              f"backend={t['backend'] or '-':<14} ledger={'Y' if t['ledger_confirmed'] else 'N'}")
        for a in t.get("artifacts", []):
            hm = {True: "MATCH", False: "MISMATCH", None: "n/a"}[a.get("hash_match")]
            print(f"      artifact exists={a['exists_on_disk']} valid={a['validation_valid']} "
                  f"hash={hm} {a['kernel_sha256']}")
        if t.get("error"):
            print(f"      error: {t['error']}")
    if d["drift"]:
        print(f"  drift: {json.dumps(d['drift'])}")
    print(f"  telemetry  : {d['telemetry_path']}")


def main(argv: list[str]) -> int:
    kernel = get_kernel()

    print("=== EXPANDED BOOT CHECK (BUILD-034) ===")
    boot = kernel.boot_check()
    print(f"  substrate_truth: {boot['substrate_truth']}")
    print(f"  delegates: {boot['delegates']['boot_truth']} "
          f"({boot['delegates']['resolved']}/{boot['delegates']['total']})")
    print(f"  rooms: {boot['rooms']}")
    print(f"  agents: {boot['agents']}")
    print(f"  replay: {boot['replay']}")
    print(f"  orchestration: {boot['orchestration']}")

    if argv:
        _print_run("cli", kernel.run(" ".join(argv)))
        return 0

    _print_run("audio", kernel.run("compose a short ambient synth tone"))
    _print_run("image", kernel.run("generate a cinematic cyberpunk city image"))

    print("\n=== DRIFT SCAN ===")
    from omega.tracing import run_drift_scan
    drift = run_drift_scan()
    print(f"  findings: {drift['total_findings']}  by_severity: {drift['by_severity']}")
    for f in drift["findings"][:8]:
        print(f"   [{f['severity']}] {f['kind']} ({f['subsystem']}): {f['detail']}")

    print("\n=== SELF DIAGNOSIS ===")
    from omega.evolution import diagnose
    diag = diagnose()
    print(f"  health: {diag['health']}  issues: {diag['issue_count']}  {diag['by_severity']}")
    for i in diag["issues"][:8]:
        print(f"   [{i['severity']}] {i['symptom']} ({i['subsystem']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
