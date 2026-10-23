"""
The copilot as a graph: one question's work as nodes, the choices between them as edges anyone
can read. LangGraph runs it (STF_AGENT=graph, the default when langgraph is installed); the same
nodes and edges also run as a plain loop (STF_AGENT=linear, or without langgraph), so the graph is
an engine choice, never a second implementation.

    prepare ──cached──▶ END
       │
     route ──no model──▶ tools_only ──▶ respond ──▶ END
       │ web/deep                ▲          ▲
       ├──────────▶ web ─────────┼─answered─┤
       ▼                         │          │
     answer ──every model busy───┘          │
       │  ▲                                 │
       ▼  │ an unbacked number, once        │
     verify ────────────────────────────────┘

  prepare     the session (its turns and remembered facts), the rules router's tool calls, the
              answer cache for a repeated question
  route       orchestrate.decide (rules, never a model) picks chat / twin / docs / web / deep; the
              question's style (respond.py) and depth (depth.py); the provider ladder
  web         the web search ladder (WEB_SEARCH_ORDER) and, when thorough, the literature; a web
              question's search answer can be the reply itself
  answer      the model ladder (Gemini lanes, Groq, UPB, an open model, Ollama): each provider
              runs the one tool loop (toolloop.py); a failure hands over to the next
  verify      the number check (verify.py): an answer with a number nothing backs goes back to
              the model that wrote it, once; then it stands, flagged
  tools_only  the twin's tools answer: no model is configured, or none answered in time
  respond     the payload (policy-vetted links, cites, steps, usage), the session and the cache

Two kinds of data flow through it. The graph STATE is what the edges decide on and what a
checkpoint would keep: the route and the outcome. The QUESTION (runtime context) is the
working memory of one request - the HTTP request, the emit hook of the stream, the tool results
the model loops append to - and is never checkpointed. Nothing in this module calls a model
directly: every step is a method of chat.Chat or a module it already uses.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, TypedDict

from fastapi import HTTPException, Request

from . import chat as C
from . import depth as D
from . import orchestrate as O
from . import respond as R
from . import scholar as SCH
from . import sessions as S
from . import source_policy as SP
from . import token_budget as TB
from . import tools as T
from . import verify as V
from . import websearch as W
from .logging_config import get_logger

logger = get_logger(__name__)

END = "__end__"  # langgraph.graph.END, without importing langgraph

try:  # the graph engine is optional: without it the same nodes run as a loop
    from langgraph.graph import END as _END
    from langgraph.graph import START, StateGraph
    from langgraph.runtime import Runtime

    assert _END == END
    HAVE_LANGGRAPH = True
except ImportError:  # pragma: no cover - the image installs it
    HAVE_LANGGRAPH = False


class State(TypedDict, total=False):
    """What the edges decide on, and what a checkpoint would keep."""

    mode: str  # the route: chat, twin, docs, web, deep
    web: bool  # the route searches the web
    rules: bool  # the twin's tools answer (no model, or none answered)
    why: str | None  # why the tools answer
    retry: bool  # verify sent the answer back to its model once
    outcome: dict  # {answer, model, note, bad}: what respond turns into the payload
    out: dict  # the payload (a cache hit sets it at once)


@dataclass
class Question:
    """One request's working memory: the runtime context every node reads and appends to."""

    chat: Any  # chat.Chat
    req: Any  # chat.ChatRequest
    request: Request
    emit: Any
    client: str
    started: float = field(default_factory=time.monotonic)
    usage: dict = field(default_factory=dict)
    level: str = "vetted"
    removed: int = 0
    steps: list[str] = field(default_factory=list)
    thinking: list[str] = field(default_factory=list)
    switched: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    web_pages: list[str] = field(default_factory=list)
    user: str | None = None
    guest: str = ""
    session: dict | None = None
    memory: str = ""
    ctx: Any = None
    rules_text: str = ""
    results: list = field(default_factory=list)
    called: list[str] = field(default_factory=list)
    cache_key: tuple = ()
    plan: Any = None
    style: str = ""
    dp: Any = None
    extra: str = ""
    chain: list[str] = field(default_factory=list)
    found: Any = None
    convo: Any = None  # the conversation that answered (toolloop.Conversation)
    prov: str = ""  # its provider

    def say(self, kind: str, text: str) -> None:
        """Record a progress step and forward it to the client's emit hook."""
        if kind == "step":
            self.steps.append(text)
        if self.emit:
            self.emit(kind, text)

    def evidence(self) -> str:
        """What the answer may draw numbers from: the context, the session's remembered facts,
        every tool result so far, the web pages read, and the operator's own words (never the
        model's earlier answers)."""
        req = self.req
        mine = " ".join(t.text for t in req.history if t.role == "user")
        dumps = " ".join(json.dumps(r.as_dict(), ensure_ascii=False) for r in self.results)
        pages = " ".join(self.web_pages)
        block = C.context_block(req.grounding, req.page, self.results)
        return f"{block} {self.memory} {dumps} {pages} {mine}"

    def check(self, answer: str) -> list[str]:
        """Claims in the answer the evidence does not support (verify.py)."""
        return V.unverified(answer, self.evidence(), self.req.question)


