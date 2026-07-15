"""
tests/test_ops_hardening.py — Tests for Milestone 15: Operational Hardening.

Covers:
  - ops_audit.write_ops_event writes a valid JSON-lines entry
  - ops_audit.write_ops_event does not raise on bad input
  - diff endpoint returns a diff_token field
  - restore with confirm=True and no diff_token returns 409
  - restore with confirm=True and expired token returns 409
  - restore with confirm=True and valid token succeeds (mock the backup manager)
  - restore with confirm=False does not require a token
  - memory delete audit is written (mock write_ops_event)
  - file write audit is written (mock write_ops_event)
  - unhandled exception handler returns 500 with sanitised message
  - /health version matches core.version.__version__
  - timeout on restore returns 504
  - timeout on dav check returns 504
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helper: create a valid backup zip in the test project
# ---------------------------------------------------------------------------

def _make_backup_zip(tmp_project: Path) -> Path:
    """Create a minimal valid backup zip in the exports directory."""
    exports_dir = tmp_project / "data" / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    zip_path = exports_dir / "test_backup.zip"
    manifest = {
        "backup_version": "1",
        "app_version": "1.4.0",
        "created_at": "2026-06-01T00:00:00Z",
        "hostname": "testhost",
        "includes": {"profiles": True, "config": True, "audit": False, "data": False},
        "file_count": 0,
        "files": [],
    }
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("athena_backup_manifest.json", json.dumps(manifest))
    return zip_path


# ===========================================================================
# 1. ops_audit: write_ops_event writes a valid JSON-lines entry
# ===========================================================================

def test_write_ops_event_creates_valid_json_entry(tmp_project: Path, monkeypatch):
    """write_ops_event should append a valid JSON object to today's ops audit log."""
    # Patch APP_ROOT so the audit goes to tmp_project
    for mod in list(sys.modules.keys()):
        if "ops_audit" in mod or mod == "audit":
            sys.modules.pop(mod, None)
    import core.config as cc
    monkeypatch.setattr(cc, "APP_ROOT", tmp_project)
    import audit.ops_audit as oa
    monkeypatch.setattr(oa, "APP_ROOT", tmp_project)

    oa.write_ops_event(
        event="test_event",
        outcome="success",
        detail={"key": "value", "count": 42},
    )

    # Find the log file
    audit_dir = tmp_project / "audit"
    log_files = list(audit_dir.glob("*_ops_audit.log"))
    assert len(log_files) == 1, "Expected exactly one ops audit log file"

    lines = log_files[0].read_text().strip().splitlines()
    assert len(lines) == 1

    entry = json.loads(lines[0])
    assert entry["event"] == "test_event"
    assert entry["outcome"] == "success"
    assert entry["detail"] == {"key": "value", "count": 42}
    assert "timestamp" in entry


# ===========================================================================
# 2. ops_audit: write_ops_event does not raise on bad input
# ===========================================================================

def test_write_ops_event_does_not_raise_on_bad_input(tmp_project: Path, monkeypatch):
    """write_ops_event must never raise — even with unserializable detail values."""
    for mod in list(sys.modules.keys()):
        if "ops_audit" in mod:
            sys.modules.pop(mod, None)
    import core.config as cc
    monkeypatch.setattr(cc, "APP_ROOT", tmp_project)
    import audit.ops_audit as oa
    monkeypatch.setattr(oa, "APP_ROOT", tmp_project)

    # Should not raise even if APP_ROOT is read-only or detail is unserializable
    # We test with a non-serializable object; ops_audit catches exceptions internally
    class _Unserializable:
        pass

    # This may or may not succeed depending on json serialization, but must NOT raise
    try:
        oa.write_ops_event(event="bad", outcome="failure", detail={"obj": _Unserializable()})
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"write_ops_event raised unexpectedly: {exc}")


def test_write_ops_event_multiple_entries_appended(tmp_project: Path, monkeypatch):
    """Multiple calls should produce multiple JSON-lines entries."""
    for mod in list(sys.modules.keys()):
        if "ops_audit" in mod:
            sys.modules.pop(mod, None)
    import core.config as cc
    monkeypatch.setattr(cc, "APP_ROOT", tmp_project)
    import audit.ops_audit as oa
    monkeypatch.setattr(oa, "APP_ROOT", tmp_project)

    oa.write_ops_event("ev1", "success", {"n": 1})
    oa.write_ops_event("ev2", "failure", {"n": 2})

    log_files = list((tmp_project / "audit").glob("*_ops_audit.log"))
    lines = log_files[0].read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "ev1"
    assert json.loads(lines[1])["event"] == "ev2"


# ===========================================================================
# 3. diff endpoint returns a diff_token field
# ===========================================================================

def test_backup_diff_returns_diff_token(client, tmp_project: Path):
    """GET /backup/exports/{filename}/diff should include diff_token in the response."""
    _make_backup_zip(tmp_project)
    response = client.get("/backup/exports/test_backup.zip/diff")
    assert response.status_code == 200
    data = response.json()
    assert "diff_token" in data
    assert isinstance(data["diff_token"], str)
    assert len(data["diff_token"]) > 0


