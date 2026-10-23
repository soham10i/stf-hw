"""
The tool loop, once for every provider: the model answers or asks for tools, the tools run here,
their results go back, until it answers or the rounds run out.

Each provider's API says the same few things in its own words - a request body, a tool call, a
tool result, its thinking, a correction - so a provider is an Adapter of a handful of small
methods, and the loop itself is written once:

    Gemini        generateContent: functionCall / functionResponse parts, thought summaries,
                  Google Search grounding on web questions (both lanes: Vertex AI, AI Studio)
    Groq, UPB,    OpenAI chat completions: tool_calls / role "tool" messages with their ids,
    open model    reasoning in a field or in <think> tags
    Ollama        /api/chat: tool_calls / role "tool" messages without ids, a local deadline

A Conversation is one provider's exchange for one question. `run()` is the tool loop;
`correct(bad)` is the number check's single correction (verify.py), sent back into the same
conversation - the graph's verify node calls it, and `Chat.converse` does the same outside the
graph. Both share the round budget: MAX_ROUNDS tool rounds and the correction together, then
one last request without tools, whose answer is final.
"""

from __future__ import annotations

import json
import urllib.error
from dataclasses import dataclass, field

from . import chat as C
from . import tools as T


@dataclass
class Call:
    """A tool call as any provider asks for it."""

    name: str
    args: dict
    id: str | None = None


def _args(raw) -> dict:
    """A tool call's arguments: a JSON string (OpenAI-compatible) or already an object."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


class Adapter:
    """One provider's words for the loop's steps."""

    name = ""

    def __init__(self, chat) -> None:
        self.chat = chat

    def start(self, meta: dict) -> None:
        """Before each run, in the worker thread it runs in."""

    def body(self, req, results: list, meta: dict) -> dict:
        raise NotImplementedError

    def post(self, body: dict, meta: dict) -> dict:
        raise NotImplementedError

    def think(self, data: dict) -> str:
        return ""

    def calls(self, data: dict) -> list[Call]:
        raise NotImplementedError

    def text(self, data: dict) -> str:
        raise NotImplementedError

    def keep(self, body: dict, data: dict) -> None:
        """The model's turn that asked for tools, as the API wants it back."""
        raise NotImplementedError

    def answer_back(self, body: dict, done: list[tuple[Call, T.Result]]) -> None:
        """The tools' results, in reply to the calls."""
        raise NotImplementedError

    def correct(self, body: dict, data: dict, text: str, message: str) -> None:
        """The model's answer, then the correction asking it to drop what nothing backs."""
        raise NotImplementedError

    def can_correct(self, data: dict) -> bool:
        return True

    def last_round(self, body: dict) -> None:
        body.pop("tools", None)  # answer with what it has


class Gemini(Adapter):
    name = "gemini"

    def body(self, req, results, meta):
        web = bool(meta.get("web"))
        body = C.build_body(
            req, results, meta.get("extra", ""), search=self.chat.c.grounding or web,
            functions=not web,
        )
        if meta.get("gemini_tokens"):
            body["generationConfig"]["maxOutputTokens"] = meta["gemini_tokens"]
        return body

    def post(self, body, meta):
        data = self.chat._gemini_post(body, meta)
        if meta.get("web"):
            meta["web_sources"] = C.grounding_sources(data) or meta.get("web_sources", [])
        return data

    def think(self, data):
        return C.thoughts(data)

    def calls(self, data):
        return [Call(fc.get("name", ""), fc.get("args") or {}) for fc in C.function_calls(data)]

    def text(self, data):
        return C.parse(data)

    def keep(self, body, data):
        # the model's turn as it came: it may carry thought signatures
        body["contents"].append({"role": "model", **data["candidates"][0]["content"]})

    def answer_back(self, body, done):
        parts = [
            {"functionResponse": {"name": c.name, "response": {"content": r.as_markdown()}}}
            for c, r in done
        ]
        body["contents"].append({"role": "user", "parts": parts})

    def correct(self, body, data, text, message):
        self.keep(body, data)
        body["contents"].append({"role": "user", "parts": [{"text": message}]})

    def can_correct(self, data):
        return bool(data.get("candidates"))


class Completions(Adapter):
    """An OpenAI-compatible chat-completions API (Groq, UPB, an open model of your own)."""

    def model(self, meta: dict) -> str:
        raise NotImplementedError

    def body(self, req, results, meta):
        body = C.build_groq_body(req, self.model(meta), results, meta.get("extra", ""))
        body["max_tokens"] = meta.get("max_tokens") or body["max_tokens"]
        return body

    def think(self, data):
        return C.groq_thinking(data)

    @staticmethod
    def _msg(data: dict) -> dict:
        return ((data.get("choices") or [{}])[0].get("message")) or {}

    def calls(self, data):
        return [
            Call((tc.get("function") or {}).get("name", ""),
                 _args((tc.get("function") or {}).get("arguments") or {}), tc.get("id"))
            for tc in self._msg(data).get("tool_calls") or []
        ]

    def text(self, data):
        return C.parse_groq(data)

    def keep(self, body, data):
        # the model's turn as it came, less what the API does not take back
        msg = self._msg(data)
        body["messages"].append(
            {k: v for k, v in msg.items() if k not in ("reasoning", "executed_tools")}
        )

    def answer_back(self, body, done):
        for c, r in done:
            body["messages"].append(
                {"role": "tool", "tool_call_id": c.id, "content": r.as_markdown()}
            )

    def correct(self, body, data, text, message):
        body["messages"].append({"role": "assistant", "content": text})
        body["messages"].append({"role": "user", "content": message})


