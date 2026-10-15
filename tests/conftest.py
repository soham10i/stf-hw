"""Shared fixtures. Nothing here may touch the network or a database."""

from __future__ import annotations

from pathlib import Path

import pytest

from stf_layout import Layout, load_layout

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def layout() -> Layout:
    """The canonical layout, loaded once per session."""
    return load_layout()


@pytest.fixture(scope="session")
def all_slots(layout: Layout) -> list[str]:
    return layout.all_slots()
