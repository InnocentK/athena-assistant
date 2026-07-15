"""
diagnostics/store.py — Provider latency data model + in-memory store (Milestone 22).

Measure-only. Records attribution + timing for each provider attempt during
`ProviderRouter.route()`. **No message/prompt/response content is ever stored** —
only provider/transport/model/timing/outcome and a short, truncated error string.

  ProviderCallRecord — one provider attempt.
  RequestTrace       — one route() call (a list of records + summary fields).
  DiagnosticsStore   — bounded in-memory ring buffer of recent traces (singleton),
                       lost on restart; no persistence. Lock-guarded (M26.16).

The trace is also attached to `ProviderResponse.metadata["diagnostics"]` so M24
(web UI) and M25 (CLI) can consume it later. In M22 it is not surfaced to users.
"""

from __future__ import annotations

import threading
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_request_id() -> str:
    return uuid.uuid4().hex[:8]


def short_error(error: object | None, limit: int = 200) -> str | None:
    """Truncate an error to a short, traceback-free string (or None)."""
    if error is None:
        return None
    text = str(error)
    if not text:
        return None
    clean = text[:limit]
    for marker in ('File "', "Traceback"):
        if marker in clean:
            clean = clean[: clean.index(marker)].strip()
    return clean.strip() or None


def classify_error_kind(
    outcome: str, error: object | None, exc: BaseException | None = None
) -> str | None:
    """
    Bucket a failed attempt into a coarse, content-free kind for diagnostics.

    Returns None for non-error outcomes ("ok", "skipped", "unavailable").
    """
    if outcome in ("ok", "skipped", "unavailable"):
        return None

    if exc is not None:
        return "timeout" if "Timeout" in type(exc).__name__ else "exception"

    low = str(error or "").lower()
    if "timeout" in low or "timed out" in low:
        return "timeout"
    if "connection error" in low or "could not reach" in low:
        return "api_error"
    if "subprocess error" in low or "non-zero exit" in low:
        return "cli_error"
    return "provider_failure"


@dataclass
class ProviderCallRecord:
    """One provider attempt during routing (timing + attribution, no content)."""

    provider: str
    transport: str = "unknown"        # cli | api | stub | unknown (canonical: metadata.transport)
    model: str | None = None
    outcome: str = "ok"               # ok | skipped | unavailable | failure | exception
    error_kind: str | None = None
    error: str | None = None
    started_at: str = field(default_factory=_now_iso)
    availability_ms: float = 0.0      # time in is_available()
    call_ms: float = 0.0              # time in complete() (0.0 if never reached)
    duration_ms: float = 0.0          # availability_ms + call_ms

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RequestTrace:
    """The latency ledger for one route() call."""

    request_id: str = field(default_factory=new_request_id)
    started_at: str = field(default_factory=_now_iso)
    total_ms: float = 0.0
    mode: str = ""
    attempt_order: list[str] = field(default_factory=list)
    selected: str | None = None
    records: list[ProviderCallRecord] = field(default_factory=list)

    def add(self, record: ProviderCallRecord) -> None:
        self.records.append(record)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def format_summary(trace: RequestTrace) -> str:
    """One-line, parseable summary of a request trace (no message content)."""
    inner = "; ".join(
        f"{r.provider}/{r.transport} {r.outcome} {r.duration_ms:.0f}ms" for r in trace.records
    )
    return (
        f"Router latency req={trace.request_id} "
        f"selected={trace.selected or 'none'} total_ms={trace.total_ms:.0f} "
        f"attempts={len(trace.records)} trace=[{inner}]"
    )


class DiagnosticsStore:
    """Bounded in-memory ring buffer of recent RequestTrace dicts (singleton)."""

    def __init__(self, maxlen: int = 50) -> None:
        # M26.16: route() records from to_thread worker threads while the
        # diagnostics endpoints list the deque on the loop thread — iterating
        # a deque during a concurrent append raises RuntimeError, so all
        # access holds this lock.
        self._lock = threading.Lock()
        self._maxlen = maxlen
        self._traces: Deque[dict[str, Any]] = deque(maxlen=maxlen)

    def set_maxlen(self, maxlen: int) -> None:
        with self._lock:
            if maxlen > 0 and maxlen != self._maxlen:
                self._maxlen = maxlen
                self._traces = deque(self._traces, maxlen=maxlen)

    def record(self, trace: RequestTrace) -> None:
        try:
            with self._lock:
                self._traces.append(trace.as_dict())
        except Exception:  # noqa: BLE001 — diagnostics must never break the caller
            pass

    def recent(self, limit: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._traces)
        return items[-limit:] if limit is not None else items

    def last(self) -> dict[str, Any] | None:
        with self._lock:
            return self._traces[-1] if self._traces else None

    def reset(self) -> None:
        with self._lock:
            self._traces.clear()


# ---------------------------------------------------------------------------
# Module-level singleton (mirrors dav_status/store.py)
# ---------------------------------------------------------------------------

_store = DiagnosticsStore()


def get_diagnostics_store() -> DiagnosticsStore:
    """Return the module-level singleton DiagnosticsStore."""
    return _store
