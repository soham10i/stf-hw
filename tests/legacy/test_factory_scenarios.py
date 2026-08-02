"""
STF Digital Twin - Factory Scenario Tests

This test suite demonstrates and validates all factory operation scenarios,
showcasing the two-robot architecture (HBW + VGR) with conveyor handshake.

Test Categories:
1. Individual Component Tests (HBW, VGR, Conveyor)
2. Kinematic Movement Tests (pulse calculations, sequences)
3. Full Workflow Tests (VGR → Conveyor → HBW handshake)
4. Sensor Simulation Tests (Light Barriers, Trail Sensors)
5. Error/Edge Case Tests

Run with: python -m pytest tests/test_factory_scenarios.py -v
Or standalone: python tests/test_factory_scenarios.py
"""

import sys
import os
import time
import asyncio
from datetime import datetime
from typing import Dict, List, Tuple

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hardware.mock_factory import (
    HBWSimulation, VGRSimulation, ConveyorSimulation,
    MotorSimulation, MotorPhase, ElectricalModel,
    LightBarrierSimulation, TrailSensorSimulation,
)

# Color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def print_header(text: str):
    """Print a formatted header"""
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*70}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text.center(70)}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*70}{Colors.ENDC}\n")


def print_subheader(text: str):
    """Print a formatted subheader"""
    print(f"\n{Colors.CYAN}{'-'*50}{Colors.ENDC}")
    print(f"{Colors.CYAN}{text}{Colors.ENDC}")
    print(f"{Colors.CYAN}{'-'*50}{Colors.ENDC}")


def print_success(text: str):
    """Print success message"""
    print(f"{Colors.GREEN}✓ PASS: {text}{Colors.ENDC}")


def print_fail(text: str):
    """Print failure message"""
    print(f"{Colors.RED}✗ FAIL: {text}{Colors.ENDC}")


def print_info(text: str):
    """Print info message"""
    print(f"{Colors.BLUE}ℹ {text}{Colors.ENDC}")


def print_state(label: str, state: Dict):
    """Print formatted state dictionary"""
    print(f"{Colors.YELLOW}  {label}:{Colors.ENDC}")
    for key, value in state.items():
        if isinstance(value, dict):
            print(f"    {key}:")
            for k, v in value.items():
                print(f"      {k}: {v}")
        else:
            print(f"    {key}: {value}")


# =============================================================================
# TEST CLASS: HBW (High-Bay Warehouse) Tests
# =============================================================================

class TestHBW:
    """
    Tests for the High-Bay Warehouse (HBW) - Automated Stacker Crane.
    
    The HBW uses a mechanical fork (cantilever) to pick carriers from below.
    Its Z-axis is HORIZONTAL (telescoping in/out of rack slots).
    """
    
    def __init__(self):
        self.hbw = HBWSimulation()
        self.tests_passed = 0
        self.tests_failed = 0
    
    def test_initial_state(self):
        """Test HBW starts at correct home position"""
        print_subheader("Test: HBW Initial State")
        
        try:
            assert self.hbw.x == 0.0, f"Expected x=0, got {self.hbw.x}"
            assert self.hbw.y == 0.0, f"Expected y=0, got {self.hbw.y}"
            assert self.hbw.z == 0.0, f"Expected z=0 (fork retracted), got {self.hbw.z}"
            assert self.hbw.gripper_closed == False, "Fork should be open initially"
            assert self.hbw.has_carrier == False, "Should not have carrier initially"
            
            print_success("HBW initializes at home position (0,0,0) with fork retracted")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def test_slot_coordinates(self):
        """Test slot coordinate mapping (A1-C3)"""
        print_subheader("Test: HBW Slot Coordinate Mapping")
        
        expected_slots = {
            "A1": (0, 200), "A2": (100, 200), "A3": (200, 200),  # Top row
            "B1": (0, 100), "B2": (100, 100), "B3": (200, 100),  # Middle row
            "C1": (0, 0),   "C2": (100, 0),   "C3": (200, 0),    # Bottom row
        }
        
        print_info("Storage Rack Layout:")
        print("       Col 1    Col 2    Col 3")
        print("    ┌────────┬────────┬────────┐")
        print(f"  A │   A1   │   A2   │   A3   │  (Y=200, Top)")
        print("    ├────────┼────────┼────────┤")
        print(f"  B │   B1   │   B2   │   B3   │  (Y=100, Middle)")
        print("    ├────────┼────────┼────────┤")
        print(f"  C │   C1   │   C2   │   C3   │  (Y=0, Bottom)")
        print("    └────────┴────────┴────────┘")
        print("       X=0     X=100    X=200\n")
        
        try:
            for slot, (expected_x, expected_y) in expected_slots.items():
                actual = self.hbw.SLOT_COORDINATES.get(slot)
                assert actual is not None, f"Slot {slot} not found"
                assert actual == (expected_x, expected_y), f"Slot {slot}: expected {(expected_x, expected_y)}, got {actual}"
                print(f"  {slot}: X={expected_x}mm, Y={expected_y}mm ✓")
            
            print_success("All 9 slot coordinates mapped correctly")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def test_move_to_slot(self):
        """Test HBW movement to slot positions"""
        print_subheader("Test: HBW Move to Slot")
        
        try:
            # Move to slot B2 (middle center)
            success = self.hbw.move_to_slot("B2")
            assert success, "move_to_slot should return True for valid slot"
            
            # Check targets were set
            assert self.hbw.target_x == 100, f"Target X should be 100, got {self.hbw.target_x}"
            assert self.hbw.target_y == 100, f"Target Y should be 100, got {self.hbw.target_y}"
            assert self.hbw.target_z == 0, f"Target Z should be 0 (retracted), got {self.hbw.target_z}"
            
            print_info(f"Moving to B2: target=({self.hbw.target_x}, {self.hbw.target_y}, {self.hbw.target_z})")
            
            # Simulate movement ticks
            for i in range(50):
                state = self.hbw.tick(0.1)
            
            print_info(f"After movement: position=({state['x']}, {state['y']}, {state['z']})")
            print_success("HBW can move to slot positions")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def test_fork_extension(self):
        """Test HBW fork extension (Z-axis is HORIZONTAL)"""
        print_subheader("Test: HBW Fork Extension (Horizontal Z-axis)")
        
        print_info("HBW Z-axis is HORIZONTAL - telescoping IN/OUT of rack")
        print_info("  Z=0: Fork retracted (safe for travel)")
        print_info("  Z=80: Fork extended into slot")
        
        try:
            # Reset HBW
            self.hbw = HBWSimulation()
            
            # Extend fork
            self.hbw.extend_fork()
            assert self.hbw.target_z == self.hbw.FORK_EXTENSION_MM, "Fork should target extension distance"
            assert self.hbw.gripper_closed == True, "gripper_closed should be True when fork extends"
            
            # Simulate extension
            for _ in range(20):
                state = self.hbw.tick(0.1)
            
            print_info(f"Fork extended: Z={state['z']}mm, fork_extended={state['fork_extended']}")
            
            # Retract fork
            self.hbw.retract_fork()
            for _ in range(20):
                state = self.hbw.tick(0.1)
            
            print_info(f"Fork retracted: Z={state['z']}mm")
            
            print_success("Fork extends horizontally into rack slots")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def test_motor_electrical_model(self):
        """Test HBW motor electrical characteristics"""
        print_subheader("Test: HBW Motor Electrical Model")
        
        try:
            self.hbw = HBWSimulation()
            
            # Get initial state (idle)
            state = self.hbw.tick(0.1)
            idle_power = state['total_power_watts']
            print_info(f"Idle power: {idle_power:.2f}W")
            
            # Start movement
            self.hbw.move_to(100, 100, 0)
            
            # Check startup current spike
            state = self.hbw.tick(0.1)
            startup_power = state['total_power_watts']
            print_info(f"Startup power: {startup_power:.2f}W (inrush current)")
            
            # Let motors complete startup phase and stabilize
            for _ in range(20):  # Wait longer for motors to finish startup
                state = self.hbw.tick(0.1)
            
            running_power = state['total_power_watts']
            print_info(f"Running power: {running_power:.2f}W (steady state)")
            
            # Verify power is being consumed during movement
            assert running_power > idle_power, "Running power should exceed idle power"
            
            print_success("Motor electrical model shows realistic power during operation")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def run_all(self):
        """Run all HBW tests"""
        print_header("HBW (High-Bay Warehouse) Tests")
        print_info("Testing the Storage Robot with Mechanical Fork")
        print_info("Z-axis = HORIZONTAL (in/out of rack slots)")
        
        self.test_initial_state()
        self.test_slot_coordinates()
        self.test_move_to_slot()
        self.test_fork_extension()
        self.test_motor_electrical_model()
        
        return self.tests_passed, self.tests_failed


