"""nextcloud_integration — read-only Nextcloud NETWORK client (WebDAV
files + OCS notes/activity/user). Fixed base URL (no caller-supplied hosts),
15s timeouts, 2MB streaming read cap, defusedxml parsing (M26.15).

File: client.py. Tests: tests/test_nextcloud_correctness.py,
tests/test_dav_correctness.py."""
