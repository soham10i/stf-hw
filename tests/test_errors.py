"""The error codes (core/errors.py), the request id (core/request_context.py) and the log
filters (core/logging_config.py): one body for every failure, a stable code per situation, the
id that ties a visitor's report to the log, and repeated warnings collapsed."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from services.api.agent.chat import ModelError
from services.api.core import errors
from services.api.core.errors import AppError, Code, Reason
from services.api.core.logging_config import JsonFormatter, RepeatFilter, TextFormatter
from services.api.core.request_context import RequestIdMiddleware

DOC = Path(__file__).resolve().parents[1] / "docs" / "reference" / "architecture" / "error-codes.md"


class Body(BaseModel):
    n: int


def client() -> TestClient:
    app = FastAPI()
    errors.install(app)
    app.add_middleware(RequestIdMiddleware)

    @app.get("/budget")
    def budget():
        raise AppError(Reason.DAILY_BUDGET_SPENT, "today's question budget is used up")

    @app.get("/model")
    def model():
        raise ModelError("Groq did not answer in time", 30.0)

    @app.get("/crash")
    def crash():
        raise ZeroDivisionError("secret path /etc/x")

    @app.post("/body")
    def body(b: Body):
        return {"n": b.n}

    return TestClient(app, raise_server_exceptions=False)


def test_every_reason_has_one_code_and_every_wire_name_is_unique():
    names = [c.value for c in Code] + [r.value for r in Reason]
    assert len(names) == len(set(names))
    for reason in Reason:
        assert isinstance(reason.code, Code)
    for code in Code:
        assert Code.for_status(code.status) is code
    assert Code.for_status(418) is Code.BAD_REQUEST and Code.for_status(599) is Code.INTERNAL


def test_a_coded_failure_answers_with_the_one_body_and_its_request_id():
    r = client().get("/budget")
    body = r.json()
    assert r.status_code == 429
    assert body["code"] == "rate_limited" and body["reason"] == "daily_budget_spent"
    message = "today's question budget is used up"
    assert body["message"] == body["error"] == body["detail"] == message
    assert re.fullmatch(r"[0-9a-f]{16}", body["request_id"])
    assert r.headers["x-request-id"] == body["request_id"]


def test_a_callers_request_id_is_kept_and_a_strange_one_replaced():
    c = client()
    assert c.get("/budget", headers={"X-Request-ID": "trace-1234abcd"}).json()["request_id"] == (
        "trace-1234abcd"
    )
    odd = c.get("/budget", headers={"X-Request-ID": "<script>"}).json()["request_id"]
    assert odd != "<script>" and re.fullmatch(r"[0-9a-f]{16}", odd)


def test_a_service_error_that_escapes_keeps_its_code_and_safe_message():
    body = client().get("/model").json()
    assert body["status"] == 502 and body["reason"] == "model_failed"
    assert body["message"] == "Groq did not answer in time"


def test_an_unknown_exception_is_internal_and_its_text_is_never_shown():
    r = client().get("/crash")
    assert r.status_code == 500 and r.json()["code"] == "internal"
    assert "/etc/x" not in r.text


def test_an_unknown_route_and_a_bad_body_use_the_universal_codes():
    c = client()
    assert c.get("/nowhere").json()["code"] == "not_found"
    bad = c.post("/body", json={"n": "many"})
    body = bad.json()
    assert bad.status_code == 422 and body["code"] == "validation_failed"
    assert body["fields"][0]["field"] == "body.n"
    assert isinstance(body["detail"], str) and body["detail"].startswith("body.n: ")


def test_a_stream_reports_known_errors_by_code_and_hides_unknown_ones():
    known = errors.body_of(AppError(Reason.ORIGIN_DENIED, "origin not allowed"))
    assert known["reason"] == "origin_denied" and known["status"] == 403
    secret = RuntimeError("db password=x")
    unknown = errors.body_of(secret, Reason.COPILOT_FAILED, "the copilot failed")
    assert unknown["reason"] == "copilot_failed" and "password" not in json.dumps(unknown)


def test_the_live_api_answers_its_own_errors_with_codes():
    import services.api.app as appmod

    with TestClient(appmod.app) as c:
        r = c.post("/twin/state", content=b"[1, 2]", headers={"origin": "http://localhost:5173"})
    assert r.status_code == 400 and r.json()["code"] == "bad_request"


def test_the_error_code_document_lists_every_code_and_reason():
    text = DOC.read_text()
    missing = [m.value for m in [*Code, *Reason] if f"`{m.value}`" not in text]
    assert not missing, f"docs/reference/architecture/error-codes.md lacks {missing}"


def record(msg: str, level: int = logging.WARNING, t: float = 0.0) -> logging.LogRecord:
    r = logging.LogRecord("x", level, __file__, 1, msg, None, None)
    r.created = t
    return r


def test_a_repeated_warning_is_dropped_and_counted_when_it_passes_again():
    f = RepeatFilter(60.0)
    assert f.filter(record("down", t=0.0))
    assert not f.filter(record("down", t=1.0)) and not f.filter(record("down", t=2.0))
    assert f.filter(record("other", t=3.0))
    again = record("down", t=61.0)
    assert f.filter(again) and again.getMessage() == "down (repeated 2x, not logged)"
    assert f.filter(record("info", logging.INFO, 1.0))
    assert f.filter(record("info", logging.INFO, 1.1))


def test_the_json_and_text_lines_carry_the_request_id():
    r = record("hello")
    r.request_id = "abcd1234abcd1234"
    line = json.loads(JsonFormatter().format(r))
    assert line["severity"] == "WARNING" and line["message"] == "hello"
    assert line["request_id"] == "abcd1234abcd1234"
    assert "[abcd1234abcd1234]: hello" in TextFormatter().format(r)
