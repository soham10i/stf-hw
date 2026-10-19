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

from .grounding import tokenize
from .logging_config import get_logger
from .store import DocStore

logger = get_logger(__name__)

COL = "sessions"
MAX_TURNS = 200
MAX_FACTS = 40
HISTORY_TURNS = 6
USER = re.compile(r"^[a-zA-Z0-9_-]{8,64}$")
SUMMARY = ("title", "created", "updated", "n_turns", "last_model")


def new_id() -> str:
    """Generate a random 32-character hexadecimal session identifier."""
    return uuid.uuid4().hex


def new(page: str | None) -> dict:
    """Initialize a fresh conversation session record.

    Args:
        page: Optional identifier of the active frontend dashboard page.

    Returns:
        dict: New session record dictionary.
    """
    now = time.time()
    sid = new_id()
    logger.debug("Initialized new chat session %s (page=%s)", sid, page)
    ctx = {"facts": [], "tools": [], "models": [], "page": page}
    return {
        "id": sid,
        "title": "",
        "created": now,
        "updated": now,
        "n_turns": 0,
        "last_model": None,
        "turns": [],
        "context": ctx,
    }


def load(store: DocStore, user: str, sid: str | None, page: str | None) -> dict:
    """Retrieve an existing session or initialize a fresh one if missing or inaccessible.

    Args:
        store: Document repository holding persistent session documents.
        user: Authenticated user or guest identifier.
        sid: Optional session identifier to look up.
        page: Active frontend page identifier.

    Returns:
        dict: Existing or newly initialized session dictionary.
    """
    if sid:
        try:
            doc = store.get(COL, user, sid)
            if doc:
                logger.debug("Loaded existing session %s for user %s", sid, user)
                return doc
        except ValueError:
            logger.debug("Session %s not found for user %s; starting new session", sid, user)
        except Exception as e:
            logger.warning("Error reading session %s for user %s (%s); creating new session", sid, user, e)
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
            facts.append([k, str(v)[:200], src])
    del facts[:-MAX_FACTS]


def history(s: dict) -> list[dict]:
    """The recent turns for the model: the operator's words in full, the answers shortened."""
    out = []
    for t in s["turns"][-HISTORY_TURNS:]:
        text = t["text"][:1500] if t["role"] == "assistant" else t["text"]
        out.append({"role": t["role"], "text": text})
    return out


def _rank_facts(facts: list[list[str]], question: str, limit: int) -> list[list[str]]:
    """The facts that best overlap the question's words (token overlap of name + value), then
    the newest ones, kept in their original order."""
    qt = set(tokenize(question))
    if not qt:
        return facts[-limit:]
    scored = [(len(qt & set(tokenize(f"{f[0]} {f[1]}"))), i) for i, f in enumerate(facts)]
    picked = sorted(scored, key=lambda x: (-x[0], x[1]))[:limit]
    return [facts[i] for _, i in sorted(picked, key=lambda x: x[1])]


def context_text(s: dict, question: str = "") -> str:
    """The context store as text for any model: what this session already established. When the
    question is given and the store has grown, the facts that overlap the question come first
    and the rest is trimmed, so a hand-over to another model stays short and on-point."""
    facts = s["context"]["facts"]
    if not facts:
        return ""
    if question and len(facts) > 12:
        head = _rank_facts(facts, question, 10)
        tail = [f for f in facts if f not in head][-4:]
        facts = head + [f for f in tail if f not in head]

    def cell(x: object) -> str:
        return str(x).replace("|", "\\|").replace("\n", " ")

    rows = [f"| {cell(k)} | {cell(v)} | [{cell(src)}] |" for k, v, src in facts[-14:]]
    head = [
        "## Established earlier in this session",
        "",
        "Still valid unless a tool says otherwise.",
        "",
        "| Fact | Value | Source |",
        "|---|---|---|",
    ]
    return "\n".join(head + rows)


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
    """Persist session record to the underlying document store.

    Args:
        store: Document repository instance.
        user: Authenticated or guest user identifier.
        s: Session dictionary to save.
    """
    try:
        store.put(COL, user, s["id"], s)
        logger.debug("Saved session %s for user %s (%d turns)", s.get("id"), user, s.get("n_turns", 0))
    except Exception as e:
        logger.error("Failed to save session %s for user %s: %s", s.get("id"), user, e, exc_info=True)
        raise


def public(s: dict) -> dict:
    """The session as the browser sees it."""
    keys = ("id", "title", "created", "updated", "n_turns", "last_model", "turns", "context")
    # what the next model is given from this session, as it is given (Markdown)
    return {**{k: s.get(k) for k in keys}, "memory": context_text(s)}
