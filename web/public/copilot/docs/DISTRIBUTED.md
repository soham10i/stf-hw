# Distributed deployment — API and frontend, separately

The API is a standalone FastAPI app (`services/api/app.py`). The frontend
(`web/`) is a static Vite build. Today one Cloud Run service serves both
(`STF_WEB_DIST=/app/web/dist` mounts the built site at `/stf/`). This document
covers running them on separate origins, testing the API with Postman, and the
trade-offs of each topology.

## Topologies

### 1. All-in-one (current, default)

One container serves the API and the built site. Zero configuration; the guest
cookie, WebSockets and fetches are all same-origin. Use this unless there is a
specific reason to split.

### 2. Dev split (`make api` + `make web`)

Uvicorn on :8000, Vite on :5173. `web/vite.config.ts` proxies
`/layout /command /orders /health /chat /twin /copilot /guest /notify /vision/captures /ws`
to `127.0.0.1:8000`. This is for development only.

### 3. Portfolio reverse-proxy (recommended for a split)

Host the frontend on the portfolio origin and reverse-proxy the API paths from
the same origin, e.g. `https://portfolio.dev/stf-api/*` →
`https://stf-live-…run.app/*`. The browser stays same-origin, so the guest
cookie, CORS and WebSockets all keep working unchanged; set
`VITE_STF_API=/stf-api` (a path-prefixed same-origin base) — `api()` in
`web/src/shared/api.ts` concatenates it directly, so a relative base works.

### 4. Full cross-origin

Frontend on origin A, API on origin B, built with
`VITE_STF_API=https://api.example.com`. **Caveats:**

- The guest session cookie is `SameSite=Lax` (set in `services/api/guests.py`),
  so cross-site fetch/XHR will not carry it. Guest-bound features — orders,
  photos, visit tracking — then have no session identity.
- The copilot is unaffected: it identifies the user with the `X-STF-User`
  header, which is set explicitly on every copilot request.
- CORS must list the frontend origin (`STF_ALLOWED_ORIGINS`).
- Prefer topology 3 unless the API is truly public.

## The API base in the frontend

`web/src/shared/api.ts` exports `api(path)` and `apiWs(path)`. Every fetch and
WebSocket in the app goes through them. The base comes from the build-time env
var `VITE_STF_API`:

- unset → same-origin (topologies 1, 2, 3 with a path prefix)
- `VITE_STF_API=https://api.example.com` → absolute origin (topology 4)

It is build-time, not runtime: Vite replaces `import.meta.env.VITE_*` at
build, so changing the base means a rebuild. The CSP of a separately hosted
frontend is the hoster's concern; the built app's own CSP already allows
`ws:`/`wss:` in its live configuration.

## OpenAPI / Postman

- Interactive docs: `/docs` (Swagger UI) and `/openapi.json`, gated behind
  `STF_API_DOCS=1` (off on the public service).
- Export the contract: `make api-spec` writes `docs/openapi.json` — committed,
  so diffs show contract changes.
- Postman: *Import → file* `docs/openapi.json` (or *Import → link* pointing at
  `https://<host>/openapi.json`). Then point the collection's base URL at the
  API origin.

### Authenticating from Postman

- `stf-staging` (private, IAM-invoked): request
  `Authorization: Bearer $(gcloud auth print-identity-token)` per request
  (Postman: collection pre-request script that runs the gcloud CLI, or paste the
  token manually — it lives ~1 h).
- Operator routes (`POST /command`, `POST /notify/test`): also send
  `X-STF-Token: <STF_API_TOKEN>` unless calling from the operator's loopback
  machine. See `tests/test_api_security.py` for the exact guard matrix.
- The guest cookie (`GET /guest`) is issued automatically on first call; Postman
  stores and resends cookies by default, so subsequent calls carry the session.

## Environment variables

| Variable | Where | Effect |
|---|---|---|
| `STF_API_DOCS` | API | `1` enables `/docs` + `/openapi.json` |
| `STF_ALLOWED_ORIGINS` | API | CORS allow-list for cross-origin frontends |
| `VITE_STF_API` | web build | API origin the frontend calls (build-time) |
| `STF_WEB_DIST` | API | serve a built frontend at `/stf/` (unset = API-only mode) |
| `STF_API_TOKEN` | API | operator token for command routes |

## Contract tests

`tests/test_openapi.py` pins the contract: expected routes present, product
identity (`STF Digital Twin`), and JSON-serializability. Regenerate
`docs/openapi.json` with `make api-spec` when routes change.
