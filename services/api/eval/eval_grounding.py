"""
How well the copilot catches what its answers make up: the hallucination detector (claims.py and
verify.py) and the answer confidence (confidence.py), scored on labelled answers, with no model.

The evidence of a case is what the chat would be given: the top passages retrieval returns for
its question (crag.candidates, as tools.docs_result labels them). Two sets of labelled claims:

  hand        tests/grounding_eval.json - claims written by hand against that evidence: true
              ones mostly in other words (the detector's false alarms), invented ones that sound
              right (its misses)
  perturbed   for every golden retrieval question (eval_retrieval.GOLDEN): two sentences taken
              from its evidence (supported), and from them a number changed, the rarest word
              swapped for another document's, and a sentence from a document the evidence does
              not hold (all unsupported)

Every case becomes answers: its supported claims together (backed), and those plus one
unsupported claim each (not backed). Measured:

  claims    precision, recall and F1 of "unsupported" (a claim flagged against its label), with
            "unsure" counted as flagged and as not; recall per kind of fabrication
  answers   AUROC of the confidence and of the groundedness against "every claim backed"; the
            confidence's Brier score and expected calibration error

    python -m services.api.eval.eval_grounding                 # the report
    python -m services.api.eval.eval_grounding --fit           # also fit confidence_weights.json
    python -m services.api.eval.eval_grounding --out r.json    # write the report

--fit fits the confidence on the even-numbered questions and reports it on the odd ones (it is
not judged on what it was fitted to), then writes the weights fitted on all of them. rag_report()
adds the retrieval metrics (eval_retrieval.py); eval_gate.py --rag compares it with
tests/golden/rag_baseline.json.
"""

from __future__ import annotations

import argparse
import json
import os
import re

from services.api.agent import claims as CL
from services.api.agent import confidence as CF
from services.api.agent import tools as twin_tools
from services.api.agent import verify as faithfulness
from services.api.core.logging_config import get_logger
from services.api.rag import crag

from . import eval_retrieval

logger = get_logger(__name__)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
HAND = os.path.join(ROOT, "tests", "grounding_eval.json")
TOP_K = 8  # passages a docs answer is given (the chat's search_docs default)
MIN_WORDS = 6  # a sentence taken from a passage must say this much


# --- the evidence
def evidence(q: str) -> tuple[list[CL.Passage], str, set[str]]:
    """The passages the chat would see for q, their text, and the files they come from."""
    hits = crag.candidates(q)[:TOP_K]
    r = twin_tools.docs_result(q, hits)
    ps = CL.passages_from([r])
    return ps, " ".join(p.text for p in ps), {h["passage"].file for h in hits}


def sentences(text: str) -> list[str]:
    """A passage's factual sentences, long enough to stand as a claim (no formulas, no tables)."""
    out = []
    for c in CL.split(text):
        if (c.kind == "fact" and len(CL.content(c.plain)) >= MIN_WORDS and "$" not in c.text
                and "|" not in c.text and ":" not in c.plain[:40] and len(c.plain) <= 260):
            out.append(c.plain.rstrip(".") + ".")
    return out


# --- the perturbations
def change_number(s: str, ev: str, q: str) -> str | None:
    """s with its first larger number changed to one the evidence does not hold."""
    for m in re.finditer(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])", s):
        n = m.group(1)
        if n in CL.SMALL:
            continue
        x = float(n)
        new = f"{x * 2 + 3:g}" if "." not in n else f"{x * 1.7 + 0.3:.1f}"
        out = s[: m.start()] + new + s[m.end():]
        if faithfulness.unverified(out, ev, q):
            return out
    return None


def swap_word(s: str, other: str) -> str | None:
    """s with its rarest content word replaced by the rarest of another document's sentence."""
    idf = CL.get_idf()
    mine = [w for w in re.findall(r"[A-Za-z][A-Za-z-]{3,}", s) if w.lower() not in CL.FILLER]
    theirs = [w for w in re.findall(r"[A-Za-z][A-Za-z-]{3,}", other)
              if w.lower() not in {m.lower() for m in mine}]
    if not mine or not theirs:
        return None
    a = max(mine, key=lambda w: idf(w.lower()))
    b = max(theirs, key=lambda w: idf(w.lower()))
    return re.sub(rf"\b{re.escape(a)}\b", b, s, count=1)