# ---------------------------------------------------------------------------------- the nodes
async def prepare(state: State, q: Question) -> State:
    """The session, the rules router's tool calls, and the cache for a repeated question."""
    chat, req, request = q.chat, q.req, q.request
    user = request.headers.get("x-stf-user") or req.user
    q.user = user if user and S.USER.match(user) else None
    q.guest = q.user or q.client  # whose share of the Gemini token budget the question counts on
    q.session = S.load(chat.store, q.user, req.session_id, req.page) if q.user else None
    q.memory = S.context_text(q.session, req.question) if q.session else ""
    if q.session and not req.history:
        req.history = [C.Turn(role=t["role"], text=t["text"]) for t in S.history(q.session)]

    q.ctx = T.Ctx(age=req.age, pm=req.pm, page=req.page, client=q.client)
    # every Gemini model is cooling down: give small local models the lean retrieval
    lean = chat.has_gemini and not any(ln.pool.available() for ln in chat.lanes)
    q.rules_text, q.results = T.rules_answer(req.question, q.ctx, lean=lean)
    q.called = [r.tool for r in q.results]
    # identical session-less questions (a double-ask, a voice echo) reuse the answer for
    # cache_ttl_s; never cached when live_state answered (the twin may have moved on). Keyed by
    # the guest and by everything the client supplied (grounding, history): one visitor's
    # crafted context must never become another visitor's cached answer
    supplied = json.dumps(
        [req.grounding.model_dump(), [t.model_dump() for t in req.history]], sort_keys=True
    )
    q.cache_key = (
        q.user or q.client, req.question, req.page, req.provider, req.mode, req.age, req.pm,
        req.depth, req.audience, q.level, hashlib.sha256(supplied.encode()).hexdigest(),
    )
    if q.session is None and "live_state" not in q.called:
        hit = chat.cache.get(q.cache_key)
        if hit and time.time() - hit[0] < chat.cache_ttl_s:
            logger.info("Chat cache hit for question: %r", req.question[:60])
            return {"out": hit[1]}
    return {}


