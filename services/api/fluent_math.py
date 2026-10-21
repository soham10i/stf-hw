"""Fluent equation readings from a language model, ahead of the voice pipeline.

The rules (mathspeak) read an equation the way a lecturer does - its structure in the
wording ("rho times the quantity ...", "the gradient of p", "a plus b, all over c") and
in timed pauses between terms and before the relation - deterministically, offline and
at no cost. They cover the notation the copilot writes. This layer is for the rest:
notation mathspeak cannot say (it raises Unsupported) goes to the chat's language
model (Groq first, Gemini next), which words it in the same style.

TTS_MATH_FLUENT:
- unset / "fallback" (default): only expressions the rules cannot say go to the LLM.
- "always" (or "1"): every expression goes to the LLM first; the rules are the fallback.
  More latency (~1 s per answer), quota, and the reading of an equation may vary.
- "0" / "off": no LLM; what the rules cannot say is read as "(formula)".

Design:
- One batched call per answer for every not-yet-cached expression (~1 s on Groq).
- Per-expression cache (memory + disk): a repeated equation costs nothing.
- Any failure - no key, rate limit, timeout, malformed JSON - leaves the LaTeX in
  place and tts.py's rules-based mathspeak verbalizes it, so speech never breaks.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tempfile
import urllib.error
from pathlib import Path

from . import mathspeak
from .chat import API, ChatSettings, _post, _post_groq, dotenv, groq_model, parse, parse_groq
from .logging_config import get_logger

logger = get_logger(__name__)

MATH_RX = re.compile(
    r"\$\$([\s\S]+?)\$\$|\\\[(.+?)\\\]|\\\((.+?)\\\)|\$([^$\n]{1,2000})\$"
)

SYSTEM = (
    """\
You write how a professor reads equations aloud in a lecture. You receive a JSON array
of LaTeX math expressions and reply with a JSON array of the same length: for each
expression, the spoken wording, in plain words, with commas where the professor pauses.

Rules:
- Plain words only: no LaTeX, no symbols, no markdown, no numbering.
- Name Greek letters (lambda, rho, omega), units (metres per second squared), and
  functions (sine of x, log base 2 of x).
- Derivatives: "partial u by partial t"; "d y by d x" for ordinary d-derivatives.
- Named operators: "the gradient of p" for \\nabla p, "the divergence of v" for
  \\nabla \\cdot v, "the curl of B", "the Laplacian of u" for \\nabla^2 u, and
  "u dot del u" for (u \\cdot \\nabla) u.
- Grouping by wording, never "open bracket": "rho times the quantity a plus b",
  "a plus b, all over c", "one half m v squared".
- Pauses carry the hierarchy: a comma between the terms of a side and before the
  relation ("..., equals ..."), and where a bracketed group closes.
- Keep the expression's order. A short phrase per expression; not a full sentence.
- Reply with JSON only: an array of strings.

Examples:
Input: ["\\\\frac{\\\\partial \\\\lambda}{\\\\partial x}"]
Output: ["the partial derivative of lambda with respect to x"]
Input: ["\\\\rho \\\\left( \\\\frac{\\\\partial \\\\mathbf{u}}{\\\\partial t} + """
    """\\\\mathbf{u} \\\\cdot \\\\nabla \\\\mathbf{u} \\\\right) = -\\\\nabla p + """
    """\\\\mu \\\\nabla^2 \\\\mathbf{u}"]
Output: ["rho times the quantity partial u by partial t, plus u dot del u, """
    """equals minus the gradient of p, plus mu times the Laplacian of u"]
Input: ["E = mc^2", "\\\\int_0^1 x^2\\\\,dx", """
    """"\\\\mathrm{3.5\\\\,m/s^2}"]
Output: ["E equals m c squared", "the integral from 0 to 1 of x squared with """
    """respect to x", "3 point 5 metres per second squared"]"""
)

_CACHE_DIR = Path(tempfile.gettempdir()) / "stf-fluent-math"
_memo: dict[str, str] = {}


def _mode() -> str:
    """off, fallback (only what the rules cannot say) or always (TTS_MATH_FLUENT)."""
    v = {**dotenv(), **os.environ}.get("TTS_MATH_FLUENT", "fallback").strip().lower()
    if v in ("0", "false", "no", "off"):
        return "off"
    return "always" if v in ("1", "true", "yes", "on", "always") else "fallback"


