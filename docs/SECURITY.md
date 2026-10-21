# Security review (2026-10-01)

Scope: the live API (`services/api`), the web app and how it is served (`web/`), the infrastructure
(`docker-compose.yml`, `mosquitto/`), the Python model and analytics code (`stf-cad/hbw`), and the dependencies
of all of them. The machine-side security design (IEC 62443 zones, the Modbus allow-list, the hardwired
interlocks) is Upgrades 11 and 12, documented in `UPGRADE_PLAN.md`. This document covers the software that
runs the twin.

## Findings and fixes

| # | Finding | Severity | Status |
|---|---|---|---|
| S1 | `POST /command` had no authentication. It was reachable through the public ngrok link, so anyone with the link could command the machine. | High | **Fixed.** Commands are accepted from the operator's own machine (Host is localhost) or with the operator token `STF_API_TOKEN` (`X-STF-Token` header). A tunnel is read-only. |
| S2 | CORS `allow_origins=["*"]`: any website open in the operator's browser could call the API on localhost (CSRF). | High | **Fixed.** An origin allow-list (`STF_ALLOWED_ORIGINS`), and a foreign `Origin` is refused for commands even towards localhost. |
| S3 | The Vite proxy rewrote `Host` to `127.0.0.1:8000` (`changeOrigin`), which made every tunnelled request look local and bypassed S1. Found while verifying S1. | High | **Fixed.** `changeOrigin: false` and `xfwd: true`. A comment in `vite.config.ts` says why it must stay that way. |
| S4 | The WebSocket had no origin check (cross-site WebSocket hijacking), no client cap and no message size limit. | Medium | **Fixed.** Origin check, 32 clients (`STF_MAX_WS_CLIENTS`), 1 KB messages, and only `{"type": "resync"}` is understood. |
| S5 | Infrastructure published on every interface: Redis with no password, Postgres with password `stf`, MQTT anonymous. | High (when run) | **Fixed.** Ports bound to 127.0.0.1. Redis and Postgres passwords are required from `.env` (see `.env.example`; `.env` is git-ignored). Mosquitto refuses anonymous clients and uses a password file. |
| S6 | The public link served the Vite **dev** server: source maps, module graph, HMR socket. | Medium | **Fixed.** The tunnel now serves the production build (`vite preview`, port 4173) with security headers. The dev server listens on localhost only. |
| S7 | No security headers. | Medium | **Fixed.** A strict CSP: scripts from self only (plus `wasm-unsafe-eval` for the mesh decoder, never `unsafe-eval`). Also `frame-ancestors 'none'`, `nosniff`, `no-referrer`, `X-Frame-Options`, `Permissions-Policy` and COOP. The theme pre-paint script moved out of the HTML so no inline script is needed. |
| S8 | Commands validated deep in the runtime only (`op` a free string, `slot` unchecked at the boundary). | Low | **Fixed.** `op` is one of a fixed set of four, and `slot` must match `^[A-C][1-4]$`. Anything else gets a 422. Commands are rate-limited per client (token bucket, 4/s, burst 8). |
| S9 | `torch.load` of pickled checkpoints: code execution if a `.pt` file is replaced. | Medium | **Fixed.** `weights_only=True` in `ml/tune.py` and `validate.py`. |
| S10 | The old stack (`api/main.py` with CORS `*` on 0.0.0.0, the Streamlit dashboard, `database/`, `controller/`, `hardware/`, `run_all.*`). It was unmaintained and still runnable. | Medium | **Removed** (it is in git history). |
| S11 | `nanoid` < 3.3.18 (dev dependency). | High (dev) | **Fixed** (`npm audit fix`). |
| S12 | `esbuild` ≤ 0.24.2 dev-server advisory (GHSA-67mh-4wv8-2f99). The fix is Vite 6+, a breaking upgrade. | Moderate (dev) | **Mitigated.** The advisory concerns esbuild's own `serve`, which Vite does not use, and the dev server is now localhost-only and never tunnelled. Upgrading Vite is left as a follow-up. |
| S13 | `eval(c.STF_Envelope)` in `stf-cad/hbw/mcp_build.py`, which reads a property from an FCStd document. | Medium | **Open.** The file belongs to the FreeCAD build workstream and was not edited here. Replace it with `ast.literal_eval`. |
| S14 | The OPC UA server (Upgrade 14) is a new network service that exposes the cell's live I/O and a method. asyncua's defaults offer a None endpoint, anonymous access, and a user manager that accepts any password. | High (when run) | **Designed out.** One endpoint on 127.0.0.1, Basic256Sha256 Sign & Encrypt only; user name and password from `STF_OPCUA_USER` / `STF_OPCUA_PASSWORD` (12 characters or more), compared in constant time; no anonymous token; client certificates must be in the trust list; every variable read-only. `opcua/check.py` proves each refusal against a running server, and a mutant that allows anonymous access is caught. |
| S15 | The MQTT broker (Upgrade 14, Sparkplug B and the Unified Namespace) carries the cell's live data and its commands. Mosquitto's existing configuration listened in plain text, and an MQTT broker gives every client every topic unless told otherwise. | High (when run) | **Designed out.** One listener on 127.0.0.1, TLS 1.3 only, with the cell's own CA; no anonymous clients; one account per role (edge, host, viewer, auditor) with random passwords kept readable by the user only; an access list per role, so the edge writes only its own Sparkplug topics, only the host sends commands and writes the UNS, and the viewer only reads the UNS. `uns/check.py` proves four refused connections, six forbidden writes never delivered and a forbidden read; mutants that allow anonymous access or let the edge command itself are caught. |