async def route(state: State, q: Question) -> State:
    """The route (rules, not a model), the answer's style and depth, and the provider ladder."""
    chat, req = q.chat, q.req
    q.plan = plan = O.decide(
        req.question, q.called, req.mode, can_search=bool(chat.c.groq_key or chat.has_gemini)
    )
    if q.emit:
        q.emit("route", json.dumps(plan.as_dict()))
    for r in q.results:
        if r.tool == "search_docs":
            best = max((c.get("score", 0) for c in r.cites), default=0)
            n = len(r.cites)
            q.say("step", f"searched the documents: {n} passages (best match {best:.1f})")
        else:
            q.say("step", f"computed {r.tool.replace('_', ' ')}")
    q.style = R.classify(req.question, q.called)
    if plan.mode in ("web", "deep") and q.style not in ("derive", "greeting"):
        q.style = "research"
    if q.style in ("derive", "explain", "research") and plan.mode != "chat":
        # an explanation needs the passages that hold the equations: more of them, whole
        more = T.call("search_docs", {"query": req.question, "k": 6}, q.ctx)
        if q.style == "derive":
            more = T.equations(more)
        q.results = [r for r in q.results if r.tool != "search_docs"] + [more]
        q.called = [r.tool for r in q.results]
    q.dp = dp = D.pick(req.depth, plan.mode, q.style)
    q.say("step", f"depth: {dp.name} (answers up to {dp.answer_tokens} tokens; sources {q.level})")
    q.extra = "\n\n".join(
        x for x in (q.memory, R.instruction(q.style), D.instruction(dp, req.audience)) if x
    )
    q.chain = chat._provider(req.provider)
    if not q.chain:
        why = None if req.provider == "rules" else (
            "No model is configured; answered from the twin's tools."
        )
        return {"mode": plan.mode, "web": plan.web, "rules": True, "why": why}
    if not chat.cap.take():
        raise HTTPException(status_code=429, detail="today's question budget is used up")
    return {"mode": plan.mode, "web": plan.web}


async def web(state: State, q: Question) -> State:
    """The web, in the operator's order (WEB_SEARCH_ORDER, default gemini, groq, ddg): Gemini's
    Google Search on a token budget that shrinks the search as it is used, Groq's browser search,
    and DuckDuckGo (keyless; a configured model writes the fetched pages up). Each one that fails
    or cannot be afforded hands the question to the next. Deep research searches each
    sub-question, and the chosen model then writes the findings up."""
    chat, req, plan, dp, level = q.chat, q.req, q.plan, q.dp, q.level
    context = C.context_block(req.grounding, req.page, q.results)
    found: W.Found | None = None
    for name in chat.c.search_order:
        if name == "gemini" and chat.has_gemini:
            found = await chat._web_gemini(
                req, plan.mode, context, q.guest, q.say, q.notes, dp, level
            )
        elif name == "groq" and chat.c.groq_key:
            found = await chat._web_groq(req, plan.mode, context, q.say, q.notes, dp, level)
        elif name == "ddg":
            found = await chat._web_ddg(req, plan.mode, context, q.say, q.notes, dp, level)
        if found:
            break
    if found:
        found, n = SP.clean(found, level)
        q.removed += n
        if n:
            pl = "s" if n > 1 else ""
            q.say("step", f"left out {n} page{pl} the source policy does not allow")
    # a thorough answer reads the peer-reviewed literature too (OpenAlex): its abstracts join the
    # findings, or stand in for them when every web search failed
    if dp.scholar:
        lit = await asyncio.to_thread(SCH.found, req.question, dp.scholar)
        if lit:
            if found:
                found.text += "\n\n" + lit.text
                found.sources = found.sources + lit.sources
                found.pages += " " + lit.pages
                found.steps += lit.steps
            else:
                found = lit
                q.notes.append("the web searches failed; the peer-reviewed literature answered")
        else:
            q.say("step", "the peer-reviewed literature search returned nothing")
    q.found = found
    if found:
        for t in found.steps:
            q.say("step", t)
        for t in found.reasoning:
            q.thinking.append(t)
            q.say("thinking", t)
        q.web_pages.append(found.pages)
        # first, so its pages lead the sources
        q.results.insert(
            0, C.web_result("web_research" if plan.mode == "deep" else "web_search", found)
        )
        q.called.append(q.results[0].tool)
        # a web search's own answer is the reply - unless the literature joined it (a thorough
        # answer), when a model writes both up together
        if plan.mode == "web" and found.via != "openalex" and not dp.scholar:
            bad = q.check(found.text)
            note = None
            if bad:
                note = (
                    f"Not found in the pages read: {', '.join(bad)} - check these before "
                    "relying on them."
                )
            label = {
                "gemini": f"{found.model} + Google Search",
                "duckduckgo": f"duckduckgo + {found.model}",
            }.get(found.via, f"groq {found.model} + web search")
            return {"outcome": {"answer": found.text, "model": label, "note": note, "bad": bad}}
        q.extra += "\n\n" + R.instruction("research")
    elif chat.has_gemini and chat.search_ready(q.guest):
        q.say("step", "searching the web with Gemini's Google Search")
    return {}


