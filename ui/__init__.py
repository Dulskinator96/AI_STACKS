"""ui/ — extracted Qt view classes per MODULE_DECOMPOSITION_PLAN.md Phase A.

Each module here hosts a single Qt view that was previously inline in app.py.
Per CLAUDE.md §5 (MVC): Views are widget construction + QPainter + event
handling only — they MUST NOT call requests / sqlite3 / subprocess directly.
"""
