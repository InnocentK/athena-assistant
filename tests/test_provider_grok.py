"""
tests/test_provider_grok.py — Tests for providers/grok.py (GrokAdapter, M21).

Fully mocked — no real `grok` CLI, no network, no API key. Covers the explicit
cli/api transport split, the default-CLI guarantee (API is opt-in and never
silently takes over), and error handling for both transports.
"""

from __future__ import annotations

import subprocess

import pytest

from providers.base import Message
from providers.grok import DEFAULT_API_URL, DEFAULT_MODEL, GrokAdapter


@pytest.fixture(autouse=True)
def _clear_grok_env(monkeypatch):
    for var in ("GROK_TRANSPORT", "XAI_API_KEY", "GROK_MODEL", "GROK_API_URL", "GROK_TIMEOUT"):
        monkeypatch.delenv(var, raising=False)


def _fake_completion(mocker, content="hi from grok api"):
    resp = mocker.MagicMock()
    choice = mocker.MagicMock()
    choice.message.content = content
    resp.choices = [choice]
    return resp


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_name_and_cost_tier():
    a = GrokAdapter()
    assert a.name() == "grok"
    assert a.cost_tier() == "low"


# ---------------------------------------------------------------------------
# Transport resolution: GROK_TRANSPORT env > providers.yaml > default cli
# ---------------------------------------------------------------------------


def test_transport_default_cli_when_unset(mocker):
    mocker.patch("providers.grok._transport_from_config", return_value="")
    assert GrokAdapter()._transport() == "cli"


def test_transport_from_providers_yaml(mocker):
    mocker.patch("providers.grok._transport_from_config", return_value="api")
    assert GrokAdapter()._transport() == "api"


def test_transport_env_overrides_config(monkeypatch, mocker):
    mocker.patch("providers.grok._transport_from_config", return_value="api")
    monkeypatch.setenv("GROK_TRANSPORT", "cli")
    assert GrokAdapter()._transport() == "cli"


def test_transport_invalid_env_falls_through(monkeypatch, mocker):
    mocker.patch("providers.grok._transport_from_config", return_value="api")
    monkeypatch.setenv("GROK_TRANSPORT", "nonsense")
    assert GrokAdapter()._transport() == "api"


# ---------------------------------------------------------------------------
# Default-CLI guarantee — the API is never constructed in default mode
# ---------------------------------------------------------------------------


def test_default_uses_cli_and_never_calls_api(mocker):
    mocker.patch("providers.grok._transport_from_config", return_value="")  # default config
    run = mocker.patch(
        "providers.grok.subprocess.run",
        return_value=mocker.MagicMock(returncode=0, stdout="cli answer", stderr=""),
    )
    openai_ctor = mocker.patch("openai.OpenAI")

    resp = GrokAdapter().complete([Message(role="user", content="hi")], None)

    assert resp.success is True
    assert resp.content == "cli answer"
    assert resp.metadata["transport"] == "cli"
    run.assert_called_once()
    openai_ctor.assert_not_called()  # API must NOT be constructed when default/cli


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def test_is_available_cli(mocker):
    mocker.patch("providers.grok._transport_from_config", return_value="cli")
    mocker.patch("providers.grok.shutil.which", return_value="/usr/bin/grok")
    assert GrokAdapter().is_available() is True
    mocker.patch("providers.grok.shutil.which", return_value=None)
    assert GrokAdapter().is_available() is False


def test_is_available_api(monkeypatch):
    monkeypatch.setenv("GROK_TRANSPORT", "api")
    assert GrokAdapter().is_available() is False  # no key
    monkeypatch.setenv("XAI_API_KEY", "xai-123")
    assert GrokAdapter().is_available() is True  # key present (+ openai installed)


# ---------------------------------------------------------------------------
# CLI transport (preserves the original behaviour)
# ---------------------------------------------------------------------------


