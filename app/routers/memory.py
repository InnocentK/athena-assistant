"""
app/routers/memory.py — memory HTTP routes (M26.18, split from main.py).

Handlers reference app state/singletons/tunables through ``main.`` (module-level
``import main`` below). main.py reloads these router modules as it assembles the
app, so the reference always resolves to the live main — see app/__init__.py.
Do NOT convert ``main.X`` lookups into ``from main import X`` (that captures a
stale module across the test suite's per-test main re-import).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from memory.manager import CATEGORIES as MEMORY_CATEGORIES

from app.models import (
    MemoryCreateRequest,
    MemoryExtractRequest, MemoryUpdateRequest,
)

import main  # noqa: E402  — call-time-safe via reload in main.py; see docstring

router = APIRouter()


@router.get("/memory", summary="List all memories grouped by category")
async def memory_list() -> dict[str, list[dict[str, Any]]]:
    """
    Returns all memory entries grouped by category.

    Response shape: { "preferences": [...], "workflows": [...], ... }
    """
    mm = main._require_memory()
    return mm.all_memories()


@router.get("/memory/pending", summary="List the pending review queue")
async def memory_pending() -> list[dict[str, Any]]:
    """
    Returns all entries currently in the pending_review queue.

    Response shape: [{id, category, key, value, reason, source, created_at}, ...]
    """
    mm = main._require_memory()
    return mm.get_pending()


@router.post("/memory", summary="Create a memory entry manually")
async def memory_create(body: MemoryCreateRequest) -> dict[str, Any]:
    """
    Create a new memory entry directly in the specified category (no review queue).

    Returns the created entry dict.
    """
    mm = main._require_memory()
    # M26.7: validate the category against the known set before writing. Gives a
    # clean 400 (rather than the manager backstop's generic failure) and blocks
    # path-traversal attempts like category="../evil".
    if body.category not in MEMORY_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown category: {body.category!r}. Valid categories: {', '.join(MEMORY_CATEGORIES)}.",
        )
    entry = mm.add_memory(
        category=body.category,
        key=body.key,
        value=body.value,
        source="manual",
        notes=body.notes,
    )
    if not entry:
        raise HTTPException(status_code=500, detail="Failed to create memory entry.")
    return entry


@router.patch("/memory/{memory_id}", summary="Update a memory entry")
async def memory_update(memory_id: str, body: MemoryUpdateRequest) -> dict[str, Any]:
    """
    Update an existing memory entry identified by id.

    Searches across all categories.  Updatable fields: key, value, notes.
    Returns the updated entry or 404 if not found.
    """
    mm = main._require_memory()
    updates: dict[str, Any] = {}
    if body.key is not None:
        updates["key"] = body.key
    if body.value is not None:
        updates["value"] = body.value
    if body.notes is not None:
        updates["notes"] = body.notes

    result = mm.update_memory(memory_id, updates)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Memory id not found: {memory_id}")
    return result


@router.delete("/memory/{memory_id}", summary="Delete a memory entry")
async def memory_delete(memory_id: str) -> dict[str, bool]:
    """
    Delete a memory entry by id from any category or pending_review.

    Returns {"deleted": true} on success or 404 if not found.
    """
    mm = main._require_memory()
    deleted = mm.delete_memory(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Memory id not found: {memory_id}")
    main.write_ops_event(
        event="memory_delete",
        outcome="success",
        detail={"memory_id": memory_id},
    )
    return {"deleted": True}


@router.post(
    "/memory/pending/{memory_id}/approve",
    summary="Approve a pending memory entry",
)
async def memory_approve(memory_id: str) -> dict[str, Any]:
    """
    Move a pending_review entry to its target category with source="approved".

    Returns the approved entry or 404 if not found.
    """
    mm = main._require_memory()
    result = mm.approve_pending(memory_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Pending memory id not found: {memory_id}",
        )
    return result


@router.delete(
    "/memory/pending/{memory_id}",
    summary="Discard a pending memory entry",
)
async def memory_discard(memory_id: str) -> dict[str, bool]:
    """
    Discard a pending_review entry without saving it to any category.

    Returns {"discarded": true} or 404 if not found.
    """
    mm = main._require_memory()
    discarded = mm.discard_pending(memory_id)
    if not discarded:
        raise HTTPException(
            status_code=404,
            detail=f"Pending memory id not found: {memory_id}",
        )
    return {"discarded": True}


@router.post("/memory/extract", summary="Run auto-extraction on a message pair")
async def memory_extract(body: MemoryExtractRequest) -> list[dict[str, Any]]:
    """
    Run the conservative auto-extraction pass on a user/assistant message pair.

    Any detected candidates are added to pending_review.
    Returns the list of pending entries created (may be empty).
    """
    mm = main._require_memory()
    return mm.auto_extract(body.user_message, body.assistant_response)