WHO = {"gemini": "Gemini", "groq": "Groq", "upb": "UPB AI", "ollama": "the local model"}
NEXT_NAME = {
    "groq": "Groq", "upb": "UPB AI", "gemini": "Gemini", "openai": "the open model",
    "ollama": "local model",
}


async def answer(state: State, q: Question) -> State:
    """The chosen kind first, the other next (each model in turn), then the tools: a limit hands
    the question - with the session's context - to the next, never an error. The whole hand-over
    is bounded: past DEADLINE_S the tools answer. Each provider runs the one tool loop
    (toolloop.py); its answer goes to verify. Sent back by verify, the same conversation goes on
    with the correction."""
    chat, req, plan, dp = q.chat, q.req, q.plan, q.dp
    if state.get("retry"):
        try:
            await asyncio.to_thread(q.convo.run)
        except C.ModelError as e:  # the first answer stands, flagged by verify
            q.convo.final = True
            q.notes.append(f"the correction failed ({e})")
            q.say("step", f"the correction failed: {e}")
        return {"retry": False}
    t0 = time.monotonic()
    for i, prov in enumerate(q.chain):
        if time.monotonic() - t0 > C.DEADLINE_S:
            q.notes.append(f"no model answered within {C.DEADLINE_S:.0f} s")
            break
        if prov == "ollama" and not await asyncio.to_thread(chat._ollama_alive):
            q.notes.append("the local model is not running")
            q.switched.append({"from": "local model", "to": "next", "why": "not running"})
            continue
        deep = plan.mode == "deep" or q.style == "derive"
        meta: dict = {
            "max_tokens": dp.answer_tokens,
            "gemini_tokens": dp.gemini_tokens,
            "extra": q.extra,
            "emit": q.say,
            "thinking": q.thinking,
            "web": plan.web and q.found is None and prov == "gemini" and chat.search_ready(q.guest),
            "guest": q.guest,
            "effort": "medium" if deep else dp.effort,
            "long": deep or q.style == "research",
            "deadline": t0 + C.DEADLINE_S,
        }
        try:
            convo = chat.conversation(prov, req, q.ctx, q.results, q.called, meta)
            await asyncio.to_thread(convo.run)
        except C.ModelError as e:
            logger.warning(
                "LLM provider '%s' failed for question %r: %s", prov, req.question[:60], e
            )
            if e.cool:
                chat.out[prov] = time.time() + e.cool
            who = WHO.get(prov) or f"the open model ({chat.c.openai_model})"
            q.notes.append(f"{who} unavailable ({e})")
            q.say("step", f"{who} unavailable: {e}")
            for m, why in meta.get("skipped", []):
                q.switched.append({"from": m, "to": "next", "why": why})
            if i + 1 < len(q.chain):
                nxt = NEXT_NAME.get(q.chain[i + 1], "next")
                q.switched.append({"from": who, "to": nxt, "why": str(e)})
            continue
        q.convo, q.prov = convo, prov
        return {"retry": False}
    why = (
        "Every model is busy (" + "; ".join(q.notes)
        + "); answered from the twin's tools and documents."
    )
    return {"rules": True, "why": why}


