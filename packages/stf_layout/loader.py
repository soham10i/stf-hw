"""
Loading and caching of the canonical factory layout.

The default layout ships inside the package so that every process - kernel,
orchestrator, API, tests - resolves the same file without depending on the
current working directory. ``STF_LAYOUT`` overrides it, which is how an
alternate machine (or a fault-injection profile) is selected.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

from .schema import Layout

DEFAULT_LAYOUT_PATH = Path(__file__).parent / "factory.layout.yaml"
ENV_VAR = "STF_LAYOUT"


class LayoutError(RuntimeError):
    """Raised when a layout file is missing or fails validation."""


def layout_path() -> Path:
    override = os.environ.get(ENV_VAR)
    return Path(override).expanduser() if override else DEFAULT_LAYOUT_PATH


def load_layout(path: str | Path | None = None) -> Layout:
    """
    Parse and validate a layout file.

    Uncached: tests that mutate a layout on disk need a fresh read. Application
    code should call :func:`get_layout`.
    """
    resolved = Path(path) if path is not None else layout_path()
    if not resolved.is_file():
        raise LayoutError(f"layout file not found: {resolved}")

    try:
        raw = yaml.safe_load(resolved.read_text())
    except yaml.YAMLError as exc:
        raise LayoutError(f"{resolved} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise LayoutError(f"{resolved} must contain a mapping at the top level")

    try:
        return Layout.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError, re-raised with the path
        raise LayoutError(f"{resolved} failed validation:\n{exc}") from exc


@lru_cache(maxsize=4)
def _cached(resolved: Path) -> Layout:
    return load_layout(resolved)


def get_layout() -> Layout:
    """The process-wide layout. Cached; the file is read at most once."""
    return _cached(layout_path())


def clear_cache() -> None:
    _cached.cache_clear()


__all__ = [
    "DEFAULT_LAYOUT_PATH",
    "ENV_VAR",
    "LayoutError",
    "clear_cache",
    "get_layout",
    "load_layout",
    "layout_path",
]
