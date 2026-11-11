# Security findings: review of 2026-10-22

Scope: the working tree on top of commit `5be748a` (including the uncommitted changes in
`services/api`, `web/` and the new modules `livehub.py`, `keepalive.py`, `gemini_search.py`,
`token_budget.py`, `mathspeak.py`, `fluent_math.py`). Method: code review of every new or changed
backend module and the web app's HTML sinks; `npm audit`; `pip-audit`; a Trivy scan of the
Docker image; Supabase's security advisor and bucket settings on the live project
(read-only); a fuzz of the TTS math parser. The live Cloud Run service was not attacked.

The fixes from the previous reviews (client IP, SSRF guard, body limits, docs off, CORS,
cookie secret) are present and the test suite passes (408 tests).

## Status (2026-10-22, second pass)

| # | Finding | Status |
|---|---|---|
| F1 | `/twin/live` without connection caps | **Fixed**: per-address (`STF_LIVE_PER_CLIENT`) and per-instance (`STF_MAX_LIVE_CLIENTS`) socket limits, at most 2 twins + 4 dashboards per room, a 1.5 MB/s relay budget per room |
| F2 | Rooms shared by IP address | **Fixed**: a socket without the signed guest cookie is refused (1008); the page fetches `GET /guest` first (`web/src/shared/liveLink.ts`); `fetchGuest` no longer caches a failure |
| F3 | 16 MiB WebSocket frames | **Fixed**: `--ws-max-size 400000` in the Dockerfile and `make api` |
| F4 | Spending caps in memory | **Fixed in code** (`services/api/usage.py`): question, token, search and spoken-answer counts are shared by every instance through the guests' database. **Needs** the migration `supabase/migrations/20261022120000_stf_usage_counters.sql` applied to the live project (until then: per instance, as before) and the Google Cloud quota + budget alert (owner) |
| F5 | Dev server Host check off; dev-tool advisories | **Fixed**: Host check on; tunnelling the dev server is opt-in (`STF_TUNNEL_DEV=1`, ngrok hosts only). vite 5.4.21 → 6.4.5, vitest 2.1.9 → 4.1.12, source-map-js → 1.2.2: OSV reports 0 advisories in 230 npm packages |
| F6 | Unpinned Python packages | **Fixed**: `requirements-api.in` → `requirements-api.txt` (exact versions + hashes, `pip-audit`: clean); the image installs with `--require-hashes` |
| F7 | Base image OS vulnerabilities | **Mitigated**: base images pinned by digest; refresh them on a schedule (none of the 44 has a Debian fix yet) |
| F8 | Status endpoints reveal budgets | **Fixed**: the per-minute window and per-question / per-guest allowances and the rejection counters moved to the operator-only `GET /admin/status`; the public status keeps what the copilot settings draw |
| F9 | KaTeX advisory | **Fixed**: katex 0.19.0; `trust: false` and `maxExpand` explicit |
| F10 | UPB key is a session token | **Owner**: remove `UPB_AI_KEY` from Cloud Run |
| F11 (new) | Operator token kept in `localStorage` | **Fixed**: kept in `sessionStorage` for the tab only; the old copy is removed |

Tests: 416 Python (8 new in `tests/test_livehub.py`), 165 web; the production and the standalone
Pages builds pass; the live link verified in a browser (twin and dashboard join one room under
the guest cookie). Not verified: the Docker image build with the hashed requirements and pinned
base images (Docker Desktop was not running).

Rules for the agent fixing these:
- Fix in the shared helper, not per route (`security.py`, `livehub.py`).
- Add a regression test per finding in `tests/test_api_security.py` (or a new
  `tests/test_livehub.py`) that fails before the fix and passes after.
- Run `PYTHONPATH=packages .venv/bin/python -m pytest tests -q` and `npm test` in `web/`.
- Do not commit; leave the changes for review.

---

## F1 (medium): the `/twin/live` WebSocket has no connection caps

**Where:** `services/api/app.py:720` (`twin_live`), `services/api/livehub.py:33-36`

**Problem:** `/ws` counts sockets against `STF_MAX_WS_CLIENTS` and `STF_WS_PER_CLIENT`;
`/twin/live` counts against neither. Its only limits are 200 rooms × 8 sockets, and a room is a
guest, which any client can mint (20 per address at once, then 1 a minute).

**Abuse:**
1. A few addresses mint ~200 guests and open one socket each: `MAX_ROOMS` is reached and
   every real visitor's live link is refused (`1013 room full`) - the dashboard/twin link is down.
2. Bandwidth amplification on a metered host: one "twin" socket may send 40 messages/s of up to
   320 kB (`RATE`, `MAX_MSG`), each relayed to up to 7 "dashboard" sockets in the same room =
   about 90 MB/s of egress per room, billed to the owner on Cloud Run.

**Fix:**
- Count `/twin/live` sockets in the same per-address and global counters as `/ws` (reuse
  `_ws_by_ip` / `ws_clients`, or a second `ClientCounter` with its own env limit).
