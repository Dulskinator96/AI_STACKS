"""
implementer_loop.py — Self-healing detector + patch orchestrator.

The Implementation agent's "ability to patch / add fixes as detected" wired
end-to-end. Pipeline:

    Detector  →  Refiner  →  Optimizer  →  Integrator
       │            │            │              │
       │            │            │              └─ patch_engine.run_patch_pipeline
       │            │            │                 (CodeForge OLD/NEW block, audit-gated)
       │            │            └─ heuristics + risk gate (>=0.90 manual)
       │            └─ AI_STACK L4 ReasoningCoordinator + OllamaCapability
       │              (governed inference through ExecutionOrchestrator)
       └─ ast + py_compile + import scan over codebase

Pipeline position: invoked by the Pyramid ImplementationAgent (or stand-alone
diagnostic tool). Never patches without explicit `apply=True` and
risk_threshold satisfied. DRY-RUN is the default.

Honors CLAUDE.md doctrine: SOLID (Detector/Refiner/Optimizer/Integrator each
have one responsibility), KISS (ast + py_compile + heuristics, no ML),
config.py-aware (uses Ollama via the AI_STACK governed gate), expert framework
grounding (system_prompt cites Knuth/Martin/Torvalds for the
ImplementationAgent role).

NOT a replacement for the existing proposal_engine pipeline. This module
COMPLEMENTS it: provides the detection front-end that the legacy pipeline
lacked. For high-risk/structural changes, callers should still go through
intent_engine -> code_correlator -> proposal_engine -> executor.
"""
from __future__ import annotations

import ast
import json
import logging
import py_compile
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional


_log = logging.getLogger(__name__)


# ── Telemetry instrumentation (LAW_3 receipts + LAW_10 calibration) ─────────

class TelemetryRecorder:
    """Routes every Implementer operation through AI_STACK Constitution.

    Best-effort: if substrate unreachable, no-ops. Never raises.

    Emits:
      * LAW_3 receipts (subsystem='intelligence.implementer', action=<op>)
      * LAW_10 calibration signals (metrics: scan_latency_ms, scan_issue_count,
        refine_latency_ms, refine_outcome, integrate_outcome,
        deterministic_hit, llm_hit, patch_applied)
    """

    def __init__(self):
        self._constitution = None
        self._enabled = True

    def _con(self):
        if self._constitution is None:
            try:
                import sys
                substrate = Path(__file__).resolve().parent.parent
                if str(substrate) not in sys.path:
                    sys.path.append(str(substrate))
                from kernel.constitution import get_constitution
                self._constitution = get_constitution()
            except Exception as e:
                _log.debug("TelemetryRecorder substrate unavailable: %s", e)
                self._enabled = False
                self._constitution = None
        return self._constitution

    def record_op(self, op: str, outcome: str, evidence: dict,
                   lineage: Optional[list] = None) -> None:
        if not self._enabled: return
        con = self._con()
        if con is None: return
        try:
            con.record_receipt(
                "intelligence.implementer", "ImplementerLoop", op, outcome,
                evidence or {}, lineage=lineage or [],
            )
        except Exception as e:
            _log.warning(f'caught exception: {e}')

    def signal(self, metric: str, value, baseline_ref: str = "implementer_baseline") -> None:
        if not self._enabled: return
        con = self._con()
        if con is None: return
        try:
            con.register_calibration_signal(
                "intelligence.implementer", metric, float(value),
                baseline_ref=baseline_ref,
            )
        except Exception as e:
            _log.warning(f'caught exception: {e}')


_global_telemetry: Optional["TelemetryRecorder"] = None

def get_telemetry() -> "TelemetryRecorder":
    global _global_telemetry
    if _global_telemetry is None:
        _global_telemetry = TelemetryRecorder()
    return _global_telemetry


# ── Configuration constants (will move to config.py in a follow-up) ──────────
DEFAULT_RISK_AUTO_APPLY        = 0.30   # below this -> auto-apply allowed if apply=True
DEFAULT_RISK_MANUAL_THRESHOLD  = 0.90   # at/above this -> ALWAYS manual (patch_engine gate)
DEFAULT_SCAN_MAX_FILE_BYTES    = 250_000   # skip huge files in detector pass
DEFAULT_SKIP_DIRS = frozenset({
    "__pycache__", ".git", "node_modules", ".venv", "venv", "build",
    "dist", "releases", ".pytest_cache", ".mypy_cache",
})

