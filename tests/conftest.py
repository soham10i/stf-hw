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


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch, tmp_path):
    """Every test runs against a throwaway SQLite database and no model keys, whatever the
    repo's .env holds (the environment wins over .env): a test that loads the API never
    writes guests to the configured Supabase project or calls a model."""
    monkeypatch.setenv("STF_DB", "sqlite")
    monkeypatch.setenv("STF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STF_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("STF_SCHOLAR", "0")  # the literature search (scholar.py) stays offline
    for k in ("GEMINI_API_KEY", "GROQ_API_KEY", "ELEVENLABS_API_KEY", "SUPABASE_URL"):
        monkeypatch.setenv(k, "")
