# gemini_bridge.py — Gemini CLI → AI Monitor Bridge
# ──────────────────────────────────────────────────────────────────────────────
# Wraps the Gemini CLI process. Intercepts every user prompt + model response,
# routes through the full AI Monitor pipeline (WON + MemPalace + Obsidian),
# and injects the shared ground state at session start so Gemini has perception
# of everything Claude and WON have built.
#
# Usage:
#   python gemini_bridge.py              — interactive session
#   python gemini_bridge.py --peek       — print ground state and exit
#   python gemini_bridge.py --search Q   — search ground memory and exit
#
# Or via gemini_cli.bat (recommended — sets env vars first).
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os
import sys
import re
import json
import time
import shutil
import signal
import threading
import subprocess
import argparse
from datetime import datetime
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────────
_HERE     = Path(__file__).resolve().parent
_WON_ROOT = Path(os.environ.get("WON_PATH", str(_HERE)))
for p in [str(_HERE), str(_WON_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# ── Import shared layers ───────────────────────────────────────────────────────
try:
    import pipeline as _pipeline
    PIPELINE_OK = True
except Exception as exc:
    PIPELINE_OK = False
    print(f"[Bridge] Pipeline unavailable — {exc}", file=sys.stderr)

try:
    import perception as _perception
    PERCEPTION_OK = True
except Exception as exc:
    PERCEPTION_OK = False
    print(f"[Bridge] Perception unavailable — {exc}", file=sys.stderr)

# ── Constants ──────────────────────────────────────────────────────────────────
GEMINI_CMD      = os.environ.get("GEMINI_CMD", "gemini")   # or full path
SESSION_SAVE_DIR = Path.home() / "Documents" / "AI_Monitor" / "history"
_SOURCE_TAG     = "gemini_cli"

# Heuristic: response is "done" when output is silent for this many seconds
_RESPONSE_TIMEOUT = 2.5

# Minimum chars before we consider a response worth indexing
_MIN_RESPONSE_LEN = 40


# ── Response buffer ────────────────────────────────────────────────────────────

class ExchangeBuffer:
    """Accumulates user/assistant turns for the current session."""

    def __init__(self):
        self.exchanges: list[dict] = []
        self.session_id = datetime.utcnow().strftime("GEM-%Y%m%d-%H%M%S")

    def add(self, role: str, text: str):
        text = text.strip()
        if not text:
            return
        self.exchanges.append({
            "role":      role,
            "text":      text,
            "ts":        datetime.utcnow().isoformat(),
        })

    def to_summary(self) -> str:
        lines = []
        for e in self.exchanges:
            prefix = "You" if e["role"] == "user" else "Gemini"
            lines.append(f"{prefix}: {e['text']}")
        return "\n\n".join(lines)

    def last_exchange_text(self) -> str:
        """Most recent user+assistant pair as a single string."""
        recent = self.exchanges[-2:] if len(self.exchanges) >= 2 else self.exchanges
        return "\n\n".join(
            f"{'You' if e['role'] == 'user' else 'Gemini'}: {e['text']}"
            for e in recent
        )

    def msg_count(self) -> int:
        return len(self.exchanges)


# ── Process wrapper ────────────────────────────────────────────────────────────

class GeminiBridge:
    def __init__(self):
        self.buffer   = ExchangeBuffer()
        self.proc     = None
        self._running = False
        self._lock    = threading.Lock()

    # ── Startup ────────────────────────────────────────────────────────────────

    def _check_gemini(self) -> bool:
        if shutil.which(GEMINI_CMD):
            return True
        # Also check npm global / npx
        for cmd in ["npx gemini-cli", "npx @google/gemini-cli"]:
            if shutil.which(cmd.split()[0]):
                return True
        return False

    def _build_system_context(self) -> str:
        """
        Build the ground state injection for Gemini's first prompt.
        Keeps it compact to minimise token spend.
        """
        if not PERCEPTION_OK:
            return ""
        ctx = _perception.get_compressed_context(max_chars=900)
        if not ctx:
            return ""
        return (
            "[AI MONITOR GROUND STATE]\n"
            "You have shared memory with Claude and WON. "
            "The following is the current state of our shared knowledge base:\n\n"
            f"{ctx}\n\n"
            "[END GROUND STATE — proceed with the conversation]\n"
        )

    # ── Per-exchange pipeline routing ──────────────────────────────────────────

    def _route_exchange(self, user_text: str, assistant_text: str):
        """
        After each exchange: contribute to ground + brief if significant.
        Runs in a daemon thread so it doesn't block the terminal.
        """
        exchange_text = f"You: {user_text}\n\nGemini: {assistant_text}"

        if PERCEPTION_OK:
            try:
                _perception.contribute(
                    content=exchange_text,
                    source=_SOURCE_TAG,
                    mode="exchange",
                    tags=["gemini", "exchange"],
                )
            except Exception as exc:
                print(f"[Bridge] perception.contribute — {exc}", file=sys.stderr)

    def _route_session_end(self):
        """
        On session close: run the full pipeline (Obsidian notes + brief).
        """
        summary   = self.buffer.to_summary()
        msg_count = self.buffer.msg_count()

        if not summary or msg_count == 0:
            return

        print("\n[AI Monitor] Indexing session…", flush=True)

        if PIPELINE_OK:
            try:
                result = _pipeline.process({
                    "platform":     "Gemini CLI",
                    "summary":      summary,
                    "messageCount": msg_count,
                })
                parts = []
                if result.get("won_indexed"):
                    parts.append("WON ✓")
                if result.get("palace_indexed"):
                    parts.append("MemPalace ✓")
                if result.get("brief_path"):
                    brief = Path(result["brief_path"]).name
                    parts.append(f"Brief → {brief}")
                if result.get("history_path"):
                    hist = Path(result["history_path"]).name
                    parts.append(f"History → {hist}")
                if result.get("context_updated"):
                    parts.append("context.txt ✓")
                print(f"[AI Monitor] {' · '.join(parts)}", flush=True)
            except Exception as exc:
                print(f"[Bridge] pipeline.process — {exc}", file=sys.stderr)
        elif PERCEPTION_OK:
            # Fallback: at least contribute the full summary to the ground
            _perception.contribute(
                content=summary,
                source=_SOURCE_TAG,
                mode="session",
                tags=["gemini", "session"],
            )
            print("[AI Monitor] Session contributed to ground (pipeline offline).", flush=True)

    # ── Interactive loop ───────────────────────────────────────────────────────

    def run(self):
        if not self._check_gemini():
            print(
                "[Bridge] Gemini CLI not found.\n"
                "Install: npm install -g @google/gemini-cli\n"
                "Or set GEMINI_CMD env var to the full path.",
                file=sys.stderr,
            )
            sys.exit(1)

        # Print ground state summary before starting
        print("\n" + "─" * 60)
        print("  AI Monitor — Gemini CLI Bridge")
        print("  Ground: WON + MemPalace + Obsidian")
        print("─" * 60)

        if PERCEPTION_OK:
            state = _perception.get_ground_state(max_chars=400)
            if state:
                print("\n[Ground State Preview]")
                print(state[:400])
                print()

        print("[Bridge] Starting Gemini CLI…\n")

        # Spawn gemini as subprocess with stdin/stdout pipes
        try:
            cmd = GEMINI_CMD.split() if " " in GEMINI_CMD else [GEMINI_CMD]
            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            # Try npx fallback
            try:
                self.proc = subprocess.Popen(
                    ["npx", "@google/gemini-cli"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
            except Exception as exc:
                print(f"[Bridge] Failed to start Gemini CLI — {exc}", file=sys.stderr)
                sys.exit(1)

        self._running = True

        # Read thread: streams gemini output to terminal
        response_lines: list[str] = []
        response_ready  = threading.Event()
        last_output_ts  = [time.time()]

        def read_output():
            while self._running:
                line = self.proc.stdout.readline()
                if not line:
                    break
                print(line, end="", flush=True)
                response_lines.append(line)
                last_output_ts[0] = time.time()

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()

        # Inject ground state as the very first input (if available)
        system_ctx = self._build_system_context()
        if system_ctx and self.proc.stdin:
            time.sleep(0.8)   # let gemini print its prompt first
            try:
                self.proc.stdin.write(system_ctx + "\n")
                self.proc.stdin.flush()
                time.sleep(0.3)
            except Exception:
                pass

        # Main I/O loop
        try:
            while self._running and self.proc.poll() is None:
                try:
                    user_input = input()
                except (EOFError, KeyboardInterrupt):
                    break

                if not user_input.strip():
                    continue

                # Handle bridge-specific commands
                cmd_lower = user_input.strip().lower()
                if cmd_lower in ("/peek", "/ground"):
                    ctx = _perception.get_ground_state() if PERCEPTION_OK else "Perception offline."
                    print(f"\n{ctx}\n", flush=True)
                    continue
                elif cmd_lower.startswith("/search "):
                    q = user_input[8:].strip()
                    results = _perception.search(q) if PERCEPTION_OK else []
                    for r in results[:5]:
                        src   = r.get("source_file", "?")
                        score = int(float(r.get("similarity", 0)) * 100)
                        print(f"  [{score}%] {src}\n  {r.get('text','')[:200]}\n")
                    continue
                elif cmd_lower in ("/exit", "/quit"):
                    break

                # Clear response buffer for this exchange
                response_lines.clear()
                last_output_ts[0] = time.time()

                # Send to gemini
                try:
                    self.proc.stdin.write(user_input + "\n")
                    self.proc.stdin.flush()
                except BrokenPipeError:
                    break

                self.buffer.add("user", user_input)

                # Wait for response to settle
                time.sleep(0.5)
                while time.time() - last_output_ts[0] < _RESPONSE_TIMEOUT:
                    time.sleep(0.2)

                assistant_text = "".join(response_lines).strip()

                if len(assistant_text) >= _MIN_RESPONSE_LEN:
                    self.buffer.add("assistant", assistant_text)
                    # Route exchange to ground in background — non-blocking
                    threading.Thread(
                        target=self._route_exchange,
                        args=(user_input, assistant_text),
                        daemon=True,
                    ).start()

        except Exception as exc:
            print(f"\n[Bridge] Loop error — {exc}", file=sys.stderr)

        finally:
            self._running = False
            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.stdin.write("/exit\n")
                    self.proc.stdin.flush()
                except Exception:
                    pass
                try:
                    self.proc.wait(timeout=3)
                except Exception:
                    self.proc.kill()

            self._route_session_end()
            print("\n[AI Monitor] Session closed. Ground updated.\n")


# ── CLI utilities ──────────────────────────────────────────────────────────────

def cmd_peek():
    """Print current ground state and exit."""
    if not PERCEPTION_OK:
        print("Perception layer offline — check WON_PATH and pipeline.py.")
        return
    print(_perception.get_ground_state(max_chars=2000))


def cmd_search(query: str):
    """Search ground memory and print results."""
    if not PERCEPTION_OK:
        print("Perception layer offline.")
        return
    results = _perception.search(query, limit=8)
    if not results:
        print("No results found.")
        return
    for i, r in enumerate(results, 1):
        src   = r.get("source_file", r.get("source", "?"))
        score = int(float(r.get("similarity", 0)) * 100)
        text  = r.get("text", "")[:300].replace("\n", " ")
        print(f"\n{i}. [{score}%] {src}\n   {text}")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Gemini CLI → AI Monitor Bridge")
    parser.add_argument("--peek",   action="store_true", help="Print ground state and exit")
    parser.add_argument("--search", metavar="QUERY",     help="Search ground memory and exit")
    args = parser.parse_args()

    if args.peek:
        cmd_peek()
    elif args.search:
        cmd_search(args.search)
    else:
        GeminiBridge().run()


if __name__ == "__main__":
    main()
