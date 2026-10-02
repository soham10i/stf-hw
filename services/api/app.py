"""
The live twin API.

    PYTHONPATH=packages .venv/bin/uvicorn services.api.app:app --reload

Endpoints:

    GET  /health        liveness + client count
    GET  /layout        scene descriptor (the front end builds its 3D scene from this)
    GET  /orders        recent order history
    POST /command       queue an order  {"op": "retrieve", "slot": "B2"}
                        (operator only, see security.py)
    WS   /ws            live world frames at ~30 Hz

The kernel runs on one asyncio task started at app startup; every request and
socket reads from that single authoritative simulation.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from stf_layout import get_layout

from . import security as sec
from . import wire
from .runtime import SimRuntime

# STF_TIME_SCALE speeds up (or slows) the DEMO only - it multiplies how much sim
# time each real second advances. The physics is unchanged; a move still takes
# the same number of sim-seconds. Handy for watching a full ~2-minute cycle in
# 20 seconds. Defaults to real time.
_TIME_SCALE = float(os.environ.get("STF_TIME_SCALE", "1.0"))

runtime = SimRuntime(time_scale=_TIME_SCALE)
settings = sec.Settings.from_env()
command_guard = sec.CommandGuard(settings)
ws_clients = sec.ClientCounter(settings.max_ws_clients)
WS_MAX_MSG = 1024          # bytes: the client only ever sends {"type": "resync"}


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
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-STF-Token"],
)


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
