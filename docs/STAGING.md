# Staging mirror and promotion

`stf-staging` is the private mirror of the public API (`stf-live`). All development and
testing land here first; the public URL only ever receives code that passed on staging.
Both services run in `smart-tabletop-factory-512013` / `europe-west1` and scale to zero,
so the mirror costs almost nothing on the trial credits.

## The two services

| | `stf-staging` | `stf-live` |
|---|---|---|
| URL | `https://stf-staging-g6jrc6bpwq-ew.a.run.app` | `https://stf-live-g6jrc6bpwq-ew.a.run.app` |
| Access | **private** — only your Google account (IAM invoker) | public |
| Swagger | `STF_API_DOCS=1` → `/docs` | off |
| Mail | `STF_NOTIFY_EMAIL` blanked — can never send | as configured |
| Config | copied from `stf-live` at deploy time | source of truth |
| Keep-warm | none (dev service; cold start is fine) | Cloud Scheduler + UptimeRobot (docs/GCP_DEPLOY.md) |

Secrets: the environment (API keys, Supabase keys, SMTP) is read from `stf-live` at
deploy time and passed through `--env-vars-file`. Secret values are never written to
the repo, never printed, and the temp files are deleted on exit.

## Accessing staging

Every request needs an identity token (it expires, so fetch per session):

```bash
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     https://stf-staging-g6jrc6bpwq-ew.a.run.app/health
```

Browser: run `make staging-proxy` (same as `gcloud run services proxy stf-staging
--region europe-west1 --project smart-tabletop-factory-512013`) and open
`http://localhost:8080/` — or `http://localhost:8080/docs` for the Swagger UI.
No token needed through the proxy; it authenticates with your gcloud credentials.
Opening the `*.run.app` URL directly in a browser shows Google's `Forbidden` page —
that is the privacy working, not an outage; the browser sends no identity token.

## Development loop

1. Change code locally; run the suite (`.venv/bin/python -m pytest -q --ignore=tests/perf`).
2. `make staging-deploy` — builds the current tree onto `stf-staging`.
3. Test on staging (Swagger, curl with token, dashboard pointed at staging if needed).
4. Repeat until stable.

## Promotion

`make promote` rebuilds `stf-live` from the **same tree** that passed on staging,
carrying `stf-live`'s environment over verbatim. Cloud Run keeps the previous
revision, so promotion is atomic and rollback is one command:

```bash
# if something is wrong after promoting:
gcloud run revisions list --service stf-live --region europe-west1 \
  --project smart-tabletop-factory-512013
gcloud run services update-traffic stf-live --region europe-west1 \
  --project smart-tabletop-factory-512013 --to-revisions <old-revision>=100
```

After promoting, re-run the smoke checks against the public URL (`curl $URL/health`,
one copilot question) — and remember the keep-warm job covers `stf-live`, not staging.

## Secrets in Secret Manager (done 2026-10-23)

The credential env vars are no longer plain text on either service: ten secrets
(`GEMINI_API_KEY`, `GROQ_API_KEY`, `ELEVENLABS_API_KEY`, `UPB_AI_KEY`,
`SUPABASE_SERVICE_KEY`, `SUPABASE_SECRET_KEY`, `SUPABASE_DATABASE_PASSWORD`,
`STF_SMTP_PASS`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`) live in Secret Manager and are
mounted by `deploy/staging.sh` / `deploy/promote.sh` via `--set-secrets`. `STF_SESSION_SECRET`
and `STF_API_TOKEN` were unset on `stf-live` and stay env-set when you configure them.

- Created/updated by `./deploy/migrate-secrets.sh` (values are read from the running
  service's spec and never printed or written to the repo).
- The runtime service account (`…-compute@developer.gserviceaccount.com`) holds
  `roles/secretmanager.secretAccessor` at the project level.
- To rotate a key: update the env on `stf-live` (console, one field), rerun
  `./deploy/migrate-secrets.sh`, then `make staging-deploy && make promote` — or just
  add a new version in the Secret Manager console; the next revision picks up `:latest`.
- Cost: ~$0.06 per secret per month + negligible access fees — well inside the trial.
