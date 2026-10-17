"""
What a cycle is: the orders, the phases of one carrier's material flow (bay -> fork -> belt ->
gripper -> oven -> delivery) and the speeds they run at. The runtime (runtime.py) steps
through them in real time and broadcasts the result.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from stf_kernel import (
    Trajectory,
    plan_home,
    plan_retrieve,
    plan_store,
    plan_vgr_approach_pick,
    plan_vgr_carry_place,
    plan_vgr_stow,
)
from stf_layout import Layout

#: Cookie flavours a carrier can hold, cycled per order.
FLAVORS = ("CHOCO", "VANILLA", "STRAWBERRY")

#: Belt-local coordinate the gripper picks from (the VGR interface, I3 window).
VGR_PICK_MM = 15.0
#: Belt-local coordinate the crane deposits at (the HBW end).
HBW_DEPOSIT_MM = 118.0

#: Ofenschieber (oven slider) and Ofentuer (oven door) animation speeds, as a
#: fraction of full travel per sim-second: slider full stroke in 1.4 s, the
#: pneumatic door in 0.9 s. Baking time per workpiece.
OVEN_SLIDER_RATE = 1.0 / 1.4
OVEN_DOOR_RATE = 1.0 / 0.9
OVEN_BAKE_SECONDS = 4.0


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
class Phase:
    """
    One step of a cycle.

    A `trajectory` phase plans lazily from the current pose (via ``plan_fn``) so
    a VGR move is always computed from where the arm actually is, then completes
    when the kernel is idle. Carrier transitions along a crane move are keyed to
    segment descriptions (``markers``) so the carrier rides the fork from the
    lift and lands on the belt at the place-down, matching the motion.
    """

    kind: str  # "trajectory" | "belt" | "carrier" | "wait" | "oven"
    plan_fn: Callable[[dict[str, float]], Trajectory] | None = None
    markers: list[tuple[str, str]] = field(default_factory=list)  # (desc substr, holder)
    place_on_deposit: bool = False
    belt_target_mm: float = 0.0
    belt_dir: int = -1
    holder: str | None = None
    clear_belt: bool = False
    seconds: float = 0.0
    action: str = ""  # oven phases: "slide_in" | "bake" | "slide_out"

    # runtime bookkeeping
    _traj: Trajectory | None = None
    _marker_times: list[tuple[float, str]] = field(default_factory=list)
    _start_sim: float = 0.0
    _last_holder_idx: int = -1
    _sub: int = 0  # sub-state for multi-step phases (oven bake)


def build_cycle(L: Layout, slot: str) -> list[Phase]:
    """
    The full flow for one carrier: bay -> fork -> belt -> gripper -> oven
    (bake) -> delivery. The oven steps mirror the real Multi-
    Bearbeitungsstation (manual p31): the gripper sets the workpiece on the
    EXTENDED Ofenschieber, the door is open; the slider draws it into the
    Brennofen, the pneumatic door closes, the lamp bakes it; then door and
    slider open again for the gripper to pick it back up.
    """
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
        Phase(
            kind="trajectory",
            plan_fn=lambda st: plan_vgr_approach_pick(L, "conveyor", start=st),
        ),
        # grip: the carrier leaves the belt and rides the suction
        Phase(kind="carrier", holder="suction", clear_belt=True),
        Phase(kind="wait", seconds=0.4),
        # carry to the oven and set it on the extended Ofenschieber
        Phase(kind="trajectory", plan_fn=lambda st: plan_vgr_carry_place(L, "oven", start=st)),
        Phase(kind="carrier", holder="oven"),
        Phase(kind="wait", seconds=0.3),
        # bake: slider in, door shut, lamp on; then door and slider open
        Phase(kind="oven", action="slide_in"),
        Phase(kind="oven", action="bake", seconds=OVEN_BAKE_SECONDS),
        Phase(kind="oven", action="slide_out"),
        # gripper takes the baked workpiece back off the slider
        Phase(
            kind="trajectory",
            plan_fn=lambda st: plan_vgr_approach_pick(L, "oven", start=st),
        ),
        Phase(kind="carrier", holder="suction"),
        Phase(kind="wait", seconds=0.4),
        # carry to delivery and set down
        Phase(
            kind="trajectory",
            plan_fn=lambda st: plan_vgr_carry_place(L, "delivery", start=st),
        ),
        Phase(kind="carrier", holder="delivery"),
        Phase(kind="wait", seconds=0.5),
        # gripper stows
        Phase(kind="trajectory", plan_fn=lambda st: plan_vgr_stow(L, start=st)),
    ]


def simple_plan(layout: Layout, order: Order, start: dict[str, float]) -> Trajectory:
    """A one-trajectory order (retrieve, store, home) planned from the current pose."""
    if order.op == "retrieve":
        return plan_retrieve(layout, order.slot, start=start)
    if order.op == "store":
        return plan_store(layout, order.slot, start=start)
    return plan_home(layout, start=start)
