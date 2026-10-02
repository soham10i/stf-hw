"""
Test script for the HBW Kinematic Controller.
Demonstrates pulse calculation and sequence generation.
"""

from controller.main_controller import KinematicController
from database.models import (
    SLOT_COORDINATES_3D, REST_POS, CONVEYOR_POS,
    PULSES_PER_MM, Z_RETRACTED, Z_CARRY, Z_EXTENDED
)


def main():
    print("=" * 70)
    print("HBW KINEMATIC CONTROLLER TEST")
    print("=" * 70)
    
    # Print constants
    print("\n--- Hardware Constants ---")
    print(f"Pulses per mm: {PULSES_PER_MM}")
    print(f"Z Retracted:   {Z_RETRACTED} mm")
    print(f"Z Carry:       {Z_CARRY} mm")
    print(f"Z Extended:    {Z_EXTENDED} mm")
    print(f"REST_POS:      X={REST_POS[0]}, Y={REST_POS[1]}, Z={REST_POS[2]}")
    print(f"CONVEYOR_POS:  X={CONVEYOR_POS[0]}, Y={CONVEYOR_POS[1]}, Z={CONVEYOR_POS[2]}")
    
    # Print slot coordinates
    print("\n--- 3D Slot Coordinates ---")
    for slot, (x, y, z) in SLOT_COORDINATES_3D.items():
        print(f"  {slot}: X={x:5.1f}, Y={y:5.1f}, Z={z:5.1f}")
    
    # Test pulse calculation
    print("\n--- Pulse Calculation Test ---")
    kc = KinematicController()
    
    test_cases = [
        (100, 0, "Move 100mm forward"),
        (200, 100, "Move from 100mm to 200mm"),
        (50, 100, "Move from 100mm to 50mm (backward)"),
        (100.5, 100.4, "Small move (within dead zone)"),
    ]
    
    for target, current, desc in test_cases:
        pulses, direction = kc.calc_pulses(target, current)
        dir_str = "+" if direction > 0 else "-" if direction < 0 else "="
        print(f"  {desc}")
        print(f"    {current}mm -> {target}mm = {pulses} pulses ({dir_str})")
    
    # Generate retrieve sequence
    print("\n--- Retrieve Sequence for B2 ---")
    sequence = kc.generate_retrieve_sequence("B2")
    
    print(f"Total steps: {len(sequence)}")
    print()
    print(f"{'Step':>4} | {'Axis':>4} | {'Target':>8} | {'Pulses':>6} | {'Dir':>3} | Description")
    print("-" * 80)
    
    for i, step in enumerate(sequence):
        dir_char = "+" if step['direction'] > 0 else "-" if step['direction'] < 0 else "="
        print(f"{i+1:>4} | {step['axis']:>4} | {step['target']:>7.1f}mm | {step['pulses']:>6} | {dir_char:>3} | {step['description']}")
    
    # Generate store sequence
    print("\n--- Store Sequence for A1 ---")
    kc2 = KinematicController()  # Fresh controller at REST_POS
    store_sequence = kc2.generate_store_sequence("A1")
    
    print(f"Total steps: {len(store_sequence)}")
    print()
    print(f"{'Step':>4} | {'Axis':>4} | {'Target':>8} | {'Pulses':>6} | {'Dir':>3} | Description")
    print("-" * 80)
    
    for i, step in enumerate(store_sequence):
        dir_char = "+" if step['direction'] > 0 else "-" if step['direction'] < 0 else "="
        print(f"{i+1:>4} | {step['axis']:>4} | {step['target']:>7.1f}mm | {step['pulses']:>6} | {dir_char:>3} | {step['description']}")
    
    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
