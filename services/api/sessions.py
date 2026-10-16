"""
Chat sessions and their context: what lets the conversation continue whichever model answers.

A session is one document in the store (store.py):

    {"id", "title", "created", "updated",
     "turns":   [{"role": "user" | "assistant", "text", "t",
                  ...answer metadata}],
     "context": {"facts": [[name, value, source], ...],   the established facts,
              newest last
                 "tools": [...], "models": [...], "page": ...}}

The CONTEXT STORE is `context.facts`: every tool result's facts, kept (deduplicated by name,
bounded) across the session. Any model that answers next - Gemini, another Gemini when the first
reaches its limit, the local model - gets the recent turns AND these facts, so a hand-over does not
lose what was already found, and a follow-up ("and the spindle?") still has the belt's numbers.
"""

from __future__ import annotations

import re
import time
import uuid

from .store import DocStore

COL = "sessions"
MAX_TURNS = 200
MAX_FACTS = 40
HISTORY_TURNS = 6
USER = re.compile(r"^[a-zA-Z0-9_-]{8,64}$")
SUMMARY = ("title", "created", "updated", "n_turns", "last_model")


def new_id() -> str:
    return uuid.uuid4().hex


def new(page: str | None) -> dict:
    now = time.time()
    ctx = {"facts": [], "tools": [], "models": [], "page": page}
    return {
        "id": new_id(),
        "title": "",
        "created": now,
        "updated": now,
        "n_turns": 0,
        "last_model": None,
        "turns": [],
        "context": ctx,
    }


def load(store: DocStore, user: str, sid: str | None, page: str | None) -> dict:
    """The session, or a new one when the id is missing or unknown to this user."""
    if sid:
        try:
            doc = store.get(COL, user, sid)
        except ValueError:
            doc = None
        if doc:
            return doc
    return new(page)


def remember(s: dict, results: list) -> None:
    """Keep the facts the tools returned in the session's context (the newest value wins)."""
    facts = s["context"]["facts"]
    for r in results:
        if r.tool not in s["context"]["tools"]:
            s["context"]["tools"].append(r.tool)
        if r.tool in ("search_docs", "page_guide"):
            continue  # passages, not facts: the documents can be searched again
        src = r.sources[0] if r.sources else r.tool
        for k, v in r.facts:
            facts[:] = [f for f in facts if f[0] != k]
            facts.append([k, str(v)[:300], src])
    del facts[:-MAX_FACTS]


def history(s: dict) -> list[dict]:
    """The recent turns for the model: the operator's words in full, the answers shortened."""
    out = []
    for t in s["turns"][-HISTORY_TURNS:]:
        text = t["text"][:1500] if t["role"] == "assistant" else t["text"]
        out.append({"role": t["role"], "text": text})
    return out


def context_text(s: dict) -> str:
    """The context store as text for any model: what this session already established."""
    facts = s["context"]["facts"]
    if not facts:
        return ""
    lines = [f"- {k}: {v} [{src}]" for k, v, src in facts[-25:]]
    head = "Established earlier in this session (still valid unless a tool says otherwise):\n"
    return head + "\n".join(lines)


def add_turn(s: dict, role: str, text: str, **meta) -> None:
    keep = {k: v for k, v in meta.items() if v}
    s["turns"].append({"role": role, "text": text, "t": time.time(), **keep})
    del s["turns"][:-MAX_TURNS]
    s["n_turns"] = len(s["turns"])
    s["updated"] = time.time()
    if role == "user" and not s["title"]:
        s["title"] = (text[:60] + "…") if len(text) > 60 else text
    if role == "assistant" and meta.get("model"):
        s["last_model"] = meta["model"]
        if meta["model"] not in s["context"]["models"]:
            s["context"]["models"].append(meta["model"])


def save(store: DocStore, user: str, s: dict) -> None:
    store.put(COL, user, s["id"], s)


def public(s: dict) -> dict:
    """The session as the browser sees it."""
    keys = ("id", "title", "created", "updated", "n_turns", "last_model", "turns", "context")
    return {k: s.get(k) for k in keys}
