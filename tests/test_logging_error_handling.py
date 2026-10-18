"""
Tests for structured logging system, global exception handling, and error boundaries.
"""

import json
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
    assert any("Unhandled exception processing GET /orders" in record.message for record in caplog.records)
