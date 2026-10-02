"""
STF Digital Twin - Complete Conveyor Belt Operation Test

This test file demonstrates the COMPLETE working of the conveyor belt system:
1. Inbound Transport: VGR → HBW (item placed by VGR, picked up by HBW)
2. Outbound Transport: HBW → VGR (item placed by HBW, picked up by VGR)
3. Congestion Avoidance: What happens when interfaces are blocked

Conveyor Belt Specifications:
- Belt length: 120mm (~12cm realistic Fischertechnik conveyor)
- Global factory position: ~(400, 100, 25) - where HBW picks up
- Origin (0,0) is at LEFT of storage rack (slots at X=100-300mm)

Sensor-Based Positioning:
- The conveyor does NOT use encoder positioning
- Position is determined by Light Barriers (I2, I3) and Trail Sensors (I5, I6)
- I2: Triggers at HBW interface (~105mm ±10mm) 
- I3: Triggers at VGR interface (~15mm ±10mm)
- I5/I6: Toggle every 5mm to prove physical motion

Run with: python tests/test_conveyor_complete.py
"""

import sys
import os
import time

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hardware.mock_factory import ConveyorSimulation, MotorPhase


# =============================================================================
# TERMINAL OUTPUT FORMATTING
# =============================================================================

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'


def print_banner(text: str):
    """Print a large banner"""
    width = 70
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*width}")
    print(f"{text.center(width)}")
    print(f"{'='*width}{Colors.ENDC}\n")


def print_section(text: str):
    """Print a section header"""
    print(f"\n{Colors.CYAN}{Colors.BOLD}┌{'─'*60}┐{Colors.ENDC}")
    print(f"{Colors.CYAN}{Colors.BOLD}│ {text.ljust(58)} │{Colors.ENDC}")
    print(f"{Colors.CYAN}{Colors.BOLD}└{'─'*60}┘{Colors.ENDC}\n")


def print_step(step_num: int, text: str):
    """Print a workflow step"""
    print(f"{Colors.YELLOW}  [{step_num}] {text}{Colors.ENDC}")


def print_status(text: str, value: str, ok: bool = True):
    """Print a status line"""
    icon = f"{Colors.GREEN}✓{Colors.ENDC}" if ok else f"{Colors.RED}✗{Colors.ENDC}"
    print(f"      {icon} {text}: {Colors.BOLD}{value}{Colors.ENDC}")


def print_sensor(name: str, triggered: bool, position: str = ""):
    """Print sensor status"""
    state = f"{Colors.GREEN}TRIGGERED{Colors.ENDC}" if triggered else f"{Colors.DIM}inactive{Colors.ENDC}"
    pos_info = f" ({position})" if position else ""
    print(f"      • {name}: {state}{pos_info}")


def print_error(text: str):
    """Print an error message"""
    print(f"{Colors.RED}{Colors.BOLD}  ✗ ERROR: {text}{Colors.ENDC}")


def print_success(text: str):
    """Print a success message"""
    print(f"{Colors.GREEN}{Colors.BOLD}  ✓ SUCCESS: {text}{Colors.ENDC}")


def print_warning(text: str):
    """Print a warning message"""
    print(f"{Colors.YELLOW}  ⚠ WARNING: {text}{Colors.ENDC}")


def print_diagram():
    """Print the conveyor belt diagram"""
    print(f"{Colors.DIM}")
    print("    CONVEYOR BELT LAYOUT (Sensor-Based Positioning)")
    print("    ════════════════════════════════════════════════")
    print("")
    print("    VGR Side                          HBW Side")
    print("    (Production)                      (Storage)")
    print("         │                                │")
    print("         ▼                                ▼")
    print("    ┌─────────┐                    ┌─────────┐")
    print("    │   I3    │                    │   I2    │")
    print("    │  15±10  │◄────── BELT ──────►│ 105±10  │")
    print("    │  (VGR)  │    ══════════      │  (HBW)  │")
    print("    └─────────┘    I5/I6 ribs      └─────────┘")
    print("         │         (motion)             │")
    print("         │          proof)              │")
    print("    ┌─────────┐                    ┌─────────┐")
    print("    │  VGR    │                    │   HBW   │")
    print("    │ Suction │                    │  Fork   │")
    print("    │  Cup    │                    │(Cantilv)│")
    print("    └─────────┘                    └─────────┘")
    print("")
    print("    Position:  0mm ◄───────────────► 120mm")
    print("    Global Factory Coords: ~(400, 100, 25)")
    print(f"{Colors.ENDC}")


