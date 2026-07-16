"""Persistent conversation history (M29.1): store + /chat wiring + endpoints."""

from __future__ import annotations

import json

import pytest

from history.manager import ConversationStore


# ---------------------------------------------------------------------------
# Store units
# ---------------------------------------------------------------------------


def test_store_round_trip(tmp_path):
    store = ConversationStore(tmp_path)
    conv = store.new_conversation()
    store.append_turn(conv, "user", "hello")
    store.append_turn(conv, "assistant", "hi!", {"provider": "mock", "success": True})

    turns = store.read(conv)
    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert turns[1]["provider"] == "mock" and turns[1]["success"] is True

    listed = store.list_conversations()
    assert listed[0]["id"] == conv and listed[0]["turns"] == 2
    assert listed[0]["preview"] == "hello"

    assert store.delete(conv) is True
    assert store.delete(conv) is False
    with pytest.raises(FileNotFoundError):
        store.read(conv)


def test_store_rejects_traversal_ids(tmp_path):
    store = ConversationStore(tmp_path)
    for bad in ("../x", "a/b", "a b", "", "..", "x.jsonl"):
        with pytest.raises(ValueError):
            store.append_turn(bad, "user", "x")
        with pytest.raises(ValueError):
            store.read(bad)


def test_store_skips_malformed_lines(tmp_path):
    store = ConversationStore(tmp_path)
    conv = store.new_conversation()
    store.append_turn(conv, "user", "ok")
    path = tmp_path / "history" / f"{conv}.jsonl"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("NOT JSON\n")
    store.append_turn(conv, "assistant", "fine")
    assert [t["role"] for t in store.read(conv)] == ["user", "assistant"]


# ---------------------------------------------------------------------------
# /chat wiring + endpoints (client fixture; provider mocked via router swap)
# ---------------------------------------------------------------------------


def _mock_router():
    from unittest.mock import MagicMock

    from providers.base import ProviderResponse

    router = MagicMock()
    router.route.return_value = ProviderResponse(
        content="mock answer", provider_name="mock", model="m1", success=True
    )
    return router


def test_chat_creates_and_continues_conversation(client):
    import core.config as cc
    import main as app_module

    app_module._router = _mock_router()

    r1 = client.post("/chat", json={"message": "first", "history": []})
    assert r1.status_code == 200
    conv = r1.json()["conversation_id"]
    assert conv

    r2 = client.post(
        "/chat",
        json={
            "message": "second",
            "history": [{"role": "user", "content": "first"},
                        {"role": "assistant", "content": "mock answer"}],
            "conversation_id": conv,
        },
    )
    assert r2.json()["conversation_id"] == conv

    # one file, four lines (user/assistant ×2), assistant meta recorded
    path = cc.APP_ROOT / "profiles" / "athena" / "history" / f"{conv}.jsonl"
    lines = [json.loads(x) for x in path.read_text().splitlines()]
    assert [x["role"] for x in lines] == ["user", "assistant", "user", "assistant"]
    assert lines[1]["provider"] == "mock"


def test_chat_rejects_bad_conversation_id(client):
    import main as app_module

    app_module._router = _mock_router()
    resp = client.post(
        "/chat", json={"message": "x", "history": [], "conversation_id": "../evil"}
    )
    assert resp.status_code == 400


def test_history_endpoints_list_read_delete(client):
    import main as app_module

    app_module._router = _mock_router()
    conv = client.post("/chat", json={"message": "hey", "history": []}).json()[
        "conversation_id"
    ]

    listed = client.get("/history/conversations").json()
    assert any(c["id"] == conv and c["preview"] == "hey" for c in listed)

    read = client.get(f"/history/conversations/{conv}").json()
    assert read["id"] == conv and len(read["turns"]) == 2

    assert client.get("/history/conversations/nope").status_code == 404
    assert client.delete(f"/history/conversations/{conv}").json()["deleted"] is True
    assert client.get(f"/history/conversations/{conv}").status_code == 404


def test_export_markdown_round_trip(client):
    import main as app_module

    app_module._router = _mock_router()
    conv = client.post("/chat", json={"message": "export me", "history": []}).json()[
        "conversation_id"
    ]
    resp = client.get(f"/history/conversations/{conv}/export")
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]
    assert f'{conv}.md"' in resp.headers["content-disposition"]
    body = resp.text
    assert f"# Conversation {conv}" in body
    assert "## You" in body and "export me" in body
    assert "## Assistant (mock/m1)" in body and "mock answer" in body

    assert client.get("/history/conversations/nope/export").status_code == 404


def test_export_flags_failed_turns(client):
    import main as app_module

    app_module._router = _mock_router()
    conv = client.post("/chat", json={"message": "q", "history": []}).json()[
        "conversation_id"
    ]
    app_module._history.append_turn(
        conv, "assistant", "boom", {"provider": "mock", "success": False}
    )
    body = client.get(f"/history/conversations/{conv}/export").text
    assert "*(failed)*" in body


def test_profile_switch_repoints_history(client):
    import main as app_module
    from tests.test_profile_switch import _mk_profile

    app_module._router = _mock_router()
    _mk_profile(client, "zeus", "Zeus")
    client.post("/profiles/activate", json={"name": "zeus"})

    conv = client.post("/chat", json={"message": "in zeus", "history": []}).json()[
        "conversation_id"
    ]
    import core.config as cc

    assert (cc.APP_ROOT / "profiles" / "zeus" / "history" / f"{conv}.jsonl").exists()


def test_conversation_id_validator_agrees_at_both_layers(client):
    """REVIEW-3.0 F6: one validator — /chat's 400 set and the store's
    ValueError set are the same by construction; pin the agreement."""
    import main as app_module
    from history.manager import is_valid_conversation_id

    app_module._router = _mock_router()
    for bad in ("../x", "a/b", "a b", "", "x!y"):
        assert not is_valid_conversation_id(bad)
        if bad:  # empty string can't ride the JSON field meaningfully
            resp = client.post(
                "/chat", json={"message": "q", "history": [], "conversation_id": bad}
            )
            assert resp.status_code == 400, bad
    assert is_valid_conversation_id("20260101T000000Z-abcd")