async def verify(state: State, q: Question) -> State:
    """The number check (verify.py): every number in the answer must be in the evidence. The
    first time one is not, the answer goes back to the model that wrote it, once
    (Conversation.correct); after that it stands, flagged as unverified."""
    chat, convo, prov = q.chat, q.convo, q.prov
    bad = q.check(convo.text)
    if bad and convo.correct(bad):
        return {"retry": True}
    meta = convo.meta
    chat.out.pop(prov, None)
    for m, why in meta.get("skipped", []):
        q.switched.append({"from": m, "to": meta.get("model"), "why": why})
    if meta.get("web_sources"):  # Gemini's Google Search grounding
        g, n = SP.clean(W.Found("", meta["web_sources"], model="gemini"), q.level)
        q.removed += n
        q.results.append(C.web_result("web_search", g))
        q.called.append("web_search")
    if prov == "gemini":
        model = meta.get("model") or chat.c.model
    elif prov == "groq":
        model = meta.get("model") or f"groq {chat.c.groq_model}"
    elif prov == "openai":
        model = chat.c.openai_model
    elif prov == "upb":
        model = meta.get("model") or f"upb {chat.c.upb_model}"
    else:
        model = chat.c.ollama_model or "ollama"
    warn = [n for n in q.notes if "web search failed" in n][-1:]
    warn += [n for n in q.notes if n.startswith("the correction failed")][-1:]
    if bad:
        warn.append(
            f"Not backed by the twin's data: {', '.join(bad)} - "
            "check these before relying on them"
        )
    note = "; ".join(warn) + "." if warn else None
    return {"outcome": {"answer": C.tidy(convo.text), "model": model, "note": note, "bad": bad}}


async def tools_only(state: State, q: Question) -> State:
    """The twin's tools answer, in the rules mode's words: never an error page."""
    text = C.fallback(q.rules_text, q.results, q.style)
    return {"outcome": {"answer": text, "model": "rules", "note": state.get("why"), "bad": None}}


async def respond(state: State, q: Question) -> State:
    """The response payload: answer with policy-vetted links, cites, status, meter; the session
    turn and the cache entry."""
    chat, req, o = q.chat, q.req, state["outcome"]
    # a model may still link a page the policy does not allow: the link goes
    text, gone = SP.strip_links(o["answer"], q.level)
    q.removed += len(gone)
    model, note, bad = o["model"], o.get("note"), o.get("bad")
    sources, links = C._cite(q.results)
    out = {
        "answer": text,
        "model": model,
        "sources": sources,
        "links": links,
        "tools": q.called,
        "style": q.style,
        "facts": [
            f for r in q.results if r.tool not in ("search_docs", *C.WEB_TOOLS) for f in r.facts
        ][:8],
        "cites": C._cites(q.results),
        "route": q.plan.as_dict(),
        "steps": q.steps,
        "ms": round(1000 * (time.monotonic() - q.started)),
        "usage": {
            **q.usage,
            "depth": q.dp.name,
            "audience": req.audience,
            "sources": q.level,
            "removed": q.removed,
        },
    }
    if q.thinking:
        out["thinking"] = "\n\n".join(q.thinking)[: C.MAX_THINKING]
    if note:
        out["note"] = note
    if bad:
        out["unverified"] = bad
    if q.switched:
        out["switched"] = q.switched
    session = q.session
    if session is not None:
        S.add_turn(session, "user", req.question)
        S.add_turn(
            session,
            "assistant",
            text,
            model=model,
            style=q.style,
            sources=sources,
            cites=out["cites"],
            links=links,
            tools=q.called,
            note=note,
            unverified=bad,
            switched=q.switched,
            route=out["route"],
            steps=q.steps,
            thinking=out.get("thinking"),
            ms=out["ms"],
            usage=out["usage"],
        )
        S.remember(session, q.results)
        S.save(chat.store, q.user, session)
        out["session"] = {
            "id": session["id"],
            "title": session["title"],
            "facts": len(session["context"]["facts"]),
            "models": session["context"]["models"],
        }
    elif "live_state" not in q.called:
        if len(chat.cache) >= 64:
            for old in sorted(chat.cache, key=lambda k: chat.cache[k][0])[:32]:
                chat.cache.pop(old, None)
        chat.cache[q.cache_key] = (time.time(), out)
    logger.info("Chat replied: model=%s, elapsed=%dms, tools=%s", model, out["ms"], q.called)
    return {"out": out}