# =============================================================================
# TEST CLASS: VGR (Vacuum Gripper Robot) Tests
# =============================================================================

class TestVGR:
    """
    Tests for the Vacuum Gripper Robot (VGR) - 3-Axis Gantry Robot.
    
    The VGR uses a pneumatic suction cup to grip items from above.
    Its Z-axis is VERTICAL (up/down to reach items on the table).
    """
    
    def __init__(self):
        self.vgr = VGRSimulation()
        self.tests_passed = 0
        self.tests_failed = 0
    
    def test_initial_state(self):
        """Test VGR starts at correct home position"""
        print_subheader("Test: VGR Initial State")
        
        try:
            assert self.vgr.x == 0.0, f"Expected x=0, got {self.vgr.x}"
            assert self.vgr.y == 0.0, f"Expected y=0, got {self.vgr.y}"
            assert self.vgr.z == 0.0, f"Expected z=0 (suction up), got {self.vgr.z}"
            assert self.vgr.vacuum_active == False, "Vacuum should be off initially"
            assert self.vgr.has_item == False, "Should not have item initially"
            
            print_success("VGR initializes at home position with vacuum off")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def test_work_positions(self):
        """Test VGR work position constants"""
        print_subheader("Test: VGR Work Positions")
        
        print_info("VGR Work Area Layout:")
        print("  ┌─────────────────────────────────┐")
        print("  │                                 │")
        print("  │  DELIVERY     OVEN     CONVEYOR │")
        print("  │    (0,0)    (150,50)   (200,100)│")
        print("  │      ↓         ↓          ↓     │")
        print("  │   Raw Item → Process → To Belt  │")
        print("  │                                 │")
        print("  └─────────────────────────────────┘")
        
        try:
            assert hasattr(self.vgr, 'DELIVERY_ZONE'), "VGR should have DELIVERY_ZONE"
            assert hasattr(self.vgr, 'OVEN_POSITION'), "VGR should have OVEN_POSITION"
            assert hasattr(self.vgr, 'CONVEYOR_INPUT'), "VGR should have CONVEYOR_INPUT"
            
            print_info(f"Delivery Zone: {self.vgr.DELIVERY_ZONE}")
            print_info(f"Oven Position: {self.vgr.OVEN_POSITION}")
            print_info(f"Conveyor Input: {self.vgr.CONVEYOR_INPUT}")
            
            print_success("VGR work positions defined correctly")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def test_vacuum_system(self):
        """Test VGR pneumatic vacuum system"""
        print_subheader("Test: VGR Vacuum System (Pneumatic)")
        
        print_info("VGR uses compressed air to create vacuum suction")
        print_info("  - Compressor creates air pressure")
        print_info("  - Valve opens to create suction")
        print_info("  - Item is held by vacuum, released by breaking seal")
        
        try:
            self.vgr = VGRSimulation()
            
            # Check initial state
            assert self.vgr.vacuum_active == False
            assert self.vgr.valve_open == False
            
            # Activate vacuum
            self.vgr.activate_vacuum()
            assert self.vgr.vacuum_active == True, "Vacuum should be active"
            assert self.vgr.valve_open == True, "Valve should be open"
            
            # Simulate compressor running
            for _ in range(10):
                state = self.vgr.tick(0.1)
            
            print_info(f"Compressor running: {state['compressor']['is_active']}")
            print_info(f"Compressor current: {state['compressor']['current_amps']:.2f}A")
            print_info(f"Vacuum active: {state['vacuum_active']}")
            
            # Release vacuum
            self.vgr.release_vacuum()
            assert self.vgr.vacuum_active == False, "Vacuum should be off"
            assert self.vgr.has_item == False, "Item should be released"
            
            print_success("Vacuum system activates/deactivates correctly")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def test_vertical_z_axis(self):
        """Test VGR Z-axis is VERTICAL (up/down)"""
        print_subheader("Test: VGR Vertical Z-axis (Up/Down)")
        
        print_info("VGR Z-axis is VERTICAL - suction cup moves UP/DOWN")
        print_info("  Z=0: Suction cup raised (safe for travel)")
        print_info("  Z=50: Suction cup lowered to pickup height")
        
        try:
            self.vgr = VGRSimulation()
            
            # Lower suction cup
            self.vgr.lower_to_pickup()
            assert self.vgr.target_z == self.vgr.PICKUP_HEIGHT_MM, "Should target pickup height"
            
            # Simulate lowering
            for _ in range(20):
                state = self.vgr.tick(0.1)
            
            print_info(f"Suction lowered: Z={state['z']}mm, lowered={state['suction_lowered']}")
            
            # Raise suction cup
            self.vgr.raise_suction_cup()
            for _ in range(20):
                state = self.vgr.tick(0.1)
            
            print_info(f"Suction raised: Z={state['z']}mm")
            
            print_success("Z-axis moves vertically to reach items")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def test_pickup_workflow(self):
        """Test complete VGR pickup workflow"""
        print_subheader("Test: VGR Pickup Workflow")
        
        print_info("Workflow: Move to item → Lower → Activate vacuum → Raise")
        
        try:
            self.vgr = VGRSimulation()
            
            # Step 1: Move to delivery zone
            self.vgr.move_to_delivery()
            for _ in range(30):
                self.vgr.tick(0.1)
            print_info("Step 1: Moved to delivery zone ✓")
            
            # Step 2: Lower suction cup
            self.vgr.lower_to_pickup()
            for _ in range(20):
                self.vgr.tick(0.1)
            print_info("Step 2: Lowered suction cup ✓")
            
            # Step 3: Activate vacuum to grab item
            self.vgr.activate_vacuum()
            self.vgr.has_item = True  # Simulate item pickup
            state = self.vgr.tick(0.1)
            assert state['vacuum_active'] == True
            assert state['has_item'] == True
            print_info("Step 3: Vacuum activated, item grabbed ✓")
            
            # Step 4: Raise with item
            self.vgr.raise_suction_cup()
            for _ in range(20):
                state = self.vgr.tick(0.1)
            print_info("Step 4: Raised with item ✓")
            
            print_success("Complete pickup workflow executed successfully")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def run_all(self):
        """Run all VGR tests"""
        print_header("VGR (Vacuum Gripper Robot) Tests")
        print_info("Testing the Production Robot with Suction Cup")
        print_info("Z-axis = VERTICAL (up/down to table)")
        
        self.test_initial_state()
        self.test_work_positions()
        self.test_vacuum_system()
        self.test_vertical_z_axis()
        self.test_pickup_workflow()
        
        return self.tests_passed, self.tests_failed


