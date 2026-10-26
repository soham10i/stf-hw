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
    POST /chat/stream   the same, as server-sent events: the route, each step and the model's
                        thinking as they happen, then the answer
    POST /twin/state    the open 3D twin's live snapshot, for the chat's live_state tool (live.py)
    GET  /chat/tts/status  the voice providers and which voice models have quota left
    POST /chat/tts      an answer read aloud: ElevenLabs, Gemini or the local voice (tts.py)
    GET  /chat/stt/status  the transcription providers (ElevenLabs Scribe, Groq Whisper, Gemini)
    POST /chat/stt      a recorded question (audio/webm ...) -> its transcript (tts.py)
    GET  /guest         this visitor's guest session: since when, how many visits, which database
    DELETE /guest       forget this guest: its conversations and photos; a new one starts
    POST /guest/track   usage beacon (consent-gated, visits.py): page + the guest's coarse place;
                        optionally emails the owner once per guest (notify.py)
    GET  /guest/visits  this guest's own visits, newest first
    GET  /notify/status   owner notifications configured? (email/webhook on, no secrets)
    POST /notify/test   send the owner a test notice (operator only, like /command)
    GET  /copilot/sessions        the guest's chat history
    GET  /copilot/sessions/{id}   one session: its turns and its context store
    DELETE /copilot/sessions/{id}
    POST /vision/captures   a photo from the inspection camera in the colour hood (captures.py)
    GET  /vision/captures   the newest photos' records;  GET /vision/captures/{id}.jpg  one photo
    WS   /ws            live world frames at ~30 Hz
    WS   /twin/live     the live link: the 3D twin's units, order, inspections and camera to the
                        visitor's dashboards, and their commands back (livehub.py)
    GET  /stf/...       the built web app, when STF_WEB_DIST points at it (one-service deploy,
                        see docs/DEPLOY.md); / redirects there

The kernel runs on one asyncio task started at app startup; every request and
socket reads from that single authoritative simulation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from stf_layout import get_layout

from . import actuation as ACT
from . import guests as G
from . import industrial_io as IIO
from . import live, wire
from . import security as sec
from . import usage as U
from . import visits as VIS
from . import watchdog as WD
from .captures import Captures
from .chat import Chat, ChatRequest, dotenv
from .factory_db import factory_from
from .livehub import MAX_MSG as LIVE_MAX_MSG
from .livehub import LiveHub
from .logging_config import get_logger
from .notify import Notifier
from .runtime import SimRuntime
from .tts import Stt, Tts, TtsRequest

logger = get_logger(__name__)

# STF_TIME_SCALE speeds up (or slows) the DEMO only - it multiplies how much sim
# time each real second advances. The physics is unchanged; a move still takes
# the same number of sim-seconds. Handy for watching a full ~2-minute cycle in
# 20 seconds. Defaults to real time.
_TIME_SCALE = float(os.environ.get("STF_TIME_SCALE", "1.0"))

runtime = SimRuntime(time_scale=_TIME_SCALE)
ACT.set_runtime(runtime)
watchdog = WD.TelemetryWatchdog(runtime)
WD.set_watchdog(watchdog)
opcua = IIO.OpcUaBridge()
aas = IIO.AasBridge()
settings = sec.Settings.from_env()
command_guard = sec.CommandGuard(settings)
ws_clients = sec.ClientCounter(settings.max_ws_clients)
guests = G.Guests({**dotenv(), **os.environ})
chat = Chat(settings, store=guests.db)
factory = factory_from(guests.db)
tts = Tts(settings)
# spoken answers a day (paid voices): counted across every instance, like the chat's caps
tts.cap.shared, tts.cap.name = U.shared_from(guests.db), "tts:spoken"
stt = Stt(settings)
captures = Captures(settings)
visits = VIS.Visits({**dotenv(), **os.environ})
notify = Notifier({**dotenv(), **os.environ}, geo=visits.geo)
# WARNING-and-above logs ship to the same database the visits use (SQLite or Supabase)
if visits.store.name == "supabase":
    _log_shipper = VIS.SupabaseLogHandler(visits.store)
    _log_shipper.setFormatter(logging.Formatter("%(levelname)s [%(name)s]: %(message)s"))
    get_logger("").addHandler(_log_shipper)
