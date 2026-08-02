"""
Planner and trajectory tests.

The headline test here is :func:`test_planner_and_integrator_agree`. The
original repository shipped two kinematic engines - a sequential analytic
planner and a simultaneous-axis integrator - that were never checked against
each other, so nobody could have noticed they disagreed about the fork stroke
(50 mm vs 80 mm) or about which shelf row A was. Cross-validating them is the
test that would have caught it.
"""

from __future__ import annotations

import pytest

from stf_kernel import (
    ACCEL_FACTOR,
    DEAD_ZONE,
    DECEL_FACTOR,
    Kernel,
    PlanError,
    Trajectory,
    check_square_path,
    make_segment,
    plan_home,
    plan_retrieve,
    plan_store,
    profile_duration,
)
from stf_kernel.planner import FORK, LIFT, TRAVEL
from stf_layout import Layout

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# Trapezoidal profiles
# --------------------------------------------------------------------------


def test_long_move_reaches_top_speed(layout: Layout) -> None:
    top = layout.joint(TRAVEL).drive.max_speed
    duration, peak = profile_duration(300.0, top)

    assert peak == pytest.approx(top), "a 300mm move should reach cruise"

    # A trapezoid costs the cruise time plus half of each ramp: the ramps still
    # cover ground, so they add t_a/2 + t_d/2 rather than their full duration.
    overhead = 1.0 / (2.0 * ACCEL_FACTOR) + 1.0 / (2.0 * DECEL_FACTOR)
    assert duration == pytest.approx(300.0 / top + overhead, abs=1e-6)


def test_short_move_is_triangular(layout: Layout) -> None:
    top = layout.joint(TRAVEL).drive.max_speed
    _, peak = profile_duration(0.5, top)
    assert peak < top, "a 0.5mm move cannot reach top speed"


def test_profile_is_monotonic_in_distance(layout: Layout) -> None:
    top = layout.joint(TRAVEL).drive.max_speed
    durations = [profile_duration(d, top)[0] for d in (1, 10, 50, 100, 300)]
    assert durations == sorted(durations)


def test_segment_position_is_continuous_and_lands_on_target(layout: Layout) -> None:
    seg = make_segment(layout, TRAVEL, 0.0, 300.0, "test")
    assert seg is not None

    assert seg.position_at(0.0) == pytest.approx(0.0)
    assert seg.position_at(seg.duration) == pytest.approx(300.0)
    assert seg.position_at(seg.duration * 2) == pytest.approx(300.0), "must hold after arrival"

    samples = [seg.position_at(seg.duration * f / 50) for f in range(51)]
    assert samples == sorted(samples), "a one-way move must not reverse"


def test_segment_handles_negative_direction(layout: Layout) -> None:
    seg = make_segment(layout, TRAVEL, 300.0, 100.0, "back")
    assert seg is not None
    assert seg.direction == -1
    assert seg.position_at(seg.duration) == pytest.approx(100.0)
    assert seg.position_at(seg.duration / 2) < 300.0


# --------------------------------------------------------------------------
# Dead zone and limits
# --------------------------------------------------------------------------


def test_sub_dead_zone_move_is_dropped(layout: Layout) -> None:
    assert make_segment(layout, TRAVEL, 100.0, 100.0 + DEAD_ZONE / 2, "tiny") is None


def test_move_past_a_hard_stop_is_rejected(layout: Layout) -> None:
    lo, hi = layout.joint(TRAVEL).limits
    with pytest.raises(ValueError, match="outside limits"):
        make_segment(layout, TRAVEL, 0.0, hi + 50.0, "too far")
    with pytest.raises(ValueError, match="outside limits"):
        make_segment(layout, TRAVEL, 0.0, lo - 50.0, "too far back")


def test_pulses_match_the_encoder_resolution(layout: Layout) -> None:
    seg = make_segment(layout, TRAVEL, 0.0, 100.0, "100mm")
    assert seg is not None
    assert seg.pulses == 1875, "100mm at 18.75 pulses/mm"


# --------------------------------------------------------------------------
# Choreography
# --------------------------------------------------------------------------


def test_unknown_slot_is_rejected(layout: Layout) -> None:
    with pytest.raises(PlanError, match="unknown slot"):
        plan_retrieve(layout, "D9")
    with pytest.raises(PlanError, match="unknown slot"):
        plan_store(layout, "Z1")


@pytest.mark.parametrize("planner", [plan_retrieve, plan_store])
def test_every_slot_is_plannable(layout: Layout, planner) -> None:
    for slot in layout.all_slots():
        traj = planner(layout, slot)
        assert len(traj) > 0
        assert traj.duration > 0


@pytest.mark.parametrize("planner", [plan_retrieve, plan_store])
def test_square_path_invariant_holds(layout: Layout, planner) -> None:
    """
    The crane's one safety rule: never travel with the fork in the shelving.

    The original asserted this in a test but never enforced it in the planner,
    so a later edit to the choreography could have driven an extended fork
    through a shelf upright.
    """
    for slot in layout.all_slots():
        violations = check_square_path(layout, planner(layout, slot))
        assert not violations, f"{slot}: " + "; ".join(violations)


