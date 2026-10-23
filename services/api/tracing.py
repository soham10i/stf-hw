"""
Tracing: one OpenTelemetry trace per question - a span for each graph node, and inside them a
span for every model call, tool call and web search - kept in memory for the reply's own trace
(the thinking drawer) and exported over OTLP/HTTP to a trace store when one is configured.

    copilot.question                        the question: route, model, tokens, outcome
      node.prepare / node.route / ...       one per graph node (agent.py), both engines
        llm.<provider>                      one model request: model, input/output tokens
        tool.<name>                         one tool the model called
        search.<provider>                   one web search attempt down the ladder
        llm.quick                           a helper call: judge, rewriter, planner, critic

Where the spans go, each enabled by its settings:

  always                      memory: the question's spans, returned with the reply as
                              {"id", "spans"} and kept with the session's turn
  LANGFUSE_PUBLIC_KEY,        Langfuse (cloud or self-hosted), its OTLP endpoint
  LANGFUSE_SECRET_KEY         {LANGFUSE_HOST}/api/public/otel/v1/traces, HTTP basic auth;
                              LANGFUSE_HOST defaults to https://cloud.langfuse.com
  PHOENIX_COLLECTOR_ENDPOINT  Arize Phoenix, e.g. http://127.0.0.1:6006 ({endpoint}/v1/traces)
  OTEL_EXPORTER_OTLP_TRACES_ENDPOINT
                              any OTLP/HTTP collector (the standard OTel variables apply)

Each span carries both vocabularies, so either store reads it natively: the OpenTelemetry GenAI
conventions (gen_ai.*, read by Langfuse) and OpenInference (openinference.span.kind, llm.*,
read by Phoenix).

What leaves the process: by default only metadata - the route and its reasons, models, token
counts, timings, tool names, verdicts. The question and the answer are exported only with
STF_TRACE_CONTENT=1. The guest is never exported as an address: user ids are a salted hash
(STF_SESSION_SECRET). Without the opentelemetry packages everything here is a no-op and the
reply simply carries no trace.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import os
import threading
import time
from collections import OrderedDict

from .envcfg import dotenv
from .logging_config import get_logger

logger = get_logger(__name__)

try:
    from opentelemetry import trace as otel
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    HAVE_OTEL = True
except ImportError:  # pragma: no cover - the image installs it
    HAVE_OTEL = False
    SpanProcessor = object

MAX_TRACES = 256  # questions whose spans are held at once
MAX_SPANS = 400  # spans kept per question
# the attributes the drawer shows (the rest go to the trace store only)
SHOWN = (
    "stf.provider", "gen_ai.request.model", "gen_ai.usage.input_tokens",
    "gen_ai.usage.output_tokens", "stf.tool", "stf.found", "stf.sources", "stf.verdict",
    "stf.kept", "stf.unverified", "stf.corrected", "stf.mode", "stf.sub", "stf.error",
)
KIND = {"llm": "LLM", "tool": "TOOL", "search": "RETRIEVER", "node": "CHAIN", "copilot": "AGENT"}


def content_allowed() -> bool:
    return os.environ.get("STF_TRACE_CONTENT", "").lower() in ("1", "true", "yes")


def user_id(guest: str | None) -> str | None:
    """A guest as the trace store sees it: a salted hash, never the address itself."""
    if not guest:
        return None
    salt = os.environ.get("STF_SESSION_SECRET", "stf")
    return hashlib.sha256(f"{salt}:{guest}".encode()).hexdigest()[:16]


class Collector(SpanProcessor):
    """Holds each question's finished spans until its reply is built (snapshot); a question's
    entry goes when its root span ends."""

    def __init__(self) -> None:
        self._by: OrderedDict[int, list] = OrderedDict()
        self._lock = threading.Lock()

    def on_start(self, span, parent_context=None) -> None:
        pass

    def on_end(self, span) -> None:
        tid = span.context.trace_id
        with self._lock:
            if span.parent is None:  # the question is over
                self._by.pop(tid, None)
                return
            spans = self._by.setdefault(tid, [])
            self._by.move_to_end(tid)
            if len(spans) < MAX_SPANS:
                spans.append(span)
            while len(self._by) > MAX_TRACES:
                self._by.popitem(last=False)

    def spans(self, tid: int) -> list:
        with self._lock:
            return list(self._by.get(tid, []))

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


def exporters(env: dict | None = None) -> list[tuple[str, object]]:
    """The configured trace stores as (name, OTLP exporter) pairs."""
    if not HAVE_OTEL:
        return []
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    env = env if env is not None else {**dotenv(), **os.environ}
    out: list[tuple[str, object]] = []
    pk, sk = env.get("LANGFUSE_PUBLIC_KEY"), env.get("LANGFUSE_SECRET_KEY")
    if pk and sk:
        host = (env.get("LANGFUSE_HOST") or "https://cloud.langfuse.com").rstrip("/")
        auth = base64.b64encode(f"{pk}:{sk}".encode()).decode()
        out.append(("langfuse", OTLPSpanExporter(
            endpoint=f"{host}/api/public/otel/v1/traces",
            headers={"Authorization": f"Basic {auth}"},
        )))
    phoenix = env.get("PHOENIX_COLLECTOR_ENDPOINT")
    if phoenix:
        out.append(("phoenix", OTLPSpanExporter(endpoint=f"{phoenix.rstrip('/')}/v1/traces")))
    otlp = env.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if otlp:  # its headers, timeout and so on: the standard OTEL_EXPORTER_OTLP_* variables
        out.append(("otlp", OTLPSpanExporter(endpoint=otlp)))
    return out


class Tracing:
    """The process's tracer: the collector always, the trace stores when configured."""

    def __init__(self, env: dict | None = None, extra=()) -> None:
        self.collector = Collector()
        self.stores: list[str] = []
        self.tracer = None
        if not HAVE_OTEL:
            return
        provider = TracerProvider(
            resource=Resource.create({"service.name": "stf-copilot", "service.version": "4.0.0"})
        )
        provider.add_span_processor(self.collector)
        for name, exporter in exporters(env):
            provider.add_span_processor(BatchSpanProcessor(exporter))
            self.stores.append(name)
        for processor in extra:  # tests: an in-memory exporter
            provider.add_span_processor(processor)
        self.provider = provider
        # a tracer of our own provider: the global one stays free for the application's use
        self.tracer = provider.get_tracer("stf.copilot")
        if self.stores:
            logger.info("copilot traces export to: %s", ", ".join(self.stores))

    def flush(self) -> None:
        if self.tracer is not None:
            self.provider.force_flush(5000)