WS_MAX_MSG = 1024
# one address may hold only a few frame streams, so one visitor cannot take every slot
WS_PER_CLIENT = int(os.environ.get("STF_WS_PER_CLIENT", "4"))
_ws_by_ip: dict[str, int] = {}
# the live link (/twin/live) has its own limits: all its sockets on this instance, and per address
live_clients = sec.ClientCounter(int(os.environ.get("STF_MAX_LIVE_CLIENTS", "64")))
LIVE_PER_CLIENT = int(os.environ.get("STF_LIVE_PER_CLIENT", "6"))
_live_by_ip: dict[str, int] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle tasks."""
    logger.info(
        "Starting STF Digital Twin API (version=4.0.0, time_scale=%.1f, database=%s)",
        _TIME_SCALE,
        factory.name,
    )
    await runtime.start()
    await watchdog.start()
    try:
        yield
    finally:
        logger.info("Shutting down STF Digital Twin API")
        await watchdog.stop()
        await runtime.stop()


# the interactive API docs (/docs, /redoc, /openapi.json) map every route for a visitor: off
# unless STF_API_DOCS=1 (a developer's machine)
_DOCS = os.environ.get("STF_API_DOCS", "0") == "1"
app = FastAPI(
    title="STF Digital Twin",
    version="4.0.0",
    lifespan=lifespan,
    docs_url="/docs" if _DOCS else None,
    redoc_url="/redoc" if _DOCS else None,
    openapi_url="/openapi.json" if _DOCS else None,
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global catch-all exception handler logging unexpected 500 errors with full tracebacks."""
    logger.error(
        "Unhandled exception processing %s %s: %s", request.method, request.url.path, exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "detail": "An unexpected error occurred processing your request.",
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Global HTTP exception handler logging client and server errors with contextual detail."""
    if exc.status_code >= 500:
        logger.error(
            "HTTP error %d on %s %s: %s",
            exc.status_code,
            request.method,
            request.url.path,
            exc.detail,
        )
    else:
        logger.warning(
            "HTTP %d on %s %s: %s",
            exc.status_code,
            request.method,
            request.url.path,
            exc.detail,
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
        headers=getattr(exc, "headers", None),
    )


# Only the web app's own origins may call the API from a browser (STF_ALLOWED_ORIGINS).
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    # anyone can register an ngrok subdomain, so tunnels are allowed only when the operator
    # opts in (STF_ALLOW_TUNNELS=1); localhost on any port always is
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
    + (
        r"|https://([a-zA-Z0-9-]+\.)+(ngrok-free\.dev|ngrok\.app|ngrok\.io)"
        if os.environ.get("STF_ALLOW_TUNNELS") == "1"
        else ""
    ),
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-STF-Token", "X-STF-User"],
)


# The headers `vite preview` sends (web/vite.config.ts), for when this process serves the app.
SECURITY_HEADERS = {
    "Content-Security-Policy": "; ".join(
        [
            "default-src 'self'",
            "script-src 'self' 'wasm-unsafe-eval'",
            "style-src 'self' 'unsafe-inline'",
            "font-src 'self' data:",
            "img-src 'self' data: blob:",
            "media-src 'self' blob: data:",
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
    # with COOP: cross-origin isolation, so the twin's simulation bridge can use SharedArrayBuffer
    # (web/src/core/SimulationBridge.ts); the CSP already loads nothing from another origin
    "Cross-Origin-Embedder-Policy": "require-corp",
}


# the paths that serve a guest's own data
GUEST_PATHS = ("/chat", "/copilot", "/vision", "/twin", "/guest")


@app.middleware("http")
async def guest_session(request: Request, call_next):
    """The request's guest, from its signed cookie or new: bound for the rest of the API, and
    put in place of any X-STF-User the browser sent (the server decides who a guest is)."""
    if not request.url.path.startswith(GUEST_PATHS):
        return await call_next(request)
    # in a worker thread: a guest the server has not seen yet is looked up and added in the
    # database (Supabase: network round trips), which must not stall the event loop and the stream
    gid, new = await asyncio.to_thread(
        guests.resolve, request.cookies.get(G.COOKIE), sec.client_ip(request)
    )
    request.scope["headers"] = [(k, v) for k, v in request.scope["headers"] if k != b"x-stf-user"]
    request.scope["headers"].append((b"x-stf-user", gid.encode()))
    token = G.bind(gid)
    try:
        response = await call_next(request)
    finally:
        G.unbind(token)
    if new and not (request.url.path == "/guest" and request.method == "DELETE"):
        response.headers.append("set-cookie", guests.cookie(gid, _https(request)))
    return response


def _https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


@app.middleware("http")
async def forwarded_scheme(request: Request, call_next):
    """Behind a trusted proxy (security.proxy_hops) that terminated TLS, the request was HTTPS:
    redirects the app builds (StaticFiles' /stf -> /stf/) keep https. uvicorn itself no longer
    trusts forwarded headers from arbitrary peers (Dockerfile)."""
    if sec.proxy_hops() and request.headers.get("x-forwarded-proto") == "https":
        request.scope["scheme"] = "https"
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Attach the security headers (CSP, frame denial, ...) to every response."""
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
    """Liveness and readiness: the keep-warm jobs and monitors poll this."""
    return {
        "status": "ok",
        "version": "4.0.0",
        "clients": runtime.client_count,
        "layout": get_layout().fingerprint(),
        "commands": "token" if settings.api_token else "localhost only",
    }


@app.get("/admin/status", dependencies=[Depends(command_guard)])
async def admin_status() -> dict:
    """The operator's view (X-STF-Token or the operator's machine, like /command): which
    defences were tripped, and the copilot's budgets in full. Not public: it would tell a
    visitor exactly how to pace an attack at the limits."""
    return {
        "rejected": dict(sec.COUNTS),
        "chat": await asyncio.to_thread(chat.status, True),
        "live": {"rooms": len(hub.rooms), "clients": live_clients.n, "frame_clients": ws_clients.n},
    }


@app.get("/layout")
async def layout() -> dict:
    """The scene descriptor. The front end builds its 3D scene from this alone."""
    return wire.scene_descriptor(get_layout())


@app.get("/orders")
async def orders() -> dict:
    """The factory simulation's open orders (public twin state)."""
    return {"orders": runtime.orders()}


@app.post("/command", dependencies=[Depends(command_guard)])
async def command(req: CommandRequest) -> JSONResponse:
    """Queue an operational order (retrieve, store, home, cycle) through the safety guard."""
    logger.info("Command received: op=%s, slot=%s", req.op, req.slot)
    res = ACT.get_guard().execute_order(runtime, op=req.op, slot=req.slot, actor="operator")
    if not res.get("accepted"):
        logger.warning("Command rejected by safety guard: %s", res.get("error"))
        return JSONResponse(status_code=400, content={"error": res.get("error")})
    order = res.get("order", {})
    logger.info("Command accepted: order #%d (%s, slot=%s)", order.get("id", 0), req.op, req.slot)
    return JSONResponse(
        content={
            "accepted": True,
            "order": order,
            "audit_id": res.get("audit_id"),
            "signature": res.get("signature"),
        }
    )


@app.delete("/orders/{order_id}", dependencies=[Depends(command_guard)])
async def cancel_order(order_id: int) -> JSONResponse:
    """Cancel a queued order. Invariant: once an order moves to production, it cannot be cancelled."""
    res = ACT.get_guard().execute_order_cancel(runtime, order_id=order_id, actor="operator")
    if not res.get("accepted"):
        return JSONResponse(status_code=400, content={"error": res.get("error")})
    return JSONResponse(content=res)


@app.post("/orders/{order_id}/cancel", dependencies=[Depends(command_guard)])
async def cancel_order_post(order_id: int) -> JSONResponse:
    """Cancel a queued order (POST alias). Invariant: once an order moves to production, it cannot be cancelled."""
    res = ACT.get_guard().execute_order_cancel(runtime, order_id=order_id, actor="operator")
    if not res.get("accepted"):
        return JSONResponse(status_code=400, content={"error": res.get("error")})
    return JSONResponse(content=res)


@app.get("/watchdog/status")
async def watchdog_status() -> dict:
    """Current health and monitoring status of the autonomous background watchdog."""
    return watchdog.get_status()


@app.get("/watchdog/incidents")
async def watchdog_incidents(
    severity: str | None = None,
    category: str | None = None,
    limit: int = 50,
) -> dict:
    """List recent cyber-physical anomalies and incidents detected by the watchdog."""
    return {"incidents": watchdog.list_incidents(severity=severity, category=category, limit=limit)}


@app.post("/watchdog/scan")
async def watchdog_scan() -> dict:
    """Trigger an immediate synchronous telemetry evaluation pass."""
    new_incidents = watchdog.scan_once()
    return {
        "scanned": True,
        "new_incidents": [i.as_dict() for i in new_incidents],
        "status": watchdog.get_status(),
    }


@app.post("/watchdog/incidents/{incident_id}/ack")
async def watchdog_ack(incident_id: str) -> JSONResponse:
    """Acknowledge a specific incident detected by the watchdog."""
    ok = watchdog.acknowledge_incident(incident_id)
    if not ok:
        return JSONResponse(status_code=404, content={"error": "Incident ID not found"})
    return JSONResponse(content={"acknowledged": True, "incident_id": incident_id})


@app.get("/actuation/audit", dependencies=[Depends(command_guard)])
async def actuation_audit(limit: int = 50, action: str | None = None) -> dict:
    """Retrieve cryptographically signed IEC 62443 cyber-physical actuation audit log."""
    return {"records": ACT.get_guard().list_audit_records(limit=limit, action=action)}


@app.post("/actuation/e-stop", dependencies=[Depends(command_guard)])
async def actuation_estop() -> dict:
    """Engage emergency stop safety latch, interlocking all physical and simulation motions."""
    ACT.get_guard().trigger_emergency_stop(actor="operator", reason="Manual operator e-stop requested")
    return {"status": "EMERGENCY_STOP_ACTIVE", "latched": True}


@app.post("/actuation/reset-e-stop", dependencies=[Depends(command_guard)])
async def actuation_reset_estop() -> dict:
    """Reset emergency stop safety latch after clearance."""
    ACT.get_guard().reset_emergency_stop(actor="operator")
    return {"status": "EMERGENCY_STOP_CLEARED", "latched": False}


@app.get("/opcua/nodes")
async def opcua_nodes() -> dict:
    """Browse the standard OPC UA (IEC 62541) address space nodeset."""
    return {"nodes": opcua.browse_nodes()}


@app.get("/opcua/nodes/{node_id:path}")
async def opcua_read(node_id: str) -> JSONResponse:
    """Read an OPC UA node value from the live cyber-physical simulation."""
    try:
        val = opcua.read_node(node_id, runtime)
        return JSONResponse(content={"node_id": node_id, "value": val})
    except KeyError:
        return JSONResponse(status_code=404, content={"error": f"NodeID '{node_id}' not found"})


@app.post("/opcua/nodes/{node_id:path}", dependencies=[Depends(command_guard)])
async def opcua_write(node_id: str, req: dict) -> JSONResponse:
    """Write an OPC UA variable value (e.g. Safety.EmergencyStop) with audit enforcement."""
    try:
        val = req.get("value")
        ok = opcua.write_node(node_id, val, actor="operator")
        return JSONResponse(content={"node_id": node_id, "written": ok, "value": val})
    except (PermissionError, KeyError) as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.post("/opcua/methods/{method_id:path}", dependencies=[Depends(command_guard)])
async def opcua_call(method_id: str, req: dict) -> JSONResponse:
    """Invoke an industrial OPC UA method dispatched through ActionGuard."""
    try:
        res = opcua.call_method(method_id, req, actor="operator", runtime=runtime)
        status_code = 200 if res.get("accepted") else 400
        return JSONResponse(status_code=status_code, content=res)
    except KeyError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})


