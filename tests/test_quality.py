"""Online answer quality: the graph scores every answer (claims, citations, policy, confidence),
returns the scores with it, keeps one row per request id (storage/quality.py) holding no words,
and GET /copilot/quality shows them over time."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fastapi")

from services.api import chat as C  # noqa: E402
from services.api import security as sec  # noqa: E402
from services.api.agent import quality as AQ  # noqa: E402
from services.api.core import request_context  # noqa: E402
from services.api.storage import quality as SQ  # noqa: E402

from .test_chat import req  # noqa: E402

Q = "how does the colour sensor work?"
GOOD = ("The colour sensor gives a voltage in millivolts that depends on how bright the cookie "
        "is - it is a brightness reading, not a colour.")
BAD = "The colour sensor was invented by Marie Curie in Vienna during the war."


def row(rid, t, **kw):
    return {"request_id": rid, "t": t, "mode": "docs", "model": "m", "claims": 2,
            "unsupported": 0, "groundedness": 1.0, "citation_coverage": 1.0, "action": "pass",
            "declined": False, "confidence": 0.9, "latency_ms": 100, "tokens": 50,
            "cost_usd": 0.0001, **kw}


# --- the store
def test_the_sqlite_store_keeps_replaces_and_prunes(tmp_path):
    db = SQ.SqliteQuality(str(tmp_path / "q.db"))
    db.add(row("a" * 16, 1000.0))
    db.add(row("b" * 16, 2000.0, action="hedge", unsupported=1))
    db.add(row("a" * 16, 1500.0, action="strip"))  # the same request again: the newer row
    got = db.get("a" * 16)
    assert got["action"] == "strip" and got["t"] == 1500.0 and got["declined"] is False
    assert [r["request_id"][0] for r in db.since(0)] == ["a", "b"]
    db.lapse(1600.0)
    assert db.get("a" * 16) is None and db.get("b" * 16)


def test_the_totals_and_buckets():
    rows = [row("1", 10.0), row("2", 20.0, unsupported=1, groundedness=0.5, action="hedge"),
            row("3", 3700.0, declined=True, action="decline", claims=0, groundedness=None)]
    t = SQ.totals(rows)
    assert t["answers"] == 3 and t["groundedness"] == 0.75  # the claim-less answer left out
    assert t["hallucination_rate"] == round(1 / 3, 4) and t["decline_rate"] == round(1 / 3, 4)
    assert t["actions"] == {"pass": 1, "hedge": 1, "decline": 1} and t["tokens"] == 150
    s = SQ.series(rows, 0.0, 3600.0)
    assert [b["answers"] for b in s] == [2, 1] and s[1]["t"] == 3600.0


def test_the_tracker_writes_off_the_request_and_only_rows_with_an_id(tmp_path):
    import time

    q = SQ.Quality({}, store=SQ.SqliteQuality(str(tmp_path / "q.db")))
    q.record(row("x" * 16, time.time()), wait=True)
    q.record({**row("", time.time()), "request_id": None}, wait=True)
    assert q.get("x" * 16)["model"] == "m" and len(q.store.since(0)) == 1
    off = SQ.Quality({"STF_QUALITY": "0"}, store=SQ.SqliteQuality(str(tmp_path / "o.db")))
    off.record(row("y" * 16, 5.0), wait=True)
    assert off.store.since(0) == []


def test_a_failing_store_never_raises():
    class Broken:
        name = "broken"

        def add(self, row):
            raise OSError("disk full")

    SQ.Quality({}, store=Broken()).record(row("z" * 16, 1.0), wait=True)


# --- the graph
class Rows:
    def __init__(self):
        self.rows = []

    def record(self, r):
        self.rows.append(r)


def ask(answer, engine, monkeypatch):
    chat = C.Chat(
        sec.Settings.from_env(),
        C.ChatSettings(key=None, model="m", daily_limit=10, groq_key="gsk",
                       groq_model="openai/gpt-oss-120b", groq_models=["openai/gpt-oss-120b"]),
    )
    chat.c.ollama_model = None
    sent = []

    def post(url, key, body):
        sent.append(body["messages"][-1]["content"][:60])
        return {"choices": [{"message": {"content": answer}}]}

    chat.post_groq = post
    monkeypatch.setenv("STF_AGENT", engine)
    rows = Rows()
    AQ.set_tracker(rows)
    request_context._current.set("feedc0ffee123456")
    try:
        out = asyncio.run(chat.ask(C.ChatRequest(question=Q), req()))
    finally:
        AQ.set_tracker(None)
        request_context._current.set(None)
    return out, rows.rows, sent


@pytest.mark.parametrize("engine", ["graph", "linear"])
def test_a_backed_answer_is_scored_cited_and_recorded(engine, monkeypatch):
    out, rows, sent = ask(GOOD, engine, monkeypatch)
    qa = out["quality"]
    assert qa["claims"] == 1 and qa["supported"] == 1 and qa["action"] == "pass"
    assert qa["groundedness"] == 1.0 and qa["citation_coverage"] == 1.0 and qa["confidence"] > 0.5
    assert out["answer"].startswith(GOOD + " [") and len(sent) == 1  # cited, no second call
    assert out["claims"][0]["verdict"] == "supported"
    (r,) = rows
    assert r["request_id"] == "feedc0ffee123456" and r["mode"] == "docs" and not r["cached"]
    # scores, never words
    assert not any(isinstance(v, str) and ("colour" in v or "sensor" in v) for v in r.values())


@pytest.mark.parametrize("engine", ["graph", "linear"])
def test_an_invented_claim_is_hedged_and_counted(engine, monkeypatch):
    out, rows, sent = ask(f"{GOOD} {BAD}", engine, monkeypatch)
    qa = out["quality"]
    assert qa["unsupported"] == 1 and qa["action"] == "hedge" and not qa["regenerated"]
    assert "Marie Curie" in out["note"] and len(sent) == 1
    assert rows[0]["unsupported"] == 1


def test_a_mostly_invented_answer_is_sent_back_once(monkeypatch):
    two = f"{BAD} Its lens was ground by hand in a monastery near Lyon."
    out, rows, sent = ask(two, "graph", monkeypatch)
    assert len(sent) == 2
    qa = out["quality"]
    assert qa["regenerated"] and qa["action"] == "decline"
    assert "can't answer this reliably" in out["answer"]


# --- the routes
@pytest.fixture
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from services.api import app as appmod

    store = SQ.Quality({}, store=SQ.SqliteQuality(str(tmp_path / "q.db")))
    monkeypatch.setattr(appmod, "quality", store)
    return TestClient(appmod.app, raise_server_exceptions=False), store


def test_the_routes_show_quality_over_time_and_per_request(client):
    import time

    c, store = client
    now = time.time()
    store.record(row("r1" * 8, now - 600), wait=True)
    store.record(row("r2" * 8, now - 60, action="hedge", unsupported=1), wait=True)
    body = c.get("/copilot/quality?hours=1&bucket_s=300").json()
    assert body["totals"]["answers"] == 2 and body["totals"]["hallucination_rate"] == 0.5
    assert sum(b["answers"] for b in body["series"]) == 2 and body["bucket_s"] == 300
    assert c.get("/copilot/quality/" + "r2" * 8).json()["action"] == "hedge"
    miss = c.get("/copilot/quality/nope1234")
    assert miss.status_code == 404 and miss.json()["reason"] == "quality_not_found"
