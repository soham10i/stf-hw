"""Compare two eval_copilot reports and fail on quality, latency or cost regressions.

Example:
  python -m services.api.eval_gate baseline.json candidate.json --max-p95-s 90 --max-cost-usd 5

A candidate must contain the same questions. Quality includes tool coverage, expected facts,
number faithfulness, expected routing and required declines. Unknown-model pricing is visible and
can be made blocking; it is never silently interpreted as free.
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
            max_cost_usd=5.0, max_unpriced=0) -> dict:
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
    return {
        "passed": not failures,
        "questions": len(common),
        "quality": {"baseline_passed": old_pass, "candidate_passed": new_pass,
                    "regressions": regressions},
        "candidate": {"p95_s": p95, "estimated_model_cost_usd": cost,
                      "unpriced_calls": unpriced},
        "budgets": {"max_quality_drop": max_quality_drop, "max_p95_s": max_p95_s,
                    "max_cost_usd": max_cost_usd, "max_unpriced": max_unpriced},
        "failures": failures,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
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
