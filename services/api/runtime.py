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
import json
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
from .logging_config import get_logger

logger = get_logger(__name__)

#: How often a world frame is pushed to browsers. The kernel integrates far
#: faster (100 Hz); 30 Hz is plenty for the eye and keeps bandwidth modest.
BROADCAST_HZ = 30.0

#: Guard against a scheduling stall: if the loop is starved, never advance the
#: physics by more than this in one wake, or a hiccup would teleport the crane.
MAX_STEP_SECONDS = 0.1


@dataclass
class SimRuntime:
    """Real-time simulation runtime driving the physics kernel and WebSocket broadcasting.

    Attributes:
        layout: Factory layout defining machine boundaries and rack geometries.
        seed: Random seed for simulation physics and deterministic behavior.
        time_scale: Speed multiplier applied to simulated time elapsed per wall-clock second.
    """

    layout: Layout = field(default_factory=get_layout)
    seed: int = 42
    time_scale: float = 1.0

    def __post_init__(self) -> None:
        """Initialize simulation components, queues, and oven state."""
        self.kernel = Kernel(self.layout, seed=self.seed)
        self._clients: set[Any] = set()
        self._pending: deque[Order] = deque()
        self._active: Order | None = None
        self._history: list[Order] = []
        self._phases: list[Phase] = []
        self._phase_i = 0
        self._carrier: dict[str, Any] = {"flavor": None, "holder": None, "slot": None}
        self._oven: dict[str, Any] = {"slider": 1.0, "door": 1.0, "lamp": False}
        self._oven_target = {"slider": 1.0, "door": 1.0}
        self._flavor_i = 0
        self._next_id = 1
        self._seq = 0
        self._running = False
        self._task: asyncio.Task | None = None

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Start the background simulation loop task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="sim-loop")
        logger.info(
            "Simulation runtime started (time_scale=%.1fx, broadcast=%.0fHz)",
            self.time_scale,
            BROADCAST_HZ,
        )

    async def stop(self) -> None:
        """Stop the background simulation loop and cancel running tasks."""
        self._running = False
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)
            logger.info("Simulation runtime stopped")

    # -- orders ------------------------------------------------------------

    def submit(self, op: str, slot: str | None) -> Order:
        """Queue a factory machine order for execution.

        Args:
            op: Operation name ('retrieve', 'store', 'home', or 'cycle').
            slot: Rack slot target (e.g. 'A1'..'C4'), required for retrieve, store, and cycle.

        Returns:
            Order: The newly created and queued order record.

        Raises:
            ValueError: If op is unknown or the target slot is invalid.
        """
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
        """The most recent factory orders (the /orders payload)."""
        return [o.as_dict() for o in self._history[-20:]]

    # -- cycle construction ------------------------------------------------

    def _build_cycle(self, slot: str) -> list[Phase]:
        return build_cycle(self.layout, slot)

    def _simple_plan(self, order: Order) -> Trajectory:
        return simple_plan(self.layout, order, self.kernel.backend.snapshot().joints)

    # -- client fan-out ----------------------------------------------------

    def add_client(self, ws: Any) -> None:
        """Register a connected WebSocket client to receive world state frames.

        Args:
            ws: Connected FastAPI WebSocket instance.
        """
        self._clients.add(ws)
        logger.debug("Added WebSocket client; total active: %d", len(self._clients))

    def remove_client(self, ws: Any) -> None:
        """Unregister a disconnected WebSocket client.

        Args:
            ws: Disconnected WebSocket instance.
        """
        self._clients.discard(ws)
        logger.debug("Removed WebSocket client; total active: %d", len(self._clients))

    @property
    def client_count(self) -> int:
        """Return the current number of connected WebSocket clients."""
        return len(self._clients)

    async def _broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast a message to all connected clients, evicting clients that time out or
disconnect.

        The frame is encoded once (not once per client), and sent to every client at once, each
        with its own timeout: a slow client is evicted without holding up the others.

        Args:
            message: JSON-serializable message dictionary to broadcast.
        """
        if not self._clients:
            return
        text = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        clients = list(self._clients)

        async def send(ws: Any) -> bool:
            """One frame onto one socket, with a send timeout; False means the socket is gone."""
            try:
                await asyncio.wait_for(ws.send_text(text), timeout=0.5)
                return True
            except Exception as e:
                logger.debug("Evicting disconnected or timed out WebSocket client: %s", e)
                return False

        results = await asyncio.gather(*(send(ws) for ws in clients))
        for ws, ok in zip(clients, results, strict=True):
            if not ok:
                self._clients.discard(ws)

    def latest_frame(self) -> dict[str, Any]:
        """The current snapshot as a numbered wire frame (for late-joining live clients)."""
        frame = wire.frame(self.kernel.backend.snapshot(), self._seq)
        frame["carrier"] = dict(self._carrier)
        frame["oven"] = dict(self._oven)
        return frame

    # -- the loop ----------------------------------------------------------

    async def _run(self) -> None:
        # ticks on fixed deadlines, two per frame: the kernel steps at 60 Hz and every second tick
        # broadcasts, so the stream runs at BROADCAST_HZ exactly. (It polled before, sleeping a
        # 60th of a second and broadcasting once a 30th had passed: 26.8 frames a second, as
        # measured - tests/perf/bench_backend.py.)
        last = time.perf_counter()
        tick = 1.0 / (BROADCAST_HZ * 2)
        deadline = last
        n = 0

        while self._running:
            now = time.perf_counter()
            dt = min(now - last, MAX_STEP_SECONDS)
            last = now

            self._service()
            self.kernel.advance(dt * self.time_scale)
            self._animate_oven(dt * self.time_scale)

            if n % 2 == 0:
                self._seq += 1
                await self._broadcast(self.latest_frame())
            n += 1

            deadline += tick
            behind = time.perf_counter() - deadline
            if behind > 4 * tick:
                # stalled (a long GC, a suspended laptop): start the schedule again from now
                deadline = time.perf_counter()
            await asyncio.sleep(max(0.0, deadline - time.perf_counter()))

    # -- order + phase servicing ------------------------------------------

    def _service(self) -> None:
        """Service pending or active orders, advancing multi-phase cycles or completing jobs."""
        if self._active is None:
            self._start_next()
            return
        if self._phases:
            self._step_phase()
        elif not self.kernel.backend.busy:
            logger.info("Order #%d (%s) completed", self._active.id, self._active.op)
            self._active.status = "completed"
            self._active = None

    def _start_next(self) -> None:
        """Attempt to plan and execute the next queued order."""
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
            logger.warning(
                "Order #%d (%s, slot=%s) planning failed: %s",
                order.id,
                order.op,
                order.slot,
                exc,
            )
            order.status = "failed"
            order.error = str(exc)
            return
        logger.info("Order #%d (%s, slot=%s) started", order.id, order.op, order.slot)
        order.status = "running"
        self._active = order

    def _step_phase(self) -> None:
        """Advance the active cycle through its sequence of material-flow phases."""
        if self._phase_i >= len(self._phases):
            self._phases = []
            if self._active:
                logger.info(
                    "Order #%d (%s) cycle completed all phases",
                    self._active.id,
                    self._active.op,
                )
                self._active.status = "completed"
            self._active = None
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
