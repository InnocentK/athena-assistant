"""
app/routers/dav_status.py — dav_status HTTP routes (M26.18, split from main.py).

Handlers reference app state/singletons/tunables through ``main.`` (module-level
``import main`` below). main.py reloads these router modules as it assembles the
app, so the reference always resolves to the live main — see app/__init__.py.
Do NOT convert ``main.X`` lookups into ``from main import X`` (that captures a
stale module across the test suite's per-test main re-import).
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from dav_status.store import get_status_store as _get_dav_status


import main  # noqa: E402  — call-time-safe via reload in main.py; see docstring

router = APIRouter()


@router.get("/status/dav", summary="DAV integrations health overview")
async def status_dav_all() -> dict[str, Any]:
    """
    Return status summary for all three DAV integrations (caldav, carddav, nextcloud).

    Always returns 200, even when integrations are disabled.
    Status is updated in memory on each API call to the integration.
    """
    return _get_dav_status().get_all()


@router.get("/status/dav/{integration}", summary="Single DAV integration status")
async def status_dav_single(integration: str) -> dict[str, Any]:
    """
    Return detailed status for one DAV integration.

    integration must be one of: caldav, carddav, nextcloud.
    Returns 404 if the integration name is unrecognised.
    """
    _valid = ("caldav", "carddav", "nextcloud")
    if integration not in _valid:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown integration: {integration!r}. Must be one of {_valid}.",
        )
    return _get_dav_status().get(integration)


@router.post("/status/dav/{integration}/check", summary="On-demand DAV connection check")
async def check_dav_integration(integration: str) -> dict[str, Any]:
    """
    Perform an on-demand connection check for the specified DAV integration.

    Requires the integration to be enabled (returns 503 if not configured).
    Returns the check result plus the updated status record.
    """
    # Each client type exposes check_connection(); bind the method directly
    # (no shared `client` var — the three client types share no common base).
    if integration == "caldav":
        check_fn = main._require_caldav().check_connection
    elif integration == "carddav":
        check_fn = main._require_carddav().check_connection
    elif integration == "nextcloud":
        check_fn = main._require_nextcloud().check_connection
    else:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown integration: {integration!r}. Must be one of 'caldav', 'carddav', 'nextcloud'.",
        )
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(check_fn),
            timeout=30,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Operation timed out after 30s. The server may be busy or the remote service is not responding.",
        ) from None
    return {**result, "status": _get_dav_status().get(integration)}

