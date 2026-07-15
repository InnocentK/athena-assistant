"""
tests/test_saved_items.py — Tests for saved/manager.py (SavedItemsManager).

Pure unit tests against a temp directory — no FastAPI, no providers, no network.
"""

from __future__ import annotations

from pathlib import Path

from saved.manager import SavedItemsManager


def _mgr(tmp_path: Path) -> SavedItemsManager:
    return SavedItemsManager(tmp_path)


# ---------------------------------------------------------------------------
# Searches
# ---------------------------------------------------------------------------


def test_add_and_list_search(tmp_path):
    m = _mgr(tmp_path)
    assert m.list_searches() == []
    item = m.add_search(name="md notes", query="*.md", path="data")
    assert item["id"].startswith("srch_")
    assert item["name"] == "md notes"
    assert item["query"] == "*.md"
    assert item["target"] == "files"
    assert item["path"] == "data"
    assert "created_at" in item and "updated_at" in item
    assert len(m.list_searches()) == 1


def test_get_search_and_missing(tmp_path):
    m = _mgr(tmp_path)
    item = m.add_search(name="x", query="*.txt")
    assert m.get_search(item["id"])["name"] == "x"
    assert m.get_search("nope") is None


def test_update_search_allowed_fields_only(tmp_path):
    m = _mgr(tmp_path)
    item = m.add_search(name="x", query="*.txt")
    updated = m.update_search(item["id"], {"name": "y", "query": "*.md", "id": "HACK", "created_at": "X"})
    assert updated["name"] == "y"
    assert updated["query"] == "*.md"
    assert updated["id"] == item["id"]            # id is not client-updatable
    assert updated["created_at"] == item["created_at"]
    assert updated["updated_at"] >= item["updated_at"]


def test_update_search_missing_returns_none(tmp_path):
    assert _mgr(tmp_path).update_search("nope", {"name": "z"}) is None


def test_delete_search(tmp_path):
    m = _mgr(tmp_path)
    item = m.add_search(name="x", query="*.txt")
    assert m.delete_search(item["id"]) is True
    assert m.list_searches() == []
    assert m.delete_search(item["id"]) is False    # already gone


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def test_add_and_get_action(tmp_path):
    m = _mgr(tmp_path)
    item = m.add_action(name="standup", prompt="Summarise my day", mode="budget-first", provider="ollama")
    assert item["id"].startswith("act_")
    assert item["prompt"] == "Summarise my day"
    assert item["mode"] == "budget-first"
    assert item["provider"] == "ollama"
    assert m.get_action(item["id"])["name"] == "standup"
    assert m.get_action("nope") is None


def test_update_and_delete_action(tmp_path):
    m = _mgr(tmp_path)
    item = m.add_action(name="a", prompt="p")
    updated = m.update_action(item["id"], {"prompt": "p2", "provider": "claude", "id": "HACK"})
    assert updated["prompt"] == "p2"
    assert updated["provider"] == "claude"
    assert updated["id"] == item["id"]
    assert m.delete_action(item["id"]) is True
    assert m.list_actions() == []


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_persistence_round_trip(tmp_path):
    m1 = _mgr(tmp_path)
    s = m1.add_search(name="s", query="*.md")
    a = m1.add_action(name="a", prompt="p")
    # A fresh manager over the same dir sees the persisted items.
    m2 = _mgr(tmp_path)
    assert [x["id"] for x in m2.list_searches()] == [s["id"]]
    assert [x["id"] for x in m2.list_actions()] == [a["id"]]
    # Files live under <profile>/saved/
    assert (tmp_path / "saved" / "searches.yaml").exists()
    assert (tmp_path / "saved" / "actions.yaml").exists()


def test_searches_and_actions_are_independent(tmp_path):
    m = _mgr(tmp_path)
    m.add_search(name="s", query="*.md")
    m.add_action(name="a", prompt="p")
    assert len(m.list_searches()) == 1
    assert len(m.list_actions()) == 1
    m.delete_search(m.list_searches()[0]["id"])
    assert len(m.list_searches()) == 0
    assert len(m.list_actions()) == 1   # unaffected
