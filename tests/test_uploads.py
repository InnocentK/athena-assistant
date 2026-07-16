"""File uploads (M29.3): sanitize, cap, uniqueness, allowlist round-trip."""

from __future__ import annotations


def test_upload_round_trip_readable_via_allowlist(client):
    resp = client.post(
        "/files/upload", files={"file": ("notes.txt", b"hello upload", "text/plain")}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["path"] == "data/uploads/notes.txt" and data["bytes"] == 12

    listed = client.get("/files/uploads").json()
    assert any(e["name"] == "notes.txt" for e in listed)

    # readable through the EXISTING allowlisted read path
    read = client.get("/files/read", params={"path": "data/uploads/notes.txt"})
    assert read.status_code == 200
    assert read.json()["content"] == "hello upload"


def test_upload_sanitizes_traversal_names(client):
    import core.config as cc

    resp = client.post(
        "/files/upload", files={"file": ("../../evil.txt", b"x", "text/plain")}
    )
    assert resp.status_code == 200
    assert resp.json()["path"] == "data/uploads/evil.txt"
    assert (cc.APP_ROOT / "data" / "uploads" / "evil.txt").exists()
    assert not (cc.APP_ROOT / "evil.txt").exists()


def test_upload_dotfile_and_weird_chars_sanitized(client):
    resp = client.post(
        "/files/upload", files={"file": (".env stolen?.txt", b"x", "text/plain")}
    )
    assert resp.status_code == 200
    name = resp.json()["name"]
    assert not name.startswith(".") and "?" not in name and " " not in name


def test_upload_collision_gets_unique_suffix(client):
    a = client.post("/files/upload", files={"file": ("same.txt", b"a", "text/plain")})
    b = client.post("/files/upload", files={"file": ("same.txt", b"b", "text/plain")})
    assert a.json()["name"] == "same.txt"
    assert b.json()["name"] == "same-1.txt"


def test_upload_rejects_oversize_and_leaves_nothing(client):
    import core.config as cc

    big = b"x" * (10 * 1024 * 1024 + 1)
    resp = client.post("/files/upload", files={"file": ("big.bin", big, "application/octet-stream")})
    assert resp.status_code == 413
    assert not (cc.APP_ROOT / "data" / "uploads" / "big.bin").exists()


def test_upload_rejects_empty(client):
    resp = client.post("/files/upload", files={"file": ("empty.txt", b"", "text/plain")})
    assert resp.status_code == 400


def test_concurrent_same_name_uploads_never_overwrite(client):
    """REVIEW-3.0 F1: exclusive create ('xb') means the filesystem enforces
    never-overwrite — a real two-thread race must yield two distinct files
    with both payloads intact."""
    import threading

    import core.config as cc

    barrier = threading.Barrier(2, timeout=10)
    results = []

    def upload(payload: bytes):
        barrier.wait()
        r = client.post("/files/upload", files={"file": ("race.txt", payload, "text/plain")})
        results.append(r.json())

    t1 = threading.Thread(target=upload, args=(b"payload-A",))
    t2 = threading.Thread(target=upload, args=(b"payload-B",))
    t1.start()
    t2.start()
    t1.join(10)
    t2.join(10)

    names = {r["name"] for r in results}
    assert len(names) == 2                              # distinct files
    contents = {
        (cc.APP_ROOT / "data" / "uploads" / n).read_bytes() for n in names
    }
    assert contents == {b"payload-A", b"payload-B"}     # both intact
