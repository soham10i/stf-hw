#!/usr/bin/env python3
"""
STF Digital Twin - Kinematic Controller Unit Tests

This script validates the KinematicController logic including:
- Pulse calculations (18.75 pulses/mm)
- Square-path motion sequences (no diagonal moves)
- Dead reckoning position tracking
- Collision avoidance (Z never extended during X travel)

Usage:
    python tests/test_kinematics.py
"""

import sys
import os

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import dataclass
from typing import List, Tuple, Dict

# Import from project modules
from controller.main_controller import KinematicController
from database.models import (
    SLOT_COORDINATES_3D,
    REST_POS,
    CONVEYOR_POS,
    PULSES_PER_MM,
    Z_RETRACTED,
    Z_CARRY,
    Z_EXTENDED,
)


# =============================================================================
# TEST UTILITIES
# =============================================================================

@dataclass
class SimulatedPosition:
    """Tracks simulated robot position during test."""
    x: float
    y: float
    z: float
    
    def as_tuple(self) -> Tuple[float, float, float]:
        return (self.x, self.y, self.z)
    
    def update_from_step(self, step: Dict):
        """Update position based on a kinematic step."""
        axis = step['axis']
        target = step['target']
        if axis == 'X':
            self.x = target
        elif axis == 'Y':
            self.y = target
        elif axis == 'Z':
            self.z = target


