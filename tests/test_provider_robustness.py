"""
tests/test_provider_robustness.py — Provider/router robustness tests (M26.8).

Covers the adapter/router-level fixes:
  - ChatGPT API is bounded (timeout + max_retries=0) and maps timeout/connection
    errors to clean success=False responses (H3).
  - CLI adapters pass stdin=DEVNULL + explicit utf-8/replace decoding (L1/L2).
  - Unknown routing mode falls back to 'balanced' with a warning, not the
    most-expensive 'quality-first' order (M4).
  - Router diagnostics report a dynamic adapter's real transport() on records
    with no response metadata, e.g. an unavailable Grok in API mode (M2).

All mocked — no real providers, API keys, or network.
"""

from __future__ import annotations

import logging
import subprocess

import pytest

from providers.base import Message, ProviderResponse


# ---------------------------------------------------------------------------
# H3 — ChatGPT API is bounded and maps errors cleanly
# ---------------------------------------------------------------------------


class _FakeOpenAIModule:
    """Minimal stand-in for the `openai` package with the exception classes."""

    class APITimeoutError(Exception):
        pass

    class APIConnectionError(Exception):
        pass

    def __init__(self, behaviour):
        self._behaviour = behaviour
        self.captured_kwargs: dict = {}

    # `openai.OpenAI(...)` → returns a client; capture the init kwargs.
    def OpenAI(self, **kwargs):
        self.captured_kwargs = kwargs
        behaviour = self._behaviour
        outer = self

        class _Client:
            def __init__(self):
                self.chat = self

            @property
            def completions(self):
                return self

            def create(self, **_kw):
                if behaviour == "timeout":
                    raise outer.APITimeoutError("timed out")
                if behaviour == "connection":
                    raise outer.APIConnectionError("no route")

                class _Msg:
                    content = "hi from gpt"

                class _Choice:
                    message = _Msg()

                class _Resp:
                    choices = [_Choice()]

                return _Resp()

        return _Client()


def _run_chatgpt(monkeypatch, behaviour):
    import providers.chatgpt as cg

    fake = _FakeOpenAIModule(behaviour)
    monkeypatch.setitem(__import__("sys").modules, "openai", fake)
    resp = cg.ChatGPTAPIAdapter().complete([Message(role="user", content="x")], None)
    return resp, fake