Python dependencies: `pip-audit` finds no known vulnerabilities. npm: 0 in production dependencies, and only S12 remains in development.

## Verified

- `tests/test_api_security.py` covers the cases below, and the full suite (100 tests) passes:
  - local commands are accepted;
  - commands through a tunnel are refused, but accepted with the token and refused with a wrong one;
  - a CSRF attempt from a foreign origin is refused;
  - a DNS-rebinding host name is refused;
  - malformed operations and slots are rejected;
  - the rate limiter works;
  - a WebSocket from a foreign origin is closed, and one from the app's own origin streams.
- Against the running system through the public link:
  - a command gets a 403, and reads get a 200;
  - the CSP and the other headers are present;
  - `/stf/src/...` returns the app shell, not source;
  - the 3D view (including the WebAssembly decoder) and the live stream work under the CSP.

## Operating notes

- To command the machine from another device, set `STF_API_TOKEN` and send it as `X-STF-Token`. Never put the token in
  a URL.
- Share the production build only: `npm run build && npm run preview` on port 4173, and tunnel that port.

## Second review (2026-10-20): the public deployment on Cloud Run

Reviewed with the Strix checklists (OWASP Top 10, API security) by reading the code and making
read-only requests; every fix has a regression test in `tests/test_api_security.py`.

| Finding | Fix |
|---|---|
| Rate limits keyed on the leftmost `X-Forwarded-For` (uvicorn `--forwarded-allow-ips='*'`), which the client writes: any per-client limit, and so the daily model quota, could be bypassed | `security.client_ip()`: the entry `STF_PROXY_HOPS` from the right (the one the platform's front end appended); 0 hops (the TCP peer) unless configured, 1 automatically on Cloud Run; uvicorn no longer runs with `--forwarded-allow-ips='*'` |
| Strix (UPB `gpt-oss-120b`, local instance): the first version of that fix still trusted the rightmost entry when NO proxy was in front, so a directly reached server took its rate-limit key from the client (30 forged addresses = 30 kept guests) | trust the header only with a configured or detected proxy; replayed PoC now keeps 20 (the per-client burst) |
| A command was "local" on the `Host` header alone | `is_local_request()`: Host, the TCP peer and every proxy hop must be loopback |
| SSRF: the research path fetched search-result URLs with no address check; `open_page` missed `0.0.0.0`, IPv4-mapped IPv6, CGNAT and redirects; both were open to DNS rebinding | `netguard.py`: the connected socket's peer must be public, checked before any request bytes, on every redirect |
| The copilot's answer cache ignored the guest and the client-supplied grounding: one visitor could plant another's answer | cache key = guest + hash of grounding and history |
| Owner emails were throttled per guest, but a guest is free to create | `STF_NOTIFY_MAX_PER_HOUR` across all guests; visitor text cleaned |
| Bodies read whole before the size check (photos, recordings, `/twin/state`) | `security.read_body()`: Content-Length checked, stream counted |
| Any `*.ngrok` origin allowed by CORS | only with `STF_ALLOW_TUNNELS=1` |
| `/docs` and `/openapi.json` public | only with `STF_API_DOCS=1` |
| No rate limit on `/twin/order`, `/twin/inspection`; log shipping unbounded; one client could hold every WebSocket slot | limits on each (`STF_WS_PER_CLIENT`) |
| A placeholder `STF_SESSION_SECRET` (the deploy guide's `CHANGE_ME` fallback) would sign forgeable cookies | secrets under 32 characters or containing "change" are refused |
| API keys deployed as plain Cloud Run variables | `docs/GCP_DEPLOY.md`: Secret Manager (`--set-secrets`) |

Rate limits and daily caps live in each instance's memory, so with `--max-instances 2` they
are per instance (at most twice the configured values).