# =============================================================================
# CONVEYOR SIMULATION HELPER
# =============================================================================

class ConveyorController:
    """
    Simulates the controller logic for conveyor operations.
    This mirrors what MainController does but works with the simulation directly.
    """
    
    TIMEOUT_SECONDS = 5.0
    TICK_INTERVAL = 0.1  # 10Hz simulation
    
    def __init__(self):
        self.conveyor = ConveyorSimulation()
        self.log = []
    
    def _log(self, message: str):
        """Add to operation log"""
        self.log.append(message)
        print(f"{Colors.DIM}      → {message}{Colors.ENDC}")
    
    def get_sensor_states(self) -> dict:
        """Get current sensor states"""
        state = self.conveyor.tick(0)  # Zero-time tick just to read state
        return {
            "I2": state["light_barriers"]["I2"]["is_triggered"],
            "I3": state["light_barriers"]["I3"]["is_triggered"],
            "I5": state["trail_sensors"]["I5"]["is_triggered"],
            "I6": state["trail_sensors"]["I6"]["is_triggered"],
            "at_hbw": state["at_hbw_interface"],
            "at_vgr": state["at_vgr_interface"],
        }
    
    def move_inbound(self) -> dict:
        """
        Move item from VGR side to HBW side (inbound transport).
        
        Direction: VGR → HBW (forward, direction=1)
        Monitors: I2 sensor (triggers when item reaches HBW interface at ~105mm)
        
        Returns dict with success status, final position, and sensor that triggered.
        """
        result = {
            "success": False,
            "direction": "INBOUND (VGR → HBW)",
            "start_position": self.conveyor.object_position_mm,
            "final_position": None,
            "sensor_triggered": None,
            "ticks": 0,
            "error": None
        }
        
        # Step 1: Congestion Check
        sensors = self.get_sensor_states()
        if sensors["I2"]:
            result["error"] = "CONGESTION: I2 already triggered (HBW interface blocked)"
            return result
        
        self._log("Congestion check passed (I2 clear)")
        
        # Step 2: Start motor forward
        self.conveyor.start(direction=1)
        self._log("Motor M1 started (direction: INWARD/Q1)")
        
        # Step 3: Monitor I2 with timeout
        start_time = time.time()
        ticks = 0
        
        while time.time() - start_time < self.TIMEOUT_SECONDS:
            state = self.conveyor.tick(self.TICK_INTERVAL)
            ticks += 1
            
            # Check if I2 triggered
            if state["at_hbw_interface"]:
                # Step 4: Stop immediately
                self.conveyor.stop()
                self._log(f"I2 triggered at position {state['object_position_mm']:.1f}mm")
                self._log("Motor M1 stopped")
                
                result["success"] = True
                result["final_position"] = state["object_position_mm"]
                result["sensor_triggered"] = "I2"
                result["ticks"] = ticks
                return result
            
            # Progress indicator every 20 ticks
            if ticks % 20 == 0:
                self._log(f"Position: {state['object_position_mm']:.1f}mm, I2: {state['at_hbw_interface']}")
        
        # Timeout reached
        self.conveyor.stop()
        result["error"] = f"TIMEOUT: I2 not triggered within {self.TIMEOUT_SECONDS}s (belt jammed?)"
        result["final_position"] = self.conveyor.object_position_mm
        result["ticks"] = ticks
        return result
    
    def move_outbound(self) -> dict:
        """
        Move item from HBW side to VGR side (outbound transport).
        
        Direction: HBW → VGR (reverse, direction=-1)
        Monitors: I3 sensor (triggers when item reaches VGR interface at ~15mm)
        
        Returns dict with success status, final position, and sensor that triggered.
        """
        result = {
            "success": False,
            "direction": "OUTBOUND (HBW → VGR)",
            "start_position": self.conveyor.object_position_mm,
            "final_position": None,
            "sensor_triggered": None,
            "ticks": 0,
            "error": None
        }
        
        # Step 1: Congestion Check
        sensors = self.get_sensor_states()
        if sensors["I3"]:
            result["error"] = "CONGESTION: I3 already triggered (VGR interface blocked)"
            return result
        
        self._log("Congestion check passed (I3 clear)")
        
        # Step 2: Start motor reverse (towards VGR at position 0)
        self.conveyor.start(direction=-1)
        self._log("Motor M1 started (direction: OUTWARD/Q2)")
        
        # Step 3: Monitor I3 with timeout
        start_time = time.time()
        ticks = 0
        
        while time.time() - start_time < self.TIMEOUT_SECONDS:
            state = self.conveyor.tick(self.TICK_INTERVAL)
            ticks += 1
            
            # Check if I3 triggered
            if state["at_vgr_interface"]:
                # Step 4: Stop immediately
                self.conveyor.stop()
                self._log(f"I3 triggered at position {state['object_position_mm']:.1f}mm")
                self._log("Motor M1 stopped")
                
                result["success"] = True
                result["final_position"] = state["object_position_mm"]
                result["sensor_triggered"] = "I3"
                result["ticks"] = ticks
                return result
            
            # Progress indicator every 20 ticks
            if ticks % 20 == 0:
                self._log(f"Position: {state['object_position_mm']:.1f}mm, I3: {state['at_vgr_interface']}")
        
        # Timeout reached
        self.conveyor.stop()
        result["error"] = f"TIMEOUT: I3 not triggered within {self.TIMEOUT_SECONDS}s (belt jammed?)"
        result["final_position"] = self.conveyor.object_position_mm
        result["ticks"] = ticks
        return result


