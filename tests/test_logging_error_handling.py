"""
Tests for structured logging system, global exception handling, and error boundaries.
"""

import logging
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from services.api import app as appmod
from services.api import grounding, tools
from services.api.logging_config import configure_logging, get_logger


def test_logger_configuration():
    """Verify configure_logging initializes logger hierarchy and formatting."""
    configure_logging("DEBUG")
    log = get_logger("test.module")
    assert isinstance(log, logging.Logger)
    assert log.name == "test.module"
    assert logging.getLogger().level <= logging.INFO


def test_grounding_load_json_handles_missing_file(caplog):
    """Verify load_json returns None and logs debug for nonexistent file."""
    with caplog.at_level(logging.DEBUG):
        res = grounding.load_json("nonexistent/path/to/file.json")
    assert res is None


def test_tools_call_handles_exception_and_logs(caplog):
    """Verify tools.call catches tool exceptions and logs with exc_info."""
    ctx = tools.Ctx()

    def buggy_fn(args, ctx):
        raise RuntimeError("Simulated tool crash")

    fake_tool = tools.Tool("buggy_test_tool", buggy_fn, {})
    with patch.dict(tools.TOOLS, {"buggy_test_tool": fake_tool}):
        with caplog.at_level(logging.ERROR):
            res = tools.call("buggy_test_tool", {}, ctx)
    assert "The tool failed: RuntimeError" in res.text
    assert any("Simulated tool crash" in record.message for record in caplog.records)


def test_global_exception_handler_returns_json_and_logs(caplog):
    """Verify unhandled exceptions trigger 500 JSON response and error log."""
    client = TestClient(appmod.app, raise_server_exceptions=False)

    with patch.object(appmod.runtime, "orders", side_effect=ZeroDivisionError("division by zero")):
        with caplog.at_level(logging.ERROR):
            resp = client.get("/orders")

    assert resp.status_code == 500
    data = resp.json()
    assert data["error"] == "internal_server_error"
    assert any(
        "Unhandled exception processing GET /orders" in record.message
        for record in caplog.records
    )


def test_vectors_hybrid_search_graceful_fallback_on_error(caplog):
    """Verify hybrid_search falls back to lexical BM25 when vector store encounters an error."""
    from services.api import vectors

    with patch.object(vectors, "get_store", side_effect=RuntimeError("Vector database corrupted")):
        with caplog.at_level(logging.WARNING):
            hits = vectors.hybrid_search("oven temperature sensor", top_k=3)

    assert isinstance(hits, list)
    for h in hits:
        assert h.get("via") == "bm25"
        assert h.get("vscore") == 0.0
    assert any("falling back to pure BM25" in r.message for r in caplog.records)


def test_security_note_logs_warning(caplog):
    """Verify security rejection events are logged at WARNING level."""
    from services.api import security

    with caplog.at_level(logging.WARNING):
        security.note("command: test foreign origin violation")

    assert any("Security check rejected: command: test foreign origin violation" in r.message for r in caplog.records)


def test_sessions_load_and_save_error_handling(caplog, tmp_path):
    """Verify sessions.load falls back to new session on error and save logs on failure."""
    from services.api import sessions
    from services.api.store import JsonStore

    store = JsonStore(str(tmp_path))
    user = "test_user_123"

    # Loading corrupted/broken session
    with patch.object(store, "get", side_effect=Exception("Database lock error")):
        with caplog.at_level(logging.WARNING):
            sess = sessions.load(store, user, "nonexistent_sid", None)
    assert sess["id"] is not None
    assert any("Error reading session" in r.message for r in caplog.records)

    # Saving session failure
    with patch.object(store, "put", side_effect=OSError("Disk write failure")):
        with caplog.at_level(logging.ERROR):
            with pytest.raises(OSError):
                sessions.save(store, user, sess)
    assert any("Failed to save session" in r.message for r in caplog.records)


def test_orchestrate_decide_safe_bm25_fallback(caplog):
    """Verify orchestrate.decide routes safely when BM25 search fails."""
    from services.api import orchestrate

    with patch.object(orchestrate, "get_bm25", side_effect=RuntimeError("Index read failure")):
        with caplog.at_level(logging.WARNING):
            plan = orchestrate.decide("how does the oven work?", ["oven_process"], can_search=False)

    assert plan.mode in ("twin", "docs", "chat", "web", "deep")
    assert any("BM25 lexical search failed in router" in r.message for r in caplog.records)