# ── Issue taxonomy ────────────────────────────────────────────────────────────
ISSUE_SYNTAX_ERROR        = "syntax_error"
ISSUE_IMPORT_ERROR        = "import_error"
ISSUE_BARE_EXCEPT         = "bare_except_swallow"     # except: / except Exception: pass
ISSUE_PRINT_STATEMENT     = "print_statement"          # CLAUDE.md doctrine: use _log
ISSUE_NULL_BYTE_FILE      = "null_byte_corruption"     # the bug that prompted this work
ISSUE_TODO_MARKER         = "todo_marker"
ISSUE_LARGE_MODULE        = "large_module"             # > 1000 LOC heuristic for refactor

VALID_ISSUE_KINDS = frozenset({
    ISSUE_SYNTAX_ERROR, ISSUE_IMPORT_ERROR, ISSUE_BARE_EXCEPT,
    ISSUE_PRINT_STATEMENT, ISSUE_NULL_BYTE_FILE, ISSUE_TODO_MARKER,
    ISSUE_LARGE_MODULE,
})

SEVERITY_CRITICAL  = "CRITICAL"   # file unrunnable
SEVERITY_HIGH      = "HIGH"       # silent failure / hidden bug surface
SEVERITY_MEDIUM    = "MEDIUM"     # doctrine violation
SEVERITY_LOW       = "LOW"        # advisory


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class IssueReport:
    issue_id:        str            # uuid-like; deterministic from (file, line, kind)
    file:            str
    line:            int
    kind:            str            # VALID_ISSUE_KINDS
    severity:        str
    evidence:        str            # short snippet / error message
    suggested_hint:  str            # human-readable suggestion (not a patch)
    risk_estimate:   float          # 0.0-1.0; CONSERVATIVE bias toward 0.9+ for anything ambiguous

    def to_dict(self) -> dict: return asdict(self)


@dataclass(frozen=True)
class ImplementerResult:
    timestamp:       str
    total_files:     int
    files_scanned:   int
    files_skipped:   int
    issues:          tuple         # tuple of IssueReport
    by_kind:         dict
    by_severity:     dict
    dry_run:         bool
    apply_attempts:  int           # 0 when dry_run=True
    apply_succeeded: int
    apply_blocked:   int           # blocked by risk threshold

    def to_dict(self) -> dict:
        d = asdict(self)
        d["issues"] = [i.to_dict() if hasattr(i, "to_dict") else dict(i)
                        for i in self.issues]
        return d


# ── Detector ──────────────────────────────────────────────────────────────────

