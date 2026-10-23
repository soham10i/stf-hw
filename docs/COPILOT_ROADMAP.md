# Copilot roadmap: closing the gap to industrial grade

Where the copilot stands after the pgvector integration (2026-10-23) and what comes next,
in dependency order. Each phase lists what it unblocks and how it is verified. The
industrial-deficit analysis behind this list is in the session log and
`docs/architecture/RAG_SYSTEM_DESIGN.md`.

**Done this phase (baseline for everything below):**

- pgvector backend in Supabase Postgres (HNSW ANN, metadata columns, RPC seam) with
  SQLite fallback - `vectors.py`, migration `20261023023000_stf_kb_vectors.sql`, live:
  920 passages indexed, ANN serving queries.
- Hybrid-aware routing: `orchestrate.decide` reads vector cosines as well as BM25, so
  meaning-matches route to docs instead of the web (external/standards questions still
  route to the web first).
- `dotenv` moved to `envcfg.py` so every backend module (including vectors) reads the
  same merged env as the app.
- Full suite green (418 tests), incl. pgvector tests on a scripted PostgREST transport.

## Phase B - answer precision (next)

1. **Cross-encoder reranker.** Re-score the fused top candidates with a model that reads
   query and passage together. **Seam built 2026-10-23** (`vectors.py: Reranker`,
   STF_RERANKER_URL-gated, fused order stands on any failure; local validation with a
   placeholder model: semantic MRR +0.10, lexical −0.06 - the gate, not hope, decides
   shipping). **Deployment**: TEI + bge-reranker-v2-m3 on Cloud Run, scale-to-zero on
   trial credits - `deploy/reranker.sh`, plan and continuity in `docs/GCP_RERANKER.md`;
   pending the owner's gcloud login.
2. **Retrieval eval harness in CI.** Golden set of 16 question→passage pairs (8 lexical / 8
   paraphrase) in `services/api/eval_retrieval.py`; hit@1/3/5/8, MRR and nDCG@10, reported
   per mode so a BM25 regression and an embedding regression are told apart. `make
   eval-retrieval` runs it against whatever backend/embedder is configured; pytest floors
   (tests/test_retrieval_eval.py) guard the baseline in CI. **Built 2026-10-23** — baseline
   on the hash embedder: hit@8 0.875, MRR 0.64; the lexical MISSes it surfaced are the
   reranker's target list.
3. **Query rewriting.** Spell-fix plus vocabulary expansion from the page the question
   was asked on; HyDE for the vector side when BM25 is empty.

## Phase C - context engineering

4. **Continuous ingestion.** The kb is a batch snapshot; add an incremental path:
   shift reports, alarm logs, validation notes enter `kb_vectors` through `stf_kb_insert`
   with `meta` tags (source type, date) instead of waiting for `make copilot`. The
   `meta` jsonb column and the RPC seam already exist for this.
5. **ISA-95 asset metadata.** Tag passages and telemetry by asset hierarchy
   (line → cell → equipment → sensor); retrieval filters by the page/equipment the user
   is looking at - the twin's navigation becomes a retrieval filter for free.
6. **Token-budget context packing.** Replace fixed passage counts with budget-aware
   packing (importance-ranked, MMR diversity, per-section caps), driven by the same
   tier system token_budget.py already exposes.

## Phase D - the STF agent

7. **Actuation tool tier.** `scenario_run` (start/stop/fast-forward), `order_submit`
   (12-order queue rule), `twin_navigate` (voice "show me the oven"), `alarm_ack` - all
   behind the existing `command_guard` (operator token), all advisory-first. This
   completes the original ElevenLabs voice-navigation vision on the free ladder.
8. **Planner-executor-critic state machine.** Generalize the deep-research planner into a
   per-request DAG (planner → tools → verify.py → critic → respond.py), replacing the
   linear MAX_ROUNDS loop; LangGraph-style but native to this codebase.
9. **Health-aware routing policy.** Persist provider success-rate EMA, p95 latency and
   unverified-rate in the store; the ladder becomes a weighted choice under privacy /
   latency / cost constraints. Deterministic orchestrate.py rules stay on top as the
   safety layer.

## Phase E - operations and trust

10. **Request tracing.** One trace id per question carrying route → passages → provider
    → verify outcome; visible in the dashboard's copilot tab (the "thinking" drawer is
    already there) and logged to Supabase app_logs.
11. **Online feedback capture.** Thumbs + "wrong number" per answer; feeds the golden
    sets (B2) and the routing policy (D9).
12. **Copilot eval as a CI gate.** `eval_copilot.py` thresholds (faithfulness, held-out
    regression) run on every push; shadow-mode for router changes.

## Phase F - industrial shape (portfolio capstone)

13. **OT data fabric in simulation.** OPC UA / MQTT (Sparkplug B) adapter over the twin's
    live socket, historian tables in Supabase, time-series summaries as retrievable
    passages - "what happened at 14:32?" becomes answerable, and the RAG story becomes
    genuinely Industry 4.0.
14. **Edge/offline story.** Document and demo the local-first mode: Ollama + SQLite
    vectors + local STT/TTS, so the copilot keeps working with the cloud fully offline.
15. **Standards mapping.** Map `oee_bottleneck`/`alarm_lookup` outputs to ISO 22400 and
    ISA-18.2 language in the docs the copilot cites - cheap, and reads as plant literacy.

Ordering rationale: B sharpens every answer the system gives (highest leverage per
dollar - all free-tier); C makes the context fresh and filterable (prerequisite for
agent trust); D turns the copilot from an oracle into an operator; E makes it
observable and self-improving; F is the industrial narrative that makes the portfolio
distinct.