def perturbed() -> list[dict]:
    """The generated cases: per golden question, supported sentences and their fabrications."""
    golden = eval_retrieval.GOLDEN
    tops = []
    for g in golden:
        ps, ev, files = evidence(g["q"])
        said = [s for p in ps for s in sentences(p.text)]
        tops.append((g, ps, ev, files, said))
    cases = []
    for i, (g, _ps, ev, files, said) in enumerate(tops):
        if len(said) < 2:
            continue
        # a sentence from another question's evidence, none of whose documents this one holds
        others = (tops[(i + 7 * j) % len(tops)] for j in range(1, len(tops)))
        foreign = next((s for o in others if not (o[3] & files) for s in o[4][:1]), None)
        claims = [{"text": said[0], "supported": True}, {"text": said[1], "supported": True}]
        num = next((x for x in (change_number(s, ev, g["q"]) for s in said) if x), None)
        if num:
            claims.append({"text": num, "supported": False, "kind": "number"})
        if foreign:
            claims.append({"text": foreign, "supported": False, "kind": "foreign"})
            swapped = swap_word(said[0], foreign)
            if swapped and swapped != said[0]:
                claims.append({"text": swapped, "supported": False, "kind": "swap"})
        cases.append({"q": g["q"], "claims": claims, "set": "perturbed"})
    return cases


def hand() -> list[dict]:
    with open(HAND, encoding="utf-8") as f:
        return [{**c, "set": "hand"} for c in json.load(f)["cases"]]


# --- scoring
def answers(case: dict) -> list[tuple[str, list[dict], int]]:
    """The answers of a case: the supported claims together, then with one fabrication each."""
    good = [c for c in case["claims"] if c["supported"]]
    out = [(" ".join(c["text"] for c in good), good, 1)] if good else []
    for bad in (c for c in case["claims"] if not c["supported"]):
        claims = [*good, bad]
        out.append((" ".join(c["text"] for c in claims), claims, 0))
    return out


def run(cases: list[dict], ask=None) -> list[dict]:
    """Every answer of every case, checked as the chat checks it: one row per answer."""
    rows = []
    for n, case in enumerate(cases):
        ps, ev, _ = evidence(case["q"])
        for text, labelled, backed in answers(case):
            report = CL.check(text, ps, ev, case["q"], ask)
            facts = report.facts()
            got = []
            for want in labelled:  # the claim of the report that is this labelled sentence
                c = next((f for f in facts if f.plain.rstrip(".") in want["text"]
                          or want["text"].rstrip(".") in f.plain), None)
                got.append({"text": want["text"], "supported": want["supported"],
                            "kind": want.get("kind") or
                            ("hand" if case["set"] == "hand" else "taken"),
                            "verdict": c.verdict if c else "missed"})
            bad = faithfulness.unverified(text, ev, case["q"])
            rows.append({
                "q": case["q"], "n": n, "set": case["set"], "backed": backed,
                "claims": got,
                "x": CF.features(report, bad, None),
                "groundedness": report.groundedness(),
            })
    return rows


def _prf(pairs: list[tuple[bool, bool]]) -> dict:
    tp = sum(1 for want, got in pairs if want and got)
    fp = sum(1 for want, got in pairs if not want and got)
    fn = sum(1 for want, got in pairs if want and not got)
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f1 = 2 * p * r / (p + r) if p and r else 0.0
    return {"precision": _r(p), "recall": _r(r), "f1": _r(f1), "tp": tp, "fp": fp, "fn": fn}


def _r(x):
    return None if x is None else round(x, 4)


def claim_metrics(rows: list[dict]) -> dict:
    """Detection of unsupported claims, each distinct claim counted once."""
    # a supported claim is in every answer of its case: it counts once
    seen: dict[tuple, dict] = {}
    for r in rows:
        for c in r["claims"]:
            seen.setdefault((r["q"], c["text"]), c)
    claims = list(seen.values())
    strict = [(not c["supported"], c["verdict"] == "unsupported") for c in claims]
    lenient = [(not c["supported"], c["verdict"] in ("unsupported", "unsure")) for c in claims]
    kinds = sorted({c["kind"] for c in claims if not c["supported"]})
    return {
        "claims": len(claims),
        "unsupported": sum(1 for c in claims if not c["supported"]),
        "strict": _prf(strict),
        "lenient": _prf(lenient),
        "recall_by_kind": {
            k: _r(sum(1 for c in claims if c["kind"] == k and not c["supported"]
                      and c["verdict"] == "unsupported")
                  / max(1, sum(1 for c in claims if c["kind"] == k and not c["supported"])))
            for k in kinds
        },
        # supported claims flagged: the rate an honest answer is hedged or stripped
        "false_alarm_rate": _r(sum(1 for c in claims if c["supported"]
                                   and c["verdict"] == "unsupported")
                               / max(1, sum(1 for c in claims if c["supported"]))),
    }


