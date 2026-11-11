# BUILD BRIEF — NEXUS Agentic Runtime (handoff for an AI coding agent)

You are building **NEXUS**, a reusable agentic control & assistance runtime, as a fresh
repository. Read `ARCHITECTURE.md` (same folder) first — it is the source of truth for
design intent. This brief is your execution contract.

## 0. Hard constraints (non-negotiable)

1. **Never run `git commit` or `git push`.** All work stays as an uncommitted working
   tree for human review.
2. **License-clean only:** Apache-2.0/MIT code and dependencies; no Coqui/XTTS-style
   non-commercial weights anywhere in the repo; no ripped or unlicensed voice/model data.
3. **Offline-capable dev stack:** after initial downloads, `docker compose up` must run
   with no external API keys set (local LLM via Ollama, local TTS via Kokoro).
4. **Every public number must come from a runnable test or eval.** No placeholder metrics
   in docs — mark unmeasured values as `TODO(measure)`.
5. **Python 3.12+, ruff-clean (`ruff check` passes on all touched files), pytest for
   everything.** Type hints on all public interfaces.
6. Keep it boring: FastAPI, pydantic v2, SQLModel/pgvector, httpx. No LangChain, no
   agent frameworks, no event buses.

## 1. Repository bootstrap

Create `nexus/` with this layout (see ARCHITECTURE.md §8). Initialize git, make the
initial commit (this is the ONLY commit you are allowed to make — it is the scaffold;
everything after stays uncommitted):

```
core/        # kernel: actions, gate, audit, router, memory
nexusd/      # FastAPI service (REST + WebSocket)
sdk/         # nexus-client python package
packs/stf/   # STF domain pack (actions.yaml, binding.py, corpus/, evals/)
evals/       # harness + red-team suites
deploy/      # Dockerfile, compose.yml, cloudrun.yaml
docs/        # ARCHITECTURE.md (copy), ADRs
```

`pyproject.toml` at root: single package, `[tool.ruff]` config, pytest config with
`addopts = -q`.

## 2. Build order — phases with acceptance gates

Do not proceed past a phase until its acceptance gate passes. Run commands from repo root.

### Phase 0 — Kernel skeleton (target: ~1 week)

1. `core/actions.py` — pydantic models: `ActionSpec` (id, pack, risk, preconditions
   as a tiny DSL, effects, params JSON-schema, approval, sandbox), `WorldState`
   (typed key-value store with atomic compare-and-set), `ActionProposal`, `GateDecision`
   (ALLOW / DENY(reasons) / NEEDS_APPROVAL / NEEDS_SIM), `ExecutionRecord`.
2. `core/gate.py` — `evaluate(proposal, world_state)`: schema-validate params;
   evaluate preconditions deterministically; route by risk (low→execute, medium→execute+
   log, high→NEEDS_APPROVAL, critical→always NEEDS_APPROVAL); invoke sandbox hook if
   declared. < 20 ms per decision excluding sandbox — add a perf test asserting this.
3. `core/audit.py` — append-only log; each entry = `{seq, prev_hash, entry_sha256,
   payload, ts}`; `verify_chain()` returns bool. Tamper test: flip one byte in the
   store, `verify_chain()` must fail.
4. `core/echo pack` — `packs/echo/` with one action `echo.say` (risk low, binding writes
   to stdout) proving the full lifecycle end-to-end.
5. **Acceptance:** `pytest` green; a demo script `scripts/demo_lifecycle.py` shows
   propose→gate→execute→audit→verify_chain for one ALLOW, one DENY (bad precondition),
   one NEEDS_APPROVAL.

### Phase 1 — STF pack + service surface (~2 weeks)

1. `nexusd/` — FastAPI app: `POST /v1/sessions` (returns session id; sessions are fully
   isolated — test: two sessions, action in one invisible to the other), `POST /v1/plan`
   (accepts plan JSON, runs gate lifecycle, returns evidence pack), `GET /v1/audit`
   (paginated, chain-verified), `WS /v1/events` (gate decisions, approvals, executions).
2. `sdk/` — `nexus-client`: `Client(base_url, session_key)` with `plan()`, `approve()`,
   `audit()`, asyncio support. STF's repo will use only this surface.
