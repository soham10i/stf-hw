# Deploying the twin

Two things can be deployed. Both are free.

| | What it is | Needs a server? | Free host | Sleeps? |
|---|---|---|---|---|
| **The public demo** (`stf-twin`) | The standalone twin. The 3D cell, the orders, the compiled PLC program, the vision CNN, the AAS and OPC UA browsers all run in the visitor's browser. | No: static files (`web/dist-pages`) | Render Static Site, GitHub Pages, Firebase | Never |
| **The live twin** (`stf-live`) | The Python physics kernel (`services/api`) streaming the machine over a WebSocket, with the web app served by the same process. | Yes: one container (`Dockerfile`) | **Google Cloud Run** (see [GCP_DEPLOY.md](GCP_DEPLOY.md)), Render | Scales to 0 / wakes in seconds |

For a portfolio link, use the public demo: it is always on and costs nothing at any traffic level.
The live twin can be hosted for free on **Google Cloud Run** or Render to demonstrate live server-side kinematics and WebSockets.


## 1. Push the project to GitHub

The repository is the whole project; everything the builds need is committed (the generated data in
`web/public` included). Heavy and local-only files (`.venv`, `node_modules`, `.cache`, FreeCAD backups)
are ignored.

```bash
git checkout main
git merge feat/3d-twin-rearchitecture
git push origin main
```

## 2. Deploy on Render with the Blueprint (both services)

1. Sign up at <https://render.com> with your GitHub account (no card needed for free services).
2. **New → Blueprint**, pick `soham10i/stf-hw`, branch `main`. Render reads `render.yaml` and proposes:
   - `stf-twin`: a static site, built with `npm ci && npm run build:pages` in `web/`, published from
     `web/dist-pages`, at the site root (`STF_BASE=/`).
   - `stf-live`: a Docker web service on the free plan, health-checked on `/health`.
3. **Apply**. The first builds take about 3 minutes (static) and 6 minutes (Docker).
4. Open the URLs Render shows:
   - `https://stf-twin.onrender.com/`: the demo. The status chip reads **Simulation**.
   - `https://stf-live.onrender.com/`: redirects to `/stf/`. The chip reads **Live** once the
     WebSocket is connected; the manual crane commands appear under Orders.

Every push to `main` redeploys both. To deploy only the demo, delete the `stf-live` block from
`render.yaml` (or skip it when applying).

### Without the Blueprint (static site only)

**New → Static Site**, pick the repository, then:

| Setting | Value |
|---|---|
| Root directory | `web` |
| Build command | `npm ci && npm run build:pages` |
| Publish directory | `dist-pages` |
| Environment variable | `STF_BASE` = `/` |

## 3. Security on a public host

