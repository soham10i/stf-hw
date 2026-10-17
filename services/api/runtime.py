"""
The live simulation runtime.

Owns the kernel and advances it in real time on a single asyncio task, drains an
order queue, and broadcasts world frames to connected WebSocket clients. Simple
orders (retrieve/store/home) load one crane trajectory. A `cycle` order runs a
whole material-flow sequence - crane pulls a carrier from a bay, sets it on the
belt, the belt conveys it to the gripper end, the VGR picks it, bakes it in the
Brennofen (Ofenschieber in, door shut, lamp on) and delivers it - by stepping
through a list of phases and tracking where the carrier is.

Still no Redis/MQTT/database: the command-in, frames-out shape matches the
eventual design so the browser contract will not change when those land.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from stf_kernel import (
    Kernel,
    PlanError,
    Trajectory,
)
from stf_layout import Layout, get_layout

from . import wire
from .cycle import (
    FLAVORS,
    HBW_DEPOSIT_MM,
    OVEN_DOOR_RATE,
    OVEN_SLIDER_RATE,
    Order,
    Phase,
    build_cycle,
    simple_plan,
)

#: How often a world frame is pushed to browsers. The kernel integrates far
#: faster (100 Hz); 30 Hz is plenty for the eye and keeps bandwidth modest.
BROADCAST_HZ = 30.0

#: Guard against a scheduling stall: if the loop is starved, never advance the
#: physics by more than this in one wake, or a hiccup would teleport the crane.
MAX_STEP_SECONDS = 0.1


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
        self._phases: list[Phase] = []
        self._phase_i = 0
        self._carrier: dict[str, Any] = {"flavor": None, "holder": None, "slot": None}
        # Brennofen state: Ofenschieber (1.0 = ausgefahren/out, 0.0 = inside the
        # chamber), Ofentuer (1.0 = open, 0.0 = closed), oven lamp. The machine
        # idles ready to receive: slider out, door open, lamp off.
        self._oven: dict[str, Any] = {"slider": 1.0, "door": 1.0, "lamp": False}
        self._oven_target = {"slider": 1.0, "door": 1.0}
        self._flavor_i = 0
        self._next_id = 1
        self._seq = 0
        self._running = False
        self._task: asyncio.Task | None = None

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
        """Queue an order. Planning happens when the machine is free."""
        if op not in ("retrieve", "store", "home", "cycle"):
            raise ValueError(f"unknown op {op!r}; use retrieve, store, home or cycle")
        if op in ("retrieve", "store", "cycle"):
            if not slot or not self.layout.main_rack.contains(slot):
                raise ValueError(f"op {op!r} needs a valid slot, got {slot!r}")
        order = Order(id=self._next_id, op=op, slot=slot)
        self._next_id += 1
        self._pending.append(order)
        self._history.append(order)
        return order

    def orders(self) -> list[dict[str, Any]]:
        return [o.as_dict() for o in self._history[-20:]]

    # -- cycle construction ------------------------------------------------

    def _build_cycle(self, slot: str) -> list[Phase]:
        return build_cycle(self.layout, slot)

    def _simple_plan(self, order: Order) -> Trajectory:
        return simple_plan(self.layout, order, self.kernel.backend.snapshot().joints)

    # -- client fan-out ----------------------------------------------------

    def add_client(self, ws: Any) -> None:
        self._clients.add(ws)

    def remove_client(self, ws: Any) -> None:
        self._clients.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def _broadcast(self, message: dict[str, Any]) -> None:
        """Push to every client, evicting any that cannot keep up in time."""
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
        frame = wire.frame(self.kernel.backend.snapshot(), self._seq)
        frame["carrier"] = dict(self._carrier)
        frame["oven"] = dict(self._oven)
        return frame

    # -- the loop ----------------------------------------------------------

    async def _run(self) -> None:
        last = time.perf_counter()
        last_broadcast = 0.0
        interval = 1.0 / BROADCAST_HZ

        while self._running:
            now = time.perf_counter()
            dt = min(now - last, MAX_STEP_SECONDS)
            last = now

            self._service()
            self.kernel.advance(dt * self.time_scale)
            self._animate_oven(dt * self.time_scale)

            if now - last_broadcast >= interval:
                self._seq += 1
                await self._broadcast(self.latest_frame())
                last_broadcast = now

            await asyncio.sleep(1.0 / (BROADCAST_HZ * 2))

    # -- order + phase servicing ------------------------------------------

    def _service(self) -> None:
        if self._active is None:
            self._start_next()
            return
        if self._phases:
            self._step_phase()
        elif not self.kernel.backend.busy:
            self._active.status = "completed"
            self._active = None

    def _start_next(self) -> None:
        if not self._pending:
            return
        order = self._pending.popleft()
        try:
            if order.op == "cycle":
                self._carrier = {
                    "flavor": FLAVORS[self._flavor_i % len(FLAVORS)],
                    "holder": None,
                    "slot": order.slot,
                }
                self._flavor_i += 1
                self._phases = self._build_cycle(order.slot)
                self._phase_i = 0
            else:
                self._phases = []
                self.kernel.load(self._simple_plan(order))
        except PlanError as exc:
            order.status = "failed"
            order.error = str(exc)
            return
        order.status = "running"
        self._active = order

    def _step_phase(self) -> None:
        if self._phase_i >= len(self._phases):
            self._phases = []
            if self._active:
                self._active.status = "completed"
            self._active = None
            # The delivered carrier stays visible on the pad; the next cycle
            # replaces it when it seeds a fresh carrier in the bay.
            return

        phase = self._phases[self._phase_i]
        sim_t = self.kernel.backend.snapshot().sim_time

        if phase.kind == "carrier":
            self._carrier["holder"] = phase.holder
            if phase.clear_belt:
                self.kernel.backend.clear_belt()
            self._advance_phase()
            return

        if phase.kind == "wait":
            if phase._start_sim == 0.0:
                phase._start_sim = sim_t
            if sim_t - phase._start_sim >= phase.seconds:
                self._advance_phase()
            return

        if phase.kind == "trajectory":
            self._step_trajectory(phase, sim_t)
            return

        if phase.kind == "belt":
            self._step_belt(phase)
            return

        if phase.kind == "oven":
            self._step_oven(phase, sim_t)
            return

    def _animate_oven(self, dt: float) -> None:
        """Chase the slider/door targets at the drives' honest speeds."""
        for key, rate in (("slider", OVEN_SLIDER_RATE), ("door", OVEN_DOOR_RATE)):
            cur = self._oven[key]
            tgt = self._oven_target[key]
            if cur < tgt:
                self._oven[key] = min(tgt, cur + rate * dt)
            elif cur > tgt:
                self._oven[key] = max(tgt, cur - rate * dt)

    def _step_oven(self, phase: Phase, sim_t: float) -> None:
        """
        Brennofen choreography (manual p31). The door must be open whenever the
        Ofenschieber moves - the slider never travels through a closed door.
        """
        if phase.action == "slide_in":
            self._oven_target["door"] = 1.0
            if self._oven["door"] >= 0.98:
                self._oven_target["slider"] = 0.0
            if self._oven["slider"] <= 0.02:
                self._advance_phase()
            return

        if phase.action == "slide_out":
            self._oven_target["door"] = 1.0
            if self._oven["door"] >= 0.98:
                self._oven_target["slider"] = 1.0
            if self._oven["slider"] >= 0.98:
                self._advance_phase()
            return

        if phase.action == "bake":
            if phase._sub == 0:
                # slider is inside; close the door, then switch the lamp on
                self._oven_target["door"] = 0.0
                if self._oven["door"] <= 0.02:
                    self._oven["lamp"] = True
                    phase._start_sim = sim_t
                    phase._sub = 1
                return
            if phase._sub == 1:
                if sim_t - phase._start_sim >= phase.seconds:
                    self._oven["lamp"] = False
                    self._oven_target["door"] = 1.0
                    phase._sub = 2
                return
            if self._oven["door"] >= 0.98:
                self._advance_phase()
            return

    def _step_trajectory(self, phase: Phase, sim_t: float) -> None:
        if phase._traj is None:
            joints = self.kernel.backend.snapshot().joints
            traj = phase.plan_fn(joints)  # type: ignore[misc]
            phase._traj = traj
            phase._start_sim = sim_t
            # resolve carrier markers to absolute sim-times from segment ends
            elapsed = 0.0
            for seg in traj.segments:
                elapsed += seg.duration
                for substr, holder in phase.markers:
                    if substr in seg.description:
                        phase._marker_times.append((sim_t + elapsed, holder))
            self.kernel.load(traj)
            return

        # apply any carrier transition whose time has passed
        for i, (t, holder) in enumerate(phase._marker_times):
            if i > phase._last_holder_idx and sim_t >= t:
                phase._last_holder_idx = i
                self._carrier["holder"] = holder
                if holder == "belt" and phase.place_on_deposit:
                    self.kernel.backend.place_on_belt(HBW_DEPOSIT_MM)

        if not self.kernel.backend.busy:
            self._advance_phase()

    def _step_belt(self, phase: Phase) -> None:
        snap = self.kernel.backend.snapshot()
        obj = snap.belt_object_mm
        if obj is None:
            self.kernel.backend.set_belt(False)
            self._advance_phase()
            return
        if phase._start_sim == 0.0:
            phase._start_sim = snap.sim_time
            self.kernel.backend.set_belt(True, phase.belt_dir)
        reached = obj <= phase.belt_target_mm if phase.belt_dir < 0 else obj >= phase.belt_target_mm
        if reached:
            self.kernel.backend.set_belt(False)
            self._advance_phase()

    def _advance_phase(self) -> None:
        self._phase_i += 1
