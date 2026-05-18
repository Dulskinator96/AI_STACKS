"""
executor.py — Deterministic execution layer.

Takes a validated Proposal and applies it to the filesystem.
- Pre-flight: verifies all referenced files exist
- Snapshot: creates rollback copy before any mutation
- Apply: diff-based targeted edits (not full rewrites)
- Post-flight: syntax check on every modified Python file
- On any failure: automatic rollback, clean error report

Pipeline position: proposal_engine → [Executor] → filesystem
                                        ↕ rollback on failure
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from proposal_engine import ChangeItem, Proposal
import logging
_log = logging.getLogger(__name__)

# ── Rollback store ────────────────────────────────────────────────────────────

ROLLBACK_DIR = Path.home() / ".stratum" / "rollback"


def _snapshot_path(session_id: str) -> Path:
    ROLLBACK_DIR.mkdir(parents=True, exist_ok=True)
    return ROLLBACK_DIR / session_id


# ── Syntax check ─────────────────────────────────────────────────────────────

def _syntax_ok(path: str) -> tuple[bool, Optional[str]]:
    if not path.endswith(".py"):
        return True, None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
        ast.parse(source)
        return True, None
    except SyntaxError as e:
        return False, f"SyntaxError at line {e.lineno}: {e.msg}"
    except OSError as e:
        return False, str(e)


# ── Diff-based apply operations ───────────────────────────────────────────────

def _apply_replace(path: str, change: ChangeItem) -> str:
    """
    Replace lines [line_start..line_end] (1-indexed, inclusive) with content,
    OR replace the entire body of target_symbol if symbol-based.
    Returns diff description.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    if change.target_symbol:
        # Find symbol body via AST and replace it
        source = "".join(lines)
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            raise RuntimeError(f"Cannot parse {path} for symbol replacement: {e}")

        node = None
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if n.name == change.target_symbol:
                    node = n
                    break

        if node is None:
            raise RuntimeError(f"Symbol '{change.target_symbol}' not found in {path}")

        start = node.lineno - 1          # 0-indexed
        end   = getattr(node, "end_lineno", node.lineno)  # 1-indexed inclusive

        new_content = change.content or ""
        if not new_content.endswith("\n"):
            new_content += "\n"

        new_lines = lines[:start] + [new_content] + lines[end:]
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        return f"Replaced symbol '{change.target_symbol}' (L{node.lineno}-{end})"

    elif change.line_start and change.line_end:
        s = change.line_start - 1  # 0-indexed
        e = change.line_end        # exclusive slice end
        new_content = change.content or ""
        if not new_content.endswith("\n"):
            new_content += "\n"
        new_lines = lines[:s] + [new_content] + lines[e:]
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        return f"Replaced L{change.line_start}-{change.line_end}"

    else:
        raise RuntimeError("replace operation requires target_symbol OR line_start+line_end")


def _apply_insert(path: str, change: ChangeItem) -> str:
    """Insert content after line_end (or end of file if not specified)."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    new_content = change.content or ""
    if not new_content.endswith("\n"):
        new_content += "\n"

    if change.line_end:
        insert_at = change.line_end  # insert after this line (0-indexed: line_end)
        new_lines = lines[:insert_at] + [new_content] + lines[insert_at:]
    else:
        new_lines = lines + [new_content]

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    pos = f"after L{change.line_end}" if change.line_end else "at EOF"
    return f"Inserted {pos}"


def _apply_delete(path: str, change: ChangeItem) -> str:
    """Delete lines [line_start..line_end] or target_symbol."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    if change.target_symbol:
        source = "".join(lines)
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            raise RuntimeError(f"Cannot parse {path} for symbol deletion: {e}")

        node = None
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if n.name == change.target_symbol:
                    node = n
                    break
        if node is None:
            raise RuntimeError(f"Symbol '{change.target_symbol}' not found in {path}")

        start = node.lineno - 1
        end   = getattr(node, "end_lineno", node.lineno)
        new_lines = lines[:start] + lines[end:]
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        return f"Deleted symbol '{change.target_symbol}' (L{node.lineno}-{end})"

    elif change.line_start and change.line_end:
        s = change.line_start - 1
        e = change.line_end
        new_lines = lines[:s] + lines[e:]
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        return f"Deleted L{change.line_start}-{change.line_end}"

    else:
        raise RuntimeError("delete operation requires target_symbol OR line_start+line_end")


