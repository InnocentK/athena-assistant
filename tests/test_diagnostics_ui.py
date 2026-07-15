"""
tests/test_diagnostics_ui.py — Enhanced diagnostics UI (Milestone 24.5).

M24.5 is frontend-only: the provider timeline and details view are reconstructed
at completion from the content-free M22 trace already on
``ChatResponse.diagnostics`` (no backend or transport changes, no streaming).
These tests guard the *contract* the UI depends on — that the trace exposes the
keys the timeline/details read, and that those keys survive the round-trip
through ``/chat`` — plus template-presence of the new in-flight progress bar.
The JS render itself isn't exercised (no JS runtime in the suite; a JS harness
remains future work).
"""

from __future__ import annotations

from diagnostics.store import ProviderCallRecord, RequestTrace
from providers.base import ProviderResponse

# Keys the M24.5 frontend reads (buildTimeline / buildDetails / summary).
_RECORD_KEYS = {
    "provider",
    "transport",
    "model",
    "outcome",
    "error_kind",
    "error",
    "started_at",
    "availability_ms",
    "call_ms",
    "duration_ms",
}
_TRACE_KEYS = {
    "request_id",
    "started_at",
    "total_ms",
    "mode",
    "attempt_order",
    "selected",
    "records",
}


def _sample_trace() -> RequestTrace:
    trace = RequestTrace(
        total_ms=820.0,
        mode="balanced",
        attempt_order=["claude", "grok"],
        selected="grok",
    )
    trace.add(
        ProviderCallRecord(
            provider="claude",
            transport="cli",
            outcome="unavailable",
            error_kind="unavailable",
            availability_ms=40.0,
            duration_ms=40.0,
        )
    )
    trace.add(
        ProviderCallRecord(
            provider="grok",
            transport="api",
            model="grok-4.3",
            outcome="ok",
            availability_ms=20.0,
            call_ms=760.0,
            duration_ms=780.0,
        )
    )
    return trace


def test_record_as_dict_exposes_ui_keys():
    d = ProviderCallRecord(provider="grok").as_dict()
    assert _RECORD_KEYS.issubset(d.keys())


def test_trace_as_dict_exposes_ui_keys():
    d = _sample_trace().as_dict()
    assert _TRACE_KEYS.issubset(d.keys())
    assert isinstance(d["records"], list) and d["records"]
    for rec in d["records"]:
        assert _RECORD_KEYS.issubset(rec.keys())


class _FakeRouter:
    def __init__(self, diag):
        self._diag = diag

    def route(self, messages, system_prompt, profile_config):
        return ProviderResponse(
            content="hi",
            provider_name="grok",
            model="grok-4.3",
            success=True,
            metadata={"diagnostics": self._diag},
        )


def test_chat_diagnostics_roundtrip_preserves_ui_keys(client, monkeypatch):
    import main as app_module

    diag = _sample_trace().as_dict()
    monkeypatch.setattr(app_module, "_router", _FakeRouter(diag))

    body = client.post("/chat", json={"message": "hi"}).json()
    got = body["diagnostics"]
    assert _TRACE_KEYS.issubset(got.keys())
    assert got["selected"] == "grok"
    assert {r["provider"] for r in got["records"]} == {"claude", "grok"}
    # outcome + duration_ms drive the timeline; ensure they survive the round-trip
    for rec in got["records"]:
        assert "outcome" in rec and "duration_ms" in rec


def test_partial_failure_representable_in_records():
    # The timeline colours non-ok attempts differently and the details table shows
    # error_kind; ensure a failed attempt's outcome/error_kind survive as_dict()
    # alongside the ok selected attempt, with numeric duration_ms for segment widths.
    records = _sample_trace().as_dict()["records"]
    by_provider = {r["provider"]: r for r in records}
    assert by_provider["claude"]["outcome"] == "unavailable"
    assert by_provider["claude"]["error_kind"] == "unavailable"
    assert by_provider["grok"]["outcome"] == "ok"
    assert all(isinstance(r["duration_ms"], (int, float)) for r in records)


def test_index_includes_progress_bar(client):
    html = client.get("/").text
    assert 'id="chat-status"' in html
    assert 'class="progress-bar"' in html


def test_panels_unaffected(client):
    # The richer diagnostics view must not disturb the existing panels.
    html = client.get("/").text
    for needle in ['id="memory-panel"', 'id="settings-panel"', 'id="history-panel"']:
        assert needle in html
