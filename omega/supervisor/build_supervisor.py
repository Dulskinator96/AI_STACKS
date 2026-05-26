"""omega.supervisor.build_supervisor — BUILD_SUPERVISOR (BUILD-035 §9).

First-class supervisor that compresses the dev cycle: clean → verify env →
build → frozen-verify → drift-compare → (crash bundle on failure) → record.

It encodes, as supervised Python, the manual loop proven this session:
orphan kill, deterministic PyInstaller build + sha256, launch-and-confirm the
embedded API serves, real intent → artifact-survives-exit + ledger, regression
compare against the last known-good record.

Honest classification of methods:
  status()/clean()/environment()  — deterministic, exercised in dev.
  build()/frozen_verify()/cycle()  — real subprocess orchestration; heavy
                                     (minutes); exercise on demand, not on import.
No method mutates source. Patch routing goes to omega.evolution (propose-only).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

from omega.paths import project_root, telemetry_root
from omega.supervisor.hygiene import (
    scan_processes, clean_processes, scan_stale_telemetry,
)
from omega.supervisor.environment import verify_environment

_SUP_DIR = telemetry_root() / "supervisor"


def _sup_dir() -> Path:
    try:
        _SUP_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return _SUP_DIR


class BuildSupervisor:
    def __init__(self) -> None:
        self.root = project_root()

    # ── observe ──────────────────────────────────────────────────────────
    def status(self) -> dict:
        return {
            "timestamp": time.time(),
            "processes": scan_processes(),
            "stale_telemetry": scan_stale_telemetry(),
            "environment_ready": verify_environment()["ready_to_build"],
            "last_known_good": self._last_known_good_summary(),
        }

    def health(self, *, persist: bool = True) -> dict:
        """Single verified system-reality snapshot (composes all sources)."""
        from omega.supervisor.health import health_snapshot
        return health_snapshot(persist=persist)

    def clean(self, *, apply: bool = False) -> dict:
        return {"processes": clean_processes(apply=apply),
                "stale_telemetry": scan_stale_telemetry()}

    def environment(self) -> dict:
        return verify_environment()

    # ── build (heavy; real) ─────────────────────────────────────────────────
    def build(self) -> dict:
        """Deterministic PyInstaller build. Returns a build record with sha256."""
        clean_processes(apply=True)             # E3: free the locked exe first
        stage = self.root / "build" / "release"
        rec = {"started_at": time.time(), "ok": False, "exe": None,
               "sha256": None, "size": None, "error": None}
        try:
            import shutil
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
            stage.mkdir(parents=True, exist_ok=True)
            proc = subprocess.run(
                [sys.executable, "-m", "PyInstaller", "--noconfirm",
                 "--distpath", str(stage),
                 "--workpath", str(self.root / "build" / "pyinstaller"),
                 "ai_monitor.spec"],
                cwd=str(self.root), capture_output=True, text=True, timeout=900)
            exe = stage / "DBOMBLOCAL.exe"
            if exe.is_file():
                import hashlib
                h = hashlib.sha256(exe.read_bytes()).hexdigest()
                rec.update(ok=True, exe=str(exe), sha256=h, size=exe.stat().st_size)
                shutil.copy2(exe, self.root / "DBOMBLOCAL.exe")
            else:
                rec["error"] = f"exe missing (PyInstaller rc={proc.returncode})"
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
        rec["finished_at"] = time.time()
        self._record("build", rec)
        return rec

    # ── frozen verify (heavy; real) ─────────────────────────────────────────
    def frozen_verify(self, *, port: int = 8077, boot_timeout: float = 360.0,
                      serve_timeout: float = 240.0) -> dict:
        """Launch the frozen exe, confirm the embedded API serves, run a real
        intent, confirm the artifact + ledger survive process exit."""
        clean_processes(apply=True)
        exe = self.root / "build" / "release" / "DBOMBLOCAL.exe"
        tel = self.root / "build" / "release" / "telemetry"
        ob = tel / "omega_boot.json"
        rec = {"started_at": time.time(), "verdict": "UNRESOLVED", "api_serving": False,
               "intent_resolved": False, "artifact_survives": False, "ledger_ok": False,
               "exe_sha256": None, "error": None}
        if not exe.is_file():
            rec.update(verdict="BLOCKED", error="no frozen exe at build/release")
            return rec
        try:
            import hashlib
            rec["exe_sha256"] = hashlib.sha256(exe.read_bytes()).hexdigest()
            try:
                ob.unlink()
            except Exception:
                pass
            proc = subprocess.Popen([str(exe)])
            base = f"http://127.0.0.1:{port}"
            # wait for substrate boot record
            deadline = time.time() + boot_timeout
            while time.time() < deadline and not ob.is_file():
                time.sleep(3)
            # wait for the API to actually serve
            sdl = time.time() + serve_timeout
            while time.time() < sdl:
                try:
                    if urllib.request.urlopen(f"{base}/health", timeout=3).status == 200:
                        rec["api_serving"] = True
                        break
                except Exception:
                    time.sleep(2)
            if rec["api_serving"]:
                body = json.dumps({"text": "compose a short ambient synth tone"}).encode()
                req = urllib.request.Request(f"{base}/intent", data=body,
                                             headers={"Content-Type": "application/json"})
                run = json.loads(urllib.request.urlopen(req, timeout=120).read())
                t = run["tasks"][0]
                rec["intent_resolved"] = run.get("overall_truth") == "RESOLVED"
                artifact = t["artifacts"][0]["path"] if t.get("artifacts") else None
                eid = t.get("execution_id")
            else:
                artifact = eid = None
            # kill, then confirm survival
            try:
                proc.terminate()
            except Exception:
                pass
            time.sleep(3)
            if artifact:
                rec["artifact_survives"] = Path(artifact).is_file()
            if eid:
                rec["ledger_ok"] = self._ledger_has(tel / "mem_palace.db", eid)
            ok = (rec["api_serving"] and rec["intent_resolved"]
                  and rec["artifact_survives"] and rec["ledger_ok"])
            rec["verdict"] = "PASS_REAL_EXECUTION" if ok else "PARTIAL"
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
            rec["verdict"] = "FAILED"
            self._crash_bundle(rec)
        rec["finished_at"] = time.time()
        if rec["verdict"] == "PASS_REAL_EXECUTION":
            self._record("known_good", rec)
        self._record("verify", rec)
        return rec

    # ── full cycle ───────────────────────────────────────────────────────────
    def cycle(self) -> dict:
        env = self.environment()
        if not env["ready_to_build"]:
            return {"verdict": "BLOCKED", "reason": "environment not ready",
                    "missing": env["missing_required"]}
        build = self.build()
        if not build["ok"]:
            self._crash_bundle(build)
            return {"verdict": "BUILD_FAILED", "build": build}
        verify = self.frozen_verify()
        drift = self.drift_compare(verify)
        return {"verdict": verify["verdict"], "build_sha256": build["sha256"],
                "verify": verify, "drift": drift}

    # ── drift / regression ───────────────────────────────────────────────────
    def drift_compare(self, verify: dict) -> dict:
        kg = self._read("known_good")
        if not kg:
            return {"baseline": None, "regression": False, "note": "no prior known-good"}
        regressed = (kg.get("verdict") == "PASS_REAL_EXECUTION"
                     and verify.get("verdict") != "PASS_REAL_EXECUTION")
        return {"baseline_sha256": kg.get("exe_sha256"),
                "current_sha256": verify.get("exe_sha256"),
                "baseline_verdict": kg.get("verdict"),
                "current_verdict": verify.get("verdict"),
                "regression": regressed}

    # ── helpers ──────────────────────────────────────────────────────────────
    @staticmethod
    def _ledger_has(db: Path, eid: str) -> bool:
        try:
            import sqlite3
            c = sqlite3.connect(str(db))
            row = c.execute("SELECT 1 FROM executions WHERE execution_id=? AND success=1",
                            (eid,)).fetchone()
            c.close()
            return row is not None
        except Exception:
            return False

    def _record(self, kind: str, rec: dict) -> None:
        try:
            (_sup_dir() / f"{kind}.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _read(self, kind: str) -> Optional[dict]:
        try:
            p = _sup_dir() / f"{kind}.json"
            return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
        except Exception:
            return None

    def _last_known_good_summary(self) -> Optional[dict]:
        kg = self._read("known_good")
        if not kg:
            return None
        return {"exe_sha256": kg.get("exe_sha256"), "verdict": kg.get("verdict"),
                "when": kg.get("finished_at")}

    def _crash_bundle(self, ctx: dict) -> Optional[str]:
        """Bundle telemetry + the failing context for post-mortem (§9)."""
        try:
            ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            d = _sup_dir() / "crash_bundles" / ts
            d.mkdir(parents=True, exist_ok=True)
            (d / "context.json").write_text(json.dumps(ctx, indent=2), encoding="utf-8")
            tel = telemetry_root()
            for name in ("omega_boot.json", "backend_scan.json", "boot_self_check.json",
                         "mem_palace_boot_check.json", "DRIFT_REPORT.json"):
                src = tel / name
                if src.is_file():
                    (d / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            return str(d)
        except Exception:
            return None


_SUP: Optional[BuildSupervisor] = None


def get_supervisor() -> BuildSupervisor:
    global _SUP
    if _SUP is None:
        _SUP = BuildSupervisor()
    return _SUP
