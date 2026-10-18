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

ASK = "Reply with the single word OK."


def _openai(post, url, key, model):
    body = {"model": model, "messages": [{"role": "user", "content": ASK}], "max_tokens": 200}
    d = post(url, key, body)
    return (C.parse_groq(d) or "").strip()


def main() -> int:
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
        "ollama": (bool(c.ollama_model), c.ollama_model, None),
    }
    usable = []
    for name in C.ORDER:
        has, model, run = probes[name]
        if not has:
            print(f"  --   {name:7s} not configured")
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
            print(f"  ok   {name:7s} {model}  {time.monotonic() - t:4.1f} s  {reply[:40]!r}")
        except urllib.error.HTTPError as e:
            try:
                why = json.loads(e.read().decode()).get("error", {})
                why = why.get("message", "") if isinstance(why, dict) else str(why)
            except Exception:
                why = ""
            print(f"  FAIL {name:7s} {model}  HTTP {e.code} {why[:110]}")
        except Exception as e:  # noqa: BLE001 - report every failure
            print(f"  FAIL {name:7s} {model}  {type(e).__name__} {str(e)[:110]}")
    print("answers will come from: " + (" -> ".join(usable + ["the twin's tools"])))
    return 0 if usable else 1


if __name__ == "__main__":
    sys.exit(main())
