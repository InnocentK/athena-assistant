"""Shared chat-turn helpers (M29.0) — the one assembly path for /chat + CLI."""

from __future__ import annotations

from unittest.mock import MagicMock

from core.chat_turn import build_turn_messages, extract_memory, system_prompt_from


def test_build_turn_messages_appends_user_turn_in_order():
    msgs = build_turn_messages(
        [("user", "hi"), ("assistant", "hello")], "how are you?"
    )
    assert [(m.role, m.content) for m in msgs] == [
        ("user", "hi"),
        ("assistant", "hello"),
        ("user", "how are you?"),
    ]


def test_build_turn_messages_empty_history_is_single_user_turn():
    msgs = build_turn_messages([], "solo")
    assert len(msgs) == 1 and msgs[0].role == "user" and msgs[0].content == "solo"


def test_system_prompt_or_none_semantics():
    assert system_prompt_from({"system_prompt": "be brief"}) == "be brief"
    assert system_prompt_from({"system_prompt": ""}) is None   # empty → None
    assert system_prompt_from({}) is None


def test_extract_memory_runs_and_reports():
    mgr = MagicMock()
    assert extract_memory(mgr, "q", "a") is True
    mgr.auto_extract.assert_called_once_with("q", "a")


def test_extract_memory_swallows_errors_and_tolerates_none():
    mgr = MagicMock()
    mgr.auto_extract.side_effect = RuntimeError("disk full")
    assert extract_memory(mgr, "q", "a") is False   # swallowed, reported
    assert extract_memory(None, "q", "a") is False  # no manager → no-op