_T: Tracing | None = None
_LOCK = threading.Lock()


def get() -> Tracing:
    global _T
    with _LOCK:
        if _T is None:
            _T = Tracing()
        return _T


def reset(t: Tracing | None = None) -> None:
    """Replace the process's tracer (tests; a settings change)."""
    global _T
    with _LOCK:
        _T = t


def _kind(name: str) -> str:
    return KIND.get(name.split(".", 1)[0], "CHAIN")


@contextlib.contextmanager
def span(name: str, **attrs):
    """A child span of whatever span is current (a no-op without OpenTelemetry). Yields the
    span, or None; set attributes with `put(span, ...)`."""
    t = get()
    if t.tracer is None:
        yield None
        return
    with t.tracer.start_as_current_span(name) as s:
        s.set_attribute("openinference.span.kind", _kind(name))
        put(s, **attrs)
        try:
            yield s
        except Exception as e:
            s.set_attribute("stf.error", type(e).__name__)
            raise


def put(s, **attrs) -> None:
    """Attributes onto a span; None values are left out, lists of strings kept as lists."""
    if s is None:
        return
    for k, v in attrs.items():
        if v is None:
            continue
        key = k.replace("__", ".")
        if isinstance(v, (bool, int, float, str)):
            s.set_attribute(key, v)
        elif isinstance(v, (list, tuple)) and all(isinstance(x, str) for x in v):
            s.set_attribute(key, list(v))
        else:
            s.set_attribute(key, str(v))


def usage(data: dict) -> tuple[int | None, int | None]:
    """(input, output) tokens of a response in any of the three shapes."""
    if not isinstance(data, dict):
        return None, None
    u = data.get("usageMetadata")
    if u:  # Gemini
        return u.get("promptTokenCount"), u.get("candidatesTokenCount")
    u = data.get("usage")
    if u:  # OpenAI-compatible
        return u.get("prompt_tokens"), u.get("completion_tokens")
    if "eval_count" in data or "prompt_eval_count" in data:  # Ollama
        return data.get("prompt_eval_count"), data.get("eval_count")
    return None, None


def model_call(s, provider: str, model: str | None, data: dict) -> None:
    """A model request's span: the provider, the model, its tokens - in both vocabularies."""
    if s is None:
        return
    i, o = usage(data)
    put(
        s, stf__provider=provider, gen_ai__system=provider, gen_ai__request__model=model,
        llm__model_name=model, gen_ai__usage__input_tokens=i, gen_ai__usage__output_tokens=o,
        llm__token_count__prompt=i, llm__token_count__completion=o,
        langfuse__observation__type="generation",
    )


def here(**attrs) -> None:
    """Attributes onto the current span (the node a graph step runs in)."""
    if get().tracer is not None:
        put(otel.get_current_span(), **attrs)


def trace_id(s) -> str | None:
    return format(s.get_span_context().trace_id, "032x") if s is not None else None


def snapshot(root, now_ns: int | None = None) -> dict | None:
    """The question's trace for the reply: its id and the spans finished so far, as offsets
    and durations in ms from the question's start, each with its depth under the question and
    the attributes the drawer shows."""
    if root is None:
        return None
    t = get()
    ctx = root.get_span_context()
    spans = t.collector.spans(ctx.trace_id)
    start = root.start_time
    parent = {s.context.span_id: (s.parent.span_id if s.parent else None) for s in spans}
    root_id = ctx.span_id

    def depth(sid: int) -> int:
        d, p = 1, parent.get(sid)
        while p is not None and p != root_id and d < 12:
            d, p = d + 1, parent.get(p)
        return d

    rows = []
    for s in sorted(spans, key=lambda s: s.start_time):
        attrs = {k: v for k, v in (s.attributes or {}).items() if k in SHOWN}
        rows.append({
            "name": s.name,
            "at": round((s.start_time - start) / 1e6, 1),
            "ms": round((s.end_time - s.start_time) / 1e6, 1),
            "depth": depth(s.context.span_id),
            **({"attrs": attrs} if attrs else {}),
        })
    total = ((now_ns or time.time_ns()) - start) / 1e6
    return {"id": trace_id(root), "ms": round(total, 1), "stores": list(t.stores), "spans": rows}
