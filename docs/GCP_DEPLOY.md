# Deploying to Google Cloud (Cloud Run)

The entire digital twin (interactive 3D Three.js frontend + FastAPI physics kernel + WebSocket at 30 Hz + Grounded Industrial Copilot) is containerized in [`Dockerfile`](../Dockerfile) and runs natively on **Google Cloud Run**.

## Why Google Cloud Run?
* **$0 Free Tier**: Cloud Run provides 2 million requests/month, 360,000 GiB-seconds of memory, and 180,000 vCPU-seconds per month for free.
* **Native WebSockets**: Full bi-directional streaming for `/ws` live 30 Hz machine frames.
* **Automatic HTTPS**: Provides a managed, public SSL URL (e.g. `https://stf-live-xxxxxx-ew.a.run.app`).
* **Scale to Zero**: Shuts down when idle to preserve resources, and cold-starts in 1–2 seconds.
* **Cloud Build**: Google Cloud builds the container image remotely — **you do not even need Docker installed locally**.

---

## Method A: Deploy via Google Cloud Console (Web UI — Easiest, No CLI Needed)

1. Open the [Google Cloud Run Console](https://console.cloud.google.com/run).
2. Click **Create Service**.
3. Under **Deployment type**, select:
   * **Continuously deploy from a repository** → Click **Set up Cloud Build**.
   * Provider: **GitHub**.
   * Repository: `soham10i/stf-hw` (Authorize Google Cloud if prompted).
   * Branch: `^main$`.
   * Build Type: **Dockerfile** (Source location: `/Dockerfile`).
4. **Service Configuration**:
   * **Service name**: `stf-live`
   * **Region**: Choose a close region (e.g., `europe-west3` Frankfurt or `us-central1` Iowa).
   * **Authentication**: Check **Allow unauthenticated invocations** (so visitors can access the public twin).
   * **CPU allocation**: Select *CPU is only allocated during request processing*.
   * **Scaling**: Min instances `0`, Max instances `2` (prevents unnecessary billing).
5. **Container, Variables & Secrets Settings** (click expand):
   * **Container port**: `10000` (or `8080` — the container adapts automatically to `${PORT}`).
   * **Memory**: `1 GiB`
   * **CPU**: `1`
   * Under **Environment variables**, click **Add Variable** for your keys:
     ```ini
     GEMINI_API_KEY=your_gemini_key
     GEMINI_MODEL=gemini-3.5-flash
     GROQ_API_KEY=your_groq_key
     ELEVENLABS_API_KEY=your_elevenlabs_key
     ELEVENLABS_VOICE_ID_01=qFjcP4hHD9WIdODvuJOJ
     ELEVENLABS_VOICE_ID_02=bGnz83yTAb7caZSC7BBz
     UPB_AI_URL=https://ai-chat.uni-paderborn.de
     UPB_AI_KEY=your_upb_key
     SUPABASE_URL=https://buiwsvaowyigqpeprike.supabase.co
     SUPABASE_SERVICE_KEY=your_supabase_service_key
     SUPABASE_BUCKET=captures
     STF_DB=auto
     # the copilot's vector index: auto = pgvector in the Supabase project above (migration
     # supabase/migrations/20261023023000_stf_kb_vectors.sql), SQLite file when unset/off
     STF_VECTOR_BACKEND=auto
     STF_MAX_WS_CLIENTS=16
     STF_SESSION_SECRET=any_64_character_random_hex_string
     STF_TRACKING=1
     STF_GEO=1
     STF_TRACK_DAYS=180
     # security (docs/SECURITY.md): Cloud Run's front end appends the caller's address to
     # X-Forwarded-For, so 1 hop; 2 if a Google load balancer sits in front of the service
     STF_PROXY_HOPS=1
     STF_API_DOCS=0
     STF_NOTIFY_MAX_PER_HOUR=10
     # optional - "someone is on the site" notice to the owner (notify.py), off when empty:
     STF_NOTIFY_EMAIL=your.address@gmail.com
     STF_SMTP_HOST=smtp.gmail.com
     STF_SMTP_PORT=465
     STF_SMTP_USER=your.address@gmail.com
     STF_SMTP_PASS=your_gmail_app_password
     ```
     Put the **keys and secrets** (`*_API_KEY`, `*_KEY`, `STF_SESSION_SECRET`, `STF_API_TOKEN`,
     `STF_SMTP_PASS`) under **Variables & Secrets → Reference a secret** (Secret Manager), not
     as plain variables: a plain variable is readable by anyone with viewer access to the
     service and is copied into every revision.
     `STF_API_TOKEN` is the operator token for `POST /command` and the bell's test notice;
     without it the public service is read-only (which is safe).
     `STF_SESSION_SECRET` must be 32+ random characters - a placeholder or a short value is
     refused at start-up (any visitor could forge cookies signed with it). It matters on Cloud Run: without it, each new instance (and every
     scale-from-zero wake) generates a new cookie-signing secret and every visitor's session
     silently resets. Generate one: `python3 -c "import secrets; print(secrets.token_hex(32))"`.
     `STF_TRACKING`/`STF_GEO`/`STF_TRACK_DAYS` run the consent-gated usage beacon
     (services/api/visits.py) — they default to on, so they may be omitted; set
     `STF_TRACKING=0` to answer the beacon with nothing.
     `STF_NOTIFY_*` emails you when a visitor is on the site (one note per guest
     per 12 h, only after they accept the consent banner — same privacy rule as the
     beacon). For Gmail, `STF_SMTP_PASS` is a 16-character **app password** from
     myaccount.google.com/apppasswords, not the account password. Skip all five
     to disable the feature.
6. Click **Create**.
   Cloud Build will build the container from your GitHub repository, push it to Artifact Registry, and launch the service.
   You will receive your live URL: `https://stf-live-<hash>-<region>.a.run.app/stf/`.

---

## Method B: Deploy via `gcloud` CLI

If you prefer deploying from your terminal:

### 1. Install & Authenticate `gcloud`
```bash
brew install --cask google-cloud-sdk
gcloud auth login
gcloud auth application-default login
```

### 2. Set your Google Cloud Project
```bash
# List your projects
gcloud projects list

# Set your active project
gcloud config set project YOUR_PROJECT_ID
```

### 3. Enable Required Google Cloud APIs
```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
```

### 4. Store the secrets in Secret Manager (once)

Keys never go on the command line (shell history) or into plain environment variables
(readable by every viewer of the service). Create each secret once, reading the value from your
local `.env` so it is never typed or echoed:

```bash
gcloud services enable secretmanager.googleapis.com
```

```bash
for k in GEMINI_API_KEY GROQ_API_KEY ELEVENLABS_API_KEY UPB_AI_KEY SUPABASE_SERVICE_KEY STF_SMTP_PASS; do grep "^$k=" .env | cut -d= -f2- | tr -d '\n' | gcloud secrets create "$k" --data-file=- ; done
```

```bash
python3 -c "import secrets; print(secrets.token_hex(32), end='')" | gcloud secrets create STF_SESSION_SECRET --data-file=-
```

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32), end='')" | gcloud secrets create STF_API_TOKEN --data-file=-
```

Give the service's runtime account read access (the default compute account unless you chose
another):

```bash
PROJECT_NUMBER=$(gcloud projects describe "$(gcloud config get-value project)" --format='value(projectNumber)')
```

```bash
for k in GEMINI_API_KEY GROQ_API_KEY ELEVENLABS_API_KEY UPB_AI_KEY SUPABASE_SERVICE_KEY STF_SMTP_PASS STF_SESSION_SECRET STF_API_TOKEN; do gcloud secrets add-iam-policy-binding "$k" --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" --role=roles/secretmanager.secretAccessor; done
```

The session secret now stays the same across redeploys by itself (a new one would log every
visitor out).

### 5. Deploy Directly from Local Source

Run this from the root of `stf-hw` (Cloud Build builds the container; no local Docker needed):

```bash
gcloud run deploy stf-live --source . --platform managed --region europe-west1 --allow-unauthenticated --port 10000 --memory 1Gi --cpu 1 --min-instances 0 --max-instances 2 --set-secrets "GEMINI_API_KEY=GEMINI_API_KEY:latest,GROQ_API_KEY=GROQ_API_KEY:latest,ELEVENLABS_API_KEY=ELEVENLABS_API_KEY:latest,UPB_AI_KEY=UPB_AI_KEY:latest,SUPABASE_SERVICE_KEY=SUPABASE_SERVICE_KEY:latest,STF_SESSION_SECRET=STF_SESSION_SECRET:latest,STF_API_TOKEN=STF_API_TOKEN:latest" --set-env-vars "ELEVENLABS_VOICE_ID_01=qFjcP4hHD9WIdODvuJOJ,ELEVENLABS_VOICE_ID_02=bGnz83yTAb7caZSC7BBz,UPB_AI_URL=https://ai-chat.uni-paderborn.de,SUPABASE_URL=https://buiwsvaowyigqpeprike.supabase.co,SUPABASE_BUCKET=captures,STF_DB=auto,STF_MAX_WS_CLIENTS=16,STF_TRACKING=1,STF_GEO=1,STF_TRACK_DAYS=180,STF_PROXY_HOPS=1,STF_API_DOCS=0,STF_NOTIFY_MAX_PER_HOUR=10"
```

> Optional owner notifications (notify.py): add
> `STF_NOTIFY_EMAIL=you@gmail.com,STF_SMTP_HOST=smtp.gmail.com,STF_SMTP_PORT=465,STF_SMTP_USER=you@gmail.com`
> to `--set-env-vars` and `STF_SMTP_PASS=STF_SMTP_PASS:latest` to `--set-secrets`.
> With these set, a visitor who accepts the consent banner emails you "A visitor is on
> stf-live right now" - at most one email per guest per 12 hours and at most
> `STF_NOTIFY_MAX_PER_HOUR` across all visitors, so a script cannot fill your inbox.
>
> **This migration was done on 2026-10-23.** Ten credentials (the seven above plus
> `SUPABASE_SECRET_KEY`, `SUPABASE_DATABASE_PASSWORD`, `POSTGRES_PASSWORD`,
> `REDIS_PASSWORD`) now live in Secret Manager, mounted by `deploy/staging.sh` /
> `deploy/promote.sh`; no secret is a plain env var on `stf-live` anymore. The
> migration ran via `./deploy/migrate-secrets.sh` (values copied from the running
> service's spec, never printed); the compute service account holds
> `roles/secretmanager.secretAccessor`. The step below is what to do if a new
> secret is ever added as a plain variable again.

Once deployment completes, the terminal will output the live Service URL.
Visiting the URL will automatically redirect to `/stf/` and connect to the live physics WebSocket at 30 Hz.

---

---

## Keeping the service warm (no cold starts)

Cloud Run scales to zero after ~15 minutes without traffic, so the first visitor
of the day pays the 1–2 s container boot. To serve visitors instantly at any
hour, keep one instance alive with a periodic ping. Options, best first:

### Option 1 (recommended): Google Cloud Scheduler — GCP-native, free

A scheduler job calls the light `GET /health` endpoint every 5 minutes, inside
Google's network — no external dependency, no GitHub involvement, and it stays
within the free tier (3 scheduler jobs are free; the pings themselves are
~8,600 requests/month out of 2 million free).

```bash
gcloud services enable cloudscheduler.googleapis.com

