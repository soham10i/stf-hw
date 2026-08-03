"""
The live simulation runtime.

Owns the kernel and advances it in real time on a single asyncio task, drains an
order queue, and broadcasts world frames to connected WebSocket clients. This is
the thin-slice sim service: it keeps the kernel authoritative and pushes state to
the browser, without yet involving Redis, MQTT or a database (those arrive with
the hybrid data layer). The command flow is deliberately shaped like the eventual
one - orders in, frames out - so that swapping the in-process queue for Redis
Streams later does not change the contract the front end sees.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from stf_kernel import Kernel, PlanError, Trajectory, plan_home, plan_retrieve, plan_store
from stf_layout import Layout, get_layout

from . import wire

#: How often a world frame is pushed to browsers. The kernel integrates far
#: faster (100 Hz); 30 Hz is plenty for the eye and keeps bandwidth modest.
BROADCAST_HZ = 30.0

#: Guard against a scheduling stall: if the loop is starved, never advance the
#: physics by more than this in one wake, or a hiccup would teleport the crane.
MAX_STEP_SECONDS = 0.1


@dataclass
class Order:
    id: int
    op: str
    slot: str | None
    status: str = "pending"  # pending -> running -> completed | failed
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "op": self.op,
            "slot": self.slot,
            "status": self.status,
            "error": self.error,
        }


@dataclass
class SimRuntime:
    """Real-time driver around the kernel plus a client fan-out."""

    layout: Layout = field(default_factory=get_layout)
    seed: int = 42
    time_scale: float = 1.0

    def __post_init__(self) -> None:
        self.kernel = Kernel(self.layout, seed=self.seed)
        self._clients: set[Any] = set()
        self._pending: deque[Order] = deque()
        self._active: Order | None = None
        self._history: list[Order] = []
        self._next_id = 1
        self._seq = 0
        self._running = False
        self._task: asyncio.Task | None = None
        self._loop_lock = asyncio.Lock()

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="sim-loop")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)

    # -- orders ------------------------------------------------------------

    def submit(self, op: str, slot: str | None) -> Order:
        """Queue an order. Planning happens when the crane is free."""
        if op not in ("retrieve", "store", "home"):
            raise ValueError(f"unknown op {op!r}; use retrieve, store or home")
        if op in ("retrieve", "store"):
            if not slot or not self.layout.main_rack.contains(slot):
                raise ValueError(f"op {op!r} needs a valid slot, got {slot!r}")
        order = Order(id=self._next_id, op=op, slot=slot)
        self._next_id += 1
        self._pending.append(order)
        self._history.append(order)
        return order

    def _plan(self, order: Order) -> Trajectory:
        start = self.kernel.backend.snapshot().joints
        if order.op == "retrieve":
            return plan_retrieve(self.layout, order.slot, start=start)
        if order.op == "store":
            return plan_store(self.layout, order.slot, start=start)
        return plan_home(self.layout, start=start)

    def orders(self) -> list[dict[str, Any]]:
        return [o.as_dict() for o in self._history[-20:]]

    # -- client fan-out ----------------------------------------------------

    def add_client(self, ws: Any) -> None:
        self._clients.add(ws)

    def remove_client(self, ws: Any) -> None:
        self._clients.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def _broadcast(self, message: dict[str, Any]) -> None:
        """
        Push a message to every client, dropping any that cannot keep up.

        A slow consumer must never stall the loop, so each send is bounded and a
        failure simply evicts that socket - the authoritative state lives in the
        kernel, so a dropped client just reconnects and resyncs.
        """
        if not self._clients:
            return
        dead = []
        for ws in list(self._clients):
            try:
                await asyncio.wait_for(ws.send_json(message), timeout=0.5)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    def latest_frame(self) -> dict[str, Any]:
        return wire.frame(self.kernel.backend.snapshot(), self._seq)

    # -- the loop ----------------------------------------------------------

    async def _run(self) -> None:
        last = time.perf_counter()
        last_broadcast = 0.0
        broadcast_interval = 1.0 / BROADCAST_HZ

        while self._running:
            now = time.perf_counter()
            dt = min(now - last, MAX_STEP_SECONDS)
            last = now

            self._service_orders()
            self.kernel.advance(dt * self.time_scale)

            if now - last_broadcast >= broadcast_interval:
                self._seq += 1
                await self._broadcast(self.latest_frame())
                last_broadcast = now

            await asyncio.sleep(1.0 / (BROADCAST_HZ * 2))

    def _service_orders(self) -> None:
        """Advance the order queue: complete the active order, load the next."""
        if self._active is not None:
            if not self.kernel.backend.busy:
                self._active.status = "completed"
                self._active = None

        if self._active is None and self._pending:
            order = self._pending.popleft()
            try:
                trajectory = self._plan(order)
            except PlanError as exc:
                order.status = "failed"
                order.error = str(exc)
                return
            order.status = "running"
            self.kernel.load(trajectory)
            self._active = order
