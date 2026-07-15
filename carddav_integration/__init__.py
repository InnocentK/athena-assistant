"""carddav_integration — the CardDAV NETWORK client (address books,
contacts, staged merge workflow). All HTTP flows through the
CardDAVClient._request chokepoint (timeout M26.12 + same-origin guard M26.13);
writes (commit_merge, delete_contact) are human-gated. vCard parsing is NOT
here — that's dav_io/vcf_io.py (+ vcard_helpers.py locally).

Files: client.py, vcard_helpers.py. Tests: tests/test_carddav_safety.py,
tests/test_dav_transport.py, tests/test_dav_ssrf.py."""
