"""
app/routers/portable.py — Portable Profiles HTTP routes (M28).

Handlers reference app state through ``main.`` (module-level ``import main``
below). main.py reloads router modules as it assembles the app — do NOT convert
``main.X`` lookups into ``from main import X`` (see app/__init__.py).

Portable bundles are the host-agnostic, secret-free identity snapshots built by
``backup/portable.py``. Export is allowlist-built and leak-guarded: a striplist
hit is a 409, never a warning.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backup.portable import PortableExportError, PortableProfileManager
from core.config import APP_ROOT, active_profile_dir

from app.models import PortableExportRequest

import main  # noqa: E402  — call-time-safe via reload in main.py; see docstring

router = APIRouter()


def _manager() -> PortableProfileManager:
    return PortableProfileManager(
        APP_ROOT, active_profile_dir(), app_version=main.app.version
    )


@router.get("/portable/preview", summary="Preview a portable-profile export (review step)")
async def portable_preview() -> dict[str, Any]:
    """
    What WOULD be exported: the sanitized (allowlist) profile fields plus every
    memory entry (id/category/key), so specific entries can be excluded via
    POST /portable/exports. No files are written.
    """
    pm = _manager()
    return await asyncio.to_thread(pm.preview)


@router.post("/portable/exports", summary="Create a portable identity bundle")
async def portable_create(body: PortableExportRequest) -> dict[str, Any]:
    """
    Build the snapshot bundle (profile + memory, secrets/host-data stripped).

    409 when the leak guard trips — a striplist violation must never emit a
    bundle. ``exclude_ids`` drops specific memory entries (the review step).
    """
    pm = _manager()

    def _create() -> dict[str, Any]:
        zip_path, manifest = pm.create_export(exclude_ids=set(body.exclude_ids))
        return {
            "created": True,
            "filename": zip_path.name,
            "path": str(zip_path.relative_to(APP_ROOT)),
            "profile_name": manifest["profile_name"],
            "memory_entry_count": manifest["memory_entry_count"],
            "memory_entries_excluded": manifest["memory_entries_excluded"],
            "warnings": manifest["warnings"],
            "snapshot_note": manifest["snapshot_note"],
        }

    try:
        result = await asyncio.to_thread(_create)
    except PortableExportError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    main.write_ops_event(
        event="portable_export",
        outcome="success",
        detail={
            "filename": result["filename"],
            "memory_entry_count": result["memory_entry_count"],
        },
    )
    return result


@router.get("/portable/exports", summary="List portable bundles")
async def portable_list() -> list[dict[str, Any]]:
    """Portable bundles in data/exports/ (full backups are not listed here)."""
    pm = _manager()
    return await asyncio.to_thread(pm.list_exports)


@router.get("/portable/exports/{filename}", summary="Download a portable bundle")
async def portable_download(filename: str) -> FileResponse:
    """Stream the named portable bundle zip."""
    zip_path = main._safe_export_path(filename)
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail=f"Bundle not found: {filename}")
    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/portable/exports/{filename}", summary="Delete a portable bundle")
async def portable_delete(filename: str) -> dict[str, Any]:
    """Delete the named portable bundle from data/exports/."""
    zip_path = main._safe_export_path(filename)
    if not zip_path.exists():
        return {"deleted": False}
    zip_path.unlink()
    return {"deleted": True}
