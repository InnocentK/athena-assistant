"""
audit/ — Athena operational and import/backup audit logs.

This package holds audit *source* (notably `ops_audit.write_ops_event`)
alongside the runtime `*.log` files it writes at run time. Only the
generated `*.log` files are gitignored; the Python source in this package
is tracked and shipped like any other module.

See `ops_audit.py` for the structured JSON-lines operational audit log
introduced in Milestone 15.
"""
