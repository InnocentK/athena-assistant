"""dav_status — in-memory health ledger for the three DAV integrations
(reachability, last error, item counts). Thread-safe singleton (M26.16).

NOT a network client and NOT persistence — it's a runtime status snapshot,
lost on restart. File: store.py. Tests: tests/test_dav_status.py,
tests/test_thread_safety.py."""
