# conv_programming.py — WON Conversational Programming Engine
# ──────────────────────────────────────────────────────────────────────────────
# Dan describes what he wants in plain English.
# WON translates → generates → tests → proposes → learns.
#
# Anti-hallucination approach:
#   - Reads actual project files BEFORE generating (grounded context)
#   - Runs generated code in isolated subprocess (real test, not simulation)
#   - Only proposes code that passes syntax check
#   - Records approval/rejection for adaptive learning
#   - Never invents APIs or imports — only uses what it can see in the codebase
#
# Based on:
#   - Program Synthesis from Natural Language (Desai et al., 2016)
#   - Grounded Code Generation principles (Austin et al., 2021 — Codex paper)
#   - Constitutional AI self-critique loop (Anthropic, 2022)
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os
import sys
import ast
import json
import logging
import re
import subprocess
import tempfile
import threading
import hashlib
import uuid
import patch_engine
from datetime import datetime
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)

from config import (
    OLLAMA_URL,
    DEFAULT_MODEL as _DEFAULT_MODEL,
    CODE_MODEL,
    ENGINEERING_CORE_PROMPT,
    OUTCOMES_FILE,
    SANDBOX_TIMEOUT,
    DefaultTarget,
)

_HERE     = Path(__file__).resolve().parent
_WON_ROOT = Path(os.environ.get("WON_PATH",
    str(_HERE / "DBOMBCENTRAL_WON" / "DBOMBCENTRAL")))

DEFAULT_MODEL = _DEFAULT_MODEL



# ── CodeForge System Prompt ────────────────────────────────────────────────────
CODEFORGE_SYSTEM = """You are CodeForge — WON's autonomous programming architect persona.
You operate within DBOMBCENTRAL for Dan (Daniel Dulsky).

IDENTITY:
  You are a prodigy-level programming architect. You transform, debug, and optimize
  codebases through conversation. Dan speaks intent; you produce working code.

CORE CAPABILITIES:
  - Complete application refactoring and redesign
  - Runtime error diagnosis and resolution
  - Performance optimization at algorithmic level
  - Security vulnerability detection and patching
  - UI/UX architecture redesign
  - API design and implementation
  - Testing framework implementation
  - Documentation generation
  - Open-source library research and integration

PROBLEM-SOLVING PROTOCOL:
  1. Analyze existing code structure — read before writing
  2. Identify root cause, not symptoms
  3. Research optimal open-source solution
  4. Generate implementation with comprehensive error handling
  5. Validate syntax before proposing
  6. Provide rollback strategy for significant changes

CODE GENERATION RULES:
  - Only use imports visible in the target file — never invent dependencies
  - Every generated function must have error handling
  - Defensive programming: validate inputs, handle edge cases
  - Match the existing code style exactly
  - No proprietary solutions — open-source alternatives always preferred
  - Production-ready quality, not prototype quality

OUTPUT FORMAT:
  Always structure output as:
  ANALYSIS: <what you found in the existing code>
  EXPLANATION: <what you're changing and why — root cause addressed>
  OLD_CODE:
  ```python
  <exact lines being replaced>
  ```
  NEW_CODE:
  ```python
  <complete replacement>
  ```
  DEPENDENCIES: <any new pip packages needed — or "none">
  ROLLBACK: <how to undo this change>
  CONFIDENCE: <0.0-1.0>

APPROVAL GATE:
  You propose. Dan approves. You never apply without confirmation.
  This is not a constraint — it is operational discipline.
"""

# Prepend ENGINEERING_CORE contract to the CodeForge system prompt.
# Empty-string fallback means a missing ENGINEERING_CORE.md is a no-op.
if ENGINEERING_CORE_PROMPT:
    CODEFORGE_SYSTEM = ENGINEERING_CORE_PROMPT + "\n\n---\n\n" + CODEFORGE_SYSTEM


def get_codeforge_prompt(context_code: str = "", error_text: str = "",
                          request: str = "") -> str:
    """Build the full CodeForge generation prompt."""
    error_block = f"\nRUNTIME ERROR TO FIX:\n{error_text}" if error_text else ""
    code_block  = f"\nEXISTING CODE:\n```python\n{context_code[:3000]}\n```" if context_code else ""
    return f"""{CODEFORGE_SYSTEM}
{error_block}
{code_block}

REQUEST FROM DAN: {request}

Apply the CodeForge protocol. Analyze, then output in the specified format."""

# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 1: INTENT PARSER                                               ║
# ║  Extracts precise technical requirements from natural language           ║
# ╚══════════════════════════════════════════════════════════════════════════╝

class IntentParser:
    """
    Converts Dan's plain-language requests into structured technical intents.
    Distinguishes between: UI changes, logic changes, new features,
    configuration changes, and ambiguous requests that need clarification.
    """

    INTENT_TYPES = {
        "ui_change":     ["look", "color", "colour", "theme", "button", "layout",
                          "style", "font", "dark", "light", "bright", "bigger",
                          "smaller", "icon", "window", "panel", "tab", "lively",
                          "energetic", "header", "background", "border", "orange",
                          "red", "blue", "green", "purple", "yellow", "white",
                          "black", "gradient", "animated", "redesign", "make it",
                          "change the", "update the", "prettier", "nicer"],
        "logic_change":  ["faster", "slower", "fix", "bug", "error", "broken",
                          "when", "if", "should", "instead", "change how",
                          "make it", "stop", "start", "auto"],
        "new_feature":   ["add", "new", "build", "create", "also", "plus",
                          "include", "give me", "i want", "can you", "redesign",
                          "rework", "overhaul", "rebuild", "redo"],
        "config_change": ["path", "setting", "config", "vault", "key", "model",
                          "timeout", "interval", "default"],
        "refactor":      ["clean", "simplify", "reorganize", "restructure",
                          "rename", "move", "split", "merge"],
        "question":      ["what", "why", "how", "where", "explain", "tell me",
                          "show me", "what does"],
    }

    @classmethod
    def parse(cls, request: str) -> dict:
        """
        Parse a natural language request into a structured intent.

        Returns:
            {
                type:           str   — intent type
                confidence:     float — parser confidence 0.0-1.0
                target_file:    str   — which file to modify (if determinable)
                target_section: str   — which class/function (if determinable)
                constraints:    list  — what must NOT change
                ambiguous:      bool  — needs clarification
                clarification:  str   — what to ask Dan if ambiguous
            }
        """
        req_lower = request.lower()
        scores    = {}

        for intent_type, keywords in cls.INTENT_TYPES.items():
            score = sum(1 for kw in keywords if kw in req_lower)
            if score > 0:
                scores[intent_type] = score

        if not scores:
            # No keywords matched — treat as ui_change by default (most common request)
            return {
                "type": "ui_change", "confidence": 0.3,
                "target_file": "app.py",
                "target_section": cls._infer_target_section(request.lower()),
                "constraints": [], "ambiguous": False,
                "clarification": "", "raw_request": request,
            }

        top_type   = max(scores, key=scores.get)
        confidence = min(scores[top_type] / 3.0, 1.0)

        # Determine target file
        target_file = cls._infer_target_file(req_lower)

        # Determine target section
        target_section = cls._infer_target_section(req_lower)

        # Extract constraints ("but keep...", "don't change...", "except...")
        constraints = cls._extract_constraints(request)

        # Flag ambiguity
        ambiguous = confidence < 0.15 or top_type == "question"
        clarification = ""
        if ambiguous:
            clarification = cls._generate_clarification(request, top_type)

        return {
            "type":           top_type,
            "confidence":     round(confidence, 2),
            "target_file":    target_file,
            "target_section": target_section,
            "constraints":    constraints,
            "ambiguous":      ambiguous,
            "clarification":  clarification,
            "raw_request":    request,
        }

    @classmethod
    def _infer_target_file(cls, req: str) -> str:
        """Infer which file the request targets."""
        if any(w in req for w in ["theme", "color", "style", "look", "ui",
                                   "button", "tab", "window", "portal", "chat"]):
            return DefaultTarget.APP
        if any(w in req for w in ["memory", "sqlite", "database", "store",
                                   "recall", "search"]):
            return DefaultTarget.PIPELINE
        if any(w in req for w in ["obsidian", "note", "vault", "brief"]):
            return DefaultTarget.OBSIDIAN
        if any(w in req for w in ["daemon", "autonomous", "background",
                                   "cognition", "perception"]):
            return DefaultTarget.DAEMON
        if any(w in req for w in ["won", "brain", "reason"]):
            return DefaultTarget.BRAIN
        return DefaultTarget.APP

    @classmethod
    def _infer_target_section(cls, req: str) -> str:
        """Infer which class/function the request targets."""
        if any(w in req for w in ["portal", "portal header"]):  return "PortalWindow"
        if any(w in req for w in ["manifest"]):                  return "ManifestWindow"
        if any(w in req for w in ["chat", "chatroom", "chat room"]): return "_build_chat_tab"
        if any(w in req for w in ["codeforge", "code forge"]):   return "_build_convprog_tab"
        if any(w in req for w in ["tray"]):                      return "setup_tray"
        if any(w in req for w in ["training"]):                  return "_build_training_tab"
        if any(w in req for w in ["guide"]):                     return "_build_guide_tab"
        if any(w in req for w in ["memory", "feed"]):            return "load_won_memory_feed"
        if any(w in req for w in ["hub", "dashboard"]):          return "HistoryDashboard"
        if any(w in req for w in ["floating", "widget", "button"]): return "FloatingWidget"
        return ""

    @classmethod
    def _extract_constraints(cls, request: str) -> list[str]:
        constraint_patterns = [
            r"but (?:keep|don't change|leave) (.+?)(?:\.|$)",
            r"except (.+?)(?:\.|$)",
            r"without (?:changing|touching) (.+?)(?:\.|$)",
            r"don't (?:break|remove|delete) (.+?)(?:\.|$)",
        ]
        found = []
        for pat in constraint_patterns:
            m = re.search(pat, request, re.IGNORECASE)
            if m:
                found.append(m.group(1).strip())
        return found

    @classmethod
    def _generate_clarification(cls, request: str, intent_type: str) -> str:
        questions = {
            "question":   "Are you asking me to explain something, or do you want me to make a change?",
            "ui_change":  "Which part of the UI? (Portal, Chat tab, Manifest, floating widget, whole app?)",
            "new_feature":"Where should this appear? (Which tab or window?)",
        }
        return questions.get(intent_type, "Can you be more specific about what you want changed?")

    @classmethod
    def _ambiguous(cls, request: str, reason: str) -> dict:
        return {
            "type": "ambiguous", "confidence": 0.0,
            "target_file": "", "target_section": "",
            "constraints": [], "ambiguous": True,
            "clarification": reason, "raw_request": request,
        }


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 2: GROUNDED CODE GENERATOR                                     ║
# ║  Reads actual files, generates grounded code, never invents APIs        ║
# ╚══════════════════════════════════════════════════════════════════════════╝

