# Phase 0–1 implementation handoff

**Branch:** `feat/agentic-phase-0-1`

**Date:** 2026-10-27

**Status:** Phase 0 and the Phase 1 local foundations are implemented and tested. Cloud activation, paid evaluation, production promotion and git push have **not** been performed.

This is the implementation companion to `docs/plans/agentic-feasibility-report.md`. Phase 2 durable, exact-payload approvals are deliberately not included.

## 1. Delivered

### Phase 0 — safe, reproducible starting point

- Model-initiated writes are **frozen by default** with `STF_AGENT_ACTUATION=0` or unset.
- `order_submit`, `order_cancel`, `alarm_ack`, `recipe_adjust` and `twin_navigate` are omitted from model tool declarations while frozen.
- Direct calls to those tools are also rejected, including calls reached through rules routing; hiding declarations is not the only guard.
- Intent routing remains intact so a later approval workflow can recognise the request without executing it.
- The existing golden requests pass without rewriting their expected behaviour. Legacy write-guard tests opt in explicitly; ordinary tests exercise the freeze.
- `/chat/status` reports `actuation.agent_writes` so the freeze is observable.
- This switch governs agent tools, not the separate `/command` API. Staging therefore also forces `STF_API_TOKEN=""`.

### Phase 1 — Vertex, spend telemetry and evaluation readiness

- The existing Vertex lane now reports model identity as `vertex:<model>` and records model-specific token/cost telemetry.
- Gemini usage separates input, output and thinking tokens. Built-in list prices cover:
  - `gemini-3.8-flash`
  - `gemini-3.5-flash`
  - `gemini-3.1-pro-preview`
- `GEMINI_PRICING_JSON` can override/add USD-per-million-token prices. Unknown or incomplete Gemini pricing is marked **unpriced**, never silently treated as free.
- Per-request usage includes input/output tokens, estimated model cost, priced/unpriced calls and per-model breakdowns.
- Paid cloud calls and paid grounded searches share an application circuit breaker:
  - `GEMINI_CLOUD_USD_PER_DAY`, default `5`;
  - optional `GEMINI_CLOUD_USD_TOTAL`;
  - `GEMINI_CLOUD_BUDGET_START` and `GEMINI_CLOUD_BUDGET_DAYS` for the fixed pilot window.
- A configured pilot permits new paid calls only inside `[start, start + days)`. Daily spend resets by UTC day; the fixed pilot total does not reset inside the window.
- The circuit uses the existing shared usage backend when available, so restarts/additional instances do not intentionally reset its totals.
- When the paid circuit opens, Studio/Groq/other configured fallbacks and DuckDuckGo search remain available.
- Detailed chat status exposes estimated spend and circuit state without exposing credentials.
- Staging deployment now forces agent writes off, disables the command API token and keeps exported traces metadata-only. `STF_SESSION_SECRET` is carried through Secret Manager by staging and promotion scripts.
- `deploy/phase1_preflight.py` performs read-only project/API/Cloud Run/environment/IAM checks. Its optional `--live-chat` makes one intentionally paid request.
- `deploy/phase1_enable.sh` is an explicit owner-run staging activation script. It refuses to run without confirmation, a USD pilot cap, a start date and a mounted session secret. It does not target `stf-live`.
- `services/api/eval_copilot.py` now records requested/actual routes, search attempts/failures/sources, input/output tokens, cost, p50/p95 latency, engine, commit and cost basis.
- `services/api/eval_gate.py` compares identical question sets and fails on quality regression, excessive p95 latency, excessive estimated cost or unpriced calls.
- `tests/copilot_routes.json` adds representative chat/docs/web/deep/twin cases; it complements rather than replaces the 41-case quality suite.

## 2. Verification completed locally

| Check | Result |
|---|---:|
| Complete backend suite, excluding `tests/perf` | **578 passed** |
| Focused Phase 0–1 suite | **65 passed** |
| Ruff: `packages services tests deploy/phase1_preflight.py` | **Passed** |
| Shell syntax: staging, promote, Phase 1 activation | **Passed** |
| Python compilation: preflight, cost and evaluation modules | **Passed** |

The focused total is included in the complete total, not additional to it. No live Vertex/Flash/Pro benchmark has been run, so live quality, latency, IAM and credit readiness remain unverified.

## 3. Offline baselines

Both baselines used the graph engine, rules provider, frozen agent writes and hosted providers disabled. They are reproducible availability/quality baselines, not evidence of live web or model performance.

| Suite | Quality | Route/reliability failures | p50 | p95 | Model tokens | Estimated model cost |
|---|---:|---:|---:|---:|---:|---:|
| Representative routes | 3/5 | 2 | 0.1 s | 1.08 s | 0 | $0 |
| Full copilot suite | 37/41 | 0 | 0.1 s | 0.2 s | 0 | $0 |

Representative chat/docs/twin cases passed. Web/deep requests fell back to docs because no search writer was enabled, producing the two route failures. The full suite additionally reports tuning tools/facts/faithfulness at 29/29, required declines at 1/1, and held-out tools/facts/faithfulness at 8/12, 11/12 and 12/12 respectively.

Artifacts:

- `docs/history/baselines/phase0-rules.json`
- `docs/history/baselines/phase0-rules-full.json`

Reproduce the representative baseline with:

```bash
GEMINI_API_KEY= GEMINI_CLOUD_API_KEY= GEMINI_VERTEX_PROJECT= \
GROQ_API_KEY= UPB_AI_KEY= OPENAI_URL= OLLAMA_MODEL= \
STF_SCHOLAR=0 STF_DB=sqlite STF_DATA_DIR=.cache/phase0-data \
STF_AGENT_ACTUATION=0 STF_CRAG=off \
.venv/bin/python -m services.api.eval_copilot \
  --provider rules --cases tests/copilot_routes.json \
  --tag phase0-rules --output docs/history/baselines/phase0-rules.json --engine graph
```