def _apply_create_file(project_root: str, path: str, change: ChangeItem) -> str:
    full_path = Path(project_root) / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    content = change.content or ""
    with open(str(full_path), "w", encoding="utf-8") as f:
        f.write(content)
    return f"Created {path}"


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class AppliedChange:
    operation: str
    file:      str
    diff_desc: str
    success:   bool
    error:     Optional[str] = None


@dataclass
class ExecutionResult:
    success:         bool
    session_id:      str
    applied:         list[AppliedChange]     = field(default_factory=list)
    syntax_errors:   list[str]               = field(default_factory=list)
    rolled_back:     bool                    = False
    rollback_path:   Optional[str]           = None
    error:           Optional[str]           = None
    duration:        float                   = 0.0
    read_only_output: Optional[str]          = None  # for explain/research

    def summary(self) -> str:
        ok  = sum(1 for a in self.applied if a.success)
        err = sum(1 for a in self.applied if not a.success)
        parts = [f"{ok} change(s) applied"]
        if err:
            parts.append(f"{err} failed")
        if self.rolled_back:
            parts.append("ROLLED BACK")
        if self.syntax_errors:
            parts.append(f"{len(self.syntax_errors)} syntax error(s)")
        return " | ".join(parts)


# ── Executor ──────────────────────────────────────────────────────────────────