class Detector:
    """Pure-Python scanner. No LLM. Deterministic over file content."""

    def __init__(self,
                  root: Path,
                  skip_dirs: Iterable[str] = DEFAULT_SKIP_DIRS,
                  max_file_bytes: int = DEFAULT_SCAN_MAX_FILE_BYTES):
        self.root = Path(root).resolve()
        self.skip_dirs = frozenset(skip_dirs)
        self.max_file_bytes = max_file_bytes
        self._stats = {"scanned": 0, "skipped": 0, "total": 0}

    def stats(self) -> dict: return dict(self._stats)

    def iter_py_files(self) -> Iterable[Path]:
        for p in self.root.rglob("*.py"):
            try:
                rel = p.relative_to(self.root)
            except ValueError:
                continue
            parts = set(rel.parts[:-1])
            if parts & self.skip_dirs:
                continue
            yield p

    def scan(self) -> list[IssueReport]:
        import time as _t
        _t0 = _t.time()
        issues: list[IssueReport] = []
        for path in self.iter_py_files():
            self._stats["total"] += 1
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > self.max_file_bytes:
                self._stats["skipped"] += 1
                continue

            # NUL-byte corruption check -- the very bug that motivated this build
            try:
                head = path.read_bytes()[:64]
            except OSError:
                self._stats["skipped"] += 1
                continue
            if size > 0 and head and all(b == 0 for b in head):
                self._stats["skipped"] += 1
                issues.append(self._mk_issue(
                    path, 1, ISSUE_NULL_BYTE_FILE, SEVERITY_CRITICAL,
                    evidence=f"file is {size} bytes of NUL (0x00)",
                    suggested_hint=("Restore from a known-good source "
                                     "(git checkout, or copy from sibling tree). "
                                     "Auto-patch CANNOT recover NUL-byte content."),
                    risk_estimate=1.0,   # ALWAYS manual; never auto-fix
                ))
                continue

            try:
                src = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                self._stats["skipped"] += 1
                continue
            self._stats["scanned"] += 1

            # Syntax check via py_compile
            try:
                py_compile.compile(str(path), doraise=True)
            except py_compile.PyCompileError as e:
                line_no = self._extract_line(str(e)) or 1
                issues.append(self._mk_issue(
                    path, line_no, ISSUE_SYNTAX_ERROR, SEVERITY_CRITICAL,
                    evidence=str(e).splitlines()[-1][:200],
                    suggested_hint="Fix the SyntaxError per Python parser feedback.",
                    risk_estimate=0.95,  # patching syntax is structural -- manual
                ))
                # Continue to other checks on the file as best-effort

            # AST-based scans (skip if syntax already broken)
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue   # already reported above

            issues.extend(self._scan_ast(path, tree, src))

            # Heuristic: large module
            line_count = src.count("\n") + 1
            if line_count > 1000:
                issues.append(self._mk_issue(
                    path, 1, ISSUE_LARGE_MODULE, SEVERITY_LOW,
                    evidence=f"{line_count} lines",
                    suggested_hint=("Consider splitting per CLAUDE.md SOLID "
                                     "principle (one class, one reason to change)."),
                    risk_estimate=0.95,   # refactor = manual
                ))

            # TODO markers
            for i, line in enumerate(src.splitlines(), 1):
                if "TODO" in line or "FIXME" in line or "XXX" in line:
                    issues.append(self._mk_issue(
                        path, i, ISSUE_TODO_MARKER, SEVERITY_LOW,
                        evidence=line.strip()[:160],
                        suggested_hint="Triage TODO/FIXME marker.",
                        risk_estimate=0.95,
                    ))
                    if sum(1 for x in issues if x.kind == ISSUE_TODO_MARKER) > 50:
                        break  # cap noise

        # ── Telemetry: scan completed ──
        elapsed_ms = (_t.time() - _t0) * 1000
        try:
            tel = get_telemetry()
            tel.record_op(
                "scan", "ok",
                {"issue_count": len(issues),
                 "scanned": self._stats["scanned"],
                 "skipped": self._stats["skipped"],
                 "elapsed_ms": round(elapsed_ms, 2)},
            )
            tel.signal("scan_latency_ms", elapsed_ms)
            tel.signal("scan_issue_count", float(len(issues)))
        except Exception as e:
            _log.warning(f'caught exception: {e}')
        return issues

    def _scan_ast(self, path: Path, tree: ast.AST, src: str) -> list[IssueReport]:
        out: list[IssueReport] = []
        for node in ast.walk(tree):
            # Bare except / except Exception with `pass` body
            if isinstance(node, ast.ExceptHandler):
                handler_type = node.type
                handler_is_bare = handler_type is None
                handler_is_broad = (isinstance(handler_type, ast.Name)
                                     and handler_type.id == "Exception")
                if handler_is_bare or handler_is_broad:
                    body = node.body
                    only_pass = (len(body) == 1
                                  and isinstance(body[0], ast.Pass))
                    if only_pass:
                        out.append(self._mk_issue(
                            path, node.lineno, ISSUE_BARE_EXCEPT,
                            SEVERITY_HIGH,
                            evidence=("except: pass" if handler_is_bare
                                       else "except Exception: pass"),
                            suggested_hint=("Replace with explicit logging or "
                                             "narrower exception; CLAUDE.md doctrine: "
                                             "_log.warning() recoverable failures."),
                            risk_estimate=0.40,   # patchable with care
                        ))
            # print() calls (doctrine: use logging)
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "print":
                    out.append(self._mk_issue(
                        path, node.lineno, ISSUE_PRINT_STATEMENT,
                        SEVERITY_MEDIUM,
                        evidence="print(...) call",
                        suggested_hint=("Replace with _log.debug()/info() per "
                                         "CLAUDE.md error-handling doctrine."),
                        risk_estimate=0.25,   # low risk, mechanical
                    ))
        return out

    def _mk_issue(self, path: Path, line: int, kind: str, severity: str,
                   evidence: str, suggested_hint: str,
                   risk_estimate: float) -> IssueReport:
        try:
            rel = str(path.relative_to(self.root))
        except ValueError:
            rel = str(path)
        # Deterministic id: hash(file:line:kind)
        import hashlib
        digest = hashlib.sha256(
            f"{rel}:{line}:{kind}".encode("utf-8")
        ).hexdigest()[:16]
        return IssueReport(
            issue_id=digest,
            file=rel,
            line=int(line),
            kind=kind,
            severity=severity,
            evidence=str(evidence)[:240],
            suggested_hint=str(suggested_hint)[:240],
            risk_estimate=float(max(0.0, min(1.0, risk_estimate))),
        )

    def _extract_line(self, err_text: str) -> Optional[int]:
        m = re.search(r"line (\d+)", err_text)
        return int(m.group(1)) if m else None