- Lower the relay budget: a per-room byte budget (for example 2 MB/s across the room) on top of
  the per-connection message rate; drop over-budget messages.
- Allow at most 1 twin and 3 dashboards per room.
- Evict the oldest idle room instead of refusing new ones when `MAX_ROOMS` is reached, or key
  `MAX_ROOMS` per address.

**Verify:** a test opens more than the per-address limit and is refused with 1013; a test
sends 41 messages in one second and sees the 41st dropped; a test checks a second twin socket
in one room is refused.

## F2 (medium): visitors behind one address share a live-link room

**Where:** `services/api/app.py:732`
`room = guests.verify(websocket.cookies.get(G.COOKIE)) or f"ip:{ip}"`

**Problem:** without a valid guest cookie the room is the client's IP address. Everyone behind
one NAT (a university network, an office, a mobile carrier) who opens the twin before any
request that issues a cookie lands in the same room. The HTTP middleware that issues the cookie
does not run for WebSockets, so this is the normal first visit, not an edge case.

**Abuse:** a visitor on the same network sees another visitor's live twin state, inspection
results and camera frames, and can steer their twin (`simulate`, `defect` commands).

**Fix:** refuse `/twin/live` without a valid signed guest cookie (close with 1008 and let the
client call `GET /guest` first, which sets it), or have the web app call `GET /guest` before
it opens the socket. Never fall back to the address as a room key.

**Verify:** a test connects without a cookie and is closed with 1008; two clients with
different guest cookies but the same address never receive each other's messages.

## F3 (medium): WebSocket frames up to 16 MiB are read before any size check

**Where:** `Dockerfile:36` (uvicorn command), `app.py` `/ws` (`WS_MAX_MSG = 1024`) and
`/twin/live` (`LIVE_MAX_MSG`)

**Problem:** the size checks run after `receive_text()` returns, and uvicorn's default
`--ws-max-size` is 16 MiB, so each socket can make the server hold a 16 MiB frame in memory.
With dozens of sockets (see F1) this exhausts a 1 GiB Cloud Run instance.

**Fix:** start uvicorn with `--ws-max-size 400000` (just above `livehub.MAX_MSG`) in the
Dockerfile and in the `Makefile`'s `api` target. Keep the per-route checks.

**Verify:** a test sends a 1 MB frame to `/twin/live` and the connection closes without the
server buffering it (status 1009).

## F4 (medium): spending caps for the billed Gemini key live in process memory

**Where:** `services/api/token_budget.py:18,142` (`TokenBudget`), `services/api/chat.py:285`
(`DailyCap`), `chat.py:185` (`cloud_daily_limit`)

**Problem:** the daily token, search and question caps that protect `GEMINI_CLOUD_API_KEY`
(a billed key) are counters in memory. They reset to zero whenever Cloud Run scales the
service to zero and restarts it, and each extra instance gets its own full set. A visitor who
generates load (which makes Cloud Run add instances) multiplies the effective daily cap by the
instance count.

**Fix (two parts):**
1. Outside the code (owner): set a hard quota on the Generative Language API in Google Cloud
   (APIs & Services → Quotas: requests and tokens per day) and a billing budget with an alert.
   Restrict the API key to the Generative Language API only.
2. In the code: persist the day's counters (Supabase table `usage_counters (day, key, n)` with
   an atomic upsert-increment, or Redis when present) and read them before each call; keep the
   in-memory counter only as a fallback when the database is down.

**Verify:** a test creates two `TokenBudget` instances against the same store and checks they
share one day total; a test restarts the budget object and checks the day's usage survives.

## F5 (medium): the Vite dev server accepts any Host header, and its dev dependencies have known holes

**Where:** `web/vite.config.js:142` and `web/vite.config.ts:125` (`server.allowedHosts: true`);
`web/package.json` (vite 5.4.21, vitest 2.1.9)

**Problem:** `allowedHosts: true` turns off Vite's DNS-rebinding guard on the dev server, which
serves the source and the API proxy. The comment above it says the dev server is never
tunnelled, so the setting is not needed. `npm audit` (all dependencies) reports, in the dev
toolchain only: vite path traversal (high), esbuild letting any website read the dev server
(moderate), vitest/tinypool code execution (critical), source-map-js DoS (high). Together: a
malicious website the developer visits while `npm run dev` runs can read files from the dev
server.

**Fix:**
- Remove `allowedHosts: true` from `server` (keep it on `preview`, the one that is tunnelled).
- Upgrade the dev toolchain: vite to the latest 6.x/7.x, vitest to the matching major,
  @vitejs/plugin-react to match; run `npm audit` until no high/critical remain.
- `vite.config.js` shadows `vite.config.ts` (Vite loads the `.js`); make the same change in
  both or delete one.

**Verify:** `npm audit` shows no high/critical; `curl -H 'Host: evil.example' localhost:5173`
returns 403 from the dev server.

