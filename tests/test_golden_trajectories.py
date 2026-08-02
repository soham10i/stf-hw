"""
Golden-trajectory regression tests.

Eighteen recorded runs - nine slots, retrieve and store - pinned as ``.npz``
arrays. Any change to the layout, the planner or the integrator that moves the
crane differently shows up here as a reviewable diff rather than as a surprise
during a demo.

Regenerate deliberately, never reflexively::

    python -m tests.generate_goldens

The summary printed by that script is the artefact to review: it lists each
trajectory's duration, pulse count and settling time, so a change like the 7x
speed correction reads as "every cycle time went from ~9 s to ~60 s" instead of
as eighteen opaque binary blobs.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from stf_kernel import Kernel, plan_retrieve, plan_store
from stf_layout import Layout

pytestmark = [pytest.mark.golden, pytest.mark.unit]

GOLDEN_DIR = Path(__file__).parent / "golden"
SEED = 42
SAMPLE_HZ = 10.0

OPERATIONS = {"retrieve": plan_retrieve, "store": plan_store}


def golden_path(operation: str, slot: str) -> Path:
    return GOLDEN_DIR / f"{operation}_{slot}.npz"


def record(layout: Layout, operation: str, slot: str) -> dict[str, np.ndarray]:
    """
    Run one trajectory and sample it at a fixed rate.

    Sampling at 10 Hz rather than the 100 Hz physics rate keeps the files small
    while still catching any real change in the motion.
    """
    trajectory = OPERATIONS[operation](layout, slot)
    kernel = Kernel(layout, seed=SEED)
    kernel.load(trajectory)

    order = layout.joint_refs()
    stride = int(kernel.tick_hz / SAMPLE_HZ)
    positions: list[np.ndarray] = []
    errors: list[float] = []

    for i in range(int(600 * kernel.tick_hz)):
        state = kernel.step()
        if i % stride == 0:
            positions.append(state.as_vector(order))
            errors.append(max(abs(e) for e in state.tracking_error.values()))
        if not kernel.backend.busy:
            break

    final = kernel.backend.snapshot()
    return {
        "positions": np.array(positions, dtype=np.float64),
        "tracking_error": np.array(errors, dtype=np.float64),
        "summary": np.array(
            [
                trajectory.duration,
                float(len(trajectory)),
                float(trajectory.total_pulses),
                final.sim_time,
            ],
            dtype=np.float64,
        ),
    }


def _cases() -> list[tuple[str, str]]:
    from stf_layout import load_layout

    return [(op, slot) for op in sorted(OPERATIONS) for slot in load_layout().all_slots()]


@pytest.mark.parametrize(("operation", "slot"), _cases())
def test_trajectory_matches_golden(layout: Layout, operation: str, slot: str) -> None:
    path = golden_path(operation, slot)
    if not path.exists():
        pytest.fail(
            f"missing golden {path.name}; run `python -m tests.generate_goldens` "
            "and review the summary before committing"
        )

    expected = np.load(path)
    actual = record(layout, operation, slot)

    assert actual["positions"].shape == expected["positions"].shape, (
        f"{operation}:{slot} now takes {actual['positions'].shape[0]} samples, "
        f"golden has {expected['positions'].shape[0]}"
    )
    np.testing.assert_allclose(
        actual["positions"],
        expected["positions"],
        atol=1e-6,
        err_msg=f"{operation}:{slot} joint positions drifted",
    )
    np.testing.assert_allclose(
        actual["summary"],
        expected["summary"],
        atol=1e-6,
        err_msg=f"{operation}:{slot} duration/pulse count changed",
    )


def test_goldens_are_complete(layout: Layout) -> None:
    """Every slot must be covered in both directions."""
    expected = {golden_path(op, slot).name for op, slot in _cases()}
    present = {p.name for p in GOLDEN_DIR.glob("*.npz")}
    assert expected <= present, f"missing goldens: {sorted(expected - present)}"
    assert len(expected) == 18


def test_goldens_encode_realistic_cycle_times() -> None:
    """
    A guard against the 7x speed bug returning.

    If someone reintroduces a hardcoded 100 mm/s, every recorded duration
    collapses by roughly an order of magnitude and this fails loudly.
    """
    durations = [float(np.load(p)["summary"][0]) for p in sorted(GOLDEN_DIR.glob("*.npz"))]
    assert durations, "no goldens recorded"
    assert min(durations) > 30.0, (
        f"fastest recorded cycle is {min(durations):.1f}s - suspiciously quick "
        "for a machine that travels at 14.27 mm/s"
    )