@app.get("/aas/env")
async def aas_environment() -> dict:
    """Export the complete Asset Administration Shell (AAS / IEC 63278) environment."""
    return aas.export_aas_env(runtime)


@app.get("/aas/submodels/{submodel_id}")
async def aas_submodel(submodel_id: str) -> JSONResponse:
    """Fetch a specific Asset Administration Shell submodel descriptor."""
    try:
        sm = aas.get_submodel(submodel_id, runtime)
        return JSONResponse(content=sm)
    except KeyError:
        return JSONResponse(status_code=404, content={"error": f"Submodel '{submodel_id}' not found"})


@app.get("/chat/status")
async def chat_status() -> dict:
    """Check the status and availability of the copilot LLM chat providers."""
    # in a worker thread: it may probe a local model server, which must not stall the event loop
    # (and with it the frame stream)
    return await asyncio.to_thread(chat.status)


@app.get("/chat/graph")
async def chat_graph() -> dict:
    """The copilot's steps as a graph (agent.py): the engine that runs them and the Mermaid
    diagram drawn from the compiled graph itself, so the picture cannot drift from the code."""
    from . import agent as A

    return {"engine": A.engine(), "nodes": list(A.NODES), "mermaid": A.mermaid()}


@app.post("/chat")
async def chat_ask(req: ChatRequest, request: Request) -> dict:
    """The copilot: a language model answering from the twin's tools (chat.py)."""
    try:
        return await chat.ask(req, request)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("POST /chat error for question %r: %s", req.question[:60], e, exc_info=True)
        raise HTTPException(
            status_code=500, detail="The copilot encountered an unexpected error"
        ) from e


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest, request: Request) -> StreamingResponse:
    """The copilot, streamed (text/event-stream): `route` (where the question goes and why),
    `step` (each retrieval, tool, model and search), `thinking` (the model's reasoning), then
    `answer` (the reply, as POST /chat returns it) or `error`."""
    client = chat.admit(req, request)  # a refusal is an HTTP status, before the stream starts
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def emit(kind: str, data) -> None:
        """Feed one SSE event into the stream's FIFO (thread-safe via the loop)."""
        # from any thread, and always this way: one FIFO, so the answer never overtakes a step
        loop.call_soon_threadsafe(queue.put_nowait, (kind, data) if kind else None)

    async def run() -> None:
        """Produce the answer on a task, so the request's guest contextvar carries over."""
        try:
            emit("answer", await chat.ask(req, request, emit=emit, admitted=client))
        except Exception as e:
            logger.error(
                "POST /chat/stream failed for question %r: %s", req.question[:80], e,
                exc_info=True,
            )
            emit("error", {"detail": getattr(e, "detail", None) or "the copilot failed"})
        emit("", None)

    # started now, so it carries this request's guest (a contextvar) into the answer
    task = asyncio.create_task(run())

    async def events():
        """Drain the FIFO onto the wire as SSE, one event at a time, until the sentinel."""
        try:
            while (item := await queue.get()) is not None:
                kind, data = item
                if kind == "route":
                    data = json.loads(data)
                payload = data if isinstance(data, dict) else {"text": data}
                yield f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/chat/tts/status")
