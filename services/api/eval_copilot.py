"""
Score the copilot with a real model on the evaluation set (tests/copilot_eval.json).

    python -m services.api.eval_copilot --provider gemini     # needs GEMINI_API_KEY (.env or env)
    python -m services.api.eval_copilot --provider ollama     # needs `ollama serve`, OLLAMA_MODEL
    python -m services.api.eval_copilot --provider rules      # the no-model baseline

Per question, through the same Chat.ask the dashboard uses:
  tools      every tool the question needs was called (pre-fetched by the router or by the model)
  facts      the expected strings are in the answer
  faithful   every number in the answer is backed by what the tools returned (verify.py: the
             same check the chat runs before it shows an answer)
  declines   an out-of-scope question is answered with "I don't know" or the like, not made up
Held-out questions are reported apart: they were not used to tune the router, so they show how
the model copes with paraphrases. Writes .cache/copilot_eval_<provider>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import subprocess
import time

from starlette.requests import Request

from . import chat as C
from . import live
from . import security as sec
from . import tools as T
from . import verify as V

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
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


def score(case: dict, out: dict, evidence: str) -> dict:
    """Score quality, route, search, tokens, cost and latency through the production Chat path."""
    ans = out.get("answer", "")
    called = set(out.get("tools", []))
    need = set(case["tools"])
    facts_ok = all(f.lower() in ans.lower() for f in case.get("facts", []))
    invented = V.unverified(ans, evidence, case["q"])  # the check the chat itself runs
    route = (out.get("route") or {}).get("mode") or "unknown"
    spans = (out.get("trace") or {}).get("spans") or []
    searches = [s for s in spans if s.get("name", "").startswith("search.")]
    return {
        "q": case["q"],
        "held_out": bool(case.get("held_out")),
        "route": route,
        "requested_route": case.get("route") or route,
        "route_ok": route == case["route"] if case.get("route") else None,
        "tools_ok": need <= called,
        "missing_tools": sorted(need - called),
        "facts_ok": facts_ok,
        "faithful": not invented,
        "invented_numbers": invented[:8],
        "declines": bool(DECLINE.search(ans)) if case.get("unanswerable") else None,
        "model": out.get("model"),
        "note": out.get("note"),
        "usage": out.get("usage") or {},
        "search_attempts": len(searches),
        "search_failures": sum((s.get("attrs") or {}).get("stf.found") is False for s in searches),
        "web_sources": sum((s.get("attrs") or {}).get("stf.sources") or 0 for s in searches),
        "answer": ans,
    }


def percentile(values: list[float], fraction: float) -> float:
    """Linear-interpolated percentile, rounded for stable evaluation artifacts."""
    xs = sorted(values)
    if not xs:
        return 0.0
    at = (len(xs) - 1) * fraction
    low, high = int(at), min(int(at) + 1, len(xs) - 1)
    return round(xs[low] + (xs[high] - xs[low]) * (at - low), 3)


def summarize(rows: list[dict], provider: str) -> dict:
    """Aggregate overall and per-route quality, reliability, latency, usage and cost."""
    def rate(sel, key):
        xs = [r[key] for r in sel if r.get(key) is not None]
        return f"{sum(xs)}/{len(xs)}" if xs else "-"

    def quality(sel):
        return sum(
            r["tools_ok"] and r["facts_ok"] and r["faithful"]
            and r.get("route_ok") is not False and r.get("declines") is not False
            for r in sel
        )

    def route_row(sel):
        lat = [r["s"] for r in sel]
        return {
            "questions": len(sel),
            "quality_passed": quality(sel),
            "tokens": sum((r.get("usage") or {}).get("tokens", 0) for r in sel),
            "input_tokens": sum((r.get("usage") or {}).get("input_tokens", 0) for r in sel),
            "output_tokens": sum((r.get("usage") or {}).get("output_tokens", 0) for r in sel),
            "estimated_model_cost_usd": round(sum(
                (r.get("usage") or {}).get("estimated_model_cost_usd", 0) for r in sel
            ), 8),
            "unpriced_calls": sum((r.get("usage") or {}).get("unpriced_calls", 0) for r in sel),
            "search_attempts": sum(r.get("search_attempts", 0) for r in sel),
            "search_failures": sum(r.get("search_failures", 0) for r in sel),
            "web_sources": sum(r.get("web_sources", 0) for r in sel),
            "failures": sum(bool(r.get("note")) or r.get("route_ok") is False for r in sel),
            "latency_s": {
                "p50": percentile(lat, 0.5), "p95": percentile(lat, 0.95),
                "mean": round(sum(lat) / max(1, len(lat)), 3),
            },
        }

    tune = [r for r in rows if not r["held_out"]]
    held = [r for r in rows if r["held_out"]]
    modes = sorted({r.get("requested_route", r["route"]) for r in rows})
    return {
        "provider": provider,
        "model": next((r["model"] for r in rows if r["model"]), None),
        "fell_back": sum(1 for r in rows if r["note"]),
        "tuning": {k: rate(tune, k) for k in ("tools_ok", "facts_ok", "faithful", "declines")},
        "held_out": {k: rate(held, k) for k in ("tools_ok", "facts_ok", "faithful")},
        "mean_s": round(sum(r["s"] for r in rows) / max(1, len(rows)), 3),
        "overall": route_row(rows),
        "by_route": {
            mode: route_row([
                r for r in rows if r.get("requested_route", r["route"]) == mode
            ]) for mode in modes
        },
    }


def main() -> None:
    """The eval CLI: replay the golden cases against a provider, write the report."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["gemini", "groq", "ollama", "rules"], default="gemini")
    ap.add_argument("--limit", type=int, default=0, help="first N cases only")
    ap.add_argument("--cases", default=os.path.join(ROOT, "tests", "copilot_eval.json"))
    ap.add_argument("--tag", default="", help="report name, e.g. gemini-3.8-flash")
    ap.add_argument("--output", help="explicit JSON report path")
    ap.add_argument("--engine", choices=["graph", "linear"], help="override STF_AGENT for this run")
    ap.add_argument(
        "--pause", type=float, default=0.0, help="seconds between questions (rate limits)"
    )
    a = ap.parse_args()
    if a.engine:
        os.environ["STF_AGENT"] = a.engine

    chat = C.Chat(sec.Settings.from_env())
    chat.limiter = sec.RateLimiter(rate=1000, burst=1000)  # the eval is one trusted client
    evidence: list[str] = []
    real_call = T.call

    def recording_call(name, args, ctx):  # keep what every tool returned
        """Wrap a tool call, appending its result to the evidence log."""
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

    with open(a.cases, encoding="utf-8") as f:
        cases = json.load(f)["cases"]
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
        req = C.ChatRequest(
            question=c["q"], page=c.get("page"), provider=a.provider,
            mode=c.get("mode"), depth=c.get("depth"),
        )
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

    summary = summarize(rows, a.provider)
    try:
        commit = subprocess.run(  # noqa: S603 - fixed argv, repository provenance only
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = "unknown"
    metadata = {
        "schema_version": 1,
        "recorded_at": dt.datetime.now(dt.UTC).isoformat(),
        "commit": commit,
        "cases": os.path.relpath(a.cases, ROOT),
        "engine": a.engine or os.environ.get("STF_AGENT", "graph"),
        "tag": a.tag or a.provider,
        "agent_actuation": T.actuation_enabled(),
        "cost_basis": "estimated model list price; excludes grounding, infrastructure, tax and FX",
    }
    path = a.output or os.path.join(ROOT, ".cache", f"copilot_eval_{metadata['tag']}.json")
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"metadata": metadata, "summary": summary, "rows": rows}, f, indent=1)
        f.write("\n")
    print(json.dumps(summary, indent=1))
    print(f"-> {path}")


if __name__ == "__main__":
    main()
