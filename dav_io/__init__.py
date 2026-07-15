"""dav_io — LOCAL ICS (iCalendar) and VCF (vCard) logic: parse, format,
RFC 5545 escaping, conflict detection, import/export orchestration.

NOT network I/O — the HTTP clients live in caldav_integration/,
carddav_integration/, and nextcloud_integration/. Files: ics_io.py, vcf_io.py.
Tests: tests/test_dav_io.py, tests/test_dav_correctness.py."""
