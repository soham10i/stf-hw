"""
Kinematic planning for the High-Bay Warehouse crane.

This is a port of ``KinematicController`` from ``controller/main_controller.py``.
The choreography is preserved move for move - it was the most competent code in
the original repository - but three things changed:

1. Geometry comes from the layout instead of module constants, so the planner
   and the simulator can no longer disagree about where slot A1 is.
2. Axes are named. What the old code called X/Y/Z is ``travel``/``lift``/``fork``;
   the fork is horizontal and the lift vertical, a distinction the single letter
   "Z" actively obscured (the VGR used Z for a *vertical* axis).
3. Moves carry real durations from a trapezoidal profile rather than being
   untimed steps the controller blocked on with a 30 s polling timeout.

The crane never moves diagonally. Every move is a single axis, sequenced so the
fork is clear of the shelving before the carriage travels - the original called
this the "square path" rule and it is the one safety invariant the machine has.
"""

from __future__ import annotations

from dataclasses import dataclass

from stf_layout import Layout

from .trajectory import Segment, Trajectory, make_segment


@dataclass(frozen=True, slots=True)
class PickPlaceOffsets:
    """
    Pick-and-place strategy, in millimetres.

    Not factory geometry - these describe *how* the crane engages a carrier, not
    where anything is, which is why they live here and not in the layout. Values
    are the originals from ``KinematicController``.
    """

    approach: float = 10.0  # drop below the carrier before sliding the fork under it
    lift: float = 10.0      # raise to take the load onto the fork
    hover: float = 10.0     # clearance above the belt before descending
    place: float = 5.0      # descend to set the carrier down


DEFAULT_OFFSETS = PickPlaceOffsets()

TRAVEL = "hbw.travel"
LIFT = "hbw.lift"
FORK = "hbw.fork"


class PlanError(ValueError):
    """Raised when a trajectory cannot be planned."""


class _Builder:
    """Accumulates segments while dead-reckoning the joint state."""

    def __init__(self, layout: Layout, start: dict[str, float]) -> None:
        self._layout = layout
        self._pos = dict(start)
        self._segments: list[Segment] = []

    def move(self, joint_ref: str, target: float, description: str) -> None:
        current = self._pos[joint_ref]
        segment = make_segment(self._layout, joint_ref, current, target, description)
        # A dead-zone move still advances the tracked position: the axis is
        # already there to within a fraction of an encoder count.
        self._pos[joint_ref] = target
        if segment is not None:
            self._segments.append(segment)

    def finish(self, name: str, **metadata: str) -> Trajectory:
        return Trajectory(name=name, segments=tuple(self._segments), metadata=metadata)


def _hbw_state(layout: Layout, start: dict[str, float] | None) -> dict[str, float]:
    """Resolve the crane's starting joint state, defaulting to home."""
    home = layout.home_vector()
    state = {ref: home[ref] for ref in (TRAVEL, LIFT, FORK)}
    if start:
        for ref in (TRAVEL, LIFT, FORK):
            if ref in start:
                state[ref] = start[ref]
    return state


def _require_slot(layout: Layout, slot: str) -> tuple[float, float]:
    """Return a slot's (travel, lift) coordinates, or fail with the valid set."""
    try:
        x, _, z = layout.slot_pose(slot).xyz
    except KeyError as exc:
        raise PlanError(f"unknown slot {slot!r}; valid slots: {layout.all_slots()}") from exc
    return x, z


