"""
The live twin API.

    PYTHONPATH=packages .venv/bin/uvicorn services.api.app:app --reload

Endpoints:

    GET  /health        liveness + client count
    GET  /layout        scene descriptor (the front end builds its 3D scene from this)
    GET  /orders        recent order history
    POST /command       queue an order  {"op": "retrieve", "slot": "B2"}
    WS   /ws            live world frames at ~30 Hz

The kernel runs on one asyncio task started at app startup; every request and
socket reads from that single authoritative simulation.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from stf_layout import get_layout

from . import wire
from .runtime import SimRuntime

# STF_TIME_SCALE speeds up (or slows) the DEMO only - it multiplies how much sim
# time each real second advances. The physics is unchanged; a move still takes
# the same number of sim-seconds. Handy for watching a full ~2-minute cycle in
# 20 seconds. Defaults to real time.
_TIME_SCALE = float(os.environ.get("STF_TIME_SCALE", "1.0"))

runtime = SimRuntime(time_scale=_TIME_SCALE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await runtime.start()
    try:
        yield
    finally:
        await runtime.stop()


app = FastAPI(title="STF Digital Twin", version="4.0.0", lifespan=lifespan)

# The Vite dev server runs on a different port, so the browser needs CORS to
# reach this API. Wide-open is fine for a local dev tool; lock it down if this
# is ever exposed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CommandRequest(BaseModel):
    op: str = Field(description="retrieve | store | home | cycle")
    slot: str | None = Field(default=None, description="target slot A1..C3")


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "version": "4.0.0",
        "clients": runtime.client_count,
        "layout": get_layout().fingerprint(),
    }


@app.get("/layout")
async def layout() -> dict:
    """The scene descriptor. The front end builds its 3D scene from this alone."""
    return wire.scene_descriptor(get_layout())


@app.get("/orders")
async def orders() -> dict:
    return {"orders": runtime.orders()}


@app.post("/command")
async def command(req: CommandRequest) -> JSONResponse:
    try:
        order = runtime.submit(req.op, req.slot)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    return JSONResponse(content={"accepted": True, "order": order.as_dict()})


@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    await websocket.accept()
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
            msg = await websocket.receive_json()
            if msg.get("type") == "resync":
                await websocket.send_json(runtime.latest_frame())
    except WebSocketDisconnect:
        pass
    finally:
        runtime.remove_client(websocket)
