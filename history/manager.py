"""
history/manager.py — append-only conversation store (M29.1).

One JSONL file per conversation under ``profiles/<name>/history/``:
    {"ts": "...", "role": "user", "content": "..."}
    {"ts": "...", "role": "assistant", "content": "...", "provider": "...", ...}

Design contract:
- Conversation ids match ``^[A-Za-z0-9_-]+$`` and are validated BEFORE any
  path is built — no caller can escape the history directory (write-safety
  pattern, M26.7).
- All access holds the per-store lock: ``/chat`` records from
  ``asyncio.to_thread`` worker threads (M26.16 discipline).
- Writes are line-appends; a malformed line in a file is skipped on read
  rather than failing the conversation.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_PREVIEW_LEN = 80


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class ConversationStore:
    """Per-profile persistent conversation history."""

    def __init__(self, profile_dir: Path) -> None:
        self._dir = profile_dir / "history"
        self._lock = threading.Lock()

    # ------------------------------------------------------------------

    def _path(self, conversation_id: str) -> Path:
        """Validated id → file path. Raises ValueError on a bad id (the guard
        every public method funnels through — never build paths elsewhere)."""
        if not _ID_RE.match(conversation_id):
            raise ValueError(f"Invalid conversation id: {conversation_id!r}")
        return self._dir / f"{conversation_id}.jsonl"

    # ------------------------------------------------------------------

    def new_conversation(self) -> str:
        """Create a new (empty) conversation and return its id."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        conv_id = f"{stamp}-{secrets.token_hex(2)}"
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._path(conv_id).touch()
        return conv_id

    def append_turn(
        self,
        conversation_id: str,
        role: str,
        content: str,
        meta: dict[str, Any] | None = None,
    ) -> None:
        """Append one turn. Raises on invalid id; IO errors propagate to the
        caller (which, via core.chat_turn.record_turn, swallows them)."""
        path = self._path(conversation_id)
        line: dict[str, Any] = {"ts": _now_iso(), "role": role, "content": content}
        if meta:
            line.update(meta)
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")

    def read(self, conversation_id: str) -> list[dict[str, Any]]:
        """All turns of one conversation (malformed lines skipped)."""
        path = self._path(conversation_id)
        with self._lock:
            if not path.exists():
                raise FileNotFoundError(conversation_id)
            raw = path.read_text(encoding="utf-8")
        turns: list[dict[str, Any]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    turns.append(item)
            except Exception:  # noqa: BLE001 — one bad line must not kill the file
                continue
        return turns

    def list_conversations(self) -> list[dict[str, Any]]:
        """Newest-first summaries: id, started_at, turn count, preview."""
        with self._lock:
            if not self._dir.exists():
                return []
            files = sorted(self._dir.glob("*.jsonl"), reverse=True)
        out: list[dict[str, Any]] = []
        for path in files:
            conv_id = path.stem
            if not _ID_RE.match(conv_id):
                continue
            try:
                turns = self.read(conv_id)
            except Exception:  # noqa: BLE001
                continue
            preview = next(
                (t.get("content", "") for t in turns if t.get("role") == "user"), ""
            )
            out.append(
                {
                    "id": conv_id,
                    "started_at": turns[0].get("ts") if turns else None,
                    "turns": len(turns),
                    "preview": str(preview)[:_PREVIEW_LEN],
                }
            )
        return out

    def delete(self, conversation_id: str) -> bool:
        """Delete one conversation file. False if it didn't exist."""
        path = self._path(conversation_id)
        with self._lock:
            if not path.exists():
                return False
            path.unlink()
            return True