class Executor:
    def __init__(self, project_root: str, dry_run: bool = False):
        self.project_root = str(Path(project_root).resolve())
        self.dry_run      = dry_run

    def _abs(self, rel_path: str) -> str:
        if os.path.isabs(rel_path):
            return rel_path
        return str(Path(self.project_root) / rel_path)

    def _preflight(self, proposal: Proposal) -> list[str]:
        """Returns list of error strings; empty = all clear."""
        errors = []
        for c in proposal.changes:
            if c.operation == "create_file":
                continue
            if c.operation in {"explain", "research_note"}:
                continue
            abs_path = self._abs(c.file)
            if not os.path.isfile(abs_path):
                errors.append(f"File not found: {c.file}")
        return errors

    def _snapshot(self, proposal: Proposal, session_id: str) -> Optional[str]:
        snap_dir = _snapshot_path(session_id)
        snap_dir.mkdir(parents=True, exist_ok=True)
        for c in proposal.changes:
            if c.operation in {"explain", "research_note", "create_file"}:
                continue
            abs_path = self._abs(c.file)
            if os.path.isfile(abs_path):
                dest = snap_dir / Path(c.file).name
                shutil.copy2(abs_path, dest)

        manifest = {
            "session_id":   session_id,
            "timestamp":    time.time(),
            "project_root": self.project_root,
            "files":        [c.file for c in proposal.changes
                             if c.operation not in {"explain", "research_note"}],
            "proposal":     proposal.to_dict(),
        }
        (snap_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        return str(snap_dir)

    def _rollback(self, session_id: str) -> None:
        snap_dir = _snapshot_path(session_id)
        manifest_path = snap_dir / "manifest.json"
        if not manifest_path.exists():
            return
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for rel_file in manifest.get("files", []):
            src = snap_dir / Path(rel_file).name
            dst = Path(self.project_root) / rel_file
            if src.exists():
                shutil.copy2(str(src), str(dst))

    def execute(self, proposal: Proposal) -> ExecutionResult:
        t0         = time.time()
        session_id = f"{int(t0)}_{id(proposal):x}"

        # Handle read-only proposals
        if proposal.is_read_only():
            output_parts = []
            for c in proposal.changes:
                if c.content:
                    output_parts.append(c.content)
            return ExecutionResult(
                success          = True,
                session_id       = session_id,
                read_only_output = "\n\n".join(output_parts) or proposal.summary,
                duration         = time.time() - t0,
            )

        # Pre-flight
        errors = self._preflight(proposal)
        if errors:
            return ExecutionResult(
                success    = False,
                session_id = session_id,
                error      = "Pre-flight failed:\n" + "\n".join(f"  {e}" for e in errors),
                duration   = time.time() - t0,
            )

        # Snapshot (skip for dry run)
        rollback_path = None
        if not self.dry_run:
            rollback_path = self._snapshot(proposal, session_id)

        # Pre-mutation syntax check
        syntax_errors_pre = []
        for c in proposal.changes:
            if c.operation in {"explain", "research_note"}:
                continue
            abs_path = self._abs(c.file)
            ok, err = _syntax_ok(abs_path)
            if not ok:
                syntax_errors_pre.append(f"{c.file}: {err}")

        applied: list[AppliedChange] = []
        fatal = False

        for c in proposal.changes:
            if c.operation in {"explain", "research_note"}:
                applied.append(AppliedChange(
                    operation = c.operation,
                    file      = c.file or "(none)",
                    diff_desc = "(read-only)",
                    success   = True,
                ))
                continue

            abs_path = self._abs(c.file)

            if self.dry_run:
                applied.append(AppliedChange(
                    operation = c.operation,
                    file      = c.file,
                    diff_desc = f"[DRY RUN] would {c.operation}",
                    success   = True,
                ))
                continue

            try:
                if c.operation == "replace":
                    desc = _apply_replace(abs_path, c)
                elif c.operation == "insert":
                    desc = _apply_insert(abs_path, c)
                elif c.operation == "delete":
                    desc = _apply_delete(abs_path, c)
                elif c.operation == "create_file":
                    desc = _apply_create_file(self.project_root, c.file, c)
                else:
                    desc = f"Unknown operation skipped: {c.operation}"

                applied.append(AppliedChange(
                    operation = c.operation,
                    file      = c.file,
                    diff_desc = desc,
                    success   = True,
                ))

            except Exception as e:
                applied.append(AppliedChange(
                    operation = c.operation,
                    file      = c.file,
                    diff_desc = "",
                    success   = False,
                    error     = str(e),
                ))
                fatal = True
                break  # stop applying further changes

        # Post-mutation syntax check
        syntax_errors_post = []
        for a in applied:
            if not a.success or a.operation in {"explain", "research_note"}:
                continue
            abs_path = self._abs(a.file)
            ok, err = _syntax_ok(abs_path)
            if not ok:
                syntax_errors_post.append(f"{a.file}: {err}")
                fatal = True

        # Rollback on failure
        rolled_back = False
        if fatal and not self.dry_run:
            self._rollback(session_id)
            rolled_back = True

        return ExecutionResult(
            success        = not fatal,
            session_id     = session_id,
            applied        = applied,
            syntax_errors  = syntax_errors_post,
            rolled_back    = rolled_back,
            rollback_path  = rollback_path,
            error          = None if not fatal else "Execution failed; rollback applied",
            duration       = time.time() - t0,
        )


# ── Rollback utility ──────────────────────────────────────────────────────────

def rollback_session(session_id: str, project_root: str) -> bool:
    """Public utility to manually rollback a session by ID."""
    ex = Executor(project_root)
    try:
        ex._rollback(session_id)
        return True
    except Exception:
        return False


def list_rollback_sessions() -> list[dict]:
    if not ROLLBACK_DIR.exists():
        return []
    sessions = []
    for d in sorted(ROLLBACK_DIR.iterdir(), reverse=True):
        manifest_path = d / "manifest.json"
        if manifest_path.exists():
            try:
                m = json.loads(manifest_path.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id":  m.get("session_id"),
                    "timestamp":   m.get("timestamp"),
                    "files":       m.get("files", []),
                })
            except Exception as e:
                _log.warning(f'caught exception: {e}')
    return sessions
