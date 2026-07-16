"""
app/routers/files.py — files HTTP routes (M26.18, split from main.py).

Handlers reference app state/singletons/tunables through ``main.`` (module-level
``import main`` below). main.py reloads these router modules as it assembles the
app, so the reference always resolves to the live main — see app/__init__.py.
Do NOT convert ``main.X`` lookups into ``from main import X`` (that captures a
stale module across the test suite's per-test main re-import).
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, UploadFile

from core.config import APP_ROOT


from app.models import (
    FileAllowlistAddRequest,
    FileSearchRequest, FileWriteRequest,
)

import main  # noqa: E402  — call-time-safe via reload in main.py; see docstring

router = APIRouter()


@router.get("/files/allowlist", summary="List the file access allowlist")
async def files_allowlist_list() -> list[dict[str, Any]]:
    """
    Returns the current file access allowlist entries.

    Each entry has: path, label, search, read, write.
    """
    fm = main._require_files()
    return fm.list_allowlist()


@router.post("/files/allowlist", summary="Add an entry to the file access allowlist")
async def files_allowlist_add(body: FileAllowlistAddRequest) -> dict[str, Any]:
    """
    Add a new path entry to the file access allowlist.

    The entry is immediately persisted to config/files.yaml.
    Returns the created entry dict.
    """
    fm = main._require_files()
    try:
        entry = fm.add_entry(
            path=body.path,
            search=body.search,
            read=body.read,
            write=body.write,
            label=body.label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return entry


@router.delete("/files/allowlist", summary="Remove an entry from the file access allowlist")
async def files_allowlist_remove(
    path: str = Query(..., description="The path entry to remove from the allowlist"),
) -> dict[str, bool]:
    """
    Remove a path entry from the allowlist by its path string.

    Returns {"removed": true} on success, or 404 if not found.
    """
    fm = main._require_files()
    removed = fm.remove_entry(path)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Allowlist entry not found: {path!r}")
    return {"removed": True}


@router.patch("/files/allowlist/reload", summary="Hot-reload the file allowlist config from disk")
async def files_allowlist_reload() -> dict[str, bool]:
    """
    Re-read config/files.yaml from disk without restarting the server.

    Returns {"reloaded": true}.
    """
    fm = main._require_files()
    fm.reload()
    return {"reloaded": True}


@router.post("/files/search", summary="Glob-search files across search-permitted paths")
async def files_search(body: FileSearchRequest) -> list[str]:
    """
    Search for files matching the given glob pattern across all search-allowed paths.

    The optional ``root`` field restricts the search to a specific sub-path.
    Returns a list of relative path strings.
    """
    fm = main._require_files()
    allowed_roots = [body.root] if body.root else None
    # M26.14: rglob across allowlisted roots is disk-bound — run off the loop.
    return await asyncio.to_thread(
        fm.search_files,
        body.pattern,
        allowed_roots=allowed_roots,
        exclude_internal=body.exclude_internal,
    )


@router.get("/files/read", summary="Read a file from a read-permitted path")
async def files_read(
    path: str = Query(..., description="Path to the file to read (relative to APP_ROOT or absolute)"),
) -> dict[str, Any]:
    """
    Read the contents of a file that falls under a read-permitted allowlist entry.

    Returns {"content": "<text>", "path": "<relative-path>", "truncated": bool}.
    Reads are capped at 2MB (truncated=true beyond that) and decoded with
    errors="replace" — binary files return replacement characters, not a 500.
    Raises 403 if the path is not allowed, 404 if the file does not exist.
    """
    fm = main._require_files()
    try:
        # M26.14: up-to-2MB disk read runs off the loop.
        return await asyncio.to_thread(fm.read_file, path)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IsADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/files/write", summary="Write a file to a write-permitted path")
async def files_write(body: FileWriteRequest) -> dict[str, Any]:
    """
    Write content to a file that falls under a write-permitted allowlist entry.

    The write is logged to audit/<YYYY-MM-DD>_file_audit.log.
    Raises 403 if the path is the allowlist config, not under any allowed root,
    or lacks write permission.
    """
    from core.config import APP_ROOT as _APP_ROOT  # local import to avoid shadowing
    from pathlib import Path as _Path

    # Safety guard: block writes to config/files.yaml
    _config_resolved = (_APP_ROOT / "config" / "files.yaml").resolve()
    _candidate = _Path(body.path)
    if not _candidate.is_absolute():
        _candidate = _APP_ROOT / _candidate
    _candidate = _candidate.resolve()
    if _candidate == _config_resolved:
        raise HTTPException(
            status_code=403,
            detail="Cannot write to the file allowlist config via the API.",
        )

    fm = main._require_files()
    try:
        result = fm.write_file(body.path, body.content)
        main.write_ops_event(
            event="file_write",
            outcome="success",
            detail={"path": body.path},
        )
        return result
    except PermissionError as exc:
        main.write_ops_event(
            event="file_write",
            outcome="failure",
            detail={"path": body.path, "error": str(exc)},
        )
        raise HTTPException(status_code=403, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Uploads (M29.3) — plain files under data/uploads/, read via the allowlist
# ---------------------------------------------------------------------------

_UPLOAD_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_UPLOAD_SAFE_CHAR = re.compile(r"[^A-Za-z0-9._-]")


def _uploads_dir():
    return APP_ROOT / "data" / "uploads"


def _sanitize_upload_name(raw: str | None) -> str:
    """Basename only; unsafe chars -> _; no dotfiles; never empty."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = _UPLOAD_SAFE_CHAR.sub("_", name).lstrip(".")
    return name or "upload"