# ── Refiner: turns IssueReport -> structured "intent" for patch_engine ────────

def _deterministic_fix(issue: "IssueReport",
                        file_content: str) -> Optional[str]:
    """Template-based exact-quote CodeForge generator for mechanical issues.

    Returns a valid CodeForge block when the issue.kind has a known safe
    template AND the source line matches the template's preconditions.
    Returns None when no template applies -- caller falls back to L4 inference.

    NO LLM INVOLVED. Pure-Python string ops. The Knuth path: precise + fast.
    """
    if not isinstance(file_content, str) or not file_content:
        return None
    lines = file_content.splitlines()
    if not (1 <= issue.line <= len(lines)):
        return None
    line_text = lines[issue.line - 1]
    line_rtrim = line_text.rstrip()

    # File-level precondition: the file must really *define* `_log` as a
    # module-level assignment AND import logging. Substring matching against
    # the raw source produced false positives when the literal text appeared
    # inside a string (e.g., this very file's docstring). So we use ast.
    def _module_defines_log(src: str) -> bool:
        try:
            tree = ast.parse(src)
        except Exception:
            return False
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "_log":
                        return True
        return False

    def _module_imports_logging(src: str) -> bool:
        try:
            tree = ast.parse(src)
        except Exception:
            return False
        for node in tree.body:
            if isinstance(node, ast.Import):
                if any(n.name == "logging" for n in node.names):
                    return True
            if isinstance(node, ast.ImportFrom) and node.module == "logging":
                return True
        return False

    has_log_logger = _module_defines_log(file_content)
    has_logging_import = _module_imports_logging(file_content)

    # ── print_statement ────────────────────────────────────────────────────
    if issue.kind == ISSUE_PRINT_STATEMENT:
        if not (has_log_logger and has_logging_import):
            return None
        # Anchor: line starts with `print(` after stripping leading whitespace
        stripped = line_text.lstrip()
        if not stripped.startswith("print("):
            return None
        indent = line_text[:len(line_text) - len(stripped)]
        # Heuristic: file=sys.stderr -> warning. otherwise debug.
        is_stderr = ("file=sys.stderr" in stripped
                     or "file=sys.stdout" in stripped)
        # Strip the `file=sys.stderr` / `file=sys.stdout` keyword arg
        body = stripped
        # Naive: drop the print( ... ) wrapper and pull the inner expression.
        # We only attempt if there is exactly one top-level call.
        if not body.endswith(")"):
            return None
        # Remove "print(" and trailing ")"
        inner = body[len("print("):-1].strip()
        # Drop the file=... kwarg if present (Knuth precision: split top-level
        # commas only -- but we accept simple last-kwarg removal)
        for kw in (", file=sys.stderr", ", file=sys.stdout",
                    " ,file=sys.stderr", " ,file=sys.stdout"):
            if kw in inner:
                inner = inner.replace(kw, "")
        if not inner:
            return None
        new_call = (f"_log.warning({inner})"
                    if is_stderr
                    else f"_log.debug({inner})")
        new_line = f"{indent}{new_call}"
        return (f"<<< OLD_CODE\n{line_text}\n>>> NEW_CODE\n{new_line}\n<<< END")

    # ── bare_except_swallow ───────────────────────────────────────────────
    if issue.kind == ISSUE_BARE_EXCEPT:
        if not (has_log_logger and has_logging_import):
            return None
        # The detector reports the `except` line; the swallow is on the
        # immediately-following indented `pass`. We anchor OLD with the
        # try block prelude + except + pass to make the match file-unique.
        if issue.line >= len(lines):
            return None
        next_line = lines[issue.line]   # zero-based: line after except:
        if next_line.strip() != "pass":
            return None

        # Walk back to find the matching `try:` at the same column as `except`.
        # Captures the try-block body in between for uniqueness anchoring.
        except_indent_n = len(line_text) - len(line_text.lstrip())
        try_idx = None
        for back in range(issue.line - 2, max(-1, issue.line - 30), -1):
            cand = lines[back]
            if not cand.strip():
                continue
            cand_indent_n = len(cand) - len(cand.lstrip())
            # Same column AND ends with bare `try:`
            if cand_indent_n == except_indent_n and cand.rstrip().endswith("try:"):
                try_idx = back
                break
            # If we hit a line at a STRICTLY SHALLOWER indent before finding
            # try, we've left the block -- abort.
            if cand_indent_n < except_indent_n and cand.strip():
                break
        if try_idx is None:
            # No clean try anchor; fall back to 2-line OLD (less unique but
            # patch_engine will refuse if not file-unique -- safe failure).
            old = f"{line_text}\n{next_line}"
        else:
            # Capture from try line through pass line (inclusive)
            old = "\n".join(lines[try_idx:issue.line + 1])

        # Build NEW: same prelude, but rewrite the `pass` line as a log call.
        except_stripped = line_rtrim.strip()
        var = ("e" if " as e:" in except_stripped
               else ("exc" if " as exc:" in except_stripped else None))
        indent = next_line[:len(next_line) - len(next_line.lstrip())]
        if var:
            new_pass = f'{indent}_log.warning("swallowed exception: %s", {var})'
        else:
            new_pass = f'{indent}_log.warning("swallowed exception")'
        # NEW = OLD with the last line replaced
        old_lines = old.split("\n")
        new_lines = old_lines[:-1] + [new_pass]
        new = "\n".join(new_lines)
        return (f"<<< OLD_CODE\n{old}\n>>> NEW_CODE\n{new}\n<<< END")

    return None


