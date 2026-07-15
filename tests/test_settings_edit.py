"""
tests/test_settings_edit.py — Editable settings (Milestone 26).

`PATCH /profile` makes a narrow set of behaviour-affecting profile fields
editable (system_prompt, routing.mode, routing.preferred_provider), persisting
to profile.yaml and applying to the live runtime. These tests assert the
persistence + runtime application and — critically — that a validation failure
writes nothing and mutates nothing. Fully mocked via the `client` fixture; the
editable UI itself is JS-rendered and not exercised here (no JS runtime).
"""

from __future__ import annotations

import yaml

PROFILE_REL = "profiles/athena/profile.yaml"


def _read_profile(tmp_project):
    return yaml.safe_load((tmp_project / PROFILE_REL).read_text())


# ---------------------------------------------------------------------------
# Happy paths — persist + apply
# ---------------------------------------------------------------------------


def test_patch_system_prompt_persists_and_applies(client, tmp_project):
    resp = client.patch("/profile", json={"system_prompt": "Be terse."})
    assert resp.status_code == 200
    assert resp.json()["system_prompt"] == "Be terse."
    # persisted to disk
    assert _read_profile(tmp_project)["system_prompt"] == "Be terse."
    # reflected by a fresh GET (runtime _profile_data updated in place)
    assert client.get("/profile").json()["system_prompt"] == "Be terse."


def test_patch_mode_valid_persists(client, tmp_project):
    resp = client.patch("/profile", json={"mode": "quality-first"})
    assert resp.status_code == 200
    assert resp.json()["routing"]["mode"] == "quality-first"
    assert _read_profile(tmp_project)["routing"]["mode"] == "quality-first"


def test_patch_preferred_provider_valid_then_clear(client, tmp_project):
    name = client.get("/providers").json()[0]["name"]

    set_resp = client.patch("/profile", json={"preferred_provider": name})
    assert set_resp.status_code == 200
    assert set_resp.json()["routing"]["preferred_provider"] == name

    clear_resp = client.patch("/profile", json={"preferred_provider": ""})
    assert clear_resp.status_code == 200
    assert clear_resp.json()["routing"]["preferred_provider"] is None
    assert _read_profile(tmp_project)["routing"]["preferred_provider"] is None


def test_patch_writes_success_audit_event(client, monkeypatch):
    import main as app_module

    calls = []
    monkeypatch.setattr(app_module, "write_ops_event", lambda **kw: calls.append(kw))

    resp = client.patch("/profile", json={"mode": "balanced"})
    assert resp.status_code == 200
    assert any(
        c.get("event") == "settings_update" and c.get("outcome") == "success" for c in calls
    )


# ---------------------------------------------------------------------------
# Validation failures — no disk write, no runtime mutation
# ---------------------------------------------------------------------------


def test_invalid_mode_rejected_no_change(client, tmp_project):
    before = _read_profile(tmp_project)["routing"].get("mode")
    resp = client.patch("/profile", json={"mode": "ultra-fast"})
    assert resp.status_code == 400
    assert _read_profile(tmp_project)["routing"].get("mode") == before  # disk untouched
    assert client.get("/profile").json()["routing"].get("mode") == before  # runtime untouched


def test_unknown_preferred_provider_rejected(client, tmp_project):
    before = _read_profile(tmp_project)["routing"].get("preferred_provider")
    resp = client.patch("/profile", json={"preferred_provider": "definitely-not-a-provider"})
    assert resp.status_code == 400
    assert _read_profile(tmp_project)["routing"].get("preferred_provider") == before


def test_empty_body_rejected(client):
    resp = client.patch("/profile", json={})
    assert resp.status_code == 400


def test_oversized_system_prompt_rejected_no_write(client, tmp_project):
    before = _read_profile(tmp_project).get("system_prompt")
    resp = client.patch("/profile", json={"system_prompt": "x" * 9000})
    assert resp.status_code == 400
    assert _read_profile(tmp_project).get("system_prompt") == before


def test_non_editable_field_ignored(client, tmp_project):
    # `name` is outside the editable set; it must never be written, even when a
    # valid editable field is present in the same request.
    resp = client.patch("/profile", json={"name": "Hacked", "mode": "balanced"})
    assert resp.status_code == 200
    assert _read_profile(tmp_project).get("name") != "Hacked"
    assert client.get("/profile").json().get("name") != "Hacked"
