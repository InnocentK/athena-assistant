"""
tests/test_dav_io.py — Tests for dav_io/vcf_io.py and dav_io/ics_io.py.

All tests use in-memory strings and tmp_path — no live server required.
CardDAV/CalDAV client calls are mocked.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch



# ---------------------------------------------------------------------------
# Test fixtures — minimal VCF / ICS strings
# ---------------------------------------------------------------------------

SINGLE_VCARD = """\
BEGIN:VCARD
VERSION:3.0
UID:uid-001
FN:Alice Smith
EMAIL:alice@example.com
TEL:+1-555-1234
ORG:Example Corp
NOTE:A test contact
END:VCARD
"""

SECOND_VCARD = """\
BEGIN:VCARD
VERSION:3.0
UID:uid-002
FN:Bob Jones
EMAIL:bob@example.com
END:VCARD
"""

TWO_VCARDS = SINGLE_VCARD + "\r\n" + SECOND_VCARD

SINGLE_ICS_EVENT = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
UID:event-001
SUMMARY:Team Meeting
DTSTART:20260601T100000Z
DTEND:20260601T110000Z
LOCATION:Conference Room
DESCRIPTION:Weekly team sync
END:VEVENT
END:VCALENDAR
"""

SINGLE_ICS_TODO = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VTODO
UID:todo-001
SUMMARY:Buy groceries
STATUS:NEEDS-ACTION
PRIORITY:5
DESCRIPTION:Milk and eggs and bread
END:VTODO
END:VCALENDAR
"""


# ===========================================================================
# VCF tests
# ===========================================================================


class TestParseVcfString:
    def test_parse_vcf_single_card(self):
        from dav_io.vcf_io import parse_vcf_string

        parsed, errors = parse_vcf_string(SINGLE_VCARD)
        assert len(parsed) == 1
        assert parsed[0]["fn"] == "Alice Smith"
        assert parsed[0]["uid"] == "uid-001"
        assert parsed[0]["email"] == "alice@example.com"
        assert not errors

    def test_parse_vcf_multiple_cards(self):
        from dav_io.vcf_io import parse_vcf_string

        parsed, errors = parse_vcf_string(TWO_VCARDS)
        assert len(parsed) == 2
        fns = {c["fn"] for c in parsed}
        assert "Alice Smith" in fns
        assert "Bob Jones" in fns

    def test_parse_vcf_invalid_block(self):
        from dav_io.vcf_io import parse_vcf_string

        parsed, errors = parse_vcf_string("NOT A VCARD")
        assert len(parsed) == 0
        assert len(errors) >= 1

    def test_parse_vcf_empty_string(self):
        from dav_io.vcf_io import parse_vcf_string

        parsed, errors = parse_vcf_string("")
        assert parsed == []
        assert errors == []

    def test_parse_vcf_raw_vcard_present(self):
        from dav_io.vcf_io import parse_vcf_string

        parsed, _ = parse_vcf_string(SINGLE_VCARD)
        assert "BEGIN:VCARD" in parsed[0]["raw_vcard"]
        assert "END:VCARD" in parsed[0]["raw_vcard"]


class TestDetectVcfConflict:
    def test_detect_vcf_conflict_by_uid(self):
        from dav_io.vcf_io import detect_vcf_conflict

        candidate = {"uid": "abc", "fn": "Alice", "email": "a@x.com"}
        existing = [
            {"uid": "ABC", "fn": "Alice Smith", "email": "different@x.com", "href": "/c/1.vcf"},
        ]
        result = detect_vcf_conflict(candidate, existing)
        assert result is not None
        assert result["uid"] == "ABC"

    def test_detect_vcf_conflict_by_fn_email(self):
        from dav_io.vcf_io import detect_vcf_conflict

        candidate = {"uid": "new-uid", "fn": "Alice Smith", "email": "alice@example.com"}
        existing = [
            {"uid": "other-uid", "fn": "Alice Smith", "email": "ALICE@EXAMPLE.COM", "href": "/c/1.vcf"},
        ]
        result = detect_vcf_conflict(candidate, existing)
        assert result is not None

    def test_detect_vcf_no_conflict(self):
        from dav_io.vcf_io import detect_vcf_conflict

        candidate = {"uid": "uid-x", "fn": "Charlie", "email": "charlie@x.com"}
        existing = [
            {"uid": "uid-y", "fn": "Alice Smith", "email": "alice@example.com", "href": "/c/1.vcf"},
        ]
        result = detect_vcf_conflict(candidate, existing)
        assert result is None

    def test_detect_vcf_no_conflict_empty_uid(self):
        from dav_io.vcf_io import detect_vcf_conflict

        # Empty UID should not trigger uid-match rule
        candidate = {"uid": "", "fn": "Dave", "email": "dave@x.com"}
        existing = [
            {"uid": "", "fn": "Someone Else", "email": "other@x.com", "href": "/c/2.vcf"},
        ]
        result = detect_vcf_conflict(candidate, existing)
        assert result is None

    def test_detect_vcf_fn_email_requires_both_nonempty(self):
        from dav_io.vcf_io import detect_vcf_conflict

        # Email is empty — fn-alone match should NOT trigger conflict
        candidate = {"uid": "uid-new", "fn": "Alice Smith", "email": ""}
        existing = [
            {"uid": "uid-other", "fn": "Alice Smith", "email": "", "href": "/c/1.vcf"},
        ]
        result = detect_vcf_conflict(candidate, existing)
        assert result is None


class TestExportVcf:
    def test_export_vcf_from_dicts(self):
        from dav_io.vcf_io import export_vcf

        contacts = [
            {
                "uid": "export-001",
                "fn": "Export Person",
                "email": "export@example.com",
                "phone": "+1-555-9999",
                "org": "Export Corp",
                "note": "Export note",
                "href": "/carddav/export-001.vcf",
            }
        ]
        result = export_vcf(contacts, carddav_client=None)
        assert "BEGIN:VCARD" in result
        assert "Export Person" in result

    def test_export_vcf_empty_contacts(self):
        from dav_io.vcf_io import export_vcf

        result = export_vcf([], carddav_client=None)
        assert result == ""

    def test_export_vcf_multiple_contacts(self):
        from dav_io.vcf_io import export_vcf

        contacts = [
            {"uid": "e1", "fn": "Person One", "email": "one@x.com",
             "phone": "", "org": "", "note": "", "href": "/1.vcf"},
            {"uid": "e2", "fn": "Person Two", "email": "two@x.com",
             "phone": "", "org": "", "note": "", "href": "/2.vcf"},
        ]
        result = export_vcf(contacts, carddav_client=None)
        assert "Person One" in result
        assert "Person Two" in result


# ===========================================================================
# VCF import flow tests (mocked client)
# ===========================================================================


class TestImportVcf:
    def test_import_vcf_no_conflicts(self, tmp_path):
        from dav_io.vcf_io import import_vcf

        mock_client = MagicMock()
        mock_client._url = "https://example.com"  # M26.13: import validates origin
        mock_client.list_contacts.return_value = []
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 201
        mock_client._request.return_value = mock_resp

        conflicts_dir = tmp_path / "conflicts"
        summary = import_vcf(SINGLE_VCARD, "https://example.com/cards/", mock_client, conflicts_dir)

        assert summary.imported == 1
        assert summary.skipped_conflicts == 0
        assert summary.invalid == 0
        assert summary.failed == 0

    def test_import_vcf_conflict_queued(self, tmp_path):
        from dav_io.vcf_io import import_vcf

        mock_client = MagicMock()
        mock_client._url = "https://example.com"  # M26.13: import validates origin
        # Return an existing contact with the same UID as the incoming card
        mock_client.list_contacts.return_value = [
            {"uid": "uid-001", "fn": "Alice (existing)", "email": "alice@example.com", "href": "/cards/uid-001.vcf"}
        ]

        conflicts_dir = tmp_path / "conflicts"
        summary = import_vcf(SINGLE_VCARD, "https://example.com/cards/", mock_client, conflicts_dir)

        assert summary.skipped_conflicts == 1
        assert summary.imported == 0
        # A conflict file should exist
        conflict_files = list(conflicts_dir.glob("*_carddav.json"))
        assert len(conflict_files) == 1
        data = json.loads(conflict_files[0].read_text())
        assert data["status"] == "pending"
        assert len(data["conflicts"]) == 1

    def test_import_vcf_failed_put(self, tmp_path):
        from dav_io.vcf_io import import_vcf

        mock_client = MagicMock()
        mock_client._url = "https://example.com"  # M26.13: import validates origin
        mock_client.list_contacts.return_value = []
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 500
        mock_resp.text = "Server error"
        mock_client._request.return_value = mock_resp

        conflicts_dir = tmp_path / "conflicts"
        summary = import_vcf(SINGLE_VCARD, "https://example.com/cards/", mock_client, conflicts_dir)

        assert summary.failed == 1
        assert summary.imported == 0

    def test_import_vcf_invalid_content(self, tmp_path):
        from dav_io.vcf_io import import_vcf

        mock_client = MagicMock()
        mock_client._url = "https://example.com"  # M26.13: import validates origin
        mock_client.list_contacts.return_value = []

        conflicts_dir = tmp_path / "conflicts"
        summary = import_vcf("NOT A VCARD", "https://example.com/cards/", mock_client, conflicts_dir)

        assert summary.invalid >= 1
        assert summary.imported == 0

    def test_import_vcf_empty_string(self, tmp_path):
        from dav_io.vcf_io import import_vcf

        mock_client = MagicMock()
        mock_client._url = "https://example.com"  # M26.13: import validates origin
        mock_client.list_contacts.return_value = []

        conflicts_dir = tmp_path / "conflicts"
        summary = import_vcf("", "https://example.com/cards/", mock_client, conflicts_dir)

        assert summary.total == 0
        assert summary.imported == 0

    def test_import_vcf_multiple_mixed(self, tmp_path):
        """Two cards: one conflicts, one imports successfully."""
        from dav_io.vcf_io import import_vcf

        mock_client = MagicMock()
        mock_client._url = "https://example.com"  # M26.13: import validates origin
        # Only uid-001 conflicts
        mock_client.list_contacts.return_value = [
            {"uid": "uid-001", "fn": "Alice (existing)", "email": "alice@example.com", "href": "/c/1.vcf"}
        ]
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 201
        mock_client._request.return_value = mock_resp

        conflicts_dir = tmp_path / "conflicts"
        summary = import_vcf(TWO_VCARDS, "https://example.com/cards/", mock_client, conflicts_dir)

        assert summary.imported == 1      # uid-002 imports fine
        assert summary.skipped_conflicts == 1  # uid-001 conflicts


# ===========================================================================
# ICS tests
# ===========================================================================


class TestParseIcsString:
    def test_parse_ics_single_event(self):
        from dav_io.ics_io import parse_ics_string

        parsed, errors = parse_ics_string(SINGLE_ICS_EVENT)
        assert len(parsed) == 1
        assert parsed[0]["type"] == "VEVENT"
        assert parsed[0]["summary"] == "Team Meeting"
        assert parsed[0]["uid"] == "event-001"
        assert not errors

    def test_parse_ics_single_todo(self):
        from dav_io.ics_io import parse_ics_string

        parsed, errors = parse_ics_string(SINGLE_ICS_TODO)
        assert len(parsed) == 1
        assert parsed[0]["type"] == "VTODO"
        assert parsed[0]["uid"] == "todo-001"

    def test_parse_ics_invalid(self):
        from dav_io.ics_io import parse_ics_string

        parsed, errors = parse_ics_string("NOT AN ICS")
        assert len(errors) >= 1

    def test_parse_ics_empty(self):
        from dav_io.ics_io import parse_ics_string

        parsed, errors = parse_ics_string("")
        assert parsed == []
        assert errors == []

    def test_parse_ics_raw_component_present(self):
        from dav_io.ics_io import parse_ics_string

        parsed, _ = parse_ics_string(SINGLE_ICS_EVENT)
        assert "BEGIN:VEVENT" in parsed[0]["raw_component"]
        assert "END:VEVENT" in parsed[0]["raw_component"]

    def test_parse_ics_event_fields(self):
        from dav_io.ics_io import parse_ics_string

        parsed, _ = parse_ics_string(SINGLE_ICS_EVENT)
        event = parsed[0]
        assert event["location"] == "Conference Room"
        assert event["description"] == "Weekly team sync"

    def test_parse_ics_todo_fields(self):
        from dav_io.ics_io import parse_ics_string

        parsed, _ = parse_ics_string(SINGLE_ICS_TODO)
        todo = parsed[0]
        assert todo["status"] == "NEEDS-ACTION"
        assert todo["priority"] == "5"
        assert todo["description"] == "Milk and eggs and bread"


class TestDetectIcsConflict:
    def test_detect_ics_conflict_by_uid(self):
        from dav_io.ics_io import detect_ics_conflict

        candidate = {"uid": "event-001", "type": "VEVENT", "summary": "Meeting"}
        existing = [
            {"uid": "EVENT-001", "type": "VEVENT", "summary": "Meeting (existing)"},
        ]
        result = detect_ics_conflict(candidate, existing)
        assert result is not None
        assert result["uid"] == "EVENT-001"

    def test_detect_ics_no_conflict(self):
        from dav_io.ics_io import detect_ics_conflict

        candidate = {"uid": "event-new", "type": "VEVENT", "summary": "New Meeting"}
        existing = [
            {"uid": "event-001", "type": "VEVENT", "summary": "Other Meeting"},
        ]
        result = detect_ics_conflict(candidate, existing)
        assert result is None

    def test_detect_ics_no_conflict_empty_uid(self):
        from dav_io.ics_io import detect_ics_conflict

        # Empty UID — should not conflict
        candidate = {"uid": "", "type": "VEVENT", "summary": "No UID"}
        existing = [{"uid": "", "type": "VEVENT", "summary": "Also No UID"}]
        result = detect_ics_conflict(candidate, existing)
        assert result is None


class TestExportIcs:
    def test_export_ics_from_dicts(self):
        from dav_io.ics_io import export_ics

        items = [
            {
                "type": "VEVENT",
                "uid": "export-ev-001",
                "summary": "Test Event",
                "dtstart": "2026-06-01T10:00:00",
                "dtend": "2026-06-01T11:00:00",
                "location": "",
                "description": "",
                "all_day": False,
                "raw_component": "",
            }
        ]
        result = export_ics(items, calendar_name="Test Calendar")
        assert "BEGIN:VCALENDAR" in result
        assert "END:VCALENDAR" in result
        assert "BEGIN:VEVENT" in result
        assert "Test Calendar" in result

    def test_export_ics_todo_from_dicts(self):
        from dav_io.ics_io import export_ics

        items = [
            {
                "type": "VTODO",
                "uid": "export-todo-001",
                "summary": "Test Task",
                "status": "NEEDS-ACTION",
                "due": "",
                "priority": "",
                "description": "",
                "raw_component": "",
            }
        ]
        result = export_ics(items)
        assert "BEGIN:VTODO" in result
        assert "Test Task" in result

    def test_export_ics_with_raw_component(self):
        from dav_io.ics_io import export_ics

        raw = "BEGIN:VEVENT\r\nUID:raw-001\r\nSUMMARY:Raw Event\r\nEND:VEVENT"
        items = [
            {"type": "VEVENT", "uid": "raw-001", "summary": "Raw Event", "raw_component": raw}
        ]
        result = export_ics(items)
        assert "Raw Event" in result
        assert "BEGIN:VCALENDAR" in result

    def test_export_ics_empty(self):
        from dav_io.ics_io import export_ics

        result = export_ics([])
        assert "BEGIN:VCALENDAR" in result
        assert "END:VCALENDAR" in result

    def test_export_ics_prodid(self):
        from dav_io.ics_io import export_ics

        result = export_ics([])
        assert "PRODID:-//Athena Assistant//CalDAV Export//EN" in result


# ===========================================================================
# ICS import flow tests (mocked client)
# ===========================================================================


class TestImportIcs:
    def _make_caldav_client(self):
        """Return a mock CalDAVClient."""
        mock_client = MagicMock()
        mock_client.list_events.return_value = []
        mock_client.list_tasks.return_value = []
        mock_client._ensure_connected.return_value = None
        mock_client._client = MagicMock()
        # M26.13: import_ics validates calendar_url against the client's
        # configured origin — mirror the real client's _url attribute.
        mock_client._url = "https://example.com"
        return mock_client

    def test_import_ics_no_conflicts(self, tmp_path):
        from dav_io.ics_io import import_ics

        mock_client = self._make_caldav_client()

        with patch("caldav.Calendar") as mock_cal_cls:
            mock_cal = MagicMock()
            mock_cal.add_event.return_value = MagicMock()
            mock_cal_cls.return_value = mock_cal

            conflicts_dir = tmp_path / "conflicts"
            summary = import_ics(
                SINGLE_ICS_EVENT,
                "https://example.com/cal/",
                mock_client,
                conflicts_dir,
            )

        assert summary.imported >= 1
        assert summary.skipped_conflicts == 0

    def test_import_ics_conflict_queued(self, tmp_path):
        from dav_io.ics_io import import_ics

        mock_client = self._make_caldav_client()
        # Return existing event with same UID
        mock_client.list_events.return_value = [
            {"uid": "event-001", "type": "VEVENT", "summary": "Existing Meeting"}
        ]

        with patch("caldav.Calendar") as mock_cal_cls:
            mock_cal = MagicMock()
            mock_cal_cls.return_value = mock_cal

            conflicts_dir = tmp_path / "conflicts"
            summary = import_ics(
                SINGLE_ICS_EVENT,
                "https://example.com/cal/",
                mock_client,
                conflicts_dir,
            )

        assert summary.skipped_conflicts == 1
        assert summary.imported == 0
        conflict_files = list(conflicts_dir.glob("*_caldav.json"))
        assert len(conflict_files) == 1
        data = json.loads(conflict_files[0].read_text())
        assert data["status"] == "pending"
        assert data["conflicts"][0]["reason"] == "uid_match"

    def test_import_ics_add_event_failure(self, tmp_path):
        from dav_io.ics_io import import_ics

        mock_client = self._make_caldav_client()

        with patch("caldav.Calendar") as mock_cal_cls:
            mock_cal = MagicMock()
            mock_cal.add_event.side_effect = Exception("Server error")
            mock_cal_cls.return_value = mock_cal

            conflicts_dir = tmp_path / "conflicts"
            summary = import_ics(
                SINGLE_ICS_EVENT,
                "https://example.com/cal/",
                mock_client,
                conflicts_dir,
            )

        assert summary.failed == 1
        assert summary.imported == 0

    def test_import_ics_empty(self, tmp_path):
        from dav_io.ics_io import import_ics

        mock_client = self._make_caldav_client()

        with patch("caldav.Calendar"):
            conflicts_dir = tmp_path / "conflicts"
            summary = import_ics("", "https://example.com/cal/", mock_client, conflicts_dir)

        assert summary.total == 0
        assert summary.imported == 0


# ===========================================================================
# API endpoint tests (using client fixture from conftest.py)
# ===========================================================================


class TestCardDavImportExportEndpoints:
    def test_carddav_import_returns_503_when_disabled(self, client):
        resp = client.post(
            "/carddav/import",
            json={
                "address_book_url": "https://dav.example.com/carddav/",
                "vcf_content": SINGLE_VCARD,
            },
        )
        assert resp.status_code == 503

    def test_carddav_export_returns_503_when_disabled(self, client):
        resp = client.get("/carddav/export?address_book_url=https://dav.example.com/carddav/")
        assert resp.status_code == 503

    def test_carddav_conflicts_list_returns_empty(self, client):
        resp = client.get("/carddav/conflicts")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_carddav_conflict_batch_not_found(self, client):
        resp = client.get("/carddav/conflicts/nonexistent-batch")
        assert resp.status_code == 404

    def test_carddav_resolve_conflict_returns_404_for_missing_batch(self, client):
        resp = client.post(
            "/carddav/conflicts/no-such-batch/no-such-conflict/resolve",
            json={"action": "skip"},
        )
        assert resp.status_code == 404


class TestCalDavImportExportEndpoints:
    def test_caldav_import_returns_503_when_disabled(self, client):
        resp = client.post(
            "/caldav/import",
            json={
                "calendar_url": "https://dav.example.com/caldav/",
                "ics_content": SINGLE_ICS_EVENT,
            },
        )
        assert resp.status_code == 503

    def test_caldav_export_returns_503_when_disabled(self, client):
        resp = client.get("/caldav/export?calendar_url=https://dav.example.com/caldav/")
        assert resp.status_code == 503

    def test_caldav_conflicts_list_returns_empty(self, client):
        resp = client.get("/caldav/conflicts")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_caldav_conflict_batch_not_found(self, client):
        resp = client.get("/caldav/conflicts/nonexistent-batch")
        assert resp.status_code == 404

    def test_caldav_resolve_conflict_returns_404_for_missing_batch(self, client):
        resp = client.post(
            "/caldav/conflicts/no-such-batch/no-such-conflict/resolve",
            json={"action": "skip"},
        )
        assert resp.status_code == 404


class TestConflictFileRoundtrip:
    """Test writing and reading conflict files directly."""

    def test_carddav_conflict_file_write_and_list(self, client):
        """The empty conflict list returns 200 + a list. (The real write→list→
        get→resolve round-trip is covered by TestConflictQueueRoundTrip, M26.18.)"""
        resp = client.get("/carddav/conflicts")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_caldav_conflicts_list_is_list(self, client):
        resp = client.get("/caldav/conflicts")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ===========================================================================
# M26.18 post-split regression: conflict-queue endpoints round-trip through
# REAL files. Guards the _carddav/_caldav filename suffix — during the router
# split these string literals were accidentally rewritten, which made list
# return [] and get/resolve 404 while every existing test still passed
# (they only asserted empty-list-200 and missing-batch-404).
# ===========================================================================


def _write_conflict_file(tmp_project, suffix: str, batch_id: str) -> None:
    import json as _json

    conflicts_dir = tmp_project / "data" / "import_conflicts"
    conflicts_dir.mkdir(parents=True, exist_ok=True)
    (conflicts_dir / f"{batch_id}{suffix}.json").write_text(
        _json.dumps(
            {
                "batch_id": batch_id,
                "created_at": "2026-07-14T00:00:00+00:00",
                "status": "pending",
                "conflicts": [
                    {
                        "conflict_id": "c-1",
                        "status": "pending",
                        "reason": "uid_match",
                        "incoming": {"uid": "u1", "fn": "A"},
                        "existing": {"uid": "u1", "fn": "B"},
                    }
                ],
            }
        )
    )


class TestConflictQueueRoundTrip:
    def test_carddav_conflict_list_get_and_skip_roundtrip(self, client, tmp_project):
        _write_conflict_file(tmp_project, "_carddav", "batch-cd-1")

        listing = client.get("/carddav/conflicts")
        assert listing.status_code == 200
        summaries = {s["batch_id"]: s for s in listing.json()}
        assert "batch-cd-1" in summaries, "list endpoint must see the real file"
        assert summaries["batch-cd-1"]["conflict_count"] == 1

        got = client.get("/carddav/conflicts/batch-cd-1")
        assert got.status_code == 200
        assert got.json()["conflicts"][0]["conflict_id"] == "c-1"

        resolved = client.post(
            "/carddav/conflicts/batch-cd-1/c-1/resolve", json={"action": "skip"}
        )
        assert resolved.status_code == 200
        assert resolved.json()["resolved"] is True

        # The save path must hit the SAME file (suffix intact end-to-end).
        again = client.get("/carddav/conflicts/batch-cd-1")
        assert again.json()["conflicts"][0]["status"] == "skipped"

    def test_caldav_conflict_list_get_and_skip_roundtrip(self, client, tmp_project):
        _write_conflict_file(tmp_project, "_caldav", "batch-cal-1")

        listing = client.get("/caldav/conflicts")
        assert listing.status_code == 200
        assert any(s["batch_id"] == "batch-cal-1" for s in listing.json())

        got = client.get("/caldav/conflicts/batch-cal-1")
        assert got.status_code == 200
        assert got.json()["conflicts"][0]["conflict_id"] == "c-1"

        resolved = client.post(
            "/caldav/conflicts/batch-cal-1/c-1/resolve", json={"action": "skip"}
        )
        assert resolved.status_code == 200

        again = client.get("/caldav/conflicts/batch-cal-1")
        assert again.json()["conflicts"][0]["status"] == "skipped"