async def tts_status() -> dict:
    """Which TTS providers are configured (voice tab's status chip)."""
    return tts.status()


@app.post("/chat/tts")
async def tts_speak(req: TtsRequest, request: Request):
    """The answer read aloud: Gemini 2.5 Pro TTS, the flash voices when its quota is closed."""
    return await tts.speak(req, request)


@app.post("/chat/tts/stream")
async def tts_stream(req: TtsRequest, request: Request):
    """The answer read aloud as it is synthesised (SSE: meta, base64 chunks, end); the browser
    plays from the first chunk. Non-streaming providers answer as one file chunk (tts.py)."""
    return await tts.stream(req, request)


@app.get("/chat/stt/status")
async def stt_status() -> dict:
    """The transcription providers in order and which are ready (tts.py)."""
    return stt.status()


@app.post("/chat/stt")
async def stt_transcribe(request: Request) -> dict:
    """A spoken question to text, for browsers without speech recognition (tts.py)."""
    return await stt.transcribe(request)


@app.get("/guest")
async def guest_status(request: Request, page: str = "site") -> dict:
    """This visitor's guest session (guests.py): no personal data, only when and how often."""
    gid = G.current()
    if gid and notify.may_send(request.headers.get("host")):
        ip = sec.client_ip(request)
        ua = request.headers.get("user-agent")
        await asyncio.to_thread(notify.visit, gid, page, ip, ua)
    st = guests.status(gid)
    st["session_id"] = gid
    return st


