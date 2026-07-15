"""
core/logger.py — Shared logger setup for Athena Assistant.

Import the logger with:
    from core.logger import get_logger
    logger = get_logger()

Or use the module-level convenience instance:
    from core.logger import logger
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def _ensure_logs_dir(logs_path: Path) -> None:
    """Create the logs directory if it doesn't exist."""
    try:
        logs_path.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Fall back gracefully — file logging will be skipped below
        pass


def _build_logger(name: str = "athena") -> logging.Logger:
    """
    Build and configure the named logger.

    Handlers are only added once; calling this function multiple times
    returns the same logger without duplicating handlers.
    """
    # Defer the settings import to avoid circular imports at module load time
    from core.config import get_settings, logs_dir  # noqa: PLC0415

    settings = get_settings()
    log_level = getattr(logging, settings.log_level, logging.INFO)

    _logger = logging.getLogger(name)

    # Guard: don't add handlers if already configured (e.g. module reloads)
    if _logger.handlers:
        return _logger

    _logger.setLevel(log_level)

    formatter = logging.Formatter(
        fmt="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # --- stdout handler ---
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(log_level)
    stdout_handler.setFormatter(formatter)
    # M26.6: tag this as Athena's own console handler. The CLI
    # (_configure_cli_logging) retargets ONLY tagged handlers to stderr, so it
    # never clobbers handlers a third party (e.g. pytest's log capture) attaches
    # to this shared, non-propagating logger.
    stdout_handler._athena_console = True  # type: ignore[attr-defined]
    _logger.addHandler(stdout_handler)

    # --- file handler ---
    log_file = logs_dir() / "app.log"
    _ensure_logs_dir(logs_dir())

    try:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        _logger.addHandler(file_handler)
    except OSError as exc:
        # If we can't open the log file, warn on stdout but keep running
        _logger.warning("Could not open log file %s: %s — file logging disabled.", log_file, exc)

    # Prevent log records from propagating to the root logger
    _logger.propagate = False

    return _logger


def get_logger(name: str = "athena") -> logging.Logger:
    """Return the configured application logger."""
    return _build_logger(name)


# Module-level convenience instance — available via `from core.logger import logger`
logger: logging.Logger = get_logger()
