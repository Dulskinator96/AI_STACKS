"""truth/failure_classifier.py — silent-failure eradication helper.

Doctrine §3 P2 (NO SILENT FAILURE): every caught exception that is not
re-raised must be classified, emitted, receipted, and lineage-linked.
This module provides the one-line idiom that does all four:

    from truth.failure_classifier import report_caught
    try:
        ...
    except Exception as exc:
        report_caught("task_name", exc, executor="MyClass.method",
                       evidence={"context_key": value})
        # then return / continue / re-raise as the caller's logic requires

`report_caught` never raises. If the truth layer itself is unreachable
(e.g., during very early boot before the receipt_engine import resolves),
the failure is logged at WARNING and otherwise swallowed — that's the
ONE acceptable silent point: the receipt-emission machinery itself.

Classification codes are stable strings useful for grep + dashboards:
    FS_NOT_FOUND, FS_PERMISSION, FS_OS, JSON_PARSE, IMPORT_FAIL,
    NETWORK, NETWORK_TIMEOUT, DB_OPERATIONAL, DB_INTEGRITY,
    MISSING_KEY, MISSING_ATTR, TYPE_MISMATCH, VALUE_INVALID,
    RUNTIME, UNCLASSIFIED

Severity tags are recorded as evidence but never raise on caller side.
"""
from __future__ import annotations

import logging
from typing import Optional

_log = logging.getLogger(__name__)


# Class-name → stable failure code. Walks the exception MRO so a subclass
# of ConnectionError still classifies as NETWORK.
_EXCEPTION_TO_CODE: dict[str, str] = {
    "FileNotFoundError":   "FS_NOT_FOUND",
    "PermissionError":     "FS_PERMISSION",
    "IsADirectoryError":   "FS_OS",
    "NotADirectoryError":  "FS_OS",
    "OSError":             "FS_OS",
    "JSONDecodeError":     "JSON_PARSE",
    "ImportError":         "IMPORT_FAIL",
    "ModuleNotFoundError": "IMPORT_FAIL",
    "ConnectionError":     "NETWORK",
    "ConnectionResetError":   "NETWORK",
    "ConnectionRefusedError": "NETWORK",
    "TimeoutError":        "NETWORK_TIMEOUT",
    "OperationalError":    "DB_OPERATIONAL",
    "IntegrityError":      "DB_INTEGRITY",
    "KeyError":            "MISSING_KEY",
    "AttributeError":      "MISSING_ATTR",
    "TypeError":           "TYPE_MISMATCH",
    "ValueError":          "VALUE_INVALID",
    "RuntimeError":        "RUNTIME",
    "MemoryError":         "RUNTIME_OOM",
    "RecursionError":      "RUNTIME_RECURSION",
    "AssertionError":      "ASSERTION",
}


def classify_exception(exc: BaseException) -> str:
    """Map an exception to a stable failure code via MRO walk.
    Returns 'UNCLASSIFIED' when no class in the MRO matches the table."""
    try:
        for cls in type(exc).__mro__:
            name = cls.__name__
            if name in _EXCEPTION_TO_CODE:
                return _EXCEPTION_TO_CODE[name]
    except Exception:
        pass
    return "UNCLASSIFIED"


def report_caught(
    task: str,
    exc: BaseException,
    *,
    executor: str = "",
    evidence: Optional[dict] = None,
    severity: str = "warning",
) -> str:
    """Emit a classified receipt for a swallowed exception.

    Returns the classification code (so callers can branch on it if needed).
    Never raises — receipt emission failure is the one place silence is OK
    because that's where the bottom turtle lives.
    """
    code = classify_exception(exc)
    try:
        from truth.receipt_engine import record_execution
        ev: dict = {
            "exception_code": code,
            "exception_type": type(exc).__name__,
            "exception_msg":  str(exc)[:240],
            "severity":       severity,
        }
        if evidence:
            ev.update(evidence)
        record_execution(
            task=task,
            executor=executor or "anonymous",
            artifact=None,
            duration_ms=0.0,
            verified=False,
            compute_sha256=False,
            evidence=ev,
        )
    except Exception as e:
        _log.warning(
            "report_caught: receipt emit failed for task=%s code=%s: %s",
            task, code, e,
        )
    return code