# ===========================================================================
# 4. restore with confirm=True and no diff_token returns 409
# ===========================================================================

def test_restore_confirm_without_token_returns_409(client, tmp_project: Path):
    """POST /backup/restore with confirm=True and no diff_token must return 409."""
    _make_backup_zip(tmp_project)
    response = client.post(
        "/backup/restore",
        json={"zip_filename": "test_backup.zip", "confirm": True},
    )
    assert response.status_code == 409
    assert "diff_token" in response.json()["detail"].lower()


# ===========================================================================
# 5. restore with confirm=True and expired token returns 409
# ===========================================================================

def test_restore_confirm_with_expired_token_returns_409(client, tmp_project: Path):
    """POST /backup/restore with an expired diff_token should return 409."""
    _make_backup_zip(tmp_project)

    # Manually inject an expired token (M26.7: value is (filename, expiry))
    import main as app_module
    expired_token = "expired_token_abc123"
    app_module._restore_diff_tokens[expired_token] = ("test_backup.zip", time.monotonic() - 1)  # already expired

    response = client.post(
        "/backup/restore",
        json={
            "zip_filename": "test_backup.zip",
            "confirm": True,
            "diff_token": expired_token,
        },
    )
    assert response.status_code == 409
    assert "diff_token" in response.json()["detail"].lower()


# ===========================================================================
# 6. restore with confirm=True and valid token succeeds
# ===========================================================================

def test_restore_confirm_with_valid_token_succeeds(client, tmp_project: Path):
    """POST /backup/restore with a valid diff_token and confirm=True should succeed."""
    _make_backup_zip(tmp_project)

    # First get a diff to obtain a real token
    diff_resp = client.get("/backup/exports/test_backup.zip/diff")
    assert diff_resp.status_code == 200
    token = diff_resp.json()["diff_token"]

    # Now restore with confirm=True
    restore_resp = client.post(
        "/backup/restore",
        json={
            "zip_filename": "test_backup.zip",
            "confirm": True,
            "diff_token": token,
        },
    )
    assert restore_resp.status_code == 200
    data = restore_resp.json()
    assert data.get("restored") is True


# ===========================================================================
# 7. restore with confirm=False does not require a token
# ===========================================================================

def test_restore_dry_run_no_token_required(client, tmp_project: Path):
    """POST /backup/restore with confirm=False should work without a diff_token."""
    _make_backup_zip(tmp_project)
    response = client.post(
        "/backup/restore",
        json={"zip_filename": "test_backup.zip", "confirm": False},
    )
    assert response.status_code == 200
    data = response.json()
    # confirm=False returns a diff (no restored key)
    assert data.get("confirmed") is False or "would_add" in data


# ===========================================================================
# 8. memory delete audit is written
# ===========================================================================

def test_memory_delete_audit_written(client, monkeypatch):
    """DELETE /memory/{id} should call write_ops_event with event='memory_delete'."""
    import main as app_module

    audit_calls: list[dict] = []

    def fake_write_ops_event(event: str, outcome: str, detail: dict) -> None:
        audit_calls.append({"event": event, "outcome": outcome, "detail": detail})

    monkeypatch.setattr(app_module, "write_ops_event", fake_write_ops_event)

    # Create a memory entry first
    create_resp = client.post(
        "/memory",
        json={"category": "facts", "key": "test_key", "value": "test_value"},
    )
    assert create_resp.status_code == 200
    memory_id = create_resp.json()["id"]

    # Delete it
    del_resp = client.delete(f"/memory/{memory_id}")
    assert del_resp.status_code == 200

    # Verify audit was written
    delete_events = [c for c in audit_calls if c["event"] == "memory_delete"]
    assert len(delete_events) == 1
    assert delete_events[0]["outcome"] == "success"
    assert delete_events[0]["detail"]["memory_id"] == memory_id


# ===========================================================================
# 9. file write audit is written
# ===========================================================================

def test_file_write_audit_written(client, tmp_project: Path, monkeypatch):
    """POST /files/write should call write_ops_event with event='file_write'."""
    import main as app_module

    audit_calls: list[dict] = []

    def fake_write_ops_event(event: str, outcome: str, detail: dict) -> None:
        audit_calls.append({"event": event, "outcome": outcome, "detail": detail})

    monkeypatch.setattr(app_module, "write_ops_event", fake_write_ops_event)

    # data/ is write-permitted in conftest files.yaml
    response = client.post(
        "/files/write",
        json={"path": "data/ops_test.txt", "content": "hello from test"},
    )
    assert response.status_code == 200

    write_events = [c for c in audit_calls if c["event"] == "file_write"]
    assert len(write_events) == 1
    assert write_events[0]["outcome"] == "success"
    assert "data/ops_test.txt" in write_events[0]["detail"]["path"]


# ===========================================================================
# 10. unhandled exception handler returns 500 with sanitised message
# ===========================================================================