class Refiner:
    """Converts a detector finding into a fix-intent.

    For mechanical issues (print_statement, bare_except_swallow) a deterministic
    template is tried first -- no LLM round-trip. Falls back to L4 Reasoning +
    OllamaCapability for novel cases.

    HC4.7 binding: failed inference -> result.status='unresolved', no fabrication.
    """

    EXPERT_PROMPT = (
        # CLAUDE.md ImplementationAgent expert grounding
        "You are the Implementation agent. Expert grounding: Donald Knuth "
        "(precision), Robert C. Martin (clean code), Linus Torvalds (show the "
        "code). Produce a minimal, surgical fix. Output ONLY a CodeForge "
        "block:\n"
        "<<< OLD_CODE\n<exact existing snippet>\n>>> NEW_CODE\n"
        "<replacement snippet>\n<<< END\n\n"
        "No prose, no explanation outside the block. If unsure, output:\n"
        "<<< OLD_CODE\n<<< UNRESOLVED >>>\n>>> NEW_CODE\n<<< UNRESOLVED >>>\n<<< END"
    )

    def __init__(self, root: Path):
        self.root = Path(root)
        self._reasoning = None
        self._knowledge = None

    def _resolve_reasoning(self):
        if self._reasoning is None:
            try:
                # AI_STACK substrate lives at the parent tree (ai-monitor -> AI_STACK)
                substrate_root = self.root.parent
                # IMPORTANT: append (not insert at 0) so ai-monitor's own
                # config.py / patch_engine / helixchain still resolve first.
                if str(substrate_root) not in sys.path:
                    sys.path.append(str(substrate_root))
                from intelligence.reasoning import get_reasoning_coordinator
                self._reasoning = get_reasoning_coordinator()
            except Exception as e:
                _log.warning("L4 ReasoningCoordinator unavailable: %s", e)
                self._reasoning = None
        return self._reasoning

    def build_prompt(self, issue: IssueReport, file_content: str) -> str:
        """Construct a focused fix-prompt with context window from the file."""
        lines = file_content.splitlines()
        ctx_start = max(0, issue.line - 3)
        ctx_end   = min(len(lines), issue.line + 3)
        snippet = "\n".join(
            f"{n:5d}{'>' if n == issue.line else ' '} {lines[n-1]}"
            for n in range(ctx_start + 1, ctx_end + 1)
            if 1 <= n <= len(lines)
        )
        target_line = (lines[issue.line - 1]
                        if 1 <= issue.line <= len(lines) else "")
        return (
            f"{self.EXPERT_PROMPT}\n"
            f"FILE: {issue.file}\n"
            f"ISSUE: {issue.kind} ({issue.severity})\n"
            f"EVIDENCE: {issue.evidence}\n"
            f"HINT: {issue.suggested_hint}\n"
            f"\n"
            f"TARGET LINE (copy this verbatim as your OLD_CODE):\n"
            f"{target_line}\n"
            f"\n"
            f"CONTEXT (the TARGET LINE is marked with `>`):\n{snippet}\n"
        )

    @staticmethod
    def _extract_codeforge_block(text: str) -> Optional[str]:
        """Pull the first complete `<<< OLD_CODE ... <<< END` block from text.

        Lenient: ignores prose before/after the block. Returns None if no
        complete block is present. Treats `<<< UNRESOLVED >>>` markers as
        honest non-fabrication.
        """
        if not text:
            return None
        if "<<< UNRESOLVED >>>" in text:
            return None
        start = text.find("<<< OLD_CODE")
        if start < 0:
            return None
        end = text.find("<<< END", start)
        if end < 0:
            return None
        block = text[start:end + len("<<< END")]
        # Sanity: must contain >>> NEW_CODE between OLD_CODE and END
        if ">>> NEW_CODE" not in block:
            return None
        return block

    def refine(self, issue: IssueReport,
                file_content: str,
                retries: int = 1,
                model: Optional[str] = None,
                allow_llm: bool = True) -> tuple[Optional[str], str]:
        """Return (codeforge_block_or_None, source).

        source = 'deterministic' (template match), 'substrate' (L4 inference),
        'unavailable' (L4 unreachable), or 'unresolved' (no patch produced).

        Per HC4.7 substrate doctrine: unresolved is honest, NOT fabricated.

        Tries the deterministic template first; falls back to L4 inference
        (with retries) only when no template matches.
        """
        import time as _t
        _t0 = _t.time()
        _tel = get_telemetry()

        # Step 1: deterministic template (NO LLM)
        det_block = _deterministic_fix(issue, file_content)
        if det_block is not None:
            elapsed_ms = (_t.time() - _t0) * 1000
            try:
                _tel.record_op("refine", "deterministic_hit",
                    {"issue_id": issue.issue_id, "kind": issue.kind,
                     "file": issue.file, "line": issue.line,
                     "elapsed_ms": round(elapsed_ms, 2)})
                _tel.signal("refine_latency_ms", elapsed_ms)
                _tel.signal("deterministic_hit", 1.0)
            except Exception: pass
            return det_block, "deterministic"

        if not allow_llm:
            try:
                _tel.record_op("refine", "deterministic_miss_no_llm",
                    {"issue_id": issue.issue_id, "kind": issue.kind})
                _tel.signal("deterministic_hit", 0.0)
            except Exception: pass
            return None, "unresolved"

        rc = self._resolve_reasoning()
        if rc is None:
            return None, "unavailable"
        prompt = self.build_prompt(issue, file_content)
        try:
            from intelligence.reasoning import H_COMPLETED
        except Exception as e:
            _log.warning("Refiner.refine substrate import failed: %s", e)
            return None, "unavailable"

        # Code-specialized default; override for ablation
        chosen_model = model or "deepseek-coder-v2:16b"
        attempts = max(1, int(retries) + 1)
        last_text = ""
        for attempt in range(attempts):
            try:
                h = rc.form_hypothesis(
                    question=prompt,
                    evidence_refs=[issue.issue_id, issue.file],
                    input_lineage={"input_id": issue.issue_id,
                                    "perception_id": "implementer_loop",
                                    "query_id": issue.kind},
                    initial_confidence=0.5,
                )
                res = rc.dispatch_inference(
                    h.hypothesis_id,
                    options={"temperature": 0.0, "num_predict": 384},
                    model=chosen_model,
                )
                if res.status != H_COMPLETED or not res.response_text:
                    last_text = res.response_text or ""
                    continue
                block = self._extract_codeforge_block(res.response_text)
                if block is not None:
                    elapsed_ms = (_t.time() - _t0) * 1000
                    try:
                        _tel.record_op("refine", "llm_hit",
                            {"issue_id": issue.issue_id, "kind": issue.kind,
                             "file": issue.file, "model": chosen_model,
                             "attempt": attempt + 1,
                             "elapsed_ms": round(elapsed_ms, 2)})
                        _tel.signal("refine_latency_ms", elapsed_ms)
                        _tel.signal("llm_hit", 1.0)
                    except Exception: pass
                    return block, "substrate"
                last_text = res.response_text
            except Exception as e:
                _log.warning("Refiner.refine attempt %d raised: %s", attempt, e)
                continue
        _log.debug("Refiner.refine exhausted retries for %s; last_text=%r",
                    issue.issue_id, (last_text[:200] if last_text else ""))
        elapsed_ms = (_t.time() - _t0) * 1000
        try:
            _tel.record_op("refine", "unresolved",
                {"issue_id": issue.issue_id, "kind": issue.kind,
                 "file": issue.file, "model": chosen_model,
                 "attempts": attempts, "elapsed_ms": round(elapsed_ms, 2)})
            _tel.signal("refine_latency_ms", elapsed_ms)
            _tel.signal("llm_hit", 0.0)
        except Exception: pass
        return None, "unresolved"