@app.delete("/guest")
async def guest_forget(request: Request) -> JSONResponse:
    """Forget this guest: its copilot sessions, its photos and its live twin; the next request
    starts a new guest."""
    gid = G.current()
    if gid:
        guests.db.forget(gid)
        captures.forget(gid)
        live.drop(gid)
    r = JSONResponse(content={"forgotten": True})
    r.headers.append("set-cookie", guests.clear_cookie(_https(request)))
    return r


class TrackRequest(BaseModel):
    """The usage beacon: which page, and whether the visitor agreed to being measured."""

    page: str = Field(min_length=1, max_length=200)
    consent: bool
    ua: bool = False  # send the user-agent only when asked (it may hold a rare identifier)


@app.post("/guest/track")
async def track(req: TrackRequest, request: Request) -> Response:
    """A page visit, stored only with consent (visits.py): the guest's id, the page, the time,
    the IP and its coarse place. Declined, or switched off (STF_TRACKING=0): an empty 204, no row.
    """
    if not visits.on:
        return Response(status_code=204)
    gid = G.current() or guests.verify(request.cookies.get(G.COOKIE))
    if not _same_site(request):
        return Response(status_code=403)
    ip = sec.client_ip(request)
    ua = request.headers.get("user-agent")
    kept = await asyncio.to_thread(
        visits.record, gid, req.page, ip, ua if req.ua else None, req.consent
    )
    # the owner's "someone is on the site" note (notify.py): throttled to one per guest
    # per STF_NOTIFY_EVERY_HOURS, synchronous with a short timeout, never blocks the beacon;
    # a localhost request never sends (a local test run cannot spam the mailbox)
    if gid and notify.may_send(request.headers.get("host")):
        await asyncio.to_thread(
            notify.visit, gid, req.page, ip, ua
        )
    return {"kept": bool(kept)}


