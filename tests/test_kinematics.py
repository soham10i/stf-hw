#!/usr/bin/env python3
"""
STF Digital Twin - Kinematic Controller Unit Tests (pytest)

Validates the KinematicController logic including:
- Pulse calculations (18.75 pulses/mm)
- Square-path motion sequences (no diagonal moves)
- Dead reckoning position tracking
- Collision avoidance (Z never extended during X travel)
"""

import os
import sys
from dataclasses import dataclass
from typing import Dict, List

import pytest

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from controller.main_controller import KinematicController
from database.models import (
    CONVEYOR_POS,
    PULSES_PER_MM,
    REST_POS,
    SLOT_COORDINATES_3D,
    Z_CARRY,
    Z_EXTENDED,
    Z_RETRACTED,
)


# =============================================================================
# TEST: PULSE CALCULATION
# =============================================================================


@pytest.mark.unit
class TestPulseCalculation:
    """Tests for the pulse calculation formula."""

    def test_100mm_backward_movement(self):
        """100mm movement (400 -> 300) should produce 1875 pulses, direction -1."""
        kc = KinematicController()
        pulses, direction = kc.calc_pulses(300, 400)
        expected_pulses = int(100 * PULSES_PER_MM)  # 100 * 18.75 = 1875
        assert pulses == expected_pulses
        assert direction == -1

    def test_200mm_forward_movement(self):
        """200mm movement (100 -> 300) should produce 3750 pulses, direction +1."""
        kc = KinematicController()
        pulses, direction = kc.calc_pulses(300, 100)
        expected_pulses = int(200 * PULSES_PER_MM)  # 200 * 18.75 = 3750
        assert pulses == expected_pulses
        assert direction == 1

    def test_dead_zone_movement(self):
        """Movement within dead zone (0.05mm) should produce 0 pulses."""
        kc = KinematicController()
        pulses, direction = kc.calc_pulses(100.05, 100.0)
        assert pulses == 0
        assert direction == 0


# =============================================================================
# TEST: RETRIEVE SEQUENCE FOR A3
# =============================================================================


@pytest.mark.unit
class TestRetrieveSequence:
    """Tests for the retrieve sequence generation."""

    def test_retrieve_a3_ends_at_rest_pos(self):
        """Retrieve sequence for A3 should end at REST_POS."""
        kc = KinematicController()
        sequence = kc.generate_retrieve_sequence("A3")

        pos = _simulate_sequence(REST_POS, sequence)

        assert abs(pos.x - REST_POS[0]) <= 0.1
        assert abs(pos.y - REST_POS[1]) <= 0.1
        assert abs(pos.z - REST_POS[2]) <= 0.1

    def test_retrieve_a3_first_x_pulses(self):
        """First X movement in A3 retrieve should match expected pulse count."""
        kc = KinematicController()
        slot_coords = SLOT_COORDINATES_3D["A3"]
        sequence = kc.generate_retrieve_sequence("A3")

        x_move_pulses = [step["pulses"] for step in sequence if step["axis"] == "X"]
        first_x_pulses = x_move_pulses[0] if x_move_pulses else 0
        expected_first_x = int(abs(REST_POS[0] - slot_coords[0]) * PULSES_PER_MM)

        assert first_x_pulses == expected_first_x

    def test_retrieve_a3_no_z_during_x_travel(self):
        """Z should never be extended during X travel (collision safety)."""
        kc = KinematicController()
        sequence = kc.generate_retrieve_sequence("A3")

        violations = _check_collision_violations(REST_POS, sequence)
        assert len(violations) == 0, f"Collision violations: {violations}"


# =============================================================================
# TEST: STORE SEQUENCE
# =============================================================================


@pytest.mark.unit
class TestStoreSequence:
    """Tests for the store sequence generation."""

    def test_store_b2_has_steps(self):
        """Store sequence for B2 should have steps."""
        kc = KinematicController()
        sequence = kc.generate_store_sequence("B2")
        assert len(sequence) > 0

    def test_store_b2_ends_at_rest_pos(self):
        """Store sequence for B2 should end at REST_POS X."""
        kc = KinematicController()
        sequence = kc.generate_store_sequence("B2")

        pos = _simulate_sequence(REST_POS, sequence)
        assert abs(pos.x - REST_POS[0]) <= 0.1

    def test_store_b2_no_collision_violations(self):
        """Store sequence for B2 should have no Z-during-X violations."""
        kc = KinematicController()
        sequence = kc.generate_store_sequence("B2")

        violations = _check_collision_violations(REST_POS, sequence)
        assert len(violations) == 0, f"Collision violations: {violations}"


# =============================================================================
# TEST: EDGE CASES
# =============================================================================


@pytest.mark.unit
class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.mark.parametrize("slot_name", list(SLOT_COORDINATES_3D.keys()))
    def test_retrieve_sequence_all_slots(self, slot_name):
        """Retrieve sequence should be generated for every valid slot."""
        kc = KinematicController()
        seq = kc.generate_retrieve_sequence(slot_name)
        assert len(seq) > 0

    def test_invalid_slot_raises_value_error(self):
        """Generating a retrieve sequence for an invalid slot should raise ValueError."""
        kc = KinematicController()
        with pytest.raises(ValueError):
            kc.generate_retrieve_sequence("D4")


# =============================================================================
# TEST: FULL ROUND TRIP
# =============================================================================


@pytest.mark.unit
class TestFullRoundTrip:
    """Tests for a complete retrieve + store round trip."""

    def test_retrieve_ends_at_rest(self):
        """Retrieve sequence for C3 should end at REST_POS."""
        kc = KinematicController()
        retrieve_seq = kc.generate_retrieve_sequence("C3")
        pos = _simulate_sequence(REST_POS, retrieve_seq)

        assert abs(pos.x - REST_POS[0]) <= 0.1
        assert abs(pos.y - REST_POS[1]) <= 0.1

    def test_store_ends_at_rest(self):
        """Store sequence for C3 should end at REST_POS."""
        kc = KinematicController()
        store_seq = kc.generate_store_sequence("C3")
        pos = _simulate_sequence(REST_POS, store_seq)

        assert abs(pos.x - REST_POS[0]) <= 0.1
        assert abs(pos.y - REST_POS[1]) <= 0.1


# =============================================================================
# HELPERS
# =============================================================================


@dataclass
class _Pos:
    x: float
    y: float
    z: float

    def update_from_step(self, step: Dict):
        axis = step["axis"]
        target = step["target"]
        if axis == "X":
            self.x = target
        elif axis == "Y":
            self.y = target
        elif axis == "Z":
            self.z = target


def _simulate_sequence(start_pos, sequence) -> _Pos:
    pos = _Pos(x=start_pos[0], y=start_pos[1], z=start_pos[2])
    for step in sequence:
        pos.update_from_step(step)
    return pos


def _check_collision_violations(start_pos, sequence) -> List[str]:
    violations = []
    pos = _Pos(x=start_pos[0], y=start_pos[1], z=start_pos[2])
    for i, step in enumerate(sequence):
        if step["axis"] == "X" and pos.z > Z_CARRY:
            violations.append(f"Step {i + 1}: X moving while Z={pos.z}mm (> {Z_CARRY}mm)")
        pos.update_from_step(step)
    return violations


if __name__ == "__main__":
    import pytest as _pytest

    raise SystemExit(_pytest.main([__file__, "-v"]))
