"""The claim check (claims.py): an answer split into claims with their spans, each scored against
the passages it was given, numbers through verify.py, and the optional judge for the claims the
words leave unsure."""

from __future__ import annotations

from services.api.agent import claims as CL

SENSOR = (
    "The colour sensor gives a voltage in millivolts that depends on how bright the cookie is - "
    "it is a brightness reading, not a colour."
)
VIENNA = "It was invented in Vienna by a famous physicist."
UNSURE = "The reading depends on the cookie being bright or dark."
BANDS = "Bin blau from 0 to 645 mV; bin rot from 645 to 1305 mV; bin weiss from 1305 to 5000 mV."


def passages():
    return [CL._with_tokens(CL.Passage("Dashboard: Quality & trace > Terms", SENSOR, "doc")),
            CL._with_tokens(CL.Passage("PLC traceability > Colour bands", BANDS, "doc"))]


def check(answer, ask=None):
    ps = passages()
    return CL.check(answer, ps, " ".join(p.text for p in ps), "how does the colour sensor work?",
                    ask)


# --- splitting
def test_the_answer_splits_into_claims_with_their_spans():
    answer = ("Hello!\n\n## How it works\n\n- The sensor reads brightness in millivolts.\n"
              "- It is not an RGB sensor. A cookie above 1305 mV is white.\n\n"
              "```\nraw = 812\n```\nDo you want the bands?")
    claims = CL.split(answer)
    assert [c.kind for c in claims] == ["meta", "fact", "fact", "fact", "meta"]
    for c in claims:
        assert answer[c.start:c.end] == c.text
    one, two = claims[1], claims[2]
    assert one.text.startswith("- ") and one.whole  # a one-sentence item goes marker and all
    assert not two.text.startswith("- ")  # a sentence of a two-sentence item: just itself
    assert all("raw" not in c.plain for c in claims)  # code is not a claim


def test_declines_general_knowledge_and_citations():
    assert CL.split("What the documents say about the oven heating:")[0].kind == "meta"
    claims = CL.split("I don't know the oven's warranty terms.\n"
                      "In general, ovens lose heat through their doors.\n"
                      "The bands are fixed in the PLC [PLC traceability > Colour bands].")
    assert [c.kind for c in claims] == ["decline", "general", "fact"]
    assert claims[2].cited == ["PLC traceability > Colour bands"]
    assert "[" not in claims[2].plain


def test_a_table_row_is_one_claim_and_its_rule_is_none():
    claims = CL.split("| Bin | From |\n|---|---|\n| blau | 0 mV |")
    assert len(claims) == 2 and all(c.text.startswith("|") for c in claims)


# --- scoring
def test_a_backed_claim_is_supported_and_an_invented_one_is_not():
    r = check("The colour sensor gives a brightness reading in millivolts, not a colour.\n"
              "The colour sensor was invented by Marie Curie in Vienna during the war.")
    good, bad = r.facts()
    assert good.verdict == "supported" and good.support >= CL.HIGH
    assert r.passages[good.passage].label.startswith("Dashboard")
    assert bad.verdict == "unsupported" and bad.support < CL.LOW
    assert r.groundedness() == 0.5 and r.unsupported() == [bad]


def test_a_number_nothing_backs_condemns_the_claim_whatever_its_words():
    r = check("Bin rot runs from 645 to 1400 mV.")
    (c,) = r.facts()
    assert c.verdict == "unsupported" and c.why == "number" and c.numbers == ["1400"]


def test_a_citation_is_checked_against_the_passage_it_names():
    right = check("Bin rot runs from 645 to 1305 mV [PLC traceability > Colour bands].")
    wrong = check("Bin rot runs from 645 to 1305 mV [Dashboard: Quality & trace > Terms].")
    assert right.citation_precision() == 1.0 and wrong.citation_precision() == 0.0
    assert right.cited_by_model() == 1.0


def test_an_answer_with_nothing_to_check_has_no_groundedness():
    r = check("Hello! Happy to help.")
    assert r.facts() == [] and r.groundedness() is None


# --- the judge
def test_the_judge_settles_the_claims_the_words_leave_unsure(monkeypatch):
    monkeypatch.setenv("STF_CLAIM_JUDGE", "auto")
    asked = []

    def ask(system, user):
        asked.append(user)
        return '<think>hm</think> ["yes", "no"]'

    # the first is right in other words: the lexical score misses it, the judge does not
    r = check("The sensor measures how much light the cookie reflects.\n"
              "It was invented in Vienna by a famous physicist.", ask)
    assert r.judge_calls == 1 and len(asked) == 1 and "Claim 1:" in asked[0]
    assert [c.why for c in r.facts()] == ["judge", "judge"]
    assert [c.verdict for c in r.facts()] == ["supported", "unsupported"]


def test_off_or_a_bad_reply_leaves_the_words_verdict(monkeypatch):
    monkeypatch.setenv("STF_CLAIM_JUDGE", "off")
    r = check(VIENNA, lambda s, u: '["yes"]')
    assert r.judge_calls == 0 and r.facts()[0].verdict == "unsupported"
    monkeypatch.setenv("STF_CLAIM_JUDGE", "auto")
    r = check(VIENNA, lambda s, u: "I cannot tell")
    assert r.judge_calls == 1 and r.facts()[0].why != "judge"


def test_a_number_is_never_sent_to_the_judge(monkeypatch):
    monkeypatch.setenv("STF_CLAIM_JUDGE", "auto")
    sent = []
    r = check("Bin rot runs from 645 to 1400 mV.", lambda s, u: sent.append(u) or '["yes"]')
    assert not sent and r.judge_calls == 0 and r.facts()[0].verdict == "unsupported"


def test_carry_keeps_the_judges_verdicts_after_a_recheck(monkeypatch):
    monkeypatch.setenv("STF_CLAIM_JUDGE", "auto")
    first = check(UNSURE, lambda s, u: '["yes"]')
    assert first.judge_calls == 1
    again = CL.carry(check(UNSURE), first)
    assert again.facts()[0].verdict == "supported" and again.judge_calls == 1


# --- evidence
def test_the_evidence_is_every_passage_tool_and_the_operators_words():
    class R:
        def __init__(self, tool, text, facts, sources=(), cites=()):
            self.tool, self.text, self.facts = tool, text, facts
            self.sources, self.cites = list(sources), list(cites)

    ps = CL.passages_from(
        [R("search_docs", "", [("Doc > A", "alpha text")]),
         R("machine_health", "The belt is worn.", [("wear", "0.8")], ["condition model"])],
        context="the page", turns="my question",
    )
    assert [(p.label, p.kind) for p in ps] == [
        ("Doc > A", "doc"), ("condition model", "tool"), ("the page's context", "context"),
        ("your question", "turn"),
    ]
    assert "0.8" in ps[1].text