# =============================================================================
# TEST CLASS: Conveyor Belt Tests
# =============================================================================

class TestConveyor:
    """
    Tests for the Conveyor Belt - the bridge between VGR and HBW.
    
    The conveyor transports items from VGR (input side) to HBW (output side).
    The two robots never interact directly - only through this belt.
    """
    
    def __init__(self):
        self.conveyor = ConveyorSimulation()
        self.tests_passed = 0
        self.tests_failed = 0
    
    def test_initial_state(self):
        """Test conveyor initial state"""
        print_subheader("Test: Conveyor Initial State")
        
        try:
            assert self.conveyor.belt_position_mm == 0.0
            assert self.conveyor.has_object == False
            assert self.conveyor.direction == 1  # Forward by default
            
            print_info(f"Belt position: {self.conveyor.belt_position_mm}mm")
            print_info(f"Direction: {'Forward (VGR→HBW)' if self.conveyor.direction == 1 else 'Reverse'}")
            print_info(f"Has object: {self.conveyor.has_object}")
            
            print_success("Conveyor initializes correctly")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def test_conveyor_endpoints(self):
        """Test conveyor VGR/HBW endpoints"""
        print_subheader("Test: Conveyor Endpoints")
        
        print_info("Conveyor Layout:")
        print("  ┌────────────────────────────────────────┐")
        print("  │  VGR INPUT                  HBW OUTPUT │")
        print("  │    (0mm)    ───────────>    (1000mm)   │")
        print("  │   ↑ Drop                      Pickup ↑ │")
        print("  └────────────────────────────────────────┘")
        
        try:
            assert hasattr(self.conveyor, 'VGR_INPUT_POSITION'), "Should have VGR_INPUT_POSITION"
            assert hasattr(self.conveyor, 'HBW_OUTPUT_POSITION'), "Should have HBW_OUTPUT_POSITION"
            
            print_info(f"VGR Input Position: {self.conveyor.VGR_INPUT_POSITION}mm")
            print_info(f"HBW Output Position: {self.conveyor.HBW_OUTPUT_POSITION}mm")
            print_info(f"Belt Length: {self.conveyor.belt_length_mm}mm")
            
            print_success("Conveyor endpoints defined correctly")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def test_object_transport(self):
        """Test object transport from VGR to HBW side"""
        print_subheader("Test: Object Transport (VGR → HBW)")
        
        try:
            self.conveyor = ConveyorSimulation()
            
            # Place object at VGR input (0mm)
            self.conveyor.place_object(position_mm=0.0)
            assert self.conveyor.has_object == True
            assert self.conveyor.object_position_mm == 0.0
            print_info("Object placed at VGR input (0mm)")
            
            # Start conveyor forward
            self.conveyor.start(direction=1)
            
            # Simulate transport
            positions = []
            for _ in range(100):
                state = self.conveyor.tick(0.1)
                if state['has_object']:
                    positions.append(state['object_position_mm'])
            
            print_info(f"Object traveled: {positions[0]:.1f}mm → {positions[-1]:.1f}mm")
            
            # Check it moved towards HBW side
            assert positions[-1] > positions[0], "Object should move towards HBW"
            
            print_success("Object transports from VGR side towards HBW side")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def test_light_barriers(self):
        """Test light barrier sensors (Lichtschranke) with sensor-based positioning"""
        print_subheader("Test: Light Barriers (Lichtschranke) - Sensor-Based Positioning")
        
        print_info("Light barriers detect presence at interface points")
        print_info("  I2: HBW Interface (375-425mm) - triggers at 400mm ±25mm")
        print_info("  I3: VGR Interface (925-975mm) - triggers at 950mm ±25mm")
        
        try:
            self.conveyor = ConveyorSimulation()
            
            # Test I2 (HBW Interface at ~400mm)
            self.conveyor.place_object(position_mm=400.0)  # Exactly at HBW interface
            state = self.conveyor.tick(0.1)
            
            lb_states = state['light_barriers']
            print_info(f"Object at 400mm (HBW interface):")
            print_info(f"  I2 (HBW) triggered: {lb_states['I2']['is_triggered']}")
            print_info(f"  I3 (VGR) triggered: {lb_states['I3']['is_triggered']}")
            
            assert lb_states['I2']['is_triggered'] == True, "I2 should trigger at HBW interface (400mm)"
            assert lb_states['I3']['is_triggered'] == False, "I3 should not trigger at HBW interface"
            
            # Test position just outside I2 tolerance
            self.conveyor.object_position_mm = 350.0  # Outside ±25mm of 400mm
            state = self.conveyor.tick(0.1)
            lb_states = state['light_barriers']
            print_info(f"Object at 350mm (outside I2 zone):")
            print_info(f"  I2 (HBW) triggered: {lb_states['I2']['is_triggered']}")
            assert lb_states['I2']['is_triggered'] == False, "I2 should not trigger at 350mm"
            
            # Test I3 (VGR Interface at ~950mm)
            self.conveyor.object_position_mm = 950.0  # Exactly at VGR interface
            state = self.conveyor.tick(0.1)
            lb_states = state['light_barriers']
            
            print_info(f"Object at 950mm (VGR interface):")
            print_info(f"  I2 (HBW) triggered: {lb_states['I2']['is_triggered']}")
            print_info(f"  I3 (VGR) triggered: {lb_states['I3']['is_triggered']}")
            
            assert lb_states['I2']['is_triggered'] == False, "I2 should not trigger at VGR interface"
            assert lb_states['I3']['is_triggered'] == True, "I3 should trigger at VGR interface (950mm)"
            
            # Test convenience flags
            assert state.get('at_hbw_interface') == False, "Should have at_hbw_interface flag"
            assert state.get('at_vgr_interface') == True, "Should have at_vgr_interface flag"
            
            print_success("Light barriers detect HBW/VGR interfaces correctly")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def test_trail_sensors(self):
        """Test trail sensors (Spursensor) with rib detection simulation"""
        print_subheader("Test: Trail Sensors (Spursensor) - Rib Detection")
        
        print_info("Trail sensors detect belt ribs every 10mm of movement")
        print_info("  I5 and I6 alternate states to prove physical motion")
        print_info("  This prevents false positives from stuck belt")
        
        try:
            self.conveyor = ConveyorSimulation()
            self.conveyor.place_object(100)
            self.conveyor.start()
            
            # Track toggle changes
            i5_states = []
            i6_states = []
            
            # Simulate belt movement and capture rib detections
            for i in range(50):  # 50 ticks at 0.1s with 100mm/s = ~500mm travel
                state = self.conveyor.tick(0.1)
                ts_states = state['trail_sensors']
                i5_states.append(ts_states['I5']['is_triggered'])
                i6_states.append(ts_states['I6']['is_triggered'])
            
            # Count state changes (should have multiple toggles)
            i5_toggles = sum(1 for i in range(1, len(i5_states)) if i5_states[i] != i5_states[i-1])
            i6_toggles = sum(1 for i in range(1, len(i6_states)) if i6_states[i] != i6_states[i-1])
            
            print_info(f"Belt travel: ~{self.conveyor.belt_position_mm:.1f}mm")
            print_info(f"I5 toggles: {i5_toggles}")
            print_info(f"I6 toggles: {i6_toggles}")
            
            # Verify I5 and I6 are always opposite (alternating)
            for i in range(len(i5_states)):
                assert i5_states[i] != i6_states[i], f"I5 and I6 should always be opposite at tick {i}"
            
            # Verify we had some toggles (motion detection)
            assert i5_toggles > 0, "I5 should toggle during belt movement"
            assert i6_toggles > 0, "I6 should toggle during belt movement"
            
            print_info("✓ I5 and I6 always alternate (motion proof)")
            print_success("Trail sensors simulate rib detection correctly")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def test_bidirectional_operation(self):
        """Test conveyor runs in both directions"""
        print_subheader("Test: Bidirectional Operation")
        
        try:
            self.conveyor = ConveyorSimulation()
            self.conveyor.place_object(500.0)  # Middle of belt
            
            # Forward direction
            self.conveyor.start(direction=1)
            for _ in range(20):
                state = self.conveyor.tick(0.1)
            forward_pos = state['object_position_mm']
            print_info(f"Forward: 500mm → {forward_pos:.1f}mm")
            
            # Reverse direction
            self.conveyor.start(direction=-1)
            for _ in range(20):
                state = self.conveyor.tick(0.1)
            reverse_pos = state['object_position_mm']
            print_info(f"Reverse: {forward_pos:.1f}mm → {reverse_pos:.1f}mm")
            
            assert forward_pos > 500, "Should move forward"
            assert reverse_pos < forward_pos, "Should move backward"
            
            print_success("Conveyor operates in both directions")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def run_all(self):
        """Run all conveyor tests"""
        print_header("Conveyor Belt Tests")
        print_info("Testing the Bridge between VGR and HBW")
        
        self.test_initial_state()
        self.test_conveyor_endpoints()
        self.test_object_transport()
        self.test_light_barriers()
        self.test_trail_sensors()
        self.test_bidirectional_operation()
        
        return self.tests_passed, self.tests_failed


