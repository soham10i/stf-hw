"""
Determinism guarantees.

Everything downstream depends on these: golden trajectories, reproducible fault
demos, and the ability to replay a recorded run against the twin all require
that the same seed produces the same history, bit for bit.

The original simulator failed this on two counts. It integrated with
``dt = time.time() - last_tick``, so its results were a function of process
scheduling, and it drew from the global ``random`` module, so any other code
consuming randomness shifted its noise stream.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from stf_kernel import Kernel, plan_retrieve
from stf_kernel.motor import MICRO_STOPPAGE_HEALTH
from stf_layout import Layout

pytestmark = pytest.mark.unit


def _degrade(kernel: Kernel, health: float) -> None:
    """
    Age every motor.

    A fresh motor never consumes randomness - the wear model only rolls dice
    below the anomaly threshold - so a determinism test on a pristine factory
    would pass trivially without ever exercising the RNG.
    """
    for motor in kernel.backend._motors.values():
        motor.health_score = health


def _history(layout: Layout, seed: int, ticks: int, health: float = 0.45) -> np.ndarray:
    kernel = Kernel(layout, seed=seed)
    _degrade(kernel, health)
    kernel.load(plan_retrieve(layout, "B2"))

    order = layout.joint_refs()
    rows = np.empty((ticks, len(order) + 1), dtype=np.float64)
    for i in range(ticks):
        state = kernel.step()
        rows[i, : len(order)] = state.as_vector(order)
        rows[i, len(order)] = sum(m["current_amps"] for m in state.motors.values())
    return rows


def _digest(array: np.ndarray) -> str:
    return hashlib.blake2b(np.ascontiguousarray(array).tobytes(), digest_size=16).hexdigest()


# --------------------------------------------------------------------------


def test_same_seed_is_bitwise_identical(layout: Layout) -> None:
    a = _history(layout, seed=42, ticks=4000)
    b = _history(layout, seed=42, ticks=4000)
    assert _digest(a) == _digest(b)


def test_different_seeds_diverge(layout: Layout) -> None:
    """If seeds did not matter, the RNG would not be wired in at all."""
    a = _history(layout, seed=1, ticks=4000)
    b = _history(layout, seed=2, ticks=4000)
    assert _digest(a) != _digest(b)


@pytest.mark.parametrize("seed", [1, 42, 1337])
def test_reset_restores_the_initial_state(layout: Layout, seed: int) -> None:
    """A kernel reset must be indistinguishable from a fresh one."""
    kernel = Kernel(layout, seed=seed)
    _degrade(kernel, 0.45)
    kernel.load(plan_retrieve(layout, "A3"))
    for _ in range(500):
        kernel.step()

    kernel.backend.reset(layout, seed)
    _degrade(kernel, 0.45)
    kernel.load(plan_retrieve(layout, "A3"))
    replayed = np.array([kernel.step().as_vector(layout.joint_refs()) for _ in range(500)])

    fresh_kernel = Kernel(layout, seed=seed)
    _degrade(fresh_kernel, 0.45)
    fresh_kernel.load(plan_retrieve(layout, "A3"))
    fresh = np.array([fresh_kernel.step().as_vector(layout.joint_refs()) for _ in range(500)])

    assert _digest(replayed) == _digest(fresh)


def test_component_rng_streams_are_independent(layout: Layout) -> None:
    """
    Each component draws from its own stream.

    This is what stops a layout edit from invalidating every golden file: add a
    spare motor and the existing motors' noise must not shift. With one shared
    generator the whole history would rotate.
    """
    kernel = Kernel(layout, seed=42)
    motors = kernel.backend._motors
    ids = sorted(motors)
    assert len(ids) >= 2

    draws = {cid: motors[cid].rng.random(50) for cid in ids}
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            assert not np.array_equal(draws[a], draws[b]), f"{a} and {b} share a stream"


def test_no_wall_clock_in_the_physics(layout: Layout) -> None:
    """
    Two runs separated by real time must be identical.

    The original motor model read ``time.time()`` to decide when the startup
    inrush ended, which coupled the physics to wall-clock scheduling.
    """
    import time

    first = _history(layout, seed=7, ticks=1500)
    time.sleep(0.05)
    second = _history(layout, seed=7, ticks=1500)
    assert _digest(first) == _digest(second)


def test_tick_rate_does_not_change_the_wear_outcome(layout: Layout) -> None:
    """
    Wear is a rate, not a per-tick probability.

    The original rolled a fixed 5% chance *per tick*, so running the simulator
    faster made the motors fail sooner. Health decay must depend only on elapsed
    simulated time.
    """
    results = []
    for hz in (50.0, 100.0, 200.0):
        kernel = Kernel(layout, seed=3, tick_hz=hz)
        kernel.load(plan_retrieve(layout, "B2"))
        for _ in range(int(30.0 * hz)):
            kernel.step()
        results.append(kernel.backend.snapshot().motors["HBW_X"]["health_score"])

    assert max(results) - min(results) < 1e-4, (
        f"health after 30s varied with tick rate: {results}"
    )


def test_health_decay_matches_the_documented_rate(layout: Layout) -> None:
    kernel = Kernel(layout, seed=0)
    kernel.load(plan_retrieve(layout, "C3"))
    for _ in range(1000):  # 10 s at 100 Hz
        kernel.step()

    motor = kernel.backend._motors["HBW_X"]
    expected = 1.0 - 0.0001 * motor.accumulated_runtime_sec
    assert motor.health_score == pytest.approx(expected, abs=1e-9)


def test_time_to_failure_is_reported(layout: Layout) -> None:
    kernel = Kernel(layout, seed=0)
    motor = kernel.backend._motors["HBW_X"]

    motor.health_score = 1.0
    assert motor.time_to_failure_hours == pytest.approx(0.5 / 0.0001 / 3600.0)

    motor.health_score = MICRO_STOPPAGE_HEALTH
    assert motor.time_to_failure_hours == 0.0


def test_worn_motors_produce_tracking_error(layout: Layout) -> None:
    """
    Wear must be observable, not merely recorded.

    A degraded motor stalls intermittently, so the axis falls behind its
    command - which is the signal the dashboard is meant to surface.
    """
    healthy = Kernel(layout, seed=5)
    healthy.run_trajectory(plan_retrieve(layout, "B2"))

    worn = Kernel(layout, seed=5)
    _degrade(worn, 0.30)
    worn.run_trajectory(plan_retrieve(layout, "B2"))

    assert worn.backend.max_tracking_error() > healthy.backend.max_tracking_error(), (
        "a worn machine should track worse than a healthy one"
    )