# =============================================================================
# TEST SCENARIOS
# =============================================================================

def test_inbound_vgr_to_hbw():
    """
    SCENARIO 1: Complete Inbound Transport (VGR → HBW)
    
    Simulates a cookie being placed by VGR on the conveyor input (0mm)
    and transported to the HBW interface (105mm) where I2 triggers.
    """
    print_section("SCENARIO 1: Inbound Transport (VGR → HBW)")
    
    print_step(1, "Initialize conveyor and place item at VGR input (0mm)")
    controller = ConveyorController()
    controller.conveyor.place_object(position_mm=0.0)
    
    print_status("Item placed at", "0mm (VGR input)")
    print_status("Target", "105mm (HBW interface, I2 sensor)")
    
    # Show initial sensor states
    print_step(2, "Check initial sensor states")
    sensors = controller.get_sensor_states()
    print_sensor("I2 (HBW interface)", sensors["I2"], "105±10mm")
    print_sensor("I3 (VGR interface)", sensors["I3"], "15±10mm")
    
    print_step(3, "Start inbound transport")
    result = controller.move_inbound()
    
    print_step(4, "Transport result")
    if result["success"]:
        print_success(f"Item arrived at HBW interface!")
        print_status("Final position", f"{result['final_position']:.1f}mm")
        print_status("Sensor triggered", result["sensor_triggered"])
        print_status("Ticks elapsed", str(result["ticks"]))
        
        # Verify final sensor states
        print_step(5, "Verify final sensor states")
        sensors = controller.get_sensor_states()
        print_sensor("I2 (HBW interface)", sensors["I2"], "SHOULD BE TRIGGERED")
        print_sensor("I3 (VGR interface)", sensors["I3"], "should be inactive")
        
        return True
    else:
        print_error(result["error"])
        return False


