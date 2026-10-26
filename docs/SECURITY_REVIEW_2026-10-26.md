# Security review: 2026-10-26

Scope: live site posture (read-only probes), dependency scans, active penetration
probes against a locally built container, fixes. Follow-up to the 2026-10-22 review
(`docs/SECURITY_FINDINGS.md`). **No code was committed or pushed** — all fixes are
local, uncommitted, awaiting owner review.

## Method

1. **Passive probes** against `https://stf-live-500754517962.europe-west1.run.app`:
   headers, API docs surface, auth guards, cookie flags.
2. **Dependency scans**: `pip-audit` on `requirements-api.txt` (clean),
   `npm audit` in `web/` (clean).
3. **Active probes** against a locally built container (`docker build -t stf-pentest .`,
   bound to `127.0.0.1` only) — the safe test environment, no live traffic affected.
   Script kept at `kimi-code/probe_container.sh` for reuse.
4. Owner items from 2026-10-22 verified against the live service spec.

## Results of the pentest probes (container)

All 16 probes pass: spoofed-`Host` command injection (peer check holds), wrong/missing
operator token (403 on `/command`, e-stop, audit log, admin status), foreign-origin
CSRF (403 on `/twin/state`, `/twin/live` handshake), oversized bodies (413 at the
16 kB twin-state limit; the chat's 500-char question cap rejects at the schema with
422 — bounded either way), path traversal on `/vision/captures/{cid}.jpg` (no file
disclosure), rate limits trip on `/chat` (429) and `/command` with a token (burst 8),
API docs off, CSP and security headers present, `Server: uvicorn` (no version leak),
guest cookie `HttpOnly; SameSite=Lax; Secure`.

## Findings and fixes (uncommitted, in the working tree)

| # | Finding | Fix |
|---|---|---|
| R1 | `POST /watchdog/scan` and `POST /watchdog/incidents/{id}/ack` were unauthenticated, origin-unchecked state-changing writes | Same-site origin check + per-IP rate limit (1/s, burst 4), same pattern as the twin-record endpoints (`services/api/app.py`). Regression tests in `tests/test_api_security.py`; verified in the rebuilt container (foreign origin 403, burst trip 429) |
| R2 | Groq web-search lane had no 429 cooldown: every question re-hit the free tier's 8k TPM limit and the raw provider error leaked into the UI note | `_web_groq` rests ~60 s after a 429 (parses "try again in Ns"), short UI note, `groq_rest_s` in `/chat/status` (`services/api/chat.py`) |
| R3 | `ruff check` broken on `main` by the industrial-agent commits (39 errors: E501/F401/F841 in `actuation.py`, `runtime.py`, `tools.py`, `watchdog.py`, `industrial_io.py`, tests) | Fixed the 5 violations in files this review touches (`app.py`, `chat.py`). **Remaining 34 are in the other session's committed feature code** — needs a dedicated cleanup pass, not folded into this review |
| — | `test_golden_requests[graph|linear]` fail on clean HEAD | Pre-existing (the NEXUS system-prompt change invalidated the recorded golden bodies); owner to re-record |

## Owner items (from 2026-10-22, verified)

- **F10 still open**: `UPB_AI_KEY` is still wired into `stf-live` (as a secret ref). It
  is a session token; when it expires it just stops working — remove the env entry when convenient.
- **F4 partially open**: spending caps share through Supabase (code in place); confirm
  the migration `supabase/migrations/20261022120000_stf_usage_counters.sql` is applied
  and the GCP budget alert exists.
- All secrets on `stf-live` are `secretKeyRef` — verified, nothing plaintext.

## Mirror deployment (done)

The pentested local image is deployed to the **private** mirror, no git push needed:

```
docker build --platform linux/amd64 -t stf-pentest .
docker tag  stf-pentest europe-west1-docker.pkg.dev/smart-tabletop-factory-512013/cloud-run-source-deploy/stf-staging:sec-20261026
docker push europe-west1-docker.pkg.dev/smart-tabletop-factory-512013/cloud-run-source-deploy/stf-staging:sec-20261026
gcloud run deploy stf-staging --image <same> --region=europe-west1
```

- Image tag: `…/stf-staging:sec-20261026` (keep it until the reviewed changes land on `dev`)
- All 30 env entries and 10 secret refs preserved; IAM invoker binding intact (private)
- Note: Cloud Run needs `linux/amd64`; an arm64 (Apple Silicon) build is refused with a
  manifest-type error.
- Once the owner commits these changes to `dev` and pushes, the GitHub trigger rebuilds
  the mirror from source; after that the manually-pushed tag is no longer referenced.

## Gates

- `pytest -q --ignore=tests/perf`: passes except the 2 pre-existing golden failures.
- `ruff check` on the files this review touched: clean.
