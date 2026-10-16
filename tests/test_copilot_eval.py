"""The rules router against the evaluation set (tests/copilot_eval.json): it must call every tool
a question needs on the tuning cases, and its held-out score must not fall below the floor -
the honest measure of how well keyword routing generalises. The models are scored by
services/api/eval_copilot.py, which needs a model."""

import json
import os

from services.api import tools as T

SET = json.load(open(os.path.join(os.path.dirname(__file__), "copilot_eval.json")))["cases"]
HELD_OUT_FLOOR = (
    8 / 12
)  # measured 2026-10-16; keyword routing cannot follow paraphrases - the models must


def routed(case) -> set[str]:
    return {n for n, _ in T.route(case["q"], T.Ctx(page=case.get("page")))}


def test_tuning_cases_route_to_every_needed_tool():
    misses = [
        (c["q"], sorted(set(c["tools"]) - routed(c)))
        for c in SET
        if not c.get("held_out") and not set(c["tools"]) <= routed(c)
    ]
    assert not misses, misses


def test_held_out_routing_floor():
    held = [c for c in SET if c.get("held_out")]
    ok = sum(set(c["tools"]) <= routed(c) for c in held)
    print(f"held-out routing: {ok}/{len(held)}")
    assert ok / len(held) >= HELD_OUT_FLOOR, f"{ok}/{len(held)}"


def test_rules_answers_contain_the_facts():
    misses = []
    for c in SET:
        if (
            c.get("held_out")
            or c.get("unanswerable")
            or "live_state" in c["tools"]
            or not c.get("facts")
        ):
            continue
        text, res = T.rules_answer(c["q"], T.Ctx(page=c.get("page")))
        blob = (text + " " + json.dumps([r.as_dict() for r in res])).lower()
        missing = [f for f in c["facts"] if f.lower() not in blob]
        if missing:
            misses.append((c["q"], missing))
    assert not misses, misses
