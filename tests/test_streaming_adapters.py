"""
tests/test_streaming_adapters.py — M30 adapter streaming contract.

Fully mocked (no real SDK/network): openai.OpenAI is patched and streams are
plain iterators of SimpleNamespace chunk objects, so the adapters' defensive
getattr-walks are exercised against honest attribute shapes (MagicMock would
auto-create truthy attributes and mask bugs).

Contract under test (providers/base.py):
  - supports_streaming(): chatgpt/ollama True; grok True iff transport==api;
    base default False.
  - complete_stream(): yields text chunks (str), then EXACTLY ONE final
    ProviderResponse — assembled full content; usage only when the backend
    provided it; mid-stream errors yield a failure response with the same
    error strings as complete(); never raises.
  - M30 cross-adapter norm: empty output is a failure in BOTH modes.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from providers.base import Message, ProviderAdapter, ProviderResponse
from providers.chatgpt import ChatGPTAPIAdapter
from providers.grok import GrokAdapter
from providers.ollama import OllamaAdapter


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    """Deterministic provider env for every test."""
    for var in (
        "OLLAMA_API_URL", "OLLAMA_MODEL", "OLLAMA_API_KEY", "OLLAMA_TIMEOUT",
        "OPENAI_API_KEY", "OPENAI_TIMEOUT",
        "XAI_API_KEY", "GROK_MODEL", "GROK_API_URL", "GROK_TIMEOUT", "GROK_TRANSPORT",
    ):
        monkeypatch.delenv(var, raising=False)


def _chunk(text: str | None = None, usage: SimpleNamespace | None = None):
    """One fake SDK stream chunk: .choices[0].delta.content (+ optional .usage)."""
    choices = (
        [SimpleNamespace(delta=SimpleNamespace(content=text))] if text is not None else []
    )
    if usage is not None:
        return SimpleNamespace(choices=choices, usage=usage)
    return SimpleNamespace(choices=choices)


def _usage(prompt=7, completion=3, total=10):
    return SimpleNamespace(
        prompt_tokens=prompt, completion_tokens=completion, total_tokens=total
    )


_MSGS = [Message(role="user", content="hello")]


# ---------------------------------------------------------------------------
# Base class defaults
# ---------------------------------------------------------------------------


def test_base_defaults_not_streaming():
    class _Plain(ProviderAdapter):
        def name(self):
            return "plain"

        def is_available(self):
            return True

        def cost_tier(self):
            return "low"

        def complete(self, messages, system_prompt=None):
            return ProviderResponse(content="x", provider_name="plain")

    adapter = _Plain()
    assert adapter.supports_streaming() is False
    with pytest.raises(NotImplementedError):
        adapter.complete_stream(_MSGS)


# ---------------------------------------------------------------------------
# ChatGPT — streams with include_usage
# ---------------------------------------------------------------------------


def test_chatgpt_supports_streaming():
    assert ChatGPTAPIAdapter().supports_streaming() is True


def test_chatgpt_stream_happy_path(mocker):
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = iter(
        [_chunk("Hel"), _chunk("lo"), _chunk(None, usage=_usage())]
    )
    mocker.patch("openai.OpenAI", return_value=fake_client)

    events = list(ChatGPTAPIAdapter().complete_stream(_MSGS, "be terse"))

    assert events[:2] == ["Hel", "lo"]
    final = events[-1]
    assert isinstance(final, ProviderResponse)
    assert final.success is True
    assert final.content == "Hello"
    assert final.provider_name == "chatgpt"
    # usage came from the include_usage final chunk
    assert final.metadata["usage"] == {
        "prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10,
    }
    # exactly one final response, after all text chunks
    assert [e for e in events if isinstance(e, ProviderResponse)] == [final]

    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert kwargs["stream"] is True
    assert kwargs["stream_options"] == {"include_usage": True}
    assert kwargs["messages"][0] == {"role": "system", "content": "be terse"}


def test_chatgpt_stream_client_is_bounded(mocker):
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = iter([_chunk("x")])
    ctor = mocker.patch("openai.OpenAI", return_value=fake_client)

    list(ChatGPTAPIAdapter().complete_stream(_MSGS))

    assert ctor.call_args.kwargs["max_retries"] == 0
    assert ctor.call_args.kwargs["timeout"] == 120.0  # DEFAULT_API_TIMEOUT


def test_chatgpt_stream_midstream_exception_yields_failure(mocker):
    def _explode():
        yield _chunk("partial ")
        raise RuntimeError("connection dropped")

    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = _explode()
    mocker.patch("openai.OpenAI", return_value=fake_client)

    events = list(ChatGPTAPIAdapter().complete_stream(_MSGS))

    assert events[0] == "partial "
    final = events[-1]
    assert isinstance(final, ProviderResponse)
    assert final.success is False
    assert "connection dropped" in (final.error or "")
    # a failure after chunks still terminates the generator cleanly
    assert len(events) == 2


def test_chatgpt_stream_timeout_error_string_matches_buffered(mocker):
    import openai

    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.side_effect = openai.APITimeoutError(
        request=mocker.MagicMock()
    )
    mocker.patch("openai.OpenAI", return_value=fake_client)

    events = list(ChatGPTAPIAdapter().complete_stream(_MSGS))

    assert len(events) == 1
    assert events[0].success is False
    assert "Timeout: ChatGPT API did not respond within" in (events[0].error or "")


def test_chatgpt_stream_empty_output_is_failure(mocker):
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = iter([_chunk(None)])
    mocker.patch("openai.OpenAI", return_value=fake_client)

    events = list(ChatGPTAPIAdapter().complete_stream(_MSGS))

    assert len(events) == 1
    assert events[0].success is False
    assert "returned no output" in (events[0].error or "")


def test_chatgpt_stream_missing_sdk_yields_failure(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", None)  # ImportError on import
    events = list(ChatGPTAPIAdapter().complete_stream(_MSGS))
    assert len(events) == 1
    assert events[0].success is False
    assert "not installed" in (events[0].error or "")


# ---------------------------------------------------------------------------
# Ollama — streams WITHOUT include_usage (compat), usage honest-absent
# ---------------------------------------------------------------------------


def test_ollama_supports_streaming():
    assert OllamaAdapter().supports_streaming() is True


def test_ollama_stream_happy_path_no_stream_options(monkeypatch, mocker):
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4")
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = iter(
        [_chunk("a"), _chunk("b"), _chunk("c")]
    )
    mocker.patch("openai.OpenAI", return_value=fake_client)

    events = list(OllamaAdapter().complete_stream(_MSGS))

    assert events[:3] == ["a", "b", "c"]
    final = events[-1]
    assert final.success is True and final.content == "abc"
    assert final.model == "gemma4"
    assert "usage" not in final.metadata  # honest absence, never fabricated

    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert kwargs["stream"] is True
    assert "stream_options" not in kwargs  # compat risk — deliberately not sent


def test_ollama_stream_records_usage_if_server_volunteers_it(monkeypatch, mocker):
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4")
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = iter(
        [_chunk("hi", usage=_usage(1, 2, 3))]
    )
    mocker.patch("openai.OpenAI", return_value=fake_client)

    final = list(OllamaAdapter().complete_stream(_MSGS))[-1]
    assert final.metadata["usage"] == {
        "prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3,
    }


def test_ollama_stream_without_model_fails_before_any_call(mocker):
    ctor = mocker.patch("openai.OpenAI")
    events = list(OllamaAdapter().complete_stream(_MSGS))
    assert len(events) == 1
    assert events[0].success is False
    assert "OLLAMA_MODEL" in (events[0].error or "")
    ctor.assert_not_called()


# ---------------------------------------------------------------------------
# Grok — streaming rides the API transport only
# ---------------------------------------------------------------------------


def test_grok_cli_transport_does_not_stream():
    adapter = GrokAdapter()  # default transport: cli
    assert adapter.supports_streaming() is False
    with pytest.raises(NotImplementedError):
        adapter.complete_stream(_MSGS)  # raises at CALL time, like the base


def test_grok_api_transport_streams(monkeypatch, mocker):
    monkeypatch.setenv("GROK_TRANSPORT", "api")
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    assert GrokAdapter().supports_streaming() is True

    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = iter([_chunk("G"), _chunk("k")])
    mocker.patch("openai.OpenAI", return_value=fake_client)

    events = list(GrokAdapter().complete_stream(_MSGS))

    assert events[:2] == ["G", "k"]
    final = events[-1]
    assert final.success is True and final.content == "Gk"
    assert final.metadata["transport"] == "api"
    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert kwargs["stream"] is True
    assert "stream_options" not in kwargs  # x.ai compat — deliberately not sent


def test_grok_stream_without_key_fails(monkeypatch, mocker):
    monkeypatch.setenv("GROK_TRANSPORT", "api")
    monkeypatch.setenv("XAI_API_KEY", "xai-test")  # passes the dispatcher…
    adapter = GrokAdapter()
    monkeypatch.delenv("XAI_API_KEY")  # …but gone when the generator runs
    mocker.patch("openai.OpenAI")

    events = list(adapter.complete_stream(_MSGS))
    assert len(events) == 1
    assert events[0].success is False
    assert "XAI_API_KEY" in (events[0].error or "")


# ---------------------------------------------------------------------------
# M30 cross-adapter norm: empty output is a failure in BUFFERED mode too
# ---------------------------------------------------------------------------


def _empty_completion(mocker):
    resp = mocker.MagicMock()
    choice = mocker.MagicMock()
    choice.message.content = ""
    resp.choices = [choice]
    resp.usage = None
    return resp


def test_chatgpt_buffered_empty_output_is_failure(monkeypatch, mocker):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = _empty_completion(mocker)
    mocker.patch("openai.OpenAI", return_value=fake_client)

    resp = ChatGPTAPIAdapter().complete(_MSGS)
    assert resp.success is False
    assert "returned no output" in (resp.error or "")


def test_ollama_buffered_empty_output_is_failure(monkeypatch, mocker):
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4")
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = _empty_completion(mocker)
    mocker.patch("openai.OpenAI", return_value=fake_client)

    resp = OllamaAdapter().complete(_MSGS)
    assert resp.success is False
    assert "returned no output" in (resp.error or "")


def test_grok_api_buffered_empty_output_is_failure(monkeypatch, mocker):
    monkeypatch.setenv("GROK_TRANSPORT", "api")
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = _empty_completion(mocker)
    mocker.patch("openai.OpenAI", return_value=fake_client)

    resp = GrokAdapter().complete(_MSGS)
    assert resp.success is False
    assert "Grok API returned no output" in (resp.error or "")


def test_grok_cli_empty_stdout_is_failure(mocker):
    result = mocker.MagicMock(returncode=0, stdout="   \n", stderr="")
    mocker.patch("subprocess.run", return_value=result)

    resp = GrokAdapter().complete(_MSGS)
    assert resp.success is False
    assert "Grok CLI returned no output" in (resp.error or "")


def test_gemini_empty_stdout_is_failure(mocker):
    from providers.gemini import GeminiAdapter

    result = mocker.MagicMock(returncode=0, stdout="", stderr="")
    mocker.patch("subprocess.run", return_value=result)

    resp = GeminiAdapter().complete(_MSGS)
    assert resp.success is False
    assert "Gemini CLI returned no output" in (resp.error or "")