NODES = {
    "prepare": prepare,
    "route": route,
    "web": web,
    "answer": answer,
    "verify": verify,
    "tools_only": tools_only,
    "respond": respond,
}


# ---------------------------------------------------------------------------------- the edges
def after_prepare(s: State) -> str:
    return END if "out" in s else "route"


def after_route(s: State) -> str:
    return "tools_only" if s.get("rules") else ("web" if s.get("web") else "answer")


def after_web(s: State) -> str:
    return "respond" if "outcome" in s else "answer"


def after_answer(s: State) -> str:
    return "tools_only" if s.get("rules") else "verify"


def after_verify(s: State) -> str:
    return "answer" if s.get("retry") else "respond"


# each node's edge: a function of the state (with every place it can lead), or one fixed node
EDGES: dict[str, tuple] = {
    "prepare": (after_prepare, ["route", END]),
    "route": (after_route, ["tools_only", "web", "answer"]),
    "web": (after_web, ["respond", "answer"]),
    "answer": (after_answer, ["tools_only", "verify"]),
    "verify": (after_verify, ["answer", "respond"]),
    "tools_only": ("respond",),
    "respond": (END,),
}


# ---------------------------------------------------------------------------------- the engines
def engine() -> str:
    """Which engine runs the nodes: graph (LangGraph) unless STF_AGENT=linear or it is missing."""
    want = os.environ.get("STF_AGENT", "graph").strip().lower()
    return "graph" if want != "linear" and HAVE_LANGGRAPH else "linear"


MAX_STEPS = 12  # the longest path is 8 (verify -> answer once); also LangGraph's recursion limit


async def run_linear(q: Question) -> dict:
    """The nodes in a plain loop, following the same edges: the graph without its engine."""
    state: State = {}
    node = "prepare"
    for _ in range(MAX_STEPS):
        if node == END:
            break
        state.update(await NODES[node](state, q) or {})
        edge = EDGES[node][0]
        node = edge(state) if callable(edge) else edge
    return state["out"]


_GRAPH = None


def graph():
    """The compiled LangGraph (built once). The question rides as runtime context."""
    global _GRAPH
    if _GRAPH is None:
        g = StateGraph(State, context_schema=Question)

        def bind(fn):
            async def node(state: State, runtime: Runtime[Question]) -> State:
                return await fn(state, runtime.context)

            node.__name__ = fn.__name__
            return node

        for name, fn in NODES.items():
            g.add_node(name, bind(fn))
        g.add_edge(START, "prepare")
        for name, edge in EDGES.items():
            if callable(edge[0]):
                g.add_conditional_edges(name, edge[0], edge[1])
            else:
                g.add_edge(name, edge[0])
        _GRAPH = g.compile()
    return _GRAPH


async def run(q: Question) -> dict:
    """Answer one question on the configured engine."""
    if engine() == "graph":
        state = await graph().ainvoke({}, context=q, config={"recursion_limit": MAX_STEPS})
        return state["out"]
    return await run_linear(q)


def mermaid() -> str:
    """The graph as a Mermaid diagram (GET /chat/graph): what runs, drawn from what runs."""
    if HAVE_LANGGRAPH:
        return graph().get_graph().draw_mermaid()
    lines = ["graph TD;", "  __start__ --> prepare;"]
    for name, edge in EDGES.items():
        for to in edge[1] if callable(edge[0]) else edge:
            arrow = "-.->" if callable(edge[0]) else "-->"
            lines.append(f"  {name} {arrow} {to};")
    return "\n".join(lines)


def start(chat, req, request: Request, emit, client: str) -> Question:
    """A question's working memory, with its token meter started."""
    return Question(
        chat=chat, req=req, request=request, emit=emit, client=client,
        usage=TB.meter_start(), level=req.sources or "vetted",
    )
