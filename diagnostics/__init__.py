"""
diagnostics/ — Provider latency instrumentation (Milestone 22).

Diagnostics-first and measure-only: this package records WHERE time is spent in
provider routing (which providers were attempted, over which transport, how
long each took, and what failed) without changing any routing behaviour.

See `store.py` for the data model (`ProviderCallRecord`, `RequestTrace`), the
bounded in-memory `DiagnosticsStore` singleton, and helpers. The per-request
trace is also attached to `ProviderResponse.metadata["diagnostics"]` for later
consumption by M24 (web UI) and M25 (CLI). In M22 there is intentionally **no
HTTP endpoint** for this data and it is **not** surfaced to end users.
"""
