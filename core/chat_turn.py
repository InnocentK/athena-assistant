"""
core/chat_turn.py — the shared chat-turn helpers (M29.0).

ONE code path for the pieces of a chat turn that the web ``/chat`` handler
(`app/routers/core.py`) and the CLI (`cli/main.py`) previously each assembled
on their own: message-list building, system-prompt extraction, and the
best-effort memory auto-extraction semantics. The M29 Conversations epic and
M30 streaming hang their seams here — persistent turn recording (M29.1) and
streamed assembly (M30) get built once, for both surfaces.

Deliberately NOT here: the surfaces' execution models. The HTTP path wraps
routing in ``asyncio.wait_for(to_thread(...))`` for loop responsiveness
(M26.5) and the CLI drives a live-status spinner (M27.0) — those stay at the
call sites. This module is synchronous, FastAPI-free, and side-effect-free
except for `extract_memory`.
"""

from __future__ import annotations

from typing import Any, Iterable

from core.logger import logger
from providers.base import Message


def build_turn_messages(
    history: "Iterable[tuple[str, str]]", new_message: str
) -> list[Message]:
    """
    Assemble the full message list for one turn: prior history (as
    ``(role, content)`` pairs, role "user" | "assistant") followed by the new
    user message. Both surfaces MUST build their turns through this so the
    assembly (and, from M29.1, its recording) stays identical.
    """
    messages: list[Message] = [
        Message(role=role, content=content) for role, content in history
    ]
    messages.append(Message(role="user", content=new_message))
    return messages


def system_prompt_from(profile: dict[str, Any]) -> str | None:
    """
    The system prompt exactly as both surfaces have always resolved it:
    a present-but-empty prompt is None (``or None``), so providers never
    receive an empty system turn.
    """
    return profile.get("system_prompt") or None


def record_turn(
    store: Any,
    conversation_id: str,
    role: str,
    content: str,
    meta: "dict[str, Any] | None" = None,
) -> bool:
    """
    Best-effort history recording (M29.1) — same contract as
    ``extract_memory``: a history write must NEVER fail an answered turn.
    Returns True iff the turn was recorded.
    """
    if store is None or not conversation_id:
        return False
    try:
        store.append_turn(conversation_id, role, content, meta)
        return True
    except Exception as exc:  # noqa: BLE001 — non-fatal by contract
        logger.warning("history record_turn failed (non-fatal): %s", exc)
        return False


def extract_memory(memory_mgr: Any, user_message: str, response_content: str) -> bool:
    """
    Best-effort memory auto-extraction — the SYNC core shared by both
    surfaces. Never raises: an answered turn must never fail because a YAML
    write hiccuped (M26 norm). Returns True iff extraction ran.

    Callers own their execution model: the HTTP handler wraps this in
    ``asyncio.wait_for(asyncio.to_thread(...), _AUTO_EXTRACT_TIMEOUT)``; the
    CLI calls it directly.
    """
    if memory_mgr is None:
        return False
    try:
        memory_mgr.auto_extract(user_message, response_content)
        return True
    except Exception as exc:  # noqa: BLE001 — non-fatal by contract
        logger.warning("auto_extract failed (non-fatal): %s", exc)
        return False