def test_outbound_hbw_to_vgr():
    """
    SCENARIO 2: Complete Outbound Transport (HBW → VGR)
    
    Simulates a cookie being placed by HBW at the conveyor output (105mm)
    and transported to the VGR interface (15mm) where I3 triggers.
    """
    print_section("SCENARIO 2: Outbound Transport (HBW → VGR)")
    
    print_step(1, "Initialize conveyor and place item at HBW interface (105mm)")
    controller = ConveyorController()
    controller.conveyor.place_object(position_mm=105.0)
    
    print_status("Item placed at", "105mm (HBW interface)")
    print_status("Target", "15mm (VGR interface, I3 sensor)")
    
    # Show initial sensor states
    print_step(2, "Check initial sensor states")
    sensors = controller.get_sensor_states()
    print_sensor("I2 (HBW interface)", sensors["I2"], "105±10mm")
    print_sensor("I3 (VGR interface)", sensors["I3"], "15±10mm")
    
    print_step(3, "Start outbound transport")
    result = controller.move_outbound()
    
    print_step(4, "Transport result")
    if result["success"]:
        print_success(f"Item arrived at VGR interface!")
        print_status("Final position", f"{result['final_position']:.1f}mm")
        print_status("Sensor triggered", result["sensor_triggered"])
        print_status("Ticks elapsed", str(result["ticks"]))
        
        # Verify final sensor states
        print_step(5, "Verify final sensor states")
        sensors = controller.get_sensor_states()
        print_sensor("I2 (HBW interface)", sensors["I2"], "should be inactive")
        print_sensor("I3 (VGR interface)", sensors["I3"], "SHOULD BE TRIGGERED")
        
        return True
    else:
        print_error(result["error"])
        return False


def test_congestion_hbw_blocked():
    """
    SCENARIO 3: Congestion Avoidance - HBW Interface Blocked
    
    Tests what happens when an item is already at the HBW interface (I2 triggered)
    and we try to start another inbound transport. Should REJECT the operation.
    """
    print_section("SCENARIO 3: Congestion Avoidance (HBW Blocked)")
    
    print_step(1, "Simulate blocked HBW interface (item already at 105mm)")
    controller = ConveyorController()
    
    # First, place an item at the HBW interface (blocking position)
    controller.conveyor.place_object(position_mm=105.0)
    controller.conveyor.tick(0.1)  # Update state
    
    print_status("Blocking item at", "105mm (HBW interface)")
    
    # Show sensor states - I2 should be triggered
    print_step(2, "Verify I2 is triggered (interface blocked)")
    sensors = controller.get_sensor_states()
    print_sensor("I2 (HBW interface)", sensors["I2"], "BLOCKING")
    
    if not sensors["I2"]:
        print_error("Test setup failed - I2 should be triggered")
        return False
    
    print_step(3, "Attempt inbound transport (should be REJECTED)")
    print_warning("Attempting to move another item to blocked interface...")
    
    # Try to start inbound - should fail congestion check
    result = controller.move_inbound()
    
    print_step(4, "Congestion check result")
    if not result["success"] and "CONGESTION" in (result["error"] or ""):
        print_success("Inbound transport correctly REJECTED!")
        print_status("Reason", result["error"])
        print_status("Motor started", "NO (blocked before starting)")
        return True
    else:
        print_error("Congestion check failed - should have rejected!")
        return False


def test_congestion_vgr_blocked():
    """
    SCENARIO 4: Congestion Avoidance - VGR Interface Blocked
    
    Tests what happens when an item is already at the VGR interface (I3 triggered)
    and we try to start another outbound transport. Should REJECT the operation.
    """
    print_section("SCENARIO 4: Congestion Avoidance (VGR Blocked)")
    
    print_step(1, "Simulate blocked VGR interface (item already at 15mm)")
    controller = ConveyorController()
    
    # Place an item exactly at the VGR interface to block it
    controller.conveyor.place_object(position_mm=15.0)
    controller.conveyor.tick(0)  # Update state
    
    print_status("Blocking item at", "15mm (VGR interface)")
    
    # Show sensor states - I3 should be triggered
    print_step(2, "Verify I3 is triggered (interface blocked)")
    sensors = controller.get_sensor_states()
    print_sensor("I3 (VGR interface)", sensors["I3"], "BLOCKING")
    
    if not sensors["I3"]:
        print_error("Test setup failed - I3 should be triggered")
        return False
    
    print_step(3, "Attempt outbound transport (should be REJECTED)")
    print_warning("Attempting to move another item to blocked interface...")
    
    # Try to start outbound - should fail congestion check
    result = controller.move_outbound()
    
    print_step(4, "Congestion check result")
    if not result["success"] and "CONGESTION" in (result["error"] or ""):
        print_success("Outbound transport correctly REJECTED!")
        print_status("Reason", result["error"])
        print_status("Motor started", "NO (blocked before starting)")
        return True
    else:
        print_error("Congestion check failed - should have rejected!")
        return False