class Groq(Completions):
    name = "groq"

    def model(self, meta):
        return meta.get("groq_model") or self.chat.c.groq_model

    def body(self, req, results, meta):
        if not self.chat.c.groq_key:
            raise C.ModelError("no Groq API key configured")
        # Groq's own max_tokens follow the model and the depth (groq_model in _groq_post)
        return C.build_groq_body(req, self.model(meta), results, meta.get("extra", ""))

    def post(self, body, meta):
        return self.chat._groq_post(body, meta)


class UPB(Completions):
    name = "upb"

    def model(self, meta):
        return self.chat.c.upb_model

    def body(self, req, results, meta):
        if not self.chat.c.upb_key:
            raise C.ModelError("no UPB API key configured")
        return super().body(req, results, meta)

    def post(self, body, meta):
        return self.chat._upb_post(body, meta)

    def think(self, data):
        return ""  # UPB's models return no reasoning


class OpenAI(Completions):
    name = "openai"

    def model(self, meta):
        return self.chat.c.openai_model

    def body(self, req, results, meta):
        if not self.chat.c.openai_url:
            raise C.ModelError("no OpenAI-compatible endpoint configured")
        return super().body(req, results, meta)

    def post(self, body, meta):
        return self.chat._openai_post(body, meta)


class Ollama(Completions):
    name = "ollama"

    def start(self, meta):
        self.chat._local.deadline = meta.get("deadline")  # read by Chat._post_ollama_bounded

    def model(self, meta):
        return self.chat.c.ollama_model or "qwen2.5:7b-instruct"

    def body(self, req, results, meta):
        body = C.build_ollama_body(req, self.model(meta), results, meta.get("extra", ""))
        if meta.get("max_tokens"):  # a small local model: a third of a hosted model's allowance
            body["options"]["num_predict"] = max(600, meta["max_tokens"] // 3)
        return body

    def post(self, body, meta):
        try:
            return self.chat.post_ollama(self.chat.c.ollama_url, body)
        except urllib.error.HTTPError as e:
            raise C.ModelError(f"the local model answered HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError):
            raise C.ModelError(
                "the local model did not answer in time (is 'ollama serve' running?)"
            ) from None

    def think(self, data):
        msg = data.get("message") or {}
        return (msg.get("thinking") or C.split_think(msg.get("content") or "")[0]).strip()

    def calls(self, data):
        return [
            Call((tc.get("function") or {}).get("name", ""),
                 _args((tc.get("function") or {}).get("arguments") or {}))
            for tc in (data.get("message") or {}).get("tool_calls") or []
        ]

    def text(self, data):
        return C.parse_ollama(data)

    def keep(self, body, data):
        body["messages"].append(data.get("message") or {})

    def answer_back(self, body, done):
        for _, r in done:
            body["messages"].append({"role": "tool", "content": r.as_markdown()})


ADAPTERS: dict[str, type[Adapter]] = {
    a.name: a for a in (Gemini, Groq, UPB, OpenAI, Ollama)
}


@dataclass
class Conversation:
    """One provider's exchange for one question: the request so far, the rounds left, the last
    response and answer. The tool results it gathers go into the question's shared lists."""

    adapter: Adapter
    req: object
    ctx: T.Ctx
    results: list
    called: list[str]
    meta: dict
    body: dict = field(default_factory=dict)
    rounds: int = C.MAX_ROUNDS + 1
    last: dict = field(default_factory=dict)
    text: str = ""
    final: bool = False  # the answer came from the last request, without tools
    corrected: bool = False

    def __post_init__(self) -> None:
        self.body = self.adapter.body(self.req, self.results, self.meta)

    def say(self, kind: str, text: str) -> None:
        (self.meta.get("emit") or (lambda *_: None))(kind, text)

    def run(self) -> str:
        """The tool loop: to the model, its tool calls run here, their results back - until it
        answers without calls or the rounds run out, then once more without tools."""
        a = self.adapter
        a.start(self.meta)
        while self.rounds > 0:
            self.rounds -= 1
            data = self.last = a.post(self.body, self.meta)
            th = a.think(data)
            if th:
                self.meta.setdefault("thinking", []).append(th)
                self.say("thinking", th)
            calls = a.calls(data)
            if not calls:
                self.text = a.text(data)
                return self.text
            a.keep(self.body, data)
            done = []
            for call in calls:
                self.say("step", f"called {(call.name or '?').replace('_', ' ')}")
                r = T.call(call.name, call.args, self.ctx)
                self.results.append(r)
                self.called.append(r.tool)
                call.id = call.id or f"call_{len(self.called)}"
                done.append((call, r))
            a.answer_back(self.body, done)
        a.last_round(self.body)
        self.final = True
        self.last = a.post(self.body, self.meta)
        self.text = a.text(self.last)
        return self.text

    def correct(self, bad: list[str]) -> bool:
        """Send the answer back once with the numbers nothing backs (verify.py). False when the
        correction was already spent, the answer was the final one, or the response cannot take
        a reply - the answer then stands, flagged."""
        if self.corrected or self.final or not self.adapter.can_correct(self.last):
            return False
        self.corrected = True
        self.say("step", f"checking: {', '.join(bad)} not in the evidence - asked to rewrite")
        self.adapter.correct(self.body, self.last, self.text, C.correction(bad))
        return True
