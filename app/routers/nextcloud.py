"""
app/routers/nextcloud.py — nextcloud HTTP routes (M26.18, split from main.py).

Handlers reference app state/singletons/tunables through ``main.`` (module-level
``import main`` below). main.py reloads these router modules as it assembles the
app, so the reference always resolves to the live main — see app/__init__.py.
Do NOT convert ``main.X`` lookups into ``from main import X`` (that captures a
stale module across the test suite's per-test main re-import).
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from nextcloud_integration.client import (
    NextcloudConnectionError,
)


import main  # noqa: E402  — call-time-safe via reload in main.py; see docstring

router = APIRouter()


@router.get("/nextcloud/ping", summary="Check Nextcloud reachability")
async def nextcloud_ping() -> dict[str, Any]:
    """
    Ping the Nextcloud server and return reachability status and version.

    Returns {reachable, version} on success or {reachable: false, error} on failure.
    Requires Nextcloud to be enabled in config/nextcloud.yaml.
    """
    client = main._require_nextcloud()
    # M26.5: remote ping runs off the loop; preserve its status-return contract
    # (ping reports reachability rather than raising) on timeout.
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(client.ping),
            timeout=main._DAV_READ_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return {"reachable": False, "error": f"timed out after {main._DAV_READ_TIMEOUT}s"}


@router.get("/nextcloud/user", summary="Get Nextcloud current user info")
async def nextcloud_user() -> dict[str, Any]:
    """
    Return info about the authenticated Nextcloud user.

    Returns {id, display_name, email, quota_used, quota_total}.
    """
    client = main._require_nextcloud()
    try:
        # M26.5: remote read runs off the event loop with a bounded time.
        return await asyncio.wait_for(
            asyncio.to_thread(client.get_user_info),
            timeout=main._DAV_READ_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Nextcloud server did not respond in time.") from None
    except NextcloudConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/nextcloud/files", summary="List files/folders via Nextcloud WebDAV")
async def nextcloud_list_files(
    path: str = Query(default="/", description="WebDAV path to list (default: root)"),
) -> list[dict[str, Any]]:
    """
    List files and folders at the given path using WebDAV PROPFIND.

    Each entry has: name, path, type (file|folder), size, last_modified, content_type.
    This is a read-only operation.
    """
    client = main._require_nextcloud()
    try:
        # M26.5: remote read runs off the event loop with a bounded time.
        return await asyncio.wait_for(
            asyncio.to_thread(client.list_files, path),
            timeout=main._DAV_READ_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Nextcloud server did not respond in time.") from None
    except NextcloudConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/nextcloud/files/read", summary="Read a text file from Nextcloud (≤2MB)")
async def nextcloud_read_file(
    path: str = Query(..., description="WebDAV path to the file"),
) -> dict[str, Any]:
    """
    Read the content of a Nextcloud file.

    Returns {path, content, content_type, size} for text files.
    Binary files and files >2MB return content: null with a note field.
    This is a read-only operation.
    """
    client = main._require_nextcloud()
    try:
        # M26.5: remote read runs off the event loop with a bounded time.
        return await asyncio.wait_for(
            asyncio.to_thread(client.read_file, path),
            timeout=main._DAV_READ_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Nextcloud server did not respond in time.") from None
    except NextcloudConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/nextcloud/files/search", summary="Search Nextcloud files by name")
async def nextcloud_search_files(
    query: str = Query(..., description="Search term to match against file names"),
    path: str = Query(default="/", description="Scope path for the search (default: root)"),
) -> list[dict[str, Any]]:
    """
    Search for files whose names contain the given query string.

    Uses Nextcloud DASL SEARCH; falls back to local filtering if DASL is unavailable.
    Returns same shape as /nextcloud/files. Read-only.
    """
    client = main._require_nextcloud()
    try:
        # M26.5: remote read runs off the event loop with a bounded time.
        return await asyncio.wait_for(
            asyncio.to_thread(client.search_files, query, path),
            timeout=main._DAV_READ_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Nextcloud server did not respond in time.") from None
    except NextcloudConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/nextcloud/notes", summary="List Nextcloud Notes (requires Notes app)")
async def nextcloud_list_notes() -> list[dict[str, Any]]:
    """
    List all notes from the Nextcloud Notes app (content excluded).

    Returns list of {id, title, category, modified, favorite}.
    Returns [] if the Notes app is not installed. Read-only.
    """
    client = main._require_nextcloud()
    try:
        # M26.5: remote read runs off the event loop with a bounded time.
        return await asyncio.wait_for(
            asyncio.to_thread(client.list_notes),
            timeout=main._DAV_READ_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Nextcloud server did not respond in time.") from None
    except NextcloudConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/nextcloud/notes/{note_id}", summary="Get a single Nextcloud Note by ID")
async def nextcloud_get_note(note_id: int) -> dict[str, Any]:
    """
    Retrieve a single Nextcloud Note including its content.

    Returns {id, title, category, content, modified, favorite}. Read-only.
    """
    client = main._require_nextcloud()
    try:
        # M26.5: remote read runs off the event loop with a bounded time.
        return await asyncio.wait_for(
            asyncio.to_thread(client.get_note, note_id),
            timeout=main._DAV_READ_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Nextcloud server did not respond in time.") from None
    except NextcloudConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/nextcloud/activity", summary="List recent Nextcloud activity")
async def nextcloud_activity(
    limit: int = Query(default=20, ge=1, le=100, description="Number of activity items to return"),
) -> list[dict[str, Any]]:
    """
    Return recent activity entries from the Nextcloud Activity app.

    Each entry has: activity_id, type, subject, message, object_type, object_name, timestamp.
    Returns [] if the Activity app is not installed. Read-only.
    """
    client = main._require_nextcloud()
    try:
        # M26.5: remote read runs off the event loop with a bounded time.
        return await asyncio.wait_for(
            asyncio.to_thread(client.list_recent_activity, limit),
            timeout=main._DAV_READ_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Nextcloud server did not respond in time.") from None
    except NextcloudConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

