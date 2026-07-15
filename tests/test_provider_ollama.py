"""
tests/test_provider_ollama.py — Tests for providers/ollama.py (OllamaAdapter).

All tests are fully mocked and never contact a real Ollama server: the openai
SDK client is patched, and OLLAMA_* environment variables are set explicitly
per test. An autouse fixture clears the OLLAMA_* environment first so tests are
deterministic regardless of the host environment.
"""

from __future__ import annotations

import sys

import httpx
import pytest

from providers.base import Message
from providers.ollama import (
    DEFAULT_BASE_URL,
    HEALTHCHECK_TIMEOUT,
    OllamaAdapter,
)


@pytest.fixture(autouse=True)
def _clear_ollama_env(monkeypatch: pytest.MonkeyPatch):
    """Guarantee a clean OLLAMA_* environment for every test."""
    for var in ("OLLAMA_API_URL", "OLLAMA_MODEL", "OLLAMA_API_KEY", "OLLAMA_TIMEOUT"):
        monkeypatch.delenv(var, raising=False)


def _fake_completion(mocker, content: str = "hello from ollama"):
    """Build a fake OpenAI chat-completion response object."""
    resp = mocker.MagicMock()
    choice = mocker.MagicMock()
    choice.message.content = content
    resp.choices = [choice]
    return resp


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_name_and_cost_tier():
    adapter = OllamaAdapter()
    assert adapter.name() == "ollama"
    assert adapter.cost_tier() == "low"


# ---------------------------------------------------------------------------
# is_available() — health check
# ---------------------------------------------------------------------------


def test_is_available_true_when_model_set_and_healthy(monkeypatch, mocker):
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4")
    fake_client = mocker.MagicMock()
    ctor = mocker.patch("openai.OpenAI", return_value=fake_client)

    assert OllamaAdapter().is_available() is True

    fake_client.models.list.assert_called_once()
    kwargs = ctor.call_args.kwargs
    assert kwargs["timeout"] == HEALTHCHECK_TIMEOUT  # short, keeps routing snappy
    assert kwargs["max_retries"] == 0
    assert kwargs["base_url"] == DEFAULT_BASE_URL


def test_is_available_false_when_model_unset(mocker):
    ctor = mocker.patch("openai.OpenAI")
    # OLLAMA_MODEL is not set (cleared by the autouse fixture)
    assert OllamaAdapter().is_available() is False
    ctor.assert_not_called()  # no network probe is attempted without a model


def test_is_available_false_when_unreachable(monkeypatch, mocker):
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4")
    fake_client = mocker.MagicMock()
    fake_client.models.list.side_effect = Exception("connection refused")
    mocker.patch("openai.OpenAI", return_value=fake_client)

    assert OllamaAdapter().is_available() is False  # never raises


def test_is_available_false_when_openai_missing(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4")
    monkeypatch.setitem(sys.modules, "openai", None)  # forces ImportError on `import openai`
    assert OllamaAdapter().is_available() is False


def test_is_available_uses_custom_endpoint(monkeypatch, mocker):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.6")
    monkeypatch.setenv("OLLAMA_API_URL", "http://192.168.1.20:11434/v1")
    fake_client = mocker.MagicMock()
    ctor = mocker.patch("openai.OpenAI", return_value=fake_client)

    assert OllamaAdapter().is_available() is True
    assert ctor.call_args.kwargs["base_url"] == "http://192.168.1.20:11434/v1"


# ---------------------------------------------------------------------------
# complete() — happy path
# ---------------------------------------------------------------------------


def test_complete_happy_path(monkeypatch, mocker):
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4")
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = _fake_completion(mocker, "hi there")
    mocker.patch("openai.OpenAI", return_value=fake_client)

    resp = OllamaAdapter().complete([Message(role="user", content="hello")], None)

    assert resp.success is True
    assert resp.content == "hi there"
    assert resp.provider_name == "ollama"
    assert resp.model == "gemma4"


def test_complete_passes_system_prompt_and_message_order(monkeypatch, mocker):
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4")
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = _fake_completion(mocker)
    mocker.patch("openai.OpenAI", return_value=fake_client)

    messages = [
        Message(role="user", content="first"),
        Message(role="assistant", content="second"),
        Message(role="user", content="third"),
    ]
    OllamaAdapter().complete(messages, system_prompt="be terse")

    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gemma4"
    assert kwargs["messages"][0] == {"role": "system", "content": "be terse"}
    assert [m["content"] for m in kwargs["messages"]] == [
        "be terse",
        "first",
        "second",
        "third",
    ]


def test_complete_honours_custom_timeout(monkeypatch, mocker):
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4")
    monkeypatch.setenv("OLLAMA_TIMEOUT", "45")
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = _fake_completion(mocker)
    ctor = mocker.patch("openai.OpenAI", return_value=fake_client)

    OllamaAdapter().complete([Message(role="user", content="x")], None)

    assert ctor.call_args.kwargs["timeout"] == 45.0
    assert ctor.call_args.kwargs["max_retries"] == 0


# ---------------------------------------------------------------------------
# complete() — failure modes (must never raise)
# ---------------------------------------------------------------------------


def test_complete_missing_model_returns_error(mocker):
    ctor = mocker.patch("openai.OpenAI")
    resp = OllamaAdapter().complete([Message(role="user", content="x")], None)

    assert resp.success is False
    assert "OLLAMA_MODEL" in (resp.error or "")
    ctor.assert_not_called()  # no client built / no network when misconfigured


def test_complete_generic_exception_is_caught(monkeypatch, mocker):
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4")
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.side_effect = RuntimeError("boom")
    mocker.patch("openai.OpenAI", return_value=fake_client)

    resp = OllamaAdapter().complete([Message(role="user", content="x")], None)

    assert resp.success is False
    assert "boom" in (resp.error or "")
    assert resp.provider_name == "ollama"


def test_complete_connection_error_friendly_message(monkeypatch, mocker):
    import openai

    monkeypatch.setenv("OLLAMA_MODEL", "gemma4")
    req = httpx.Request("POST", "http://localhost:11434/v1/chat/completions")
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.side_effect = openai.APIConnectionError(
        message="refused", request=req
    )
    mocker.patch("openai.OpenAI", return_value=fake_client)

    resp = OllamaAdapter().complete([Message(role="user", content="x")], None)

    assert resp.success is False
    assert "Ollama" in (resp.error or "")


def test_complete_timeout_friendly_message(monkeypatch, mocker):
    import openai

    monkeypatch.setenv("OLLAMA_MODEL", "gemma4")
    req = httpx.Request("POST", "http://localhost:11434/v1/chat/completions")
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.side_effect = openai.APITimeoutError(req)
    mocker.patch("openai.OpenAI", return_value=fake_client)

    resp = OllamaAdapter().complete([Message(role="user", content="x")], None)

    assert resp.success is False
    assert "Timeout" in (resp.error or "")


def test_complete_openai_missing_returns_error(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4")
    monkeypatch.setitem(sys.modules, "openai", None)  # forces ImportError

    resp = OllamaAdapter().complete([Message(role="user", content="x")], None)

    assert resp.success is False
    assert "openai" in (resp.error or "").lower()