@app.get("/guest/visits")
async def guest_visits() -> dict:
    """What traction is kept for this guest: their own visits, newest first."""
    gid = G.current()
    if not gid:
        return {"visits": []}
    try:
        return {"visits": visits.store.visits(gid)}
    except (OSError, ValueError) as e:
        logger.warning("Visits not reachable: %s", e)
        raise HTTPException(status_code=503, detail="the visits are not reachable") from None


@app.get("/notify/status")
async def notify_status() -> dict:
    """Whether owner notifications are configured (notify.py): which channels are on.
    No secrets - safe to show any visitor; it only says the feature exists."""
    return {"on": notify.on, "channels": notify.channels, "every_hours": notify.every_s / 3600.0}


@app.post("/notify/test", dependencies=[Depends(command_guard)])
async def notify_test(request: Request) -> dict:
    """Send the owner a test notice (notify.py). Operator-only, like /command: from the
    operator's machine or with X-STF-Token. Use the dashboard's bell button. From a local
    address it refuses unless STF_NOTIFY_LOCAL=1 arms it - a local test run cannot spam."""
    if not notify.on:
        detail = "owner notifications are not configured (STF_NOTIFY_*)"
        raise HTTPException(status_code=409, detail=detail)
    if not notify.may_send(request.headers.get("host")):
        detail = "refusing to send from a local address (set STF_NOTIFY_LOCAL=1 to arm a test)"
        raise HTTPException(status_code=409, detail=detail)
    sent = await asyncio.to_thread(notify.test)
    if not sent:
        detail = "the notice could not be sent - check the SMTP/webhook settings and the log"
        raise HTTPException(status_code=502, detail=detail)
    return {"sent": True, "channels": notify.channels}


@app.get("/copilot/sessions")
async def copilot_sessions(request: Request) -> dict:
    """The user's chat history, newest first (sessions.py, store.py)."""
    return {"sessions": chat.sessions(request)}


@app.get("/copilot/sessions/{sid}")
async def copilot_session(sid: str, request: Request) -> dict:
    """One chat session's full record (the history drawer's opened conversation)."""
    return chat.session(request, sid)


@app.delete("/copilot/sessions/{sid}")
async def copilot_forget(sid: str, request: Request) -> dict:
    """Delete one of the caller's chat sessions."""
    return chat.forget(request, sid)


@app.post("/vision/captures")
async def vision_capture(request: Request) -> dict:
    """A photo the inspection camera took of a baked cookie, for the dataset (captures.py)."""
    return await captures.upload(request)


@app.get("/vision/captures")
async def vision_captures(limit: int = 48) -> dict:
    """The guest's own photos, newest first."""
    return captures.list(limit, G.current())


@app.get("/vision/captures/{cid}.jpg")
async def vision_capture_image(cid: str):
    """Serve one capture's JPEG (ownership-checked inside captures)."""
    return captures.image(cid, G.current())


