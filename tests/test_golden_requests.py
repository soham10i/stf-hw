"""
Golden copilot requests: what each provider is sent, request by request, for one scripted
conversation - a tool call, an answer with a number nothing backs, the corrected answer.

The golden file was recorded on the five per-provider loops before they became one tool loop
(toolloop.py) and a verify node (agent.py); the refactor sends byte-identical requests, and any
later change to the protocol - the order of turns, how a tool result or a correction goes back -
shows up here as a reviewable diff. The system prompt and the tool declarations are replaced by
placeholders: they change for their own reasons and have their own tests.

Regenerate deliberately, never reflexively::

    python -m tests.test_golden_requests
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from services.api import chat as C  # noqa: E402
from services.api import security as sec  # noqa: E402

pytestmark = [pytest.mark.golden]

GOLDEN = Path(__file__).parent / "golden" / "copilot_requests.json"
BAD, GOOD = "The belt warns in 7.7 shifts.", "The belt warns in 0.6 shifts."
SCRIPT = [dict(call="machine_health"), dict(text=BAD), dict(text=GOOD)]
ARGS = {"parts": ["hbw_belt"]}


def completion(text=None, call=None):
    m = {"role": "assistant", "content": text or ""}
    if call:
        m["tool_calls"] = [{"id": "t1", "function": {"name": call, "arguments": json.dumps(ARGS)}}]
    return {"choices": [{"message": m}]}


def ollama(text=None, call=None):
    m = {"role": "assistant", "content": text or ""}
    if call:
        m["tool_calls"] = [{"function": {"name": call, "arguments": ARGS}}]
    return {"message": m}


def gemini(text=None, call=None):
    p = {"functionCall": {"name": call, "args": ARGS}} if call else {"text": text}
    return {"candidates": [{"content": {"role": "model", "parts": [p]}}]}


PROVIDERS = [
    ("gemini", dict(key="g"), "post", gemini),
    ("groq", dict(groq_key="g", groq_model="openai/gpt-oss-120b",
                  groq_models=["openai/gpt-oss-120b"]), "post_groq", completion),
    ("ollama", dict(ollama_model="qwen2.5:7b-instruct"), "post_ollama", ollama),
]


def _plain(body: dict) -> dict:
    """The body with the system prompt and the tool declarations as placeholders."""
    body = json.loads(json.dumps(body))
    if "systemInstruction" in body:
        body["systemInstruction"] = "<SYSTEM>"
    for m in body.get("messages", []):
        if m.get("role") == "system":
            m["content"] = "<SYSTEM>"
    if "tools" in body:
        body["tools"] = f"<{len(body['tools'])} tool groups>"
    return body


def record() -> dict:
    """Every provider's requests for the scripted conversation, and what it answered."""
    from .test_chat import req

    out = {}
    for prov, kw, attr, reply in PROVIDERS:
        settings = C.ChatSettings(**{"key": None, "model": "gemini-test", "daily_limit": 9, **kw})
        chat = C.Chat(sec.Settings.from_env(), settings)
        if prov != "ollama":
            chat.c.ollama_model = None
        chat._ollama_alive = lambda: True
        sent: list[dict] = []

        def fake(*a, sent=sent, reply=reply):
            sent.append(_plain(a[-1]))
            return reply(**SCRIPT[min(len(sent), len(SCRIPT)) - 1])

        setattr(chat, attr, fake)
        body = C.ChatRequest(question="which part needs service first?", provider=prov)
        r = asyncio.run(chat.ask(body, req()))
        out[prov] = {"requests": sent, "answer": r["answer"], "tools": r["tools"]}
    return out


@pytest.mark.parametrize("engine", ["graph", "linear"])
def test_every_provider_is_sent_the_recorded_requests(engine, monkeypatch):
    monkeypatch.setenv("STF_AGENT", engine)
    want = json.loads(GOLDEN.read_text())
    got = json.loads(json.dumps(record()))
    for prov in want:
        assert got[prov]["requests"] == want[prov]["requests"], prov
        assert got[prov]["answer"] == want[prov]["answer"] == GOOD, prov


if __name__ == "__main__":
    os.environ.setdefault("STF_DB", "sqlite")
    GOLDEN.write_text(json.dumps(record(), indent=1, sort_keys=True) + "\n")
    print(f"wrote {GOLDEN}")