def test_full_round_trip():
    """
    SCENARIO 5: Complete Round Trip (VGR → HBW → VGR)
    
    Simulates a complete cookie flow:
    1. VGR places cookie at input (0mm)
    2. Conveyor moves cookie to HBW interface (105mm) - I2 triggers
    3. HBW picks up cookie (simulated by removing from belt)
    4. HBW places processed cookie back (105mm)
    5. Conveyor moves cookie to VGR interface (15mm) - I3 triggers
    6. VGR picks up cookie (simulated)
    """
    print_section("SCENARIO 5: Complete Round Trip")
    
    # Phase 1: VGR → HBW
    print(f"{Colors.BOLD}  ═══ PHASE 1: VGR → HBW (Store Operation) ═══{Colors.ENDC}")
    controller1 = ConveyorController()  # Fresh conveyor for phase 1
    
    print_step(1, "VGR places cookie at input (0mm)")
    controller1.conveyor.place_object(position_mm=0.0)
    print_status("Cookie placed", "0mm")
    
    print_step(2, "Transport to HBW interface")
    result1 = controller1.move_inbound()
    
    if not result1["success"]:
        print_error(f"Phase 1 failed: {result1['error']}")
        return False
    
    print_success(f"Cookie at HBW interface ({result1['final_position']:.1f}mm)")
    
    print_step(3, "HBW picks up cookie (fork extends, lifts, retracts)")
    controller1.conveyor.remove_object()
    print_status("Cookie removed by HBW", "Fork operation complete")
    
    # Phase 2: HBW → VGR (use a fresh conveyor to simulate HBW placing item back)
    print(f"\n{Colors.BOLD}  ═══ PHASE 2: HBW → VGR (Retrieve Operation) ═══{Colors.ENDC}")
    controller2 = ConveyorController()  # Fresh conveyor for phase 2
    
    print_step(4, "HBW places processed cookie at interface (105mm)")
    controller2.conveyor.place_object(position_mm=105.0)  # Exactly at HBW interface
    print_status("Cookie placed", "105mm (HBW interface)")
    
    print_step(5, "Transport to VGR interface")
    result2 = controller2.move_outbound()
    
    if not result2["success"]:
        print_error(f"Phase 2 failed: {result2['error']}")
        return False
    
    print_success(f"Cookie at VGR interface ({result2['final_position']:.1f}mm)")
    
    print_step(6, "VGR picks up cookie (suction cup lowers, grabs, raises)")
    controller2.conveyor.remove_object()
    print_status("Cookie removed by VGR", "Suction operation complete")
    
    # Summary
    print(f"\n{Colors.BOLD}  ═══ ROUND TRIP SUMMARY ═══{Colors.ENDC}")
    print_status("Phase 1 (VGR→HBW)", f"0mm → {result1['final_position']:.1f}mm in {result1['ticks']} ticks")
    print_status("Phase 2 (HBW→VGR)", f"105mm → {result2['final_position']:.1f}mm in {result2['ticks']} ticks")
    print_success("Complete round trip successful!")
    
    return True