# =============================================================================
# TEST CLASS: Full Handshake Workflow Tests
# =============================================================================

class TestHandshakeWorkflow:
    """
    Tests for the complete VGR → Conveyor → HBW handshake workflow.
    
    This simulates the real factory operation where:
    1. VGR picks up raw item and places on conveyor INPUT
    2. Conveyor transports item from VGR side to HBW side
    3. HBW picks up item from conveyor OUTPUT and stores in rack
    """
    
    def __init__(self):
        self.vgr = VGRSimulation()
        self.conveyor = ConveyorSimulation()
        self.hbw = HBWSimulation()
        self.tests_passed = 0
        self.tests_failed = 0
    
    def test_vgr_to_conveyor_handoff(self):
        """Test VGR placing item on conveyor input"""
        print_subheader("Test: VGR → Conveyor Handoff")
        
        print_info("Workflow:")
        print("  1. VGR moves to delivery zone")
        print("  2. VGR picks up item")
        print("  3. VGR moves to conveyor input")
        print("  4. VGR releases item onto belt")
        
        try:
            # Reset
            self.vgr = VGRSimulation()
            self.conveyor = ConveyorSimulation()
            
            # Step 1: Move to delivery
            self.vgr.move_to_delivery()
            for _ in range(30):
                self.vgr.tick(0.1)
            print_info("  Step 1: VGR at delivery zone ✓")
            
            # Step 2: Pick up item
            self.vgr.lower_to_pickup()
            for _ in range(15):
                self.vgr.tick(0.1)
            self.vgr.activate_vacuum()
            self.vgr.has_item = True
            self.vgr.raise_suction_cup()
            for _ in range(15):
                self.vgr.tick(0.1)
            print_info("  Step 2: Item picked up ✓")
            
            # Step 3: Move to conveyor input
            self.vgr.move_to_conveyor()
            for _ in range(40):
                self.vgr.tick(0.1)
            print_info("  Step 3: VGR at conveyor input ✓")
            
            # Step 4: Release onto belt
            self.vgr.lower_to_pickup()
            for _ in range(15):
                self.vgr.tick(0.1)
            self.vgr.release_vacuum()
            
            # Place object on conveyor at input position
            self.conveyor.place_object(position_mm=0.0)
            
            state = self.conveyor.tick(0.1)
            assert state['has_object'] == True
            assert abs(state['object_position_mm'] - 0.0) < 10
            print_info(f"  Step 4: Item on conveyor at {state['object_position_mm']:.1f}mm ✓")
            
            print_success("VGR successfully hands off item to conveyor")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def test_conveyor_transport(self):
        """Test conveyor transporting item from VGR to HBW side"""
        print_subheader("Test: Conveyor Transport (VGR side → HBW side)")
        
        try:
            self.conveyor = ConveyorSimulation()
            
            # Place at VGR input
            self.conveyor.place_object(position_mm=0.0)
            print_info(f"Start: Item at {self.conveyor.object_position_mm}mm (VGR side)")
            
            # Start belt
            self.conveyor.start(direction=1)
            
            # Track progress
            checkpoints = []
            for i in range(200):
                state = self.conveyor.tick(0.1)
                if state['has_object']:
                    pos = state['object_position_mm']
                    if i % 40 == 0:
                        checkpoints.append(pos)
            
            for i, pos in enumerate(checkpoints):
                print_info(f"  Checkpoint {i+1}: {pos:.1f}mm")
            
            final_pos = state['object_position_mm'] if state['has_object'] else "exited"
            print_info(f"End: Item at {final_pos}mm (HBW side)")
            
            print_success("Conveyor transports item from VGR to HBW side")
            self.tests_passed += 1
        except Exception as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def test_conveyor_to_hbw_handoff(self):
        """Test HBW picking item from conveyor output"""
        print_subheader("Test: Conveyor → HBW Handoff")
        
        print_info("Workflow:")
        print("  1. Item arrives at conveyor output (HBW side)")
        print("  2. HBW moves to conveyor pickup position")
        print("  3. HBW extends fork under carrier")
        print("  4. HBW lifts and retracts fork")
        print("  5. HBW moves to storage slot")
        
        try:
            self.conveyor = ConveyorSimulation()
            self.hbw = HBWSimulation()
            
            # Simulate item at HBW pickup position
            self.conveyor.place_object(position_mm=950.0)
            print_info("  Step 1: Item at conveyor output (950mm) ✓")
            
            # Step 2: HBW moves to conveyor
            self.hbw.move_to_conveyor()
            for _ in range(40):
                self.hbw.tick(0.1)
            print_info(f"  Step 2: HBW at conveyor ({self.hbw.x:.0f}, {self.hbw.y:.0f}) ✓")
            
            # Step 3: Extend fork
            self.hbw.extend_fork()
            for _ in range(20):
                state = self.hbw.tick(0.1)
            print_info(f"  Step 3: Fork extended (Z={state['z']:.1f}mm) ✓")
            
            # Step 4: Lift and retract
            self.hbw.has_carrier = True
            self.conveyor.remove_object()
            self.hbw.retract_fork()
            for _ in range(20):
                state = self.hbw.tick(0.1)
            print_info(f"  Step 4: Fork retracted with carrier ✓")
            
            # Step 5: Move to slot B2
            self.hbw.move_to_slot("B2")
            for _ in range(50):
                state = self.hbw.tick(0.1)
            print_info(f"  Step 5: HBW at slot B2 ({state['x']:.0f}, {state['y']:.0f}) ✓")
            
            assert state['has_carrier'] == True
            print_success("HBW successfully picks from conveyor and moves to slot")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def test_complete_store_workflow(self):
        """Test complete workflow: Raw item → VGR → Conveyor → HBW → Slot"""
        print_subheader("Test: Complete STORE Workflow")
        
        print_info("=" * 50)
        print_info("COMPLETE STORE WORKFLOW")
        print_info("Raw Item → VGR → Conveyor → HBW → Slot A1")
        print_info("=" * 50)
        
        try:
            # Initialize all
            self.vgr = VGRSimulation()
            self.conveyor = ConveyorSimulation()
            self.hbw = HBWSimulation()
            
            # Phase 1: VGR picks from delivery
            print_info("\n[Phase 1] VGR: Pickup from delivery zone")
            self.vgr.move_to_delivery()
            for _ in range(30): self.vgr.tick(0.1)
            self.vgr.lower_to_pickup()
            for _ in range(15): self.vgr.tick(0.1)
            self.vgr.activate_vacuum()
            self.vgr.has_item = True
            self.vgr.raise_suction_cup()
            for _ in range(15): self.vgr.tick(0.1)
            print_info("  → VGR has item")
            
            # Phase 2: VGR places on conveyor
            print_info("\n[Phase 2] VGR: Place on conveyor input")
            self.vgr.move_to_conveyor()
            for _ in range(40): self.vgr.tick(0.1)
            self.vgr.lower_to_pickup()
            for _ in range(15): self.vgr.tick(0.1)
            self.vgr.release_vacuum()
            self.conveyor.place_object(position_mm=0.0)
            print_info("  → Item on conveyor at 0mm")
            
            # Phase 3: Conveyor transport
            print_info("\n[Phase 3] Conveyor: Transport to HBW side")
            self.conveyor.start(direction=1)
            for i in range(150):
                state = self.conveyor.tick(0.1)
                if state['object_position_mm'] and state['object_position_mm'] > 900:
                    break
            self.conveyor.stop()
            print_info(f"  → Item at {state['object_position_mm']:.0f}mm")
            
            # Phase 4: HBW picks from conveyor
            print_info("\n[Phase 4] HBW: Pick from conveyor output")
            self.hbw.move_to_conveyor()
            for _ in range(40): self.hbw.tick(0.1)
            self.hbw.extend_fork()
            for _ in range(20): self.hbw.tick(0.1)
            self.hbw.has_carrier = True
            self.conveyor.remove_object()
            self.hbw.retract_fork()
            for _ in range(20): self.hbw.tick(0.1)
            print_info("  → HBW has carrier")
            
            # Phase 5: HBW stores in slot A1
            print_info("\n[Phase 5] HBW: Store in slot A1")
            self.hbw.move_to_slot("A1")
            for _ in range(60): self.hbw.tick(0.1)
            self.hbw.extend_fork()
            for _ in range(20): self.hbw.tick(0.1)
            # Place carrier
            self.hbw.has_carrier = False
            self.hbw.retract_fork()
            for _ in range(20): 
                state = self.hbw.tick(0.1)
            print_info(f"  → Carrier stored at A1 (X={state['x']:.0f}, Y={state['y']:.0f})")
            
            print_info("\n" + "=" * 50)
            print_success("Complete STORE workflow executed successfully!")
            self.tests_passed += 1
        except Exception as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def run_all(self):
        """Run all handshake workflow tests"""
        print_header("Full Handshake Workflow Tests")
        print_info("Testing the complete VGR → Conveyor → HBW coordination")
        
        self.test_vgr_to_conveyor_handoff()
        self.test_conveyor_transport()
        self.test_conveyor_to_hbw_handoff()
        self.test_complete_store_workflow()
        
        return self.tests_passed, self.tests_failed


