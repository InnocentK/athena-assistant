"""
tests/test_write_safety.py — Filesystem write-safety tests (Milestone 26.7).

Regression guards for the four write/traversal holes closed in M26.7:
  - C2: memory `category` path traversal (allowlist in _category_path + 400 at API)
  - C3: backup restore Zip-Slip (per-member containment to the app root)
  - H1: diff_token not bound to the backup it was issued for
  - H2: zip_filename traversal in POST /backup/restore

All self-contained: real temp zips under the tmp project's data/exports, no network.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

MANIFEST_NAME = "athena_backup_manifest.json"


def _manifest_bytes() -> str:
    return json.dumps(
        {
            "backup_version": "1",
            "app_version": "1.4.0",
            "created_at": "2026-06-01T00:00:00Z",
            "hostname": "testhost",
            "includes": {"profiles": True, "config": True, "audit": False, "data": False},
            "file_count": 0,
            "files": [],
        }
    )


def _write_zip(path: Path, members: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(MANIFEST_NAME, _manifest_bytes())
        for name, content in members.items():
            zf.writestr(name, content)
    return path


# ---------------------------------------------------------------------------
# C2 — memory category traversal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_category", ["../evil", "../../../tmp/pwned", "foo/bar", "/abs"])
def test_memory_create_rejects_traversal_category(client, tmp_project: Path, bad_category):
    resp = client.post(
        "/memory",
        json={"category": bad_category, "key": "k", "value": "v"},
    )
    assert resp.status_code == 400
    assert "category" in resp.json()["detail"].lower()

    # Nothing was written outside the memory directory.
    memory_dir = tmp_project / "profiles" / "athena" / "memory"
    escaped = list((tmp_project / "profiles" / "athena").glob("*.yaml"))
    # profile.yaml lives in profiles/athena; only memory/*.yaml should hold memories
    assert all(p.parent == memory_dir or p.name == "profile.yaml" for p in escaped + list(memory_dir.glob("*.yaml")))
    assert not (tmp_project / "profiles" / "athena" / "evil.yaml").exists()


def test_memory_create_accepts_valid_category(client):
    resp = client.post(
        "/memory",
        json={"category": "facts", "key": "sky", "value": "blue"},
    )
    assert resp.status_code == 200
    assert resp.json()["category"] == "facts"


def test_category_path_rejects_unknown(tmp_project: Path):
    from memory.manager import MemoryManager

    mm = MemoryManager(tmp_project / "profiles" / "athena", {})
    # Valid category stems resolve to a path inside the memory dir.
    assert mm._category_path("facts").name == "facts.yaml"
    assert mm._category_path("pending_review").name == "pending_review.yaml"
    # Anything else — including traversal — raises before a path is built.
    for bad in ["../evil", "../../x", "foo", "/abs"]:
        with pytest.raises(ValueError):
            mm._category_path(bad)


# ---------------------------------------------------------------------------
# C3 — backup restore Zip-Slip
# ---------------------------------------------------------------------------


def test_restore_backup_blocks_zip_slip(tmp_project: Path):
    from backup.manager import BackupManager

    bm = BackupManager(tmp_project)
    exports = tmp_project / "data" / "exports"
    escape_rel = "../../ESCAPED_BY_ZIPSLIP.txt"
    zip_path = _write_zip(
        exports / "evil.zip",
        {
            escape_rel: "pwned",
            "config/safe_marker.txt": "safe",   # a legitimate in-root member
        },
    )

    # diff_restore reports the escaping member as rejected, not as an add.
    diff = bm.diff_restore(zip_path)
    assert escape_rel in diff["rejected"]
    assert escape_rel not in diff["would_add"]
    assert any("escape" in w.lower() for w in diff["warnings"])

    result = bm.restore_backup(zip_path, confirm=True)

    # The escaping file must NOT exist anywhere outside the app root.
    assert not (tmp_project.parent / "ESCAPED_BY_ZIPSLIP.txt").exists()
    assert not (tmp_project.parent.parent / "ESCAPED_BY_ZIPSLIP.txt").exists()
    # It was rejected, and the legitimate member was restored.
    assert result["rejected"] >= 1
    assert (tmp_project / "config" / "safe_marker.txt").exists()


def test_restore_backup_blocks_absolute_member(tmp_project: Path):
    from backup.manager import BackupManager

    bm = BackupManager(tmp_project)
    exports = tmp_project / "data" / "exports"
    # zipfile normalizes a leading "/", so emulate an absolute-style escape via ..
    zip_path = _write_zip(exports / "abs.zip", {"../../../tmp/abs_escape.txt": "x"})
    result = bm.restore_backup(zip_path, confirm=True)
    assert result["rejected"] >= 1
    assert not Path("/tmp/abs_escape.txt").exists()


# ---------------------------------------------------------------------------
# H1 — diff_token bound to its backup
# ---------------------------------------------------------------------------


def test_diff_token_bound_to_filename(client, tmp_project: Path):
    exports = tmp_project / "data" / "exports"
    _write_zip(exports / "A.zip", {"config/a.txt": "a"})
    _write_zip(exports / "B.zip", {"config/b.txt": "b"})

    # Token issued for A.zip.
    token = client.get("/backup/exports/A.zip/diff").json()["diff_token"]

    # Using A's token to restore B is rejected.
    cross = client.post(
        "/backup/restore",
        json={"zip_filename": "B.zip", "confirm": True, "diff_token": token},
    )
    assert cross.status_code == 409
    assert "not issued for this backup" in cross.json()["detail"].lower()

    # The same token restores A.zip fine.
    ok = client.post(
        "/backup/restore",
        json={"zip_filename": "A.zip", "confirm": True, "diff_token": token},
    )
    assert ok.status_code == 200
    assert ok.json().get("restored") is True


# ---------------------------------------------------------------------------
# H2 — zip_filename traversal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_name", ["../../etc/passwd.zip", "../secret.zip", "/etc/x.zip"])
def test_restore_zip_filename_traversal_rejected(client, bad_name):
    resp = client.post(
        "/backup/restore",
        json={"zip_filename": bad_name, "confirm": False},
    )
    assert resp.status_code == 400
    assert "invalid backup filename" in resp.json()["detail"].lower()


def test_safe_export_path_guard(client):
    """
    Direct unit test of the shared filename guard used by every backup endpoint
    (path-param endpoints can't be URL-traversed — the HTTP client normalizes
    `..` — so the guard is validated at the function level).
    """
    import main as app_module
    from fastapi import HTTPException

    # A legitimate filename resolves to a path inside data/exports/.
    good = app_module._safe_export_path("backup.zip")
    assert good.name == "backup.zip"
    assert good.parent.name == "exports"

    # Traversal and absolute paths are rejected with a 400.
    for bad in ["../secret.zip", "../../etc/passwd", "/etc/x"]:
        with pytest.raises(HTTPException) as exc:
            app_module._safe_export_path(bad)
        assert exc.value.status_code == 400
