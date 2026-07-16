"""
core/config.py — Application settings and path helpers.

APP_ROOT is the project root (parent of this file's directory).
All path helpers resolve relative to APP_ROOT so no absolute paths
are ever hardcoded elsewhere in the codebase.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Project root — two levels up from this file (core/config.py → core/ → root)
# ---------------------------------------------------------------------------
APP_ROOT: Path = Path(__file__).parent.parent.resolve()

# Load .env from project root (silently ignored if the file doesn't exist)
load_dotenv(dotenv_path=APP_ROOT / ".env")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def _resolve_active_profile() -> str:
    """
    Resolve the active profile name (M28.5). Precedence:

      1. ``ATHENA_PROFILE_OVERRIDE`` env — process-scoped explicit override
         (the CLI's ``--profile`` flag sets this); beats everything.
      2. ``config/active_profile.yaml`` (key ``active_profile``) — the
         runtime-switch persistence file, written ONLY by
         ``POST /profiles/activate``. Deliberately beats ACTIVE_PROFILE:
         `.env` sets that on default installs, and a UI switch must survive
         a restart there. Delete the file (or switch back) to return control
         to the environment.
      3. ``ACTIVE_PROFILE`` env (usually via `.env`).
      4. ``"athena"``.

    The file read is defensive: unreadable/invalid → fall through to env.
    Reads module-global APP_ROOT at call time (tests monkeypatch it).
    """
    override = os.environ.get("ATHENA_PROFILE_OVERRIDE", "").strip()
    if override:
        return override
    try:
        path = APP_ROOT / "config" / "active_profile.yaml"
        if path.exists():
            import yaml  # noqa: PLC0415 — keep config import-light at module load

            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            name = data.get("active_profile") if isinstance(data, dict) else None
            if isinstance(name, str) and name.strip():
                return name.strip()
    except Exception:  # noqa: BLE001 — a broken switch file must not brick boot
        pass
    return os.environ.get("ACTIVE_PROFILE", "athena")


class Settings:
    """
    Application settings resolved from environment variables.

    We use a plain class rather than pydantic-settings to keep the
    dependency surface minimal in Milestone 1.  All values are read
    from os.environ (populated by python-dotenv above), except the active
    profile, which resolves override > switch-file > env > default (M28.5).
    """

    def __init__(self) -> None:
        self.app_env: str = os.environ.get("APP_ENV", "development")
        self.log_level: str = os.environ.get("LOG_LEVEL", "INFO").upper()
        self.active_profile: str = _resolve_active_profile()

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"Settings(app_env={self.app_env!r}, "
            f"log_level={self.log_level!r}, "
            f"active_profile={self.active_profile!r})"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached singleton Settings instance."""
    return Settings()


# ---------------------------------------------------------------------------
# Path helpers — all resolve relative to APP_ROOT
# ---------------------------------------------------------------------------

def profiles_dir() -> Path:
    """Return the path to the profiles/ directory."""
    return APP_ROOT / "profiles"


def active_profile_dir() -> Path:
    """Return the path to the currently active profile directory."""
    return profiles_dir() / get_settings().active_profile


def logs_dir() -> Path:
    """Return the path to the logs/ directory."""
    return APP_ROOT / "logs"


def audit_dir() -> Path:
    """Return the path to the audit/ directory."""
    return APP_ROOT / "audit"


def data_dir() -> Path:
    """Return the path to the data/ directory."""
    return APP_ROOT / "data"
