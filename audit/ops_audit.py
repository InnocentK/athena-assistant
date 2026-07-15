"""
audit/ops_audit.py — Structured operational audit log (Milestone 15).

`write_ops_event()` appends a single JSON object (JSON-lines format) to
today's ops audit log at `audit/<YYYY-MM-DD>_ops_audit.log`. It records
destructive or operationally significant events — for example memory
deletes, file writes, backup restores, and DAV connection checks.

Contract:
  - **Never raises.** Any filesystem or serialization error is swallowed
    so that audit logging can never break the request path.
  - One JSON object per line: ``{timestamp, event, outcome, detail}``.
  - Timestamps and the daily filename use UTC, matching the import and
    backup audit writers elsewhere in the project.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from core.config import APP_ROOT


def write_ops_event(event: str, outcome: str, detail: dict[str, Any] | None = None) -> None:
    """
    Append an operational audit event to today's ops audit log.

    Args:
        event:   Short event name, e.g. ``"memory_delete"`` or ``"file_write"``.
        outcome: Result of the operation, e.g. ``"success"`` or ``"failure"``.
        detail:  Best-effort JSON-serialisable dict of extra context.
                 Non-serialisable values are coerced with ``str``.

    This function never raises — failures are intentionally swallowed.
    """
    try:
        audit_dir = APP_ROOT / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        audit_file = audit_dir / f"{date_str}_ops_audit.log"

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "outcome": outcome,
            "detail": detail if detail is not None else {},
        }
        # default=str keeps the writer robust against non-serialisable detail.
        line = json.dumps(entry, default=str)

        with audit_file.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        # Audit logging must never break the caller.
        pass
