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

**A Google Cloud key (billing on, e.g. the $300 trial credit)** is a second Gemini lane,
`GEMINI_CLOUD_API_KEY`, asked *before* the AI Studio key. Each lane has its own models and cooldowns,
its own Google Search pool and its own token budget (larger defaults: `GEMINI_CLOUD_TOKENS_PER_DAY` 2500000,
`GEMINI_CLOUD_SEARCHES_PER_DAY` 40, and so on - sized so 90 days at the cap stay inside the $300 credit), and a billed key lifts the daily question cap
(`GEMINI_CLOUD_DAILY_LIMIT`, 2000). A key that is at its limit, refused or too slow hands the question to the
next lane, and then to Groq. Create the key in the Cloud console for a project with billing on, restricted to the
Generative Language API, and put it only in `.env` or Render's environment. `make model-check` tests both keys.
Spend is capped by the token and search limits you set, not by the credit: Google Search grounding is billed
per query beyond a free daily allowance, so set `GEMINI_CLOUD_SEARCHES_PER_DAY` to what you are willing to spend.

**Web search and deep research** run through three providers in order (`WEB_SEARCH_ORDER`, default
`gemini,groq,ddg`); one that fails, is resting or cannot be afforded hands the question to the next:

1. **Gemini's Google Search** (`services/api/gemini_search.py`) - the model searches Google and answers.
   Each sentence gets the links of the pages that back it, the pages are followed to their real address
   (public hosts only) and graded by host, and the first few are read so the server can check the
   answer's figures against text it fetched itself. A deep research plans up to four sub-questions and
   searches each.
2. **Groq's browser search** (`GROQ_SEARCH_MODEL`), and 3. **DuckDuckGo** (keyless; a configured model
   writes the fetched pages up).

**Token budget (dynamic).** Every Gemini answer's `usageMetadata` is counted (`services/api/token_budget.py`).
What a search may do depends on the budget left - the smallest of the day's, the minute's and the guest's
share:

| Left | Tier | A search may |
|---|---|---|
| over 50 % | `full` | send the whole context, think, read pages, run up to 4 sub-searches (2048 tokens each) |
| 20-50 % | `lean` | half the context, little thinking, 3 sub-searches (1536 each) |
| 5-20 % | `minimal` | a short context, no thinking, 2 sub-searches (1024 each) |
| under 5 %, or no searches left | `spent` | no Gemini search: Groq or DuckDuckGo answers |

A question may also spend at most `GEMINI_WEB_TOKENS` (search) or `GEMINI_DEEP_TOKENS` (research), and
never more than is left; a deep research drops the sub-searches that would not fit. These limits are
yours, set below Google's own, so one busy hour or one visitor cannot run the key dry. They are held
in memory and restart with the service. `GET /chat/status` shows the tier, the tokens used and the
searches left.

**Google Search has its own quota**, apart from plain answers (a key can answer questions yet have none
for Google Search - every grounded call is then a 429). Grounded calls use their own model pool, so a
refusal never takes a model out of the chat; when every model refuses, searches rest for
`GEMINI_SEARCH_REST_S` and go straight to Groq. A model that does not answer within
`GEMINI_SEARCH_TIMEOUT_S` is skipped for the next, up to `GEMINI_SEARCH_DEADLINE_S` in all.

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
| `GEMINI_CLOUD_API_KEY`, `GEMINI_CLOUD_MODELS` | unset, the `GEMINI_MODELS` list | the Google Cloud lane, asked first |
| `GEMINI_CLOUD_TOKENS_PER_DAY`, `_PER_MINUTE`, `_PER_GUEST`, `_WEB_TOKENS`, `_DEEP_TOKENS`, `_SEARCHES_PER_DAY`, `GEMINI_CLOUD_DAILY_LIMIT` | 2500000, 800000, 400000, 16000, 80000, 40, 2000 | its budget and question cap |
| `GEMINI_VERTEX_PROJECT`, `GEMINI_VERTEX_LOCATION` | unset, `global` | the same lane on Vertex AI (the trial credit): the service account's token, no key; wins over `GEMINI_CLOUD_API_KEY` (docs/architecture/agent-graph.md) |
| `STF_AGENT` | `graph` | the copilot's engine: LangGraph, or `linear` (the same nodes as a plain loop - the kill switch) |
| `WEB_SEARCH_ORDER` | `gemini,groq,ddg` | who searches the web first |
| `GEMINI_TOKENS_PER_DAY`, `_PER_MINUTE`, `_PER_GUEST` | 600000, 120000, 80000 | Gemini tokens: whole service a UTC day, any minute, one guest a day |
| `GEMINI_WEB_TOKENS`, `GEMINI_DEEP_TOKENS` | 8000, 40000 | the most one web search / one deep research may use |
| `GEMINI_SEARCHES_PER_DAY` | 200 | grounded Google searches a day |
| `GEMINI_SEARCH_TIMEOUT_S`, `_DEADLINE_S`, `_REST_S` | 25, 50, 900 | one grounded call, all of a question's, and the rest after a quota refusal |
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
