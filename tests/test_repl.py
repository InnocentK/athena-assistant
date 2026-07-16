"""CLI REPL (M29.2) — scripted-stdin tests, everything mocked.

Drives cli/repl.py via cli.main with a fake TTY stdin and a scripted input()
sequence. The contracts: history accumulates only on success, /new resets it,
turns persist to the ConversationStore, and stdout stays answer-only.
"""

from __future__ import annotations

import pytest

from providers.base import ProviderResponse
from tests.test_cli import _FakeRouter, _install_router


class _ScriptedInput:
    def __init__(self, lines):
        self._lines = list(lines)

    def __call__(self, *_a):
        if not self._lines:
            raise EOFError
        return self._lines.pop(0)


@pytest.fixture
def cli_env(tmp_project, monkeypatch):
    """Point the CLI's config/profile resolution at the tmp project tree
    (mirrors tests/test_cli.py's fixture — fixtures don't cross modules)."""
    import core.config as cc

    monkeypatch.setattr(cc, "APP_ROOT", tmp_project)
    monkeypatch.setenv("ACTIVE_PROFILE", "athena")
    cc.get_settings.cache_clear()
    yield tmp_project
    cc.get_settings.cache_clear()


class _RecordingRouter(_FakeRouter):
    """Fake router that records each route() message list."""

    def __init__(self, responses=None):
        super().__init__()
        self.calls: list[list] = []
        self._responses = list(responses or [])

    def route(self, messages, system_prompt, profile_config, on_attempt=None):
        self.calls.append(list(messages))
        if on_attempt:
            on_attempt({"provider": "fake", "transport": "api", "mode": "balanced"})
        if self._responses:
            return self._responses.pop(0)
        return ProviderResponse(
            content=f"answer{len(self.calls)}", provider_name="fake",
            model="m", success=True,
        )


@pytest.fixture
def repl_env(cli_env, monkeypatch):
    """cli_env + a TTY stdin so bare invocation enters the REPL."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    return cli_env


def _run(monkeypatch, router, lines, argv=None):
    from cli.main import main

    _install_router(monkeypatch, router)
    monkeypatch.setattr("builtins.input", _ScriptedInput(lines))
    return main(argv or [])


def test_repl_accumulates_history_on_success(repl_env, monkeypatch, capsys):
    router = _RecordingRouter()
    code = _run(monkeypatch, router, ["hello", "again", "/exit"])
    assert code == 0
    assert len(router.calls) == 2
    assert len(router.calls[0]) == 1                      # first turn: just the user msg
    assert len(router.calls[1]) == 3                      # second: history + new msg
    assert [m.role for m in router.calls[1]] == ["user", "assistant", "user"]
    out = capsys.readouterr().out
    assert out == "answer1\nanswer2\n"                    # stdout = answers only


def test_repl_new_resets_history_and_conversation(repl_env, monkeypatch):
    import core.config as cc

    router = _RecordingRouter()
    code = _run(monkeypatch, router, ["one", "/new", "two", "/exit"])
    assert code == 0
    assert len(router.calls[1]) == 1                      # /new dropped the history
    hist_dir = cc.APP_ROOT / "profiles" / "athena" / "history"
    files = sorted(hist_dir.glob("*.jsonl"))
    assert len(files) == 2                                # one conversation per /new
    assert sum(1 for _ in open(files[0])) == 2            # user+assistant
    assert sum(1 for _ in open(files[1])) == 2


def test_repl_failure_not_replayed_but_persisted(repl_env, monkeypatch, capsys):
    import json

    import core.config as cc

    fail = ProviderResponse(content="", provider_name="fake", success=False, error="boom")
    router = _RecordingRouter(responses=[fail])
    code = _run(monkeypatch, router, ["bad turn", "good turn", "/exit"])
    assert code == 0
    # second call must NOT contain the failed exchange
    assert len(router.calls[1]) == 1
    err = capsys.readouterr().err
    assert "Error: boom" in err
    # persisted with success:false meta
    hist_dir = cc.APP_ROOT / "profiles" / "athena" / "history"
    lines = [json.loads(x) for f in hist_dir.glob("*.jsonl") for x in open(f)]
    assert any(x.get("success") is False for x in lines if x["role"] == "assistant")


def test_repl_eof_exits_cleanly(repl_env, monkeypatch):
    assert _run(monkeypatch, _RecordingRouter(), []) == 0


def test_bare_invocation_without_tty_is_still_usage_error(cli_env, monkeypatch, capsys):
    from cli.main import main

    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    _install_router(monkeypatch, _RecordingRouter())
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