Use the same environment without `--cases` and with the `phase0-rules-full` tag/output to reproduce the 41-case baseline.

## 4. Required from the owner before activation

1. **Confirm the real credit and pilot budget.** Check credit balance, expiry, billing currency and FX in Google Cloud Billing. Choose `PILOT_USD` in actual US dollars; do not assume a €250 credit equals $250.
2. **Create/mount a strong `STF_SESSION_SECRET`.** Store it in Secret Manager, grant the staging runtime service account access, and mount it on private `stf-staging` as `STF_SESSION_SECRET`. Do not paste the secret into chat or commit it. The activation script refuses to enable Vertex without it.
3. **Confirm IAM authority.** The owner must be able to enable `aiplatform.googleapis.com`, inspect project IAM, update Cloud Run and grant the actual staging runtime service account `roles/aiplatform.user`. API enablement alone does not prove the runtime identity can call Vertex.
4. **Configure billing budgets/alerts.** Set alerts at 50%, 80%, 90% and 100% of the approved pilot budget. Billing alerts do not stop spend. The application circuit stops new paid calls but an in-flight request can finish; neither is a billing-account hard cap.
5. **Optionally configure metadata-only tracing.** Provide an OTLP/HTTP endpoint through `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, or the existing Langfuse/Phoenix settings. Keep `STF_TRACE_CONTENT=0`; do not export question/answer content for this phase.
6. **Approve paid validation explicitly.** Only after the above checks should the owner run staging activation and the small live request/evaluations.

## 5. Activation sequence — owner-run

Review the scripts first. These commands change staging IAM/configuration or make paid calls; they were not run during implementation.

```bash
# Read-only inspection: APIs, staging config, runtime identity and IAM.
.venv/bin/python deploy/phase1_preflight.py \
  --project smart-tabletop-factory-512013

# Explicit PRIVATE STAGING activation. Replace <agreed-usd> with the approved number.
CONFIRM_PHASE1=1 PILOT_USD=<agreed-usd> BUDGET_START=2026-10-27 DAILY_USD=5 \
  ./deploy/phase1_enable.sh smart-tabletop-factory-512013

# One intentionally paid end-to-end Vertex request after credit/budget approval.
.venv/bin/python deploy/phase1_preflight.py \
  --project smart-tabletop-factory-512013 --live-chat
```

The activation script configures a Flash-first ladder, keeps `STF_AGENT_ACTUATION=0`, `STF_TRACE_CONTENT=0` and `STF_API_TOKEN=""`, and does not modify public `stf-live`.

## 6. Paid model evaluation — after activation

Run from an authenticated environment permitted to use the project's Vertex lane. Each command selects one model so reports are comparable. These calls are billable and were not run during implementation.

```bash
GEMINI_CLOUD_MODELS=gemini-3.8-flash \
.venv/bin/python -m services.api.eval_copilot --provider gemini \
  --cases tests/copilot_routes.json --tag phase1-gemini-3.8-flash \
  --output docs/history/baselines/phase1-gemini-3.8-flash.json --engine graph

GEMINI_CLOUD_MODELS=gemini-3.5-flash \
.venv/bin/python -m services.api.eval_copilot --provider gemini \
  --cases tests/copilot_routes.json --tag phase1-gemini-3.5-flash \
  --output docs/history/baselines/phase1-gemini-3.5-flash.json --engine graph

GEMINI_CLOUD_MODELS=gemini-3.1-pro-preview \
.venv/bin/python -m services.api.eval_copilot --provider gemini \
  --cases tests/copilot_routes.json --tag phase1-gemini-3.1-pro \
  --output docs/history/baselines/phase1-gemini-3.1-pro.json --engine graph
```

After the representative route runs, repeat without `--cases` for all 41 quality cases. Compare a candidate against the corresponding baseline, for example:

```bash
.venv/bin/python -m services.api.eval_gate \
  docs/history/baselines/phase0-rules.json \
  docs/history/baselines/phase1-gemini-3.8-flash.json \
  --max-quality-drop 0 --max-p95-s 90 --max-cost-usd 5 --max-unpriced 0
```

Model selection must use measured route quality, p95 latency and total cost—not model name alone. Prices are estimates and exclude grounding, infrastructure, tax and FX.

## 7. Rollback

No cloud rollback is currently needed because no cloud mutation was performed.

If staging activation is later unsatisfactory:

1. Keep `STF_AGENT_ACTUATION=0`; do not re-enable legacy agent writes as a rollback shortcut.
2. Disable the Vertex lane on staging by removing/unsetting `GEMINI_VERTEX_PROJECT`, allowing other configured providers to serve traffic.
3. Or route staging back to its previous Cloud Run revision:

```bash
gcloud run revisions list --service stf-staging \
  --project smart-tabletop-factory-512013 --region europe-west1

gcloud run services update-traffic stf-staging \
  --project smart-tabletop-factory-512013 --region europe-west1 \
  --to-revisions <previous-revision-name>=100
```

Production rollback is unnecessary unless a separate, explicit promotion is subsequently performed.

## 8. Explicitly out of scope

- Phase 2 durable approvals, exact-payload binding, approval persistence and replay protection.
- Enabling cloud APIs, changing IAM, mounting secrets or changing Cloud Run during this implementation.
- Paid live evaluation and claims about live model quality/latency.
- Public production deployment, git push, physical-hardware actuation and safety certification.
- The unrelated UI/docs edits already present in the working tree; they are preserved but not part of this implementation.