def answer_metrics(rows: list[dict], weights: dict | None = None) -> dict:
    ys = [r["backed"] for r in rows]
    ps = [CF.confidence(r["x"], weights) for r in rows]
    gs = [r["groundedness"] if r["groundedness"] is not None else 1.0 for r in rows]
    return {
        "answers": len(rows),
        "backed": sum(ys),
        "confidence_auroc": CF.auroc(ps, ys),
        "groundedness_auroc": CF.auroc(gs, ys),
        "brier": CF.brier(ps, ys),
        "ece": CF.ece(ps, ys),
    }


def score(fit: bool = False, ask=None) -> dict:
    """The detector's report; with fit, the confidence fitted on even questions and reported
    on odd ones, plus the weights fitted on all (`weights`)."""
    cases = hand() + perturbed()
    rows = run(cases, ask)
    out = {
        "cases": {"hand": sum(c["set"] == "hand" for c in cases),
                  "perturbed": sum(c["set"] == "perturbed" for c in cases)},
        "claims": claim_metrics(rows),
        "claims_hand": claim_metrics([r for r in rows if r["set"] == "hand"]),
        "answers": answer_metrics(rows),
        "weights": "fitted" if os.path.exists(CF.WEIGHTS_PATH) else "default",
    }
    if fit:
        train = [r for r in rows if r["n"] % 2 == 0]
        test = [r for r in rows if r["n"] % 2 == 1]
        w = CF.fit([r["x"] for r in train], [r["backed"] for r in train])
        out["fit"] = {
            "train_answers": len(train),
            "held_out_default": answer_metrics(test, CF.DEFAULT),
            "held_out_fitted": answer_metrics(test, w),
        }
        out["fitted_weights"] = CF.fit([r["x"] for r in rows], [r["backed"] for r in rows])
        out["_x"] = [r["x"] for r in rows]
    return out


def rag_report() -> dict:
    """The retrieval and grounding numbers the RAG gate compares (eval_gate.py --rag)."""
    ret = eval_retrieval.score()
    g = score()
    m = ret["metrics"]["all"]
    return {
        "retrieval": {k: m[k] for k in ("hit@1", "hit@3", "hit@8", "mrr", "ndcg")},
        "grounding": {
            "precision": g["claims"]["strict"]["precision"],
            "recall": g["claims"]["strict"]["recall"],
            "f1": g["claims"]["strict"]["f1"],
            "false_alarm_rate": g["claims"]["false_alarm_rate"],
            "hand_recall": g["claims_hand"]["strict"]["recall"],
            "hand_false_alarm_rate": g["claims_hand"]["false_alarm_rate"],
            "confidence_auroc": g["answers"]["confidence_auroc"],
            "brier": g["answers"]["brier"],
            "ece": g["answers"]["ece"],
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--fit", action="store_true", help="fit and write confidence_weights.json")
    ap.add_argument("--rag", action="store_true", help="the gate's report (retrieval too)")
    ap.add_argument("--out", help="where to write the JSON report")
    a = ap.parse_args()
    report = rag_report() if a.rag else score(fit=a.fit)
    if a.fit:
        with open(CF.WEIGHTS_PATH, "w", encoding="utf-8") as f:
            xs = report.pop("_x")
            fixed = [k for k in CF.FEATURES if len({r[k] for r in xs}) == 1]
            json.dump({"weights": report["fitted_weights"], "features": list(CF.FEATURES),
                       "kept_at_default": fixed,
                       "fitted_on": report["answers"]["answers"],
                       "by": "services/api/eval/eval_grounding.py --fit"}, f, indent=1)
            f.write("\n")
        CF.reset_weights()
        print(f"-> {CF.WEIGHTS_PATH}")
    text = json.dumps(report, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
