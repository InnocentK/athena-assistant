"""
app/routers/saved.py — saved HTTP routes (M26.18, split from main.py).

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

from core.logger import logger
from providers.base import Message

from app.models import (
    SavedActionCreate,
    SavedActionUpdate, SavedSearchCreate, SavedSearchUpdate,
)

import main  # noqa: E402  — call-time-safe via reload in main.py; see docstring

router = APIRouter()


@router.get("/saved/searches", summary="List saved searches")
async def saved_searches_list() -> list[dict[str, Any]]:
    """List saved searches. In v1 these are local file searches (target: files)."""
    return main._require_saved().list_searches()


@router.post("/saved/searches", summary="Create a saved file search (target must be 'files')")
async def saved_searches_create(body: SavedSearchCreate) -> dict[str, Any]:
    """
    Create a saved search. v1 supports only file searches: `target` must be
    'files' (the default). `query` is a glob pattern; `path` optionally scopes
    it to an allowlisted root. Web searches are not supported in this milestone.
    """
    target = (body.target or "files").strip().lower()
    if target != "files":
        raise HTTPException(
            status_code=400,
            detail="Only target 'files' is supported in this version; saved web searches are not available.",
        )
    item = main._require_saved().add_search(name=body.name, query=body.query, target="files", path=body.path)
    if not item:
        raise HTTPException(status_code=500, detail="Failed to create saved search.")
    return item


@router.get("/saved/searches/{item_id}", summary="Get a saved search")
async def saved_searches_get(item_id: str) -> dict[str, Any]:
    item = main._require_saved().get_search(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Saved search not found: {item_id}")
    return item


@router.patch("/saved/searches/{item_id}", summary="Update a saved search")
async def saved_searches_update(item_id: str, body: SavedSearchUpdate) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.query is not None:
        updates["query"] = body.query
    if body.path is not None:
        updates["path"] = body.path
    if body.target is not None:
        if body.target.strip().lower() != "files":
            raise HTTPException(
                status_code=400,
                detail="Only target 'files' is supported in this version.",
            )
        updates["target"] = "files"
    result = main._require_saved().update_search(item_id, updates)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Saved search not found: {item_id}")
    return result


@router.delete("/saved/searches/{item_id}", summary="Delete a saved search")
async def saved_searches_delete(item_id: str) -> dict[str, bool]:
    if not main._require_saved().delete_search(item_id):
        raise HTTPException(status_code=404, detail=f"Saved search not found: {item_id}")
    return {"deleted": True}


@router.post("/saved/searches/{item_id}/run", summary="Run a saved file search (target must be 'files')")
async def saved_searches_run(item_id: str) -> dict[str, Any]:
    """
    Run a saved search. Only `target: files` is runnable in this milestone: the
    stored glob `query` is executed via FileManager across allowlisted,
    search-permitted paths (optionally scoped to the saved `path`). Any other
    target returns 400. Web searches are not runnable here.
    """
    item = main._require_saved().get_search(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Saved search not found: {item_id}")
    target = (item.get("target") or "files").lower()
    if target != "files":
        raise HTTPException(
            status_code=400,
            detail=f"Run is not supported for target '{target}' in this version (only 'files').",
        )
    fm = main._require_files()
    path = item.get("path")
    allowed_roots = [path] if path else None
    results = fm.search_files(item.get("query", ""), allowed_roots=allowed_roots)
    return {"id": item_id, "target": "files", "query": item.get("query", ""), "results": results}


@router.get("/saved/actions", summary="List saved actions")
async def saved_actions_list() -> list[dict[str, Any]]:
    return main._require_saved().list_actions()


@router.post("/saved/actions", summary="Create a saved action (a reusable prompt)")
async def saved_actions_create(body: SavedActionCreate) -> dict[str, Any]:
    """Create a saved action: a reusable prompt with optional mode/provider overrides."""
    # M26.8: validate the optional routing overrides so a typo fails loudly here
    # rather than silently misrouting (or being ignored) at run time.
    if body.mode is not None:
        main._validate_routing_mode(body.mode)
    if body.provider is not None and body.provider not in await main._known_provider_names():
        raise HTTPException(status_code=400, detail=f"Unknown provider: {body.provider}.")
    item = main._require_saved().add_action(
        name=body.name, prompt=body.prompt, mode=body.mode, provider=body.provider
    )
    if not item:
        raise HTTPException(status_code=500, detail="Failed to create saved action.")
    return item


@router.get("/saved/actions/{item_id}", summary="Get a saved action")
async def saved_actions_get(item_id: str) -> dict[str, Any]:
    item = main._require_saved().get_action(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Saved action not found: {item_id}")
    return item


@router.patch("/saved/actions/{item_id}", summary="Update a saved action")
async def saved_actions_update(item_id: str, body: SavedActionUpdate) -> dict[str, Any]:
    # M26.8: validate the optional routing overrides before persisting.
    if body.mode is not None:
        main._validate_routing_mode(body.mode)
    if body.provider is not None and body.provider not in await main._known_provider_names():
        raise HTTPException(status_code=400, detail=f"Unknown provider: {body.provider}.")
    updates: dict[str, Any] = {}
    for field in ("name", "prompt", "mode", "provider"):
        val = getattr(body, field)
        if val is not None:
            updates[field] = val
    result = main._require_saved().update_action(item_id, updates)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Saved action not found: {item_id}")
    return result


@router.delete("/saved/actions/{item_id}", summary="Delete a saved action")
async def saved_actions_delete(item_id: str) -> dict[str, bool]:
    if not main._require_saved().delete_action(item_id):
        raise HTTPException(status_code=404, detail=f"Saved action not found: {item_id}")
    return {"deleted": True}


@router.post("/saved/actions/{item_id}/run", summary="Run a saved action's prompt through the active provider")
async def saved_actions_run(item_id: str) -> dict[str, Any]:
    """
    Run a saved action: send its stored prompt through the active provider chain
    (the same ProviderRouter seam as /chat), applying the action's optional
    mode/provider overrides. Auto-extraction is intentionally NOT run here.
    """
    item = main._require_saved().get_action(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Saved action not found: {item_id}")
    if main._router is None:
        raise HTTPException(status_code=503, detail="ProviderRouter is not available. Check startup logs.")

    # Apply per-run routing overrides without mutating the loaded profile.
    profile_config = dict(main._profile_data)
    routing = dict(profile_config.get("routing", {}) or {})
    if item.get("mode"):
        routing["mode"] = item["mode"]
    if item.get("provider"):
        routing["preferred_provider"] = item["provider"]
    profile_config["routing"] = routing

    messages = [Message(role="user", content=item.get("prompt", ""))]
    system_prompt = profile_config.get("system_prompt") or None
    # M26.5: same off-loop wrapping and bounded request time as /chat.
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(main._router.route, messages, system_prompt, profile_config),
            timeout=main._ROUTE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.error("Router timed out after %ss (saved action %s)", main._ROUTE_TIMEOUT, item_id)
        return {
            "id": item_id,
            "response": "The request timed out.",
            "provider": "none",
            "model": None,
            "success": False,
        }
    return {
        "id": item_id,
        "response": response.content,
        "provider": response.provider_name,
        "model": response.model,
        "success": response.success,
    }