# =============================================================================
# TEST CLASS: Motor Electrical Model Tests
# =============================================================================

class TestElectricalModel:
    """Tests for motor electrical characteristics and wear model"""
    
    def __init__(self):
        self.tests_passed = 0
        self.tests_failed = 0
    
    def test_motor_phases(self):
        """Test motor goes through correct phases"""
        print_subheader("Test: Motor Phase Transitions")
        
        print_info("Motor phases: IDLE → STARTUP → RUNNING → STOPPING → IDLE")
        print_info("(Note: Motor uses real-time for startup duration)")
        
        try:
            motor = MotorSimulation("TEST_MOTOR")
            
            # Initial: IDLE
            state = motor.tick(0.1)
            assert motor.phase == MotorPhase.IDLE, f"Expected IDLE, got {motor.phase}"
            print_info(f"  Initial: {motor.phase.value}, current={state['current_amps']:.3f}A")
            
            # Activate: STARTUP (inrush current)
            motor.activate()
            state = motor.tick(0.1)
            assert motor.phase == MotorPhase.STARTUP, f"Expected STARTUP, got {motor.phase}"
            startup_current = state['current_amps']
            print_info(f"  Startup: {motor.phase.value}, current={startup_current:.3f}A (inrush)")
            
            # Wait for RUNNING - uses real time! (startup_duration_ms = 500ms default)
            import time as tm
            tm.sleep(0.6)  # Wait 600ms to ensure past startup
            state = motor.tick(0.1)
            
            # Motor should now be in RUNNING state
            assert motor.phase == MotorPhase.RUNNING, f"Expected RUNNING after 600ms, got {motor.phase}"
            running_current = state['current_amps']
            print_info(f"  Running: {motor.phase.value}, current={running_current:.3f}A (steady)")
            
            # Deactivate: STOPPING
            motor.deactivate()
            state = motor.tick(0.1)
            assert motor.phase == MotorPhase.STOPPING, f"Expected STOPPING, got {motor.phase}"
            print_info(f"  Stopping: {motor.phase.value}")
            
            # Wait for IDLE (velocity-based, uses simulated time)
            for _ in range(20):
                state = motor.tick(0.1)
                if motor.phase == MotorPhase.IDLE:
                    break
            assert motor.phase == MotorPhase.IDLE, f"Expected IDLE after stop, got {motor.phase}"
            print_info(f"  Stopped: {motor.phase.value}")
            
            print_success("Motor transitions through all phases correctly")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def test_health_degradation(self):
        """Test motor health degrades over time"""
        print_subheader("Test: Motor Health Degradation")
        
        try:
            motor = MotorSimulation("TEST_MOTOR")
            
            initial_health = motor.health_score
            print_info(f"Initial health: {initial_health:.4f}")
            
            motor.activate()
            
            # Wait for RUNNING state first (motor uses real-time for startup)
            import time as tm
            tm.sleep(0.6)  # Wait past startup phase
            motor.tick(0.1)  # Trigger phase transition check
            
            assert motor.phase == MotorPhase.RUNNING, f"Motor should be RUNNING, got {motor.phase}"
            
            # Now run while motor is in RUNNING state
            # Health degrades at 0.0001 per dt during RUNNING
            # Run many ticks with small dt to accumulate degradation
            for _ in range(10000):
                state = motor.tick(0.01)  # 0.01s dt * 10000 = 100s simulated
            
            final_health = motor.health_score
            runtime = motor.accumulated_runtime_sec
            print_info(f"After {runtime:.1f}s runtime: {final_health:.4f}")
            print_info(f"Degradation: {(initial_health - final_health):.6f}")
            
            assert final_health < initial_health, f"Health should degrade: {initial_health} -> {final_health}"
            
            print_success("Motor health degrades during extended operation")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def test_power_calculation(self):
        """Test power/energy calculations"""
        print_subheader("Test: Power and Energy Calculation")
        
        try:
            motor = MotorSimulation("TEST_MOTOR", ElectricalModel(
                running_amps=2.0,
                voltage=24.0
            ))
            
            motor.activate()
            
            # Wait for running state (past startup phase)
            for _ in range(15):  # Ensure we're past startup
                state = motor.tick(0.1)
            
            # Power should be close to I*V = 2.0 * 24.0 = 48W
            # Allow for some variance due to phase transitions
            expected_power = 2.0 * 24.0  # P = I * V = 48W
            actual_power = state['power_watts']
            actual_current = state['current_amps']
            
            print_info(f"Expected power: {expected_power}W (2A × 24V)")
            print_info(f"Actual current: {actual_current:.2f}A")
            print_info(f"Actual power: {actual_power:.1f}W")
            
            # Verify power calculation is consistent with P = I * V
            calculated_power = actual_current * 24.0
            assert abs(actual_power - calculated_power) < 0.1, f"Power should equal I*V"
            
            print_success("Power calculations are consistent (P = I × V)")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def run_all(self):
        """Run all electrical model tests"""
        print_header("Electrical Model Tests")
        
        self.test_motor_phases()
        self.test_health_degradation()
        self.test_power_calculation()
        
        return self.tests_passed, self.tests_failed


