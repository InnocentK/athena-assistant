"""
dav_status/store.py — In-memory DAV sync status store.

Tracks the health and last-known state of each DAV integration:
  caldav, carddav, nextcloud

Each status record contains:
  - integration: str
  - enabled: bool
  - reachable: bool | None  (None = never checked)
  - last_check_at: str | None  (ISO UTC)
  - last_success_at: str | None
  - last_error_at: str | None
  - last_error_msg: str | None  (plain English, no stack traces)
  - item_counts: dict  (e.g. {"calendars": 3, "events": 42, "tasks": 5})
  - etags: dict  (calendar_url → last known CTag/ETag string)
  - ctags: dict  (calendar_url → last known CTag string, CalDAV specific)
  - sync_tokens: dict  (resource_url → sync token, where supported)
  - warnings: list[str]

The store is a module-level singleton. M26.16: access is guarded by a
threading.Lock — the DAV clients mutate records from `asyncio.to_thread`
worker threads while the status routes deepcopy snapshots on the event-loop
thread, so this is genuinely multi-threaded even under single-worker uvicorn
(an unlocked deepcopy iterating a dict another thread `.update()`s raises
"dictionary changed size during iteration").
"""

from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone
from typing import Union


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


class DavStatusStore:
    """In-memory store tracking health and last-known state for DAV integrations."""

    INTEGRATIONS = ("caldav", "carddav", "nextcloud")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[str, dict] = {}
        # Pre-populate with disabled/unchecked records
        for integration in self.INTEGRATIONS:
            self._store[integration] = self._default_record(integration)

    @staticmethod
    def _default_record(integration: str) -> dict:
        return {
            "integration": integration,
            "enabled": False,
            "reachable": None,
            "last_check_at": None,
            "last_success_at": None,
            "last_error_at": None,
            "last_error_msg": None,
            "item_counts": {},
            "etags": {},
            "ctags": {},
            "sync_tokens": {},
            "warnings": [],
        }

    def reset(self) -> None:
        """Reset all records to defaults (for testing)."""
        with self._lock:
            self._store = {
                k: self._default_record(k)
                for k in self.INTEGRATIONS
            }

    def set_enabled(self, integration: str, enabled: bool) -> None:
        """Update the enabled flag for an integration."""
        with self._lock:
            if integration not in self._store:
                self._store[integration] = self._default_record(integration)
            self._store[integration]["enabled"] = enabled

    def record_success(
        self,
        integration: str,
        item_counts: dict | None = None,
        etags: dict | None = None,
        ctags: dict | None = None,
        sync_tokens: dict | None = None,
    ) -> None:
        """Record a successful operation for the given integration."""
        with self._lock:
            if integration not in self._store:
                self._store[integration] = self._default_record(integration)
            record = self._store[integration]
            now = _now_iso()
            record["reachable"] = True
            record["last_check_at"] = now
            record["last_success_at"] = now
            record["last_error_msg"] = None
            record["last_error_at"] = None
            if item_counts:
                record["item_counts"].update(item_counts)
            if etags:
                record["etags"].update(etags)
            if ctags:
                record["ctags"].update(ctags)
            if sync_tokens:
                record["sync_tokens"].update(sync_tokens)

    def record_error(self, integration: str, error: Union[Exception, str]) -> None:
        """Record a failed operation for the given integration."""
        with self._lock:
            if integration not in self._store:
                self._store[integration] = self._default_record(integration)
            record = self._store[integration]
            now = _now_iso()
            record["reachable"] = False
            record["last_check_at"] = now
            record["last_error_at"] = now
            record["last_error_msg"] = self.humanise_error(error)

    def add_warning(self, integration: str, msg: str) -> None:
        """Append a warning message (capped at 10 most recent)."""
        with self._lock:
            if integration not in self._store:
                self._store[integration] = self._default_record(integration)
            warnings = self._store[integration]["warnings"]
            warnings.append(msg)
            # Keep only the 10 most recent
            if len(warnings) > 10:
                self._store[integration]["warnings"] = warnings[-10:]

    def get(self, integration: str) -> dict:
        """Return a copy of the record (or a default record if not found)."""
        with self._lock:
            if integration not in self._store:
                return self._default_record(integration)
            # M26.9: deep copy so a caller mutating a nested dict/list
            # (item_counts, etags, ctags, sync_tokens, warnings) cannot corrupt
            # the singleton. M26.16: copied under the lock so a worker thread's
            # concurrent update can't race the iteration.
            return copy.deepcopy(self._store[integration])

    def get_all(self) -> dict[str, dict]:
        """Return all records as a dict keyed by integration name."""
        with self._lock:
            return {k: copy.deepcopy(v) for k, v in self._store.items()}

    @staticmethod
    def humanise_error(exc: Union[Exception, str]) -> str:
        """Convert common exception types to plain English messages.

        Public API (M26.16) — the DAV clients call this from their
        check_connection paths; it was previously the private
        ``_humanise_error`` (kept below as an alias).
        """
        # Check exception type first
        if isinstance(exc, ConnectionRefusedError):
            return "Connection refused — server may be down or unreachable"
        if isinstance(exc, ConnectionError):
            return "Connection refused — server may be down or unreachable"
        if isinstance(exc, TimeoutError):
            return "Connection timed out — server did not respond in time"

        # Try to detect config errors by class name
        exc_type_name = type(exc).__name__
        if exc_type_name in ("CalDAVConfigError", "CardDAVConfigError", "NextcloudConfigError"):
            return "Integration not configured — missing environment variables"

        # Convert to string for pattern matching
        exc_str = str(exc)

        # Check for SSL/certificate errors
        if "SSL" in exc_str or "certificate" in exc_str:
            return "SSL/TLS error — check server certificate"

        # Check for HTTP status codes in the string
        if "401" in exc_str or "Unauthorized" in exc_str:
            return "Authentication failed — check username/password"
        if "403" in exc_str or "Forbidden" in exc_str:
            return "Access denied — insufficient permissions"
        if "404" in exc_str or "Not Found" in exc_str:
            return "Resource not found — check the URL in your config"

        # Check for config error substrings
        if "Missing required environment variable" in exc_str:
            return "Integration not configured — missing environment variables"

        # Default: first 200 chars, stripping Python traceback markers
        clean = exc_str[:200]
        # Remove common traceback markers
        for marker in ('File "', "Traceback"):
            if marker in clean:
                clean = clean[:clean.index(marker)].strip()
        return clean.strip() or "An unknown error occurred"

    # Backward-compat alias (private name used before M26.16)
    _humanise_error = humanise_error


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_status_store = DavStatusStore()


def get_status_store() -> DavStatusStore:
    """Return the module-level singleton DavStatusStore."""
    return _status_store
