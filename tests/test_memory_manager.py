"""
tests/test_memory_manager.py — Tests for memory/manager.py.

Covers: add/update/delete memory entries, pending queue CRUD,
approve/discard, auto_extract (regex patterns).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Local fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def mm(tmp_path: Path):
    """MemoryManager wired to a tmp profile directory."""
    profile_dir = tmp_path / "profiles" / "athena"
    memory_dir = profile_dir / "memory"
    memory_dir.mkdir(parents=True)

    for cat in ["preferences", "workflows", "operating_notes", "environment", "facts"]:
        (memory_dir / f"{cat}.yaml").write_text(yaml.safe_dump({cat: []}))
    (memory_dir / "pending_review.yaml").write_text(yaml.safe_dump({"pending": []}))

    from memory.manager import MemoryManager

    return MemoryManager(profile_dir=profile_dir, profile_config={})


# ---------------------------------------------------------------------------
# CRUD — saved categories
# ---------------------------------------------------------------------------


def test_add_memory_returns_entry(mm):
    """add_memory returns an entry with correct id, key, value, category."""
    entry = mm.add_memory("preferences", "date_format", "ISO 8601")
    assert entry["id"].startswith("mem_")
    assert entry["key"] == "date_format"
    assert entry["value"] == "ISO 8601"
    assert entry["category"] == "preferences"


def test_add_memory_persisted(mm):
    """After add_memory, load_category returns the new entry."""
    mm.add_memory("preferences", "date_format", "ISO 8601")
    entries = mm.load_category("preferences")
    assert len(entries) == 1
    assert entries[0]["key"] == "date_format"


def test_update_memory(mm):
    """update_memory changes the value field and persists it."""
    entry = mm.add_memory("preferences", "date_format", "ISO 8601")
    mem_id = entry["id"]
    mm.update_memory(mem_id, {"value": "DD/MM/YYYY"})
    entries = mm.load_category("preferences")
    assert entries[0]["value"] == "DD/MM/YYYY"


def test_update_memory_invalid_id_returns_none(mm):
    """update_memory with a non-existent id returns None."""
    result = mm.update_memory("nonexistent_id", {"value": "x"})
    assert result is None


def test_delete_memory(mm):
    """delete_memory returns True and removes the entry from the category."""
    entry = mm.add_memory("preferences", "date_format", "ISO 8601")
    mem_id = entry["id"]
    assert mm.delete_memory(mem_id) is True
    assert mm.load_category("preferences") == []


def test_delete_memory_invalid_id_returns_false(mm):
    """delete_memory with a non-existent id returns False."""
    assert mm.delete_memory("nonexistent_id") is False


# ---------------------------------------------------------------------------
# Pending review queue
# ---------------------------------------------------------------------------


def test_add_to_pending(mm):
    """add_to_pending creates an entry in the pending queue."""
    mm.add_to_pending("preferences", "tone", "brief", reason="test")
    pending = mm.get_pending()
    assert len(pending) == 1
    assert pending[0]["reason"] == "test"
    assert pending[0]["source"] == "auto"


def test_approve_pending_moves_to_category(mm):
    """approve_pending moves the entry out of pending and into its category."""
    entry = mm.add_to_pending("preferences", "tone", "brief", reason="test")
    mem_id = entry["id"]
    result = mm.approve_pending(mem_id)
    assert result is not None
    assert mm.get_pending() == []
    entries = mm.load_category("preferences")
    assert len(entries) == 1


def test_discard_pending(mm):
    """discard_pending removes the entry from pending; nothing is saved to a category."""
    entry = mm.add_to_pending("preferences", "tone", "brief", reason="test")
    mem_id = entry["id"]
    assert mm.discard_pending(mem_id) is True
    assert mm.get_pending() == []
    # Critical: nothing was saved to any category
    assert mm.load_category("preferences") == []


# ---------------------------------------------------------------------------
# Auto-extract
# ---------------------------------------------------------------------------


def test_auto_extract_preference_pattern(mm):
    """auto_extract on a preference sentence adds 1 entry to pending."""
    mm.auto_extract("I prefer dark mode", "ok")
    pending = mm.get_pending()
    assert len(pending) == 1
    assert pending[0]["category"] == "preferences"


def test_auto_extract_no_match(mm):
    """auto_extract on a neutral message adds nothing to pending."""
    mm.auto_extract("What time is it?", "It is 3pm.")
    assert mm.get_pending() == []


def test_auto_extract_goes_to_pending_only(mm):
    """
    Critical safety check: auto_extract never writes directly to a saved category.
    Only pending_review may be populated.
    """
    mm.auto_extract("I prefer brief responses", "ok")
    # Pending has an entry
    assert len(mm.get_pending()) == 1
    # But no saved category has anything
    all_mem = mm.all_memories()
    for cat_entries in all_mem.values():
        assert cat_entries == [], f"Expected empty category, got: {cat_entries}"