def test_cli_success(monkeypatch, mocker):
    monkeypatch.setenv("GROK_TRANSPORT", "cli")
    mocker.patch(
        "providers.grok.subprocess.run",
        return_value=mocker.MagicMock(returncode=0, stdout=" hello ", stderr=""),
    )
    resp = GrokAdapter().complete([Message(role="user", content="x")], None)
    assert resp.success is True
    assert resp.content == "hello"
    assert resp.provider_name == "grok"
    assert resp.metadata["transport"] == "cli"


def test_cli_timeout(monkeypatch, mocker):
    monkeypatch.setenv("GROK_TRANSPORT", "cli")
    mocker.patch(
        "providers.grok.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="grok", timeout=120),
    )
    resp = GrokAdapter().complete([Message(role="user", content="x")], None)
    assert resp.success is False
    assert "Timeout" in (resp.error or "")


def test_cli_nonzero_exit(monkeypatch, mocker):
    monkeypatch.setenv("GROK_TRANSPORT", "cli")
    mocker.patch(
        "providers.grok.subprocess.run",
        return_value=mocker.MagicMock(returncode=1, stdout="", stderr="boom"),
    )
    resp = GrokAdapter().complete([Message(role="user", content="x")], None)
    assert resp.success is False
    assert "boom" in (resp.error or "")


# ---------------------------------------------------------------------------
# API transport (OpenAI-compatible)
# ---------------------------------------------------------------------------


def test_api_success(monkeypatch, mocker):
    monkeypatch.setenv("GROK_TRANSPORT", "api")
    monkeypatch.setenv("XAI_API_KEY", "xai-123")
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = _fake_completion(mocker, "grok says hi")
    ctor = mocker.patch("openai.OpenAI", return_value=fake_client)

    resp = GrokAdapter().complete([Message(role="user", content="hello")], "be brief")

    assert resp.success is True
    assert resp.content == "grok says hi"
    assert resp.provider_name == "grok"
    assert resp.model == DEFAULT_MODEL
    assert resp.metadata["transport"] == "api"

    ctor_kwargs = ctor.call_args.kwargs
    assert ctor_kwargs["base_url"] == DEFAULT_API_URL
    assert ctor_kwargs["max_retries"] == 0

    sent = fake_client.chat.completions.create.call_args.kwargs
    assert sent["model"] == DEFAULT_MODEL
    assert sent["messages"][0] == {"role": "system", "content": "be brief"}
    assert sent["messages"][1] == {"role": "user", "content": "hello"}


def test_api_custom_model_and_url(monkeypatch, mocker):
    monkeypatch.setenv("GROK_TRANSPORT", "api")
    monkeypatch.setenv("XAI_API_KEY", "xai-123")
    monkeypatch.setenv("GROK_MODEL", "grok-foo")
    monkeypatch.setenv("GROK_API_URL", "https://example.test/v1")
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.return_value = _fake_completion(mocker)
    ctor = mocker.patch("openai.OpenAI", return_value=fake_client)

    resp = GrokAdapter().complete([Message(role="user", content="x")], None)
    assert resp.success is True
    assert resp.model == "grok-foo"
    assert ctor.call_args.kwargs["base_url"] == "https://example.test/v1"


def test_api_missing_key(monkeypatch, mocker):
    monkeypatch.setenv("GROK_TRANSPORT", "api")
    ctor = mocker.patch("openai.OpenAI")
    resp = GrokAdapter().complete([Message(role="user", content="x")], None)
    assert resp.success is False
    assert "XAI_API_KEY" in (resp.error or "")
    ctor.assert_not_called()


def test_api_error_is_caught(monkeypatch, mocker):
    monkeypatch.setenv("GROK_TRANSPORT", "api")
    monkeypatch.setenv("XAI_API_KEY", "xai-123")
    fake_client = mocker.MagicMock()
    fake_client.chat.completions.create.side_effect = RuntimeError("kaboom")
    mocker.patch("openai.OpenAI", return_value=fake_client)
    resp = GrokAdapter().complete([Message(role="user", content="x")], None)
    assert resp.success is False
    assert "kaboom" in (resp.error or "")
    assert resp.metadata["transport"] == "api"
