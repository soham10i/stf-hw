"""Tracing (tracing.py): one trace per question, a span per graph node and per model, tool and
search call, returned with the reply for the thinking drawer and exported over OTLP/HTTP - to
Phoenix, and to Langfuse with its basic auth - checked on the wire with a local receiver that
decodes what the exporter sends. Without STF_TRACE_CONTENT no question or answer text leaves
the process, and the guest is never exported as an address."""

from __future__ import annotations

import asyncio
import base64
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("opentelemetry.sdk")

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (  # noqa: E402
    ExportTraceServiceRequest,
)

from services.api import chat as C  # noqa: E402
from services.api import sessions as S  # noqa: E402
from services.api import tracing as TR  # noqa: E402

from .test_chat import req  # noqa: E402
from .test_orchestrate import groq_chat  # noqa: E402

Q = "which part needs service first?"
TOOL_CALL = {"choices": [{"message": {"content": "", "tool_calls": [
    {"id": "t1", "function": {"name": "machine_health", "arguments": "{}"}}]}}],
    "usage": {"prompt_tokens": 1200, "completion_tokens": 40}}
ANSWER = {"choices": [{"message": {"content": "The belt warns in 0.6 shifts."}}],
          "usage": {"prompt_tokens": 1500, "completion_tokens": 30}}


@pytest.fixture(autouse=True)
def fresh_tracer():
    TR.reset(None)
    yield
    TR.reset(None)


def ask(question=Q, engine="graph", monkeypatch=None):
    chat = groq_chat()
    replies = iter([TOOL_CALL, ANSWER])
    chat.post_groq = lambda url, key, body: next(replies, ANSWER)
    if monkeypatch:
        monkeypatch.setenv("STF_AGENT", engine)
    return asyncio.run(chat.ask(C.ChatRequest(question=question), req()))


@pytest.mark.parametrize("engine", ["graph", "linear"])
def test_the_reply_carries_its_trace(engine, monkeypatch):
    out = ask(engine=engine, monkeypatch=monkeypatch)
    t = out["trace"]
    assert len(t["id"]) == 32 and int(t["id"], 16) and t["stores"] == []
    names = [s["name"] for s in t["spans"]]
    for n in ("node.prepare", "node.route", "node.answer", "llm.groq", "tool.machine_health",
              "node.verify"):
        assert n in names, n
    by = {s["name"]: s for s in t["spans"]}
    assert by["node.answer"]["depth"] == 1 and by["llm.groq"]["depth"] == 2
    llm = [s for s in t["spans"] if s["name"] == "llm.groq"]
    assert llm[0]["attrs"]["gen_ai.usage.input_tokens"] == 1200
    assert llm[0]["attrs"]["gen_ai.request.model"] == "groq openai/gpt-oss-120b"
    assert by["tool.machine_health"]["attrs"]["stf.tool"] == "machine_health"
    assert by["node.route"]["attrs"]["stf.mode"] == "twin"
    starts = [s["at"] for s in t["spans"]]
    assert starts == sorted(starts) and all(s["ms"] >= 0 for s in t["spans"])


def test_each_question_is_its_own_trace():
    a, b = ask(), ask("which part needs service first? again")
    assert a["trace"]["id"] != b["trace"]["id"]


def test_a_sessions_turn_keeps_its_trace():
    chat = groq_chat()
    chat.post_groq = lambda url, key, body: ANSWER
    r = req()
    r.scope["headers"].append((b"x-stf-user", b"guest_tracing_01"))
    out = asyncio.run(chat.ask(C.ChatRequest(question=Q, user="guest_tracing_01"), r))
    sid = out["session"]["id"]
    turn = chat.store.get(S.COL, "guest_tracing_01", sid)["turns"][-1]
    assert turn["trace"]["id"] == out["trace"]["id"]


def test_without_opentelemetry_there_is_no_trace(monkeypatch):
    monkeypatch.setattr(TR, "HAVE_OTEL", False)
    TR.reset(TR.Tracing())
    out = ask()
    assert "trace" not in out and out["answer"]


# ------------------------------------------------------------------ on the wire
class Receiver:
    """A local OTLP/HTTP endpoint: records each export's path, headers and decoded spans."""

    def __init__(self):
        self.got: list[tuple[str, dict, ExportTraceServiceRequest]] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                msg = ExportTraceServiceRequest()
                msg.ParseFromString(body)
                headers = {k.lower(): v for k, v in self.headers.items()}
                outer.got.append((self.path, headers, msg))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def spans(self):
        return [s for _, _, m in self.got for rs in m.resource_spans for ss in rs.scope_spans
                for s in ss.spans]

    def close(self):
        self.server.shutdown()


def attrs(span) -> dict:
    out = {}
    for kv in span.attributes:
        v = kv.value
        out[kv.key] = (v.string_value or v.int_value or v.bool_value
                       or list(x.string_value for x in v.array_value.values))
    return out


@pytest.fixture
def receiver():
    r = Receiver()
    yield r
    r.close()


def test_spans_reach_phoenix_with_both_vocabularies(receiver):
    TR.reset(TR.Tracing({"PHOENIX_COLLECTOR_ENDPOINT": receiver.url}))
    out = ask()
    TR.get().flush()
    assert out["trace"]["stores"] == ["phoenix"]
    assert {p for p, _, _ in receiver.got} == {"/v1/traces"}
    spans = receiver.spans()
    ids = {s.trace_id.hex() for s in spans}
    assert ids == {out["trace"]["id"]}  # one trace per question, the reply's id
    by = {s.name: attrs(s) for s in spans}
    root = by["copilot.question"]
    assert root["openinference.span.kind"] == "AGENT" and root["stf.mode"] == "twin"
    assert root["langfuse.user.id"] != "127.0.0.1" and len(root["langfuse.user.id"]) == 16
    llm = by["llm.groq"]
    assert llm["openinference.span.kind"] == "LLM" and llm["llm.token_count.prompt"] in (1200, 1500)
    assert by["tool.machine_health"]["openinference.span.kind"] == "TOOL"
    # no question or answer text without STF_TRACE_CONTENT
    for s in spans:
        for v in attrs(s).values():
            assert "service first" not in str(v) and "0.6 shifts" not in str(v)


def test_spans_reach_langfuse_with_basic_auth(receiver):
    env = {"LANGFUSE_PUBLIC_KEY": "pk-lf-1", "LANGFUSE_SECRET_KEY": "sk-lf-2",
           "LANGFUSE_HOST": receiver.url}
    TR.reset(TR.Tracing(env))
    ask()
    TR.get().flush()
    path, headers, _ = receiver.got[0]
    assert path == "/api/public/otel/v1/traces"
    assert headers["authorization"] == "Basic " + base64.b64encode(b"pk-lf-1:sk-lf-2").decode()
    names = {s.name for s in receiver.spans()}
    assert "copilot.question" in names and "llm.groq" in names


def test_content_is_exported_only_when_asked(receiver, monkeypatch):
    monkeypatch.setenv("STF_TRACE_CONTENT", "1")
    TR.reset(TR.Tracing({"PHOENIX_COLLECTOR_ENDPOINT": receiver.url}))
    ask()
    TR.get().flush()
    root = next(attrs(s) for s in receiver.spans() if s.name == "copilot.question")
    assert root["input.value"] == Q and "0.6 shifts" in root["output.value"]


def test_the_status_says_where_traces_go(receiver):
    TR.reset(TR.Tracing({"PHOENIX_COLLECTOR_ENDPOINT": receiver.url}))
    assert groq_chat().status()["tracing"] == {"stores": ["phoenix"], "content": False}
