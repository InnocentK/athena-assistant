"""
tests/conftest.py — Shared pytest fixtures for Athena Assistant tests.

Key design decisions:
  - All tests use a temporary directory as APP_ROOT so no production
    config, profiles, or memory files are touched.
  - The FastAPI app is patched to use the temp root before import.
  - Fixtures are function-scoped by default for maximum isolation.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import yaml

# Real project root (used to copy providers.yaml)
_REAL_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Suite hermeticity: provider CLIs must never really run (M26.17)
# ---------------------------------------------------------------------------

# Binary names the CLI adapters probe with shutil.which().
_PROVIDER_BINARIES = {"claude", "gemini", "grok", "hermes", "chatgpt", "ollama"}


@pytest.fixture(autouse=True)
def _no_real_provider_clis(monkeypatch: pytest.MonkeyPatch):
    """Make every provider CLI look uninstalled, suite-wide.

    On a developer machine (or an agent sandbox) `claude`/`gemini`/… ARE on
    PATH. The router fixtures copy the real providers.yaml, so an unmocked
    `route()` would then invoke the REAL CLI — burning tokens and taking up to
    the 120s subprocess timeout (observed live: one router test jumping from
    <1s to 120s the moment a `claude` binary appeared on PATH). Availability
    is `shutil.which`-based, so blanking just the provider names keeps the
    suite hermetic while leaving which() intact for everything else. Tests
    that exercise "CLI available" paths patch which()/subprocess themselves,
    which overrides this autouse patch for their duration.
    """
    real_which = shutil.which

    def _filtered(cmd, *args, **kwargs):
        if cmd in _PROVIDER_BINARIES:
            return None
        return real_which(cmd, *args, **kwargs)

    monkeypatch.setattr(shutil, "which", _filtered)


# ---------------------------------------------------------------------------
# tmp_project fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """
    Set up a minimal but complete project tree under tmp_path.

    Creates:
      - config/app.yaml
      - config/providers.yaml  (copied from real project)
      - config/files.yaml      (minimal allowlist)
      - config/caldav.yaml     (disabled)
      - config/carddav.yaml    (disabled)
      - config/nextcloud.yaml  (disabled)
      - profiles/athena/profile.yaml
      - profiles/athena/memory/  (directory)
      - logs/, audit/, data/carddav_staged/  (directories)
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # app.yaml
    (config_dir / "app.yaml").write_text(yaml.safe_dump({"app_name": "Athena Test"}))

    # providers.yaml — copy from real project
    shutil.copy(_REAL_ROOT / "config" / "providers.yaml", config_dir / "providers.yaml")

    # files.yaml — minimal allowlist with data dir
    (config_dir / "files.yaml").write_text(
        yaml.safe_dump(
            {
                "entries": [
                    {
                        "path": "data",
                        "label": "Data directory",
                        "search": True,
                        "read": True,
                        "write": True,
                    },
                    {
                        "path": "logs",
                        "label": "Logs directory",
                        "search": True,
                        "read": True,
                        "write": False,
                    },
                ]
            }
        )
    )

    # caldav.yaml — disabled
    (config_dir / "caldav.yaml").write_text(yaml.safe_dump({"enabled": False}))

    # carddav.yaml — disabled
    (config_dir / "carddav.yaml").write_text(yaml.safe_dump({"enabled": False}))

    # nextcloud.yaml — disabled
    (config_dir / "nextcloud.yaml").write_text(yaml.safe_dump({"enabled": False}))

    # Profile directory
    profile_dir = tmp_path / "profiles" / "athena"
    memory_dir = profile_dir / "memory"
    memory_dir.mkdir(parents=True)

    profile_yaml = {
        "name": "Athena Test",
        "description": "Test profile",
        "system_prompt": "You are a test assistant.",
        "routing": {
            "mode": "balanced",
            "preferred_provider": None,
        },
        "memory": {
            "auto_save_threshold": "low",
            "require_review_for": [],
        },
        "allowed_tools": [],
    }
    (profile_dir / "profile.yaml").write_text(yaml.safe_dump(profile_yaml))

    # Memory category files
    for cat in ["preferences", "workflows", "operating_notes", "environment", "facts"]:
        (memory_dir / f"{cat}.yaml").write_text(yaml.safe_dump({cat: []}))
    (memory_dir / "pending_review.yaml").write_text(yaml.safe_dump({"pending": []}))

    # Directories
    (tmp_path / "logs").mkdir()
    (tmp_path / "audit").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "carddav_staged").mkdir()
    (tmp_path / "data" / "import_conflicts").mkdir()
    (tmp_path / "data" / "exports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "restore_staging").mkdir(parents=True, exist_ok=True)

    # Static and templates dirs — needed for FastAPI app startup
    static_src = _REAL_ROOT / "static"
    templates_src = _REAL_ROOT / "templates"
    if static_src.exists():
        shutil.copytree(static_src, tmp_path / "static")
    else:
        (tmp_path / "static").mkdir()
    if templates_src.exists():
        shutil.copytree(templates_src, tmp_path / "templates")
    else:
        (tmp_path / "templates").mkdir()

    return tmp_path


# ---------------------------------------------------------------------------
# client fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_project: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Return a synchronous FastAPI TestClient backed by a tmp project directory.

    Patches APP_ROOT in all modules that use it, clears lru_cache, forces a
    fresh import of main so the lifespan runs with the temp config.
    """
    monkeypatch.chdir(tmp_project)
    monkeypatch.setenv("ACTIVE_PROFILE", "athena")
    monkeypatch.setenv("APP_ENV", "test")

    # Remove modules that cache APP_ROOT at import time so patches take effect
    _mods_to_remove = [
        "main",
        "core.config",
        "core.loader",
        "core.logger",
        "files.manager",
        "memory.manager",
        "providers.router",
        "caldav_integration.client",
        "carddav_integration.client",
        "nextcloud_integration.client",
        "dav_io.vcf_io",
        "dav_io.ics_io",
        "dav_io",
        "backup.manager",
        "backup",
        "dav_status.store",
        "dav_status",
        "audit.ops_audit",
        "audit",
    ]
    for mod in _mods_to_remove:
        sys.modules.pop(mod, None)

    # Now import core.config fresh and patch APP_ROOT
    import core.config as cc  # noqa: PLC0415

    monkeypatch.setattr(cc, "APP_ROOT", tmp_project)

    # Clear lru_cache so Settings re-reads patched env vars
    cc.get_settings.cache_clear()

    # Patch files.manager module-level globals
    import files.manager as fm_mod  # noqa: PLC0415

    monkeypatch.setattr(fm_mod, "APP_ROOT", tmp_project)
    monkeypatch.setattr(fm_mod, "_FILES_CONFIG", tmp_project / "config" / "files.yaml")
    monkeypatch.setattr(fm_mod, "_AUDIT_DIR", tmp_project / "audit")

    # Remove main again before importing (module list might have grown)
    sys.modules.pop("main", None)

    import main as app_module  # noqa: PLC0415
    from fastapi.testclient import TestClient  # noqa: PLC0415

    with TestClient(app_module.app) as c:
        yield c

    # Cleanup: clear caches and remove imported modules so next test is fresh
    cc.get_settings.cache_clear()
    for mod in list(sys.modules.keys()):
        if mod == "main" or mod.startswith("main."):
            sys.modules.pop(mod, None)
