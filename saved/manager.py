"""
saved/manager.py — Saved searches and saved actions (Milestone 18).

A per-profile YAML store that mirrors `memory/manager.py`. Two collections live
under the active profile's `saved/` directory:

  searches — named file-search definitions:
             {id, name, query, target, path, created_at, updated_at}
  actions  — named reusable prompts:
             {id, name, prompt, mode, provider, created_at, updated_at}

IMPORTANT (v1 / Milestone 18): only **file** searches are runnable. A saved
search's `target` defaults to "files"; the API rejects any other target. There
is NO web-search backend in this milestone — runnable saved web searches are
explicitly future work.

All methods are defensively coded: exceptions are caught, logged, and safe
defaults returned, so a saved-items failure never crashes the assistant.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.loader import load_yaml, save_yaml
from core.logger import logger

SEARCHES_KEY = "searches"
ACTIONS_KEY = "actions"

# Fields a client may update; id/created_at/updated_at are managed internally.
SEARCH_UPDATABLE: set[str] = {"name", "query", "target", "path"}
ACTION_UPDATABLE: set[str] = {"name", "prompt", "mode", "provider"}


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string (no microseconds)."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _new_id(prefix: str) -> str:
    """Generate a short id using an 8-char UUID fragment, e.g. 'srch_1a2b3c4d'."""
    return f"{prefix}_" + uuid.uuid4().hex[:8]


class SavedItemsManager:
    """Manages per-profile saved searches and saved actions (YAML flat files)."""

    def __init__(self, profile_dir: Path) -> None:
        self._profile_dir = Path(profile_dir)
        logger.info("SavedItemsManager initialised for profile dir: %s", self._profile_dir)

    # ------------------------------------------------------------------
    # Paths and raw load/save
    # ------------------------------------------------------------------

    @property
    def _saved_dir(self) -> Path:
        return self._profile_dir / "saved"

    def _path(self, kind: str) -> Path:
        return self._saved_dir / f"{kind}.yaml"

    def _load(self, kind: str) -> list[dict[str, Any]]:
        try:
            data = load_yaml(self._path(kind))
            items = data.get(kind, [])
            if not isinstance(items, list):
                logger.warning("Saved '%s' did not contain a list — returning [].", kind)
                return []
            return items
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to load saved %s: %s", kind, exc)
            return []

    def _save(self, kind: str, items: list[dict[str, Any]]) -> None:
        try:
            save_yaml(self._path(kind), {kind: items})  # save_yaml creates parent dirs
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to save saved %s: %s", kind, exc)

    # ------------------------------------------------------------------
    # Shared update / delete by id
    # ------------------------------------------------------------------

    def _update(
        self, kind: str, item_id: str, updates: dict[str, Any], allowed: set[str]
    ) -> dict[str, Any] | None:
        try:
            items = self._load(kind)
            for i, item in enumerate(items):
                if item.get("id") == item_id:
                    for field, val in updates.items():
                        if field in allowed:
                            items[i][field] = val
                    items[i]["updated_at"] = _now_iso()
                    self._save(kind, items)
                    logger.info("Saved %s updated: id=%s", kind, item_id)
                    return items[i]
            logger.warning("update: saved %s id not found: %s", kind, item_id)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.error("update failed for saved %s id=%s: %s", kind, item_id, exc)
            return None

    def _delete(self, kind: str, item_id: str) -> bool:
        try:
            items = self._load(kind)
            original_len = len(items)
            items = [x for x in items if x.get("id") != item_id]
            if len(items) < original_len:
                self._save(kind, items)
                logger.info("Saved %s deleted: id=%s", kind, item_id)
                return True
            logger.warning("delete: saved %s id not found: %s", kind, item_id)
            return False
        except Exception as exc:  # noqa: BLE001
            logger.error("delete failed for saved %s id=%s: %s", kind, item_id, exc)
            return False

    # ------------------------------------------------------------------
    # Saved searches  (file searches only in v1)
    # ------------------------------------------------------------------

    def list_searches(self) -> list[dict[str, Any]]:
        return self._load(SEARCHES_KEY)

    def get_search(self, item_id: str) -> dict[str, Any] | None:
        return next((s for s in self._load(SEARCHES_KEY) if s.get("id") == item_id), None)

    def add_search(
        self, name: str, query: str, target: str = "files", path: str | None = None
    ) -> dict[str, Any]:
        try:
            now = _now_iso()
            item: dict[str, Any] = {
                "id": _new_id("srch"),
                "name": name,
                "query": query,
                "target": target or "files",
                "path": path,
                "created_at": now,
                "updated_at": now,
            }
            items = self._load(SEARCHES_KEY)
            items.append(item)
            self._save(SEARCHES_KEY, items)
            logger.info("Saved search added: id=%s name=%r", item["id"], name)
            return item
        except Exception as exc:  # noqa: BLE001
            logger.error("add_search failed: %s", exc)
            return {}

    def update_search(self, item_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        return self._update(SEARCHES_KEY, item_id, updates, SEARCH_UPDATABLE)

    def delete_search(self, item_id: str) -> bool:
        return self._delete(SEARCHES_KEY, item_id)

    # ------------------------------------------------------------------
    # Saved actions  (reusable prompts run through the provider router)
    # ------------------------------------------------------------------

    def list_actions(self) -> list[dict[str, Any]]:
        return self._load(ACTIONS_KEY)

    def get_action(self, item_id: str) -> dict[str, Any] | None:
        return next((a for a in self._load(ACTIONS_KEY) if a.get("id") == item_id), None)

    def add_action(
        self, name: str, prompt: str, mode: str | None = None, provider: str | None = None
    ) -> dict[str, Any]:
        try:
            now = _now_iso()
            item: dict[str, Any] = {
                "id": _new_id("act"),
                "name": name,
                "prompt": prompt,
                "mode": mode,
                "provider": provider,
                "created_at": now,
                "updated_at": now,
            }
            items = self._load(ACTIONS_KEY)
            items.append(item)
            self._save(ACTIONS_KEY, items)
            logger.info("Saved action added: id=%s name=%r", item["id"], name)
            return item
        except Exception as exc:  # noqa: BLE001
            logger.error("add_action failed: %s", exc)
            return {}

    def update_action(self, item_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        return self._update(ACTIONS_KEY, item_id, updates, ACTION_UPDATABLE)

    def delete_action(self, item_id: str) -> bool:
        return self._delete(ACTIONS_KEY, item_id)
