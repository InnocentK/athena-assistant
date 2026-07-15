"""
memory/manager.py — Local memory system for Athena Assistant (Milestone 4).

Manages YAML-backed flat-file memory organised by category inside the active
profile's memory/ directory.  All methods are defensively coded — exceptions
are caught, logged, and safe defaults returned so that a memory failure never
crashes the assistant.

Memory categories:
  preferences     — user preferences (date format, tone, tool choices)
  workflows       — recurring tasks and workflows
  operating_notes — active constraints, projects, ongoing context
  environment     — tool paths, system config, known endpoints
  facts           — explicitly approved important facts
  pending_review  — entries queued for human review (not a saved category)

Auto-extraction in Milestone 4 uses conservative regex pattern-matching only.
All auto-extracted candidates go to pending_review before being saved anywhere.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import functools
import threading

from core.loader import load_yaml, save_yaml
from core.logger import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CATEGORIES: list[str] = [
    "preferences",
    "workflows",
    "operating_notes",
    "environment",
    "facts",
]

PENDING_CATEGORY = "pending_review"
PENDING_LIST_KEY = "pending"

# M26.7: the only category-file stems that may ever be turned into a path.
# Every file path flows through _category_path, so this allowlist is the single
# chokepoint that prevents a caller-supplied category from escaping the memory
# dir (e.g. category="../evil" writing profiles/athena/evil.yaml).
_ALLOWED_CATEGORY_FILES = frozenset(CATEGORIES) | {PENDING_CATEGORY}

# Conservative auto-extraction patterns.
# Capturing groups are used to extract the matched value from user messages.
# Each pattern must be precise enough that false positives are rare.

PREFERENCE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"I prefer (.+)", re.IGNORECASE),
    re.compile(r"I like (.+)", re.IGNORECASE),
    re.compile(r"I always use (.+)", re.IGNORECASE),
    re.compile(r"please (?:always )?use (.+)", re.IGNORECASE),
    re.compile(r"use (.+) format", re.IGNORECASE),
    re.compile(r"I want (.+) (?:instead|always|by default)", re.IGNORECASE),
]

ENVIRONMENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"my (\w+) is (?:at |running at |on )?(.+)", re.IGNORECASE),
    re.compile(
        r"(?:the|our) (\w+) (?:server |instance )?is (?:at |running at )?(.+)",
        re.IGNORECASE,
    ),
    re.compile(r"I(?:'m| am) using (\w+)(?: version)? (.+)", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_id() -> str:
    """Generate a short memory ID using an 8-char UUID fragment."""
    return "mem_" + uuid.uuid4().hex[:8]


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string (no microseconds)."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _clean_value(raw: str) -> str:
    """Strip trailing punctuation and whitespace from a captured regex value."""
    return raw.strip().rstrip(".,;:!?")


# ---------------------------------------------------------------------------
# MemoryManager
# ---------------------------------------------------------------------------

def _locked(fn):
    """M26.16: serialise MemoryManager's YAML read-modify-write cycles.

    auto_extract runs in an asyncio.to_thread worker while approve/discard
    run on the event-loop thread and rewrite the same pending_review.yaml —
    unserialised, the last writer silently wins (or interleaves). RLock
    because methods nest (auto_extract → add_to_pending,
    approve_pending → add_memory).
    """

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)

    return wrapper


class MemoryManager:
    """
    Manages local YAML memory files for a single profile.

    Usage::

        mm = MemoryManager(profile_dir=Path("profiles/athena"), profile_config={})
        mm.add_memory("preferences", "date_format", "ISO 8601")
        pending = mm.get_pending()
    """

    def __init__(self, profile_dir: Path, profile_config: dict[str, Any]) -> None:
        self._profile_dir = Path(profile_dir)
        self._profile_config = profile_config
        self._lock = threading.RLock()  # M26.16 — see _locked
        logger.info(
            "MemoryManager initialised for profile dir: %s", self._profile_dir
        )

    # ------------------------------------------------------------------
    # Internal path helpers
    # ------------------------------------------------------------------

    @property
    def _memory_dir(self) -> Path:
        """Return the memory/ directory for the active profile."""
        return self._profile_dir / "memory"

    def _category_path(self, category: str) -> Path:
        """
        Return the YAML file path for a given category name.

        M26.7: only allowlisted category stems may be turned into a path. Any
        other value (including traversal attempts like "../evil") raises
        ValueError, so no caller can write outside the memory directory.
        """
        if category not in _ALLOWED_CATEGORY_FILES:
            raise ValueError(f"Unknown memory category: {category!r}")
        return self._memory_dir / f"{category}.yaml"

    # ------------------------------------------------------------------
    # Category read / write
    # ------------------------------------------------------------------

    @_locked
    def load_category(self, category: str) -> list[dict[str, Any]]:
        """
        Load a category YAML file and return the list of entries.

        Returns an empty list if the file does not exist or is malformed.
        """
        try:
            path = self._category_path(category)
            data = load_yaml(path)
            entries = data.get(category, [])
            if not isinstance(entries, list):
                logger.warning(
                    "Memory category '%s' did not contain a list — returning [].",
                    category,
                )
                return []
            return entries
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to load memory category '%s': %s", category, exc
            )
            return []

    @_locked
    def save_category(self, category: str, entries: list[dict[str, Any]]) -> None:
        """
        Save the full list of entries back to the category YAML file.

        Silently logs and returns on failure — never raises.
        """
        try:
            path = self._category_path(category)
            save_yaml(path, {category: entries})
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to save memory category '%s': %s", category, exc
            )

    @_locked
    def all_memories(self) -> dict[str, list[dict[str, Any]]]:
        """
        Return all memory categories as a dict of {category_name: [entries]}.

        Never raises — returns an empty list for any category that fails.
        """
        result: dict[str, list[dict[str, Any]]] = {}
        for cat in CATEGORIES:
            result[cat] = self.load_category(cat)
        return result

    # ------------------------------------------------------------------
    # CRUD — saved categories
    # ------------------------------------------------------------------

    @_locked
    def add_memory(
        self,
        category: str,
        key: str,
        value: str,
        source: str = "manual",
        notes: str = "",
    ) -> dict[str, Any]:
        """
        Create a new memory entry and append it to the given category.

        Returns the created entry dict.  On failure, returns an empty dict.
        """
        try:
            now = _now_iso()
            entry: dict[str, Any] = {
                "id": _new_id(),
                "category": category,
                "key": key,
                "value": value,
                "source": source,
                "created_at": now,
                "updated_at": now,
                "notes": notes,
            }
            entries = self.load_category(category)
            entries.append(entry)
            self.save_category(category, entries)
            logger.info(
                "Memory added: id=%s category=%s key=%r", entry["id"], category, key
            )
            return entry
        except Exception as exc:  # noqa: BLE001
            logger.error("add_memory failed: %s", exc)
            return {}

    @_locked
    def update_memory(
        self, memory_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Find an entry by id across all categories, apply allowed field updates,
        and save.

        Allowed updatable fields: key, value, notes.
        updated_at is always refreshed.

        Returns the updated entry, or None if not found.
        """
        allowed_fields = {"key", "value", "notes"}
        try:
            for category in CATEGORIES:
                entries = self.load_category(category)
                for i, entry in enumerate(entries):
                    if entry.get("id") == memory_id:
                        for field, val in updates.items():
                            if field in allowed_fields:
                                entries[i][field] = val
                        entries[i]["updated_at"] = _now_iso()
                        self.save_category(category, entries)
                        logger.info(
                            "Memory updated: id=%s category=%s", memory_id, category
                        )
                        return entries[i]
            logger.warning("update_memory: id not found: %s", memory_id)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.error("update_memory failed for id=%s: %s", memory_id, exc)
            return None

    @_locked
    def delete_memory(self, memory_id: str) -> bool:
        """
        Find and remove an entry by id from any category (or pending_review).

        Returns True if deleted, False if not found.
        """
        try:
            # Search saved categories first
            for category in CATEGORIES:
                entries = self.load_category(category)
                original_len = len(entries)
                entries = [e for e in entries if e.get("id") != memory_id]
                if len(entries) < original_len:
                    self.save_category(category, entries)
                    logger.info(
                        "Memory deleted: id=%s from category=%s", memory_id, category
                    )
                    return True

            # Also check pending_review
            pending = self.get_pending()
            original_len = len(pending)
            pending = [e for e in pending if e.get("id") != memory_id]
            if len(pending) < original_len:
                self._save_pending(pending)
                logger.info(
                    "Memory deleted from pending_review: id=%s", memory_id
                )
                return True

            logger.warning("delete_memory: id not found: %s", memory_id)
            return False
        except Exception as exc:  # noqa: BLE001
            logger.error("delete_memory failed for id=%s: %s", memory_id, exc)
            return False

    # ------------------------------------------------------------------
    # Pending review queue
    # ------------------------------------------------------------------

    @_locked
    def get_pending(self) -> list[dict[str, Any]]:
        """
        Load and return the pending_review list.

        Returns an empty list on failure.
        """
        try:
            path = self._category_path(PENDING_CATEGORY)
            data = load_yaml(path)
            entries = data.get(PENDING_LIST_KEY, [])
            if not isinstance(entries, list):
                return []
            return entries
        except Exception as exc:  # noqa: BLE001
            logger.error("get_pending failed: %s", exc)
            return []

    def _save_pending(self, entries: list[dict[str, Any]]) -> None:
        """Persist the pending_review list to disk."""
        try:
            path = self._category_path(PENDING_CATEGORY)
            save_yaml(path, {PENDING_LIST_KEY: entries})
        except Exception as exc:  # noqa: BLE001
            logger.error("_save_pending failed: %s", exc)

    @_locked
    def add_to_pending(
        self,
        category: str,
        key: str,
        value: str,
        reason: str,
        source: str = "auto",
    ) -> dict[str, Any]:
        """
        Add an entry to the pending_review queue.

        Returns the created pending entry dict.
        """
        try:
            now = _now_iso()
            entry: dict[str, Any] = {
                "id": _new_id(),
                "category": category,
                "key": key,
                "value": value,
                "source": source,
                "reason": reason,
                "created_at": now,
            }
            pending = self.get_pending()
            pending.append(entry)
            self._save_pending(pending)
            logger.info(
                "Pending memory added: id=%s category=%s key=%r reason=%r",
                entry["id"],
                category,
                key,
                reason,
            )
            return entry
        except Exception as exc:  # noqa: BLE001
            logger.error("add_to_pending failed: %s", exc)
            return {}

    @_locked
    def approve_pending(self, memory_id: str) -> dict[str, Any] | None:
        """
        Move a pending entry to its target category with source="approved".

        Returns the saved entry, or None if not found in pending_review.
        """
        try:
            pending = self.get_pending()
            target: dict[str, Any] | None = None
            remaining: list[dict[str, Any]] = []

            for entry in pending:
                if entry.get("id") == memory_id:
                    target = dict(entry)
                else:
                    remaining.append(entry)

            if target is None:
                logger.warning("approve_pending: id not found: %s", memory_id)
                return None

            category = target.get("category", "facts")
            if category not in CATEGORIES:
                logger.warning(
                    "approve_pending: unknown category '%s', defaulting to 'facts'",
                    category,
                )
                category = "facts"

            now = _now_iso()
            approved_entry: dict[str, Any] = {
                "id": target["id"],
                "category": category,
                "key": target.get("key", ""),
                "value": target.get("value", ""),
                "source": "approved",
                "created_at": target.get("created_at", now),
                "updated_at": now,
                "notes": target.get("notes", ""),
            }

            # Save to target category
            entries = self.load_category(category)
            entries.append(approved_entry)
            self.save_category(category, entries)

            # Remove from pending
            self._save_pending(remaining)

            logger.info(
                "Pending entry approved: id=%s → category=%s", memory_id, category
            )
            return approved_entry
        except Exception as exc:  # noqa: BLE001
            logger.error("approve_pending failed for id=%s: %s", memory_id, exc)
            return None

    @_locked
    def discard_pending(self, memory_id: str) -> bool:
        """
        Remove an entry from pending_review without saving it anywhere.

        Returns True if discarded, False if not found.
        """
        try:
            pending = self.get_pending()
            original_len = len(pending)
            pending = [e for e in pending if e.get("id") != memory_id]
            if len(pending) == original_len:
                logger.warning("discard_pending: id not found: %s", memory_id)
                return False
            self._save_pending(pending)
            logger.info("Pending entry discarded: id=%s", memory_id)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("discard_pending failed for id=%s: %s", memory_id, exc)
            return False

    # ------------------------------------------------------------------
    # Auto-extraction
    # ------------------------------------------------------------------

    @_locked
    def auto_extract(
        self, user_message: str, assistant_response: str  # noqa: ARG002
    ) -> list[dict[str, Any]]:
        """
        Conservatively extract memory candidates from a conversation turn.

        Only the user_message is analysed for explicit signals.
        The assistant_response is accepted as a parameter for API compatibility
        (and future use) but is not processed in Milestone 4.

        All candidates go to pending_review — nothing is auto-saved to a
        category directly.

        Returns the list of pending entries created (may be empty).
        """
        created: list[dict[str, Any]] = []

        try:
            # --- Preference patterns ---
            for pattern in PREFERENCE_PATTERNS:
                match = pattern.search(user_message)
                if match:
                    raw_value = match.group(1)
                    value = _clean_value(raw_value)
                    if not value:
                        continue

                    # Derive a human-readable key from the pattern
                    key = self._derive_preference_key(pattern.pattern, value)
                    reason = f"matched pattern: {pattern.pattern!r}"
                    entry = self.add_to_pending(
                        category="preferences",
                        key=key,
                        value=value,
                        reason=reason,
                        source="auto",
                    )
                    if entry:
                        created.append(entry)
                    # Only capture the first matching preference pattern
                    break

            # --- Environment patterns ---
            for pattern in ENVIRONMENT_PATTERNS:
                match = pattern.search(user_message)
                if match:
                    groups = match.groups()
                    if len(groups) >= 2:
                        tool_name = groups[0].strip()
                        raw_value = groups[1]
                        value = _clean_value(raw_value)
                        if not value:
                            continue
                        key = f"{tool_name.lower()}_location"
                        reason = f"matched pattern: {pattern.pattern!r}"
                        entry = self.add_to_pending(
                            category="environment",
                            key=key,
                            value=value,
                            reason=reason,
                            source="auto",
                        )
                        if entry:
                            created.append(entry)
                        # Only capture the first matching environment pattern
                        break

        except Exception as exc:  # noqa: BLE001
            logger.error("auto_extract encountered an error: %s", exc)

        if created:
            logger.info(
                "auto_extract: %d candidate(s) added to pending_review.", len(created)
            )

        return created

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_preference_key(pattern_str: str, value: str) -> str:
        """
        Derive a short snake_case key from the matched pattern and value.

        Falls back to a generic key if heuristics cannot produce a good one.
        """
        # Try to detect common preference types from the value
        value_lower = value.lower()

        # Date/time format signals
        if any(t in value_lower for t in ("date", "iso", "yyyy", "mm/dd", "dd/mm")):
            return "date_format_preference"

        # Tone / style signals
        if any(t in value_lower for t in ("terse", "verbose", "formal", "casual", "brief", "detailed")):
            return "communication_style_preference"

        # Tool name signals — first word of the value if it looks like a tool name
        first_word = value.split()[0] if value.split() else value
        if first_word.isalnum() and len(first_word) <= 20:
            return f"{first_word.lower()}_preference"

        # Generic fallback
        return "user_preference"
