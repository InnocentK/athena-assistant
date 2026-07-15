"""
backup/manager.py — Backup, export, and restore for Athena profiles and local data.

Export creates a zip archive containing:
  - athena_backup_manifest.json  (metadata)
  - profiles/                    (always included)
  - config/                      (always included)
  - audit/                       (optional, default: false)
  - data/                        (optional, default: false)

Restore flow:
  1. Validate the zip contains a manifest
  2. Check manifest version compatibility
  3. Run a dry-run diff: list files that would be added or overwritten
  4. If confirm=False, return the diff without writing anything
  5. If confirm=True, backup existing files to data/restore_staging/<timestamp>/ first,
     then extract the zip (overwriting target files)
  6. Audit all restore actions

Safety constraints:
  - Never restore .env (skip silently, warn in result)
  - Never restore .venv/ or __pycache__/
  - Manifest version mismatch (major version difference) warns but does not block
    unless the caller explicitly passes force=False
  - Existing files are staged before overwrite (rollback-friendly)
"""

from __future__ import annotations

import fnmatch
import json
import shutil
import socket
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MANIFEST_FILENAME = "athena_backup_manifest.json"
BACKUP_VERSION = "1"   # bump if manifest schema changes incompatibly
EXCLUDED_FROM_BACKUP = {".env", ".venv", "__pycache__", "*.pyc", "*.pyo"}
EXCLUDED_FROM_RESTORE = {".env", ".venv/", "__pycache__/"}


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _now_stamp() -> str:
    """Return a compact timestamp suitable for filenames."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _matches_excluded(name: str, patterns: set[str]) -> bool:
    """Return True if *name* matches any exclusion pattern."""
    for pat in patterns:
        if fnmatch.fnmatch(name, pat):
            return True
        # Also check if the name equals or starts with the pattern (for dirs)
        if pat.endswith("/") and (name == pat.rstrip("/") or name.startswith(pat)):
            return True
    return False


def _path_excluded_from_backup(rel: str) -> bool:
    """Return True if the relative path should be excluded from a backup zip."""
    parts = Path(rel).parts
    for part in parts:
        if _matches_excluded(part, EXCLUDED_FROM_BACKUP):
            return True
    return False


def _path_excluded_from_restore(rel: str) -> bool:
    """Return True if the relative path should be skipped during restore."""
    parts = Path(rel).parts
    # Check leading parts against directory exclusions
    for i, part in enumerate(parts):
        candidate = part
        if _matches_excluded(candidate, EXCLUDED_FROM_RESTORE):
            return True
        # Also check full leading path segments
        partial = str(Path(*parts[: i + 1]))
        if _matches_excluded(partial + "/", EXCLUDED_FROM_RESTORE):
            return True
    return False


class BackupManager:
    """Manages backup export, inspection, diff, and restore for Athena."""

    def __init__(self, app_root: Path, app_version: str = "0.0.0") -> None:
        self._root = app_root
        self._staging_dir = app_root / "data" / "restore_staging"
        self._audit_dir = app_root / "audit"
        # M26.9: the manifest's app_version reflects the real running app version
        # (passed from main.py's app.version — the single source, M26.2), instead
        # of a stale hardcoded literal. Defaults harmlessly when constructed in
        # isolation (e.g. tests).
        self._app_version = app_version

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _safe_target(self, member: str) -> Path | None:
        """
        Resolve a zip member name to its destination path, or return None if it
        would escape the app root (Zip-Slip guard, M26.7).

        Catches both ``../`` traversal and absolute-path members (an absolute
        member replaces the join, so it resolves outside the root and is
        rejected). Every restore/diff write must go through this.
        """
        root = self._root.resolve()
        target = (self._root / member).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return None
        return target

    def _audit(self, line: str) -> None:
        """Append a line to today's backup audit log."""
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_path = self._audit_dir / f"{date_str}_backup_audit.log"
        timestamp = _now_iso()
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(f"{timestamp} | {line}\n")

    def _collect_files(
        self,
        *,
        include_audit: bool = False,
        include_data: bool = False,
    ) -> list[tuple[Path, str]]:
        """
        Collect (absolute_path, relative_arcname) pairs for inclusion in a backup zip.

        Always includes profiles/ and config/.
        Optionally includes audit/ and data/ (with recursion guards).
        """
        pairs: list[tuple[Path, str]] = []

        dirs_to_include: list[Path] = [
            self._root / "profiles",
            self._root / "config",
        ]
        if include_audit:
            dirs_to_include.append(self._root / "audit")
        if include_data:
            dirs_to_include.append(self._root / "data")

        # Dirs to skip when recursing into data/
        skip_absolute = {
            self._root / "data" / "restore_staging",
            self._root / "data" / "exports",
        }

        for base_dir in dirs_to_include:
            if not base_dir.exists():
                continue
            for path in sorted(base_dir.rglob("*")):
                if not path.is_file():
                    continue
                # Skip directories in the recursion-guard set
                if any(path.is_relative_to(s) for s in skip_absolute):
                    continue
                rel = str(path.relative_to(self._root))
                if _path_excluded_from_backup(rel):
                    continue
                pairs.append((path, rel))

        return pairs

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_export(
        self,
        include_audit: bool = False,
        include_data: bool = False,
    ) -> Path:
        """
        Build a zip archive under data/exports/ and return its path.

        The zip contains profiles/, config/, optionally audit/ and data/,
        plus a athena_backup_manifest.json at the root.
        """
        exports_dir = self._root / "data" / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)

        stamp = _now_stamp()
        zip_path = exports_dir / f"{stamp}_athena_backup.zip"

        # Collect files before opening zip
        file_pairs = self._collect_files(
            include_audit=include_audit,
            include_data=include_data,
        )

        rel_paths = [rel for _, rel in file_pairs]

        # Build manifest
        manifest: dict[str, Any] = {
            "backup_version": BACKUP_VERSION,
            "app_version": self._app_version,
            "created_at": _now_iso(),
            "hostname": socket.gethostname(),
            "includes": {
                "profiles": True,
                "config": True,
                "audit": include_audit,
                "data": include_data,
            },
            "file_count": len(rel_paths),
            "files": rel_paths,
        }

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # Write manifest first
            zf.writestr(MANIFEST_FILENAME, json.dumps(manifest, indent=2))
            # Write files
            for abs_path, arcname in file_pairs:
                zf.write(abs_path, arcname)

        self._audit(
            f"BACKUP_EXPORT | file={zip_path} | files={len(rel_paths)}"
        )

        return zip_path

    def list_exports(self) -> list[dict[str, Any]]:
        """
        Scan data/exports/ for *.zip files.

        Returns a list of dicts with metadata read from each manifest.
        Silently skips unreadable or invalid zips.
        """
        exports_dir = self._root / "data" / "exports"
        if not exports_dir.exists():
            return []

        results: list[dict[str, Any]] = []
        for zip_path in sorted(exports_dir.glob("*.zip")):
            try:
                info = self.inspect_backup(zip_path)
                if not info.get("valid"):
                    continue
                results.append(
                    {
                        "filename": zip_path.name,
                        "path": str(zip_path),
                        "created_at": info.get("created_at"),
                        "file_count": info.get("file_count"),
                        "includes": info.get("includes"),
                        "app_version": info.get("app_version"),
                    }
                )
            except Exception:  # noqa: BLE001
                continue

        return results

    def inspect_backup(self, zip_path: Path) -> dict[str, Any]:
        """
        Open zip and return its manifest dict plus validity flag.

        On error returns {"valid": False, "error": str(exc)}.
        """
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                manifest_bytes = zf.read(MANIFEST_FILENAME)
            manifest = json.loads(manifest_bytes)
            manifest["zip_path"] = str(zip_path)
            manifest["valid"] = True
            return manifest
        except Exception as exc:  # noqa: BLE001
            return {"valid": False, "error": str(exc)}

    def diff_restore(self, zip_path: Path) -> dict[str, Any]:
        """
        Perform a dry-run diff of what restoring zip_path would change.

        Returns dict with would_add, would_overwrite, would_skip, warnings, manifest.
        No files are written.
        """
        warnings: list[str] = []

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                all_names = zf.namelist()
                try:
                    manifest_bytes = zf.read(MANIFEST_FILENAME)
                    manifest = json.loads(manifest_bytes)
                except Exception as exc:  # noqa: BLE001
                    return {
                        "manifest": {},
                        "would_add": [],
                        "would_overwrite": [],
                        "would_skip": [],
                        "warnings": [f"Could not read manifest: {exc}"],
                    }
        except Exception as exc:  # noqa: BLE001
            return {
                "manifest": {},
                "would_add": [],
                "would_overwrite": [],
                "would_skip": [],
                "warnings": [f"Could not open zip: {exc}"],
            }

        # Check version compatibility
        zip_version = manifest.get("backup_version", "?")
        if zip_version != BACKUP_VERSION:
            warnings.append(
                f"Manifest backup_version={zip_version!r} differs from current "
                f"BACKUP_VERSION={BACKUP_VERSION!r}. Proceed with caution."
            )

        would_add: list[str] = []
        would_overwrite: list[str] = []
        would_skip: list[str] = []
        rejected: list[str] = []

        for name in all_names:
            # Skip the manifest itself
            if name == MANIFEST_FILENAME:
                continue

            # Warn about .env presence
            if Path(name).name == ".env":
                warnings.append(
                    f"Zip contains '{name}' — .env will be skipped during restore."
                )

            # Check restore exclusions
            if _path_excluded_from_restore(name):
                would_skip.append(name)
                continue

            # M26.7: reject any member that would escape the app root (Zip-Slip).
            target = self._safe_target(name)
            if target is None:
                rejected.append(name)
                continue

            if target.exists():
                would_overwrite.append(name)
            else:
                would_add.append(name)

        if rejected:
            warnings.append(
                f"Rejected {len(rejected)} unsafe path(s) that would escape the app root: "
                + ", ".join(rejected[:5])
                + (" …" if len(rejected) > 5 else "")
            )

        return {
            "manifest": manifest,
            "would_add": would_add,
            "would_overwrite": would_overwrite,
            "rejected": rejected,
            "would_skip": would_skip,
            "warnings": warnings,
        }

    def restore_backup(
        self,
        zip_path: Path,
        confirm: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Restore files from zip_path.

        If confirm=False: returns diff only (no writes).
        If confirm=True: stages overwritten files, then extracts the zip.
        """
        if not confirm:
            diff = self.diff_restore(zip_path)
            diff["confirmed"] = False
            diff["message"] = "Pass confirm=true to apply."
            return diff

        # --- Confirmed restore ---
        diff = self.diff_restore(zip_path)
        warnings = list(diff.get("warnings", []))
        manifest = diff.get("manifest", {})

        # Version mismatch warning (already in diff warnings, but note it here)
        zip_version = manifest.get("backup_version", "?")
        if zip_version != BACKUP_VERSION and not force:
            # Warn but don't block (as per spec)
            pass  # warning already in diff

        # Stage files that would be overwritten
        timestamp = _now_stamp()
        staging_subdir = self._staging_dir / timestamp
        staged_paths: list[str] = []

        for rel in diff.get("would_overwrite", []):
            src = self._root / rel
            if src.exists():
                dst = staging_subdir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                staged_paths.append(rel)

        # Extract zip, skipping excluded files
        added = 0
        overwritten = 0
        skipped = 0
        rejected = 0

        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.namelist():
                # Skip manifest
                if member == MANIFEST_FILENAME:
                    continue
                # Skip exclusions
                if _path_excluded_from_restore(member):
                    skipped += 1
                    continue
                # M26.7: reject any member that would escape the app root
                # (Zip-Slip). Never open() a raw self._root / member join.
                target = self._safe_target(member)
                if target is None:
                    rejected += 1
                    continue
                is_overwrite = target.exists()

                # Extract to the resolved, contained target.
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src_f, open(target, "wb") as dst_f:
                    shutil.copyfileobj(src_f, dst_f)

                if is_overwrite:
                    overwritten += 1
                else:
                    added += 1

        if rejected:
            warnings.append(
                f"Rejected {rejected} unsafe path(s) that would escape the app root during restore."
            )

        self._audit(
            f"BACKUP_RESTORE | zip={zip_path.name} | "
            f"added={added} overwritten={overwritten} skipped={skipped} "
            f"rejected={rejected} staged={len(staged_paths)}"
        )

        result: dict[str, Any] = {
            "restored": True,
            "added": added,
            "overwritten": overwritten,
            "skipped": skipped,
            "rejected": rejected,
            "staged_to": f"data/restore_staging/{timestamp}/",
            "warnings": warnings,
        }
        return result

    def delete_export(self, zip_path: Path) -> bool:
        """
        Delete a backup zip file.

        Returns True on success, False if the file was not found.
        """
        if not zip_path.exists():
            return False
        zip_path.unlink()
        self._audit(f"BACKUP_DELETE | file={zip_path.name}")
        return True
