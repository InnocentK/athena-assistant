"""
tests/test_dav_correctness.py — Calendar/DAV correctness tests (M26.9).

Covers:
  - ICS DATE-TIME formatting: offset→UTC+Z, negative offset, naive→floating,
    trailing Z, date-only, unparseable fallback (H4).
  - ICS TEXT escaping in _reconstruct_component and CalDAV create_task (M1).
  - DavStatusStore snapshots are deep copies (M8).
  - Nextcloud read_file enforces the size cap while streaming (M10).
  - Backup manifest app_version reflects the constructed version (L1).
  - vCard multi-value email/phone survive parse → reconstruct (L2).

Self-contained: temp files + mocked requests/caldav; no network.
"""

from __future__ import annotations

import zipfile
from pathlib import Path



# ---------------------------------------------------------------------------
# H4 — ICS datetime formatting
# ---------------------------------------------------------------------------


def test_format_ics_datetime_offset_to_utc():
    from dav_io.ics_io import _format_ics_datetime

    assert _format_ics_datetime("2026-06-15T10:00:00+02:00") == "20260615T080000Z"
    assert _format_ics_datetime("2026-06-15T10:00:00-05:00") == "20260615T150000Z"


def test_format_ics_datetime_naive_is_floating():
    from dav_io.ics_io import _format_ics_datetime

    # Naive → no Z (never falsely declare UTC).
    assert _format_ics_datetime("2026-06-15T10:00:00") == "20260615T100000"


def test_format_ics_datetime_trailing_z_roundtrips():
    from dav_io.ics_io import _format_ics_datetime

    assert _format_ics_datetime("2026-06-15T10:00:00Z") == "20260615T100000Z"


def test_format_ics_datetime_unparseable_falls_back_without_z():
    from dav_io.ics_io import _format_ics_datetime

    out = _format_ics_datetime("not-a-date")
    assert not out.endswith("Z")


def test_reconstruct_event_uses_utc_and_dates():
    from dav_io.ics_io import _reconstruct_component

    ics = _reconstruct_component(
        {"type": "VEVENT", "uid": "u1", "summary": "S",
         "dtstart": "2026-06-15T10:00:00+02:00", "dtend": "2026-06-15"}
    )
    assert "DTSTART:20260615T080000Z" in ics       # offset converted to UTC
    assert "DTEND;VALUE=DATE:20260615" in ics       # date-only unchanged


# ---------------------------------------------------------------------------
# M1 — ICS TEXT escaping
# ---------------------------------------------------------------------------


def test_escape_ics_text_escapes_special_chars():
    from dav_io.ics_io import escape_ics_text

    assert escape_ics_text("a,b;c\\d") == "a\\,b\\;c\\\\d"
    assert escape_ics_text("line1\nline2") == "line1\\nline2"


def test_reconstruct_component_escapes_injection():
    from dav_io.ics_io import _reconstruct_component

    ics = _reconstruct_component(
        {"type": "VEVENT", "uid": "u1",
         "summary": "Evil\nBEGIN:VALARM", "description": "a, b; c"}
    )
    # The newline is escaped — no injected BEGIN:VALARM line.
    lines = ics.split("\r\n")
    assert not any(line.strip() == "BEGIN:VALARM" for line in lines)
    assert "SUMMARY:Evil\\nBEGIN:VALARM" in ics
    assert "DESCRIPTION:a\\, b\\; c" in ics


def test_caldav_create_task_escapes_text(monkeypatch):
    import caldav_integration.client as cc

    captured: dict = {}

    class _FakeCal:
        def __init__(self, *a, **k):
            pass

        def save_todo(self, ical_data):
            captured["ical"] = ical_data

    class _Client(cc.CalDAVClient):
        def __init__(self):
            pass

        def _ensure_connected(self):
            pass

    monkeypatch.setattr(cc, "caldav", type("m", (), {"Calendar": _FakeCal}), raising=False)
    # caldav is imported lazily inside create_task via `import caldav`
    import sys

    fake_mod = type("caldav", (), {"Calendar": _FakeCal})
    monkeypatch.setitem(sys.modules, "caldav", fake_mod)

    client = _Client()
    client._client = object()
    client._url = "http://x"  # M26.13: create_task validates URL origin
    client.create_task(
        calendar_url="http://x/cal", summary="Do X\nBEGIN:VALARM", description="a; b, c"
    )
    ical = captured["ical"]
    assert "SUMMARY:Do X\\nBEGIN:VALARM" in ical
    assert not any(line.strip() == "BEGIN:VALARM" for line in ical.split("\r\n"))
    assert "DESCRIPTION:a\\; b\\, c" in ical


