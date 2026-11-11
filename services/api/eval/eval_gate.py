"""Compare two eval reports and fail on a regression.

  python -m services.api.eval_gate baseline.json candidate.json --max-p95-s 90 --max-cost-usd 5
  python -m services.api.eval_gate --rag tests/golden/rag_baseline.json candidate.json

Answers (eval_copilot.py reports): a candidate must contain the same questions. Quality includes
tool coverage, expected facts, number faithfulness, expected routing and required declines. When
both reports carry the claim check's grounding (eval_copilot's `grounding` summary), the mean
groundedness and citation coverage may not drop, nor the hallucination rate rise, by more than
their tolerances. Unknown-model pricing is visible and can be made blocking; it is never silently
interpreted as free.

RAG (eval_grounding.rag_report(), no model): retrieval MRR and hit@8, the hallucination
detector's precision, recall and false alarms, and the confidence's AUROC and calibration error,
each against a tolerance. tests/test_rag_gate.py runs it against tests/golden/rag_baseline.json
in CI; `make rag-gate` from the shell, `make rag-baseline` to accept a new baseline.
"""

from __future__ import annotations

import argparse
import json


def quality(row: dict) -> bool:
    return bool(
        row["tools_ok"] and row["facts_ok"] and row["faithful"]
        and row.get("route_ok") is not False and row.get("declines") is not False
    )


def compare(before: dict, after: dict, max_quality_drop=0, max_p95_s=90.0,
            max_cost_usd=5.0, max_unpriced=0, max_groundedness_drop=0.05,
            max_hallucination_rise=0.05, max_citation_drop=0.1) -> dict:
    """Return machine-readable gate results; failed checks are listed explicitly."""
    old = {r["q"]: r for r in before["rows"]}
    new = {r["q"]: r for r in after["rows"]}
    failures = []
    if set(old) != set(new):
        failures.append("candidate questions differ from baseline")
    common = sorted(set(old) & set(new))
    old_pass = sum(quality(old[q]) for q in common)
    new_pass = sum(quality(new[q]) for q in common)
    drop = old_pass - new_pass
    if drop > max_quality_drop:
        failures.append(f"quality passed dropped by {drop} (allowed {max_quality_drop})")
    regressions = [q for q in common if quality(old[q]) and not quality(new[q])]
    overall = after["summary"]["overall"]
    p95 = overall["latency_s"]["p95"]
    cost = overall["estimated_model_cost_usd"]
    unpriced = overall["unpriced_calls"]
    if p95 > max_p95_s:
        failures.append(f"p95 latency {p95}s exceeds {max_p95_s}s")
    if cost > max_cost_usd:
        failures.append(f"estimated model cost ${cost} exceeds ${max_cost_usd}")
    if unpriced > max_unpriced:
        failures.append(f"{unpriced} model calls have no configured price")
    g_old = before.get("summary", {}).get("grounding") or {}
    g_new = after["summary"].get("grounding") or {}
    grounding = {}
    if g_old and g_new:
        for key, tol, worse in (("groundedness", max_groundedness_drop, -1),
                                ("citation_coverage", max_citation_drop, -1),
                                ("hallucination_rate", max_hallucination_rise, 1)):
            a, b = g_old.get(key), g_new.get(key)
            grounding[key] = {"baseline": a, "candidate": b}
            if a is not None and b is not None and worse * (b - a) > tol + 1e-9:
                failures.append(f"{key} went from {a} to {b} (allowed {tol})")
    return {
        "passed": not failures,
        "questions": len(common),
        "quality": {"baseline_passed": old_pass, "candidate_passed": new_pass,
                    "regressions": regressions},
        "candidate": {"p95_s": p95, "estimated_model_cost_usd": cost,
                      "unpriced_calls": unpriced},
        "grounding": grounding,
        "budgets": {"max_quality_drop": max_quality_drop, "max_p95_s": max_p95_s,
                    "max_cost_usd": max_cost_usd, "max_unpriced": max_unpriced},
        "failures": failures,
    }


# --- the RAG gate: (section, metric) -> (tolerance, +1 when higher is better, -1 when lower is)
RAG_TOLERANCE = {
    ("retrieval", "mrr"): (0.02, 1),
    ("retrieval", "hit@8"): (0.03, 1),
    ("grounding", "precision"): (0.03, 1),
    ("grounding", "recall"): (0.03, 1),
    ("grounding", "hand_recall"): (0.06, 1),  # 18 hand-labelled fabrications: one is 0.056
    ("grounding", "false_alarm_rate"): (0.02, -1),
    ("grounding", "hand_false_alarm_rate"): (0.07, -1),  # one of 15 hand-labelled true claims
    ("grounding", "confidence_auroc"): (0.03, 1),
    ("grounding", "ece"): (0.05, -1),
}


def compare_rag(before: dict, after: dict, tolerance: dict | None = None) -> dict:
    """The RAG gate: every metric within its tolerance of the baseline, or a failure naming it."""
    tolerance = tolerance or RAG_TOLERANCE
    failures, rows = [], {}
    for (section, key), (tol, sign) in tolerance.items():
        a = (before.get(section) or {}).get(key)
        b = (after.get(section) or {}).get(key)
        rows[f"{section}.{key}"] = {"baseline": a, "candidate": b, "tolerance": tol}
        if a is None:
            continue
        if b is None:
            failures.append(f"{section}.{key} is missing from the candidate")
        elif sign * (a - b) > tol + 1e-9:
            failures.append(f"{section}.{key} went from {a} to {b} (allowed {tol})")
    return {"passed": not failures, "metrics": rows, "failures": failures}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rag", action="store_true",
                    help="compare two eval_grounding --rag reports instead")
    ap.add_argument("baseline")
    ap.add_argument("candidate")
    ap.add_argument("--max-quality-drop", type=int, default=0)
    ap.add_argument("--max-p95-s", type=float, default=90.0)
    ap.add_argument("--max-cost-usd", type=float, default=5.0)
    ap.add_argument("--max-unpriced", type=int, default=0)
    ap.add_argument("--output")
    a = ap.parse_args()
    with open(a.baseline, encoding="utf-8") as f:
        before = json.load(f)
    with open(a.candidate, encoding="utf-8") as f:
        after = json.load(f)
    if a.rag:
        result = compare_rag(before, after)
        print(json.dumps(result, indent=1))
        raise SystemExit(0 if result["passed"] else 1)
    result = compare(before, after, a.max_quality_drop, a.max_p95_s,
                     a.max_cost_usd, a.max_unpriced)
    text = json.dumps(result, indent=1) + "\n"
    if a.output:
        with open(a.output, "w", encoding="utf-8") as f:
            f.write(text)
    print(text, end="")
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