# ── Optimizer: gates by risk threshold ───────────────────────────────────────

class Optimizer:
    """Risk gate + de-duplication."""

    def __init__(self,
                  auto_apply_threshold: float = DEFAULT_RISK_AUTO_APPLY,
                  manual_threshold: float = DEFAULT_RISK_MANUAL_THRESHOLD):
        self.auto_apply_threshold = float(auto_apply_threshold)
        self.manual_threshold     = float(manual_threshold)

    def classify(self, issue: IssueReport) -> str:
        """Returns 'auto' | 'review' | 'manual'."""
        if issue.risk_estimate >= self.manual_threshold:
            return "manual"
        if issue.risk_estimate <= self.auto_apply_threshold:
            return "auto"
        return "review"

    def filter_for_apply(self,
                          issues: list[IssueReport]) -> list[IssueReport]:
        return [i for i in issues if self.classify(i) == "auto"]


# ── Integrator: calls patch_engine ────────────────────────────────────────────

class Integrator:
    """Routes refined CodeForge blocks through patch_engine.run_patch_pipeline.

    The patch_engine has its own audit gate, hash verification, and helixchain
    re-index. We DO NOT bypass any of that.
    """

    def __init__(self, root: Optional[Path] = None):
        self._patch_engine = None
        self.root = Path(root).resolve() if root else Path.cwd()

    def _resolve_patch_engine(self):
        if self._patch_engine is None:
            try:
                import patch_engine
                self._patch_engine = patch_engine
            except Exception as e:
                _log.warning("patch_engine import failed: %s", e)
                self._patch_engine = None
        return self._patch_engine

    def integrate(self, issue: IssueReport, codeforge_block: str,
                   ai_call_fn: Optional[Callable] = None) -> dict:
        pe = self._resolve_patch_engine()
        if pe is None:
            return {"status": "unavailable", "reason": "patch_engine_missing"}
        # Resolve path -- accept relative against self.root, OR absolute
        path = Path(issue.file)
        if not path.is_absolute():
            path = (self.root / path).resolve()
        if not path.exists():
            return {"status": "rejected", "reason": f"path_missing:{path}"}
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            return {"status": "failed", "reason": f"read_failed:{e}"}

        # patch_engine expects ai_call_fn(packet) -> raw_output. We bypass that
        # by supplying a closure that returns our already-refined block.
        def _const_caller(_packet):
            return codeforge_block
        caller = ai_call_fn or _const_caller

        import time as _t
        _t0 = _t.time()
        _tel = get_telemetry()
        try:
            result = pe.run_patch_pipeline(
                file_path=str(path),
                intent=issue.kind,
                context=issue.suggested_hint,
                file_content=content,
                ai_call_fn=caller,
            )
            elapsed_ms = (_t.time() - _t0) * 1000
            outcome = (result.get("status") or "unknown")
            try:
                _tel.record_op(
                    "integrate", outcome,
                    {"issue_id": getattr(issue, "issue_id", ""),
                     "kind": getattr(issue, "kind", ""),
                     "file": getattr(issue, "file", str(path)),
                     "line": getattr(issue, "line", -1),
                     "elapsed_ms": round(elapsed_ms, 2),
                     "reason": result.get("reason", "")},
                    lineage=[getattr(issue, "issue_id", "")],
                )
                _tel.signal("integrate_latency_ms", elapsed_ms)
                _tel.signal("patch_applied",
                            1.0 if outcome == "applied" else 0.0)
            except Exception: pass
            return result
        except Exception as e:
            _log.error("patch_engine.run_patch_pipeline raised: %s", e)
            try:
                _tel.record_op(
                    "integrate", "exception",
                    {"file": getattr(issue, "file", str(path)),
                     "error": str(e)[:200]},
                )
                _tel.signal("patch_applied", 0.0)
            except Exception: pass
            return {"status": "failed", "reason": f"pipeline_exception:{e}"}