def plan_retrieve(
    layout: Layout,
    slot: str,
    start: dict[str, float] | None = None,
    offsets: PickPlaceOffsets = DEFAULT_OFFSETS,
) -> Trajectory:
    """
    Plan a retrieval: take the carrier in ``slot`` and set it on the belt.

    Four phases, unchanged from the original:
      1. retract the fork, travel to the slot's column
      2. drop below the carrier, slide the fork in, lift to take the load,
         pull the fork back to the carry stop
      3. travel to the conveyor, hover, lower onto the belt
      4. retract and return to rest
    """
    x, z = _require_slot(layout, slot)
    travel = layout.joint(TRAVEL)
    lift = layout.joint(LIFT)
    fork = layout.joint(FORK)

    b = _Builder(layout, _hbw_state(layout, start))

    # Phase 1 - safe travel to the slot column.
    b.move(FORK, fork.at("retracted"), "retract fork for safe travel")
    b.move(TRAVEL, x, f"travel to column of {slot}")

    # Phase 2 - engage and take the load.
    b.move(LIFT, z - offsets.approach, f"drop below the carrier at {slot}")
    b.move(FORK, fork.at("extended"), "extend fork into the slot")
    b.move(LIFT, z + offsets.lift, "lift to take the carrier onto the fork")
    b.move(FORK, fork.at("carry"), "pull fork back to the carry stop")

    # Phase 3 - deliver to the belt.
    b.move(TRAVEL, travel.at("conveyor"), "travel to the conveyor")
    b.move(LIFT, lift.at("conveyor") + offsets.hover, "hover above the belt")
    b.move(LIFT, lift.at("conveyor") - offsets.place, "lower onto the belt")

    # Phase 4 - clear out.
    b.move(FORK, fork.at("retracted"), "retract fork clear of the belt")
    b.move(TRAVEL, travel.at("rest"), "return to rest")
    b.move(LIFT, lift.at("rest"), "return to rest height")

    return b.finish(f"retrieve:{slot}", operation="retrieve", slot=slot)


def plan_store(
    layout: Layout,
    slot: str,
    start: dict[str, float] | None = None,
    offsets: PickPlaceOffsets = DEFAULT_OFFSETS,
) -> Trajectory:
    """
    Plan a store: take the carrier off the belt and shelve it in ``slot``.

    The mirror of :func:`plan_retrieve`.
    """
    x, z = _require_slot(layout, slot)
    travel = layout.joint(TRAVEL)
    lift = layout.joint(LIFT)
    fork = layout.joint(FORK)

    b = _Builder(layout, _hbw_state(layout, start))

    # Phase 1 - collect from the belt.
    b.move(FORK, fork.at("carry"), "set fork to the carry stop")
    b.move(TRAVEL, travel.at("conveyor"), "travel to the conveyor")
    b.move(LIFT, lift.at("conveyor") - offsets.approach, "drop below the carrier on the belt")
    b.move(LIFT, lift.at("conveyor") + offsets.place, "lift the carrier off the belt")

    # Phase 2 - carry to the shelf.
    b.move(TRAVEL, x, f"travel to column of {slot}")
    b.move(LIFT, z + offsets.lift, f"raise above {slot}")

    # Phase 3 - deposit.
    b.move(FORK, fork.at("extended"), "extend fork into the slot")
    b.move(LIFT, z - offsets.approach, "lower to release the carrier")
    b.move(FORK, fork.at("retracted"), "retract fork out of the slot")

    # Phase 4 - clear out.
    b.move(TRAVEL, travel.at("rest"), "return to rest")
    b.move(LIFT, lift.at("rest"), "return to rest height")

    return b.finish(f"store:{slot}", operation="store", slot=slot)


def plan_home(layout: Layout, start: dict[str, float] | None = None) -> Trajectory:
    """
    Drive the crane back to its reference switches.

    The fork retracts first: homing the carriage with the fork extended would
    drag it through the shelving.
    """
    b = _Builder(layout, _hbw_state(layout, start))
    b.move(FORK, layout.joint(FORK).home, "retract fork before homing")
    b.move(LIFT, layout.joint(LIFT).home, "home the lift onto its reference switch")
    b.move(TRAVEL, layout.joint(TRAVEL).home, "home the carriage onto its reference switch")
    return b.finish("home", operation="home")


def check_square_path(layout: Layout, trajectory: Trajectory) -> list[str]:
    """
    Verify the crane's one safety invariant: the fork must be clear of the
    shelving whenever the carriage travels.

    The original code asserted this in a test but never enforced it in the
    planner, so a future edit to the choreography could have driven an extended
    fork straight into a shelf upright. Returns a list of violations.
    """
    fork_limit = layout.joint(FORK).at("carry")
    fork_pos = layout.home_vector()[FORK]
    violations: list[str] = []

    for i, seg in enumerate(trajectory.segments, 1):
        if seg.joint == FORK:
            fork_pos = seg.target
        elif seg.joint == TRAVEL and fork_pos > fork_limit:
            violations.append(
                f"segment {i}: carriage travels {seg.start:.1f}->{seg.target:.1f} "
                f"with the fork at {fork_pos:.1f}mm (max safe {fork_limit:.1f}mm)"
            )
    return violations


