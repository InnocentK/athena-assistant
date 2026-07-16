"""`athena history` CLI surfaces + REPL /list & /resume (M29.6)."""

from __future__ import annotations

import pytest

from cli.main import main
from history.manager import ConversationStore


@pytest.fixture
def hist_env(tmp_project, monkeypatch):
    import core.config as cc

    monkeypatch.setattr(cc, "APP_ROOT", tmp_project)
    monkeypatch.setenv("ACTIVE_PROFILE", "athena")
    cc.get_settings.cache_clear()
    store = ConversationStore(tmp_project / "profiles" / "athena")
    yield tmp_project, store
    cc.get_settings.cache_clear()


def _seed(store, text, answer="fine", success=True):
    conv = store.new_conversation()
    store.append_turn(conv, "user", text)
    store.append_turn(
        conv, "assistant", answer, {"provider": "mock", "model": "m1", "success": success}
    )
    return conv


def test_history_list_to_stdout(hist_env, capsys):
    _, store = hist_env
    conv = _seed(store, "hello world")
    assert main(["history"]) == 0
    out = capsys.readouterr().out
    assert conv in out and "hello world" in out and "PREVIEW" in out


def test_history_show_single_and_multi_with_separator(hist_env, capsys):
    _, store = hist_env
    a = _seed(store, "first q", "first a")
    b = _seed(store, "second q", "second a", success=False)
    assert main(["history", a, b]) == 0
    out = capsys.readouterr().out
    assert "You: first q" in out and "Assistant (mock/m1): first a" in out
    assert "[failed]" in out                       # failed turn marked
    assert "\n---\n" in out                        # separator between the two
    assert out.index(a) < out.index(b)             # order as given


def test_history_export_single_multi_and_all(hist_env, capsys):
    _, store = hist_env
    a = _seed(store, "alpha")
    b = _seed(store, "beta")

    assert main(["history", "export", a]) == 0
    out = capsys.readouterr().out
    assert f"# Conversation {a}" in out and "## You" in out

    assert main(["history", "export", a, b]) == 0
    out = capsys.readouterr().out
    assert out.count("# Conversation") == 2 and "\n---\n" in out

    assert main(["history", "export", "--all"]) == 0
    out = capsys.readouterr().out
    assert out.count("# Conversation") == 2        # everything exported
    # (newest-first ordering is by the second-resolution id stamp; two convs
    # created in the same second tie, so strict order isn't asserted here)


def test_history_unknown_and_invalid_ids(hist_env, capsys):
    assert main(["history", "nope123"]) == 1
    assert "not found" in capsys.readouterr().err
    assert main(["history", "../evil"]) == 1
    assert "invalid" in capsys.readouterr().err.lower()
    assert main(["history", "export", "--bogus"]) == 2


def test_http_export_matches_cli_export(client):
    """One renderer, two surfaces: the HTTP export equals the store render."""
    import main as app_module
    from tests.test_history import _mock_router

    app_module._router = _mock_router()
    conv = client.post("/chat", json={"message": "same", "history": []}).json()[
        "conversation_id"
    ]
    http_body = client.get(f"/history/conversations/{conv}/export").text
    assert http_body == app_module._history.render_markdown(conv)


# ---------------------------------------------------------------------------
# REPL /list + /resume
# ---------------------------------------------------------------------------


def test_repl_resume_restores_context_and_appends(hist_env, monkeypatch, capsys):
    import json

    from tests.test_repl import _RecordingRouter, _ScriptedInput, _install_router

    tmp, store = hist_env
    conv = _seed(store, "old question", "old answer")

    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    router = _RecordingRouter()
    _install_router(monkeypatch, router)
    monkeypatch.setattr(
        "builtins.input", _ScriptedInput([f"/resume {conv}", "follow up", "/exit"])
    )
    assert main([]) == 0
    # resumed context: old user+assistant + new user = 3 messages
    assert [m.role for m in router.calls[0]] == ["user", "assistant", "user"]
    assert "resumed" in capsys.readouterr().err
    # appended to the SAME conversation file
    lines = (tmp / "profiles" / "athena" / "history" / f"{conv}.jsonl").read_text().splitlines()
    assert len(lines) == 4
    assert json.loads(lines[2])["content"] == "follow up"


def test_repl_resume_skips_failed_turns_and_list_on_stderr(hist_env, monkeypatch, capsys):
    from tests.test_repl import _RecordingRouter, _ScriptedInput, _install_router

    _, store = hist_env
    conv = _seed(store, "q", "bad answer", success=False)

    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    router = _RecordingRouter()
    _install_router(monkeypatch, router)
    monkeypatch.setattr(
        "builtins.input", _ScriptedInput(["/list", f"/resume {conv}", "next", "/exit"])
    )
    assert main([]) == 0
    captured = capsys.readouterr()
    assert conv in captured.err                    # /list on stderr
    assert conv not in captured.out
    # failed assistant turn NOT replayed: user turn + new user only
    assert [m.role for m in router.calls[0]] == ["user", "user"]
