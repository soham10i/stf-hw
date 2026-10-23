# The copilot's RAG: system design and loops

How the dashboard's copilot answers from documents, twin data and the web - what is built
today, the loops each request flows through, and the design rules that keep retrieval honest
as the system grows. Companion to the code (`services/api/grounding.py`, `vectors.py`,
`orchestrate.py`, `chat.py`, `respond.py`, `verify.py`, `source_policy.py`, `sessions.py`)
and the roadmap in `docs/COPILOT_ROADMAP.md`.

## 1. The pipeline as built

```
question
  │
  ├─ rules router (tools.route) ──► tool calls the question obviously needs  ─┐
  │                                                                            │
  ├─ orchestrator (orchestrate.decide) ──► mode: chat│twin│docs│web│deep      │
  │     signals: operator choice · greeting · explicit ask · data tools        │
  │     hybrid doc match: BM25 score + word cover + vector cosine (via)        │
  │                                                                            ▼
  ├─ retrieval ──► search_docs ──► hybrid_search ──► BM25 (grounding.py)       │
  │                                    │            + vector top-k (vectors.py)│
  │                                    └─► RRF fusion, cosine-margin admission │
  ├─ facts ──────► session context store (cross-model facts, dedup, bounded)   │
  ├─ generation ─► provider ladder gemini → groq → upb → openai → ollama       │
  │     (per-model cooldowns, two Gemini key lanes, tiered token budgets)      │
  ├─ shaping ────► respond.py style: greeting/quick/compare/steps/status/…     │
  ├─ verification ► verify.py: every number in the answer must appear in       │
  │     CONTEXT or a tool result; one rewrite on violation, else rules answer  │
  └─ answer ◄──── sources + cites + dashboard links, route + why included      │
```

Retrieval has two backends behind one interface (`vectors.py`), chosen by
`STF_VECTOR_BACKEND` (default `auto`):

- **pgvector** - the project's Supabase Postgres (`kb_vectors`, HNSW cosine index,
  `stf_match_kb`/`stf_kb_reset`/`stf_kb_insert` RPCs, migration
  `supabase/migrations/20261023023000_stf_kb_vectors.sql`). Rows carry passage metadata
  (`file`, `line`, `doc`, `path`, `meta` jsonb) - the seam for filtered retrieval and
  continuous ingestion. ANN search runs in Postgres; a missing RPC falls back to
  brute-force cosine on a locally cached matrix.
- **SQLite** - a local file (`vectors.sqlite`), same cache-key invalidation contract:
  rebuild only when the knowledge base or the embedder changes.

Every failure mode - no embedder, no passages, unreachable Supabase, missing table,
missing RPC - degrades one level (pgvector → SQLite → BM25-only), never to an error.
`auto` picks pgvector when `SUPABASE_URL` + a service key are configured and the table
answers; tests blank `SUPABASE_URL` so they always run on SQLite with the hash embedder.

The embedder is its own seam (`STF_EMBEDDER`): local MiniLM, an OpenAI-compatible
`/v1/embeddings` endpoint (TEI/vLLM on Azure Container Apps or Cloud Run), or a
zero-dependency feature-hash fallback that keeps tests and offline runs working.

### Why the router reads the hybrid index too

`orchestrate.decide` routes on the same hybrid signals retrieval produces
(`score`, `cover`, `vscore`, `via`), not on BM25 alone. A question whose *words* do not
match any passage but whose *meaning* does (cosine ≥ 0.72 against the best passage) is a
docs question - a BM25-only router sends those to the web, wasting search quota and
dropping the answer quality. External topics (standards, vendors) still win: the
explicit-web and external rules are weighed before the doc match, so "how do Siemens
PLCs handle safety?" never becomes a docs answer just because a passage is semantically
close.

## 2. The loops

### 2.1 Orchestration loop (per question)

```
plan = decide(question, called_tools)          # deterministic rules, always auditable
facts = run(called_tools)                      # the router's prefetch - free recall
context = session.facts + facts + doc_passages
for round in 1..MAX_ROUNDS(4):
    answer = model.generate(context, tool_declarations)
    if answer.calls_tools: facts += run(answer.tool_calls); continue
    break
bad = verify(answer, evidence=facts)           # numbers must exist in the evidence
if bad and rounds_left: rewrite once with correction(bad)
if no model answered: rules_answer()           # quoted documents, never an error page
```

