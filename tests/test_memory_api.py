"""
tests/test_memory_api.py — API tests for /memory endpoints.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# GET /memory
# ---------------------------------------------------------------------------


def test_get_memory_returns_dict(client):
    """GET /memory returns 200 with a dict response."""
    response = client.get("/memory")
    assert response.status_code == 200
    assert isinstance(response.json(), dict)


# ---------------------------------------------------------------------------
# POST /memory
# ---------------------------------------------------------------------------


def test_post_memory_creates_entry(client):
    """POST /memory returns a created entry with an id starting with 'mem_'."""
    response = client.post(
        "/memory",
        json={"category": "facts", "key": "test_key", "value": "test_value"},
    )
    assert response.status_code in (200, 201)
    data = response.json()
    assert "id" in data
    assert data["id"].startswith("mem_")


# ---------------------------------------------------------------------------
# GET /memory/pending
# ---------------------------------------------------------------------------


def test_get_pending_returns_list(client):
    """GET /memory/pending returns 200 with a list."""
    response = client.get("/memory/pending")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ---------------------------------------------------------------------------
# POST then DELETE
# ---------------------------------------------------------------------------


def test_post_memory_then_delete(client):
    """Create a memory entry, then delete it; the entry should be gone."""
    # Create
    create_resp = client.post(
        "/memory",
        json={"category": "facts", "key": "del_key", "value": "del_value"},
    )
    assert create_resp.status_code in (200, 201)
    mem_id = create_resp.json()["id"]

    # Delete
    del_resp = client.delete(f"/memory/{mem_id}")
    assert del_resp.status_code in (200, 204)

    # Verify gone
    mem_resp = client.get("/memory")
    all_mem = mem_resp.json()
    facts = all_mem.get("facts", [])
    assert not any(e.get("id") == mem_id for e in facts)


def test_delete_nonexistent_memory_returns_404(client):
    """DELETE /memory/<nonexistent_id> returns 404."""
    response = client.delete("/memory/mem_nonexistent_id_xyz")
    assert response.status_code == 404
