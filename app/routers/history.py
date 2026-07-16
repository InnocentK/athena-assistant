"""
app/routers/history.py — persistent-conversation routes (M29.1).

Handlers reference app state through ``main.`` (module-level ``import main``
below; main.py reloads router modules as it assembles the app — do NOT convert
to ``from main import X``). The store validates every conversation id against
``^[A-Za-z0-9_-]+$`` before building a path (traversal guard).
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

import main  # noqa: E402  — call-time-safe via reload in main.py; see docstring

router = APIRouter()


def _store():
    if main._history is None:
        raise HTTPException(status_code=503, detail="History is not available.")
    return main._history


@router.get("/history/conversations", summary="List persisted conversations (M29.1)")
async def history_list() -> list[dict[str, Any]]:
    """Newest-first summaries: id, started_at, turn count, first-message preview."""
    return await asyncio.to_thread(_store().list_conversations)


@router.get("/history/conversations/{conversation_id}", summary="Read one conversation")
async def history_read(conversation_id: str) -> dict[str, Any]:
    """All persisted turns of one conversation."""
    store = _store()
    try:
        turns = await asyncio.to_thread(store.read, conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation id.") from None
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Conversation not found: {conversation_id}"
        ) from None
    return {"id": conversation_id, "turns": turns}


@router.delete("/history/conversations/{conversation_id}", summary="Delete one conversation")
async def history_delete(conversation_id: str) -> dict[str, Any]:
    """Delete a persisted conversation file."""
    store = _store()
    try:
        deleted = await asyncio.to_thread(store.delete, conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation id.") from None
    if deleted:
        main.write_ops_event(
            event="history_delete", outcome="success", detail={"id": conversation_id}
        )
    return {"deleted": deleted}
