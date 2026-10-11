"""
DT-3a: the live plant as a service - REST commands, a WebSocket frame stream, and the viewer, on one local address.

    .venv-twin/bin/python -m twin.plant.serve [--port 8200] [--speed 1] [--manual]      (from stf-cad/line2)
    open http://127.0.0.1:8200/twin/web/?live

Pacing    the plant runs on VIRTUAL time (twin.plant.core); this service advances it by wall time x sim speed, in
          10 ms ticks, and publishes a frame every PUBLISH s of wall time. --manual: time moves only on POST /step
          (the gate uses it: a run is then a pure function of the commands).
WebSocket /ws/frames: {"type": "hello", glow colours, format} then {"type": "frame", t, tau, track: CHANGED rows only
          (first frame: all), glow, power, temps, master}. Rows are timeline.json's format (DATA_CONTRACT.md 3.2).
Flow      by default the plant carries line_sim's product flow (DT-3b) for --hours (24) of the --scenario; frames then
          also carry "paint" (topping colour per puck) and "flow" (counts, stock, AMRs). --no-flow: the DT-3a plant.
REST      GET /state; POST /command {"name": kick | seal | exchange | master | speed, ...args};
          POST /sim {"speed": x} (wall pacing, 0 = pause); POST /step {"ticks": n} (manual mode).
Security  binds 127.0.0.1 only and has no authentication: commands change the twin, never hardware (there is
          none). Exposing it beyond this machine needs the token scheme of services/api on main (docs/SECURITY.md).
"""
import argparse
import asyncio
import json
import os
import sys
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

HERE = os.path.dirname(os.path.abspath(__file__))
LINE2 = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, LINE2)
from twin.plant.core import TICK, Plant                   # noqa: E402
from twin.plant.flow import Flow                           # noqa: E402

PUBLISH = 0.1                                              # s of wall time between published frames


class Service:
    def __init__(self, speed=1.0, manual=False, events=None, flow=True, scenario="nominal_1h", seed=7, hours=24.0):
        """flow: the product flow of line_sim (DT-3b) decides what exists and fires kick / seal / exchange, and the
        oven runs FB_Oven's closed loop; False: the DT-3a plant (positional product, steady oven)."""
        fl = Flow(scenario, seed, horizon=hours * 3600.0) if flow else None
        self.plant = Plant(events=events, flow=fl)
        self.speed, self.manual = speed, manual
        self.clients = set()
        self.frame = self.plant.frame()
        self.lock = asyncio.Lock()
        tl = json.load(open(os.path.join(LINE2, "motion", "timeline.json")))
        self.glow_colours = {n: dict(on=g["on"], off=g["off"]) for n, g in tl["glow"].items()}
        self.zones = tl.get("zones", [])

    async def advance(self, ticks):
        async with self.lock:
            self.plant.step(ticks)
            self.frame = self.plant.frame()
        await self.broadcast()

    async def broadcast(self):
        dead = []
        for ws, last in list(self.clients):
            try:
                await ws.send_text(json.dumps(self.message(last)))
            except Exception:
                dead.append((ws, last))
        for d in dead:
            self.clients.discard(d)

    def message(self, last):
        """The frame for one client: only rows that changed since what it last received (last is updated)."""
        f = self.frame
        rows = {n: r for n, r in f["track"].items() if last.get(n) != r}
        last.update(rows)
        return dict(type="frame", t=f["t"], tau=f["tau"], track=rows, glow=f["glow"], power=f["power"],
                    temps=f["temps"], master=f["master"], bad=f["bad"], paint=f["paint"], flow=f["flow"],
                    duty=f["duty"])

    async def run(self):
        """Wall-clock pacing (not used in manual mode)."""
        acc = 0.0
        last = time.monotonic()
        while True:
            await asyncio.sleep(PUBLISH)
            now = time.monotonic()
            acc += (now - last) * self.speed
            last = now
            n = int(acc / TICK)
            if n:
                acc -= n * TICK
                await self.advance(n)


class _Client(tuple):
    """(websocket, last rows) - hashable by identity for the client set."""

    def __hash__(self):
        return id(self[0])

    def __eq__(self, other):
        return self[0] is other[0]


def create_app(service, autorun=False):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.get_running_loop().create_task(service.run()) if autorun else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="STF-2 live plant (DT-3a)", lifespan=lifespan)

    @app.get("/state")
    def state():
        p = service.plant
        return dict(t=p.t, tau=p.master.tau, master=service.frame["master"], speed=service.speed,
                    manual=service.manual, events=p.ev, commands=len(p.log), clients=len(service.clients))

    @app.post("/command")
    async def command(body: dict):
        body = dict(body)
        name = body.pop("name", None)
        async with service.lock:
            ok, msg = service.plant.command(name, **body)
        return JSONResponse(dict(ok=ok, message=msg, t=service.plant.t), status_code=200 if ok else 400)

    @app.post("/sim")
    def sim(body: dict):
        service.speed = max(0.0, min(50.0, float(body.get("speed", 1.0))))
        return dict(speed=service.speed)

    @app.post("/step")
    async def step(body: dict):
        if not service.manual:
            return JSONResponse(dict(ok=False, message="not in manual mode"), status_code=400)
        await service.advance(int(body.get("ticks", 10)))
        return dict(ok=True, t=service.plant.t)

    @app.websocket("/ws/frames")
    async def frames(ws: WebSocket):
        await ws.accept()
        client = _Client((ws, {}))
        await ws.send_text(json.dumps(dict(type="hello", format="timeline-rows", tick=TICK, glow=service.glow_colours,
                                           zones=service.zones, spawn=[dict(name=n) for n in service.plant.spawn],
                                           extra=service.plant.extra)))
        await ws.send_text(json.dumps(service.message(client[1])))
        service.clients.add(client)
        try:
            while True:
                await ws.receive_text()                      # the stream is one-way; keep the socket open
        except WebSocketDisconnect:
            service.clients.discard(client)

    app.mount("/", StaticFiles(directory=LINE2, html=True), name="static")
    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8200)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--manual", action="store_true")
    ap.add_argument("--no-flow", action="store_true", help="the DT-3a plant: positional product, steady oven")
    ap.add_argument("--scenario", default="nominal_1h", help="a line_sim scenario (its disturbances, its policy)")
    ap.add_argument("--hours", type=float, default=24.0, help="flow horizon (the line runs until then)")
    a = ap.parse_args()
    import uvicorn
    service = Service(speed=a.speed, manual=a.manual, flow=not a.no_flow, scenario=a.scenario, hours=a.hours)
    app = create_app(service, autorun=not a.manual)
    print(f"STF-2 live plant on http://127.0.0.1:{a.port}/twin/web/?live  (speed {a.speed}x"
          f"{', manual' if a.manual else ''})", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
