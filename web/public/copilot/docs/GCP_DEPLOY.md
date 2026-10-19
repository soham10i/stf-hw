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
     STF_MAX_WS_CLIENTS=16
     STF_SESSION_SECRET=any_64_character_random_hex_string
     STF_TRACKING=1
     STF_GEO=1
     STF_TRACK_DAYS=180
     # optional - "someone is on the site" notice to the owner (notify.py), off when empty:
     STF_NOTIFY_EMAIL=your.address@gmail.com
     STF_SMTP_HOST=smtp.gmail.com
     STF_SMTP_PORT=465
     STF_SMTP_USER=your.address@gmail.com
     STF_SMTP_PASS=your_gmail_app_password
     ```
     `STF_SESSION_SECRET` matters on Cloud Run: without it, each new instance (and every
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

### 4. Deploy Directly from Local Source
Run this single command from the root of `stf-hw` (Google Cloud Build will build the Docker container in the cloud without needing local Docker):

```bash
gcloud run deploy stf-live \
  --source . \
  --platform managed \
  --region europe-west3 \
  --allow-unauthenticated \
  --port 10000 \
  --memory 1Gi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 2 \
  --set-env-vars "GEMINI_API_KEY=$GEMINI_API_KEY,GROQ_API_KEY=$GROQ_API_KEY,ELEVENLABS_API_KEY=$ELEVENLABS_API_KEY,ELEVENLABS_VOICE_ID_01=$ELEVENLABS_VOICE_ID_01,ELEVENLABS_VOICE_ID_02=$ELEVENLABS_VOICE_ID_02,UPB_AI_URL=$UPB_AI_URL,UPB_AI_KEY=$UPB_AI_KEY,SUPABASE_URL=$SUPABASE_URL,SUPABASE_SERVICE_KEY=$SUPABASE_SERVICE_KEY,SUPABASE_BUCKET=captures,STF_DB=auto,STF_MAX_WS_CLIENTS=16,STF_SESSION_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || echo CHANGE_ME_64_HEX_CHARS),STF_TRACKING=1,STF_GEO=1,STF_TRACK_DAYS=180"
```

> Keep the generated `STF_SESSION_SECRET` value somewhere safe and pass the SAME one on every
> redeploy — a new secret invalidates every visitor's session cookie. The tracking variables
> default to on; `STF_TRACKING=0` turns the consent-gated beacon off.
>
> Optional owner notifications (notify.py), same for both methods:
> ```bash
> --set-env-vars "STF_NOTIFY_EMAIL=you@gmail.com,STF_SMTP_HOST=smtp.gmail.com,STF_SMTP_PORT=465,STF_SMTP_USER=you@gmail.com,STF_SMTP_PASS=your_gmail_app_password"
> ```
> With these set, every new visitor (after they accept the consent banner) emails you
> "A visitor is on stf-live right now" with the page, the coarse place and the time —
> at most one email per guest per 12 hours, so a browsing session cannot spam you.
> Leave them out and the feature stays off.

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
  --location=europe-west3 \
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

---

## First deploy with usage traction (one-time)

The consent-gated visit log and the shipped application logs need two tables in Supabase
(`visits`, `app_logs`). Without them the API falls back to local SQLite automatically and says
so in its log. The migration is in the repo: run
[`supabase/migrations/20261019043500_stf_visits_app_logs.sql`](../supabase/migrations/20261019043500_stf_visits_app_logs.sql)
once — Supabase dashboard → **SQL Editor** → paste → Run. This has already been applied to the
project above; it only needs doing for a *different* project. The guests/documents/captures
tables from the earlier migration are required the same way.
