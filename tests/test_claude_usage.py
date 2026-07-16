"""Claude CLI JSON envelope + usage capture (M28.2). All subprocess mocked.

The contract under test: JSON mode is feature-detected (cached), the envelope
is parsed defensively, and EVERY deviation degrades to plain-text behavior —
the primary provider must never break for a metric.
"""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from providers.base import Message
from providers.claude import ClaudeAdapter, _map_claude_usage

MSG = [Message(role="user", content="hi")]

HELP_WITH_FLAG = SimpleNamespace(returncode=0, stdout="... --output-format <fmt> ...", stderr="")
HELP_WITHOUT_FLAG = SimpleNamespace(returncode=0, stdout="usage: claude -p", stderr="")

ENVELOPE = {
    "type": "result",
    "result": "Hello there.",
    "is_error": False,
    "model": "claude-x",
    "usage": {"input_tokens": 12, "output_tokens": 5},
}


def _runner(help_result, complete_result, calls):
    """Fake subprocess.run recording argv."""

    def run(args, **kwargs):
        calls.append(list(args))
        if "--help" in args:
            return help_result
        return complete_result

    return run


def _complete(monkeypatch, help_result, complete_result):
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "providers.claude.subprocess.run", _runner(help_result, complete_result, calls)
    )
    adapter = ClaudeAdapter()
    resp = adapter.complete(MSG)
    return adapter, resp, calls


def test_json_mode_parses_content_model_and_usage(monkeypatch):
    ok = SimpleNamespace(returncode=0, stdout=json.dumps(ENVELOPE), stderr="")
    _, resp, calls = _complete(monkeypatch, HELP_WITH_FLAG, ok)
    assert resp.success and resp.content == "Hello there."
    assert resp.model == "claude-x"
    assert resp.metadata["usage"] == {
        "prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17,
    }
    assert calls[-1][-2:] == ["--output-format", "json"]


def test_no_flag_support_means_plain_invocation(monkeypatch):
    ok = SimpleNamespace(returncode=0, stdout="plain answer", stderr="")
    _, resp, calls = _complete(monkeypatch, HELP_WITHOUT_FLAG, ok)
    assert resp.success and resp.content == "plain answer"
    assert "usage" not in resp.metadata
    assert "--output-format" not in calls[-1]


def test_help_probe_is_cached(monkeypatch):
    ok = SimpleNamespace(returncode=0, stdout=json.dumps(ENVELOPE), stderr="")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "providers.claude.subprocess.run", _runner(HELP_WITH_FLAG, ok, calls)
    )
    adapter = ClaudeAdapter()
    adapter.complete(MSG)
    adapter.complete(MSG)
    assert sum(1 for c in calls if "--help" in c) == 1


def test_help_probe_failure_degrades_to_plain(monkeypatch):
    def run(args, **kwargs):
        if "--help" in args:
            raise subprocess.TimeoutExpired(cmd=args, timeout=10)
        return SimpleNamespace(returncode=0, stdout="answer", stderr="")

    monkeypatch.setattr("providers.claude.subprocess.run", run)
    resp = ClaudeAdapter().complete(MSG)
    assert resp.success and resp.content == "answer"


def test_non_json_stdout_in_json_mode_is_the_answer(monkeypatch):
    ok = SimpleNamespace(returncode=0, stdout="not json at all", stderr="")
    _, resp, _ = _complete(monkeypatch, HELP_WITH_FLAG, ok)
    assert resp.success and resp.content == "not json at all"
    assert "usage" not in resp.metadata


def test_json_without_result_key_falls_back_to_raw(monkeypatch):
    ok = SimpleNamespace(returncode=0, stdout=json.dumps({"weird": 1}), stderr="")
    _, resp, _ = _complete(monkeypatch, HELP_WITH_FLAG, ok)
    assert resp.success and resp.content == json.dumps({"weird": 1})


def test_is_error_envelope_is_a_provider_failure(monkeypatch):
    env = dict(ENVELOPE, is_error=True, result="quota exceeded")
    ok = SimpleNamespace(returncode=0, stdout=json.dumps(env), stderr="")
    _, resp, _ = _complete(monkeypatch, HELP_WITH_FLAG, ok)
    assert resp.success is False and "quota exceeded" in (resp.error or "")


def test_nonzero_exit_error_path_unchanged(monkeypatch):
    bad = SimpleNamespace(returncode=1, stdout="", stderr="auth required")
    _, resp, _ = _complete(monkeypatch, HELP_WITH_FLAG, bad)
    assert resp.success is False and resp.error == "auth required"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ({"input_tokens": 3}, {"prompt_tokens": 3}),
        ({"input_tokens": True, "output_tokens": 4}, {"completion_tokens": 4}),
        ({"input_tokens": "x"}, None),
        (None, None),
        ({}, None),
    ],
)
def test_map_claude_usage_edges(raw, expected):
    assert _map_claude_usage(raw) == expected
