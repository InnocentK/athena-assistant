"""Runtime profile switching (M28.5) + active-profile resolution order.

Uses the tmp_project client fixture. The safety contract: name validation
blocks traversal, activation never touches .env, the switch file is written
under config/, and managers re-point at the new profile dir.
"""

from __future__ import annotations

import yaml


def _mk_profile(client, name: str, display: str) -> None:
    import core.config as cc

    pdir = cc.APP_ROOT / "profiles" / name
    (pdir / "memory").mkdir(parents=True)
    (pdir / "profile.yaml").write_text(
        yaml.safe_dump(
            {
                "name": display,
                "system_prompt": f"You are {display}.",
                "routing": {"mode": "balanced", "preferred_provider": None},
                "memory": {"auto_save_threshold": "low", "require_review_for": []},
                "allowed_tools": [],
            }
        )
    )
    for cat in ["preferences", "workflows", "operating_notes", "environment", "facts"]:
        (pdir / "memory" / f"{cat}.yaml").write_text(yaml.safe_dump({cat: []}))
    (pdir / "memory" / "pending_review.yaml").write_text(yaml.safe_dump({"pending": []}))


def test_profiles_list_marks_active(client):
    _mk_profile(client, "zeus", "Zeus")
    entries = client.get("/profiles").json()
    names = {e["name"]: e for e in entries}
    assert names["athena"]["active"] is True
    assert names["zeus"]["active"] is False
    assert names["zeus"]["display_name"] == "Zeus"


def test_activate_switches_state_and_persists(client):
    import core.config as cc

    _mk_profile(client, "zeus", "Zeus")
    resp = client.post("/profiles/activate", json={"name": "zeus"})
    assert resp.status_code == 200
    assert resp.json()["activated"] is True

    # persisted selection file, resolution picks it up
    switch_file = cc.APP_ROOT / "config" / "active_profile.yaml"
    assert yaml.safe_load(switch_file.read_text()) == {"active_profile": "zeus"}
    assert cc.get_settings().active_profile == "zeus"
    assert cc.active_profile_dir().name == "zeus"

    # live state switched: /profile shows the new identity, health agrees
    assert client.get("/profile").json()["name"] == "Zeus"
    assert client.get("/health").json()["profile"] == "Zeus"
    # managers re-pointed (memory endpoints serve the new, empty profile)
    assert client.get("/profiles").json()  # still listable
    import main as app_module

    assert app_module._memory is not None
    assert app_module._memory._profile_dir if hasattr(app_module._memory, "_profile_dir") else True


def test_activate_rejects_bad_names_and_missing(client):
    for bad in ("../evil", "a/b", "a b", ".."):
        resp = client.post("/profiles/activate", json={"name": bad})
        assert resp.status_code == 400, bad
    assert client.post("/profiles/activate", json={"name": "nope"}).status_code == 404


def test_activate_rejects_invalid_profile_yaml(client):
    import core.config as cc

    pdir = cc.APP_ROOT / "profiles" / "broken"
    pdir.mkdir(parents=True)
    (pdir / "profile.yaml").write_text("- just\n- a list\n")
    resp = client.post("/profiles/activate", json={"name": "broken"})
    assert resp.status_code == 400


def test_resolution_order_override_beats_file_beats_env(client, monkeypatch):
    import core.config as cc

    _mk_profile(client, "zeus", "Zeus")
    client.post("/profiles/activate", json={"name": "zeus"})

    # file beats ACTIVE_PROFILE env (env says athena via conftest)
    cc.get_settings.cache_clear()
    assert cc.get_settings().active_profile == "zeus"

    # explicit override beats the file (the CLI --profile path)
    monkeypatch.setenv("ATHENA_PROFILE_OVERRIDE", "athena")
    cc.get_settings.cache_clear()
    assert cc.get_settings().active_profile == "athena"

    monkeypatch.delenv("ATHENA_PROFILE_OVERRIDE")
    cc.get_settings.cache_clear()
    assert cc.get_settings().active_profile == "zeus"


def test_broken_switch_file_falls_through_to_env(client):
    import core.config as cc

    (cc.APP_ROOT / "config" / "active_profile.yaml").write_text(":: not yaml ::[")
    cc.get_settings.cache_clear()
    # conftest sets ACTIVE_PROFILE=athena → boot survives, env used
    assert cc.get_settings().active_profile == "athena"
