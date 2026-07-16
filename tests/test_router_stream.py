"""
tests/test_router_stream.py — M30 ProviderRouter.route_stream().

One routing loop, two delivery modes: these tests pin the streaming semantics
AND the route()/route_stream() parity that the shared internals guarantee.

Semantics under test:
  - streaming adapter → ("chunk", txt)… then exactly one ("done", resp)
  - non-streaming adapter → ONE buffered chunk + done
  - failure with ZERO chunks emitted → falls through to the next provider
    (identical to route())
  - failure AFTER chunks → stops; the failure is the done event
  - mid-stream exception: zero-chunk → falls through; after chunks → stops
  - stream ending without a final response → synthesized failure (honest)
  - all providers exhausted → same "All providers failed." as route()
  - diagnostics trace attached to the done response; on_attempt fires
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from providers.base import Message, ProviderAdapter, ProviderResponse

_REAL_ROOT = Path(__file__).parent.parent
_MSGS = [Message(role="user", content="hi")]
_PROFILE = {"routing": {"mode": "balanced"}}


# ---------------------------------------------------------------------------
# Fake adapters (real classes, not MagicMock — generator methods matter here)
# ---------------------------------------------------------------------------


class _Streamer(ProviderAdapter):
    """Streaming adapter with a scriptable event tail."""

    def __init__(
        self,
        name: str = "s1",
        chunks: tuple = ("Hel", "lo"),
        final: ProviderResponse | None = None,
        raise_after_chunks: Exception | None = None,
        omit_final: bool = False,
    ):
        self._name = name
        self._chunks = chunks
        self._final = final
        self._raise = raise_after_chunks
        self._omit_final = omit_final
        self.stream_calls = 0
        self.complete_calls = 0

    def name(self):
        return self._name

    def cost_tier(self):
        return "low"

    def is_available(self):
        return True

    def supports_streaming(self):
        return True

    def complete(self, messages, system_prompt=None):
        self.complete_calls += 1
        return ProviderResponse(
            content="buffered-answer", provider_name=self._name, success=True
        )

    def complete_stream(self, messages, system_prompt=None):
        self.stream_calls += 1
        yield from self._chunks
        if self._raise is not None:
            raise self._raise
        if self._omit_final:
            return
        yield self._final or ProviderResponse(
            content="".join(self._chunks),
            provider_name=self._name,
            model="sm",
            success=True,
        )


class _Buffered(ProviderAdapter):
    """Plain non-streaming adapter (base default supports_streaming=False)."""

    def __init__(self, name: str = "b1", success: bool = True):
        self._name = name
        self._success = success
        self.complete_calls = 0

    def name(self):
        return self._name

    def cost_tier(self):
        return "low"

    def is_available(self):
        return True

    def complete(self, messages, system_prompt=None):
        self.complete_calls += 1
        if self._success:
            return ProviderResponse(
                content="whole answer", provider_name=self._name, model="bm", success=True
            )
        return ProviderResponse(
            success=False, content="", provider_name=self._name, error="nope"
        )


@pytest.fixture
def router(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """ProviderRouter backed by a tmp config dir (same pattern as router tests)."""
    import core.config as cc

    monkeypatch.setattr(cc, "APP_ROOT", tmp_path)
    cc.get_settings.cache_clear()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    shutil.copy(_REAL_ROOT / "config" / "providers.yaml", config_dir / "providers.yaml")

    from providers.router import ProviderRouter

    return ProviderRouter()


def _wire(router, adapters: dict, order: list[str]):
    router._all_adapters = dict(adapters)
    router._adapter_configs = {n: {"enabled": True, "type": "api"} for n in adapters}
    router._ranking = {"balanced": order}
    router._fallback_on_error = True


# ---------------------------------------------------------------------------
# Streaming delivery
# ---------------------------------------------------------------------------


def test_stream_chunks_then_exactly_one_done(router):
    _wire(router, {"s1": _Streamer()}, ["s1"])

    events = list(router.route_stream(_MSGS, None, _PROFILE))

    assert [k for k, _ in events] == ["chunk", "chunk", "done"]
    assert [p for k, p in events if k == "chunk"] == ["Hel", "lo"]
    done = events[-1][1]
    assert done.success is True and done.content == "Hello"
    assert done.provider_name == "s1"


def test_stream_done_carries_diagnostics_trace(router):
    _wire(router, {"s1": _Streamer()}, ["s1"])

    done = list(router.route_stream(_MSGS, None, _PROFILE))[-1][1]

    diag = done.metadata.get("diagnostics")
    assert isinstance(diag, dict)
    assert diag["selected"] == "s1"
    assert diag["records"][0]["outcome"] == "ok"


def test_stream_fires_on_attempt(router):
    _wire(router, {"s1": _Streamer()}, ["s1"])
    seen: list[dict] = []

    list(router.route_stream(_MSGS, None, _PROFILE, on_attempt=seen.append))

    assert len(seen) == 1
    assert seen[0]["provider"] == "s1"
    assert seen[0]["mode"] == "balanced"


def test_non_streaming_adapter_degrades_to_one_buffered_chunk(router):
    adapter = _Buffered()
    _wire(router, {"b1": adapter}, ["b1"])

    events = list(router.route_stream(_MSGS, None, _PROFILE))

    assert [k for k, _ in events] == ["chunk", "done"]
    assert events[0][1] == "whole answer"
    assert events[1][1].success is True
    assert adapter.complete_calls == 1  # buffered path used exactly once


# ---------------------------------------------------------------------------
# Fallback semantics
# ---------------------------------------------------------------------------


def test_zero_chunk_failure_falls_through_like_route(router):
    failing = _Streamer(
        name="s1",
        chunks=(),
        final=ProviderResponse(success=False, content="", provider_name="s1", error="dead"),
    )
    backup = _Buffered(name="b1")
    _wire(router, {"s1": failing, "b1": backup}, ["s1", "b1"])

    events = list(router.route_stream(_MSGS, None, _PROFILE))

    done = events[-1][1]
    assert done.success is True and done.provider_name == "b1"
    assert backup.complete_calls == 1
    # the failed attempt is still in the trace
    outcomes = [r["outcome"] for r in done.metadata["diagnostics"]["records"]]
    assert outcomes == ["failure", "ok"]


def test_failure_after_chunks_stops_no_fallthrough(router):
    mid_fail = _Streamer(
        name="s1",
        chunks=("partial ",),
        final=ProviderResponse(
            success=False, content="", provider_name="s1", error="died mid-stream"
        ),
    )
    backup = _Buffered(name="b1")
    _wire(router, {"s1": mid_fail, "b1": backup}, ["s1", "b1"])

    events = list(router.route_stream(_MSGS, None, _PROFILE))

    assert [k for k, _ in events] == ["chunk", "done"]
    done = events[-1][1]
    assert done.success is False and done.provider_name == "s1"
    assert backup.complete_calls == 0  # text was emitted — no provider switch


def test_zero_chunk_exception_falls_through(router):
    exploding = _Streamer(name="s1", chunks=(), raise_after_chunks=RuntimeError("boom"))
    backup = _Buffered(name="b1")
    _wire(router, {"s1": exploding, "b1": backup}, ["s1", "b1"])

    done = list(router.route_stream(_MSGS, None, _PROFILE))[-1][1]

    assert done.success is True and done.provider_name == "b1"


def test_exception_after_chunks_stops_with_failure_done(router):
    exploding = _Streamer(
        name="s1", chunks=("some text ",), raise_after_chunks=RuntimeError("boom")
    )
    backup = _Buffered(name="b1")
    _wire(router, {"s1": exploding, "b1": backup}, ["s1", "b1"])

    events = list(router.route_stream(_MSGS, None, _PROFILE))

    assert [k for k, _ in events] == ["chunk", "done"]
    done = events[-1][1]
    assert done.success is False
    assert "complete_stream" in (done.error or "")
    assert backup.complete_calls == 0


def test_stream_ending_without_final_response_is_synthesized_failure(router):
    silent = _Streamer(name="s1", chunks=(), omit_final=True)
    backup = _Buffered(name="b1")
    _wire(router, {"s1": silent, "b1": backup}, ["s1", "b1"])

    done = list(router.route_stream(_MSGS, None, _PROFILE))[-1][1]

    # zero chunks + synthesized failure → fell through to the backup
    assert done.success is True and done.provider_name == "b1"


def test_all_fail_yields_single_done_same_as_route(router):
    failing = _Streamer(
        name="s1",
        chunks=(),
        final=ProviderResponse(success=False, content="", provider_name="s1", error="dead"),
    )
    _wire(router, {"s1": failing}, ["s1"])

    events = list(router.route_stream(_MSGS, None, _PROFILE))
    assert [k for k, _ in events] == ["done"]
    stream_done = events[0][1]

    # route() leg: a provider whose complete() fails the same way
    _wire(router, {"s1": _Buffered(name="s1", success=False)}, ["s1"])
    buffered = router.route(_MSGS, None, _PROFILE)

    # identical terminal failure both modes
    assert stream_done.success is False and buffered.success is False
    assert stream_done.content == buffered.content == "All providers failed."
    assert stream_done.provider_name == buffered.provider_name == "none"


# ---------------------------------------------------------------------------
# Parity + non-regression of route()
# ---------------------------------------------------------------------------


def test_route_and_route_stream_parity_on_same_fixture(router):
    _wire(router, {"s1": _Streamer(), "b1": _Buffered()}, ["s1", "b1"])

    streamed = list(router.route_stream(_MSGS, None, _PROFILE))[-1][1]
    buffered = router.route(_MSGS, None, _PROFILE)

    assert streamed.provider_name == buffered.provider_name == "s1"
    assert streamed.success and buffered.success
    # route() must keep using complete(), never the stream (M30 non-regression)
    assert buffered.content == "buffered-answer"
    assert streamed.content == "Hello"


def test_route_never_calls_complete_stream(router):
    adapter = _Streamer()
    _wire(router, {"s1": adapter}, ["s1"])

    router.route(_MSGS, None, _PROFILE)

    assert adapter.complete_calls == 1
    assert adapter.stream_calls == 0


def test_preferred_provider_is_tried_first_in_stream_mode(router):
    a = _Streamer(name="s1")
    b = _Streamer(name="s2", chunks=("B",))
    _wire(router, {"s1": a, "s2": b}, ["s1", "s2"])

    profile = {"routing": {"mode": "balanced", "preferred_provider": "s2"}}
    done = list(router.route_stream(_MSGS, None, profile))[-1][1]

    assert done.provider_name == "s2"
    assert a.stream_calls == 0


def test_fallback_disabled_stops_after_first_streaming_failure(router):
    failing = _Streamer(
        name="s1",
        chunks=(),
        final=ProviderResponse(success=False, content="", provider_name="s1", error="dead"),
    )
    backup = _Buffered(name="b1")
    _wire(router, {"s1": failing, "b1": backup}, ["s1", "b1"])
    router._fallback_on_error = False

    events = list(router.route_stream(_MSGS, None, _PROFILE))

    assert [k for k, _ in events] == ["done"]
    assert events[0][1].content == "All providers failed."
    assert backup.complete_calls == 0
