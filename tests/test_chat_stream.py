"""
tests/test_chat_stream.py — M30 POST /chat/stream (SSE).

Fully mocked router (no providers); real ConversationStore in the tmp profile.

Under test:
  - SSE framing: text/event-stream, `event: chunk` frames then exactly one
    `event: done` whose payload mirrors ChatResponse (+ error).
  - history parity with /chat: user + assistant turns recorded by the time
    the done frame is delivered; conversation_id created/echoed.
  - invalid conversation_id → plain 400 (before any streaming starts).
  - timeout → done frame with success=false / "The request timed out."
  - /chat itself is untouched (covered by the existing suite; a smoke check
    here guards the shared module edit).
"""

from __future__ import annotations

import json
import time

from providers.base import ProviderResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StreamRouter:
    """Fake router exposing route_stream (and route, unused here)."""

    def __init__(self, events=None, delay: float = 0.0):
        self._events = events
        self._delay = delay

    def route(self, messages, system_prompt, profile_config, on_attempt=None):
        return ProviderResponse(content="buffered", provider_name="fake", success=True)

    def route_stream(self, messages, system_prompt, profile_config, on_attempt=None):
        if self._delay:
            time.sleep(self._delay)
        events = self._events or [
            ("chunk", "Hel"),
            ("chunk", "lo"),
            (
                "done",
                ProviderResponse(
                    content="Hello",
                    provider_name="fake",
                    model="fm",
                    success=True,
                    metadata={"diagnostics": {"selected": "fake", "records": []}},
                ),
            ),
        ]
        yield from events


def _sse_events(text: str) -> list[tuple[str, dict]]:
    """Parse an SSE body into [(event, payload), …]."""
    events = []
    for raw in text.split("\n\n"):
        if not raw.strip():
            continue
        event, data = "message", ""
        for line in raw.split("\n"):
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = line[len("data:"):].strip()
        events.append((event, json.loads(data)))
    return events


def _post_stream(client, payload):
    resp = client.post("/chat/stream", json=payload)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    return _sse_events(resp.text)


# ---------------------------------------------------------------------------
# Framing + payload
# ---------------------------------------------------------------------------


def test_stream_emits_chunks_then_done(client, monkeypatch):
    import main as app_module

    monkeypatch.setattr(app_module, "_router", _StreamRouter())

    events = _post_stream(client, {"message": "hi"})

    assert [e for e, _ in events] == ["chunk", "chunk", "done"]
    assert [p["text"] for e, p in events if e == "chunk"] == ["Hel", "lo"]
    done = events[-1][1]
    # mirrors ChatResponse: response/provider/model/success/diagnostics (+error)
    assert done["response"] == "Hello"
    assert done["provider"] == "fake"
    assert done["model"] == "fm"
    assert done["success"] is True
    assert done["error"] is None
    assert done["diagnostics"] == {"selected": "fake", "records": []}
    assert done["conversation_id"]  # created for us (M29.1 semantics)


def test_stream_records_history_before_done(client, monkeypatch):
    import main as app_module

    monkeypatch.setattr(app_module, "_router", _StreamRouter())

    events = _post_stream(client, {"message": "hi there"})
    conv_id = events[-1][1]["conversation_id"]

    turns = app_module._history.read(conv_id)
    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert turns[0]["content"] == "hi there"
    assert turns[1]["content"] == "Hello"
    assert turns[1]["success"] is True
    assert turns[1]["provider"] == "fake"


def test_stream_reuses_existing_conversation_id(client, monkeypatch):
    import main as app_module

    monkeypatch.setattr(app_module, "_router", _StreamRouter())

    first = _post_stream(client, {"message": "one"})
    conv_id = first[-1][1]["conversation_id"]
    second = _post_stream(client, {"message": "two", "conversation_id": conv_id})

    assert second[-1][1]["conversation_id"] == conv_id
    turns = app_module._history.read(conv_id)
    assert [t["role"] for t in turns] == ["user", "assistant", "user", "assistant"]


def test_stream_invalid_conversation_id_is_plain_400(client, monkeypatch):
    import main as app_module

    monkeypatch.setattr(app_module, "_router", _StreamRouter())

    resp = client.post(
        "/chat/stream", json={"message": "hi", "conversation_id": "../evil"}
    )
    assert resp.status_code == 400
    assert "Invalid conversation_id" in resp.json()["detail"]


def test_stream_failure_done_carries_error_and_records_turn(client, monkeypatch):
    import main as app_module

    failure = ProviderResponse(
        success=False, content="", provider_name="fake", error="died mid-stream"
    )
    monkeypatch.setattr(
        app_module,
        "_router",
        _StreamRouter(events=[("chunk", "partial "), ("done", failure)]),
    )

    events = _post_stream(client, {"message": "hi"})

    done = events[-1][1]
    assert done["success"] is False
    assert done["error"] == "died mid-stream"
    # the failed assistant turn is persisted with success=false (as /chat)
    turns = app_module._history.read(done["conversation_id"])
    assert turns[-1]["success"] is False


def test_stream_timeout_yields_failure_done(client, monkeypatch):
    import main as app_module

    monkeypatch.setattr(app_module, "_router", _StreamRouter(delay=0.6))
    monkeypatch.setattr(app_module, "_ROUTE_TIMEOUT", 0.05)

    events = _post_stream(client, {"message": "hi"})

    assert [e for e, _ in events] == ["done"]
    done = events[0][1]
    assert done["success"] is False
    assert done["response"] == "The request timed out."
    assert done["provider"] == "none"


def test_buffered_chat_unchanged_smoke(client, monkeypatch):
    """/chat still answers the buffered way with the same fake wired in."""
    import main as app_module

    monkeypatch.setattr(app_module, "_router", _StreamRouter())

    resp = client.post("/chat", json={"message": "hi"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["response"] == "buffered"
    assert body["success"] is True


def test_stream_inlines_attachment_for_provider_but_records_raw(client, monkeypatch):
    """M30.5: the provider-bound message carries the attached file's content;
    the recorded user turn keeps the raw reference form."""
    import core.config as cc
    import main as app_module

    uploads = cc.APP_ROOT / "data" / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / "notes.md").write_text("SECRET-CONTENT-42")

    captured: dict = {}

    class _CapturingRouter(_StreamRouter):
        def route_stream(self, messages, system_prompt, profile_config, on_attempt=None):
            captured["messages"] = messages
            yield from super().route_stream(
                messages, system_prompt, profile_config, on_attempt=on_attempt
            )

    monkeypatch.setattr(app_module, "_router", _CapturingRouter())

    raw = "[Attached file: data/uploads/notes.md]\nsummarize this"
    events = _post_stream(client, {"message": raw})
    conv_id = events[-1][1]["conversation_id"]

    provider_msg = captured["messages"][-1].content
    assert "SECRET-CONTENT-42" in provider_msg          # provider sees content
    assert "--- Attached file content:" in provider_msg

    turns = app_module._history.read(conv_id)
    assert turns[0]["content"] == raw                    # history stays raw
    assert "SECRET-CONTENT-42" not in turns[0]["content"]