def test_home_retracts_the_fork_first(layout: Layout) -> None:
    traj = plan_home(layout, start={FORK: 50.0, TRAVEL: 300.0, LIFT: 200.0})
    assert traj.segments[0].joint == FORK
    assert not check_square_path(layout, traj)


def test_retrieve_ends_at_rest(layout: Layout) -> None:
    traj = plan_retrieve(layout, "A1")
    finals = traj.final_targets()
    assert finals[LIFT] == pytest.approx(layout.joint(LIFT).at("rest"))
    assert finals[FORK] == pytest.approx(layout.joint(FORK).at("retracted"))


def test_retrieve_visits_the_slot_then_the_conveyor(layout: Layout) -> None:
    """Order matters: the carrier must be collected before it is delivered."""
    slot_x, _, _ = layout.slot_pose("A1").xyz
    conveyor_x = layout.joint(TRAVEL).at("conveyor")

    travel_targets = [s.target for s in plan_retrieve(layout, "A1") if s.joint == TRAVEL]
    assert travel_targets.index(slot_x) < travel_targets.index(conveyor_x)


def test_store_is_the_mirror_of_retrieve(layout: Layout) -> None:
    slot_x, _, _ = layout.slot_pose("C3").xyz
    conveyor_x = layout.joint(TRAVEL).at("conveyor")

    travel_targets = [s.target for s in plan_store(layout, "C3") if s.joint == TRAVEL]
    assert travel_targets.index(conveyor_x) < travel_targets.index(slot_x)


def test_no_segment_exceeds_a_joint_limit(layout: Layout) -> None:
    for slot in layout.all_slots():
        for planner in (plan_retrieve, plan_store):
            for seg in planner(layout, slot):
                joint = layout.joint(seg.joint)
                assert joint.contains(seg.start), f"{seg.joint} starts outside limits"
                assert joint.contains(seg.target), f"{seg.joint} targets outside limits"


def test_planning_from_a_non_home_start(layout: Layout) -> None:
    """A plan must be valid from wherever the crane actually is."""
    mid = {TRAVEL: 250.0, LIFT: 180.0, FORK: 25.0}
    traj = plan_retrieve(layout, "A1", start=mid)
    assert not check_square_path(layout, traj)
    first_travel = next(s for s in traj if s.joint == TRAVEL)
    assert first_travel.start == pytest.approx(250.0)


# --------------------------------------------------------------------------
# Planner vs integrator - the cross-validation the original never had
# --------------------------------------------------------------------------


@pytest.mark.parametrize("slot", ["A1", "B2", "C3"])
@pytest.mark.parametrize("planner", [plan_retrieve, plan_store])
def test_planner_and_integrator_agree(layout: Layout, slot: str, planner) -> None:
    """
    Run the plan through the physics and confirm the crane ends where the
    planner said it would, to within one encoder pulse.
    """
    traj: Trajectory = planner(layout, slot)
    kernel = Kernel(layout, seed=42)
    final = kernel.run_trajectory(traj)

    for ref, target in traj.final_targets().items():
        tolerance = layout.joint(ref).drive.units_per_pulse()
        assert final.joints[ref] == pytest.approx(target, abs=tolerance), (
            f"{ref} ended at {final.joints[ref]:.4f}, plan said {target:.4f}"
        )


def test_simulated_duration_tracks_the_plan(layout: Layout) -> None:
    """
    Physics should not take dramatically longer than the plan predicted.

    Some lag is expected and correct - each motor spends 500 ms drawing inrush
    before it delivers torque - but a large divergence means the plan's speed
    assumptions do not match the drive.
    """
    traj = plan_retrieve(layout, "B2")
    kernel = Kernel(layout, seed=42)
    final = kernel.run_trajectory(traj)

    assert final.sim_time >= traj.duration
    assert final.sim_time < traj.duration * 1.5, (
        f"physics took {final.sim_time:.1f}s for a {traj.duration:.1f}s plan"
    )


def test_a_move_never_outruns_its_drive(layout: Layout) -> None:
    """No axis may exceed the top speed derived from the lab calibration."""
    kernel = Kernel(layout, seed=42)
    kernel.load(plan_retrieve(layout, "C1"))

    for _ in range(4000):
        state = kernel.step()
        for ref, velocity in state.velocities.items():
            limit = layout.joint(ref).drive.max_speed
            assert abs(velocity) <= limit + 1e-6, f"{ref} moved at {velocity}, limit {limit}"
        if not kernel.backend.busy:
            break


def test_cycle_time_reflects_the_real_hardware(layout: Layout) -> None:
    """
    A retrieve takes about a minute on this machine.

    Guards the 7x speed correction. The old simulator's hardcoded 100 mm/s
    would put this trajectory near 9 s; if this assertion starts failing low,
    the fake speed has crept back in.
    """
    traj = plan_retrieve(layout, "B2")
    assert 40.0 < traj.duration < 90.0, (
        f"retrieve took {traj.duration:.1f}s - expected ~60s at 14.27 mm/s"
    )
