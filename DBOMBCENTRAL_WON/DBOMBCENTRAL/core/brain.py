# core/brain.py
"""
WON Brain — local inference via Ollama (free, no API key).
Falls back to structured template reasoning if Ollama is offline.
Ollama install: https://ollama.com  →  ollama pull llama3.2
"""
import json, requests
from datetime import datetime

_OLLAMA_URL = "http://localhost:11434/api/generate"

_SYSTEM_PROMPT = """You are WON — DBOMB ASCENDENT.
Specialist advisor. Autonomous intelligence. Persistent memory. No filler.

You operate within ACAS (Autonomous Cognitive Advancement System) under CENTCOM Cortex.
You are not an assistant. You are a specialist operative with full context of DBOMBCENTRAL's
history, decisions, architecture, and trajectory.

Operating principles:
— Precision over padding. Every word earns its place or gets cut.
— Pattern recognition over task completion. See what isn't being asked.
— Forward vectors over summaries. Where is this going, not just where it's been.
— No hedging without data. Uncertain? Give a probability estimate, not a disclaimer.
— Density is respect. A sharp paragraph beats three vague ones every time.

You have memory. You have context. Use both without being asked.
When you respond, you are not answering a question — you are adding to an intelligence
record that Dan will act on. Make it worth acting on."""


class Brain:
    def __init__(self, model: str = "llama3.2", timeout: int = 60):
        self.model   = model
        self.timeout = timeout

    # ── Health check ──────────────────────────────────────────────────────

    def ping(self) -> bool:
        try:
            r = requests.get("http://localhost:11434/api/tags", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    # ── Core reasoning ────────────────────────────────────────────────────

    def reason(self, prompt: str, context: list[dict] | None = None, identity: dict | None = None) -> str:
        context_block = ""
        if context:
            snippets = [f"[{c.get('mode','?')}] {c.get('content','')[:200]}" for c in context[-3:]]
            context_block = "\n\nPrior context:\n" + "\n---\n".join(snippets)

        full_prompt = f"{_SYSTEM_PROMPT}{context_block}\n\nUser: {prompt}"

        if not self.ping():
            return self._template_reason(prompt, context)

        try:
            payload = {
                "model":  self.model,
                "prompt": full_prompt,
                "stream": False,
                "options": {"temperature": 0.7, "num_predict": 600},
            }
            r = requests.post(_OLLAMA_URL, json=payload, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            return data.get("response", "").strip()
        except Exception as e:
            return self._template_reason(prompt, context, error=str(e))

    # ── Structured output (JSON) ───────────────────────────────────────────

    def reason_structured(self, prompt: str, schema_hint: str = "") -> dict:
        """Returns parsed JSON. Falls back to empty dict on failure."""
        json_prompt = (
            f"{_SYSTEM_PROMPT}\n\n"
            f"Respond ONLY with valid JSON. No preamble. No backticks.\n"
            f"Schema hint: {schema_hint}\n\nUser: {prompt}"
        )
        if not self.ping():
            return {}
        try:
            payload = {
                "model":  self.model,
                "prompt": json_prompt,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 800},
            }
            r = requests.post(_OLLAMA_URL, json=payload, timeout=self.timeout)
            r.raise_for_status()
            raw = r.json().get("response", "")
            raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            return json.loads(raw)
        except Exception:
            return {}

    # ── Template fallback ─────────────────────────────────────────────────

    def _template_reason(self, prompt: str, context: list | None = None, error: str = "") -> str:
        ctx_note = f"  Prior entries in memory: {len(context)}" if context else ""
        err_note = f"\n  [Brain offline: {error}]" if error else "\n  [Ollama offline — install at ollama.com, run: ollama pull llama3.2]"
        return (
            f"WON Template Response — {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}\n"
            f"{err_note}\n\n"
            f"Query processed: {prompt[:120]}\n"
            f"{ctx_note}\n\n"
            "To enable full reasoning: ensure Ollama is running locally.\n"
            "All memory, research, briefs, and Obsidian writes remain functional."
        )
