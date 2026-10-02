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
