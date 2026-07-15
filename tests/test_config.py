"""
tests/test_config.py — Tests for core/config.py and profile loading.
"""

from __future__ import annotations

from pathlib import Path



def test_app_root_is_path():
    """APP_ROOT is a Path instance and is absolute."""
    from core.config import APP_ROOT

    assert isinstance(APP_ROOT, Path)
    assert APP_ROOT.is_absolute()


def test_profiles_dir_is_under_app_root():
    """profiles_dir() returns a path whose final component is 'profiles'."""
    from core.config import profiles_dir

    assert profiles_dir().name == "profiles"


def test_active_profile_dir_uses_env(monkeypatch):
    """get_settings().active_profile reflects the ACTIVE_PROFILE env var."""
    import core.config as cc

    monkeypatch.setenv("ACTIVE_PROFILE", "testprofile")
    cc.get_settings.cache_clear()

    assert cc.get_settings().active_profile == "testprofile"

    # Reset
    cc.get_settings.cache_clear()
    monkeypatch.delenv("ACTIVE_PROFILE", raising=False)


def test_settings_defaults(monkeypatch):
    """Without env vars, app_env defaults to 'development' and active_profile to 'athena'."""
    import core.config as cc

    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ACTIVE_PROFILE", raising=False)
    cc.get_settings.cache_clear()

    s = cc.get_settings()
    assert s.app_env == "development"
    assert s.active_profile == "athena"

    # Restore cache state for subsequent tests
    cc.get_settings.cache_clear()


def test_logs_dir_is_under_app_root():
    """logs_dir() returns a path named 'logs' under APP_ROOT."""
    from core.config import APP_ROOT, logs_dir

    assert logs_dir() == APP_ROOT / "logs"


def test_audit_dir_is_under_app_root():
    """audit_dir() returns a path named 'audit' under APP_ROOT."""
    from core.config import APP_ROOT, audit_dir

    assert audit_dir() == APP_ROOT / "audit"
