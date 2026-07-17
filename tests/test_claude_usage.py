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

# Structurally faithful to the REAL envelope captured from Claude Code 2.1.206
# (M29.5 validation run): no top-level "model"; the name is modelUsage's key;
# extra fields present to prove the parser tolerates them.
REAL_ENVELOPE_2_1_206 = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "duration_ms": 3636,
    "num_turns": 1,
    "result": "Hi! What can I help you with today?",
    "stop_reason": "end_turn",
    "session_id": "ee6a69b8-afe3-5973-9ac4-1c08eb032335",
    "total_cost_usd": 0.182322,
    "usage": {
        "input_tokens": 5954,
        "cache_creation_input_tokens": 27375,
        "cache_read_input_tokens": 0,
        "output_tokens": 14,
        "service_tier": "standard",
        "iterations": [{"input_tokens": 5954, "output_tokens": 14, "type": "message"}],
    },
    "modelUsage": {
        "claude-sonnet-5": {
            "inputTokens": 5954,
            "outputTokens": 14,
            "costUSD": 0.182322,
            "contextWindow": 1000000,
        }
    },
    "permission_denials": [],
    "uuid": "b5c3342d-9c59-489a-99b4-63388c452aa1",
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


def test_real_2_1_206_envelope_parses_with_model_attribution(monkeypatch):
    """The pinned real-world envelope (M29.5): content + usage + model from
    modelUsage's key, with all the extra fields tolerated."""
    ok = SimpleNamespace(returncode=0, stdout=json.dumps(REAL_ENVELOPE_2_1_206), stderr="")
    _, resp, _ = _complete(monkeypatch, HELP_WITH_FLAG, ok)
    assert resp.success and resp.content == "Hi! What can I help you with today?"
    assert resp.model == "claude-sonnet-5"          # attributed via modelUsage
    assert resp.metadata["usage"] == {
        "prompt_tokens": 5954, "completion_tokens": 14, "total_tokens": 5968,
    }


def test_top_level_model_wins_over_model_usage(monkeypatch):
    env = dict(REAL_ENVELOPE_2_1_206, model="claude-explicit")
    ok = SimpleNamespace(returncode=0, stdout=json.dumps(env), stderr="")
    _, resp, _ = _complete(monkeypatch, HELP_WITH_FLAG, ok)
    assert resp.model == "claude-explicit"


def test_model_usage_edge_cases_yield_none(monkeypatch):
    # (JSON object keys are always strings, so a non-str key can't occur on
    # the wire — the isinstance guard covers hand-constructed dicts only.)
    for bad in ({}, "not a dict", None, 42):
        env = {k: v for k, v in REAL_ENVELOPE_2_1_206.items() if k != "modelUsage"}
        env["modelUsage"] = bad
        ok = SimpleNamespace(returncode=0, stdout=json.dumps(env), stderr="")
        _, resp, _ = _complete(monkeypatch, HELP_WITH_FLAG, ok)
        assert resp.success and resp.model is None


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


# ---------------------------------------------------------------------------
# M29.8 — F4 (is_error before shape fallback) + F14 (empty output → failure)
# ---------------------------------------------------------------------------


def test_error_envelope_without_result_is_failure_not_raw_success(monkeypatch):
    """F4: is_error is checked BEFORE the shape fallback — an error envelope
    with a null/absent result must never render raw JSON as a success."""
    env = {"type": "result", "is_error": True, "subtype": "error_max_turns", "result": None}
    ok = SimpleNamespace(returncode=0, stdout=json.dumps(env), stderr="")
    _, resp, _ = _complete(monkeypatch, HELP_WITH_FLAG, ok)
    assert resp.success is False
    assert "error_max_turns" in (resp.error or "")


def test_error_envelope_without_result_or_subtype_generic_failure(monkeypatch):
    env = {"type": "result", "is_error": True}
    ok = SimpleNamespace(returncode=0, stdout=json.dumps(env), stderr="")
    _, resp, _ = _complete(monkeypatch, HELP_WITH_FLAG, ok)
    assert resp.success is False and "error result" in (resp.error or "")


def test_empty_output_is_failure_plain_mode(monkeypatch):
    """F14: empty answers fail (hermes parity) so the router falls through."""
    ok = SimpleNamespace(returncode=0, stdout="   \n", stderr="")
    _, resp, _ = _complete(monkeypatch, HELP_WITHOUT_FLAG, ok)
    assert resp.success is False and "no output" in (resp.error or "")


def test_empty_output_is_failure_json_mode(monkeypatch):
    ok = SimpleNamespace(returncode=0, stdout="", stderr="")
    _, resp, _ = _complete(monkeypatch, HELP_WITH_FLAG, ok)
    assert resp.success is False and "no output" in (resp.error or "")


def test_empty_result_string_in_envelope_is_failure(monkeypatch):
    env = dict(ENVELOPE, result="   ")
    ok = SimpleNamespace(returncode=0, stdout=json.dumps(env), stderr="")
    _, resp, _ = _complete(monkeypatch, HELP_WITH_FLAG, ok)
    assert resp.success is False and "no output" in (resp.error or "")


# ---------------------------------------------------------------------------
# M30.7 — tool restriction (feature-detected, like JSON mode)
# ---------------------------------------------------------------------------


def _fake_run_recorder(mocker, help_text: str):
    """subprocess.run fake: --help returns help_text; completions echo args."""
    calls: list[list] = []

    def _run(args, **kwargs):
        calls.append(list(args))
        if "--help" in args:
            return mocker.MagicMock(returncode=0, stdout=help_text, stderr="")
        return mocker.MagicMock(returncode=0, stdout="fine answer", stderr="")

    return calls, _run


def test_tool_restriction_flag_added_when_supported(mocker):
    from providers.claude import _DISALLOWED_TOOLS, ClaudeAdapter

    calls, run = _fake_run_recorder(
        mocker, "usage… --output-format … --disallowedTools …"
    )
    mocker.patch("providers.claude.subprocess.run", side_effect=run)

    ClaudeAdapter().complete([Message(role="user", content="hi")], None)

    completion = calls[-1]
    idx = completion.index("--disallowedTools")
    assert completion[idx + 1] == _DISALLOWED_TOOLS
    # pure-LLM denylist covers the agent's action tools
    for name in ("Bash", "Read", "Glob", "WebSearch", "Write", "Task"):
        assert name in _DISALLOWED_TOOLS


def test_tool_restriction_omitted_on_old_cli(mocker):
    from providers.claude import ClaudeAdapter

    calls, run = _fake_run_recorder(mocker, "usage… --output-format …")  # no flag
    mocker.patch("providers.claude.subprocess.run", side_effect=run)

    ClaudeAdapter().complete([Message(role="user", content="hi")], None)

    assert "--disallowedTools" not in calls[-1]  # degrade: agentic as before
    assert "--output-format" in calls[-1]        # JSON mode unaffected


def test_help_probe_runs_once_for_both_feature_checks(mocker):
    from providers.claude import ClaudeAdapter

    calls, run = _fake_run_recorder(
        mocker, "--output-format --disallowedTools"
    )
    mocker.patch("providers.claude.subprocess.run", side_effect=run)

    adapter = ClaudeAdapter()
    adapter.complete([Message(role="user", content="one")], None)
    adapter.complete([Message(role="user", content="two")], None)

    help_calls = [c for c in calls if "--help" in c]
    assert len(help_calls) == 1  # ONE cached probe feeds both checks, forever
