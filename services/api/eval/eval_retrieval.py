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

from services.api.core.logging_config import get_logger
from services.api.rag import crag, vectors

logger = get_logger(__name__)

GOLDEN: list[dict[str, str]] = [
    # mode "lex": word overlap exists - BM25 alone should surface the passage
    {"q": "how is the health index of a part calculated?",
     "file": "docs/reference/maintenance/README.md", "mode": "lex"},
    {"q": "what does the colour sensor measure in millivolts?",
     "file": "docs/reference/machines/sorting-line.md", "mode": "lex"},
    {"q": "how do the inspection camera photos reach the server?",
     "file": "docs/reference/operations/captures.md", "mode": "lex"},
    {"q": "what is the PLC's I/O map?",
     "file": "docs/reference/plc/02-io-map.md", "mode": "lex"},
    {"q": "how does the vacuum gripper robot move the mould?",
     "file": "docs/reference/machines/gripper-robot.md", "mode": "lex"},
    {"q": "what pages does the dashboard have?",
     "file": "docs/reference/dashboard/overview.md", "mode": "lex"},
    {"q": "how does the guest session cookie work?",
     "file": "docs/reference/operations/database.md", "mode": "lex"},
    {"q": "what baking temperature and time does the oven use?",
     "file": "docs/reference/machines/oven.md", "mode": "lex"},
    # mode "sem": a paraphrase - little word overlap, the vectors must bridge it
    {"q": "why does a belt warn long before it actually fails?",
     "file": "docs/reference/maintenance/README.md", "mode": "sem"},
    {"q": "how are cookies checked for colour defects?",
     "file": "docs/reference/dashboard/vision.md", "mode": "sem"},
    {"q": "where do the spoken answers come from?",
     "file": "docs/reference/copilot/speech-pipeline.md", "mode": "sem"},
    {"q": "what keeps two visitors' data apart?",
     "file": "docs/reference/operations/database.md", "mode": "sem"},
    {"q": "how is the factory's carbon footprint computed per cookie?",
     "file": "docs/reference/dashboard/carbon.md", "mode": "sem"},
    {"q": "what happens when the high-bay crane picks a mould?",
     "file": "docs/reference/machines/warehouse.md", "mode": "sem"},
    {"q": "how is the simulation's PLC program verified?",
     "file": "docs/reference/plc/07-verification.md", "mode": "sem"},
    {"q": "what is the difference between the real factory and this twin?",
     "file": "docs/reference/factory/factory-vs-twin.md", "mode": "sem"},
    # added with the docs reorganisation (2026-11-09): the newly indexed areas (PLC, operations,
    # architecture, process, vision), and questions with more than one right document ("files")
    {"q": "what does the PLC do when the emergency stop is pressed?",
     "files": [
         "docs/reference/plc/06-safety.md",
         "docs/reference/twin/panels/safety-security.md",
     ], "mode": "lex"},
    {"q": "how is a change promoted from staging to the live service?",
     "files": ["docs/reference/operations/staging.md"], "mode": "lex"},
    {"q": "what error code does the API return when the daily question budget is spent?",
     "files": ["docs/reference/architecture/error-codes.md"], "mode": "lex"},
    {"q": "which RevPi DIO terminal does each signal land on?",
     "files": ["docs/reference/architecture/electrics.md"], "mode": "lex"},
    {"q": "how does the sorting line decide which bay a cookie goes to?",
     "files": ["docs/reference/machines/sorting-line.md"], "mode": "lex"},
    {"q": "what does the normal-behaviour model in predictive maintenance do?",
     "files": ["docs/reference/maintenance/pdm-pipeline.md"], "mode": "lex"},
    {"q": "why does the inspection camera use a telecentric view?",
     "files": ["docs/reference/vision/README.md"], "mode": "lex"},
    {"q": "what are the three policies for ending a bake?",
     "files": [
         "docs/reference/process/README.md",
         "docs/reference/dashboard/process.md",
     ], "mode": "lex"},
    {"q": "what parts and connections does the edge computer have?",
     "files": ["docs/reference/machines/edge-computer.md"], "mode": "lex"},
    {"q": "how does the cross-encoder reranker on Cloud Run fit the trial budget?",
     "files": ["docs/reference/operations/gcp-reranker.md"], "mode": "lex"},
    {"q": "which providers does text to speech use, in order?",
     "files": ["docs/reference/copilot/speech-pipeline.md"], "mode": "lex"},
    {"q": "what are the drag chains on the moving axes?",
     "files": ["docs/reference/twin/panels/remote-io.md"], "mode": "lex"},
    {"q": "what stops someone from moving an axis by hand into a collision?",
     "files": ["docs/reference/plc/06-safety.md"], "mode": "sem"},
    {"q": "how can I try a change privately before the public site gets it?",
     "files": ["docs/reference/operations/staging.md"], "mode": "sem"},
    {"q": "what happens to the factory's electricity on a sunny day?",
     "files": ["docs/reference/dashboard/energy.md"], "mode": "sem"},
    {"q": "can a learning scheduler beat the PLC's order without getting stuck?",
     "files": ["docs/reference/dashboard/scheduler.md"], "mode": "sem"},
    {"q": "how many cookie slots are in the rack?",
     "files": ["docs/reference/machines/warehouse.md"], "mode": "sem"},
    {"q": "who decides whether a question is answered from the documents or the web?",
     "files": [
         "docs/reference/copilot/README.md",
         "docs/reference/architecture/rag-system-design.md",
     ], "mode": "sem"},
    {"q": "what does one cookie go through from the order to its bay?",
     "files": [
         "docs/reference/factory/production-cycle.md",
         "docs/reference/twin/overview.md",
     ], "mode": "sem"},
    {"q": "how does the answer pipeline keep from looping forever?",
     "files": ["docs/reference/architecture/agent-graph.md"], "mode": "sem"},
    {"q": "what does the browser get back when a request fails?",
     "files": ["docs/reference/architecture/error-codes.md"], "mode": "sem"},
    {"q": "on real hardware, which messages would feed the dashboard?",
     "files": ["docs/reference/dashboard/data.md"], "mode": "sem"},
    {"q": "how was the cell made quicker without touching its hardware?",
     "files": ["docs/reference/dashboard/throughput.md"], "mode": "sem"},
    {"q": "how does the twin see a part failing before it breaks?",
     "files": [
         "docs/reference/maintenance/pdm-pipeline.md",
         "docs/reference/maintenance/README.md",
         "docs/reference/dashboard/ai.md",
     ], "mode": "sem"},
]

KS = (1, 3, 5, 8)
TOP_K = 10  # ranks are computed over the top 10; MRR and nDCG use that window


def expected(g: dict) -> list[str]:
    """The files a question's answer may come from: its "files", or its one "file"."""
    return list(g.get("files") or [g["file"]])


def _ndcg(rel: list[int]) -> float:
    """nDCG@len(rel) with binary relevance: any passage of an expected file is relevant."""
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
    store = vectors.get_store()
    backend = "bm25" if store is None else getattr(store, "name", "sqlite")
    embedder = "none" if store is None else store.embedder.name
    questions = []
    t0 = time.time()
    for g in GOLDEN:
        verdict = None
        if ask:
            j = crag.correct(g["q"], None, ask, k=top_k)
            hits, verdict = j.hits, j.verdict
        else:
            hits = vectors.hybrid_search(g["q"], top_k=top_k)
        want = expected(g)
        ranks = [i + 1 for i, h in enumerate(hits) if h["passage"].file in want]
        rel = [1 if h["passage"].file in want else 0 for h in hits]
        questions.append(
            {
                "q": g["q"],
                "file": want[0],
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
        from services.api.agent import chat as chat_engine
        from services.api.security import security

        chat = chat_engine.Chat(security.Settings.from_env())
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
