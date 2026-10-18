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
     ```
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
  --set-env-vars "GEMINI_API_KEY=$GEMINI_API_KEY,GROQ_API_KEY=$GROQ_API_KEY,ELEVENLABS_API_KEY=$ELEVENLABS_API_KEY,ELEVENLABS_VOICE_ID_01=$ELEVENLABS_VOICE_ID_01,ELEVENLABS_VOICE_ID_02=$ELEVENLABS_VOICE_ID_02,UPB_AI_URL=$UPB_AI_URL,UPB_AI_KEY=$UPB_AI_KEY,SUPABASE_URL=$SUPABASE_URL,SUPABASE_SERVICE_KEY=$SUPABASE_SERVICE_KEY,SUPABASE_BUCKET=captures,STF_DB=auto,STF_MAX_WS_CLIENTS=16"
```

Once deployment completes, the terminal will output the live Service URL.
Visiting the URL will automatically redirect to `/stf/` and connect to the live physics WebSocket at 30 Hz.
