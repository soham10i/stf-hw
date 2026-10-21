"""Fluent equation readings (services/api/fluent_math.py): an LLM words each LaTeX
expression for speech; per-expression cache; rules-based mathspeak stays the fallback.
No network: the LLM call is mocked."""

import pytest

from services.api import fluent_math as F

LAMBDA = "\\frac{\\partial \\lambda}{\\partial x}"
NS = ("\\rho \\left( \\frac{\\partial \\mathbf{u}}{\\partial t} + \\mathbf{u} \\cdot "
      "\\nabla \\mathbf{u} \\right) = -\\nabla p + \\mu \\nabla^2 \\mathbf{u}")


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "_memo", {})
    monkeypatch.setattr(F, "_CACHE_DIR", tmp_path / "fluent-math")
    monkeypatch.setenv("TTS_MATH_FLUENT", "always")  # the LLM first; the default is below


def test_default_asks_the_llm_only_what_the_rules_cannot_say(monkeypatch):
    monkeypatch.delenv("TTS_MATH_FLUENT")
    monkeypatch.setattr(F, "dotenv", lambda: {})
    asked = []

    def fake(expressions):
        asked.append(expressions)
        return ["the qubit x"] * len(expressions)

    monkeypatch.setattr(F, "_ask", fake)
    out = F.verbalize_fluent_sync(f"Rule ${LAMBDA}$ and odd $\\qubit{{x}}$.")
    assert asked == [["\\qubit{x}"]]  # the rules say the derivative themselves
    assert LAMBDA in out  # left for mathspeak, read with its pauses
    assert "the qubit x" in out


def test_replaces_math_with_fluent_wording(monkeypatch):
    asked = []

    def fake(expressions):
        asked.append(expressions)
        return ["the partial derivative of lambda with respect to x",
                "rho times, open bracket, the partial derivative of u with respect to t "
                "plus u dot del u, close bracket, equals minus the gradient of p plus "
                "mu times the Laplacian of u"]

    monkeypatch.setattr(F, "_ask", fake)
    md = f"Balance: ${LAMBDA}$ and $${NS}$$."
    out = F.verbalize_fluent_sync(md)
    assert asked == [[LAMBDA, NS]]  # one batched call for both expressions
    assert "the partial derivative of lambda with respect to x" in out
    assert "the Laplacian of u" in out
    assert "\\frac" not in out and "$" not in out


def test_cache_makes_a_repeat_free(monkeypatch):
    calls = 0

    def fake(expressions):
        nonlocal calls
        calls += 1
        return ["the partial derivative of lambda with respect to x"] * len(expressions)

    monkeypatch.setattr(F, "_ask", fake)
    md = f"${LAMBDA}$"
    assert F.verbalize_fluent_sync(md) == " the partial derivative of lambda with respect to x "
    assert F.verbalize_fluent_sync(md) == " the partial derivative of lambda with respect to x "
    assert calls == 1  # the second answer comes from the cache
    # a fresh process reads the disk cache: only the memory cache was cleared
    F._memo.clear()
    assert F.verbalize_fluent_sync(md) == " the partial derivative of lambda with respect to x "
    assert calls == 1


def test_no_llm_answer_leaves_latex_for_rules_fallback(monkeypatch):
    monkeypatch.setattr(F, "_ask", lambda expressions: None)
    md = f"Efficiency ${LAMBDA}$."
    assert F.verbalize_fluent_sync(md) == md


def test_no_model_configured_returns_none(monkeypatch):
    monkeypatch.setattr(F.ChatSettings, "from_env", lambda: F.ChatSettings(
        key=None, model="m", daily_limit=1, groq_key=None))
    assert F._ask(["x^2"]) is None


def test_disabled_by_env(monkeypatch):
    monkeypatch.setenv("TTS_MATH_FLUENT", "0")
    monkeypatch.setattr(F, "_ask", lambda expressions: pytest.fail("must not call the LLM"))
    md = f"${LAMBDA}$"
    assert F.verbalize_fluent_sync(md) == md


@pytest.mark.parametrize("reply", [
    "no json here",
    '["only one"]',                       # wrong length
    '["ok", 42]',                         # not all strings
])
def test_parse_reply_rejects_malformed(reply):
    assert F._parse_reply(reply, 2) is None


def test_parse_reply_accepts_fenced_json():
    reply = '```json\n["a squared", "b cubed"]\n```'
    assert F._parse_reply(reply, 2) == ["a squared", "b cubed"]


def test_clean_strips_math_delimiters():
    assert F._clean("costs \\$5 and \\[x\\]") == "costs 5 and [x ]"
