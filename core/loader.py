"""
core/loader.py — YAML file read/write utilities.

All YAML I/O in the project must go through these two functions so that
error handling, logging, and directory creation are consistent everywhere.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("athena")


def load_yaml(path: Path) -> dict[str, Any]:
    """
    Load a YAML file and return its contents as a dict.

    Returns an empty dict if the file does not exist or is empty.
    Logs a warning for missing files and an error for parse failures
    (returning an empty dict in both cases so callers never crash).
    """
    path = Path(path)

    if not path.exists():
        logger.warning("YAML file not found, returning empty dict: %s", path)
        return {}

    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
            return data if isinstance(data, dict) else {}
    except yaml.YAMLError as exc:
        logger.error("Failed to parse YAML file %s: %s", path, exc)
        return {}
    except OSError as exc:
        logger.error("Could not read YAML file %s: %s", path, exc)
        return {}


def save_yaml(path: Path, data: dict[str, Any], sort_keys: bool = True) -> None:
    """
    Write *data* to a YAML file at *path*.

    Creates all intermediate directories if they do not exist.
    Logs an error on failure but does not raise so callers stay stable.

    ``sort_keys`` defaults to True (existing behaviour). Pass ``sort_keys=False``
    to preserve the in-dict key order — used when rewriting human-authored files
    like ``profile.yaml`` so the on-disk diff stays minimal (M26). Note: YAML
    comments are not preserved by ``safe_dump`` either way.
    """
    path = Path(path)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(
                data, fh, default_flow_style=False, allow_unicode=True, sort_keys=sort_keys
            )
        logger.debug("Saved YAML file: %s", path)
    except OSError as exc:
        logger.error("Could not write YAML file %s: %s", path, exc)