_state_limit = sec.RateLimiter(rate=2.0, burst=4)


class TwinInspection(BaseModel):
    """One cookie the twin's camera judged (vision/inspect.ts), as the database keeps it."""

    n: int = Field(ge=0, le=10**6)
    flavour: Literal["chocolate", "strawberry", "vanilla"]
    truth: Literal["ok", "burnt", "underbaked", "cracked"]
    condition: str = Field(max_length=24)
    p: float = Field(ge=0, le=1)
    verdict: Literal["pass", "reject", "check"]
    ae: float = Field(ge=0, le=1000)
    unusual: bool


class TwinOrder(BaseModel):
    """An order line the twin finished: what it baked, kept, and threw out."""

    flavour: Literal["chocolate", "strawberry", "vanilla"]
    qty: int = Field(ge=1, le=12)
    baked: int = Field(ge=0, le=48)
    good: int = Field(ge=0, le=12)
    scrap: int = Field(ge=0, le=36)
    qc_fault: Literal["", "burnt", "underbaked", "cracked"] = ""


def _same_site(request: Request) -> bool:
    return sec.origin_ok(settings, request)


# the twin's records: a finished order or an inspected cookie is seconds apart, never 100/s
_record_limit = sec.RateLimiter(rate=2.0, burst=10)


def _record_ok(request: Request) -> JSONResponse | None:
    if not _same_site(request):
        return JSONResponse(status_code=403, content={"error": "origin not allowed"})
    if not _record_limit.allow(G.current() or sec.client_ip(request)):
        return JSONResponse(status_code=429, content={"error": "too often"})
    return None


@app.post("/twin/inspection")
async def twin_inspection(rec: TwinInspection, request: Request) -> JSONResponse:
    """Store a cookie the twin's camera judged, as this guest's (factory_db.py)."""
    if refused := _record_ok(request):
        return refused
    row = {
        **rec.model_dump(),
        "source": "twin",
        "owner": G.current() or "",
        "t": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "capture_id": None,
    }
    try:
        await asyncio.to_thread(factory.insert, "inspections", [row])
        return JSONResponse(content={"stored": True})
    except Exception as e:
        logger.error("Failed to store twin inspection: %s", e, exc_info=True)
        return JSONResponse(status_code=500, content={"error": "failed to store inspection"})


@app.post("/twin/order")
async def twin_order(rec: TwinOrder, request: Request) -> JSONResponse:
    """Store an order line the twin finished, as this guest's (factory_db.py)."""
    if refused := _record_ok(request):
        return refused
    row = {
        **rec.model_dump(),
        "source": "twin",
        "owner": G.current() or "",
        "t": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
    }
    try:
        await asyncio.to_thread(factory.insert, "orders", [row])
        return JSONResponse(content={"stored": True})
    except Exception as e:
        logger.error("Failed to store twin order: %s", e, exc_info=True)
        return JSONResponse(status_code=500, content={"error": "failed to store order"})


@app.get("/twin/records")
async def twin_records() -> dict:
    """This guest's own twin records: the orders it finished and the cookies it inspected."""
    gid = G.current() or ""
    orders, ins = await asyncio.gather(
        asyncio.to_thread(factory.recent, "orders", gid, 50),
        asyncio.to_thread(factory.recent, "inspections", gid, 100),
    )
    return {"database": factory.name, "orders": orders, "inspections": ins}


