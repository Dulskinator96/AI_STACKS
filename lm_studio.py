# lm_studio.py — LM Studio Integration
# ──────────────────────────────────────────────────────────────────────────────
# LM Studio runs locally on port 1234 with an OpenAI-compatible API.
# Supports any model loaded in LM Studio — much larger than Ollama defaults.
#
# Setup:
#   1. Open LM Studio
#   2. Go to Local Server tab (left sidebar)
#   3. Load any model (recommended: deepseek-coder, qwen2.5-coder, codellama)
#   4. Click Start Server
#   5. Default: http://localhost:1234
#
# Docs: https://lmstudio.ai/docs/local-server
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os
import json
import requests
from datetime import datetime
import logging
_log = logging.getLogger(__name__)

LM_STUDIO_URL  = os.environ.get("LM_STUDIO_URL", "http://localhost:1234")
OLLAMA_URL     = "http://localhost:11434/api/generate"
OLLAMA_MODEL   = os.environ.get("WON_MODEL", "mistral:latest")


# ── Connection checks ──────────────────────────────────────────────────────────

def lm_studio_available() -> bool:
    """Check if LM Studio server is running."""
    try:
        r = requests.get(f"{LM_STUDIO_URL}/v1/models", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def ollama_available() -> bool:
    """Check if Ollama is running."""
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def get_lm_studio_models() -> list[str]:
    """Return list of models loaded in LM Studio."""
    try:
        r = requests.get(f"{LM_STUDIO_URL}/v1/models", timeout=5)
        if r.status_code == 200:
            data = r.json()
            return [m["id"] for m in data.get("data", [])]
    except Exception as e:
        _log.warning(f'caught exception: {e}')
    return []


def get_active_model() -> str:
    """Return the currently active model name."""
    models = get_lm_studio_models()
    return models[0] if models else "unknown"


def status() -> dict:
    """Full inference status — LM Studio + Ollama."""
    lms_ok     = lm_studio_available()
    ollama_ok  = ollama_available()
    lms_models = get_lm_studio_models() if lms_ok else []

    return {
        "lm_studio":        lms_ok,
        "lm_studio_url":    LM_STUDIO_URL,
        "lm_studio_models": lms_models,
        "active_model":     lms_models[0] if lms_models else None,
        "ollama":           ollama_ok,
        "ollama_model":     OLLAMA_MODEL,
        "primary":          "lm_studio" if lms_ok else ("ollama" if ollama_ok else "offline"),
    }


# ── Core inference ─────────────────────────────────────────────────────────────

def infer(
    prompt:      str,
    system:      str  = "",
    max_tokens:  int  = 1000,
    temperature: float = 0.4,
    timeout:     int  = 120,
    prefer_lms:  bool = True,
) -> dict:
    """
    Unified inference — tries LM Studio first, falls back to Ollama.

    Returns:
        {
            ok:        bool
            text:      str    — the model response
            model:     str    — which model was used
            source:    str    — "lm_studio" | "ollama" | "offline"
            tokens:    dict   — usage stats if available
            error:     str    — if not ok
        }
    """
    if prefer_lms and lm_studio_available():
        result = _infer_lm_studio(prompt, system, max_tokens, temperature, timeout)
        if result["ok"]:
            return result
        # Fall through to Ollama on failure

    if ollama_available():
        return _infer_ollama(prompt, system, max_tokens, temperature, timeout)

    return {
        "ok":    False,
        "text":  "",
        "model": "none",
        "source": "offline",
        "tokens": {},
        "error": (
            "No inference engine available.\n"
            "Start LM Studio server (port 1234) or run: ollama serve"
        ),
    }


def _infer_lm_studio(
    prompt:      str,
    system:      str,
    max_tokens:  int,
    temperature: float,
    timeout:     int,
) -> dict:
    """Call LM Studio via OpenAI-compatible /v1/chat/completions."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        r = requests.post(
            f"{LM_STUDIO_URL}/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json={
                "messages":    messages,
                "max_tokens":  max_tokens,
                "temperature": temperature,
                "stream":      False,
            },
            timeout=timeout,
        )
        if r.status_code != 200:
            return {
                "ok": False, "text": "", "source": "lm_studio",
                "model": "unknown", "tokens": {},
                "error": f"LM Studio returned {r.status_code}: {r.text[:200]}",
            }
        data    = r.json()
        text    = data["choices"][0]["message"]["content"].strip()
        model   = data.get("model", "lm_studio_model")
        usage   = data.get("usage", {})
        return {
            "ok":     True,
            "text":   text,
            "model":  model,
            "source": "lm_studio",
            "tokens": usage,
            "error":  "",
        }
    except requests.Timeout:
        return {"ok": False, "text": "", "source": "lm_studio",
                "model": "", "tokens": {}, "error": "LM Studio timed out"}
    except Exception as exc:
        return {"ok": False, "text": "", "source": "lm_studio",
                "model": "", "tokens": {}, "error": str(exc)}


def _infer_ollama(
    prompt:      str,
    system:      str,
    max_tokens:  int,
    temperature: float,
    timeout:     int,
) -> dict:
    """Call Ollama via its native API."""
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    try:
        r = requests.post(
            OLLAMA_URL,
            json={
                "model":  OLLAMA_MODEL,
                "prompt": full_prompt,
                "stream": False,
                "options": {
                    "temperature":    temperature,
                    "num_predict":    max_tokens,
                    "repeat_penalty": 1.1,
                },
            },
            timeout=timeout,
        )
        if r.status_code != 200:
            return {"ok": False, "text": "", "source": "ollama",
                    "model": OLLAMA_MODEL, "tokens": {},
                    "error": f"Ollama {r.status_code}"}
        data = r.json()
        return {
            "ok":     True,
            "text":   data.get("response", "").strip(),
            "model":  OLLAMA_MODEL,
            "source": "ollama",
            "tokens": {
                "prompt_tokens":     data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
            },
            "error": "",
        }
    except requests.Timeout:
        return {"ok": False, "text": "", "source": "ollama",
                "model": OLLAMA_MODEL, "tokens": {}, "error": "Ollama timed out"}
    except Exception as exc:
        return {"ok": False, "text": "", "source": "ollama",
                "model": OLLAMA_MODEL, "tokens": {}, "error": str(exc)}


# ── Streaming inference ────────────────────────────────────────────────────────

def stream(
    prompt:      str,
    system:      str   = "",
    max_tokens:  int   = 1000,
    temperature: float = 0.4,
    timeout:     int   = 120,
    on_token:    callable = None,
) -> dict:
    """
    Streaming inference from LM Studio.
    on_token(text_chunk) called for each streamed token.
    Falls back to non-streaming if LM Studio unavailable.
    """
    if not lm_studio_available():
        result = infer(prompt, system, max_tokens, temperature, timeout)
        if on_token and result["ok"]:
            on_token(result["text"])
        return result

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    full_text = []
    try:
        with requests.post(
            f"{LM_STUDIO_URL}/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json={
                "messages":    messages,
                "max_tokens":  max_tokens,
                "temperature": temperature,
                "stream":      True,
            },
            stream=True,
            timeout=timeout,
        ) as r:
            for line in r.iter_lines():
                if not line:
                    continue
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    line = line[6:]
                if line == "[DONE]":
                    break
                try:
                    chunk = json.loads(line)
                    token = chunk["choices"][0]["delta"].get("content", "")
                    if token:
                        full_text.append(token)
                        if on_token:
                            on_token(token)
                except Exception:
                    continue

        text = "".join(full_text)
        return {
            "ok":     bool(text),
            "text":   text,
            "model":  get_active_model(),
            "source": "lm_studio_stream",
            "tokens": {},
            "error":  "" if text else "No content received",
        }
    except Exception as exc:
        return {"ok": False, "text": "", "source": "lm_studio_stream",
                "model": "", "tokens": {}, "error": str(exc)}
