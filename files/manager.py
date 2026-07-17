"""
files/manager.py — FileManager: dynamic file allowlist and file I/O.

The allowlist is loaded from config/files.yaml and can be reloaded at
runtime without restarting the server.

Security rules (MUST NOT regress):
  - Paths in the allowlist must be absolute or relative to APP_ROOT.
  - Every resolved path is normalised and checked that it stays within
    an allowed root entry — no path traversal.
  - The server-side Python source tree (APP_ROOT itself as a write root)
    is never added automatically.
  - All file writes are appended to audit/<date>_file_audit.log.
  - FileManager never modifies config/files.yaml itself via the write API.
"""

from __future__ import annotations

import datetime
import fnmatch
from pathlib import Path
from typing import Any

import yaml

from core.config import APP_ROOT

# Path to the allowlist configuration file
_FILES_CONFIG: Path = APP_ROOT / "config" / "files.yaml"

# Path to the audit directory
_AUDIT_DIR: Path = APP_ROOT / "audit"

# M26.14 — cap on read_file. Deliberately equal to the Nextcloud client's
# streaming read cap so local and remote reads behave alike. An oversized file
# returns the first 2MB with truncated=true instead of buffering everything.
_MAX_READ_BYTES: int = 2 * 1024 * 1024

# M26.3 — view-level hygiene for the History → Files tab. These paths are
# internal/operational (logs, audit, staging, backups) and are hidden from the
# user-facing Files view by default. This is a *presentation* filter only:
# the allowlist and all FileManager read/write/search security are unchanged,
# and the filter is opt-in via the `exclude_internal` argument.
_INTERNAL_DIR_PREFIXES: tuple[str, ...] = (
    "logs",
    "audit",
    "data/carddav_staged",
    "data/import_conflicts",
    "data/restore_staging",
    "data/exports",
)
_INTERNAL_FILE_PATTERNS: tuple[str, ...] = ("*.log", ".gitkeep", "*.pyc")


def _is_internal_path(rel_posix: str) -> bool:
    """
    True if *rel_posix* (an APP_ROOT-relative POSIX path) is an internal/ops
    artifact — i.e. lives under an internal directory subtree or matches an
    internal file pattern (M26.3). Used only to filter the user-facing view.
    """
    parts = rel_posix.split("/")
    for prefix in _INTERNAL_DIR_PREFIXES:
        prefix_parts = prefix.split("/")
        if parts[: len(prefix_parts)] == prefix_parts:
            return True
    name = parts[-1] if parts else rel_posix
    return any(fnmatch.fnmatch(name, pat) for pat in _INTERNAL_FILE_PATTERNS)