class TestResult:
    """Collects test results for final summary."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors: List[str] = []
    
    def assert_equal(self, actual, expected, message: str):
        if actual == expected:
            self.passed += 1
            print(f"  ✅ PASS: {message}")
        else:
            self.failed += 1
            error = f"{message} - Expected {expected}, got {actual}"
            self.errors.append(error)
            print(f"  ❌ FAIL: {error}")
    
    def assert_true(self, condition: bool, message: str):
        if condition:
            self.passed += 1
            print(f"  ✅ PASS: {message}")
        else:
            self.failed += 1
            self.errors.append(message)
            print(f"  ❌ FAIL: {message}")
    
    def assert_almost_equal(self, actual: float, expected: float, tolerance: float, message: str):
        if abs(actual - expected) <= tolerance:
            self.passed += 1
            print(f"  ✅ PASS: {message}")
        else:
            self.failed += 1
            error = f"{message} - Expected {expected} ±{tolerance}, got {actual}"
            self.errors.append(error)
            print(f"  ❌ FAIL: {error}")


def print_header(title: str):
    """Print a formatted section header."""
    print()
    print("=" * 70)
    print(f" {title}")
    print("=" * 70)


def print_subheader(title: str):
    """Print a formatted subsection header."""
    print()
    print(f"--- {title} ---")


# =============================================================================
# TEST: PULSE CALCULATION
# =============================================================================

def test_pulse_calculation(results: TestResult):
    """Test the pulse calculation formula."""
    print_header("TEST 1: Pulse Calculation")
    
    kc = KinematicController()
    
    # Test case 1: 100mm movement (400 -> 300)
    pulses, direction = kc.calc_pulses(300, 400)
    expected_pulses = int(100 * PULSES_PER_MM)  # 100 * 18.75 = 1875
    
    print(f"  Movement: 400mm -> 300mm (100mm backward)")
    print(f"  Expected pulses: {expected_pulses}")
    print(f"  Actual pulses: {pulses}")
    print(f"  Direction: {direction} ({'backward' if direction < 0 else 'forward'})")
    
    results.assert_equal(pulses, expected_pulses, "100mm movement = 1875 pulses")
    results.assert_equal(direction, -1, "Backward direction = -1")
    
    # Test case 2: 200mm movement forward
    pulses2, direction2 = kc.calc_pulses(300, 100)
    expected_pulses2 = int(200 * PULSES_PER_MM)  # 200 * 18.75 = 3750
    
    print()
    print(f"  Movement: 100mm -> 300mm (200mm forward)")
    print(f"  Expected pulses: {expected_pulses2}")
    print(f"  Actual pulses: {pulses2}")
    
    results.assert_equal(pulses2, expected_pulses2, "200mm movement = 3750 pulses")
    results.assert_equal(direction2, 1, "Forward direction = 1")
    
    # Test case 3: Small movement within dead zone
    pulses3, direction3 = kc.calc_pulses(100.05, 100.0)
    
    print()
    print(f"  Movement: 100.0mm -> 100.05mm (0.05mm, within dead zone)")
    print(f"  Pulses: {pulses3}, Direction: {direction3}")
    
    results.assert_equal(pulses3, 0, "Dead zone movement = 0 pulses")
    results.assert_equal(direction3, 0, "Dead zone direction = 0")


# =============================================================================
# TEST: RETRIEVE SEQUENCE FOR A3
# =============================================================================

def test_retrieve_a3_sequence(results: TestResult):
    """Test the retrieve sequence for slot A3."""
    print_header("TEST 2: Retrieve Sequence for A3")
    
    # Setup
    kc = KinematicController()
    slot_name = "A3"
    slot_coords = SLOT_COORDINATES_3D[slot_name]
    
    print(f"  Start Position (REST_POS): X={REST_POS[0]}, Y={REST_POS[1]}, Z={REST_POS[2]}")
    print(f"  Target Slot {slot_name}: X={slot_coords[0]}, Y={slot_coords[1]}, Z={slot_coords[2]}")
    print(f"  Conveyor Position: X={CONVEYOR_POS[0]}, Y={CONVEYOR_POS[1]}, Z={CONVEYOR_POS[2]}")
    
    # Generate sequence
    sequence = kc.generate_retrieve_sequence(slot_name)
    
    print_subheader(f"Generated Sequence ({len(sequence)} steps)")
    
    # Simulate with dead reckoning
    current_pos = SimulatedPosition(x=REST_POS[0], y=REST_POS[1], z=REST_POS[2])
    
    # Track for collision detection
    collision_violations: List[str] = []
    x_move_pulses: List[int] = []  # Collect X movement pulses
    
    print()
    print(f"{'Step':>4} | {'Axis':>4} | {'From':>10} | {'To':>10} | {'Pulses':>6} | {'Dir':>3} | Description")
    print("-" * 90)
    
    for i, step in enumerate(sequence):
        axis = step['axis']
        target = step['target']
        pulses = step['pulses']
        direction = step['direction']
        desc = step['description']
        
        # Get current value for this axis
        if axis == 'X':
            from_val = current_pos.x
            x_move_pulses.append(pulses)
        elif axis == 'Y':
            from_val = current_pos.y
        else:  # Z
            from_val = current_pos.z
        
        dir_char = "+" if direction > 0 else "-" if direction < 0 else "="
        
        print(f"{i+1:>4} | {axis:>4} | {from_val:>9.1f}mm | {target:>9.1f}mm | {pulses:>6} | {dir_char:>3} | {desc}")
        
        # === COLLISION CHECK ===
        # Z should never be extended (> Z_CARRY) while X is moving
        if axis == 'X' and current_pos.z > Z_CARRY:
            violation = f"Step {i+1}: X moving while Z={current_pos.z}mm (> {Z_CARRY}mm carry height)"
            collision_violations.append(violation)
        
        # Update position (dead reckoning)
        current_pos.update_from_step(step)
    
    # Print final position
    print("-" * 90)
    print(f"Final Position: X={current_pos.x:.1f}, Y={current_pos.y:.1f}, Z={current_pos.z:.1f}")
    print(f"Expected (REST): X={REST_POS[0]:.1f}, Y={REST_POS[1]:.1f}, Z={REST_POS[2]:.1f}")
    
    print_subheader("Assertions")
    
    # Assert 1: Final position equals REST_POS
    results.assert_almost_equal(current_pos.x, REST_POS[0], 0.1, "Final X = REST_POS X")
    results.assert_almost_equal(current_pos.y, REST_POS[1], 0.1, "Final Y = REST_POS Y")
    results.assert_almost_equal(current_pos.z, REST_POS[2], 0.1, "Final Z = REST_POS Z")
    
    # Assert 2: X movement from 400 -> 300 = 1875 pulses
    # First X move should be from REST (400) to slot A3 (300) = 100mm = 1875 pulses
    first_x_pulses = x_move_pulses[0] if x_move_pulses else 0
    expected_first_x = int(abs(REST_POS[0] - slot_coords[0]) * PULSES_PER_MM)
    
    print()
    print(f"  First X movement: {REST_POS[0]}mm -> {slot_coords[0]}mm")
    print(f"  Expected pulses: {expected_first_x}")
    print(f"  Actual pulses: {first_x_pulses}")
    
    results.assert_equal(first_x_pulses, expected_first_x, 
                        f"X movement (400->300mm) = {expected_first_x} pulses")
    
    # Assert 3: No collision violations
    if collision_violations:
        print()
        print("  ⚠️  Collision Violations Detected:")
        for v in collision_violations:
            print(f"      - {v}")
    
    results.assert_true(len(collision_violations) == 0, 
                       "No Z extension during X travel (collision safety)")


# =============================================================================
# TEST: STORE SEQUENCE
# =============================================================================

def test_store_sequence(results: TestResult):
    """Test the store sequence logic."""
    print_header("TEST 3: Store Sequence for B2")
    
    kc = KinematicController()
    slot_name = "B2"
    slot_coords = SLOT_COORDINATES_3D[slot_name]
    
    print(f"  Start Position (REST_POS): X={REST_POS[0]}, Y={REST_POS[1]}, Z={REST_POS[2]}")
    print(f"  Target Slot {slot_name}: X={slot_coords[0]}, Y={slot_coords[1]}, Z={slot_coords[2]}")
    
    sequence = kc.generate_store_sequence(slot_name)
    
    print_subheader(f"Generated Sequence ({len(sequence)} steps)")
    
    # Verify sequence exists and has steps
    results.assert_true(len(sequence) > 0, "Store sequence has steps")
    
    # Track positions
    current_pos = SimulatedPosition(x=REST_POS[0], y=REST_POS[1], z=REST_POS[2])
    collision_violations = []
    
    print()
    print(f"{'Step':>4} | {'Axis':>4} | {'Target':>10} | {'Pulses':>6} | Description")
    print("-" * 70)
    
    for i, step in enumerate(sequence):
        axis = step['axis']
        target = step['target']
        pulses = step['pulses']
        desc = step['description']
        
        print(f"{i+1:>4} | {axis:>4} | {target:>9.1f}mm | {pulses:>6} | {desc}")
        
        # Collision check
        if axis == 'X' and current_pos.z > Z_CARRY:
            collision_violations.append(f"Step {i+1}: X moving with Z={current_pos.z}")
        
        current_pos.update_from_step(step)
    
    print("-" * 70)
    print(f"Final Position: X={current_pos.x:.1f}, Y={current_pos.y:.1f}, Z={current_pos.z:.1f}")
    
    print_subheader("Assertions")
    
    # Final position should return to REST_POS
    results.assert_almost_equal(current_pos.x, REST_POS[0], 0.1, "Store ends at REST_POS X")
    results.assert_true(len(collision_violations) == 0, "No collision violations in store sequence")


# =============================================================================
# TEST: EDGE CASES
# =============================================================================

def test_edge_cases(results: TestResult):
    """Test edge cases and boundary conditions."""
    print_header("TEST 4: Edge Cases")
    
    kc = KinematicController()
    
    # Test all slots
    print_subheader("Testing All 9 Slots")
    
    for slot_name in SLOT_COORDINATES_3D.keys():
        try:
            seq = kc.generate_retrieve_sequence(slot_name)
            results.assert_true(len(seq) > 0, f"Retrieve sequence for {slot_name} generated")
        except Exception as e:
            results.assert_true(False, f"Retrieve sequence for {slot_name} - ERROR: {e}")
    
    # Test invalid slot
    print_subheader("Testing Invalid Slot")
    
    try:
        kc.generate_retrieve_sequence("D4")  # Invalid slot
        results.assert_true(False, "Invalid slot should raise ValueError")
    except ValueError as e:
        results.assert_true(True, f"Invalid slot raises ValueError: {e}")
    except Exception as e:
        results.assert_true(False, f"Unexpected exception: {e}")


# =============================================================================
# TEST: FULL ROUND TRIP
# =============================================================================

def test_full_round_trip(results: TestResult):
    """Test a complete retrieve + store round trip."""
    print_header("TEST 5: Full Round Trip (Retrieve + Store)")
    
    kc = KinematicController()
    slot_name = "C3"  # Top-right corner slot
    
    print(f"  Simulating full cycle for slot {slot_name}")
    print(f"  Slot coordinates: {SLOT_COORDINATES_3D[slot_name]}")
    
    # Phase 1: Retrieve
    retrieve_seq = kc.generate_retrieve_sequence(slot_name)
    
    # Simulate retrieve
    pos = SimulatedPosition(x=REST_POS[0], y=REST_POS[1], z=REST_POS[2])
    for step in retrieve_seq:
        pos.update_from_step(step)
    
    print(f"  After RETRIEVE: X={pos.x:.1f}, Y={pos.y:.1f}, Z={pos.z:.1f}")
    
    # Phase 2: Store (from REST_POS again, simulating conveyor pickup)
    # Reset kinematics position tracker
    kc2 = KinematicController()
    store_seq = kc2.generate_store_sequence(slot_name)
    
    pos2 = SimulatedPosition(x=REST_POS[0], y=REST_POS[1], z=REST_POS[2])
    for step in store_seq:
        pos2.update_from_step(step)
    
    print(f"  After STORE: X={pos2.x:.1f}, Y={pos2.y:.1f}, Z={pos2.z:.1f}")
    
    print_subheader("Assertions")
    
    # Both should end at REST_POS
    results.assert_almost_equal(pos.x, REST_POS[0], 0.1, "Retrieve ends at REST X")
    results.assert_almost_equal(pos.y, REST_POS[1], 0.1, "Retrieve ends at REST Y")
    results.assert_almost_equal(pos2.x, REST_POS[0], 0.1, "Store ends at REST X")
    results.assert_almost_equal(pos2.y, REST_POS[1], 0.1, "Store ends at REST Y")
    
    # Calculate total travel distance
    total_retrieve_pulses = sum(s['pulses'] for s in retrieve_seq)
    total_store_pulses = sum(s['pulses'] for s in store_seq)
    
    print()
    print(f"  Total retrieve pulses: {total_retrieve_pulses}")
    print(f"  Total store pulses: {total_store_pulses}")
    print(f"  Combined cycle pulses: {total_retrieve_pulses + total_store_pulses}")


# =============================================================================
# MAIN TEST RUNNER
# =============================================================================

def main():
    """Run all tests and print summary."""
    print()
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║       STF DIGITAL TWIN - KINEMATIC CONTROLLER UNIT TESTS             ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")
    
    print()
    print(f"Configuration:")
    print(f"  PULSES_PER_MM: {PULSES_PER_MM}")
    print(f"  Z_RETRACTED:   {Z_RETRACTED} mm")
    print(f"  Z_CARRY:       {Z_CARRY} mm")
    print(f"  Z_EXTENDED:    {Z_EXTENDED} mm")
    print(f"  REST_POS:      {REST_POS}")
    print(f"  CONVEYOR_POS:  {CONVEYOR_POS}")
    
    results = TestResult()
    
    # Run all tests
    test_pulse_calculation(results)
    test_retrieve_a3_sequence(results)
    test_store_sequence(results)
    test_edge_cases(results)
    test_full_round_trip(results)
    
    # Print summary
    print()
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║                         TEST SUMMARY                                  ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")
    print()
    print(f"  Total Tests:  {results.passed + results.failed}")
    print(f"  Passed:       {results.passed} ✅")
    print(f"  Failed:       {results.failed} ❌")
    print()
    
    if results.failed > 0:
        print("  Failed Tests:")
        for error in results.errors:
            print(f"    - {error}")
        print()
        print("  ❌ TESTS FAILED")
        return 1
    else:
        print("  ✅ ALL TESTS PASSED")
        return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
