---
title: "Nexus RAG: production plan"
scope: How the copilot's retrieval-augmented answers are scored online, guarded against hallucination, gated offline, and fed from a clean documents corpus.
module: copilot
last_verified: 2026-11-09
---

# Nexus RAG: production plan

The copilot already retrieves well (hybrid BM25 + vectors, corrective retrieval in `rag/crag.py`)
and already refuses to show a number nothing backs (`agent/verify.py`). What it does not do yet is
know, per answer, how grounded the *words* are, say how sure it is, act on an unsupported claim,
or keep a record of any of it. This plan closes those gaps in four stages, measured before and
after each one.

Constraints that shape every choice: the models are Groq's free tier and Gemini/Vertex, so model
calls are rate-limited. Every new check is deterministic first; a model judge is optional, used
only where the deterministic check is unsure, capped per question, and never required for an
answer to be shown.

## Target architecture

```
question
  └─ route ── docs_rag (crag: judge, rewrite, verdict) ── answer (model ladder, tool loop)
                                                              │
                                                           verify
                     numbers  verify.py: every number backed by the evidence (unchanged)
                     claims   claims.py: every sentence-level claim scored against the
                              passages and tool results it could come from; a small-model
                              judge only for the claims the lexical score leaves unsure
                     policy   answer_policy.py: regenerate once with the evidence, then
                              strip / hedge / decline / pass; citations attached per claim
                              │
                           respond ── payload: answer, cites, claims, quality{...}
                              │
                           quality.py ── one score record per request id
                                          → storage/quality.py (SQLite | Supabase)
                                          → GET /copilot/quality (series + totals)
                                          → GET /copilot/quality/{request_id}
```

New modules, each named for the noun it owns:

| Module | Owns |
|---|---|
| `agent/claims.py` | splitting an answer into claims, the evidence passages, lexical support, the optional judge, citations per claim |
| `agent/confidence.py` | the calibrated answer confidence (logistic over the quality features; weights fitted offline) |
| `agent/answer_policy.py` | what happens to an unsupported claim |
| `agent/quality.py` | the per-answer score record built from the payload |
| `storage/quality.py` | persisting and summarising score records |
| `eval/eval_grounding.py` | the offline hallucination-detector and calibration evaluation |

## Hallucination policy

A claim is a sentence, bullet or table row of the answer that states something (greetings,
questions back, "I don't know" and headings are not claims). Each gets a support score in [0, 1]:
the IDF-weighted share of its content words found in its best evidence passage (or, at a small
discount, in all the evidence together). A number in it that is not backed (`verify.py`) makes it
unsupported. Above the high threshold it is *supported*, below the low one *unsupported*, between
them *unsure*. A rare word that no evidence holds (a swapped part, an invented name) caps it at
unsure, and two such words make it unsupported. Unsure claims go to the judge when one is free
(one call per verify pass, at most two per question).

| Situation | Action |
|---|---|
| An unbacked number, a claim the judge rejected, or more than half the claims unsupported; correction not yet spent | **regenerate** once: the model is told which numbers and claims are not backed and rewrites, citing its sources. One claim the words alone miss is not worth a second call on a rate-limited tier, so the steps below handle it. |
| After that: no factual claims (a greeting, a decline) | **pass** |
| Docs or twin route, groundedness below 0.34 and confidence below 0.3 | **decline**: say the documents do not cover it, list the closest passages |
| At most a third of the claims unsupported, each a whole sentence or bullet | **strip** those sentences; the note says how many were removed |
| Otherwise, any unsupported claim | **hedge**: keep the text, the note lists what is not backed |
| Web and deep research routes | **hedge** only: their evidence is a search summary, not the pages |
| The rules fallback (no model) | **pass**: it is built from the tools' own words; still scored |

Every supported claim from a document passage or web page that has no citation of its own gets
that passage's label appended (`[Machine: Oven > Temperatures]`, the form the dashboard already
renders as a numbered chip). So every answer from the documents carries citations to the
passages it uses. A tool's reading is not marked inline, because the answer's facts list already
names its source. Voice answers are left unmarked.

## Metrics

Online, per request id (no question or answer text is stored):