Rules worth keeping when extending this: the route and its reasons travel with the
answer; a model never decides on its own to spend a web search; the deadline
(`DEADLINE_S`) hands over to the next provider so the user never waits on one model's
limit; the ladder order (gemini → groq → upb → openai → ollama) is the same locally and
deployed.

### 2.2 Retrieval loop (docs mode)

```
query ──► [optional] rewrite: spellfix, term expansion from the page's vocabulary
      ──► BM25 top-k  ──┐
      ──► vector top-k ─┴─► RRF fusion ──► cosine-margin admission for vector-only hits
      ──► (next phase: cross-encoder rerank of the top 20)
      ──► MMR diversity pass when k > 4
      ──► passages packed into CONTEXT under the token budget (depth.py tiers)
```

The admission rule keeps vectors from taking over: a vector-only candidate enters the
fused ranking only when it beats the best BM25 hit's cosine by a clear margin
(`COS_MARGIN`), or when BM25 found nothing (`VECTOR_ACCEPT`). RRF re-ranks BM25's set;
it does not replace it - BM25 stays the spine because its scores calibrate the router's
thresholds and the citations' meaning.

### 2.3 Deep-research loop (deep mode)

```
sub_questions = planner(question, budget)      # one small-model call, capped by token tier
for sq in sub_questions:                       # concurrency bounded by the search provider
    findings += web_search(sq)                 # sources graded (source_policy.py)
writeup = model.synthesize(findings + doc_passages)   # every claim linked to its page
verify(writeup, evidence=findings)
```

Budget tiers (`token_budget.py`: full → lean → minimal → spent) shrink context, thinking
budget and sub-search count as the day's tokens drain - the service degrades gradually
instead of failing at the quota wall. When every provider refuses a grounded call,
searches rest (`GEMINI_SEARCH_REST_S`) rather than hammering 429s.

### 2.4 Feedback loop (the next phase - see the roadmap)

```
answer shown ──► thumb up/down · "wrong number" reports
      ──► stored per session + answer id
      ──► weekly: false-fact cases become golden eval questions (tests/copilot_eval.json)
      ──► retrieval cases become question→passage pairs for the hit-rate harness
      ──► provider-level unverified-rate feeds the routing policy
```

The eval harness (`eval_copilot.py` for answers, `eval_retrieval.py` for the layer
below: golden question→passage pairs with hit@k, MRR, nDCG, lexical and paraphrase
halves reported apart) scores both layers against golden sets with held-out questions;
the pytest floors guard the baseline in CI, and the harness is the objective gate for
the reranker in the next phase.

## 3. Free-tier token strategy

The ladder is designed around free quotas, and the accounting keeps any single key away
from its wall:

- **Two Gemini lanes.** A Google Cloud key (billing on, trial credit) is asked before the
  AI Studio key, each with its own models, quotas and token budget - one lane's daily
  cap never starves the other.
- **Model pools with cooldowns.** `gemini_pool.py` keeps an ordered model list; a 429/503
  takes that model out for the RetryInfo delay (or a default), the next model answers.
  Chat and TTS have separate pools - a voice quota refusal never kills text answers.
- **Tiered degradation.** Budget tiers (per day, per minute, per guest) decide how much
  context, thinking and how many sub-searches a request may spend; at "spent", the
  request hands to the next provider rather than failing.
- **The free bench.** Groq (gpt-oss-120b/qwen), UPB's hosted chat, DuckDuckGo for the
  un-grounded web, Ollama locally - each covers a class of failure for zero cost.

## 4. Design rules that survive growth

1. **BM25 is the spine, vectors are the recall.** Citations, router thresholds and the
   margin rule all speak BM25; embeddings widen recall without taking over ranking.
2. **Every backend failure lands one level down, never on the user.** pgvector → SQLite
   → BM25; model limit → next model → rules answer with quoted documents.
3. **The route is decided by rules anyone can read**, before any model is asked, and the
   reasons ship with the answer.
4. **Numbers are verified against evidence** before the answer is shown; a correction
   rewrite replaces confident fabrication.
5. **Cache keys, not faith.** Both stores key their validity on (embedder, dims, passage
   ids); a docs change invalidates the index before a stale search can run.
6. **Metadata is the seam for scale.** Passages already carry file/line/doc/path; the
   `meta` jsonb column waits for doc-type, part and standard filters - ISA-95 asset
   tags come in through the same door.