def test_trail_sensor_motion_proof():
    """
    SCENARIO 6: Trail Sensor Motion Proof
    
    Demonstrates how I5/I6 trail sensors alternate every 5mm to prove
    the belt is physically moving (not slipping or stuck).
    """
    print_section("SCENARIO 6: Trail Sensor Motion Proof")
    
    print_step(1, "Understanding trail sensors")
    print(f"{Colors.DIM}      Trail sensors I5 and I6 detect belt ribs every 5mm.")
    print(f"      They ALTERNATE states: when I5=True, I6=False and vice versa.")
    print(f"      This proves the belt is physically moving, not just motor running.{Colors.ENDC}")
    
    controller = ConveyorController()
    controller.conveyor.place_object(position_mm=0.0)
    controller.conveyor.start(direction=1)
    
    print_step(2, "Monitor trail sensors during movement")
    print(f"\n      {'Position':>10} │ {'I5':^6} │ {'I6':^6} │ {'Motion Proof':^15}")
    print(f"      {'─'*10}─┼{'─'*8}┼{'─'*8}┼{'─'*17}")
    
    last_i5 = None
    motion_events = 0
    
    for tick in range(30):
        state = controller.conveyor.tick(0.1)
        i5 = state["trail_sensors"]["I5"]["is_triggered"]
        i6 = state["trail_sensors"]["I6"]["is_triggered"]
        pos = state["object_position_mm"]
        
        # Stop if object exited belt
        if pos is None:
            break
        
        # Check for toggle (motion proof)
        if last_i5 is not None and i5 != last_i5:
            motion_events += 1
            proof = f"{Colors.GREEN}Toggle #{motion_events}{Colors.ENDC}"
        else:
            proof = ""
        
        last_i5 = i5
        
        # Print every 5 ticks
        if tick % 5 == 0:
            i5_str = f"{Colors.GREEN}ON{Colors.ENDC}" if i5 else f"{Colors.DIM}off{Colors.ENDC}"
            i6_str = f"{Colors.GREEN}ON{Colors.ENDC}" if i6 else f"{Colors.DIM}off{Colors.ENDC}"
            print(f"      {pos:>8.1f}mm │ {i5_str:^15} │ {i6_str:^15} │ {proof}")
    
    controller.conveyor.stop()
    
    print_step(3, "Motion verification result")
    belt_travel = controller.conveyor.belt_position_mm
    expected_toggles = int(belt_travel / 5)
    
    print_status("Belt traveled", f"{belt_travel:.1f}mm")
    print_status("Expected toggles", f"~{expected_toggles} (every 5mm)")
    print_status("Actual toggles detected", str(motion_events))
    
    if motion_events >= expected_toggles - 2:
        print_success("Trail sensors confirm belt is physically moving!")
        return True
    else:
        print_error("Insufficient toggle events - belt may be slipping!")
        return False


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Run all conveyor test scenarios"""
    print_banner("COMPLETE CONVEYOR BELT OPERATION TEST")
    print_diagram()
    
    results = []
    
    # Run all scenarios
    scenarios = [
        ("Inbound Transport (VGR → HBW)", test_inbound_vgr_to_hbw),
        ("Outbound Transport (HBW → VGR)", test_outbound_hbw_to_vgr),
        ("Congestion Avoidance (HBW Blocked)", test_congestion_hbw_blocked),
        ("Congestion Avoidance (VGR Blocked)", test_congestion_vgr_blocked),
        ("Complete Round Trip", test_full_round_trip),
        ("Trail Sensor Motion Proof", test_trail_sensor_motion_proof),
    ]
    
    for name, test_func in scenarios:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print_error(f"Exception in {name}: {e}")
            results.append((name, False))
    
    # Print summary
    print_banner("TEST RESULTS SUMMARY")
    
    passed_count = sum(1 for _, p in results if p)
    failed_count = len(results) - passed_count
    
    for name, passed in results:
        icon = f"{Colors.GREEN}✓ PASS{Colors.ENDC}" if passed else f"{Colors.RED}✗ FAIL{Colors.ENDC}"
        print(f"  {icon}  {name}")
    
    print(f"\n  {'─'*50}")
    print(f"  Total: {Colors.GREEN}{passed_count} passed{Colors.ENDC}, {Colors.RED if failed_count else Colors.DIM}{failed_count} failed{Colors.ENDC}")
    
    if failed_count == 0:
        print(f"\n{Colors.GREEN}{Colors.BOLD}  ★ ALL SCENARIOS PASSED! Conveyor system working correctly. ★{Colors.ENDC}\n")
        return True
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}  ✗ SOME SCENARIOS FAILED! Check above for details. ✗{Colors.ENDC}\n")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