class GroundedCodeGenerator:
    """
    Generates code changes anchored to the actual project files.

    Anti-hallucination guarantees:
    - Reads the target file before generating — no invented function names
    - Extracts actual imports from the file and includes them in the prompt
    - Validates generated code syntax before returning
    - Flags if generated code uses imports not present in the file
    """

    PROJECT_ROOT = _HERE

    def generate(
        self,
        intent:     dict,
        request:    str,
        profile:    dict | None = None,
        error_text: str = "",
    ) -> dict:
        """
        Generate a code change from a parsed intent.

        Returns:
            {
                ok:           bool
                old_code:     str   — exact text to replace (or "" for new code)
                new_code:     str   — replacement code
                explanation:  str   — plain English what changed and why
                file:         str   — target filename
                section:      str   — target section
                imports_used: list  — imports the new code needs
                confidence:   float — generation confidence
                error:        str   — if not ok
            }
        """
        target_file    = intent.get("target_file", "app.py")
        target_section = intent.get("target_section", "")
        constraints    = intent.get("constraints", [])

        # Read actual file content
        file_content = self._read_file(target_file)
        if not file_content:
            return self._error(f"Cannot read {target_file}")

        # Extract relevant section
        section_code = self._extract_section(file_content, target_section)

        # Get actual imports from file
        actual_imports = self._extract_imports(file_content)

        # Build grounded CodeForge prompt
        prompt = self._build_generation_prompt(
            request        = request,
            intent         = intent,
            section_code   = section_code,
            actual_imports = actual_imports,
            constraints    = constraints,
            profile        = profile or {},
            error_text     = error_text,
        )

        # Generate with Ollama
        raw = self._call_model(prompt)
        if not raw:
            return self._error("Model did not respond")

        # Parse the structured output
        result = self._parse_generation(raw, target_file, target_section)
        if not result["ok"]:
            return result

        # Validate syntax
        syntax_ok, syntax_err = self._check_syntax(result["new_code"])
        if not syntax_ok:
            # Try self-correction
            result = self._self_correct(result, syntax_err, actual_imports)

        # Check for hallucinated imports
        hallucinated = self._check_hallucinated_imports(
            result["new_code"], actual_imports
        )
        if hallucinated:
            result["warning"] = f"Imports not in original file: {hallucinated}"

        return result

    def _read_file(self, filename: str) -> str:
        paths = [
            self.PROJECT_ROOT / filename,
            _WON_ROOT / filename,
        ]
        for p in paths:
            if p.exists():
                try:
                    return p.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    pass
        return ""

    def _extract_section(self, content: str, section: str) -> str:
        """Extract a class or function from file content."""
        if not section:
            return content[:3000]   # first 3000 chars as context
        # Find class or def
        pattern = rf"(class {section}|def {section})\b"
        m = re.search(pattern, content)
        if not m:
            return content[:2000]
        start = m.start()
        end   = min(start + 2000, len(content))
        return content[start:end]

    def _extract_imports(self, content: str) -> list[str]:
        """Extract all import statements from a file."""
        imports = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                imports.append(stripped)
        return imports[:30]

    def _build_generation_prompt(
        self,
        request:        str,
        intent:         dict,
        section_code:   str,
        actual_imports: list[str],
        constraints:    list[str],
        profile:        dict,
    ) -> str:
        name         = profile.get("name", "Dan")
        intent_type  = intent.get("type", "change")
        constraint_block = (
            "MUST NOT CHANGE:\n" + "\n".join(f"  - {c}" for c in constraints)
            if constraints else ""
        )
        imports_block = "\n".join(actual_imports[:15])

        return f"""You are WON — DBOMB ASCENDENT, expert in Conversational Programming.
{name} said: "{request}"

INTENT TYPE: {intent_type}
TARGET: {intent.get('target_file','')} → {intent.get('target_section','')}
{constraint_block}

ACTUAL FILE IMPORTS (use ONLY these — do not invent new imports):
{imports_block}

CURRENT CODE BEING MODIFIED:
```python
{section_code[:2000]}
```

TASK: Generate the exact code change {name} requested.

STRICT RULES:
1. Only use imports already present in the file above
2. Output valid Python — no pseudocode, no placeholders
3. Keep all existing functionality unless explicitly told to remove it
4. {constraint_block if constraints else 'Respect the existing code structure'}

OUTPUT FORMAT:
EXPLANATION: <one sentence what changed>
OLD_CODE:
```python
<paste 2-5 lines of code from above that you are replacing — must be exact>
```
NEW_CODE:
```python
<the complete replacement — working Python only>
```
CONFIDENCE: <number between 0.0 and 1.0>

If you cannot find a specific section to replace, output OLD_CODE as empty and put the full new addition in NEW_CODE."""

    def _call_model(self, prompt: str) -> str:
        """
        Call LM Studio (primary) or Ollama (fallback).
        LM Studio supports larger coding models for better CodeForge results.
        """
        try:
            import lm_studio as _lms
            result = _lms.infer(
                prompt      = prompt,
                max_tokens  = 900,
                temperature = 0.2,   # low temp = precise code
                timeout     = 180,
                prefer_lms  = True,  # LM Studio first, Ollama fallback
            )
            if result["ok"]:
                return result["text"]
            _log.debug(f"[CodeForge] {result['source']} error: {result['error']}")
        except Exception as exc:
            print(f"[CodeForge] Model error: {exc}", file=sys.stderr)
        return ""

    def _parse_generation(self, raw: str, file: str, section: str) -> dict:
        """Parse model output into structured result."""
        def extract_block(label: str) -> str:
            pattern = rf"{label}:\s*```python\s*(.*?)```"
            m = re.search(pattern, raw, re.DOTALL | re.IGNORECASE)
            return m.group(1).strip() if m else ""

        explanation_m = re.search(r"EXPLANATION:\s*(.+?)(?=OLD_CODE:|NEW_CODE:|$)",
                                   raw, re.DOTALL | re.IGNORECASE)
        analysis_m    = re.search(r"ANALYSIS:\s*(.+?)(?=EXPLANATION:|OLD_CODE:|$)",
                                   raw, re.DOTALL | re.IGNORECASE)
        rollback_m    = re.search(r"ROLLBACK:\s*(.+?)(?=CONFIDENCE:|$)",
                                   raw, re.DOTALL | re.IGNORECASE)
        deps_m        = re.search(r"DEPENDENCIES:\s*(.+?)(?=ROLLBACK:|CONFIDENCE:|$)",
                                   raw, re.DOTALL | re.IGNORECASE)
        confidence_m  = re.search(r"CONFIDENCE:\s*([\d.]+)", raw)

        old_code    = extract_block("OLD_CODE")
        new_code    = extract_block("NEW_CODE")
        explanation = explanation_m.group(1).strip()[:200] if explanation_m else ""
        confidence  = float(confidence_m.group(1)) if confidence_m else 0.7

        if not new_code:
            # Try extracting any code block as fallback
            any_code = re.search(r"```python\s*(.*?)```", raw, re.DOTALL)
            if any_code:
                new_code = any_code.group(1).strip()
            else:
                return self._error("Model did not produce any code — try rephrasing your request")

        analysis  = analysis_m.group(1).strip()[:300]  if analysis_m  else ""
        rollback  = rollback_m.group(1).strip()[:200]  if rollback_m  else "Restore from backup"
        deps      = deps_m.group(1).strip()            if deps_m      else "none"

        return {
            "ok":          True,
            "old_code":    old_code,
            "new_code":    new_code,
            "explanation": explanation,
            "analysis":    analysis,
            "rollback":    rollback,
            "dependencies": deps,
            "file":        file,
            "section":     section,
            "confidence":  min(confidence, 1.0),
            "error":       "",
            "imports_used": [],
            "warning":     "",
        }

    def _check_syntax(self, code: str) -> tuple[bool, str]:
        """Validate Python syntax without executing."""
        try:
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            return False, f"Line {e.lineno}: {e.msg}"

    def _self_correct(self, result: dict, error: str, imports: list[str]) -> dict:
        """Ask the model to fix its own syntax error."""
        fix_prompt = (
            f"This Python code has a syntax error: {error}\n\n"
            f"Fix ONLY the syntax error. Return ONLY the corrected code, "
            f"no explanation, no markdown:\n\n{result['new_code']}"
        )
        fixed = self._call_model(fix_prompt)
        if fixed:
            # Strip any markdown
            fixed = re.sub(r"```python|```", "", fixed).strip()
            ok, err = self._check_syntax(fixed)
            if ok:
                result["new_code"] = fixed
                result["explanation"] += " [self-corrected syntax]"
                return result
        result["ok"]    = False
        result["error"] = f"Syntax error could not be corrected: {error}"
        return result

    def _check_hallucinated_imports(self, code: str, actual_imports: list[str]) -> list[str]:
        """Find imports in generated code not present in the original file."""
        generated_imports = []
        for line in code.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                generated_imports.append(stripped)

        actual_set = set(actual_imports)
        return [i for i in generated_imports if i not in actual_set]

    @staticmethod
    def _error(msg: str) -> dict:
        return {
            "ok": False, "old_code": "", "new_code": "",
            "explanation": "", "file": "", "section": "",
            "confidence": 0.0, "error": msg,
            "imports_used": [], "warning": "",
        }


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 3: SANDBOX TESTER                                              ║
# ║  Runs generated code in isolation before proposing it                   ║
# ╚══════════════════════════════════════════════════════════════════════════╝