3. `packs/stf/` — bind the STF factory sim (provided as a python module path in env
   `STF_SIM_MODULE`): actions `order.place`, `oven.set_zone_temp` (high risk, approval
   required), `conveyor.set_speed` (medium), `vgr.sweep_home` (low). Sandbox = the sim's
   step function: run 30 virtual seconds, assert no invariant violation (12-cookie rule,
   zone temp ceilings). Red-team evals: 10 seeded unsafe prompts/must-deny proposals
   (e.g., set_zone_temp above ceiling, place order with empty raw storage).
4. `core/router.py` — provider-agnostic `generate()` with Gemini, Groq, Ollama backends;
   per-provider cooldown on 429 (parse retry-after, cap at 60 s); structured-output
   enforcement via JSON-schema retry (max 2 retries); every routing decision appended to
   audit. Failover test: mock provider A raising 429, assert provider B answers and the
   user-visible result carries a failover note.
5. **Acceptance:** the demo from Phase 0 now runs over HTTP; STF pack evals block 100%
   of seeded unsafe proposals in CI (`pytest evals/`); session isolation test green.

### Phase 2 — Voice + memory (~1 week)

1. `core/voice.py` — `TTSEngine` protocol (`synth(text, preset) -> wav bytes`);
   `KokoroEngine` (offline; presets loaded from a voice_card.json exactly as produced by
   the STF Voice Lab notebook: blend string, speed, pedalboard chain) and
   `ElevenLabsEngine` (streaming; raises unless `ELEVENLABS_API_KEY` set). Per-agent
   preset mapping lives in config.
2. `core/memory.py` — per-session append-only episode log (context transfer between
   models mid-session: test that session state survives an enforced provider switch);
   pgvector-backed RAG over pack corpora with NLI-verified answers and an explicit
   abstention path (`answer.confidence < threshold → "I don't know" + sources`).
3. **Acceptance:** offline voice smoke test produces a WAV with no network (monkeypatch
   socket to raise); memory test proves mid-session model migration keeps full context;
   RAG test: unanswerable question abstains rather than hallucinates.

### Phase 3 — Eval harness hardening + deploy (~1 week)

1. `evals/harness.py` — runs frozen scenario suites per pack, outputs a metrics JSON:
   blocked rate, abstention rate, median gate latency, seeded-defect catch rate.
   GitHub Action runs it on every PR.
2. `deploy/` — multi-stage Dockerfile (python:3.12-slim, non-root user, pinned deps
   hash), `compose.yml` (nexusd + postgres/pgvector + optional ollama sidecar),
   `cloudrun.yaml` (staging mirror, IAM-locked, `allUsers` absent by default).
3. Load-test at 20 concurrent sessions on the free tier; record p50/p95 latencies in
   `docs/PERF.md` as `TODO(measure)` → measured.
4. **Acceptance:** one-command `docker compose up` from a clean clone reaches a working
   `/healthz` and passes the Phase 1 HTTP demo offline.

## 3. Definition of done (whole brief)

- `pytest` green across the repo; `ruff check` clean.
- Demo story works end-to-end: a user says (voice, local) "set zone two to 240 degrees"
  → LLM proposes `oven.set_zone_temp` → gate NEEDS_APPROVAL → user approves in UI →
  sim executes → evidence pack + audit entry returned, spoken confirmation in the
  configured preset. This demo is the portfolio video.
- Docs updated: every SLO in ARCHITECTURE.md §9 is either measured (with the command
  that produced it) or marked `TODO(measure)`.

## 4. Integration order after the core lands

1. **STF (first):** replace its ad-hoc copilot loop with `nexus-client`; the verified-agent
   demo replaces the current chat-only copilot. STF keeps its repo; only a thin adapter
   changes.
2. **Wind PdM:** new pack over the existing turbine-telemetry + XGBoost work; actions
   are read-only/schedule-class (no actuation) until a sim exists.
3. **Scene understanding:** vision pack; start read-only (annotate, escalate) — the gate
   pattern is identical even when the sensor is a camera.

## 5. Report-back format

When finished (or blocked), produce: (a) list of what passed its acceptance gate,
(b) `TODO(measure)` items remaining, (c) any contract in ARCHITECTURE.md you had to
change and why (changing a contract is allowed; silently diverging is not).
