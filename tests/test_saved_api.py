"""
tests/test_saved_api.py — HTTP tests for the /saved/* endpoints (Milestone 18).

Uses the `client` fixture (FastAPI TestClient over a tmp project). The provider
router is monkeypatched for the action-run test, so no real provider is needed.
File-search runs use the tmp allowlist (data/ is search-permitted in conftest).
"""

from __future__ import annotations

from providers.base import ProviderResponse


# ---------------------------------------------------------------------------
# Saved searches — CRUD
# ---------------------------------------------------------------------------


def test_saved_search_crud(client):
    # create
    r = client.post("/saved/searches", json={"name": "md", "query": "*.md", "path": "data"})
    assert r.status_code == 200
    item = r.json()
    sid = item["id"]
    assert item["target"] == "files"

    # list
    assert any(s["id"] == sid for s in client.get("/saved/searches").json())

    # get
    assert client.get(f"/saved/searches/{sid}").json()["query"] == "*.md"

    # update
    r = client.patch(f"/saved/searches/{sid}", json={"name": "markdown"})
    assert r.status_code == 200 and r.json()["name"] == "markdown"

    # delete
    assert client.delete(f"/saved/searches/{sid}").json() == {"deleted": True}
    assert client.get(f"/saved/searches/{sid}").status_code == 404


def test_saved_search_rejects_non_files_target(client):
    r = client.post("/saved/searches", json={"name": "web", "query": "cats", "target": "web"})
    assert r.status_code == 400
    assert "files" in r.json()["detail"].lower()


def test_saved_search_run_files(client):
    # Create a file under the search-permitted data/ root.
    w = client.post("/files/write", json={"path": "data/m18_target.md", "content": "hello"})
    assert w.status_code == 200

    sid = client.post(
        "/saved/searches", json={"name": "md", "query": "*.md", "path": "data"}
    ).json()["id"]

    r = client.post(f"/saved/searches/{sid}/run")
    assert r.status_code == 200
    body = r.json()
    assert body["target"] == "files"
    assert any(p.endswith("m18_target.md") for p in body["results"])


def test_saved_search_run_missing_returns_404(client):
    assert client.post("/saved/searches/nope/run").status_code == 404


# ---------------------------------------------------------------------------
# Saved actions — CRUD + run
# ---------------------------------------------------------------------------


def test_saved_action_crud(client):
    r = client.post(
        "/saved/actions",
        json={"name": "standup", "prompt": "Summarise my day", "mode": "budget-first"},
    )
    assert r.status_code == 200
    aid = r.json()["id"]
    assert r.json()["mode"] == "budget-first"

    assert any(a["id"] == aid for a in client.get("/saved/actions").json())
    assert client.get(f"/saved/actions/{aid}").json()["prompt"] == "Summarise my day"

    r = client.patch(f"/saved/actions/{aid}", json={"prompt": "Summarise concisely"})
    assert r.status_code == 200 and r.json()["prompt"] == "Summarise concisely"

    assert client.delete(f"/saved/actions/{aid}").json() == {"deleted": True}
    assert client.get(f"/saved/actions/{aid}").status_code == 404


def test_saved_action_run_uses_router_with_overrides(client, monkeypatch):
    import main as app_module

    captured: dict = {}

    class _FakeRouter:
        def route(self, messages, system_prompt, profile_config):
            captured["messages"] = messages
            captured["profile_config"] = profile_config
            return ProviderResponse(
                content="done", provider_name="ollama", model="gemma4", success=True
            )

        def list_providers(self):
            # M26.8: create/update now validate the provider override against
            # the known names, so the fake must advertise "ollama".
            return [
                {"name": "ollama", "enabled": True, "available": True,
                 "cost_tier": "low", "type": "api"},
            ]

    monkeypatch.setattr(app_module, "_router", _FakeRouter())

    aid = client.post(
        "/saved/actions",
        json={"name": "act", "prompt": "do the thing", "mode": "budget-first", "provider": "ollama"},
    ).json()["id"]

    r = client.post(f"/saved/actions/{aid}/run")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["response"] == "done"
    assert body["provider"] == "ollama"
    # overrides reached the router; the prompt became the single user turn
    assert captured["messages"][0].content == "do the thing"
    assert captured["profile_config"]["routing"]["mode"] == "budget-first"
    assert captured["profile_config"]["routing"]["preferred_provider"] == "ollama"


def test_saved_action_run_missing_returns_404(client):
    assert client.post("/saved/actions/nope/run").status_code == 404


# ---------------------------------------------------------------------------
# Saved actions — override validation (Milestone 26.8)
# ---------------------------------------------------------------------------


def test_saved_action_create_rejects_invalid_mode(client):
    r = client.post(
        "/saved/actions",
        json={"name": "x", "prompt": "p", "mode": "budget_first"},  # underscore typo
    )
    assert r.status_code == 400
    assert "mode" in r.json()["detail"].lower()


def test_saved_action_create_rejects_unknown_provider(client):
    r = client.post(
        "/saved/actions",
        json={"name": "x", "prompt": "p", "provider": "claud"},  # typo
    )
    assert r.status_code == 400
    assert "provider" in r.json()["detail"].lower()


def test_saved_action_create_accepts_valid_overrides(client):
    # 'claude' is a real registry provider name; 'balanced' is a valid mode.
    r = client.post(
        "/saved/actions",
        json={"name": "ok", "prompt": "p", "mode": "balanced", "provider": "claude"},
    )
    assert r.status_code == 200
    assert r.json()["mode"] == "balanced"


def test_saved_action_update_rejects_invalid_mode(client):
    aid = client.post("/saved/actions", json={"name": "a", "prompt": "p"}).json()["id"]
    r = client.patch(f"/saved/actions/{aid}", json={"mode": "cheap"})
    assert r.status_code == 400
    assert "mode" in r.json()["detail"].lower()