# ---------------------------------------------------------------------------
# Vacuum Gripper Robot
# ---------------------------------------------------------------------------
# The VGR is a cylindrical arm: swivel (rotate the whole column), reach (extend
# the arm), plunge (raise/lower the suction). A pick-and-place is split into
# three trajectories so the runtime has clean seams to attach/detach the carrier
# at the moments the suction actually grips and releases.

SWIVEL = "vgr.swivel"
REACH = "vgr.reach"
PLUNGE = "vgr.plunge"


def _vgr_state(layout: Layout, start: dict[str, float] | None) -> dict[str, float]:
    home = layout.home_vector()
    state = {ref: home[ref] for ref in (SWIVEL, REACH, PLUNGE)}
    if start:
        for ref in (SWIVEL, REACH, PLUNGE):
            if ref in start:
                state[ref] = start[ref]
    return state


def _require_station(layout: Layout, station: str) -> None:
    if station not in layout.joint(SWIVEL).positions:
        known = sorted(layout.joint(SWIVEL).positions)
        raise PlanError(f"unknown VGR station {station!r}; known: {known}")


def plan_vgr_approach_pick(
    layout: Layout, station: str, start: dict[str, float] | None = None
) -> Trajectory:
    """
    Swing to a station and lower the suction onto the workpiece there.

    Ends with the cup down at the pick height - the runtime grips the carrier at
    this seam, then runs :func:`plan_vgr_carry_place`.
    """
    _require_station(layout, station)
    reach = layout.joint(REACH)
    plunge = layout.joint(PLUNGE)

    b = _Builder(layout, _vgr_state(layout, start))
    b.move(PLUNGE, plunge.at("raised"), "raise clear")
    b.move(REACH, reach.at("retracted"), "retract arm")
    b.move(SWIVEL, layout.joint(SWIVEL).at(station), f"swivel to {station}")
    b.move(REACH, reach.at("conveyor"), f"reach over {station}")
    b.move(PLUNGE, plunge.at("pick"), "lower onto workpiece")
    return b.finish(f"vgr-pick:{station}", operation="vgr_pick", station=station)


def plan_vgr_carry_place(
    layout: Layout, station: str, start: dict[str, float] | None = None
) -> Trajectory:
    """Lift the gripped workpiece, swing to ``station`` and set it down."""
    _require_station(layout, station)
    reach = layout.joint(REACH)
    plunge = layout.joint(PLUNGE)

    b = _Builder(layout, _vgr_state(layout, start))
    b.move(PLUNGE, plunge.at("transit"), "lift workpiece")
    b.move(REACH, reach.at("retracted"), "retract arm")
    b.move(SWIVEL, layout.joint(SWIVEL).at(station), f"swivel to {station}")
    b.move(REACH, reach.at("conveyor"), f"reach over {station}")
    b.move(PLUNGE, plunge.at("pick"), "lower to place")
    return b.finish(f"vgr-place:{station}", operation="vgr_place", station=station)


def plan_vgr_stow(layout: Layout, start: dict[str, float] | None = None) -> Trajectory:
    """Raise, retract and swing back to the home angle."""
    reach = layout.joint(REACH)
    plunge = layout.joint(PLUNGE)

    b = _Builder(layout, _vgr_state(layout, start))
    b.move(PLUNGE, plunge.at("raised"), "raise clear")
    b.move(REACH, reach.at("retracted"), "retract arm")
    b.move(SWIVEL, layout.joint(SWIVEL).home, "return to home angle")
    return b.finish("vgr-stow", operation="vgr_stow")


__all__ = [
    "DEFAULT_OFFSETS",
    "FORK",
    "LIFT",
    "PLUNGE",
    "REACH",
    "SWIVEL",
    "TRAVEL",
    "PickPlaceOffsets",
    "PlanError",
    "check_square_path",
    "plan_home",
    "plan_retrieve",
    "plan_store",
    "plan_vgr_approach_pick",
    "plan_vgr_carry_place",
    "plan_vgr_stow",
]
