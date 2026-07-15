"""backup — export zip + manifest, dry-run restore diff, staged restore.
Zip-Slip-safe (_safe_target) and diff_token-gated at the API layer; .env is
never included. LOCAL disk only — no network.

File: manager.py. Tests: tests/test_backup.py, tests/test_write_safety.py,
tests/test_ops_hardening.py."""
