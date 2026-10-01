"""
Invariants that keep the layout the single source of truth.

These are the gate for the whole rearchitecture. The repository previously
carried four contradictory slot-coordinate tables and two disagreeing values for
the fork stroke; the planner and the physics engine operated in different
frames, so nothing the dashboard drew was geometrically trustworthy.

The tests below are cheap and unglamorous, and they are the reason that cannot
silently happen again.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stf_layout import JointKind, Layout, LayoutError, RowOrder, load_layout
from stf_layout.loader import DEFAULT_LAYOUT_PATH

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# 1. No hardcoded geometry anywhere in the source tree
# --------------------------------------------------------------------------

#: Tokens that betray geometry living outside the layout file. Each one is a
#: real identifier from the pre-rearchitecture code.
FORBIDDEN_TOKENS = (
    "SLOT_COORDINATES",
    "SLOT_COORDS_3D",
    "Z_RETRACTED",
    "Z_CARRY",
    "Z_EXTENDED",
    "FORK_EXTENSION_MM",
    "PULSES_PER_MM",
    "SPINDLE_PITCH_MM",
    "POS_HBW_INTERFACE",
    "POS_VGR_INTERFACE",
    "TRAIL_RIB_SPACING_MM",
    "SENSOR_TOLERANCE_MM",
    "REST_POS",
    "CONVEYOR_POS",
    "max_velocity: float = 100",
)

#: Directories that predate the rearchitecture and are scheduled for deletion.
#: They are excluded so the gate can be enforced on new code from day one
#: rather than waiting for the migration to finish. Entries are removed as each
#: legacy module is retired; the list reaching empty is the definition of done.
LEGACY_PATHS = (
    "api",
    "controller",
    "dashboard",
    "database",
    "hardware",
    "scripts",
    "tests/legacy",
)

SCANNED_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx"}


def _is_legacy(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    return any(rel == p or rel.startswith(f"{p}/") for p in LEGACY_PATHS)


def _source_files(root: Path) -> list[Path]:
    # .claude holds agent worktrees: full copies of the repo at other commits
    skip_dirs = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", "docs", ".claude"}
    out: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if _is_legacy(path, root):
            continue
        out.append(path)
    return out


def test_no_hardcoded_geometry(repo_root: Path) -> None:
    """
    Geometry must come from factory.layout.yaml, not from a constant.

    The layout package itself is exempt - it is where these concepts are
    legitimately named - as is this test file, which has to spell the tokens out.
    """
    exempt = {
        repo_root / "packages" / "stf_layout" / "schema.py",
        repo_root / "packages" / "stf_layout" / "loader.py",
        Path(__file__).resolve(),
    }

    violations: list[str] = []
    for path in _source_files(repo_root):
        if path.resolve() in exempt:
            continue
        text = path.read_text(errors="ignore")
        for token in FORBIDDEN_TOKENS:
            if token in text:
                rel = path.relative_to(repo_root)
                violations.append(f"{rel}: {token}")

    assert not violations, (
        "geometry must live in factory.layout.yaml, not in source:\n  "
        + "\n  ".join(violations)
    )


# --------------------------------------------------------------------------
# 2. A slot resolves to exactly one place, for everyone
# --------------------------------------------------------------------------


def test_slot_frame_is_singular(layout: Layout) -> None:
    """
    Every consumer must agree on where a slot is.

    This is the direct regression test for the original defect: the controller
    planned a retrieve from A1 at (100, 100, 50) while the simulator moved to
    A1 at (0, 200) with the rack rows inverted.
    """
    for slot in layout.all_slots():
        via_layout = layout.slot_pose(slot)
        via_rack = layout.main_rack.slot_pose(slot)
        assert via_layout == via_rack, f"{slot} resolves inconsistently"


def test_slot_grid_is_regular(layout: Layout) -> None:
    rack = layout.main_rack
    a1 = rack.slot_pose("A1").xyz
    a2 = rack.slot_pose("A2").xyz
    b1 = rack.slot_pose("B1").xyz

    assert a2[0] - a1[0] == pytest.approx(rack.cols.pitch), "columns run along +X"
    assert a2[2] == pytest.approx(a1[2]), "a column change must not change height"
    assert b1[2] - a1[2] == pytest.approx(rack.rows.pitch), "rows run along +Z"
    assert b1[0] == pytest.approx(a1[0]), "a row change must not change travel"


def test_row_order_declared_once(layout: Layout) -> None:
    """`order: bottom_up` must actually govern which row is lower."""
    rack = layout.main_rack
    a1_z = rack.slot_pose("A1").xyz[2]
    c1_z = rack.slot_pose("C1").xyz[2]

    if rack.order is RowOrder.BOTTOM_UP:
        assert a1_z < c1_z, "bottom_up means row A is the lowest shelf"
    else:
        assert a1_z > c1_z, "top_down means row A is the highest shelf"


def test_unknown_slot_raises(layout: Layout) -> None:
    with pytest.raises(KeyError):
        layout.slot_pose("D4")
    with pytest.raises(KeyError):
        layout.slot_pose("A9")


# --------------------------------------------------------------------------
# 3. Every slot is actually reachable
# --------------------------------------------------------------------------


def test_all_slots_within_joint_limits(layout: Layout) -> None:
    """
    A layout that describes shelves the crane cannot reach is a broken layout,
    and it should fail here rather than as a mid-demo timeout.
    """
    travel = layout.joint("hbw.travel")
    lift = layout.joint("hbw.lift")

    for slot in layout.all_slots():
        x, _, z = layout.slot_pose(slot).xyz
        assert travel.contains(x), f"{slot} at x={x} is outside travel limits {travel.limits}"
        assert lift.contains(z), f"{slot} at z={z} is outside lift limits {lift.limits}"


def test_conveyor_is_reachable_by_hbw(layout: Layout) -> None:
    travel = layout.joint("hbw.travel")
    lift = layout.joint("hbw.lift")

    assert travel.contains(travel.at("conveyor"))
    assert lift.contains(lift.at("conveyor"))

    belt_z = layout.conveyor.pose.xyz[2]
    assert lift.at("conveyor") == pytest.approx(belt_z), (
        "the crane's conveyor lift height must match the belt surface height"
    )


def test_fork_reaches_slot_depth(layout: Layout) -> None:
    """The fork must extend at least as far as a slot is deep."""
    fork = layout.joint("hbw.fork")
    slot_depth = layout.main_rack.slot_envelope[1]
    assert fork.at("extended") >= slot_depth, (
        f"fork extends {fork.at('extended')}mm but slots are {slot_depth}mm deep"
    )
    assert fork.at("retracted") < fork.at("carry") < fork.at("extended")


# --------------------------------------------------------------------------
# 4. Derived physics, not hardcoded physics
# --------------------------------------------------------------------------


def test_speed_is_derived_from_the_lab_calibration(layout: Layout) -> None:
    """
    The old simulator hardcoded 100 mm/s while the lab calibration
    (214 rpm, 75 pulses/rev, 4 mm pitch) implies 14.27 mm/s - it ran 7.01x too
    fast, so every cycle time and energy figure it reported was wrong.
    """
    drive = layout.joint("hbw.travel").drive

    assert drive.pulses_per_mm == pytest.approx(18.75)
    assert drive.sec_per_pulse == pytest.approx(0.0037383, abs=1e-6)
    assert drive.max_speed == pytest.approx(14.2667, abs=1e-3)
    assert drive.max_speed < 20.0, "a speed near 100 mm/s means the old value crept back"


def test_prismatic_and_revolute_drives_are_distinguished(layout: Layout) -> None:
    for ref in layout.joint_refs():
        joint = layout.joint(ref)
        if joint.kind is JointKind.PRISMATIC:
            assert joint.drive.spindle_pitch_mm is not None
            with pytest.raises(AttributeError):
                _ = joint.drive.pulses_per_deg
        else:
            assert joint.drive.gear_ratio is not None
            with pytest.raises(AttributeError):
                _ = joint.drive.pulses_per_mm


def test_vgr_swivel_is_revolute(layout: Layout) -> None:
    """
    docs/recovered/FACTORY_SPECS.md records VGR M3 as "Motor rotate
    clockwise/counterclockwise". The old simulator modelled the VGR as three
    prismatic axes, so it could never have matched the real machine.
    """
    assert layout.joint("vgr.swivel").kind is JointKind.REVOLUTE


# --------------------------------------------------------------------------
# 5. Wire-format stability
# --------------------------------------------------------------------------


def test_joint_ref_order_is_stable(layout: Layout) -> None:
    """
    joint_refs() defines the binary hot-frame layout streamed to the browser.
    If it is not deterministic, two processes disagree about what byte 12 means.
    """
    assert layout.joint_refs() == layout.joint_refs()
    assert layout.joint_refs() == load_layout().joint_refs()
    assert len(set(layout.joint_refs())) == len(layout.joint_refs())


def test_fingerprint_changes_with_content(tmp_path: Path, layout: Layout) -> None:
    """A browser holding a stale scene graph must be able to detect it."""
    original = layout.fingerprint()
    assert original == load_layout().fingerprint(), "fingerprint must be stable"

    text = DEFAULT_LAYOUT_PATH.read_text().replace("pitch: 120.0", "pitch: 110.0", 1)
    modified = tmp_path / "modified.layout.yaml"
    modified.write_text(text)

    assert load_layout(modified).fingerprint() != original


# --------------------------------------------------------------------------
# 6. The layout rejects incoherent input
# --------------------------------------------------------------------------


def test_named_position_outside_limits_is_rejected(tmp_path: Path) -> None:
    text = DEFAULT_LAYOUT_PATH.read_text().replace(
        "          extended: 85.0", "          extended: 5000.0", 1
    )
    bad = tmp_path / "bad.layout.yaml"
    bad.write_text(text)

    with pytest.raises(LayoutError, match="outside limits"):
        load_layout(bad)


def test_unknown_component_reference_is_rejected(tmp_path: Path) -> None:
    text = DEFAULT_LAYOUT_PATH.read_text().replace(
        "        motor_id: HBW_X", "        motor_id: HBW_NOPE", 1
    )
    bad = tmp_path / "bad.layout.yaml"
    bad.write_text(text)

    with pytest.raises(LayoutError, match="unknown component"):
        load_layout(bad)


def test_mismatched_label_count_is_rejected(tmp_path: Path) -> None:
    text = DEFAULT_LAYOUT_PATH.read_text().replace(
        "      labels: [A, B, C]", "      labels: [A, B]", 1
    )
    bad = tmp_path / "bad.layout.yaml"
    bad.write_text(text)

    with pytest.raises(LayoutError, match="labels"):
        load_layout(bad)
