# Nexus RAG evaluation log (2026-11-09 to 2026-11-10)

The numbers behind [the RAG production plan](../plans/rag-production-plan.md), measured before and
after each stage. Unless a row says otherwise: hash embedder, SQLite vector store
(`STF_VECTOR_BACKEND=sqlite`, so no run writes to the deployed Supabase index), no reranker,
`STF_TRACKING=0`.

## Baseline (before any change)

| Evaluation | Result |
|---|---|
| `pytest -q --ignore=tests/perf` | all pass except the 22 cases of `tests/test_actions_flow.py`, which need `langgraph-checkpoint-sqlite` (not installed in the venv, not in `requirements-api.txt`) |
| Retrieval, 16 questions, no judge | hit@1 0.500, hit@3 0.812, hit@8 0.875, MRR 0.642, nDCG 0.689 (lexical MRR 0.681, paraphrase MRR 0.604) |
| Retrieval, 16 questions, Groq judge (CRAG) | MRR 0.629; only the first 7 questions were judged before Groq's free tier refused (the other 9 "unjudged"), so this is not comparable with the recorded 0.797 |
| Answers, 41 questions, rules provider | 37/41 pass; tuning tools 29/29, facts 29/29, faithful 29/29, declines 1/1; held-out tools 8/12, facts 11/12, faithful 12/12 |
| Browser-side router check (`copilot-check.ts`) | 30/30 tuning, 11/16 held-out |

The knowledge base the server read was stale: 920 passages from 69 files, while `docs/` held
newer text for several of them (`DATABASE.md` 204 lines against the index's 161).

## Stage 1: the docs corpus

`docs/` split into `reference/` (indexed), `plans/`, `history/` and `internal/`. Every reference
file has front matter, and the index holds exactly `docs/reference/` (80 documents, 1147
passages). Re-indexing alone dropped the 16-question MRR from 0.642 to 0.622, because the
fresher and larger corpus has more near-duplicates. Adding the document's `scope` to the BM25
heading path (a contextual chunk header, counted twice) recovered it. Before adopting it, it was
checked on 24 new questions it was not tuned on: MRR 0.659 → 0.700. The scope hurt on the vector
side, so it is used on BM25 only.

| Evaluation | Before | After |
|---|---|---|
| Retrieval, original 16 questions | hit@1 0.500, hit@3 0.812, hit@8 0.875, MRR 0.642, nDCG 0.689 | hit@1 0.625, hit@3 0.750, hit@8 0.875, MRR 0.719, nDCG 0.737 |
| Retrieval, all 40 questions (24 new; multi-file answers allowed) | - | hit@1 0.625, hit@3 0.725, hit@5 0.850, hit@8 0.900, MRR 0.708, nDCG 0.749 (lexical MRR 0.870, paraphrase 0.546) |
| Answers, rules provider, 41 questions | 37/41 | 37/41 (unchanged) |
| Browser router check | 30/30, 11/16 held-out | unchanged |

## Stages 2 and 3: the claim check, the policy and the quality record

The graph's verify node now runs the claim check, the policy and the citations; respond adds
`claims` and `quality` to the payload; run() keeps one row per request id. None of these numbers
moved:

| Evaluation | Result |
|---|---|
| Copilot suites (`test_chat`, `test_agent`, golden requests and trajectories, `test_toolloop`, `test_orchestrate`, `test_crag`, ...) | all pass; the recorded provider requests are unchanged |
| Answers, rules provider, 41 questions | 37/41 (unchanged) |

Two design changes came out of the golden tests. In the first version, a single claim the
lexical score missed sent the answer back to its model. That doubled the model calls on
canned answers that were, in fact, fine. Now an answer goes back only for an unbacked number, a
claim the judge rejected, or a majority of unsupported claims. Inline citations are also added
only for document and web passages, not tool readings: the facts list already names those.

## Stage 4: offline grounding evaluation and the gate

`eval_grounding.py` scores the claim check on 225 labelled claims (131 fabricated) in 183
answers. Twelve hand-written cases (`tests/grounding_eval.json`: 15 true paraphrases, 18
plausible fabrications) add to 40 generated ones (number changes, one-word swaps, sentences from
documents the evidence does not hold). Deterministic: no model, hash vectors.

| Detector (strict: flagged = "unsupported") | First version | + rare-word cap |
|---|---|---|
| Precision | 1.000 | 1.000 |
| Recall, all | 0.649 | 0.687 |
| Recall: changed numbers / foreign sentences / swaps / hand-written | 1.00 / 0.975 / 0.00 / 0.72 | 1.00 / 1.00 / 0.05 / 0.83 |
| Hand-written recall, lenient (flagged = unsupported or unsure) | 0.889 | 1.000 |
| False alarms on true claims (hand-written / all) | 0 / 0 | 0 / 0 |

The rare-word cap: a word that rare in the corpus which no evidence holds makes the claim
*unsure* (two make it *unsupported*). One-word swaps are now mostly *unsure*, which is exactly
the claim the optional judge (`STF_CLAIM_JUDGE`) settles; the lexical score alone cannot tell a
swapped part name from a paraphrase. The judge was not measured here because the free tier's
limits make a 183-answer run unreliable.

| Answer confidence (held-out odd questions, fitted on even) | Hand-set weights | Fitted |
|---|---|---|
| AUROC (every claim backed) | 0.950 | 0.949 |
| Brier score | 0.320 | 0.120 |
| Expected calibration error | 0.433 | 0.137 |

Groundedness alone ranks answers with AUROC 0.859; the confidence, 0.95. Features the offline set
cannot vary (citations, retrieval verdict) keep their hand-set weights. The committed
`confidence_weights.json` is fitted on all 183 answers.

The answer eval now carries each answer's grounding and six adversarial cases (a false premise,
an injected instruction, three out-of-world questions, a wrong premise about the sensor). Rules
provider, 47 questions:

| | Result |
|---|---|
| Tuning / held-out | 29/29 tools, facts, faithful, 1/1 declines / 8/12 tools, 11/12 facts, 12/12 faithful (unchanged) |
| Adversarial | facts 4/6, faithful 6/6, declines 2/4: the router sends the Mars question to the twin's tools and the warranty question to the documents, and with no model nothing declines them. This is the baseline a model run is gated against. |
| Grounding | groundedness 0.997 over 43 checked answers, hallucination rate 0.0, citation coverage 0.15 (rules answers are mostly tool readings, which are not cited inline) |

Before the lead-in fix, the rules answers showed a 0.128 hallucination rate. All six hits were
the fallback's own heading line ("What the documents say ...:"), so a sentence ending in a colon
is now a lead-in, not a claim.

The gate: `tests/test_rag_gate.py` recomputes retrieval and grounding (about 3 s) and compares
them with `tests/golden/rag_baseline.json` within per-metric tolerances. The baseline is MRR
0.708, hit@8 0.900, detector precision 1.0, recall 0.687, hand-written recall 0.833, no false
alarms, confidence AUROC 0.934, ECE 0.111. `eval_gate.compare` also fails a model run whose mean
groundedness drops by more than 0.05, whose hallucination rate rises by more than 0.05, or whose
citation coverage drops by more than 0.1.