def _open_unique_exclusive(name: str):
    """
    Create-and-open data/uploads/<name> (suffixed -1, -2, … on collision),
    returning ``(file_handle, path)``.

    REVIEW-3.0 F1: the file is opened with ``"xb"`` (exclusive create), so the
    FILESYSTEM enforces never-overwrite — a concurrent same-name upload loses
    the create race and simply retries the next suffix. Never replace this
    with an exists()-check + ``"wb"`` (that was the race).
    """
    base = _uploads_dir()
    stem, dot, ext = name.partition(".")
    for i in range(1000):
        if i == 0:
            candidate = base / name
        else:
            candidate = base / (f"{stem}-{i}{dot}{ext}" if dot else f"{stem}-{i}")
        try:
            return open(candidate, "xb"), candidate
        except FileExistsError:
            continue
    raise HTTPException(status_code=409, detail="Too many files with this name.")


@router.post("/files/upload", summary="Upload a file to data/uploads/ (M29.3)")
async def files_upload(file: UploadFile) -> dict[str, Any]:
    """
    Save an uploaded file under data/uploads/ (allowlisted read/write in the
    shipped config, so the existing /files/read machinery serves it).

    The name is fully sanitized server-side; content is opaque bytes (never
    executed or parsed); 10 MB cap enforced while streaming (partial file
    removed on breach); collisions get a unique suffix.
    """
    name = _sanitize_upload_name(file.filename)

    def _save() -> dict[str, Any]:
        _uploads_dir().mkdir(parents=True, exist_ok=True)
        fh, target = _open_unique_exclusive(name)
        written = 0
        try:
            with fh:
                while True:
                    chunk = file.file.read(64 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > _UPLOAD_MAX_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"File too large (max {_UPLOAD_MAX_BYTES // (1024 * 1024)} MB).",
                        )
                    fh.write(chunk)
        except HTTPException:
            target.unlink(missing_ok=True)  # no partial files on breach
            raise
        if written == 0:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="Empty upload.")
        return {
            "uploaded": True,
            "name": target.name,
            "path": f"data/uploads/{target.name}",
            "bytes": written,
        }

    result = await asyncio.to_thread(_save)
    main.write_ops_event(
        event="file_upload",
        outcome="success",
        detail={"name": result["name"], "bytes": result["bytes"]},
    )
    return result


@router.get("/files/uploads", summary="List uploaded files (M29.3)")
async def files_uploads_list() -> list[dict[str, Any]]:
    """Uploads newest-first: name, relative path, size, mtime."""

    def _list() -> list[dict[str, Any]]:
        base = _uploads_dir()
        if not base.exists():
            return []
        entries = [
            {
                "name": p.name,
                "path": f"data/uploads/{p.name}",
                "bytes": p.stat().st_size,
                "mtime": p.stat().st_mtime,
            }
            for p in base.iterdir()
            if p.is_file()
        ]
        return sorted(entries, key=lambda e: e["mtime"], reverse=True)

    return await asyncio.to_thread(_list)