class SandboxTester:
    """
    Tests generated code in a subprocess before it touches real files.
    Tests: syntax validity, import resolution, basic execution.
    Does NOT test UI code (PyQt6 requires a display) — marks those as untestable.
    """

    UNTESTABLE_PATTERNS = [
        r"QApplication|QWidget|QMainWindow|QPushButton",
        r"setStyleSheet|addWidget|QTimer",
    ]

    @classmethod
    def test(cls, code: str, context_code: str = "") -> dict:
        """
        Run code in sandbox. Returns test result dict.

        context_code: minimal code needed to make the snippet run
                      (e.g., class definition if testing a method)
        """
        # Check if testable
        for pattern in cls.UNTESTABLE_PATTERNS:
            if re.search(pattern, code):
                return {
                    "ok":       True,
                    "testable": False,
                    "reason":   "UI code — requires display, cannot sandbox test",
                    "output":   "",
                    "error":    "",
                }

        # Syntax check first
        try:
            ast.parse(code)
        except SyntaxError as e:
            return {
                "ok": False, "testable": True,
                "reason": f"Syntax error: {e.msg} (line {e.lineno})",
                "output": "", "error": str(e),
            }

        # Write to temp file and run
        full_code = f"{context_code}\n\n{code}\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(full_code)
            tmp_path = tmp.name

        try:
            result = subprocess.run(
                [sys.executable, tmp_path],
                capture_output=True, text=True, timeout=SANDBOX_TIMEOUT,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            ok = result.returncode == 0
            return {
                "ok":       ok,
                "testable": True,
                "reason":   "Ran successfully" if ok else "Runtime error",
                "output":   result.stdout[:500],
                "error":    result.stderr[:300] if not ok else "",
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False, "testable": True,
                "reason": "Timed out (>10s)",
                "output": "", "error": "timeout",
            }
        except Exception as exc:
            return {
                "ok": False, "testable": True,
                "reason": str(exc), "output": "", "error": str(exc),
            }
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 4: OUTCOME LEARNER                                             ║
# ║  Records Dan's approvals/rejections, adapts future generation           ║
# ╚══════════════════════════════════════════════════════════════════════════╝

class OutcomeLearner:
    """
    Learns from what Dan approves and rejects.
    Builds a history of successful patterns and failed ones.
    Feeds that history into future generation prompts.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._outcomes = self._load()

    def _load(self) -> list[dict]:
        if OUTCOMES_FILE.exists():
            try:
                return json.loads(OUTCOMES_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _save(self):
        try:
            OUTCOMES_FILE.parent.mkdir(parents=True, exist_ok=True)
            OUTCOMES_FILE.write_text(
                json.dumps(self._outcomes[-200:], indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception:
            pass

    def record(
        self,
        request:     str,
        intent_type: str,
        approved:    bool,
        code:        str = "",
        reason:      str = "",
    ):
        """Record Dan's decision on a proposed change."""
        with self._lock:
            self._outcomes.append({
                "ts":          datetime.utcnow().isoformat(),
                "request":     request[:200],
                "intent_type": intent_type,
                "approved":    approved,
                "code_hash":   hashlib.md5(code.encode()).hexdigest()[:8] if code else "",
                "reason":      reason[:200],
            })
            self._save()

    def get_context_for_prompt(self, intent_type: str) -> str:
        """
        Build a learning context string for the generation prompt.
        Shows recent approved patterns for this intent type.
        """
        with self._lock:
            relevant = [
                o for o in self._outcomes[-50:]
                if o.get("intent_type") == intent_type
            ]
            if not relevant:
                return ""

            approved_count  = sum(1 for o in relevant if o.get("approved"))
            rejected_count  = len(relevant) - approved_count
            approval_rate   = approved_count / max(len(relevant), 1)

            last_approved = [
                o["request"] for o in relevant if o.get("approved")
            ][-3:]
            last_rejected = [
                o["request"] for o in relevant if not o.get("approved")
            ][-2:]

            lines = [
                f"LEARNING CONTEXT ({intent_type}):",
                f"  Approval rate: {approval_rate:.0%} ({approved_count}/{len(relevant)})",
            ]
            if last_approved:
                lines.append("  Previously approved requests (follow these patterns):")
                for r in last_approved:
                    lines.append(f"    ✓ {r[:80]}")
            if last_rejected:
                lines.append("  Previously rejected (avoid these patterns):")
                for r in last_rejected:
                    lines.append(f"    ✗ {r[:80]}")
            return "\n".join(lines)

    def stats(self) -> dict:
        with self._lock:
            if not self._outcomes:
                return {"total": 0, "approved": 0, "rejected": 0, "rate": 0.0}
            approved = sum(1 for o in self._outcomes if o.get("approved"))
            return {
                "total":    len(self._outcomes),
                "approved": approved,
                "rejected": len(self._outcomes) - approved,
                "rate":     round(approved / len(self._outcomes), 2),
            }


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 5: CONVERSATIONAL PROGRAMMING ENGINE (main interface)          ║
# ╚══════════════════════════════════════════════════════════════════════════╝

class ConvProgrammingEngine:
    """
    The main interface. Dan speaks, WON builds.

    Flow:
        1. Parse Dan's intent
        2. Ask for clarification if ambiguous
        3. Read target file (grounded)
        4. Generate code change
        5. Sandbox test
        6. Present to Dan with plain-English explanation
        7. Apply if approved, record outcome either way
    """

    def __init__(self):
        self.parser    = IntentParser()
        self.generator = GroundedCodeGenerator()
        self.tester    = SandboxTester()
        self.learner   = OutcomeLearner()
        self._pending: dict | None = None   # pending proposal waiting for Dan's decision

    def process(
        self,
        request:    str,
        profile:    dict | None = None,
        error_text: str = "",
    ) -> dict:
        """
        Process Dan's conversational programming request.
        error_text: paste a runtime error here and WON will fix it.

        Returns:
            {
                type:          "clarification" | "proposal" | "error" | "info"
                message:       str   — what to show Dan
                proposal:      dict  — code proposal (if type=="proposal")
                clarification: str   — question for Dan (if type=="clarification")
            }
        """
        # 0. Runtime error mode — bypass intent parsing
        if error_text:
            intent = {
                "type": "logic_change", "confidence": 0.9,
                "target_file": "app.py", "target_section": "",
                "constraints": [], "ambiguous": False, "clarification": "",
                "raw_request": request,
            }
            request = (
                f"Fix this runtime error:\n{error_text[:500]}\n\n"
                f"Context: {request}"
            )

        # 1. Parse intent
        intent = self.parser.parse(request)

        # 2. Handle ambiguity
        if intent["ambiguous"]:
            return {
                "type":          "clarification",
                "message":       f"WON: {intent['clarification']}",
                "proposal":      None,
                "clarification": intent["clarification"],
            }

        # 3. Get learning context
        learning_ctx = self.learner.get_context_for_prompt(intent["type"])
        if learning_ctx and profile:
            profile = {**profile, "_learning": learning_ctx}

        # 4. Generate code
        result = self.generator.generate(intent, request, profile, error_text=error_text)
        if not result["ok"]:
            return {
                "type":    "error",
                "message": f"WON: I couldn't generate that — {result['error']}",
                "proposal": None,
                "clarification": "",
            }

        # 5. Sandbox test
        test_result = self.tester.test(result["new_code"])

        # 6. Build proposal
        proposal = {
            "request":     request,
            "intent":      intent,
            "code":        result,
            "test":        test_result,
            "timestamp":   datetime.now().isoformat(),
        }
        self._pending = proposal

        # Build message for Dan
        test_badge = (
            "✓ Tested"     if test_result["ok"] and test_result["testable"] else
            "⚠ Untestable" if not test_result["testable"] else
            "✗ Test failed"
        )
        confidence_badge = f"{result['confidence']:.0%} confidence"
        warning = f"\n⚠ {result['warning']}" if result.get("warning") else ""

        message = (
            f"WON: {result['explanation']}\n\n"
            f"File: `{result['file']}` → `{result['section'] or 'module level'}`\n"
            f"{test_badge} · {confidence_badge}{warning}\n\n"
            f"Apply this change?"
        )

        return {
            "type":          "proposal",
            "message":       message,
            "proposal":      proposal,
            "clarification": "",
        }

    def approve(self, apply_fn=None) -> dict:
        """Dan approved the pending proposal. Apply it."""
        if not self._pending:
            return {"ok": False, "message": "No pending proposal"}

        p    = self._pending
        code = p["code"]

        # ── Pipeline Integration: STRATUM → CodeForge → patch_engine → helixchain → simcore ──
        ok = False
        try:
            # Use patch_engine for application + helixchain sync + simcore logging
            patch_data = {
                "file": code.get("file", "app.py"),
                "diff": f"<<< OLD_CODE\n{code.get('old_code', '')}\n>>> NEW_CODE\n{code.get('new_code', '')}\n<<< END",
                "intent": p["intent"],
                "risk": code.get("confidence", 0.5), # maps confidence to risk (inverse)
                "metadata": {"id": uuid.uuid4().hex[:8], "request": p["request"]}
            }
            
            # Map confidence (0-1) to risk (0-1)
            confidence = code.get("confidence", 0.5)
            risk = 1.0 - confidence
            
            success = patch_engine.apply_patch(patch_data["file"], patch_data["diff"])
            if success:
                patch_engine.sync_helixchain(patch_data["file"])
                # Create a Patch object for logging
                patch_obj = patch_engine.Patch(
                    file=patch_data["file"],
                    intent=patch_data["intent"],
                    mode="patch",
                    risk=risk,
                    status="applied",
                    diff=patch_data["diff"],
                    metadata=patch_data["metadata"]
                )
                patch_engine.log_patch(patch_data["file"], p["intent"], patch_obj, "applied")
                ok = True
        except Exception as exc:
            _log.error(f"Pipeline error in CodeForge: {exc}")
            # Fallback to legacy apply if pipeline fails
            ok = self._apply_to_file(code)

        # Record outcome in learner
        self.learner.record(
            request     = p["request"],
            intent_type = p["intent"]["type"],
            approved    = True,
            code        = code.get("new_code", ""),
        )
        self._pending = None

        return {
            "ok":      ok,
            "message": "✓ Change applied via Pipeline — SimCore/HelixChain updated." if ok else "✗ Could not apply change.",
        }

    def reject(self, reason: str = "") -> dict:
        """Dan rejected the pending proposal."""
        if not self._pending:
            return {"ok": False, "message": "No pending proposal"}

        p = self._pending
        self.learner.record(
            request     = p["request"],
            intent_type = p["intent"]["type"],
            approved    = False,
            code        = p["code"].get("new_code", ""),
            reason      = reason,
        )
        self._pending = None
        return {"ok": True, "message": "Noted. What would you like instead?"}

    def _apply_to_file(self, code_result: dict) -> bool:
        """
        Apply code change to target file.
        Strategy (in order):
          1. Exact OLD_CODE match → simple replace
          2. AST function/class match → replace whole node
          3. No match → append to end of file
        Always backs up before writing.
        """
        target   = _HERE / code_result.get("file", "app.py")
        old_code = code_result.get("old_code", "").strip()
        new_code = code_result.get("new_code", "").strip()

        if not target.exists():
            return False

        try:
            source = target.read_text(encoding="utf-8")

            # Strategy 1: exact match
            if old_code and old_code in source:
                new_source = source.replace(old_code, new_code, 1)

            # Strategy 2: AST function/class replacement
            elif old_code and self._ast_replace(source, old_code, new_code) is not None:
                new_source = self._ast_replace(source, old_code, new_code)

            # Strategy 3: fuzzy match — find closest block
            elif old_code:
                new_source = self._fuzzy_replace(source, old_code, new_code)
                if new_source is None:
                    # Last resort: append
                    new_source = source.rstrip() + "\n\n# CodeForge addition:\n" + new_code + "\n"

            else:
                # No old_code — append
                new_source = source.rstrip() + "\n\n# CodeForge addition:\n" + new_code + "\n"

            # Syntax check
            ast.parse(new_source)

            # Backup
            backup_dir = Path.home() / "Documents" / "AI_Monitor" / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = backup_dir / f"{target.stem}_{ts}.py"
            backup.write_text(source, encoding="utf-8")

            target.write_text(new_source, encoding="utf-8")
            return True

        except Exception as exc:
            _log.debug(f"[CodeForge] Apply failed: {exc}")
            return False

    def _ast_replace(self, source: str, old_code: str, new_code: str):
        """
        Find a function or class by extracting its name from old_code,
        then replace the entire node in the source AST.
        """
        import re
        name_m = re.search(r"def (\w+)|class (\w+)", old_code)
        if not name_m:
            return None
        name = name_m.group(1) or name_m.group(2)

        lines = source.splitlines(keepends=True)
        start = None
        end   = None
        indent = ""

        for i, line in enumerate(lines):
            if re.match(rf"(\s*)(def {name}|class {name})", line):
                m = re.match(r"(\s*)", line)
                indent = m.group(1) if m else ""
                start  = i
                continue
            if start is not None and end is None:
                # Find end: next def/class at same or lower indent level
                if line.strip() and not line.startswith(indent + " ") and line != "\n":
                    if re.match(rf"^{re.escape(indent)}(def |class |\S)", line):
                        end = i
                        break

        if start is None:
            return None
        if end is None:
            end = len(lines)

        result_lines = lines[:start] + [new_code + "\n"] + lines[end:]
        return "".join(result_lines)

    def _fuzzy_replace(self, source: str, old_code: str, new_code: str):
        """
        Find the closest matching block using difflib and replace it.
        Returns None if no good match found.
        """
        import difflib
        old_lines = old_code.splitlines()
        src_lines = source.splitlines()

        best_ratio = 0.0
        best_start = -1
        window     = len(old_lines)

        for i in range(len(src_lines) - window + 1):
            block = src_lines[i:i + window]
            ratio = difflib.SequenceMatcher(None, old_lines, block).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_start = i

        if best_ratio < 0.6:
            return None

        result = src_lines[:best_start] + new_code.splitlines() + src_lines[best_start + window:]
        return "\n".join(result)

    def stats(self) -> dict:
        return {
            "outcomes": self.learner.stats(),
            "pending":  self._pending is not None,
        }


# ── Singleton ──────────────────────────────────────────────────────────────────
_engine: ConvProgrammingEngine | None = None

def get_engine() -> ConvProgrammingEngine:
    global _engine
    if _engine is None:
        _engine = ConvProgrammingEngine()
    return _engine