gcloud scheduler jobs create http stf-keep-warm \
  --location=europe-west1 \
  --schedule="*/5 * * * *" \
  --time-zone="Europe/Berlin" \
  --uri="https://stf-live-<hash>-<region>.a.run.app/health" \
  --http-method=GET \
  --attempt-deadline=30s
```

The service allows unauthenticated invocations (see above), so no OIDC token
is needed. To check it is firing:

```bash
gcloud scheduler jobs describe stf-keep-warm --location=europe-west3
# recent executions: Cloud Scheduler -> Jobs -> stf-keep-warm in the console
```

### Option 2: GitHub Actions cron — zero GCP setup

[`.github/workflows/keep-warm.yml`](../.github/workflows/keep-warm.yml) pings
`/health` every 5 minutes from a GitHub runner. One-time setup: in the repo,
**Settings -> Secrets and variables -> Actions -> Variables**, add
`STF_LIVE_URL = https://stf-live-<hash>-<region>.a.run.app`. Push the workflow
to the default branch and it runs on its own; the Actions tab shows each ping.

Trade-off vs Option 1: scheduled GitHub workflows can be delayed a few minutes
under load, and GitHub pauses schedules after 60 days of repository inactivity
(pushing to the repo re-enables them). Good enough for a demo site; use
Option 1 if you want strict 5-minute cadence.