- **The demo** carries its Content-Security-Policy in the page (`<meta>`). Render adds the other headers
  from `render.yaml` (`X-Frame-Options`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`).
- **The live twin** is read-only to the public. A command is accepted only with the operator token:
  Render generates `STF_API_TOKEN` (dashboard → `stf-live` → Environment), sent as the `X-STF-Token`
  header. Its own `https://…onrender.com` origin is allowed automatically (`RENDER_EXTERNAL_URL`); the
  API sends the same security headers as `vite preview` (`services/api/app.py`). See `docs/SECURITY.md`.
- WebSocket clients are capped (`STF_MAX_WS_CLIENTS`, 16 on Render) and commands are rate-limited.
- **Every visitor is a guest of their own** (a signed, HttpOnly cookie): their copilot conversations,
  inspection photos and live twin are theirs alone. Render generates `STF_SESSION_SECRET`; guests and
  their chats are kept in SQLite until the next deploy, or in Supabase across deploys. See
  [DATABASE.md](DATABASE.md).

### The dashboard chat (Gemini)

The dashboard's **Ask** button and the Copilot page answer with Gemini when the API service has a key,
and offline otherwise (always on the static demo). The key lives only on the server:

- **Locally:** put `GEMINI_API_KEY=...` in `.env` at the repo root (git-ignored; see `.env.example`)
  and restart the API.
- **Render:** dashboard → `stf-live` → Environment → set `GEMINI_API_KEY` (the Blueprint declares it
  without a value).

The model calls the twin's tools (`services/api/tools.py`) and may state only what they return; the
server checks every number in the answer (`verify.py`) and cites the sources. Each client is
rate-limited and the daily caps protect the quota.

**When a model reaches its limit, the next one answers.** Each Gemini model has its own quota, so the
server keeps an ordered list and takes a model out for as long as Google's error says (`retryDelay`),
then tries the next; when every Gemini model is out, a local model (Ollama) answers if one runs, and
otherwise the twin's tools answer directly. `GET /chat/status` shows which models are free.

**Conversations are kept** as JSON documents, one per session (`services/api/store.py`, under
`STF_DATA_DIR`, default `.data/`), owned by an anonymous id the browser keeps. Each session carries a
context store - the facts the tools established - that whichever model answers next is given, so a
hand-over from Gemini to the local model keeps the thread. The store has the shape of a NoSQL one
(get / put / delete / list by owner), so MongoDB or Firestore can replace it. On Render's free tier
the disk is ephemeral: history lasts until the next deploy.

**Spoken answers** (🔊 on each answer, and the Voice tab) go through one speech pipeline,
`POST /chat/tts` - see `docs/TTS_PIPELINE.md` to use it from another site: ElevenLabs when
`ELEVENLABS_API_KEY` is set, then Gemini TTS (2.5 Pro first, the flash voices while its quota is
closed - on the free tier the Pro voice has none), then the computer's own voice (macOS `say`). Ollama
serves language models, not speech. The Voice tab hears questions with the browser's speech
recognition, or records them for `POST /chat/stt` (Gemini transcription) where the browser has none.

| Variable | Default | |
|---|---|---|
| `GEMINI_MODEL` | `gemini-3.5-flash` | the first chat model |
| `GEMINI_MODELS` | 3.5/3.8/3.7/3.6/3 flash, 2.5 flash, the lite models | the fallback order, comma-separated |
| `GEMINI_DAILY_LIMIT` | 300 | model questions a day, whole service |
| `GEMINI_TTS_MODELS` | `gemini-2.5-pro-preview-tts,gemini-2.5-flash-preview-tts,gemini-3.8-flash-tts` | voices in order |
| `GEMINI_TTS_DAILY_LIMIT` | 100 | spoken answers a day, whole service |
| `OLLAMA_URL`, `OLLAMA_MODEL` | `http://127.0.0.1:11434`, `qwen2.5:7b-instruct` | the local model, when it runs |
| `TTS_PROVIDERS` | `elevenlabs,gemini,local` | the speech pipeline's order |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL` | unset, a narrator voice, `eleven_multilingual_v2` | ElevenLabs |
| `GEMINI_STT_MODELS` | the lite models, then 2.5 flash | transcription for the Voice tab |
| `STF_DATA_DIR` | `.data/` | where conversations are stored |

## 4. Free-tier limits, and what "full scale" means here

| Part of the project | On the free tier | Why / alternative |
|---|---|---|
| Standalone twin | Yes, unlimited | Static files on a CDN (Render: 100 GB bandwidth a month; GitHub Pages: 100 GB soft) |
| Live API + WebSocket | Yes, with sleep | 512 MB, 0.1 CPU, 750 instance hours a month: enough for one always-on service. A free uptime pinger stops the sleep but wastes those hours; a paid Starter instance (about $7 a month) removes it |
| OPC UA server (`make opcua`) | No | It speaks raw TCP on port 4840. Render's free services accept HTTP only. Run it locally and record a client connecting; or a free Oracle Cloud VM (Always Free) can host it with port 4840 open |
| MQTT, Redis, TimescaleDB (`docker-compose.yml`) | Not needed | The current API keeps its state in memory. These are the planned plant-floor stack (Upgrade 14, step 3) and run locally with `docker compose up -d` |
| The proofs (`validate.py`, `sil`, `vision`, `aas`, `opcua-check`) | Not deployed | They generate the files the site serves; run them locally, commit the outputs |

The free web service's file system is temporary and its memory is cleared when it sleeps: the live
simulation starts from power-up after a wake. Nothing in the live twin needs to persist.

## 5. Other free hosts for the demo

The same `web/dist-pages` build works on any static host. GitHub Pages is already set up
(`.github/workflows/pages.yml`, Settings → Pages → Source: **GitHub Actions**; base path `/stf-hw/`).
Netlify and Cloudflare Pages take the Render settings above unchanged.

## Run the container locally

```bash
docker build -t stf-live .
docker run --rm -p 10000:10000 stf-live          # http://localhost:10000/
```

Without Docker:

```bash
cd web && npm run build && cd ..
STF_WEB_DIST=web/dist PYTHONPATH=packages .venv/bin/uvicorn services.api.app:app --port 10000
```