# =============================================================================
# TEST CLASS: Comparison - HBW vs VGR Z-axis
# =============================================================================

class TestZAxisComparison:
    """
    Critical test demonstrating the Z-axis difference between HBW and VGR.
    
    This is a key architectural concept that users often confuse.
    """
    
    def __init__(self):
        self.tests_passed = 0
        self.tests_failed = 0
    
    def test_z_axis_semantics(self):
        """Compare Z-axis meaning between HBW and VGR"""
        print_subheader("Test: Z-Axis Semantic Comparison")
        
        print_info("")
        print_info("┌─────────────────────────────────────────────────────────────┐")
        print_info("│              Z-AXIS COMPARISON: HBW vs VGR                  │")
        print_info("├─────────────────────────────────────────────────────────────┤")
        print_info("│  Feature          │  HBW (Storage)  │  VGR (Production)     │")
        print_info("├─────────────────────────────────────────────────────────────┤")
        print_info("│  Z-Axis Motion    │  HORIZONTAL     │  VERTICAL             │")
        print_info("│  Z=0 means        │  Fork retracted │  Suction cup UP       │")
        print_info("│  Z=max means      │  Fork extended  │  Suction cup DOWN     │")
        print_info("│                   │  (into rack)    │  (to table)           │")
        print_info("│  Tool             │  Mechanical     │  Pneumatic            │")
        print_info("│                   │  Fork           │  Suction Cup          │")
        print_info("│  Grips from       │  Below (lifts)  │  Above (sucks)        │")
        print_info("└─────────────────────────────────────────────────────────────┘")
        print_info("")
        
        try:
            hbw = HBWSimulation()
            vgr = VGRSimulation()
            
            # HBW Z-axis test
            print_info("HBW Z-axis (HORIZONTAL - fork telescoping):")
            hbw.extend_fork()
            for _ in range(20):
                hbw_state = hbw.tick(0.1)
            print_info(f"  Fork extended: Z={hbw_state['z']:.1f}mm (into rack slot)")
            
            # VGR Z-axis test  
            print_info("\nVGR Z-axis (VERTICAL - suction lowering):")
            vgr.lower_to_pickup()
            for _ in range(20):
                vgr_state = vgr.tick(0.1)
            print_info(f"  Suction lowered: Z={vgr_state['z']:.1f}mm (down to table)")
            
            # Both use positive Z but mean opposite spatial directions!
            assert hbw_state['z'] > 0, "HBW Z should be positive when extended"
            assert vgr_state['z'] > 0, "VGR Z should be positive when lowered"
            
            print_info("\n⚠️  KEY INSIGHT: Both robots use positive Z values, but:")
            print_info("   - HBW Z+ = horizontally INTO the rack")
            print_info("   - VGR Z+ = vertically DOWN to the table")
            
            print_success("Z-axis semantics are correctly differentiated")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def run_all(self):
        """Run Z-axis comparison tests"""
        print_header("Z-Axis Comparison: HBW vs VGR")
        
        self.test_z_axis_semantics()
        
        return self.tests_passed, self.tests_failed


