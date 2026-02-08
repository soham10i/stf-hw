"""
STF Digital Twin - Structured Logging Configuration

Provides centralized logging setup for all modules, replacing print() statements
with structured, leveled logging as required by Industry 4.0 observability standards.

Usage:
    from utils.logging_config import get_logger
    logger = get_logger("module_name")
    logger.info("System started")
    logger.warning("Health score low", extra={"device_id": "HBW_X", "score": 0.3})
"""

import logging
import os
import sys
from datetime import datetime, timezone


LOG_LEVEL = os.environ.get("STF_LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.environ.get(
    "STF_LOG_FORMAT",
    "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

_configured = False


def setup_logging() -> None:
    """Configure the root logger for the STF Digital Twin system."""
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

    root = logging.getLogger()
    root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    # Avoid adding duplicate handlers on repeated calls
    if not root.handlers:
        root.addHandler(handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger, ensuring the root logger is configured.

    Parameters
    ----------
    name : str
        Dot-separated logger name, e.g. ``"api"`` or ``"controller.kinematic"``.
    """
    setup_logging()
    return logging.getLogger(name)
