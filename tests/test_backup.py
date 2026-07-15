"""
tests/test_backup.py — Tests for backup/manager.py and /backup/* API endpoints.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# bm fixture — BackupManager wired to a tmp directory
# ---------------------------------------------------------------------------


@pytest.fixture
def bm(tmp_path: Path):
    """BackupManager wired to a tmp directory."""
    # Create minimum structure
    (tmp_path / "profiles" / "athena" / "memory").mkdir(parents=True)
    (tmp_path / "profiles" / "athena" / "profile.yaml").write_text(
        yaml.safe_dump({"name": "Athena Test", "version": "1.0.0"})
    )
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "app.yaml").write_text(yaml.safe_dump({"app_name": "Athena"}))
    (tmp_path / "audit").mkdir()
    (tmp_path / "data" / "exports").mkdir(parents=True)
    (tmp_path / "data" / "restore_staging").mkdir(parents=True)

    from backup.manager import BackupManager  # noqa: PLC0415
    return BackupManager(tmp_path)


# ---------------------------------------------------------------------------
# Unit tests — BackupManager
# ---------------------------------------------------------------------------


def test_create_export_returns_path(bm, tmp_path):
    path = bm.create_export()
    assert path.exists()
    assert path.suffix == ".zip"
    assert "data/exports" in str(path) or path.parent.name == "exports"


def test_export_contains_manifest(bm, tmp_path):
    path = bm.create_export()
    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()
        assert "athena_backup_manifest.json" in names
        manifest = json.loads(zf.read("athena_backup_manifest.json"))
    assert manifest["backup_version"] == "1"
    assert manifest["includes"]["profiles"] is True


def test_export_contains_profile_yaml(bm, tmp_path):
    path = bm.create_export()
    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()
    assert "profiles/athena/profile.yaml" in names


def test_export_excludes_env(bm, tmp_path):
    (tmp_path / ".env").write_text("SECRET=abc")
    path = bm.create_export()
    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()
    assert ".env" not in names


def test_export_with_audit(bm, tmp_path):
    (tmp_path / "audit" / "test.log").write_text("some audit log")
    path = bm.create_export(include_audit=True)
    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()
    assert "audit/test.log" in names


def test_list_exports_empty(bm, tmp_path):
    result = bm.list_exports()
    assert result == []


def test_list_exports_after_create(bm, tmp_path):
    bm.create_export()
    result = bm.list_exports()
    assert len(result) == 1
    assert "filename" in result[0]
    assert "created_at" in result[0]


def test_inspect_backup(bm, tmp_path):
    path = bm.create_export()
    result = bm.inspect_backup(path)
    assert result["valid"] is True
    assert result["backup_version"] == "1"


def test_diff_restore_shows_new_files(bm, tmp_path):
    zip_path = bm.create_export()
    # Delete the file so it will be "new" during restore
    (tmp_path / "profiles" / "athena" / "profile.yaml").unlink()
    diff = bm.diff_restore(zip_path)
    assert "profiles/athena/profile.yaml" in diff["would_add"]


def test_diff_restore_shows_overwrite(bm, tmp_path):
    zip_path = bm.create_export()
    # Profile still exists — should show as overwrite
    diff = bm.diff_restore(zip_path)
    assert "profiles/athena/profile.yaml" in diff["would_overwrite"]


def test_restore_confirm_false_returns_diff_only(bm, tmp_path):
    zip_path = bm.create_export()
    original_content = (tmp_path / "profiles" / "athena" / "profile.yaml").read_text()
    result = bm.restore_backup(zip_path, confirm=False)
    assert result["confirmed"] is False
    # File should not have changed
    assert (tmp_path / "profiles" / "athena" / "profile.yaml").read_text() == original_content


def test_restore_confirm_true_applies(bm, tmp_path):
    zip_path = bm.create_export()
    original_content = (tmp_path / "profiles" / "athena" / "profile.yaml").read_bytes()
    # Overwrite with different content
    (tmp_path / "profiles" / "athena" / "profile.yaml").write_text("name: Modified\n")
    # Restore
    result = bm.restore_backup(zip_path, confirm=True)
    assert result["restored"] is True
    # Should match original
    restored_content = (tmp_path / "profiles" / "athena" / "profile.yaml").read_bytes()
    assert restored_content == original_content


def test_restore_stages_overwritten_files(bm, tmp_path):
    zip_path = bm.create_export()
    # Modify the profile
    (tmp_path / "profiles" / "athena" / "profile.yaml").write_text("name: BeforeRestore\n")
    bm.restore_backup(zip_path, confirm=True)
    # Check that staging dir has a subdirectory with the old file
    staging_root = tmp_path / "data" / "restore_staging"
    staged_dirs = [d for d in staging_root.iterdir() if d.is_dir()]
    assert len(staged_dirs) == 1
    staged_profile = staged_dirs[0] / "profiles" / "athena" / "profile.yaml"
    assert staged_profile.exists()
    assert staged_profile.read_text() == "name: BeforeRestore\n"


def test_restore_skips_env(bm, tmp_path):
    """A zip that contains .env must not restore it."""
    # Build a zip manually that includes .env
    zip_path = tmp_path / "data" / "exports" / "test_env.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        manifest = {
            "backup_version": "1",
            "app_version": "1.3.0",
            "created_at": "2024-01-01T00:00:00Z",
            "hostname": "test",
            "includes": {"profiles": True, "config": True, "audit": False, "data": False},
            "file_count": 1,
            "files": [".env"],
        }
        zf.writestr("athena_backup_manifest.json", json.dumps(manifest))
        zf.writestr(".env", "SECRET=should_not_be_restored")

    bm.restore_backup(zip_path, confirm=True)
    assert not (tmp_path / ".env").exists()


def test_delete_export(bm, tmp_path):
    path = bm.create_export()
    assert path.exists()
    result = bm.delete_export(path)
    assert result is True
    assert not path.exists()


def test_audit_log_written_on_export(bm, tmp_path):
    bm.create_export()
    audit_files = list((tmp_path / "audit").glob("*_backup_audit.log"))
    assert len(audit_files) >= 1
    content = audit_files[0].read_text()
    assert "BACKUP_EXPORT" in content


# ---------------------------------------------------------------------------
# API tests — using client fixture from conftest
# ---------------------------------------------------------------------------


def test_get_backup_exports_returns_list(client):
    resp = client.get("/backup/exports")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_post_backup_export_creates_zip(client):
    resp = client.post("/backup/exports", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] is True
    assert "filename" in data


def test_get_backup_exports_after_create(client):
    client.post("/backup/exports", json={})
    resp = client.get("/backup/exports")
    assert resp.status_code == 200
    exports = resp.json()
    assert len(exports) >= 1


def test_backup_diff_returns_diff(client):
    create_resp = client.post("/backup/exports", json={})
    filename = create_resp.json()["filename"]
    resp = client.get(f"/backup/exports/{filename}/diff")
    assert resp.status_code == 200
    data = resp.json()
    assert "would_add" in data or "would_overwrite" in data


def test_backup_restore_confirm_false_returns_diff(client):
    create_resp = client.post("/backup/exports", json={})
    filename = create_resp.json()["filename"]
    resp = client.post(
        "/backup/restore",
        json={"zip_filename": filename, "confirm": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["confirmed"] is False


def test_backup_inspect_returns_manifest(client):
    create_resp = client.post("/backup/exports", json={})
    filename = create_resp.json()["filename"]
    resp = client.get(f"/backup/exports/{filename}/inspect")
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True


def test_backup_nonexistent_file_returns_404(client):
    resp = client.get("/backup/exports/nonexistent.zip/inspect")
    assert resp.status_code == 404
