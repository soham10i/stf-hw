"""
The live simulation runtime.

Owns the kernel and advances it in real time on a single asyncio task, drains an
order queue, and broadcasts world frames to connected WebSocket clients. Simple
orders (retrieve/store/home) load one crane trajectory. A `cycle` order runs a
whole material-flow sequence - crane pulls a carrier from a bay, sets it on the
belt, the belt conveys it to the gripper end, and the VGR picks it and delivers
it - by stepping through a list of phases and tracking where the carrier is.

Still no Redis/MQTT/database: the command-in, frames-out shape matches the
eventual design so the browser contract will not change when those land.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from stf_kernel import (
    Kernel,
    PlanError,
    Trajectory,
    plan_home,
    plan_retrieve,
    plan_store,
    plan_vgr_approach_pick,
    plan_vgr_carry_place,
    plan_vgr_stow,
)
from stf_layout import Layout, get_layout

from . import wire

#: How often a world frame is pushed to browsers. The kernel integrates far
#: faster (100 Hz); 30 Hz is plenty for the eye and keeps bandwidth modest.
BROADCAST_HZ = 30.0

#: Guard against a scheduling stall: if the loop is starved, never advance the
#: physics by more than this in one wake, or a hiccup would teleport the crane.
MAX_STEP_SECONDS = 0.1

#: Cookie flavours a carrier can hold, cycled per order.
FLAVORS = ("CHOCO", "VANILLA", "STRAWBERRY")

#: Belt-local coordinate the gripper picks from (the VGR interface, I3 window).
VGR_PICK_MM = 15.0
#: Belt-local coordinate the crane deposits at (the HBW end).
HBW_DEPOSIT_MM = 118.0


@dataclass
class Order:
    id: int
    op: str
    slot: str | None
    status: str = "pending"  # pending -> running -> completed | failed
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "op": self.op, "slot": self.slot,
                "status": self.status, "error": self.error}


@dataclass
class Phase:
    """
    One step of a cycle.

    A `trajectory` phase plans lazily from the current pose (via ``plan_fn``) so
    a VGR move is always computed from where the arm actually is, then completes
    when the kernel is idle. Carrier transitions along a crane move are keyed to
    segment descriptions (``markers``) so the carrier rides the fork from the
    lift and lands on the belt at the place-down, matching the motion.
    """

    kind: str  # "trajectory" | "belt" | "carrier" | "wait"
    plan_fn: Callable[[dict[str, float]], Trajectory] | None = None
    markers: list[tuple[str, str]] = field(default_factory=list)  # (desc substr, holder)
    place_on_deposit: bool = False
    belt_target_mm: float = 0.0
    belt_dir: int = -1
    holder: str | None = None
    clear_belt: bool = False
    seconds: float = 0.0

    # runtime bookkeeping
    _traj: Trajectory | None = None
    _marker_times: list[tuple[float, str]] = field(default_factory=list)
    _start_sim: float = 0.0
    _last_holder_idx: int = -1


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
        """
        The full flow for one carrier: bay -> fork -> belt -> gripper -> delivery.
        """
        L = self.layout
        return [
            # carrier waiting in its bay
            Phase(kind="carrier", holder=f"slot:{slot}"),
            Phase(kind="wait", seconds=0.4),
            # crane pulls it out and sets it on the belt; the carrier follows the
            # fork from the lift and transfers to the belt at the place-down
            Phase(
                kind="trajectory",
                plan_fn=lambda st, s=slot: plan_retrieve(L, s, start=st),
                markers=[("onto the fork", "fork"), ("onto the belt", "belt")],
                place_on_deposit=True,
            ),
            # belt conveys it to the gripper end
            Phase(kind="belt", belt_target_mm=VGR_PICK_MM, belt_dir=-1),
            Phase(kind="wait", seconds=0.5),
            # gripper swings over and lowers onto it
            Phase(kind="trajectory", plan_fn=lambda st: plan_vgr_approach_pick(L, "conveyor", start=st)),
            # grip: the carrier leaves the belt and rides the suction
            Phase(kind="carrier", holder="suction", clear_belt=True),
            Phase(kind="wait", seconds=0.4),
            # carry to delivery and set down
            Phase(kind="trajectory", plan_fn=lambda st: plan_vgr_carry_place(L, "delivery", start=st)),
            Phase(kind="carrier", holder="delivery"),
            Phase(kind="wait", seconds=0.5),
            # gripper stows
            Phase(kind="trajectory", plan_fn=lambda st: plan_vgr_stow(L, start=st)),
        ]

    def _simple_plan(self, order: Order) -> Trajectory:
        start = self.kernel.backend.snapshot().joints
        if order.op == "retrieve":
            return plan_retrieve(self.layout, order.slot, start=start)
        if order.op == "store":
            return plan_store(self.layout, order.slot, start=start)
        return plan_home(self.layout, start=start)

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
                self._carrier = {"flavor": FLAVORS[self._flavor_i % len(FLAVORS)],
                                 "holder": None, "slot": order.slot}
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
            self._carrier = {"flavor": None, "holder": None, "slot": None}
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