| Field | Meaning |
|---|---|
| `groundedness` | supported claims / checkable claims (unsure counts one half) |
| `citation_coverage` | checkable claims that carry a citation after the policy |
| `cited_by_model` | the same, counting only citations the model wrote |
| `citation_precision` | model citations whose passage really supports their claim |
| `numbers_unverified` | numbers `verify.py` could not back |
| `retrieval_verdict` | crag's verdict: relevant, relevant after rewrite, none, unjudged, or skipped |
| `action` | pass, strip, hedge, decline (`regenerated` says whether the correction was spent first) |
| `declined` | the answer says it does not know (or the policy declined) |
| `confidence` | calibrated probability that every claim is supported |
| `latency_ms`, `tokens`, `cost_usd`, `judge_calls` | what the answer cost |

Offline:

- **Retrieval** (`eval_retrieval.py`): hit@1/3/5/8, MRR, nDCG@10, now over a larger golden set
  with lexical, paraphrase and multi-document questions.
- **Grounding detector** (`eval_grounding.py`): claim-level precision and recall of
  "unsupported" on labelled answers (hand-written paraphrases, entity swaps, number changes,
  off-topic sentences), answer-level AUROC, and the confidence's Brier score and expected
  calibration error.
- **Answers** (`eval_copilot.py`): tools, facts, faithful numbers, route, declines, plus the
  answer's groundedness, citation coverage and policy action; adversarial (prompt injection,
  false premises) and out-of-scope questions added.
- **Gate** (`eval_gate.py`): fails on a drop in any of the above beyond its budget. A pytest test
  runs the deterministic evaluations (hash embedder, SQLite, rules provider) against the baseline
  committed in `tests/golden/rag_baseline.json`, so CI fails on a regression without a model key.

## Docs corpus

Today `docs/` mixes reference material, plans, dated reviews and notes for the bot, and the
indexer picks files by a hard-coded folder list. The target:

```
docs/
  README.md        the map of docs/ and the front-matter contract
  reference/       everything the copilot retrieves - and only that
    factory/  machines/  twin/  dashboard/  guide/  plc/  maintenance/
    vision/  process/  copilot/  operations/  architecture/
  plans/           roadmaps, blueprints, feasibility reports, this plan
  history/         dated reviews, validation reports, hand-overs, baselines, measurements
  internal/        notes for contributors (code conventions)
  assets/ images/  pictures the documents show
  gen/             generators of reference chapters (plc, maintenance)
  vendor/          the makers' documents (PDFs stay untracked)
```

Every file under `reference/` starts with front matter:

```
---
title: "Machine: Oven"
scope: One sentence on what the document covers.
module: oven
last_verified: 2026-11-09
---
```

`module` is one of a fixed set (factory, warehouse, gripper-robot, oven, sorting-line, machine,
plc, twin, dashboard, guide, maintenance, vision, process, copilot, operations, architecture).
`last_verified` starts as the file's last commit date and is bumped when someone checks the text
against the code; a generated chapter carries the date it was generated. `index: false` keeps a
reference file out of the index (the generated full dashboard guide, which repeats the per-page
documents). Headings are one H1 (the title) and no skipped levels, so every chunk's heading path
reads as a breadcrumb.

The indexer (`web/scripts/copilot-kb.ts`) indexes exactly `docs/reference/`, strips the front
matter, and gives every passage its document's `module`, `scope` and `last_verified`;
`grounding.Passage` carries them, the cites show them, the pgvector rows keep them in `meta`, and
`db_seed.py --kb` builds the vector index explicitly. A test checks the contract on every file.

## Stages

1. **Docs**: move with `git mv`, fix every link and path that named an old place, front matter,
   generators writing to the new places, re-index. Measure retrieval before and after.
2. **Claims and policy**: `claims.py`, `confidence.py`, `answer_policy.py`, wired into the
   graph's verify and respond nodes; tests.
3. **Online quality**: `quality.py`, `storage/quality.py`, a migration for the Supabase table,
   the two routes; tests.
4. **Offline evaluation**: the larger golden sets, `eval_grounding.py`, the extended
   `eval_copilot.py` and `eval_gate.py`, the CI baseline test.

## Results

The measured numbers for each stage are recorded in
[the evaluation log](../history/2026-11-09-rag-evaluation.md).