### Option 3: always-one-instance (costs money, zero cold start)

```bash
gcloud run services update stf-live --region europe-west3 --min-instances 1
```

One instance stays resident 24/7 — instant response even after long idle gaps.
Note the deploy settings above use *CPU only during request processing*; an
idle min-1 instance is billed mostly for its memory (roughly a few dollars a
month at 1 GiB). Pings (Option 1/2) achieve the same visitor-visible effect
for free, so prefer those unless you need guaranteed sub-100 ms first response.

> Whichever option you pick, the ping target is `/health` on purpose: it is
> the cheapest route in the API (no scene build, no DB) and it reports client
> count + security counters, which also makes the job double as an uptime probe.

### Get an email when the site goes down

The keep-warm job above already turns red on a non-200, and GitHub emails you
on workflow failure by default — that is the zero-setup alert. For a
monitor that is independent of your repo (and checks from several continents,
not just GitHub's runners), add a free **UptimeRobot** monitor:

1. Sign up at [uptimerobot.com](https://uptimerobot.com) (free tier: 50
   monitors, 5-minute checks, email alerts).
2. **Add New Monitor** → type **HTTP(s)**, URL
   `https://stf-live-<hash>-<region>.a.run.app/health`, interval **5 minutes**.
3. In **Alert Contacts** add your email and attach it to the monitor.

You get an email within ~5 minutes of an outage, and again when it recovers.
The same monitor doubles as a second keep-warm ping if you use its
keyword/monitoring hit on the service URL. (Google Cloud Monitoring uptime
checks exist too, but the free allowance is smaller and the alerting setup is
heavier — UptimeRobot is the quick win here.)

### Get an email when someone uses the site

Separate from uptime: with the optional `STF_NOTIFY_*` variables (both
methods above), the API emails you once per visitor — "A visitor is on
stf-live right now" — with the page they opened, their coarse place and the
time. It fires only for visitors who accepted the consent banner (the same
privacy rule as the usage beacon), it is throttled to one note per guest per
12 hours, and a mail-server hiccup can never break the beacon itself.

The dashboard's top-bar bell shows the configuration status at a glance (green
dot when armed) and sends a test notice on click — operator-guarded like
`POST /command`; on the deployed site paste `STF_API_TOKEN` once in the bell's
field and the browser remembers it. A request whose Host is `localhost` never
sends, unless `STF_NOTIFY_LOCAL=1` is set — a local test run with a configured
`.env` cannot spam the mailbox.

---

## First deploy with usage traction (one-time)

The consent-gated visit log and the shipped application logs need two tables in Supabase
(`visits`, `app_logs`). Without them the API falls back to local SQLite automatically and says
so in its log. The migration is in the repo: run
[`supabase/migrations/20261019043500_stf_visits_app_logs.sql`](../supabase/migrations/20261019043500_stf_visits_app_logs.sql)
once — Supabase dashboard → **SQL Editor** → paste → Run. This has already been applied to the
project above; it only needs doing for a *different* project. The guests/documents/captures
tables from the earlier migration are required the same way.

The copilot's pgvector index has its own migration,
[`supabase/migrations/20261023023000_stf_kb_vectors.sql`](../supabase/migrations/20261023023000_stf_kb_vectors.sql)
(`kb_vectors` + `kb_meta` + three RPCs; already applied to the project above). Without it the
API detects the missing table, logs a warning and answers from the SQLite vector store or
BM25 alone — nothing breaks, retrieval just stays local to the container.
