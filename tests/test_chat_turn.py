"""Shared chat-turn helpers (M29.0) — the one assembly path for /chat + CLI."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

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


# ---------------------------------------------------------------------------
# M30.5 — attachment inlining (provider-bound only, allowlist-governed)
# ---------------------------------------------------------------------------


@pytest.fixture
def attach_env(tmp_path, monkeypatch):
    """A tmp APP_ROOT with a files.yaml allowing reads under data/."""
    import core.config as cc
    import files.manager as fm_mod

    monkeypatch.setattr(cc, "APP_ROOT", tmp_path)
    monkeypatch.setattr(fm_mod, "APP_ROOT", tmp_path)
    monkeypatch.setattr(fm_mod, "_FILES_CONFIG", tmp_path / "config" / "files.yaml")
    monkeypatch.setattr(fm_mod, "_AUDIT_DIR", tmp_path / "audit")
    (tmp_path / "config").mkdir()
    (tmp_path / "audit").mkdir()
    uploads = tmp_path / "data" / "uploads"
    uploads.mkdir(parents=True)
    (tmp_path / "config" / "files.yaml").write_text(
        "entries:\n"
        "  - path: \"data\"\n"
        "    label: \"Data\"\n"
        "    search: true\n"
        "    read: true\n"
        "    write: true\n"
    )
    return uploads


def test_inline_attachments_embeds_text_content(attach_env):
    from core.chat_turn import build_turn_messages

    (attach_env / "pom.xml").write_text("<project>alpha</project>")
    msg = "[Attached file: data/uploads/pom.xml]\nCan you read this?"

    provider_msg = build_turn_messages([], msg)[-1].content

    assert "[Attached file: data/uploads/pom.xml]" in provider_msg  # kept
    assert "<project>alpha</project>" in provider_msg
    assert "--- Attached file content: data/uploads/pom.xml ---" in provider_msg
    assert "--- End of attached file ---" in provider_msg


def test_inline_attachments_caps_and_marks_truncation(attach_env):
    from core.chat_turn import _INLINE_MAX_BYTES, inline_attachments

    (attach_env / "big.txt").write_text("x" * (_INLINE_MAX_BYTES + 5000))
    out = inline_attachments("[Attached file: data/uploads/big.txt]")

    assert "[...truncated at 32 KB...]" in out
    assert len(out) < _INLINE_MAX_BYTES + 1000  # content actually capped


def test_inline_attachments_skips_non_text_extensions(attach_env):
    from core.chat_turn import inline_attachments

    (attach_env / "photo.png").write_bytes(b"\x89PNG\r\n")
    msg = "[Attached file: data/uploads/photo.png]"
    assert inline_attachments(msg) == msg  # byte-identical


def test_inline_attachments_missing_file_leaves_message_unchanged(attach_env):
    from core.chat_turn import inline_attachments

    msg = "[Attached file: data/uploads/nope.txt]\nhello"
    assert inline_attachments(msg) == msg


def test_inline_attachments_respects_allowlist(attach_env, tmp_path):
    from core.chat_turn import inline_attachments

    secret = tmp_path / "config" / "secret.txt"
    secret.write_text("do not leak")
    msg = "[Attached file: config/secret.txt]"
    out = inline_attachments(msg)
    assert out == msg  # config/ is not read-allowed → skipped
    assert "do not leak" not in out


def test_inline_attachments_limits_file_count(attach_env):
    from core.chat_turn import _INLINE_MAX_FILES, inline_attachments

    refs = []
    for i in range(_INLINE_MAX_FILES + 2):
        (attach_env / f"f{i}.txt").write_text(f"content-{i}")
        refs.append(f"[Attached file: data/uploads/f{i}.txt]")
    out = inline_attachments("\n".join(refs))

    assert out.count("--- Attached file content:") == _INLINE_MAX_FILES
    assert f"content-{_INLINE_MAX_FILES}" not in out  # the ones past the cap


def test_inline_attachments_fast_path_for_plain_messages():
    from core.chat_turn import inline_attachments

    assert inline_attachments("just a normal question") == "just a normal question"


def test_inline_attachments_ignores_mid_sentence_mentions(attach_env):
    from core.chat_turn import inline_attachments

    msg = "the UI writes [Attached file: x] into messages, right?"
    assert inline_attachments(msg) == msg  # not line-anchored → untouched
