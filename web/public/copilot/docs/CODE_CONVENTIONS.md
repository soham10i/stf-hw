# Code conventions

How this codebase is named and structured, so any reader (or contributor) can predict
where a thing lives and what it is called. Conventions below describe what the code
*actually does* — keep new code inside these rails.

## Layout

```
services/api/     the FastAPI backend (Python 3.11+, stdlib-first; deps: fastapi, pydantic, numpy)
  app.py          HTTP surface: routes, middleware, wiring only - no business logic
  chat.py         the copilot engine (routing, providers, tool loop, verification)
  tools.py        the twin's tool declarations and implementations (model-callable)
  vectors.py      hybrid retrieval (BM25 + pgvector), the Reranker client
  grounding.py    the BM25 index over docs/
  orchestrate.py  route planner (docs / web / deep research) from hybrid signals
  tts.py / stt    voice pipeline: provider ladder (ElevenLabs > Gemini > Groq > local say)
  guests.py       per-visitor identity (HMAC cookies) and the document-store protocol
  guests backends guests.py (Supabase), store.py (protocol), usage.py (counters)
  security.py     Settings, CommandGuard, RateLimiter (token bucket)
  keepalive.py    kept-alive urllib connections (one per thread and host)
  notify.py       email/webhook notifications (armed only when configured)
  runtime.py      the factory simulation kernel's live adapter (orders, frames)
  livehub.py      websocket rooms for the live twin (role checks, byte budgets)
  captures.py     inspection-camera photo intake (validation, storage)
  visits.py       analytics: consent cookie, visit rows, batched log shipping
  netguard.py     SSRF guard: public-URL check + peer-checked connections
web/              the React + TypeScript dashboard (Vite)
stf-cad/          the factory's CAD/model sources (parameters, carbon model, vision mount)
tests/            pytest suite (unit); tests/perf is manual benchmarking
deploy/           one script per deployable unit (reranker.sh, staging.sh, promote.sh)
supabase/migrations/  SQL migrations, applied in timestamp order
docs/             architecture and operations documentation
```

Rule of thumb: **a module is named after the noun it owns** (`guests.py` owns the
guest lifecycle), and `app.py` stays a thin shell over those modules.

## Naming

| Kind | Convention | Examples |
|---|---|---|
| Modules / files | `snake_case`, one noun, no verbs | `guests.py`, `token_budget.py` |
| Classes | `CapWords`, a noun (never a verb) | `Reranker`, `TokenBudget`, `LiveHub` |
| Functions / methods | `snake_case`, a verb or verb phrase | `hybrid_search`, `build_groq_body`, `add_turn` |
| Boolean-returning functions | verb phrases that read as yes/no questions | `is_local`, `token_ok`, `search_ready`, `allowed` |
| Private members | leading underscore | `_req`, `_check_peer`, `_HTTPConnection` |
| Module constants | `UPPER_SNAKE` | `RERANK_POOL`, `TIMEOUT_S`, `MAX_ROOMS` |
| Units in names | a suffix carries the unit | `..._S` seconds, `..._MS` milliseconds, `..._BYTES`, `..._PER_S` |
| Singletons | module-level underscore + `get_*`/`reset_*` accessors | `_reranker`, `get_reranker()`, `reset_reranker()` |
| Environment knobs | `STF_*` prefix; provider keys keep their provider's name | `STF_RERANKER_URL`, `STF_VECTOR_BACKEND`, `GROQ_API_KEY` |
| Env flags | `0/1` strings, defaulting to on | `STF_TRACKING`, `STF_API_DOCS` |
| HTTP routes | resource nouns, kebab-free, versionless | `/chat`, `/vision/captures`, `/copilot/sessions/{sid}` |
| Error types | `str`-subclass exceptions named for the situation | `Unavailable`, `AllBusy` |
| Provider lanes | a short lowercase name carried by the class | `Lane(name="cloud")`, `Lane(name="studio")` |
| Guest/context vars | `bind`/`unbind`/`current` verbs on the owning module | `guests.bind()`, `G.current()` |

Type hints are mandatory on public signatures (`from __future__ import annotations`
at the top of every module keeps them cheap). Docstrings: every public class and
function carries one; the style is a single imperative sentence for simple members
and Google-style `Args:`/`Returns:` blocks where the contract is not obvious from
the signature.

## Design patterns in use (and where to follow them)

- **Protocol + duck-typed backends** — `Store` (usage.py), `CaptureStore`
  (captures.py), the guest DB classes: one protocol, Supabase and SQLite
  implementations chosen at runtime by `*_from_env(env)`. New backend = new class,
  no call-site changes.
- **Provider ladder / Chain of Responsibility** — TTS (`tts.py`), STT, LLM fallback
  (`chat.py`): an ordered list of providers, each `ready()` then `speak()`; the first
  that answers wins, `Unavailable` moves to the next. Rate-limit cooldowns
  (`out_until`) temporarily remove a rung.
- **Singleton behind accessors** — expensive or shared objects (`_reranker`,
  `_store`, the BM25 index) live module-private and are reached through
  `get_*()`/`reset_*()`; `reset_*` exists for tests.
- **Decorator / middleware** — FastAPI dependencies for cross-cutting checks:
  `Depends(command_guard)` on mutating routes, `@app.middleware("http")` for headers.
- **Token bucket** — `RateLimiter` and the per-connection/per-room budgets in
  `livehub.py` are one small pattern reused everywhere a burst must be tamed.
- **Adapter** — `runtime.py` adapts the simulation kernel's state to the wire frame
  shape; `keepalive.py` adapts `http.client` to urllib's interface.
- **Facade** — `Chat.ask` is the single entry the routes call; everything behind it
  (routing, retrieval, tools, providers, verification, budgeting) is hidden.
- **Builder helpers** — `build_groq_body`, `build_ollama_body` keep request-shape
  knowledge next to the provider, not in the engine.
- **Guard / fail-safe defaults** — every external call has a timeout and a fallback
  that leaves the system working: retrieval without the reranker, chat without the
  database (unkept guests), TTS without any cloud key (`local say`).

## Comments

Comments explain *why*, never restate *what*. Accepted shapes: a short clause above
the line for a non-obvious constraint (`# Postgres' timestamptz wants ISO 8601...`),
or a trailing clause for units/edge cases (`# a crawler cannot fill the table`).
If a comment explains a whole block, it goes on its own line above the block.

## Testing

- One test file per module: `tests/test_<module>.py`; fixtures build fakes, never
  touch the network (monkeypatched `keepalive.urlopen` / provider `post`).
- New behavior ships with a test in the same change; the suite runs offline:
  `.venv/bin/python -m pytest -q --ignore=tests/perf`.
- Lint is part of CI: `ruff check packages services tests` must pass (line length
  100, rules E/F/I/UP/B).

## Versioning note

The API reports `"version": "4.0.0"` from `app.py`. Bump it with any promoted
deploy so the health endpoint tells you what is actually running.