@app.post("/twin/state")
async def twin_state(request: Request) -> JSONResponse:
    """The open 3D twin's live snapshot, kept per client for that client's chat (live.py)."""
    if not _same_site(request):
        return JSONResponse(status_code=403, content={"error": "origin not allowed"})
    client = sec.client_ip(request)
    # kept for the guest, so two visitors behind one address each have their own twin
    client = G.current() or client
    if not _state_limit.allow(client):
        return JSONResponse(status_code=429, content={"error": "too often"})
    try:
        raw = await sec.read_body(request, live.MAX_BYTES * 2)
    except HTTPException:
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
    """Stream live physics world frames at ~30 Hz to connected front-end clients."""
    if not sec.ws_origin_ok(settings, websocket):
        sec.note("ws: foreign origin")
        logger.warning("WebSocket rejected: unauthorized foreign origin")
        await websocket.close(code=1008)
        return
    ip = sec.client_ip(websocket)
    if _ws_by_ip.get(ip, 0) >= WS_PER_CLIENT:
        sec.note("ws: too many from one client")
        await websocket.close(code=1013)
        return
    if not ws_clients.try_add():
        sec.note("ws: too many clients")
        logger.warning("WebSocket rejected: client limit reached (%d)", settings.max_ws_clients)
        await websocket.close(code=1013)
        return
    _ws_by_ip[ip] = _ws_by_ip.get(ip, 0) + 1
    try:
        await websocket.accept()
        logger.debug("WebSocket client accepted successfully")
    except Exception as e:
        logger.warning("WebSocket accept failed: %s", e)
        ws_clients.remove()
        _ws_release(ip)
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
        logger.debug("WebSocket client disconnected normally")
    except Exception as e:
        logger.warning("WebSocket client encountered unexpected error: %s", e, exc_info=True)
    finally:
        runtime.remove_client(websocket)
        ws_clients.remove()
        _ws_release(ip)


hub = LiveHub()


@app.websocket("/twin/live")
async def twin_live(websocket: WebSocket) -> None:
    """The live link (livehub.py): ?role=twin publishes, ?role=dashboard watches and steers.
    One room per guest, so a visitor only sees and steers their own twin."""
    if not sec.ws_origin_ok(settings, websocket):
        sec.note("twin/live: foreign origin")
        await websocket.close(code=1008)
        return
    role = websocket.query_params.get("role")
    if role not in ("twin", "dashboard"):
        await websocket.close(code=1008)
        return
    # the room is the visitor's signed guest id, never their address: people behind one NAT
    # (a campus, an office) must not see or steer each other's twin. The page asks GET /guest
    # first (web/src/shared/liveLink.ts), which issues the cookie.
    room = guests.verify(websocket.cookies.get(G.COOKIE))
    if not room:
        sec.note("twin/live: no guest cookie")
        await websocket.close(code=1008)
        return
    ip = sec.client_ip(websocket)
    if _live_by_ip.get(ip, 0) >= LIVE_PER_CLIENT:
        sec.note("twin/live: too many from one client")
        await websocket.close(code=1013)
        return
    if not live_clients.try_add():
        sec.note("twin/live: too many clients")
        await websocket.close(code=1013)
        return
    conn = hub.join(room, websocket, role)
    if conn is None:
        sec.note("twin/live: room full")
        live_clients.remove()
        await websocket.close(code=1013)
        return
    _live_by_ip[ip] = _live_by_ip.get(ip, 0) + 1
    try:
        await websocket.accept()
    except Exception as e:
        logger.warning("live link accept failed: %s", e)
        hub.leave(room, conn)
        live_clients.remove()
        _release(_live_by_ip, ip)
        return
    try:
        await hub.announce(room)
        if role == "dashboard" and (last := hub.last_state(room)):
            await websocket.send_text(last)  # mid-order: draw the cell at once
        while True:
            raw = await websocket.receive_text()
            if not conn.allow():
                continue  # over its rate: dropped, not an error (frames are lossy anyway)
            msg = hub.accepts(role, raw)
            if msg is None:
                if len(raw) > LIVE_MAX_MSG:
                    await websocket.close(code=1009)
                    break
                continue
            await hub.relay(room, conn, msg, raw)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("live link error: %s", e)
    finally:
        hub.leave(room, conn)
        live_clients.remove()
        _release(_live_by_ip, ip)
        await hub.announce(room)


def _release(by_ip: dict[str, int], ip: str) -> None:
    n = by_ip.get(ip, 0) - 1
    if n > 0:
        by_ip[ip] = n
    else:
        by_ip.pop(ip, None)


def _ws_release(ip: str) -> None:
    _release(_ws_by_ip, ip)


# One-service deploy: the built web app (npm run build, base /stf/) served by this process,
# so the page, the REST calls and the WebSocket share one origin. Mounted last: the API
# routes above take precedence.
_WEB = os.environ.get("STF_WEB_DIST")
if _WEB and os.path.isdir(_WEB):

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    async def root() -> RedirectResponse:
        """The bare domain redirects into the dashboard."""
        return RedirectResponse("/stf/")

    app.mount("/stf", StaticFiles(directory=_WEB, html=True), name="web")