# ---------------------------------------------------------------------------
# M8 — DavStatusStore snapshots are deep copies
# ---------------------------------------------------------------------------


def test_status_store_get_is_deep_copy():
    from dav_status.store import DavStatusStore

    store = DavStatusStore()
    store.reset()
    store.record_success("caldav", item_counts={"events": 3})

    snap = store.get("caldav")
    snap["item_counts"]["events"] = 9999
    snap["warnings"].append("injected")

    fresh = store.get("caldav")
    assert fresh["item_counts"].get("events") == 3
    assert "injected" not in fresh["warnings"]


def test_status_store_get_all_is_deep_copy():
    from dav_status.store import DavStatusStore

    store = DavStatusStore()
    store.reset()
    store.record_success("nextcloud", item_counts={"files": 5})

    allsnap = store.get_all()
    allsnap["nextcloud"]["item_counts"]["files"] = -1

    assert store.get("nextcloud")["item_counts"].get("files") == 5


# ---------------------------------------------------------------------------
# M10 — Nextcloud read_file streams and caps
# ---------------------------------------------------------------------------


def _make_nextcloud_client():
    from nextcloud_integration.client import NextcloudClient

    # Construct without connecting; set the attributes read_file needs.
    c = NextcloudClient.__new__(NextcloudClient)
    c._base = "http://nc.example"
    c._username = "u"
    c._auth = ("u", "p")
    return c


def test_nextcloud_read_file_caps_without_buffering(monkeypatch):
    import nextcloud_integration.client as ncmod

    chunks_yielded = {"n": 0}

    class _Resp:
        ok = True
        headers = {"Content-Type": "text/plain"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_content(self, chunk_size=65536):
            # Yield 1MB chunks; the 3rd would exceed the 2MB cap — but we must
            # stop before yielding everything (proves we don't buffer it all).
            for _ in range(10):
                chunks_yielded["n"] += 1
                yield b"x" * (1024 * 1024)

    monkeypatch.setattr(ncmod.requests, "get", lambda *a, **k: _Resp())

    result = _make_nextcloud_client().read_file("/big.bin")
    assert result["content"] is None
    assert "too large" in result["note"].lower()
    # Cap hit after 3 chunks (2MB + 1), NOT after all 10.
    assert chunks_yielded["n"] <= 3


def test_nextcloud_read_file_small_text(monkeypatch):
    import nextcloud_integration.client as ncmod

    class _Resp:
        ok = True
        headers = {"Content-Type": "text/plain; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_content(self, chunk_size=65536):
            yield b"hello world"

    monkeypatch.setattr(ncmod.requests, "get", lambda *a, **k: _Resp())

    result = _make_nextcloud_client().read_file("/small.txt")
    assert result["content"] == "hello world"
    assert result["size"] == 11


# ---------------------------------------------------------------------------
# L1 — backup manifest app_version reflects the constructed version
# ---------------------------------------------------------------------------


def test_backup_manifest_app_version(tmp_project: Path):
    from backup.manager import BackupManager

    bm = BackupManager(tmp_project, app_version="9.9.9")
    zip_path = bm.create_export()
    with zipfile.ZipFile(zip_path, "r") as zf:
        import json

        manifest = json.loads(zf.read("athena_backup_manifest.json"))
    assert manifest["app_version"] == "9.9.9"


# ---------------------------------------------------------------------------
# L2 — vCard multi-value email/phone survive parse → reconstruct
# ---------------------------------------------------------------------------


def test_vcard_multi_value_roundtrip():
    from dav_io.vcf_io import export_vcf, parse_vcf_string

    vcf = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Jane\r\n"
        "EMAIL:jane@work.com\r\nEMAIL:jane@home.com\r\n"
        "TEL:+15550001\r\nTEL:+15550002\r\nEND:VCARD\r\n"
    )
    parsed, errs = parse_vcf_string(vcf)
    assert not errs
    e = parsed[0]
    assert e["emails"] == ["jane@work.com", "jane@home.com"]
    assert e["phones"] == ["+15550001", "+15550002"]
    assert e["email"] == "jane@work.com"  # singular = first (backward compat)

    out = export_vcf(
        [{"uid": "u", "fn": "Jane", "emails": e["emails"], "phones": e["phones"]}],
        carddav_client=None,
    )
    assert "jane@work.com" in out and "jane@home.com" in out
    assert "+15550001" in out and "+15550002" in out