def test_chatgpt_passes_timeout_and_no_retries(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("OPENAI_TIMEOUT", raising=False)
    resp, fake = _run_chatgpt(monkeypatch, "ok")
    assert resp.success is True
    assert resp.content == "hi from gpt"
    # The client was constructed bounded.
    assert fake.captured_kwargs.get("timeout") == 120.0
    assert fake.captured_kwargs.get("max_retries") == 0


def test_chatgpt_timeout_is_clean_failure(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    resp, _ = _run_chatgpt(monkeypatch, "timeout")
    assert resp.success is False
    assert "timeout" in resp.error.lower()
    # And diagnostics would classify it as a timeout, not a generic failure.
    from diagnostics.store import classify_error_kind

    assert classify_error_kind("failure", resp.error) == "timeout"


def test_chatgpt_connection_error_is_clean_failure(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    resp, _ = _run_chatgpt(monkeypatch, "connection")
    assert resp.success is False
    assert "connection error" in resp.error.lower()


def test_chatgpt_custom_timeout_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_TIMEOUT", "45")
    _, fake = _run_chatgpt(monkeypatch, "ok")
    assert fake.captured_kwargs.get("timeout") == 45.0


# ---------------------------------------------------------------------------
# L1 + L2 — CLI adapters harden the subprocess call
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module_path, adapter_name",
    [
        ("providers.claude", "ClaudeAdapter"),
        ("providers.gemini", "GeminiAdapter"),
        ("providers.grok", "GrokAdapter"),
        ("providers.hermes", "HermesAdapter"),
    ],
)
def test_cli_adapters_harden_subprocess(monkeypatch, mocker, module_path, adapter_name):
    import importlib

    mod = importlib.import_module(module_path)
    # Grok/Hermes need their CLI transport / env; force CLI for grok.
    monkeypatch.setenv("GROK_TRANSPORT", "cli")

    captured: dict = {}

    def _fake_run(*args, **kwargs):
        captured.update(kwargs)
        return mocker.MagicMock(returncode=0, stdout="ok", stderr="")

    mocker.patch(f"{module_path}.subprocess.run", side_effect=_fake_run)

    adapter = getattr(mod, adapter_name)()
    adapter.complete([Message(role="user", content="x")], None)

    assert captured.get("stdin") is subprocess.DEVNULL, f"{adapter_name} missing stdin=DEVNULL"
    assert captured.get("encoding") == "utf-8", f"{adapter_name} missing encoding"
    assert captured.get("errors") == "replace", f"{adapter_name} missing errors=replace"
    # M30.3: subprocesses must never inherit the caller's cwd — vendor CLIs
    # discover project agent config (CLAUDE.md, hooks) by walking up from it.
    import tempfile

    assert captured.get("cwd") == tempfile.gettempdir(), f"{adapter_name} missing neutral cwd (M30.3)"


def test_claude_help_probe_uses_neutral_cwd(mocker):
    """M30.3: the `claude --help` JSON-support probe must not inherit a
    project cwd either — hooks and project config load per invocation."""
    import tempfile

    from providers.claude import ClaudeAdapter

    calls: list[dict] = []

    def _fake_run(*args, **kwargs):
        calls.append(dict(kwargs))
        return mocker.MagicMock(returncode=0, stdout="--output-format", stderr="")

    mocker.patch("providers.claude.subprocess.run", side_effect=_fake_run)

    assert ClaudeAdapter()._supports_json_output() is True
    assert calls and calls[0].get("cwd") == tempfile.gettempdir()


# ---------------------------------------------------------------------------
# M4 — unknown routing mode → balanced (not quality-first) + warning
# ---------------------------------------------------------------------------


@pytest.fixture
def router(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path

    real_root = Path(__file__).parent.parent
    monkeypatch.setattr("core.config.APP_ROOT", tmp_path)
    import core.config as cc

    cc.get_settings.cache_clear()
    (tmp_path / "config").mkdir()
    shutil.copy(real_root / "config" / "providers.yaml", tmp_path / "config" / "providers.yaml")
    from providers.router import ProviderRouter

    return ProviderRouter()


def test_unknown_mode_falls_back_to_balanced(router, caplog):
    balanced = router._get_ordered_names("balanced")
    quality = router._get_ordered_names("quality-first")
    assert balanced != quality  # sanity: the two orders differ

    with caplog.at_level(logging.WARNING, logger="athena"):
        result = router._get_ordered_names("budget_first")  # underscore typo
    assert result == balanced
    assert result != quality
    assert any("unknown routing mode" in r.message.lower() for r in caplog.records)


def test_known_modes_unchanged(router):
    assert router._get_ordered_names("quality-first") == list(router._ranking["quality_first"])
    assert router._get_ordered_names("balanced") == list(router._ranking["balanced"])
    assert router._get_ordered_names("budget-first") == list(router._ranking["budget_first"])


# ---------------------------------------------------------------------------
# M2 — router reports a dynamic adapter's real transport on non-answer records
# ---------------------------------------------------------------------------


def test_transport_for_uses_adapter_transport_when_unavailable(router):
    class _GrokLike:
        def transport(self):
            return "api"

        def is_available(self):
            return False

        def complete(self, msgs, sp):  # pragma: no cover - unavailable, never called
            return ProviderResponse(content="", provider_name="grok", success=False)

    router._all_adapters = {"grok": _GrokLike()}
    router._adapter_configs = {"grok": {"enabled": True, "type": "cli"}}  # static type = cli
    router._ranking = {"balanced": ["grok"]}

    resp = router.route([Message(role="user", content="x")], None, {"routing": {"mode": "balanced"}})
    rec = resp.metadata["diagnostics"]["records"][0]
    assert rec["outcome"] == "unavailable"
    # Real transport (api) is reported, NOT the static providers.yaml type (cli).
    assert rec["transport"] == "api"
