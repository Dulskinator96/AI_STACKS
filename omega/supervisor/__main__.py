"""BUILD_SUPERVISOR CLI — python -m omega.supervisor <command>

  health   read-only: single composite system-reality snapshot (all sources)
  status   read-only: orphan procs, stale telemetry, env readiness, last good
  clean    kill orphan runtime processes + report stale telemetry (apply)
  env      verify build/runtime environment
  build    deterministic PyInstaller build (+sha256)            [heavy]
  verify   launch frozen exe, confirm API serves + reality chain [heavy]
  cycle    env -> build -> verify -> drift                       [heavy]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from omega.supervisor import get_supervisor  # noqa: E402


def main(argv: list[str]) -> int:
    cmd = (argv[0] if argv else "status").lower()
    sup = get_supervisor()
    if cmd == "health":
        out = sup.health()
    elif cmd == "status":
        out = sup.status()
    elif cmd == "clean":
        out = sup.clean(apply=True)
    elif cmd == "env":
        out = sup.environment()
    elif cmd == "build":
        out = sup.build()
    elif cmd == "verify":
        out = sup.frozen_verify()
    elif cmd == "cycle":
        out = sup.cycle()
    else:
        print(f"unknown command: {cmd}\n{__doc__}")
        return 2
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