## F6 (low): the Python packages in the image are not pinned

**Where:** `Dockerfile:23` (`pip install "fastapi>=0.115" ...`)

**Problem:** every build installs whatever is newest. Today that is clean (`pip-audit`: no
known vulnerabilities), but a compromised or broken release would be shipped by the next deploy
without review, and builds are not reproducible.

**Fix:** add `requirements-api.txt` with exact versions and hashes
(`pip-compile --generate-hashes`), install with `pip install --require-hashes -r ...`, and
let Dependabot or a CI `pip-audit` step propose upgrades.

**Verify:** two builds a day apart produce the same `pip freeze`.

## F7 (low): base image has 44 high OS vulnerabilities with no fix yet

**Where:** `Dockerfile` (`python:3.12-slim`, Debian 13)

**Problem:** Trivy: 0 critical, 44 high, 63 medium, 62 low, all in Debian packages
(util-linux CVE-2026-76642/78408/78409/78410, ncurses CVE-2025-69720, systemd CVE-2026-16742,
acl CVE-2026-54369, perl CVE-2026-9538), none with a fixed version yet. They are local
privilege-escalation issues in tools the app never runs, and the container runs as an
unprivileged user, so the exposure is low.

**Fix:** pin the base image by digest and rebuild it on a schedule (weekly CI job) so fixes
arrive when Debian publishes them; optionally move to a smaller runtime image
(`gcr.io/distroless/python3-debian12` or a Chainguard Python image) that drops util-linux,
ncurses and perl entirely. Add a Trivy step to CI that fails on fixable high/critical findings.

## F8 (low): status endpoints tell anyone how much model budget is left

**Where:** `services/api/app.py:288` (`/health` returns the rejection counters),
`services/api/chat.py:768` (`/chat/status` returns each key lane's budget, model cooldowns
and the reasons)

**Problem:** an attacker can watch the remaining daily budget and cooldowns and time an
exhaustion attack precisely (see F4); the rejection counters show which defences they trip.

**Fix:** return only what the UI needs (`enabled`, which providers are on, a coarse
`"ok" | "low" | "out"` budget state). Move the detailed budget, pool and counter data behind
the operator token (same check as `/command`), for example `GET /admin/status`.

**Verify:** a test checks `/chat/status` without a token contains no `budget`, `lanes`
or cooldown reasons; with `X-STF-Token` it does.

## F9 (low): KaTeX advisory GHSA-238p-pmpm-9mq7

**Where:** `web/package.json:21` (`katex ^0.16.47`), used with `dangerouslySetInnerHTML` in
`web/src/shared/tex.tsx:23` and `web/src/dashboard/Degradation.tsx:14`

**Problem:** with a prototype pollution elsewhere on the page, KaTeX's `trust` restriction can be
bypassed, re-enabling `\href{javascript:...}` in copilot answers (which can contain text from
web pages). It needs a second bug to be exploitable; none is known in this app today.

**Fix:** upgrade to `katex@0.19.x` (the fix; a major version, so check rendering of the
Docs and copilot pages), and pass `trust: false, maxExpand: 1000` explicitly in both
`renderToString` calls.

## F10 (operational): the UPB AI key in `.env` is a 12-hour login token

**Where:** `stf-hw/.env` and the Cloud Run secret `UPB_AI_KEY`

**Problem:** it is an Open WebUI session token (a JWT from the browser), not an API key; the one
in `stf-hw/.env` expired on 2026-10-18 and the copilot's UPB fallback has failed since. A
session token in a server config also grants the whole account (chat history, settings), not
just the API.

**Fix:** remove `UPB_AI_KEY` from Cloud Run (the copilot falls back to the other providers) until
the UPB admins grant a real API key; never deploy a browser session token.

---

## Checked and fine

- Supabase (live project): all 13 tables have row-level security on with no public policies
  (closed to anything but the service key); the `captures` bucket is private, 200 kB, JPEG only.
  The web app ships no Supabase key.
- `keepalive.py`: one connection per host, TLS verified, no redirects, used only for the
  configured Supabase URL.
- `gemini_search.py`: grounded pages are opened through `netguard` (public addresses only);
  source links are http(s) only.
- Copilot Markdown (`web/src/dashboard/copilot/Message.tsx`): links only render for
  `https?://` URLs; React escapes all text; no `javascript:` link path.
- Live-link commands (`web/src/twin/livePublish.ts`): `defect` is checked against a fixed list
  and `qty` is clamped to 1-12.
- TTS math parser (`mathspeak.py`): input is cut at 3000 characters; deeply nested LaTeX parses
  in ~1 ms; the worst case found (4000 spaces) takes 0.2 s behind the TTS rate limit.
- Python dependencies as the Dockerfile installs them: no known vulnerabilities.
- `Porfolio/backend/.env` (which holds copies of this project's secrets) is git-ignored and was
  never committed.