# ── Top-level orchestrator ────────────────────────────────────────────────────

class ImplementerLoop:
    """The end-to-end pipeline. DRY-RUN by default."""

    def __init__(self,
                  root: Path,
                  auto_apply_threshold: float = DEFAULT_RISK_AUTO_APPLY,
                  manual_threshold: float = DEFAULT_RISK_MANUAL_THRESHOLD):
        self.root = Path(root).resolve()
        self.detector  = Detector(self.root)
        self.refiner   = Refiner(self.root)
        self.optimizer = Optimizer(auto_apply_threshold, manual_threshold)
        self.integrator = Integrator(root=self.root)

    def scan_once(self) -> list[IssueReport]:
        return self.detector.scan()

    def dry_run_report(self) -> ImplementerResult:
        return self.run(apply=False, refine=False)

    def run(self, apply: bool = False, refine: bool = False) -> ImplementerResult:
        t0 = time.time()
        issues = self.scan_once()
        stats = self.detector.stats()
        by_kind: dict[str, int] = {}
        by_sev: dict[str, int] = {}
        for i in issues:
            by_kind[i.kind] = by_kind.get(i.kind, 0) + 1
            by_sev[i.severity] = by_sev.get(i.severity, 0) + 1

        apply_attempts  = 0
        apply_succeeded = 0
        apply_blocked   = 0

        if apply:
            # ONLY auto-classified issues are eligible for application;
            # 'review' and 'manual' are surfaced but never auto-applied.
            for issue in self.optimizer.filter_for_apply(issues):
                apply_attempts += 1
                # Refine if requested; otherwise the integrator needs a block
                # from somewhere else. Strict mode -- skip if no block.
                if not refine:
                    apply_blocked += 1
                    continue
                # Read file for context
                fpath = self.root / issue.file
                try:
                    content = fpath.read_text(encoding="utf-8")
                except Exception:
                    apply_blocked += 1
                    continue
                block, src = self.refiner.refine(issue, content)
                if block is None:
                    apply_blocked += 1
                    continue
                res = self.integrator.integrate(issue, block)
                if res.get("status") == "applied":
                    apply_succeeded += 1
                else:
                    apply_blocked += 1

        result = ImplementerResult(
            timestamp=datetime.now().isoformat(),
            total_files=stats["total"],
            files_scanned=stats["scanned"],
            files_skipped=stats["skipped"],
            issues=tuple(issues),
            by_kind=by_kind,
            by_severity=by_sev,
            dry_run=(not apply),
            apply_attempts=apply_attempts,
            apply_succeeded=apply_succeeded,
            apply_blocked=apply_blocked,
        )
        elapsed = time.time() - t0
        _log.info(
            "ImplementerLoop run: %d issues across %d files in %.2fs "
            "(dry_run=%s applied=%d blocked=%d)",
            len(issues), stats["scanned"], elapsed,
            (not apply), apply_succeeded, apply_blocked,
        )
        return result


# ── Default singleton + convenience ──────────────────────────────────────────

_default_loop: Optional[ImplementerLoop] = None


def get_implementer(root: Optional[Path] = None) -> ImplementerLoop:
    global _default_loop
    if _default_loop is None:
        if root is None:
            root = Path(__file__).resolve().parent
        _default_loop = ImplementerLoop(root)
    return _default_loop


__all__ = [
    "ISSUE_SYNTAX_ERROR", "ISSUE_IMPORT_ERROR", "ISSUE_BARE_EXCEPT",
    "ISSUE_PRINT_STATEMENT", "ISSUE_NULL_BYTE_FILE", "ISSUE_TODO_MARKER",
    "ISSUE_LARGE_MODULE", "VALID_ISSUE_KINDS",
    "SEVERITY_CRITICAL", "SEVERITY_HIGH", "SEVERITY_MEDIUM", "SEVERITY_LOW",
    "IssueReport", "ImplementerResult",
    "Detector", "Refiner", "Optimizer", "Integrator", "ImplementerLoop",
    "get_implementer",
    "DEFAULT_RISK_AUTO_APPLY", "DEFAULT_RISK_MANUAL_THRESHOLD",
]
