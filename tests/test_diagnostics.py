"""
tests/test_diagnostics.py — Provider latency instrumentation (Milestone 22).

Measure-only. Verifies that routing is instrumented (timing, attribution,
outcomes) without changing routing behaviour, that no message content leaks
into the trace, and that the in-memory store behaves. Fully mocked.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from diagnostics.store import (
    DiagnosticsStore,
    ProviderCallRecord,
    RequestTrace,
    classify_error_kind,
    format_summary,
    get_diagnostics_store,
    short_error,
)
from providers.base import Message, ProviderResponse

_REAL_ROOT = Path(__file__).parent.parent


@pytest.fixture(autouse=True)
def _reset_store():
    get_diagnostics_store().reset()
    yield
    get_diagnostics_store().reset()


@pytest.fixture
def router(tmp_path, monkeypatch):
    import core.config as cc

    monkeypatch.setattr(cc, "APP_ROOT", tmp_path)
    cc.get_settings.cache_clear()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    shutil.copy(_REAL_ROOT / "config" / "providers.yaml", config_dir / "providers.yaml")

    from providers.router import ProviderRouter

    return ProviderRouter()


def _adapter(available=True, success=True, transport=None, raises=None, error=None, model="m"):
    meta = {"transport": transport} if transport else {}

    class _A:
        def is_available(self):
            return available

        def complete(self, msgs, sp):
            if raises is not None:
                raise raises
            return ProviderResponse(
                content="ANSWER", provider_name="x", model=model,
                success=success, error=error, metadata=dict(meta),
            )

    return _A()


def _wire(router, adapters, configs):
    router._all_adapters = adapters
    router._adapter_configs = configs
    router._ranking = {"balanced": list(adapters.keys())}
    router._fallback_on_error = True


# ---------------------------------------------------------------------------
# Unit: store / formatter / classifier
# ---------------------------------------------------------------------------


def test_classify_error_kind():
    assert classify_error_kind("ok", None) is None
    assert classify_error_kind("unavailable", "x") is None
    assert classify_error_kind("failure", "Timeout: ...") == "timeout"
    assert classify_error_kind("failure", "Connection error: could not reach Grok") == "api_error"
    assert classify_error_kind("failure", "Subprocess error: boom") == "cli_error"
    assert classify_error_kind("failure", "weird") == "provider_failure"
    assert classify_error_kind("exception", None, RuntimeError("x")) == "exception"
    assert classify_error_kind("exception", None, TimeoutError("x")) == "timeout"


def test_short_error_truncates():
    assert short_error(None) is None
    assert short_error("") is None
    assert len(short_error("e" * 500)) <= 200


def test_format_summary_shape():
    t = RequestTrace(request_id="abc", mode="balanced", selected="grok")
    t.add(ProviderCallRecord(provider="claude", transport="cli", outcome="unavailable", duration_ms=0))
    t.add(ProviderCallRecord(provider="grok", transport="api", outcome="ok", duration_ms=842))
    s = format_summary(t)
    assert "req=abc" in s and "selected=grok" in s and "attempts=2" in s
    assert "claude/cli unavailable" in s and "grok/api ok" in s


def test_store_ring_buffer_bounded():
    store = DiagnosticsStore(maxlen=2)
    for i in range(5):
        store.record(RequestTrace(request_id=f"r{i}"))
    recent = store.recent()
    assert len(recent) == 2
    assert recent[0]["request_id"] == "r3"
    assert store.last()["request_id"] == "r4"


# ---------------------------------------------------------------------------
# Router integration
# ---------------------------------------------------------------------------


def test_trace_attached_and_stored(router):
    _wire(router, {"x": _adapter(transport="api")}, {"x": {"enabled": True, "type": "api"}})
    resp = router.route([Message(role="user", content="hi")], None, {"routing": {"mode": "balanced"}})
    assert resp.success is True
    diag = resp.metadata["diagnostics"]
    assert diag["selected"] == "x"
    assert len(diag["records"]) == 1
    assert diag["records"][0]["transport"] == "api"
    assert diag["records"][0]["outcome"] == "ok"
    assert diag["records"][0]["model"] == "m"
    assert len(get_diagnostics_store().recent()) == 1


def test_transport_from_config_type_when_no_metadata(router):
    _wire(router, {"x": _adapter(transport=None)}, {"x": {"enabled": True, "type": "cli"}})
    resp = router.route([Message(role="user", content="hi")], None, {"routing": {"mode": "balanced"}})
    assert resp.metadata["diagnostics"]["records"][0]["transport"] == "cli"


def test_unavailable_then_fallback_recorded(router):
    _wire(
        router,
        {"a": _adapter(available=False), "b": _adapter(transport="api")},
        {"a": {"enabled": True, "type": "cli"}, "b": {"enabled": True, "type": "api"}},
    )
    resp = router.route([Message(role="user", content="hi")], None, {"routing": {"mode": "balanced"}})
    diag = resp.metadata["diagnostics"]
    assert resp.provider_name == "x"  # 'b' answered (provider_name from the response)
    assert diag["selected"] == "b"
    assert [r["provider"] for r in diag["records"]] == ["a", "b"]
    assert diag["records"][0]["outcome"] == "unavailable"
    assert diag["records"][1]["outcome"] == "ok"


def test_exception_recorded(router):
    _wire(router, {"x": _adapter(raises=RuntimeError("boom"))}, {"x": {"enabled": True, "type": "api"}})
    resp = router.route([Message(role="user", content="hi")], None, {"routing": {"mode": "balanced"}})
    assert resp.success is False
    rec = resp.metadata["diagnostics"]["records"][0]
    assert rec["outcome"] == "exception"
    assert rec["error_kind"] == "exception"
    assert "boom" in rec["error"]


def test_failure_recorded_with_error_kind(router):
    _wire(
        router,
        {"x": _adapter(success=False, error="Timeout: grok did not respond")},
        {"x": {"enabled": True, "type": "cli"}},
    )
    resp = router.route([Message(role="user", content="hi")], None, {"routing": {"mode": "balanced"}})
    rec = resp.metadata["diagnostics"]["records"][0]
    assert rec["outcome"] == "failure"
    assert rec["error_kind"] == "timeout"


def test_disabled_produces_no_trace(router):
    router._diag_enabled = False
    _wire(router, {"x": _adapter(transport="api")}, {"x": {"enabled": True, "type": "api"}})
    resp = router.route([Message(role="user", content="hi")], None, {"routing": {"mode": "balanced"}})
    assert resp.success is True  # routing unaffected
    assert "diagnostics" not in resp.metadata
    assert len(get_diagnostics_store().recent()) == 0


def test_no_message_content_in_trace(router):
    _wire(router, {"x": _adapter(transport="api")}, {"x": {"enabled": True, "type": "api"}})
    resp = router.route(
        [Message(role="user", content="SECRET123")], "SYSPROMPT", {"routing": {"mode": "balanced"}}
    )
    dump = json.dumps(resp.metadata["diagnostics"])
    assert "SECRET123" not in dump
    assert "SYSPROMPT" not in dump
    assert "ANSWER" not in dump


def test_timing_recorded_deterministic(router, mocker):
    # 6 perf_counter calls for one available+success provider:
    # t_start, avail_t0, avail_end, call_t0, call_end, total
    mocker.patch(
        "providers.router.time.perf_counter",
        side_effect=[0.0, 10.0, 11.0, 11.0, 16.0, 20.0],
    )
    _wire(router, {"x": _adapter(transport="api")}, {"x": {"enabled": True, "type": "api"}})
    resp = router.route([Message(role="user", content="hi")], None, {"routing": {"mode": "balanced"}})
    diag = resp.metadata["diagnostics"]
    rec = diag["records"][0]
    assert rec["availability_ms"] == pytest.approx(1000.0)
    assert rec["call_ms"] == pytest.approx(5000.0)
    assert rec["duration_ms"] == pytest.approx(6000.0)
    assert diag["total_ms"] == pytest.approx(20000.0)
