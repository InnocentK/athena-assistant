"""
tests/test_files_api.py — API tests for /files endpoints.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------


def test_get_allowlist(client):
    """GET /files/allowlist returns 200 with a list."""
    response = client.get("/files/allowlist")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_post_and_delete_allowlist_entry(client):
    """POST an entry to the allowlist, then DELETE it, verifying both operations."""
    # Add
    add_resp = client.post(
        "/files/allowlist",
        json={"path": "exports", "label": "Exports", "search": True, "read": True, "write": False},
    )
    assert add_resp.status_code == 200

    # Verify present
    list_resp = client.get("/files/allowlist")
    paths = [e["path"] for e in list_resp.json()]
    assert "exports" in paths

    # Delete
    del_resp = client.delete("/files/allowlist?path=exports")
    assert del_resp.status_code == 200

    # Verify gone
    list_resp2 = client.get("/files/allowlist")
    paths2 = [e["path"] for e in list_resp2.json()]
    assert "exports" not in paths2


# ---------------------------------------------------------------------------
# Write and read
# ---------------------------------------------------------------------------


def test_files_write_and_read(client):
    """POST /files/write then GET /files/read returns the same content."""
    write_resp = client.post(
        "/files/write",
        json={"path": "data/api_test.txt", "content": "api write test"},
    )
    assert write_resp.status_code == 200
    assert write_resp.json()["written"] is True

    read_resp = client.get("/files/read?path=data/api_test.txt")
    assert read_resp.status_code == 200
    assert read_resp.json()["content"] == "api write test"


# ---------------------------------------------------------------------------
# Security guards
# ---------------------------------------------------------------------------


def test_files_write_to_config_rejected(client):
    """POST /files/write targeting config/files.yaml returns 403."""
    response = client.post(
        "/files/write",
        json={"path": "config/files.yaml", "content": "hacked"},
    )
    assert response.status_code == 403


def test_files_path_traversal_rejected(client):
    """GET /files/read with a traversal path returns 403 or 404."""
    response = client.get("/files/read?path=../../etc/passwd")
    assert response.status_code in (403, 404)


# ---------------------------------------------------------------------------
# Reload
# ---------------------------------------------------------------------------


def test_allowlist_reload(client):
    """PATCH /files/allowlist/reload returns 200 with reloaded=true."""
    response = client.patch("/files/allowlist/reload")
    assert response.status_code == 200
    assert response.json().get("reloaded") is True


def test_files_read_binary_returns_200_not_500(client, tmp_project):
    """M26.14: GET /files/read on a binary allowlisted file must be a clean 200
    with replacement characters — previously an unhandled UnicodeDecodeError 500."""
    (tmp_project / "data" / "image.bin").write_bytes(b"\x89PNG\r\n\x1a\n\x00\xff\xfe")

    resp = client.get("/files/read?path=data/image.bin")

    assert resp.status_code == 200
    body = resp.json()
    assert body["truncated"] is False
    assert "�" in body["content"]
