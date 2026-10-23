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

## Branch workflow (2026-10-23) — push to `dev` tests, merge to `main` ships

Two Cloud Build GitHub triggers automate the whole loop:

| push to | trigger | deploys to |
|---|---|---|
| `dev` | `stf-staging-dev-deploy` | private mirror `stf-staging` |
| `main` | `rmgpgab-stf-live-…` | public `stf-live` |

So the daily loop is pure git:

```bash
git switch dev            # all work happens on dev
# ... edit, run the suite, commit ...
git push origin dev       # -> auto-builds and deploys the mirror in ~5 min
# test the mirror (Swagger via `make staging-proxy`, curl with token)
git switch main && git merge dev && git push origin main   # -> ships to the public URL
```

Trigger deploys only replace the container image, so the mirror keeps its
configuration across builds: private IAM (invoker = your account only),
`STF_API_DOCS=1`, blanked mail, the 10 Secret Manager mounts, and the
1 GiB / 1 CPU sizing. Verified 2026-10-23 after the first dev push.

`make staging-deploy` / `make promote` remain as manual escape hatches for
deploying an uncommitted local tree; the branch flow is the normal path.

## Development loop

1. Change code locally; run the suite (`.venv/bin/python -m pytest -q --ignore=tests/perf`).
2. Commit on `dev` and `git push origin dev` — the trigger builds and deploys the mirror.
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