def _rules_can_say(expr: str) -> bool:
    try:
        mathspeak.verbalize(expr)
        return True
    except mathspeak.Unsupported:
        return False


def _key(expr: str) -> str:
    return hashlib.sha256(expr.encode()).hexdigest()


def _lookup(expr: str) -> str | None:
    if expr in _memo:
        return _memo[expr]
    f = _CACHE_DIR / f"{_key(expr)}.json"
    if f.exists():
        try:
            spoken = json.loads(f.read_text()).get("spoken")
        except (OSError, ValueError):
            return None
        if isinstance(spoken, str) and spoken.strip():
            _memo[expr] = spoken
            return spoken
    return None


def _store(expr: str, spoken: str) -> None:
    _memo[expr] = spoken
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (_CACHE_DIR / f"{_key(expr)}.json").write_text(
            json.dumps({"latex": expr, "spoken": spoken})
        )
    except OSError as e:
        logger.warning("fluent-math cache write failed: %s", e)


def _clean(text: str) -> str:
    """The spoken wording must survive the speech pipeline: no math delimiters."""
    return re.sub(r"\s+", " ", re.sub(r"[$\\]", " ", text)).strip()


def _parse_reply(text: str, n: int) -> list[str] | None:
    m = re.search(r"\[.*\]", text or "", re.S)
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(out, list) or len(out) != n:
        return None
    if not all(isinstance(s, str) and s.strip() for s in out):
        return None
    return [_clean(s) for s in out]


def _ask(expressions: list[str]) -> list[str] | None:
    """One batched verbalization via Groq, then Gemini. None when no model answered."""
    s = ChatSettings.from_env()
    user = json.dumps(expressions)
    if s.groq_key:
        try:
            body = groq_model(
                {
                    "model": s.groq_models[0] if s.groq_models else s.groq_model,
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 1200,
                },
                s.groq_models[0] if s.groq_models else s.groq_model,
            )
            reply = _parse_reply(parse_groq(_post_groq(s.groq_url, s.groq_key, body)),
                                 len(expressions))
            if reply:
                return reply
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
            logger.warning("fluent-math Groq call failed: %s", e)
    if s.key:
        try:
            body = {
                "contents": [{"role": "user", "parts": [{"text": SYSTEM + "\n\n" + user}]}],
                "generationConfig": {"temperature": 0.0, "maxOutputTokens": 1024},
            }
            reply = _parse_reply(
                parse(_post(API.format(model=s.model), s.key, body)), len(expressions)
            )
            if reply:
                return reply
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
            logger.warning("fluent-math Gemini call failed: %s", e)
    return None


def verbalize_fluent_sync(md: str) -> str:
    """Markdown with each LaTeX expression replaced by its fluent spoken wording.
    Falls back to leaving the LaTeX in place (tts.py then uses rules-based mathspeak)."""
    mode = _mode()
    if mode == "off":
        return md
    matches = list(MATH_RX.finditer(md))
    if not matches:
        return md
    asked: set[str] = set()  # what this call words by the LLM; the rest stays for the rules
    pending: list[str] = []
    for m in matches:
        inner = next(g for g in m.groups() if g is not None)
        if inner in asked or (mode == "fallback" and _rules_can_say(inner)):
            continue
        asked.add(inner)
        if _lookup(inner) is None:
            pending.append(inner)
    if pending:
        logger.info("fluent-math: verbalizing %d expression(s) via LLM", len(pending))
        spoken = _ask(pending)
        if spoken:
            for expr, words in zip(pending, spoken, strict=True):
                _store(expr, words)
        else:
            logger.warning("fluent-math: no LLM answer; rules-based mathspeak instead")

    def sub(m: re.Match) -> str:
        inner = next(g for g in m.groups() if g is not None)
        words = _lookup(inner) if inner in asked else None
        return f" {words} " if words else m.group(0)

    return MATH_RX.sub(sub, md)


async def verbalize_fluent(md: str) -> str:
    """The sync verbalizer off the event loop (it makes blocking HTTP calls)."""
    return await asyncio.to_thread(verbalize_fluent_sync, md)
