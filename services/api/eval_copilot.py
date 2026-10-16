"""
Score the copilot with a real model on the evaluation set (tests/copilot_eval.json).

    python -m services.api.eval_copilot --provider gemini     # needs GEMINI_API_KEY (.env or env)
    python -m services.api.eval_copilot --provider ollama     # needs `ollama serve`, OLLAMA_MODEL
    python -m services.api.eval_copilot --provider rules      # the no-model baseline

Per question, through the same Chat.ask the dashboard uses:
  tools      every tool the question needs was called (pre-fetched by the router or by the model)
  facts      the expected strings are in the answer
  faithful   every number in the answer appears in the facts the tools returned - the check that
             the model invents nothing (years, list numbering and the question's own numbers are
             allowed)
  declines   an out-of-scope question is answered with "I don't know" or the like, not made up
Held-out questions are reported apart: they were not used to tune the router, so they show how
the model copes with paraphrases. Writes .cache/copilot_eval_<provider>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time

from starlette.requests import Request

from . import chat as C
from . import live
from . import security as sec
from . import tools as T

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
NUM = re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)?")
DECLINE = re.compile(
    r"(don.?t|do not|does not|doesn.?t) (know|have|cover)|not (covered|available|in the)"
    r"|no (data|information|tool)"
    r"|cannot (answer|find)|outside|not part of",
    re.I,
)


def _req(client: str = "127.0.0.1") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/chat",
            "headers": [(b"host", b"localhost:8000")],
            "client": (client, 5000),
        }
    )


def _numbers(s: str) -> set[str]:
    return {n.replace(",", ".").lstrip("-").rstrip("0").rstrip(".") or "0" for n in NUM.findall(s)}


def _derived(evidence: str) -> set[str]:
    """Sums and differences of two numbers the tools returned: correct arithmetic is not
    invention (the saving between two costs), a misread unit still is (2.43 h is not 2 h 43)."""
    xs = []
    for n in NUM.findall(evidence):
        try:
            xs.append(float(n.replace(",", ".")))
        except ValueError:
            pass
    xs = list(dict.fromkeys(xs))[:120]
    out = set()
    for i, a in enumerate(xs):
        for b in xs[i + 1 :]:
            for v in (a + b, abs(a - b)):
                out |= _numbers(f"{round(v, 2):g}") | _numbers(f"{round(v, 1):g}")
    return out


def score(case: dict, out: dict, evidence: str) -> dict:
    ans = out.get("answer", "")
    called = set(out.get("tools", []))
    need = set(case["tools"])
    facts_ok = all(f.lower() in out.get("answer", "").lower() for f in case.get("facts", []))
    allowed = _numbers(evidence) | _numbers(case["q"]) | _derived(evidence)
    ans = re.sub(r"(?m)^\s*\d{1,2}[.)]\s", " ", ans)                 # list numbering is not a fact
    invented = sorted(
        n
        for n in _numbers(ans) - allowed
        if not (len(n) == 4 and n.startswith("20")) and n not in {"1", "2", "3", "4", "5"}
    )
    return {
        "q": case["q"],
        "held_out": bool(case.get("held_out")),
        "tools_ok": need <= called,
        "missing_tools": sorted(need - called),
        "facts_ok": facts_ok,
        "faithful": not invented,
        "invented_numbers": invented[:8],
        "declines": bool(DECLINE.search(ans)) if case.get("unanswerable") else None,
        "model": out.get("model"),
        "note": out.get("note"),
        "answer": ans,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["gemini", "ollama", "rules"], default="gemini")
    ap.add_argument("--limit", type=int, default=0, help="first N cases only")
    ap.add_argument(
        "--pause", type=float, default=0.0, help="seconds between questions (rate limits)"
    )
    a = ap.parse_args()

    chat = C.Chat(sec.Settings.from_env())
    chat.limiter = sec.RateLimiter(rate=1000, burst=1000)  # the eval is one trusted client
    evidence: list[str] = []
    real_call = T.call

    def recording_call(name, args, ctx):  # keep what every tool returned
        r = real_call(name, args, ctx)
        evidence.append(json.dumps(r.as_dict(), ensure_ascii=False))
        return r

    T.call = recording_call
    live.put(
        {
            "step": "baking",
            "oven_temperature_C": 176,
            "oven_heating": True,
            "current_cookie": "chocolate, from A2 to A2",
            "robot_carrying": "nothing",
            "orders": ["3 x chocolate: 1 done"],
        },
        "127.0.0.1",
    )

    cases = json.load(open(os.path.join(ROOT, "tests", "copilot_eval.json")))["cases"]
    cases = cases[: a.limit] if a.limit else cases
    rows = []
    for c in cases:
        evidence.clear()
        live.put(
            {
                "step": "baking",
                "oven_temperature_C": 176,
                "oven_heating": True,
                "current_cookie": "chocolate, from A2 to A2",
                "robot_carrying": "nothing",
                "orders": ["3 x chocolate: 1 done"],
            },
            "127.0.0.1",
        )
        req = C.ChatRequest(question=c["q"], page=c.get("page"), provider=a.provider)
        t0 = time.time()
        out = asyncio.run(chat.ask(req, _req()))
        for wait in (20, 40, 60):  # a rate-limited model is retried, not scored
            if "rate limit" not in (out.get("note") or ""):
                break
            print(f"   rate limited - waiting {wait} s", flush=True)
            time.sleep(wait)
            evidence.clear()
            out = asyncio.run(chat.ask(req, _req()))
        row = score(c, out, " ".join(evidence))
        row["s"] = round(time.time() - t0, 1)
        rows.append(row)
        inv = f" invented={','.join(row['invented_numbers'])}" if row["invented_numbers"] else ""
        mark = "ok " if row["tools_ok"] and row["facts_ok"] and row["faithful"] else "MISS"
        print(
            f"{mark} {'[held] ' if row['held_out'] else ''}{c['q'][:60]:60} "
            f"tools={row['tools_ok']} facts={row['facts_ok']} "
            f"faithful={row['faithful']}{inv} {row['s']}s"
        )
        if a.pause:
            time.sleep(a.pause)

    def rate(sel, key):
        xs = [r[key] for r in sel if r[key] is not None]
        return f"{sum(xs)}/{len(xs)}" if xs else "-"

    tune = [r for r in rows if not r["held_out"]]
    held = [r for r in rows if r["held_out"]]
    summary = {
        "provider": a.provider,
        "model": next((r["model"] for r in rows if r["model"]), None),
        "fell_back": sum(1 for r in rows if r["note"]),
        "tuning": {k: rate(tune, k) for k in ("tools_ok", "facts_ok", "faithful", "declines")},
        "held_out": {k: rate(held, k) for k in ("tools_ok", "facts_ok", "faithful")},
        "mean_s": round(sum(r["s"] for r in rows) / max(1, len(rows)), 1),
    }
    os.makedirs(os.path.join(ROOT, ".cache"), exist_ok=True)
    path = os.path.join(ROOT, ".cache", f"copilot_eval_{a.provider}.json")
    json.dump({"summary": summary, "rows": rows}, open(path, "w"), indent=1)
    print(json.dumps(summary, indent=1))
    print(f"-> {path}")


if __name__ == "__main__":
    main()