def test_unhandled_exception_returns_sanitised_500(tmp_project, monkeypatch):
    """
    A route that raises an unexpected bare Exception should return 500
    with the generic 'An unexpected error occurred' message (not a raw traceback).
    TestClient must be constructed with raise_server_exceptions=False so the
    exception handler's JSONResponse is returned rather than re-raised.
    """
    import sys
    # Fresh import of modules so APP_ROOT is patched correctly
    for mod in list(sys.modules.keys()):
        if mod == "main" or mod.startswith("main."):
            sys.modules.pop(mod, None)
    for mod in ["audit.ops_audit", "audit", "core.config"]:
        sys.modules.pop(mod, None)

    monkeypatch.chdir(tmp_project)
    monkeypatch.setenv("ACTIVE_PROFILE", "athena")
    monkeypatch.setenv("APP_ENV", "test")

    import core.config as cc
    monkeypatch.setattr(cc, "APP_ROOT", tmp_project)
    cc.get_settings.cache_clear()

    import files.manager as fm_mod
    monkeypatch.setattr(fm_mod, "APP_ROOT", tmp_project)
    monkeypatch.setattr(fm_mod, "_FILES_CONFIG", tmp_project / "config" / "files.yaml")
    monkeypatch.setattr(fm_mod, "_AUDIT_DIR", tmp_project / "audit")

    sys.modules.pop("main", None)
    import main as app_module
    from fastapi.testclient import TestClient

    # Register a crashing route
    @app_module.app.get("/test_crash_m15_unique", include_in_schema=False)
    async def _crash_route():
        raise RuntimeError("deliberate test crash")

    # raise_server_exceptions=False lets the exception handler return a response
    with TestClient(app_module.app, raise_server_exceptions=False) as tc:
        response = tc.get("/test_crash_m15_unique")

    assert response.status_code == 500
    data = response.json()
    assert "detail" in data
    assert "unexpected error" in data["detail"].lower()
    # Must NOT expose raw traceback details
    assert "RuntimeError" not in data["detail"]
    assert "deliberate test crash" not in data["detail"]


# ===========================================================================
# 11. /health surfaces the single-source version (core/version.py)
# ===========================================================================

def test_health_version_matches_single_source(client):
    """GET /health must report core.version.__version__ — the ONE bump site
    (M26.17). Guards against anyone hardcoding a version string again."""
    from core.version import __version__

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["version"] == __version__


# ===========================================================================
# 12. Token is consumed after successful restore (single-use)
# ===========================================================================

def test_restore_token_is_single_use(client, tmp_project: Path):
    """A diff_token should be consumed after a successful restore and cannot be reused."""
    _make_backup_zip(tmp_project)

    diff_resp = client.get("/backup/exports/test_backup.zip/diff")
    token = diff_resp.json()["diff_token"]

    # First restore succeeds
    r1 = client.post(
        "/backup/restore",
        json={"zip_filename": "test_backup.zip", "confirm": True, "diff_token": token},
    )
    assert r1.status_code == 200

    # Second restore with same token should fail
    r2 = client.post(
        "/backup/restore",
        json={"zip_filename": "test_backup.zip", "confirm": True, "diff_token": token},
    )
    assert r2.status_code == 409


# ===========================================================================
# 13. restore timeout returns 504
# ===========================================================================

def test_restore_timeout_returns_504(client, tmp_project: Path, monkeypatch):
    """When restore_backup times out, POST /backup/restore should return 504."""
    _make_backup_zip(tmp_project)

    # Get a valid token first
    diff_resp = client.get("/backup/exports/test_backup.zip/diff")
    token = diff_resp.json()["diff_token"]


    # Patch asyncio.wait_for to raise TimeoutError
    original_wait_for = asyncio.wait_for

    async def fake_wait_for(coro, timeout):
        # Cancel the coroutine to avoid resource warnings
        coro.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    try:
        response = client.post(
            "/backup/restore",
            json={"zip_filename": "test_backup.zip", "confirm": True, "diff_token": token},
        )
        assert response.status_code == 504
        assert "timed out" in response.json()["detail"].lower()
    finally:
        monkeypatch.setattr(asyncio, "wait_for", original_wait_for)


# ===========================================================================
# 14. DAV check timeout returns 504
# ===========================================================================

def test_dav_check_timeout_returns_504(client, monkeypatch):
    """POST /status/dav/{integration}/check should return 504 when the connection check times out."""
    import main as app_module

    # Provide a fake client with a check_connection that blocks
    fake_client = MagicMock()
    fake_client.check_connection = lambda: {"ok": True}

    monkeypatch.setattr(app_module, "_caldav", fake_client)

    original_wait_for = asyncio.wait_for

    async def fake_wait_for(coro, timeout):
        coro.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    try:
        response = client.post("/status/dav/caldav/check")
        assert response.status_code == 504
        assert "timed out" in response.json()["detail"].lower()
    finally:
        monkeypatch.setattr(asyncio, "wait_for", original_wait_for)
        monkeypatch.setattr(app_module, "_caldav", None)


# ===========================================================================
# 15. 404 for unknown DAV integration still returns 404 (not caught by unhandled handler)
# ===========================================================================

def test_unknown_dav_integration_still_404(client):
    """POST /status/dav/unknown/check must return 404, not 500."""
    response = client.post("/status/dav/unknown_xyz/check")
    assert response.status_code == 404
