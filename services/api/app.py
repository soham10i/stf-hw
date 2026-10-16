"""
The live twin API.

    PYTHONPATH=packages .venv/bin/uvicorn services.api.app:app --reload

Endpoints:

    GET  /health        liveness + client count
    GET  /layout        scene descriptor (the front end builds its 3D scene from this)
    GET  /orders        recent order history
    POST /command       queue an order  {"op": "retrieve", "slot": "B2"}
                        (operator only, see security.py)
    GET  /chat/status   is the dashboard's LLM chat on (GEMINI_API_KEY set)?
    POST /chat          a question -> the copilot's answer, from the twin's tools (chat.py)
    POST /twin/state    the open 3D twin's live snapshot, for the chat's live_state tool (live.py)
    GET  /chat/tts/status  the voice providers and which voice models have quota left
    POST /chat/tts      an answer read aloud: ElevenLabs, Gemini or the local voice (tts.py)
    POST /chat/stt      a recorded question (audio/webm ...) -> its transcript (tts.py)
    GET  /copilot/sessions        the user's chat history (header X-STF-User)
    GET  /copilot/sessions/{id}   one session: its turns and its context store
    DELETE /copilot/sessions/{id}
    WS   /ws            live world frames at ~30 Hz
    GET  /stf/...       the built web app, when STF_WEB_DIST points at it (one-service deploy,
                        see docs/DEPLOY.md); / redirects there

The kernel runs on one asyncio task started at app startup; every request and
socket reads from that single authoritative simulation.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from stf_layout import get_layout

from . import live, wire
from . import security as sec
from .chat import Chat, ChatRequest
from .runtime import SimRuntime
from .tts import Stt, Tts, TtsRequest

# STF_TIME_SCALE speeds up (or slows) the DEMO only - it multiplies how much sim
# time each real second advances. The physics is unchanged; a move still takes
# the same number of sim-seconds. Handy for watching a full ~2-minute cycle in
# 20 seconds. Defaults to real time.
_TIME_SCALE = float(os.environ.get("STF_TIME_SCALE", "1.0"))

runtime = SimRuntime(time_scale=_TIME_SCALE)
settings = sec.Settings.from_env()
command_guard = sec.CommandGuard(settings)
ws_clients = sec.ClientCounter(settings.max_ws_clients)
chat = Chat(settings)
tts = Tts(settings)
stt = Stt(settings)
WS_MAX_MSG = 1024  # bytes: the client only ever sends {"type": "resync"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await runtime.start()
    try:
        yield
    finally:
        await runtime.stop()


app = FastAPI(title="STF Digital Twin", version="4.0.0", lifespan=lifespan)

# Only the web app's own origins may call the API from a browser (STF_ALLOWED_ORIGINS).
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-STF-Token", "X-STF-User"],
)


# The headers `vite preview` sends (web/vite.config.ts), for when this process serves the app.
SECURITY_HEADERS = {
    "Content-Security-Policy": "; ".join(
        [
            "default-src 'self'",
            "script-src 'self' 'wasm-unsafe-eval'",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "font-src 'self' https://fonts.gstatic.com",
            "img-src 'self' data: blob:",
            "connect-src 'self' blob: data: ws: wss:",
            "worker-src 'self' blob:",
            "base-uri 'self'",
            "form-action 'none'",
            "object-src 'none'",
            "frame-ancestors 'none'",
        ]
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(self), geolocation=(), usb=(), serial=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response


class CommandRequest(BaseModel):
    """A command, validated at the boundary: a fixed set of operations, a slot like B2."""

    op: Literal["retrieve", "store", "home", "cycle"]
    slot: str | None = Field(
        default=None, pattern=r"^[A-C][1-4]$", description="target slot A1..C4"
    )


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "version": "4.0.0",
        "clients": runtime.client_count,
        "layout": get_layout().fingerprint(),
        "commands": "token" if settings.api_token else "localhost only",
        "rejected": dict(sec.COUNTS),
    }


@app.get("/layout")
async def layout() -> dict:
    """The scene descriptor. The front end builds its 3D scene from this alone."""
    return wire.scene_descriptor(get_layout())


@app.get("/orders")
async def orders() -> dict:
    return {"orders": runtime.orders()}


@app.post("/command", dependencies=[Depends(command_guard)])
async def command(req: CommandRequest) -> JSONResponse:
    try:
        order = runtime.submit(req.op, req.slot)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    return JSONResponse(content={"accepted": True, "order": order.as_dict()})


@app.get("/chat/status")
async def chat_status() -> dict:
    return chat.status()


@app.post("/chat")
async def chat_ask(req: ChatRequest, request: Request) -> dict:
    """The copilot: a language model answering from the twin's tools (chat.py)."""
    return await chat.ask(req, request)


