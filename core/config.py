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

class Settings:
    """
    Application settings resolved from environment variables.

    We use a plain class rather than pydantic-settings to keep the
    dependency surface minimal in Milestone 1.  All values are read
    from os.environ (populated by python-dotenv above).
    """

    def __init__(self) -> None:
        self.app_env: str = os.environ.get("APP_ENV", "development")
        self.log_level: str = os.environ.get("LOG_LEVEL", "INFO").upper()
        self.active_profile: str = os.environ.get("ACTIVE_PROFILE", "athena")

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
