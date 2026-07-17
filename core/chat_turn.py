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

import re
from typing import Any, Iterable

from core.logger import logger
from providers.base import Message

# ---------------------------------------------------------------------------
# Attachment inlining (M30.5)
# ---------------------------------------------------------------------------

# The exact whole-line form the upload UI inserts (M29.3). Anchored so prose
# that merely mentions the phrase mid-sentence is never matched.
_ATTACHMENT_RE = re.compile(r"^\[Attached file: (.+)\]$", re.MULTILINE)

# Conservative text-only allowlist — images/binaries stay reference-only
# until a vision path exists (CLAUDE.md Later).
_INLINE_EXTENSIONS = {
    "txt", "md", "markdown", "xml", "json", "yaml", "yml", "csv", "tsv",
    "toml", "ini", "cfg", "log", "py", "js", "ts", "sh", "html", "css", "sql",
}
_INLINE_MAX_BYTES = 32 * 1024  # per attachment
_INLINE_MAX_FILES = 3          # per message — bounds worst-case prompt growth


def inline_attachments(text: str) -> str:
    """
    Expand ``[Attached file: <path>]`` references with the file's content
    (M30.5) — for the PROVIDER-BOUND message only; callers record the
    original text. Reads go through FileManager (the allowlist governs, like
    every read). Best-effort by contract: any failure — missing file, not
    allowlisted, non-text extension, read error — leaves that reference
    byte-identical. Never raises.
    """
    if "[Attached file: " not in text:  # fast path — almost every message
        return text

    try:
        from files.manager import FileManager  # noqa: PLC0415 — lazy, CLI-safe

        fm = FileManager()
    except Exception as exc:  # noqa: BLE001 — no manager, no inlining
        logger.debug("inline_attachments: FileManager unavailable: %s", exc)
        return text

    inlined = 0

    def _expand(match: "re.Match[str]") -> str:
        nonlocal inlined
        original = match.group(0)
        path = match.group(1).strip()
        if inlined >= _INLINE_MAX_FILES:
            return original
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if ext not in _INLINE_EXTENSIONS:
            return original
        try:
            result = fm.read_file(path)
        except Exception as exc:  # noqa: BLE001 — allowlist/IO: skip, never fail
            logger.debug("inline_attachments: skipped %s: %s", path, exc)
            return original
        content = str(result.get("content", ""))
        truncated = bool(result.get("truncated"))
        if len(content.encode("utf-8", errors="replace")) > _INLINE_MAX_BYTES:
            content = content.encode("utf-8", errors="replace")[
                :_INLINE_MAX_BYTES
            ].decode("utf-8", errors="replace")
            truncated = True
        inlined += 1
        marker = "\n[...truncated at 32 KB...]" if truncated else ""
        return (
            f"{original}\n"
            f"--- Attached file content: {path} ---\n"
            f"{content}{marker}\n"
            f"--- End of attached file ---"
        )

    return _ATTACHMENT_RE.sub(_expand, text)


def build_turn_messages(
    history: "Iterable[tuple[str, str]]", new_message: str
) -> list[Message]:
    """
    Assemble the full message list for one turn: prior history (as
    ``(role, content)`` pairs, role "user" | "assistant") followed by the new
    user message. Both surfaces MUST build their turns through this so the
    assembly (and, from M29.1, its recording) stays identical.

    M30.5: attachment references in the NEW message are expanded with file
    content for the provider-bound copy — callers record/display the
    original text (history and exports keep the reference form). Replayed
    history turns are deliberately NOT re-inlined (cost bound; the content
    was in context on the turn that attached it).
    """
    messages: list[Message] = [
        Message(role=role, content=content) for role, content in history
    ]
    messages.append(Message(role="user", content=inline_attachments(new_message)))
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