class FileManager:
    """
    Manages a dynamic file allowlist and provides secure file I/O operations.

    The allowlist is defined in config/files.yaml and specifies which paths
    the assistant may search, read, or write.  Each entry has independent
    search/read/write permissions.

    All write operations are logged to audit/<YYYY-MM-DD>_file_audit.log.
    """

    def __init__(self) -> None:
        """Load the allowlist from config/files.yaml on initialisation."""
        self._entries: list[dict[str, Any]] = []
        self.reload()

    # ------------------------------------------------------------------
    # Allowlist management
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """Re-read config/files.yaml from disk (hot-reload without restart)."""
        if not _FILES_CONFIG.exists():
            self._entries = []
            return

        with _FILES_CONFIG.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}

        self._entries = data.get("entries", []) or []

    def list_allowlist(self) -> list[dict[str, Any]]:
        """Return the current allowlist entries as a list of dicts."""
        return list(self._entries)

    def add_entry(
        self,
        path: str,
        search: bool = True,
        read: bool = True,
        write: bool = False,
        label: str = "",
    ) -> dict[str, Any]:
        """
        Add a new entry to the allowlist, persist to YAML, and return the entry dict.

        Raises ValueError if the path is already in the allowlist.
        """
        # Normalise the path string for deduplication
        for existing in self._entries:
            if existing.get("path") == path:
                raise ValueError(f"Path already in allowlist: {path!r}")

        entry: dict[str, Any] = {
            "path": path,
            "label": label,
            "search": bool(search),
            "read": bool(read),
            "write": bool(write),
        }
        self._entries.append(entry)
        self._save_config()
        return entry

    def remove_entry(self, path: str) -> bool:
        """
        Remove an entry by path from the allowlist and persist to YAML.

        Returns True if the entry was found and removed, False otherwise.
        """
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.get("path") != path]
        if len(self._entries) < before:
            self._save_config()
            return True
        return False

    def _save_config(self) -> None:
        """Write the current entries back to config/files.yaml."""
        _FILES_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        with _FILES_CONFIG.open("w", encoding="utf-8") as fh:
            yaml.safe_dump({"entries": self._entries}, fh, default_flow_style=False, sort_keys=False)

    # ------------------------------------------------------------------
    # Path resolution and permission checks
    # ------------------------------------------------------------------

    def resolve_path(self, path_str: str) -> Path | None:
        """
        Resolve a path string relative to APP_ROOT, normalise it, and
        verify it stays within at least one allowed root entry.

        Returns the resolved absolute Path, or None if the path traverses
        outside every allowed root (path traversal rejected).
        """
        # Build candidate path: if absolute, use as-is; otherwise relative to APP_ROOT
        candidate = Path(path_str)
        if not candidate.is_absolute():
            candidate = APP_ROOT / candidate
        candidate = candidate.resolve()

        # Check that candidate is under at least one allowlist entry root
        for entry in self._entries:
            entry_path = Path(entry["path"])
            if not entry_path.is_absolute():
                entry_path = APP_ROOT / entry_path
            entry_path = entry_path.resolve()

            try:
                candidate.relative_to(entry_path)
                return candidate  # found a valid root
            except ValueError:
                continue

        return None  # path not under any allowed root

    def _find_entry_for_path(self, resolved: Path, permission: str) -> bool:
        """
        Return True if the resolved path falls under an entry that has
        the given permission (``"search"``, ``"read"``, or ``"write"``) set to True.
        """
        for entry in self._entries:
            entry_path = Path(entry["path"])
            if not entry_path.is_absolute():
                entry_path = APP_ROOT / entry_path
            entry_path = entry_path.resolve()

            try:
                resolved.relative_to(entry_path)
            except ValueError:
                continue

            if entry.get(permission, False):
                return True

        return False

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def search_files(
        self,
        pattern: str,
        allowed_roots: list[str] | None = None,
        exclude_internal: bool = False,
    ) -> list[str]:
        """
        Glob-search for files matching *pattern* across all search-allowed paths.

        If *allowed_roots* is provided, only those roots are searched (they must
        still have ``search: true`` in the allowlist).

        If *exclude_internal* is True, internal/operational artifacts (logs,
        audit, staging, backups, ``*.log``/``.gitkeep``/``*.pyc``) are filtered
        out of the results — a view-level convenience for the user-facing Files
        tab (M26.3). The allowlist itself is unchanged.

        Returns a list of paths relative to APP_ROOT as POSIX strings.
        """
        results: list[str] = []
        seen: set[Path] = set()

        for entry in self._entries:
            if not entry.get("search", False):
                continue

            entry_path = Path(entry["path"])
            if not entry_path.is_absolute():
                entry_path = APP_ROOT / entry_path
            entry_path = entry_path.resolve()

            # Filter by requested roots if provided
            if allowed_roots is not None:
                match = False
                for root in allowed_roots:
                    root_path = Path(root)
                    if not root_path.is_absolute():
                        root_path = APP_ROOT / root_path
                    root_path = root_path.resolve()
                    if entry_path == root_path or entry_path.is_relative_to(root_path):
                        match = True
                        break
                if not match:
                    continue

            if not entry_path.is_dir():
                continue

            for match_path in entry_path.rglob(pattern) if "**" in pattern or "/" in pattern else entry_path.glob(pattern):
                if match_path in seen:
                    continue
                seen.add(match_path)
                # M30.4: results are FILES only — bare directories rendered as
                # clickable "files" in the UI whose preview then 400s (observed
                # live with data/uploads).
                if not match_path.is_file():
                    continue
                try:
                    rel = match_path.relative_to(APP_ROOT)
                    results.append(rel.as_posix())
                except ValueError:
                    results.append(str(match_path))

        if exclude_internal:
            results = [r for r in results if not _is_internal_path(r)]
        return results

    def read_file(self, path_str: str) -> dict[str, Any]:
        """
        Read a file if it falls under a read-allowed allowlist entry.

        Returns ``{"content": <text>, "path": <relative-path-string>,
        "truncated": <bool>}``.

        M26.14 robustness: the read is capped at ``_MAX_READ_BYTES`` (matching
        the Nextcloud client's streaming cap) and decoded with
        ``errors="replace"`` — a binary or non-UTF-8 file returns replacement
        characters instead of raising ``UnicodeDecodeError``, and an oversized
        file returns the first 2MB with ``truncated: true``.

        Raises:
            PermissionError: if the path is not under a read-allowed entry.
            FileNotFoundError: if the file does not exist.
        """
        resolved = self.resolve_path(path_str)
        if resolved is None:
            raise PermissionError(
                f"Path traversal rejected or path not under any allowed root: {path_str!r}"
            )

        if not self._find_entry_for_path(resolved, "read"):
            raise PermissionError(
                f"Read access denied for path: {path_str!r}"
            )

        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {path_str!r}")

        if not resolved.is_file():
            raise IsADirectoryError(f"Path is a directory, not a file: {path_str!r}")

        with resolved.open("rb") as fh:
            raw = fh.read(_MAX_READ_BYTES + 1)
        truncated = len(raw) > _MAX_READ_BYTES
        content = raw[:_MAX_READ_BYTES].decode("utf-8", errors="replace")

        # Return relative path string when possible
        try:
            rel = resolved.relative_to(APP_ROOT)
            return {"content": content, "path": rel.as_posix(), "truncated": truncated}
        except ValueError:
            return {"content": content, "path": str(resolved), "truncated": truncated}

    def write_file(self, path_str: str, content: str) -> dict[str, Any]:
        """
        Write content to a file if it falls under a write-allowed entry.

        Security constraints:
          - Never writes to config/files.yaml (raise PermissionError).
          - Path must resolve within an allowlist entry with write=true.

        Returns ``{"written": True, "path": <relative-path-string>}``.

        Raises:
            PermissionError: if the path is the allowlist config, is not under
                             any allowed root, or lacks write permission.
        """
        # Reject writes to the allowlist config
        config_resolved = _FILES_CONFIG.resolve()
        candidate = Path(path_str)
        if not candidate.is_absolute():
            candidate = APP_ROOT / candidate
        candidate = candidate.resolve()
        if candidate == config_resolved:
            raise PermissionError(
                "Writing to config/files.yaml via the file API is forbidden."
            )

        resolved = self.resolve_path(path_str)
        if resolved is None:
            raise PermissionError(
                f"Path traversal rejected or path not under any allowed root: {path_str!r}"
            )

        if not self._find_entry_for_path(resolved, "write"):
            raise PermissionError(
                f"Write access denied for path: {path_str!r}"
            )

        # Create parent directories if needed
        resolved.parent.mkdir(parents=True, exist_ok=True)

        encoded = content.encode("utf-8")
        resolved.write_bytes(encoded)

        bytes_written = len(encoded)
        self._audit_write(path_str, bytes_written)

        try:
            rel = resolved.relative_to(APP_ROOT)
            rel_str = rel.as_posix()
        except ValueError:
            rel_str = str(resolved)

        return {"written": True, "path": rel_str}

    def _audit_write(self, path_str: str, bytes_written: int) -> None:
        """
        Append a write record to ``audit/YYYY-MM-DD_file_audit.log``.

        Format: ``ISO_TIMESTAMP | WRITE | <path> | <bytes> bytes``
        """
        _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.date.today().isoformat()
        log_path = _AUDIT_DIR / f"{today}_file_audit.log"
        timestamp = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
        line = f"{timestamp} | WRITE | {path_str} | {bytes_written} bytes\n"
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line)