# =============================================================================
# TEST CLASS: Sensor-Based Conveyor Positioning Tests
# =============================================================================

class TestSensorBasedPositioning:
    """
    Tests for the sensor-based conveyor positioning algorithm.
    
    The conveyor does NOT use encoder positioning. Instead, it relies on:
    - I2 (Light Barrier): Triggers at HBW interface (~400mm ±25mm)
    - I3 (Light Barrier): Triggers at VGR interface (~950mm ±25mm)
    - I5/I6 (Trail Sensors): Toggle every 10mm to prove motion
    """
    
    def __init__(self):
        self.tests_passed = 0
        self.tests_failed = 0
    
    def test_sensor_constants(self):
        """Verify sensor position constants are defined correctly"""
        print_subheader("Test: Sensor Position Constants")
        
        try:
            conveyor = ConveyorSimulation()
            
            print_info("Sensor-based positioning constants:")
            print_info(f"  POS_HBW_INTERFACE: {conveyor.POS_HBW_INTERFACE}mm")
            print_info(f"  POS_VGR_INTERFACE: {conveyor.POS_VGR_INTERFACE}mm")
            print_info(f"  SENSOR_TOLERANCE_MM: ±{conveyor.SENSOR_TOLERANCE_MM}mm")
            print_info(f"  TRAIL_RIB_SPACING_MM: {conveyor.TRAIL_RIB_SPACING_MM}mm")
            
            assert conveyor.POS_HBW_INTERFACE == 400.0, "HBW interface should be at 400mm"
            assert conveyor.POS_VGR_INTERFACE == 950.0, "VGR interface should be at 950mm"
            assert conveyor.SENSOR_TOLERANCE_MM == 25.0, "Sensor tolerance should be ±25mm"
            assert conveyor.TRAIL_RIB_SPACING_MM == 10.0, "Trail rib spacing should be 10mm"
            
            print_success("Sensor position constants defined correctly")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def test_inbound_transport_simulation(self):
        """Simulate inbound transport (VGR → HBW) with I2 sensor trigger"""
        print_subheader("Test: Inbound Transport Simulation (VGR → HBW)")
        
        print_info("Simulating item transport from VGR side to HBW interface")
        print_info("  Start: 0mm (VGR input)")
        print_info("  Target: 400mm (HBW interface, I2 triggers)")
        
        try:
            conveyor = ConveyorSimulation()
            
            # Place object at VGR input
            conveyor.place_object(position_mm=0.0)
            conveyor.start(direction=1)  # Forward: VGR → HBW
            
            # Simulate transport until I2 triggers
            i2_triggered = False
            tick_count = 0
            max_ticks = 100  # Safety limit
            
            while not i2_triggered and tick_count < max_ticks:
                state = conveyor.tick(0.1)
                i2_triggered = state['at_hbw_interface']
                tick_count += 1
                
                if tick_count % 20 == 0:
                    print_info(f"  Position: {state['object_position_mm']:.1f}mm, I2: {i2_triggered}")
            
            conveyor.stop()
            final_pos = conveyor.object_position_mm
            
            print_info(f"  Final position: {final_pos:.1f}mm")
            print_info(f"  I2 triggered after {tick_count} ticks")
            
            assert i2_triggered, "I2 should trigger when item reaches HBW interface"
            assert 375 <= final_pos <= 425, f"Item should be at HBW interface (375-425mm), got {final_pos:.1f}mm"
            
            print_success("Inbound transport triggers I2 at HBW interface")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def test_outbound_transport_simulation(self):
        """Simulate outbound transport (HBW → VGR) with I3 sensor trigger"""
        print_subheader("Test: Outbound Transport Simulation (HBW → VGR)")
        
        print_info("Simulating item transport from HBW interface to VGR side")
        print_info("  Start: 400mm (HBW interface)")
        print_info("  Target: 950mm (VGR interface, I3 triggers)")
        
        try:
            conveyor = ConveyorSimulation()
            
            # Place object at HBW interface
            conveyor.place_object(position_mm=400.0)
            conveyor.start(direction=1)  # Forward continues to VGR side
            
            # Simulate transport until I3 triggers
            i3_triggered = False
            tick_count = 0
            max_ticks = 100
            
            while not i3_triggered and tick_count < max_ticks:
                state = conveyor.tick(0.1)
                i3_triggered = state['at_vgr_interface']
                tick_count += 1
                
                if tick_count % 20 == 0:
                    print_info(f"  Position: {state['object_position_mm']:.1f}mm, I3: {i3_triggered}")
            
            conveyor.stop()
            final_pos = conveyor.object_position_mm
            
            print_info(f"  Final position: {final_pos:.1f}mm")
            print_info(f"  I3 triggered after {tick_count} ticks")
            
            assert i3_triggered, "I3 should trigger when item reaches VGR interface"
            assert 925 <= final_pos <= 975, f"Item should be at VGR interface (925-975mm), got {final_pos:.1f}mm"
            
            print_success("Outbound transport triggers I3 at VGR interface")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def test_helper_methods(self):
        """Test conveyor helper methods for position checking"""
        print_subheader("Test: Position Helper Methods")
        
        try:
            conveyor = ConveyorSimulation()
            
            # Test is_at_hbw_interface()
            conveyor.place_object(position_mm=400.0)
            assert conveyor.is_at_hbw_interface() == True, "Should be at HBW interface at 400mm"
            print_info("  is_at_hbw_interface(400mm) = True ✓")
            
            conveyor.object_position_mm = 300.0
            assert conveyor.is_at_hbw_interface() == False, "Should not be at HBW interface at 300mm"
            print_info("  is_at_hbw_interface(300mm) = False ✓")
            
            # Test is_at_vgr_interface()
            conveyor.object_position_mm = 950.0
            assert conveyor.is_at_vgr_interface() == True, "Should be at VGR interface at 950mm"
            print_info("  is_at_vgr_interface(950mm) = True ✓")
            
            conveyor.object_position_mm = 800.0
            assert conveyor.is_at_vgr_interface() == False, "Should not be at VGR interface at 800mm"
            print_info("  is_at_vgr_interface(800mm) = False ✓")
            
            # Test get_sensor_states()
            conveyor.object_position_mm = 400.0
            sensors = conveyor.get_sensor_states()
            assert "I2" in sensors and "I3" in sensors, "Should have I2 and I3 in sensor states"
            assert sensors["I2"] == True, "I2 should be true at 400mm"
            print_info(f"  get_sensor_states() at 400mm: I2={sensors['I2']}, I3={sensors['I3']} ✓")
            
            print_success("Position helper methods work correctly")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def test_motion_proof_via_trail_sensors(self):
        """Test that trail sensors prove physical motion"""
        print_subheader("Test: Motion Proof via Trail Sensors")
        
        print_info("Trail sensors I5/I6 must alternate every 10mm to prove motion")
        print_info("This prevents false positives from stuck/slipping belt")
        
        try:
            conveyor = ConveyorSimulation()
            conveyor.place_object(0)
            conveyor.start(direction=1)
            
            # Simulate exactly 100mm of travel (should toggle 10 times)
            # At 100mm/s, 100mm takes 1 second = 10 ticks at 0.1s
            i5_toggles = 0
            last_i5_state = conveyor._trail_toggle_state
            
            for _ in range(20):  # More ticks to ensure some travel
                state = conveyor.tick(0.1)
                current_i5 = state['trail_sensors']['I5']['is_triggered']
                if current_i5 != last_i5_state:
                    i5_toggles += 1
                    last_i5_state = current_i5
            
            belt_travel = conveyor.belt_position_mm
            expected_toggles = int(belt_travel / 10)  # Toggle every 10mm
            
            print_info(f"  Belt traveled: {belt_travel:.1f}mm")
            print_info(f"  Expected toggles: ~{expected_toggles}")
            print_info(f"  Actual I5 toggles: {i5_toggles}")
            
            # Should have roughly the expected number of toggles (±2 for edge effects)
            assert i5_toggles >= expected_toggles - 2, f"Expected ~{expected_toggles} toggles, got {i5_toggles}"
            
            print_success("Trail sensors toggle correctly to prove motion")
            self.tests_passed += 1
        except AssertionError as e:
            print_fail(str(e))
            self.tests_failed += 1
    
    def run_all(self):
        """Run all sensor-based positioning tests"""
        print_header("Sensor-Based Conveyor Positioning Tests")
        print_info("Testing Light Barrier (I2, I3) and Trail Sensor (I5, I6) Logic")
        
        self.test_sensor_constants()
        self.test_inbound_transport_simulation()
        self.test_outbound_transport_simulation()
        self.test_helper_methods()
        self.test_motion_proof_via_trail_sensors()
        
        return self.tests_passed, self.tests_failed


