"""
app/routers/backup.py — backup HTTP routes (M26.18, split from main.py).

Handlers reference app state/singletons/tunables through ``main.`` (module-level
``import main`` below). main.py reloads these router modules as it assembles the
app, so the reference always resolves to the live main — see app/__init__.py.
Do NOT convert ``main.X`` lookups into ``from main import X`` (that captures a
stale module across the test suite's per-test main re-import).
"""

from __future__ import annotations

import asyncio
import secrets
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from core.config import APP_ROOT

from app.models import (
    BackupExportRequest, BackupRestoreRequest,
)

import main  # noqa: E402  — call-time-safe via reload in main.py; see docstring

router = APIRouter()


@router.get("/backup/exports", summary="List all backup exports")
async def backup_list_exports() -> list[dict[str, Any]]:
    """Return metadata for every backup zip in data/exports/."""
    bm = main._require_backup()
    # M26.14: per-zip metadata reads are disk-bound — run off the loop.
    return await asyncio.to_thread(bm.list_exports)


@router.post("/backup/exports", summary="Create a new backup export")
async def backup_create_export(body: BackupExportRequest) -> dict[str, Any]:
    """
    Create a zip backup of profiles/ and config/ (optionally audit/ and data/).

    Returns the filename, relative path, and file count of the new zip.
    """
    bm = main._require_backup()

    def _create() -> dict[str, Any]:
        # M26.14: zipping whole trees + re-reading the manifest is heavy disk
        # work — the entire job runs in one worker thread, off the loop. No
        # artificial deadline: a large export legitimately takes a while and a
        # timeout couldn't cancel the thread anyway.
        zip_path = bm.create_export(
            include_audit=body.include_audit,
            include_data=body.include_data,
        )
        import zipfile as _zf
        import json as _json  # noqa: PLC0415
        try:
            with _zf.ZipFile(zip_path, "r") as z:
                manifest = _json.loads(z.read("athena_backup_manifest.json"))
            file_count = manifest.get("file_count", 0)
        except Exception:  # noqa: BLE001
            file_count = 0
        return {
            "created": True,
            "filename": zip_path.name,
            "path": str(zip_path.relative_to(APP_ROOT)),
            "file_count": file_count,
        }

    return await asyncio.to_thread(_create)


@router.get("/backup/exports/{filename}/inspect", summary="Inspect a backup zip manifest")
async def backup_inspect(filename: str) -> dict[str, Any]:
    """Read and return the manifest from the named backup zip."""
    bm = main._require_backup()
    # M26.16: route through the same traversal guard as diff/download/delete —
    # inspect was the one exports route building the path from the raw param.
    zip_path = main._safe_export_path(filename)
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail=f"Backup not found: {filename}")
    # M26.14: zip read runs off the loop.
    return await asyncio.to_thread(bm.inspect_backup, zip_path)


@router.get("/backup/exports/{filename}/diff", summary="Dry-run diff for a backup restore")
async def backup_diff(filename: str) -> dict[str, Any]:
    """
    Return a diff of what would change if this zip were restored.

    No files are written. Safe to call anytime.
    Also generates a short-lived diff_token (TTL: 300s) which is required
    by POST /backup/restore with confirm=True.
    """
    bm = main._require_backup()
    zip_path = main._safe_export_path(filename)
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail=f"Backup not found: {filename}")
    # M26.14: whole-zip dry-run diff is disk-bound — run off the loop.
    result = await asyncio.to_thread(bm.diff_restore, zip_path)
    # Generate a single-use token, bound to this filename, for the confirm restore.
    token = secrets.token_urlsafe(16)
    main._restore_diff_tokens[token] = (filename, time.monotonic() + 300)
    result["diff_token"] = token
    return result


@router.get("/backup/exports/{filename}", summary="Download a backup zip")
async def backup_download(filename: str) -> FileResponse:
    """Stream the named backup zip as a file download."""
    zip_path = main._safe_export_path(filename)
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail=f"Backup not found: {filename}")
    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/backup/exports/{filename}", summary="Delete a backup zip")
async def backup_delete(filename: str) -> dict[str, Any]:
    """Delete the named backup zip from data/exports/."""
    bm = main._require_backup()
    zip_path = main._safe_export_path(filename)
    deleted = bm.delete_export(zip_path)
    return {"deleted": deleted}


@router.post("/backup/restore", summary="Restore from a backup zip")
async def backup_restore(body: BackupRestoreRequest) -> dict[str, Any]:
    """
    Restore from a backup zip.

    With confirm=false (default): returns a dry-run diff — no files changed.
    With confirm=true: requires a valid diff_token from GET /backup/exports/{filename}/diff;
      stages overwritten files then extracts the zip.
    """
    # Sweep expired tokens
    now = time.monotonic()
    expired = [k for k, (_fn, exp) in list(main._restore_diff_tokens.items()) if exp <= now]
    for k in expired:
        main._restore_diff_tokens.pop(k, None)

    bm = main._require_backup()
    zip_path = main._safe_export_path(body.zip_filename)
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail=f"Backup not found: {body.zip_filename}")

    # Token check only applies when confirm=True
    if body.confirm:
        token = body.diff_token
        entry = main._restore_diff_tokens.get(token) if token else None
        if entry is None or entry[1] <= time.monotonic():
            raise HTTPException(
                status_code=409,
                detail=(
                    f"A valid diff_token is required before confirm=True. "
                    f"Call GET /backup/exports/{body.zip_filename}/diff first to obtain one."
                ),
            )
        # M26.7: the token must have been issued for THIS backup.
        if entry[0] != body.zip_filename:
            raise HTTPException(
                status_code=409,
                detail=(
                    "diff_token was not issued for this backup. "
                    f"Call GET /backup/exports/{body.zip_filename}/diff to obtain a matching token."
                ),
            )

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                bm.restore_backup, zip_path, body.confirm, body.force
            ),
            timeout=60,
        )
    except asyncio.TimeoutError:
        main.write_ops_event(
            event="restore_confirm",
            outcome="failure",
            detail={"zip_filename": body.zip_filename, "error": "timed out after 60s"},
        )
        raise HTTPException(
            status_code=504,
            detail="Operation timed out after 60s. The server may be busy or the remote service is not responding.",
        ) from None
    except Exception as exc:
        if body.confirm:
            main.write_ops_event(
                event="restore_confirm",
                outcome="failure",
                detail={"zip_filename": body.zip_filename, "error": str(exc)},
            )
        raise

    if body.confirm:
        # Consume the token (single-use)
        main._restore_diff_tokens.pop(body.diff_token, None)  # type: ignore[arg-type]
        main.write_ops_event(
            event="restore_confirm",
            outcome="success",
            detail={
                "zip_filename": body.zip_filename,
                "added": result.get("added", 0),
                "overwritten": result.get("overwritten", 0),
            },
        )

    return result

