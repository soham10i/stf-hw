# The reranker on Google Cloud: 90-day credit plan and continuity

The copilot's retrieval gained a cross-encoder reranker seam (`services/api/vectors.py`,
`Reranker`): after BM25+vector fusion, the top candidates are re-scored by a model that
reads the query and each passage *together*. It is strictly optional - unset
`STF_RERANKER_URL` and every code path is exactly the previous behavior, so the plan
below spends credits only when it helps, and a outage degrades instead of breaking.

## Architecture

```
dashboard question
   -> stf-live (Cloud Run): hybrid_search (BM25 + pgvector HNSW, RRF fusion)
   -> stf-reranker (Cloud Run): POST /rerank {query, texts}  (bge-reranker-large, TEI, CPU)
   -> re-ordered passages -> model -> verified answer
```

- `stf-reranker` runs the public `text-embeddings-inference` CPU image with
  `--model-id BAAI/bge-reranker-large`, 2 vCPU / 8 GiB, concurrency 4, scale to zero.
  (v2-m3 was the first choice but its fp32 CPU footprint is ~9 GiB even before the
  warmup batch - it OOMed 4 GiB and 8 GiB alike. `bge-reranker-large` fits 8 GiB with
  headroom and still re-ranks well; `--cpu 2` caps memory at 8 GiB on Cloud Run.)
- Same region as `stf-live` (`europe-west1`): no cross-region egress, one TLS hop.
- A startup TCP probe (60 s delay, 30 × 10 s) covers the cold-start model download so
  the deploy gate does not kill a healthy-but-slow first revision.
- The API's `Reranker` client times out at 120 s (`STF_RERANKER_TIMEOUT_S` overrides) so
  the first call after idle can wait out a cold start (~60-105 s model fetch); warm calls
  answer in ~1 s. It takes 3 consecutive failures to disable the reranker for the
  process - a single slow cold start never silently turns it off for good. The fused
  order always stands.

## Why this fits the trial budget

| Choice | Cost driver | Trial math |
|---|---|---|
| `--min-instances 0` (scale to zero) | the only real lever | A demo day's reranks (each ~1-2 s of 2 vCPU, 12 texts) total minutes of CPU. Across 90 days this is single-digit dollars of the $300 - the credits' bulk still goes to `stf-live` itself and the Gemini Cloud lane. |
| `--cpu-boost` + `--timeout 300` | cold-start model download | First request after idle pays a ~60-90 s model fetch; instances linger ~15 min warm. Acceptable for a demo; the chat already streams, so the wait hides in the thinking drawer. |
| Max 2 instances, concurrency 4 | burst ceiling | A crawler cannot spin up a fleet; worst case is 2 × 2 vCPU while it lasts. |
| Not `--min-instances 1` | always-on cost | Would be ~$35-45/month (~$100-135 of the trial over 90 days) to avoid a rare cold start. Wrong trade during the trial; revisit after day 91 if the demo gets real traffic. |

## Execution

1. **Deploy the reranker** (needs `gcloud` logged in; the API's `run.googleapis.com`
   is already enabled from the `stf-live` deploy):
   ```bash
   ./deploy/reranker.sh            # or: make reranker-deploy
   ```
2. **Point the API at it**: Cloud Run console → `stf-live` → *Edit* → *Add variable*:
   `STF_RERANKER_URL=https://stf-reranker-…-uc.a.run.app` (the script prints the exact
   value and URL). Redeploy `stf-live` or set it before the next revision.
3. **Verify with the acceptance gate** (from any machine with the repo):
   ```bash
   STF_RERANKER_URL=<url> make eval-retrieval
   ```
   Ship the reranker only if the golden set improves - the harness separates the
   lexical and paraphrase halves, so a model that helps one and hurts the other is
   visible, not averaged away. **Deployed-model result (2026-10-23, bge-reranker-large,
   hash embedder, pgvector): paraphrase half improved a lot - hit@3 0.875 → 1.0,
   MRR 0.604 → 0.771, nDCG 0.693 → 0.795; overall nDCG 0.689 → 0.727, hit@5
   0.812 → 0.938. Lexical half dipped (MRR 0.681 → 0.535): the cross-encoder
   re-orders keyword-exact matches it finds less "about" the query. Net: keep it -
   users ask paraphrase questions, and the truncated 800-char candidate text is the
   lexical limiter, not the model. A lexical-guard (skip rerank when BM25 exact-match
   confidence is very high) is a candidate refinement.**
4. **Optional hardening** (before real traffic): `--no-allow-unauthenticated` + a
   service-account-invoker binding so only `stf-live` can call it; add a shared header
   in `Reranker.scores` if you want defense in depth. During the trial the obscured URL
   plus scale-to-zero is a reasonable risk posture.

## Continuity: day 91 and beyond

- **Cost after the trial**: at demo traffic, scale-to-zero Cloud Run stays inside the
  always-free allowance (2 M requests, 180k vCPU-s, 360k GiB-s monthly) - expected bill
  ≈ $0 even with credits gone. The first month that exceeds it is a good problem: it
  means real users, and `--min-instances 1` becomes worth it.
- **Cheapest fallback**: unset `STF_RERANKER_URL` on `stf-live` - retrieval returns to
  the fused order with zero code change and zero cost.
- **Migration paths if credits force a move**: the client speaks the TEI `/rerank`
  protocol, so any replacement needs only the same endpoint - Azure Container Apps on
  the student credit, a Fly.io machine, or `kimi-code/rerank_server.py` (local
  sentence-transformers stand-in) for demos on the laptop.
- **What keeps working no matter what**: pgvector/SQLite hybrid retrieval, the routing,
  the fallback ladder. The reranker is precision icing, never load-bearing.

## What is needed to keep this going

| Need | Who | Status |
|---|---|---|
| `gcloud` CLI installed and logged in | owner | **done** 2026-10-23 (`smart-tabletop-factory-512013`, `europe-west1`) |
| `stf-reranker` deployed and smoke-tested | done | **live**: `https://stf-reranker-g6jrc6bpwq-ew.a.run.app` (revision stf-reranker-00003, bge-reranker-large, 8 GiB) |
| `STF_RERANKER_URL` set on `stf-live` | owner, one console field | **pending - the only blocker**; value above |
| Supabase `kb_vectors` migration | done | applied 2026-10-23 (shared project) |
| Acceptance-gate run against the deployed URL | done | reranked metrics recorded above |
