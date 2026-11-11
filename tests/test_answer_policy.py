"""The hallucination policy (answer_policy.py): what a checked answer becomes - passed, stripped
of the sentences nothing backs, hedged, declined - and the citations every supported claim gets."""

from __future__ import annotations

from services.api.agent import answer_policy as AP

from .test_claims import check

GOOD = "The colour sensor gives a brightness reading in millivolts, not a colour."
GOOD2 = "Bin rot runs from 645 to 1305 mV."
GOOD3 = "Bin weiss runs from 1305 to 5000 mV."
BAD = "The colour sensor was invented by Marie Curie in Vienna during the war."
BAD2 = "Its lens was ground by hand in a monastery near Lyon."


def decide(text, mode="docs", conf=None):
    r = check(text)
    return AP.decide(text, r, mode, conf), r


def test_a_backed_answer_and_a_greeting_pass():
    for text in (GOOD, "Hello! Happy to help."):
        d, _ = decide(text)
        assert d.action == "pass" and d.text == text and d.note is None


def test_one_invented_sentence_among_backed_ones_is_stripped():
    text = f"- {GOOD}\n- {GOOD2}\n- {GOOD3}\n- {BAD}"
    d, _ = decide(text)
    assert d.action == "strip" and BAD not in d.text and GOOD3 in d.text
    assert not d.text.endswith("-") and "Removed 1 statement" in d.note


def test_an_answer_the_sources_hardly_back_is_declined_with_its_closest_passages():
    d, _ = decide(f"{BAD} {BAD2}", conf=0.1)
    assert d.action == "decline" and "can't answer this reliably" in d.text
    assert d.removed and "Declined" in d.note


def test_a_mixed_answer_is_hedged_and_names_what_is_not_backed():
    d, _ = decide(f"{GOOD} {BAD}")
    assert d.action == "hedge" and d.text == f"{GOOD} {BAD}"
    assert "Marie Curie" in d.note


def test_web_answers_are_only_hedged_and_the_rules_fallback_never_changes():
    d, _ = decide(f"{BAD} {BAD2}", mode="web", conf=0.0)
    assert d.action == "hedge"
    r = check(BAD)
    assert AP.decide(BAD, r, "docs", 0.0, rules=True).action == "pass"


def test_only_a_judged_or_mostly_unbacked_answer_is_sent_back():
    one, _ = decide(f"{GOOD} {BAD}")
    assert AP.to_correct(check(f"{GOOD} {BAD}")) == []  # one lexical miss: hedged, no call
    assert one.action == "hedge"
    assert len(AP.to_correct(check(f"{BAD} {BAD2}"))) == 2
    r = check(f"{GOOD} {BAD}")
    r.facts()[1].why = "judge"
    assert AP.to_correct(r) == [BAD.rstrip(".") + "."]


def test_the_correction_names_the_numbers_and_the_claims():
    msg = AP.correction(["1400"], [BAD])
    assert "1400" in msg and f"- {BAD}" in msg and "square brackets" in msg


def test_every_supported_claim_gets_its_citation():
    text = f"{GOOD} {GOOD2} [PLC traceability > Colour bands]"
    r = check(text)
    shown, added = AP.cite(text, r)
    assert added == 1
    assert shown.startswith(f"{GOOD} [Dashboard: Quality & trace > Terms] {GOOD2}")
    assert AP.coverage(r) == 1.0
    assert AP.cite(text, check(text), voice=True) == (text, 0)


def test_an_unsupported_claim_gets_no_citation():
    r = check(BAD)
    assert AP.cite(BAD, r) == (BAD, 0) and AP.coverage(r) == 0.0
