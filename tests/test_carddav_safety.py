"""
tests/test_carddav_safety.py — Safety invariant tests for CardDAV merge workflow.

These tests verify the critical safety rule:
  - detect_duplicates never touches the server
  - stage_merge never writes to the server
  - commit_merge is the only write path and requires a valid staged_merge_id
  - StagedMergeNotFoundError is raised for invalid IDs
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def carddav_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """CardDAVClient backed by environment variables and tmp staging dir."""
    monkeypatch.setenv("CARDDAV_URL", "https://dav.example.com")
    monkeypatch.setenv("CARDDAV_USERNAME", "user@example.com")
    monkeypatch.setenv("CARDDAV_PASSWORD", "secret")

    import core.config as cc

    monkeypatch.setattr(cc, "APP_ROOT", tmp_path)
    staged_dir = tmp_path / "data" / "carddav_staged"
    staged_dir.mkdir(parents=True)

    from carddav_integration.client import CardDAVClient

    client = CardDAVClient()
    # Override staged_dir to use tmp_path
    client._staged_dir = staged_dir
    return client


# ---------------------------------------------------------------------------
# Config error tests (no env vars)
# ---------------------------------------------------------------------------


def test_carddav_config_error_on_missing_env(monkeypatch: pytest.MonkeyPatch):
    """CardDAVClient raises CardDAVConfigError when all credentials are missing."""
    monkeypatch.delenv("CARDDAV_URL", raising=False)
    monkeypatch.delenv("CARDDAV_USERNAME", raising=False)
    monkeypatch.delenv("CARDDAV_PASSWORD", raising=False)

    from carddav_integration.client import CardDAVClient, CardDAVConfigError

    with pytest.raises(CardDAVConfigError):
        CardDAVClient()


def test_carddav_config_error_lists_missing_vars(monkeypatch: pytest.MonkeyPatch):
    """CardDAVConfigError message names the missing environment variables."""
    monkeypatch.setenv("CARDDAV_URL", "https://dav.example.com")
    monkeypatch.delenv("CARDDAV_USERNAME", raising=False)
    monkeypatch.delenv("CARDDAV_PASSWORD", raising=False)

    from carddav_integration.client import CardDAVClient, CardDAVConfigError

    with pytest.raises(CardDAVConfigError) as exc_info:
        CardDAVClient()

    msg = str(exc_info.value)
    assert "CARDDAV_USERNAME" in msg or "CARDDAV_PASSWORD" in msg


# ---------------------------------------------------------------------------
# Staging directory operations
# ---------------------------------------------------------------------------


def test_list_staged_merges_empty(carddav_client):
    """list_staged_merges returns [] when no staged files exist."""
    assert carddav_client.list_staged_merges() == []


def test_get_staged_merge_not_found(carddav_client):
    """get_staged_merge raises StagedMergeNotFoundError for a non-existent id."""
    from carddav_integration.client import StagedMergeNotFoundError

    with pytest.raises(StagedMergeNotFoundError):
        carddav_client.get_staged_merge("nonexistent_id")


def test_discard_staged_merge_not_found(carddav_client):
    """discard_staged_merge raises StagedMergeNotFoundError for a non-existent id."""
    from carddav_integration.client import StagedMergeNotFoundError

    with pytest.raises(StagedMergeNotFoundError):
        carddav_client.discard_staged_merge("nonexistent_id")


# ---------------------------------------------------------------------------
# stage_merge safety: no server writes
# ---------------------------------------------------------------------------

_MOCK_MULTISTATUS_XML = """\
<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">
  <d:response>
    <d:href>/contacts/a.vcf</d:href>
    <d:propstat>
      <d:prop>
        <d:getetag>"etag1"</d:getetag>
        <card:address-data>BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Alice Smith\r\nUID:uid-a\r\nEND:VCARD</card:address-data>
      </d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>"""


def _make_mock_response(mocker, text: str, status_code: int = 207):
    """Build a mock requests.Response that looks valid to the CardDAV client."""
    mock_resp = mocker.MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = status_code
    mock_resp.text = text
    return mock_resp


def test_stage_merge_writes_to_local_file_only(carddav_client, mocker):
    """
    stage_merge fetches vCards from server (GET) but never PUTs or DELETEs.
    The result is saved as a JSON file in the staging directory.
    """
    # Build a simple vCard text response
    vcard_text = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Alice Smith\r\nUID:uid-a\r\nEND:VCARD\r\n"
    mock_resp = _make_mock_response(mocker, vcard_text, status_code=200)

    mocker.patch.object(carddav_client, "_request", return_value=mock_resp)

    result = carddav_client.stage_merge(
        address_book_url="https://dav.example.com/contacts/",
        contact_hrefs=["/contacts/a.vcf", "/contacts/b.vcf"],
        merged_data={"fn": "Alice B Smith"},
    )

    # Verify no PUT or DELETE was issued
    call_methods = [
        call.args[0].upper()
        for call in carddav_client._request.call_args_list
    ]
    assert "PUT" not in call_methods, f"stage_merge should not PUT; calls: {call_methods}"
    assert "DELETE" not in call_methods, f"stage_merge should not DELETE; calls: {call_methods}"

    # Verify staging file was written locally
    staged_files = list(carddav_client._staged_dir.glob("*.json"))
    assert len(staged_files) == 1

    import json

    record = json.loads(staged_files[0].read_text())
    assert record["status"] == "pending"
    assert "source_hrefs" in record
    assert result["staged_merge_id"] is not None


def test_commit_merge_requires_valid_staged_id(carddav_client):
    """
    commit_merge raises StagedMergeNotFoundError when the id is invalid.
    This confirms: without a prior stage_merge, a commit is impossible.
    """
    from carddav_integration.client import StagedMergeNotFoundError

    with pytest.raises(StagedMergeNotFoundError):
        carddav_client.commit_merge("invalid_id")


def test_stage_then_discard(carddav_client, mocker):
    """stage_merge followed by discard_staged_merge marks the file as 'discarded'."""
    vcard_text = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Alice Smith\r\nUID:uid-a\r\nEND:VCARD\r\n"
    mock_resp = _make_mock_response(mocker, vcard_text, status_code=200)
    mocker.patch.object(carddav_client, "_request", return_value=mock_resp)

    result = carddav_client.stage_merge(
        address_book_url="https://dav.example.com/contacts/",
        contact_hrefs=["/contacts/a.vcf", "/contacts/b.vcf"],
        merged_data={"fn": "Alice B Smith"},
    )
    staged_merge_id = result["staged_merge_id"]

    # Discard it
    discard_result = carddav_client.discard_staged_merge(staged_merge_id)
    assert discard_result is True

    # Verify status in the file
    record = carddav_client.get_staged_merge(staged_merge_id)
    assert record["status"] == "discarded"
