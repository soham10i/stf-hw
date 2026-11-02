"""
Centralized structured logging configuration for the STF Digital Twin backend.

Provides a unified logging setup with standardized formatting, ISO timestamps,
log level control via environment variables (LOG_LEVEL or STF_LOG_LEVEL), and
module logger retrieval.
"""

from __future__ import annotations

import logging
import os
import sys

DEFAULT_LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def configure_logging(
    level: str | int | None = None,
    log_format: str = DEFAULT_LOG_FORMAT,
    date_format: str = DEFAULT_DATE_FORMAT,
) -> None:
    """Configure the root and application loggers with structured formatting.

    Args:
        level: Optional log level name ('DEBUG', 'INFO', 'WARNING', 'ERROR') or integer.
            If not specified, reads from STF_LOG_LEVEL or LOG_LEVEL environment variable,
            defaulting to 'INFO'.
        log_format: String format for log records.
        date_format: Format for timestamp string.
    """
    global _configured
    if _configured:
        return

    if level is None:
        level_name = os.environ.get("STF_LOG_LEVEL") or os.environ.get("LOG_LEVEL", "INFO")
        resolved_level = getattr(logging, level_name.upper(), logging.INFO)
    elif isinstance(level, str):
        resolved_level = getattr(logging, level.upper(), logging.INFO)
    else:
        resolved_level = level

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(fmt=log_format, datefmt=date_format)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(resolved_level)

    # Avoid adding duplicate handlers if root already has one
    if not root.handlers:
        root.addHandler(handler)
    else:
        for existing in root.handlers:
            existing.setFormatter(formatter)

    # Suppress verbose debug outputs from external dependencies unless specifically requested
    for noisy in ("urllib3", "asyncio", "multipart"):
        logging.getLogger(noisy).setLevel(max(resolved_level, logging.WARNING))

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger for the specified module name.

    Args:
        name: Name of the module (typically __name__).

    Returns:
        logging.Logger: The logger instance configured for the module.
    """
    if not _configured:
        configure_logging()
    return logging.getLogger(name)
