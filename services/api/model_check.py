"""
Which language models the copilot can use right now, in its fallback order (chat.ORDER: Gemini,
Groq, UPB AI, the local model): each is asked one tiny question and the answer, the time and
any refusal are printed - never a key. Costs a few tokens per provider.

    PYTHONPATH=packages .venv/bin/python -m services.api.model_check     (or `make model-check`)
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error

from . import chat as C
from . import gcp_auth as GA

ASK = "Reply with the single word OK."


def _openai(post, url: str, key: str, model: str) -> str:
    """Submit a test inference probe to an OpenAI-compatible /chat/completions endpoint.

    Args:
        post: HTTP POST callable function.
        url: Base URL of the OpenAI-compatible service.
        key: Authentication key or token.
        model: Target model name.

    Returns:
        str: Cleaned text response from the model.
    """
    body = {"model": model, "messages": [{"role": "user", "content": ASK}], "max_tokens": 200}
    d = post(url, key, body)
    return (C.parse_groq(d) or "").strip()


def main() -> int:
    """Diagnostic CLI entry point probing each configured LLM provider in fallback priority.

    Returns:
        int: 0 if at least one provider answered successfully, 1 otherwise.
    """
    c = C.ChatSettings.from_env()
    probes = {
        "gemini": (
            bool(c.key),
            c.model,
            lambda: C.parse(
                C._post(
                    C.API.format(model=c.model),
                    c.key,
                    {"contents": [{"role": "user", "parts": [{"text": ASK}]}]},
                )
            ),
        ),
        "groq": (
            bool(c.groq_key),
            c.groq_model,
            lambda: _openai(C._post_groq, c.groq_url, c.groq_key, c.groq_model),
        ),
        "upb": (
            bool(c.upb_key),
            c.upb_model,
            lambda: _openai(C._post_groq, c.upb_url, c.upb_key, c.upb_model),
        ),
        "openai": (
            bool(c.openai_url),
            c.openai_model,
            lambda: _openai(C._post_groq, c.openai_url, c.openai_key or "", c.openai_model),
        ),
        "ollama": (bool(c.ollama_model), c.ollama_model, None),
    }
    if c.vertex_project:  # the Vertex AI lane (the trial credit) wins over a Google Cloud key
        cm = (c.cloud_models or [c.model])[0]
        probes["gemini (cloud)"] = (
            True,
            f"{cm} on Vertex AI ({c.vertex_project})",
            lambda: C.parse(
                C._post(
                    GA.endpoint(c.vertex_project, c.vertex_location, cm),
                    f"Bearer {GA.TOKENS.get()}",
                    {"contents": [{"role": "user", "parts": [{"text": ASK}]}]},
                )
            ),
        )
    elif c.cloud_key:  # the Google Cloud key is asked before the AI Studio one: check it on its own
        cm = (c.cloud_models or [c.model])[0]
        probes["gemini (cloud)"] = (
            True,
            cm,
            lambda: C.parse(
                C._post(
                    C.API.format(model=cm),
                    c.cloud_key,
                    {"contents": [{"role": "user", "parts": [{"text": ASK}]}]},
                )
            ),
        )
    usable = []
    for name in ("gemini (cloud)", *C.ORDER):
        if name not in probes:
            continue
        has, model, run = probes[name]
        if not has:
            print(f"  --   {name:14s} not configured")
            continue
        t = time.monotonic()
        try:
            if run is None:
                chat = C.Chat(C.sec.Settings.from_env(), c)
                if not chat._ollama_alive():
                    raise ConnectionError("not running ('ollama serve')")
                reply = "running"
            else:
                reply = run()
            usable.append(name)
            print(f"  ok   {name:14s} {model}  {time.monotonic() - t:4.1f} s  {reply[:40]!r}")
        except urllib.error.HTTPError as e:
            try:
                why = json.loads(e.read().decode()).get("error", {})
                why = why.get("message", "") if isinstance(why, dict) else str(why)
            except Exception:
                why = ""
            print(f"  FAIL {name:14s} {model}  HTTP {e.code} {why[:110]}")
        except Exception as e:  # noqa: BLE001 - report every failure
            print(f"  FAIL {name:14s} {model}  {type(e).__name__} {str(e)[:110]}")
    print("answers will come from: " + (" -> ".join(usable + ["the twin's tools"])))
    return 0 if usable else 1


if __name__ == "__main__":
    sys.exit(main())
