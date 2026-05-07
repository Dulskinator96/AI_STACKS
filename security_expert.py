# security_expert.py — Elite Cyber Security Expert Analyst
# ──────────────────────────────────────────────────────────────────────────────
# Advanced security analysis engine for AI Monitor.
# Integrates Ollama (security-expert model), Bandit, and Semgrep.
# ──────────────────────────────────────────────────────────────────────────────

import os
import sys
import json
import subprocess
import requests
from datetime import datetime, timezone
from pathlib import Path

# ── Paths & Config ─────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "security-expert:latest"

# Helper to find scripts folder
def get_scripts_dir():
    return Path(sys.executable).parent / "Scripts"

# ── Expert Engine ──────────────────────────────────────────────────────────────

class CyberSecurityExpert:
    """Elite security analyst specializing in code audits and threat modeling."""

    def __init__(self, model=MODEL_NAME):
        self.model = model
        self.scripts_dir = get_scripts_dir()

    def analyze_code(self, code: str, filename: str = "unknown") -> str:
        """Deep architectural and vulnerability audit of source code."""
        prompt = (
            f"### SECURITY AUDIT REQUEST\n"
            f"FILE: {filename}\n"
            f"SOURCE CODE:\n```python\n{code}\n```\n\n"
            f"Perform a comprehensive audit. Identify vulnerabilities, logic flaws, "
            f"and compliance issues with CENTCOM UTM mandates. "
            f"Provide a risk-rated report with remediation steps."
        )
        return self._query_ollama(prompt)

    def analyze_logs(self, logs: str) -> str:
        """Analyze system logs for Indicators of Compromise (IoC)."""
        prompt = (
            f"### LOG FORENSICS REQUEST\n"
            f"LOG DATA:\n{logs}\n\n"
            f"Analyze these logs for malicious patterns, unauthorized access, "
            f"or lateral movement. Reference MITRE ATT&CK techniques."
        )
        return self._query_ollama(prompt)

    def run_sast(self, target_path: str) -> dict:
        """Run local SAST tools (Bandit & Semgrep) and return aggregated results."""
        report = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "target": target_path,
            "bandit": self._exec_bandit(target_path),
            "semgrep": self._exec_semgrep(target_path),
        }
        return report

    def _exec_bandit(self, path: str) -> dict:
        cmd = [sys.executable, "-m", "bandit", "-r", path, "-f", "json"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            return json.loads(result.stdout)
        except Exception as e:
            # Try direct script path
            bandit_exe = self.scripts_dir / "bandit.exe"
            if bandit_exe.exists():
                try:
                    result = subprocess.run([str(bandit_exe), "-r", path, "-f", "json"], capture_output=True, text=True)
                    return json.loads(result.stdout)
                except Exception as e2:
                    return {"error": f"Bandit execution failed: {e2}"}
            return {"error": f"Bandit failed: {e}"}

    def _exec_semgrep(self, path: str) -> dict:
        semgrep_exe = self.scripts_dir / "semgrep.exe"
        cmd = [str(semgrep_exe) if semgrep_exe.exists() else "semgrep", "scan", "--config", "auto", "--json", path]
        try:
            # Fix for Windows encoding issues
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            result = subprocess.run(cmd, capture_output=True, text=True, env=env, encoding="utf-8")
            if not result.stdout.strip():
                return {"error": f"Semgrep returned empty output. Stderr: {result.stderr}"}
            return json.loads(result.stdout)
        except Exception as e:
            return {"error": f"Semgrep failed: {e}"}

    def _query_ollama(self, prompt: str) -> str:
        try:
            resp = requests.post(
                OLLAMA_URL,
                json={"model": self.model, "prompt": prompt, "stream": False},
                timeout=90,
            )
            return resp.json().get('response', "Security Engine Error: Empty response.")
        except Exception as e:
            return f"Security Engine Offline: {e}"


# ── CLI Interface ──────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python security_expert.py [analyze|scan] [path/to/file]")
        return

    cmd  = sys.argv[1]
    expert = CyberSecurityExpert()

    if cmd == "analyze" and len(sys.argv) > 2:
        path = Path(sys.argv[2])
        if path.is_file():
            print(f"[*] Auditing: {path.name}...")
            print(expert.analyze_code(path.read_text(encoding="utf-8"), path.name))
        else:
            print("[!] Error: File not found.")

    elif cmd == "scan" and len(sys.argv) > 2:
        path = sys.argv[2]
        print(f"[*] Running SAST on: {path}...")
        results = expert.run_sast(path)
        
        # Simple summary output
        b_count = len(results.get("bandit", {}).get("results", []))
        s_count = len(results.get("semgrep", {}).get("results", []))
        print(f"[*] Done. Bandit: {b_count} issues | Semgrep: {s_count} issues.")
        
        # Save full report
        report_file = _HERE / "security_report.json"
        report_file.write_text(json.dumps(results, indent=2))
        print(f"[*] Full report saved to: {report_file}")

    else:
        print("[!] Invalid command or missing path.")

if __name__ == "__main__":
    main()
