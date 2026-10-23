"""Score the copilot's retrieval against a golden set of question -> source pairs.

The answer-level eval (eval_copilot.py) checks the finished answer; this one checks the
layer below it: does hybrid retrieval surface the passage the answer must come from?
Metrics per question: hit@1/3/5/8 (a retrieved passage from the expected file),
reciprocal rank and nDCG@10. The set mixes lexical questions (BM25 must carry them)
with paraphrases (the vector side earns its keep) - the report splits the two, so a
BM25 regression and an embedding regression are told apart.

    python -m services.api.eval_retrieval                    # the report
    STF_EMBEDDER=minilm python -m services.api.eval_retrieval   # real semantic vectors
    python -m services.api.eval_retrieval --judge ollama     # corrective retrieval (crag.py)
    python -m services.api.eval_retrieval --out .cache/retrieval_eval.json

Writes .cache/retrieval_eval_<embedder>.json (per-question ranks and the summary).
Golden-set entries whose source file disappears from the kb fail loudly in tests
(tests/test_retrieval_eval.py) - a renamed doc must update the set, not silently drop.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time

from . import crag as CR
from . import vectors as V
from .logging_config import get_logger

logger = get_logger(__name__)

GOLDEN: list[dict[str, str]] = [
    # mode "lex": word overlap exists - BM25 alone should surface the passage
    {"q": "how is the health index of a part calculated?",
     "file": "docs/maintenance/README.md", "mode": "lex"},
    {"q": "what does the colour sensor measure in millivolts?",
     "file": "docs/assistant/machine-sorting-line.md", "mode": "lex"},
    {"q": "how do the inspection camera photos reach the server?",
     "file": "docs/CAPTURES.md", "mode": "lex"},
    {"q": "what is the PLC's I/O map?",
     "file": "docs/plc/02-io-map.md", "mode": "lex"},
    {"q": "how does the vacuum gripper robot move the mould?",
     "file": "docs/assistant/machine-gripper-robot.md", "mode": "lex"},
    {"q": "what pages does the dashboard have?",
     "file": "docs/assistant/dashboard-overview.md", "mode": "lex"},
    {"q": "how does the guest session cookie work?",
     "file": "docs/DATABASE.md", "mode": "lex"},
    {"q": "what baking temperature and time does the oven use?",
     "file": "docs/assistant/machine-oven.md", "mode": "lex"},
    # mode "sem": a paraphrase - little word overlap, the vectors must bridge it
    {"q": "why does a belt warn long before it actually fails?",
     "file": "docs/maintenance/README.md", "mode": "sem"},
    {"q": "how are cookies checked for colour defects?",
     "file": "docs/assistant/dashboard-vision.md", "mode": "sem"},
    {"q": "where do the spoken answers come from?",
     "file": "docs/TTS_PIPELINE.md", "mode": "sem"},
    {"q": "what keeps two visitors' data apart?",
     "file": "docs/DATABASE.md", "mode": "sem"},
    {"q": "how is the factory's carbon footprint computed per cookie?",
     "file": "docs/assistant/dashboard-carbon.md", "mode": "sem"},
    {"q": "what happens when the high-bay crane picks a mould?",
     "file": "docs/assistant/machine-warehouse.md", "mode": "sem"},
    {"q": "how is the simulation's PLC program verified?",
     "file": "docs/plc/07-verification.md", "mode": "sem"},
    {"q": "what is the difference between the real factory and this twin?",
     "file": "docs/factory-vs-twin.md", "mode": "sem"},
]

KS = (1, 3, 5, 8)
TOP_K = 10  # ranks are computed over the top 10; MRR and nDCG use that window


def _ndcg(rel: list[int]) -> float:
    """nDCG@len(rel) with binary relevance and a single expected file."""
    dcg = sum(r / math.log2(i + 2) for i, r in enumerate(rel[:TOP_K]))
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(sum(rel), TOP_K)))
    return dcg / ideal if ideal else 0.0


def score(top_k: int = TOP_K, ask=None) -> dict:
    """Run the golden set through hybrid_search and compute the metrics.

    Works with whatever backend/embedder the environment selects (pgvector, SQLite or
    BM25-only when vectors are off), so the same command scores every configuration.

    Returns:
        dict: {"embedder", "backend", "n", "questions": [...], "metrics": {...}} -
        per-question ranks plus aggregate hit@k, MRR and nDCG. With `ask` (a model call),
        each question goes through corrective retrieval (crag.correct) instead, and its verdict
        is recorded.
    """
    store = V.get_store()
    backend = "bm25" if store is None else getattr(store, "name", "sqlite")
    embedder = "none" if store is None else store.embedder.name
    questions = []
    t0 = time.time()
    for g in GOLDEN:
        verdict = None
        if ask:
            j = CR.correct(g["q"], None, ask, k=top_k)
            hits, verdict = j.hits, j.verdict
        else:
            hits = V.hybrid_search(g["q"], top_k=top_k)
        ranks = [i + 1 for i, h in enumerate(hits) if h["passage"].file == g["file"]]
        rel = [1 if h["passage"].file == g["file"] else 0 for h in hits]
        questions.append(
            {
                "q": g["q"],
                "file": g["file"],
                "mode": g["mode"],
                "best_rank": ranks[0] if ranks else None,
                "hit": {k: bool(ranks and ranks[0] <= k) for k in KS},
                "rr": 1.0 / ranks[0] if ranks else 0.0,
                "ndcg": _ndcg(rel),
                "top_file": hits[0]["passage"].file if hits else None,
                **({"verdict": verdict} if verdict else {}),
            }
        )
    metrics = {}
    for mode in ("all", "lex", "sem"):
        qs = questions if mode == "all" else [q for q in questions if q["mode"] == mode]
        if not qs:
            continue
        metrics[mode] = {
            **{f"hit@{k}": round(sum(q["hit"][k] for q in qs) / len(qs), 3) for k in KS},
            "mrr": round(sum(q["rr"] for q in qs) / len(qs), 3),
            "ndcg": round(sum(q["ndcg"] for q in qs) / len(qs), 3),
            "n": len(qs),
        }
    out = {
        "judge": bool(ask),
        "embedder": embedder,
        "backend": backend,
        "n": len(questions),
        "seconds": round(time.time() - t0, 2),
        "questions": questions,
        "metrics": metrics,
    }
    logger.info("Retrieval eval: %s", json.dumps(metrics))
    return out


def main() -> None:
    """CLI entry: print the report and write the JSON result."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None, help="where to write the JSON report")
    ap.add_argument("--top-k", type=int, default=TOP_K)
    ap.add_argument("--judge", choices=["groq", "gemini", "ollama", "auto"], default=None,
                    help="corrective retrieval with this model as the judge (crag.py)")
    args = ap.parse_args()

    ask = None
    if args.judge:
        from . import chat as C
        from . import security as sec

        chat = C.Chat(sec.Settings.from_env())
        if args.judge != "auto":
            chat.QUICK_ORDER = (args.judge,)
        ask = lambda system, user: chat.quick(system, user)  # noqa: E731
    result = score(top_k=args.top_k, ask=ask)
    print(f"embedder: {result['embedder']}   backend: {result['backend']}   "
          f"n={result['n']}   {result['seconds']}s")
    for mode, m in result["metrics"].items():
        print(f"  {mode:>4}: " + "  ".join(f"{k}={v}" for k, v in m.items() if k != "n"))
    print("\nper question:")
    for q in result["questions"]:
        mark = " ok " if q["best_rank"] == 1 else (
            f"r{q['best_rank']}" if q["best_rank"] else "MISS"
        )
        print(f"  [{mark:>4}] ({q['mode']}) {q['q'][:60]:<60} -> {q['file']}"
              + (f"   (top: {q['top_file']})" if q["best_rank"] != 1 else "")
              + (f"   [{q['verdict']}]" if q.get("verdict") else ""))
    tag = f"_judge-{args.judge}" if args.judge else ""
    out = args.out or os.path.join(
        ".cache", f"retrieval_eval_{result['embedder']}_{result['backend']}{tag}.json"
    )
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\nwritten: {out}")


if __name__ == "__main__":
    main()