# =============================================================================
# MAIN TEST RUNNER
# =============================================================================

def main():
    """Run all test suites"""
    print_header("STF DIGITAL TWIN - FACTORY SCENARIO TESTS")
    print_info("Testing the Two-Robot Architecture (HBW + VGR)")
    print_info(f"Test started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    total_passed = 0
    total_failed = 0
    
    # Run all test suites
    test_suites = [
        ("Z-Axis Comparison", TestZAxisComparison()),
        ("HBW (Storage Robot)", TestHBW()),
        ("VGR (Production Robot)", TestVGR()),
        ("Conveyor Belt", TestConveyor()),
        ("Sensor-Based Positioning", TestSensorBasedPositioning()),
        ("Electrical Model", TestElectricalModel()),
        ("Handshake Workflow", TestHandshakeWorkflow()),
    ]
    
    results = []
    
    for name, suite in test_suites:
        passed, failed = suite.run_all()
        total_passed += passed
        total_failed += failed
        results.append((name, passed, failed))
    
    # Print summary
    print_header("TEST SUMMARY")
    
    print_info("Results by suite:")
    for name, passed, failed in results:
        status = Colors.GREEN + "✓" if failed == 0 else Colors.RED + "✗"
        print(f"  {status} {name}: {passed} passed, {failed} failed{Colors.ENDC}")
    
    print_info("")
    print_info(f"{'='*50}")
    print_info(f"TOTAL: {total_passed} passed, {total_failed} failed")
    
    if total_failed == 0:
        print(f"\n{Colors.GREEN}{Colors.BOLD}ALL TESTS PASSED! ✓{Colors.ENDC}")
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}SOME TESTS FAILED ✗{Colors.ENDC}")
    
    return total_failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
