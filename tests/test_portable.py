"""Portable Profiles — export (M28.0).

The leak-guard tests are the milestone: a planted secret/URL/host-path must
never emit a bundle. Everything runs against the tmp_project client fixture —
no real providers, no network.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import yaml


def _exports_dir(client) -> Path:
    import core.config as cc

    return cc.APP_ROOT / "data" / "exports"


def _bundle(client, body=None):
    resp = client.post("/portable/exports", json=body or {})
    return resp


def _read_bundle(client, filename: str) -> dict:
    """Return {'manifest': .., 'profile': .., 'memory': {cat: [entries]}}."""
    with zipfile.ZipFile(_exports_dir(client) / filename) as zf:
        manifest = json.loads(zf.read("athena_portable_manifest.json"))
        profile = yaml.safe_load(zf.read("profile.yaml"))
        memory = {}
        for name in zf.namelist():
            if name.startswith("memory/"):
                cat = Path(name).stem
                memory[cat] = (yaml.safe_load(zf.read(name)) or {}).get(cat, [])
    return {"manifest": manifest, "profile": profile, "memory": memory}


def _seed_memory(category: str, entries: list[dict]) -> None:
    import core.config as cc

    mem = cc.APP_ROOT / "profiles" / "athena" / "memory" / f"{category}.yaml"
    mem.write_text(yaml.safe_dump({category: entries}))


def _seed_profile(extra: dict) -> None:
    import core.config as cc

    path = cc.APP_ROOT / "profiles" / "athena" / "profile.yaml"
    data = yaml.safe_load(path.read_text())
    data.update(extra)
    path.write_text(yaml.safe_dump(data))


# ---------------------------------------------------------------------------
# Happy path: identity travels, host/ops data does not
# ---------------------------------------------------------------------------


def test_export_keeps_identity_and_strips_host_fields(client):
    _seed_profile(
        {
            "machine_overrides": {"laptop": {"routing": {"mode": "cost-first"}}},
            "memory": {
                "path": "/Users/somebody/custom/memory",
                "auto_save_threshold": "low",
                "require_review_for": ["pii"],
            },
        }
    )
    _seed_memory("facts", [{"id": "mem_aaa11111", "key": "likes", "value": "tea"}])

    resp = _bundle(client)
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] is True
    assert "snapshot" in data["snapshot_note"].lower()

    bundle = _read_bundle(client, data["filename"])
    profile = bundle["profile"]
    # identity kept
    assert profile["system_prompt"]
    assert profile["memory"]["require_review_for"] == ["pii"]
    assert bundle["memory"]["facts"][0]["key"] == "likes"
    # host/ops data stripped (allowlist: absent, not blanked)
    assert profile["machine_overrides"] == {}
    assert "path" not in profile["memory"]
    # no machine identifier in the manifest
    assert "hostname" not in bundle["manifest"]
    assert bundle["manifest"]["type"] == "athena-portable-profile"


def test_pending_review_and_config_never_travel(client):
    import core.config as cc

    pending = cc.APP_ROOT / "profiles" / "athena" / "memory" / "pending_review.yaml"
    pending.write_text(yaml.safe_dump({"pending": [{"id": "mem_p1", "key": "unreviewed"}]}))

    resp = _bundle(client)
    assert resp.status_code == 200
    with zipfile.ZipFile(_exports_dir(client) / resp.json()["filename"]) as zf:
        names = zf.namelist()
    assert not any("pending_review" in n for n in names)
    assert not any(n.startswith("config/") for n in names)
    assert not any(".env" in n for n in names)


# ---------------------------------------------------------------------------
# The review step: preview + exclude_ids
# ---------------------------------------------------------------------------


def test_preview_lists_entries_and_exclusion_is_honored(client):
    _seed_memory(
        "preferences",
        [
            {"id": "mem_keep0001", "key": "tone", "value": "direct"},
            {"id": "mem_drop0001", "key": "private", "value": "sensitive thing"},
        ],
    )
    prev = client.get("/portable/preview")
    assert prev.status_code == 200
    ids = [e["id"] for e in prev.json()["memory_entries"]]
    assert "mem_keep0001" in ids and "mem_drop0001" in ids

    resp = _bundle(client, {"exclude_ids": ["mem_drop0001"]})
    assert resp.status_code == 200
    assert resp.json()["memory_entries_excluded"] == 1
    bundle = _read_bundle(client, resp.json()["filename"])
    kept_ids = [e["id"] for e in bundle["memory"]["preferences"]]
    assert kept_ids == ["mem_keep0001"]


# ---------------------------------------------------------------------------
# THE LEAK GUARD — a striplist hit must never emit a bundle
# ---------------------------------------------------------------------------


def test_env_secret_value_in_memory_hard_fails(client):
    import core.config as cc

    (cc.APP_ROOT / ".env").write_text("OPENAI_API_KEY=supersecretvalue123\n")
    _seed_memory("facts", [{"id": "mem_x1", "key": "oops", "value": "supersecretvalue123"}])

    resp = _bundle(client)
    assert resp.status_code == 409
    # nothing was emitted
    assert not list(_exports_dir(client).glob("*_athena_portable.zip"))


def test_credential_shaped_string_hard_fails(client):
    _seed_memory(
        "facts", [{"id": "mem_x2", "key": "k", "value": "sk-abcdefghijklmnop1234"}]
    )
    resp = _bundle(client)
    assert resp.status_code == 409
    assert not list(_exports_dir(client).glob("*_athena_portable.zip"))


def test_url_in_profile_fields_hard_fails(client):
    _seed_profile({"system_prompt": "Sync via https://nextcloud.internal.example/dav"})
    resp = _bundle(client)
    assert resp.status_code == 409


def test_url_in_memory_is_warning_not_failure(client):
    _seed_memory(
        "facts", [{"id": "mem_x3", "key": "docs", "value": "see https://example.com/guide"}]
    )
    resp = _bundle(client)
    assert resp.status_code == 200
    assert any("URL" in w for w in resp.json()["warnings"])


# ---------------------------------------------------------------------------
# Listing separation from full backups
# ---------------------------------------------------------------------------


def test_portable_list_excludes_full_backups_and_vice_versa(client):
    ok = _bundle(client)
    assert ok.status_code == 200
    full = client.post("/backup/exports", json={})
    assert full.status_code == 200

    portable_names = {e["filename"] for e in client.get("/portable/exports").json()}
    backup_names = {e["filename"] for e in client.get("/backup/exports").json()}
    assert ok.json()["filename"] in portable_names
    assert full.json()["filename"] in backup_names
    assert not portable_names & backup_names


# ---------------------------------------------------------------------------
# Import (M28.1)
# ---------------------------------------------------------------------------


def _write_bundle(client, *, profile: dict, memory: dict[str, list] | None = None,
                  manifest_extra: dict | None = None, name="hand_bundle.zip") -> str:
    """Hand-craft a portable bundle zip in data/exports/ (attacker-controlled)."""
    manifest = {
        "type": "athena-portable-profile",
        "portable_version": "1",
        "profile_name": profile.get("name", "X"),
    }
    manifest.update(manifest_extra or {})
    path = _exports_dir(client) / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("athena_portable_manifest.json", json.dumps(manifest))
        zf.writestr("profile.yaml", yaml.safe_dump(profile))
        for cat, items in (memory or {}).items():
            zf.writestr(f"memory/{cat}.yaml", yaml.safe_dump({cat: items}))
    return name


def test_import_round_trip_preserves_identity(client):
    import core.config as cc

    _seed_memory("facts", [{"id": "mem_rt1", "key": "likes", "value": "tea"}])
    exported = _bundle(client).json()["filename"]

    resp = client.post(
        "/portable/import", json={"zip_filename": exported, "new_name": "athena-two"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] is True and data["profile_slug"] == "athena-two"
    assert "fork" in data["fork_warning"].lower() or "snapshot" in data["fork_warning"].lower()

    new_dir = cc.APP_ROOT / "profiles" / "athena-two"
    prof = yaml.safe_load((new_dir / "profile.yaml").read_text())
    assert prof["system_prompt"] == "You are a test assistant."
    facts = yaml.safe_load((new_dir / "memory" / "facts.yaml").read_text())["facts"]
    assert facts[0]["key"] == "likes"
    pending = yaml.safe_load((new_dir / "memory" / "pending_review.yaml").read_text())
    assert pending == {"pending": []}


def test_import_never_clobbers_existing_profile(client):
    exported = _bundle(client).json()["filename"]
    # the bundle's own name slugifies to an existing profile dir? Use new_name
    # pointing at the ACTIVE profile to attempt a clobber.
    resp = client.post(
        "/portable/import", json={"zip_filename": exported, "new_name": "athena"}
    )
    assert resp.status_code == 409
    assert "never overwrites" in resp.json()["detail"]


def test_import_rejects_wrong_bundle_type(client):
    full = client.post("/backup/exports", json={}).json()["filename"]
    resp = client.post("/portable/import", json={"zip_filename": full, "new_name": "x1"})
    assert resp.status_code == 409


def test_import_rejects_planted_secret_and_writes_nothing(client):
    import core.config as cc

    name = _write_bundle(
        client,
        profile={"name": "Evil", "system_prompt": "hi"},
        memory={"facts": [{"id": "m1", "key": "k", "value": "sk-abcdefghijklmnop1234"}]},
    )
    resp = client.post("/portable/import", json={"zip_filename": name, "new_name": "evil"})
    assert resp.status_code == 409
    assert not (cc.APP_ROOT / "profiles" / "evil").exists()


def test_import_re_sanitizes_host_fields(client):
    import core.config as cc

    name = _write_bundle(
        client,
        profile={
            "name": "Sneaky",
            "system_prompt": "hello",
            "machine_overrides": {"box": {"x": 1}},
            "memory": {"path": "../../outside", "auto_save_threshold": "low"},
        },
    )
    resp = client.post("/portable/import", json={"zip_filename": name, "new_name": "sneaky"})
    assert resp.status_code == 200
    prof = yaml.safe_load(
        (cc.APP_ROOT / "profiles" / "sneaky" / "profile.yaml").read_text()
    )
    assert prof["machine_overrides"] == {}
    assert "path" not in prof["memory"]


def test_import_warns_on_unknown_provider_but_succeeds(client):
    name = _write_bundle(
        client,
        profile={
            "name": "Wanderer",
            "system_prompt": "hi",
            "routing": {"mode": "balanced", "fallback_order": ["claude", "not-a-provider"]},
        },
    )
    resp = client.post("/portable/import", json={"zip_filename": name, "new_name": "wanderer"})
    assert resp.status_code == 200
    assert any("not-a-provider" in w for w in resp.json()["warnings"])
