"""Moving the operator's view by voice or text (core/navigation.py): the pages are the dashboard's
own, a request to move is told apart from a question, navigation is never frozen as a write and
never refused by a stop, and the reply tells the dashboard which page to open. The transcript
pass (voice/spoken.py) writes the rack's slots and the machines' names as the factory does."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from services.api.agent import tools as T
from services.api.core import navigation as NAV
from services.api.voice import spoken as SP

ROOT = Path(__file__).resolve().parents[1]


def test_the_pages_are_the_dashboards_own():
    src = (ROOT / "web/src/dashboard/Dashboard.tsx").read_text()
    block = src[src.index("const PAGES = [") : src.index("] as const;")]
    assert dict(re.findall(r'\["([a-z-]+)", "([^"]+)"', block)) == NAV.LABELS


def test_every_name_leads_to_a_real_page():
    assert set(NAV.ALIASES.values()) <= NAV.PAGES


@pytest.mark.parametrize(
    "said, page",
    [
        ("take me to the oven", "process"),
        ("navigate to oven view", "process"),
        ("open alarms page", "alarms"),
        ("go to the warehouse", "production"),
        ("Show me the camera.", "vision"),
        ("please open the energy dashboard", "energy"),
        ("switch to maintenance", "maintenance"),
        ("bring up the docs", "docs"),
    ],
)
def test_a_request_to_move_names_its_page(said, page):
    assert NAV.request(said) == page


@pytest.mark.parametrize(
    "said",
    [
        "show me the oven temperature",
        "what does the alarms page show?",
        "open the oven door",  # a machine command, not a page
        "take me through the oven process step by step",
    ],
)
def test_a_question_is_not_a_request_to_move(said):
    assert NAV.request(said) is None


def test_the_router_answers_a_move_with_the_move_alone():
    assert T.route("take me to the oven", T.Ctx()) == [("twin_navigate", {"page": "process"})]
    assert all(c[0] != "twin_navigate" for c in T.route("show me the oven temperature", T.Ctx()))


def test_navigation_is_not_frozen_with_the_writes(monkeypatch):
    monkeypatch.delenv("STF_AGENT_ACTUATION", raising=False)
    assert "twin_navigate" not in T.WRITE_TOOLS
    assert "twin_navigate" in {d["name"] for d in T.declarations()}
    res = T.call("twin_navigate", {"page": "oven"}, T.Ctx(client="op"))
    assert res.link == {"page": "process", "label": "Oven process"}
    assert res.text == "Opened the Oven process page."


def test_an_unknown_page_is_refused_and_moves_nothing():
    res = T.call("twin_navigate", {"page": "settings"}, T.Ctx(client="op"))
    assert res.link is None and "rejected" in res.text.lower()


def test_the_reply_tells_the_dashboard_where_to_go():
    from tests.test_chat import ask, make

    chat, _ = make()
    out = ask(chat, body={"question": "take me to the oven", "provider": "rules"})
    assert out["tools"] == ["twin_navigate"] and out["navigate"] == "process"
    out = ask(chat, body={"question": "what is the oee?", "provider": "rules"})
    assert "navigate" not in out


# ------------------------------------------------------------------ the transcript
@pytest.mark.parametrize(
    "heard, canonical",
    [
        ("store a red one in a two", "store a red one in A2"),
        ("fetch from slot bee three", "fetch from slot B3"),
        ("take it out of c one.", "take it out of C1."),
        ("retrieve from A 2", "retrieve from A2"),
        ("how is the h b w doing", "how is the HBW doing"),
        ("move the v g r home", "move the VGR home"),
    ],
)
def test_slots_and_names_are_written_as_the_factory_writes_them(heard, canonical):
    assert SP.canonical(heard) == canonical


@pytest.mark.parametrize(
    "said",
    ["a two-minute wait", "it was a one-off", "give me a three step summary", "slot D4 is not one"],
)
def test_ordinary_speech_is_left_alone(said):
    assert SP.canonical(said) == said


def test_what_was_heard_is_kept_beside_the_rewrite():
    assert SP.heard({"text": "store in a two", "model": "m"}) == {
        "text": "store in A2",
        "model": "m",
        "heard": "store in a two",
    }
    assert SP.heard({"text": "what is the oee", "model": "m"}) == {
        "text": "what is the oee",
        "model": "m",
    }


def test_the_transcription_endpoint_returns_the_rewrite(monkeypatch):
    import services.api.app as appmod

    async def fake(request):
        return {"text": "fetch from a two", "model": "test"}

    monkeypatch.setattr(appmod.stt, "transcribe", fake)
    out = asyncio.run(appmod.stt_transcribe(None))
    assert out == {"text": "fetch from A2", "model": "test", "heard": "fetch from a two"}
