"""caldav_integration — the CalDAV NETWORK client (calendars, events,
VTODO create) with bounded timeouts (M26.12) and same-origin URL guard
(M26.13). ICS parsing/formatting is NOT here — that's dav_io/ics_io.py.

File: client.py. Tests: tests/test_dav_transport.py, tests/test_dav_ssrf.py,
tests/test_concurrency.py."""