@app.get("/chat/tts/status")
async def tts_status() -> dict:
    return tts.status()


@app.post("/chat/tts")
async def tts_speak(req: TtsRequest, request: Request):
    """The answer read aloud: Gemini 2.5 Pro TTS, the flash voices when its quota is closed."""
    return await tts.speak(req, request)


@app.post("/chat/stt")
async def stt_transcribe(request: Request) -> dict:
    """A spoken question to text, for browsers without speech recognition (tts.py)."""
    return await stt.transcribe(request)


@app.get("/copilot/sessions")
async def copilot_sessions(request: Request) -> dict:
    """The user's chat history, newest first (sessions.py, store.py)."""
    return {"sessions": chat.sessions(request)}


@app.get("/copilot/sessions/{sid}")
async def copilot_session(sid: str, request: Request) -> dict:
    return chat.session(request, sid)


@app.delete("/copilot/sessions/{sid}")
async def copilot_forget(sid: str, request: Request) -> dict:
    return chat.forget(request, sid)


_state_limit = sec.RateLimiter(rate=2.0, burst=4)


@app.post("/twin/state")
async def twin_state(request: Request) -> JSONResponse:
    """The open 3D twin's live snapshot, kept per client for that client's chat (live.py)."""
    origin = request.headers.get("origin")
    if (
        origin
        and origin not in settings.allowed_origins
        and sec._host(origin.split("://", 1)[-1]) != sec._host(request.headers.get("host"))
    ):
        return JSONResponse(status_code=403, content={"error": "origin not allowed"})
    client = request.client.host if request.client else "?"
    if client in ("127.0.0.1", "::1"):
        client = (request.headers.get("x-forwarded-for") or client).split(",")[0].strip()
    if not _state_limit.allow(client):
        return JSONResponse(status_code=429, content={"error": "too often"})
    raw = await request.body()
    if len(raw) > live.MAX_BYTES * 2:
        return JSONResponse(status_code=413, content={"error": "too large"})
    try:
        snap = json.loads(raw)
        if not isinstance(snap, dict):
            raise ValueError
        live.put(snap, client)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "a JSON object of at most 8 kB"})
    return JSONResponse(content={"ok": True})


@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    if not sec.ws_origin_ok(settings, websocket):
        sec.note("ws: foreign origin")
        await websocket.close(code=1008)
        return
    if not ws_clients.try_add():
        sec.note("ws: too many clients")
        await websocket.close(code=1013)
        return
    try:
        await websocket.accept()
    except Exception:
        ws_clients.remove()
        raise
    # Greet with the layout fingerprint so a client holding a stale scene graph
    # can detect the mismatch and refetch /layout rather than rendering the
    # factory at coordinates that no longer exist.
    await websocket.send_json(
        {"type": "hello", "layout": get_layout().fingerprint(), "broadcast_hz": 30}
    )
    await websocket.send_json(runtime.latest_frame())
    runtime.add_client(websocket)
    try:
        while True:
            # The client speaks only to keep the socket alive / request a
            # resync; frames are pushed, not polled.
            raw = await websocket.receive_text()
            if len(raw) > WS_MAX_MSG:
                await websocket.close(code=1009)
                break
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if isinstance(msg, dict) and msg.get("type") == "resync":
                await websocket.send_json(runtime.latest_frame())
    except WebSocketDisconnect:
        pass
    finally:
        runtime.remove_client(websocket)
        ws_clients.remove()


# One-service deploy: the built web app (npm run build, base /stf/) served by this process,
# so the page, the REST calls and the WebSocket share one origin. Mounted last: the API
# routes above take precedence.
_WEB = os.environ.get("STF_WEB_DIST")
if _WEB and os.path.isdir(_WEB):

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse("/stf/")

    app.mount("/stf", StaticFiles(directory=_WEB, html=True), name="web")
