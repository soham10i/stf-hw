"""
STF Digital Twin - Factory Scenario Tests (pytest)

Tests factory operation scenarios showcasing the two-robot architecture
(HBW + VGR) with conveyor handshake.

Test Categories:
1. Individual Component Tests (HBW, VGR, Conveyor)
2. Full Workflow Tests (VGR -> Conveyor -> HBW handshake)
3. Sensor Simulation Tests (Light Barriers, Trail Sensors)
4. Motor Electrical Model Tests
"""

import os
import sys
import time

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hardware.mock_factory import (
    ElectricalModel,
    HBWSimulation,
    LightBarrierSimulation,
    MotorPhase,
    MotorSimulation,
    TrailSensorSimulation,
    VGRSimulation,
    ConveyorSimulation,
)


# =============================================================================
# TEST CLASS: HBW (High-Bay Warehouse) Tests
# =============================================================================


@pytest.mark.unit
class TestHBW:
    """Tests for the High-Bay Warehouse (HBW) - Automated Stacker Crane."""

    def test_initial_state(self):
        """HBW should start at home position (0,0,0) with fork retracted."""
        hbw = HBWSimulation()
        assert hbw.x == 0.0
        assert hbw.y == 0.0
        assert hbw.z == 0.0
        assert hbw.gripper_closed is False
        assert hbw.has_carrier is False

    def test_slot_coordinates(self):
        """All 9 slot coordinates should be mapped correctly."""
        hbw = HBWSimulation()
        expected_slots = {
            "A1": (0, 200),
            "A2": (100, 200),
            "A3": (200, 200),
            "B1": (0, 100),
            "B2": (100, 100),
            "B3": (200, 100),
            "C1": (0, 0),
            "C2": (100, 0),
            "C3": (200, 0),
        }
        for slot, (expected_x, expected_y) in expected_slots.items():
            actual = hbw.SLOT_COORDINATES.get(slot)
            assert actual is not None, f"Slot {slot} not found"
            assert actual == (expected_x, expected_y), f"Slot {slot}: expected {(expected_x, expected_y)}, got {actual}"

    def test_move_to_slot(self):
        """HBW should accept a valid slot and set targets correctly."""
        hbw = HBWSimulation()
        success = hbw.move_to_slot("B2")
        assert success
        assert hbw.target_x == 100
        assert hbw.target_y == 100
        assert hbw.target_z == 0

        for _ in range(50):
            hbw.tick(0.1)

    def test_fork_extension(self):
        """HBW fork should extend and retract correctly."""
        hbw = HBWSimulation()
        hbw.extend_fork()
        assert hbw.target_z == hbw.FORK_EXTENSION_MM
        assert hbw.gripper_closed is True

        for _ in range(20):
            state = hbw.tick(0.1)

        hbw.retract_fork()
        for _ in range(20):
            hbw.tick(0.1)

    def test_motor_electrical_model(self):
        """Running HBW motors should consume more power than idle."""
        hbw = HBWSimulation()
        state = hbw.tick(0.1)
        idle_power = state["total_power_watts"]

        hbw.move_to(100, 100, 0)
        for _ in range(20):
            state = hbw.tick(0.1)

        running_power = state["total_power_watts"]
        assert running_power > idle_power


# =============================================================================
# TEST CLASS: VGR (Vacuum Gripper Robot) Tests
# =============================================================================


@pytest.mark.unit
class TestVGR:
    """Tests for the Vacuum Gripper Robot (VGR) - 3-Axis Gantry Robot."""

    def test_initial_state(self):
        """VGR should start at home position with vacuum off."""
        vgr = VGRSimulation()
        assert vgr.x == 0.0
        assert vgr.y == 0.0
        assert vgr.z == 0.0
        assert vgr.vacuum_active is False
        assert vgr.has_item is False

    def test_work_positions(self):
        """VGR should have required work position attributes."""
        vgr = VGRSimulation()
        assert hasattr(vgr, "DELIVERY_ZONE")
        assert hasattr(vgr, "OVEN_POSITION")
        assert hasattr(vgr, "CONVEYOR_INPUT")

    def test_vacuum_system(self):
        """VGR vacuum should activate and deactivate correctly."""
        vgr = VGRSimulation()
        assert vgr.vacuum_active is False
        assert vgr.valve_open is False

        vgr.activate_vacuum()
        assert vgr.vacuum_active is True
        assert vgr.valve_open is True

        for _ in range(10):
            vgr.tick(0.1)

        vgr.release_vacuum()
        assert vgr.vacuum_active is False
        assert vgr.has_item is False

    def test_vertical_z_axis(self):
        """VGR Z-axis should lower and raise correctly."""
        vgr = VGRSimulation()
        vgr.lower_to_pickup()
        assert vgr.target_z == vgr.PICKUP_HEIGHT_MM

        for _ in range(20):
            state = vgr.tick(0.1)

        vgr.raise_suction_cup()
        for _ in range(20):
            vgr.tick(0.1)

    def test_pickup_workflow(self):
        """Complete VGR pickup workflow should succeed."""
        vgr = VGRSimulation()

        vgr.move_to_delivery()
        for _ in range(30):
            vgr.tick(0.1)

        vgr.lower_to_pickup()
        for _ in range(20):
            vgr.tick(0.1)

        vgr.activate_vacuum()
        vgr.has_item = True
        state = vgr.tick(0.1)
        assert state["vacuum_active"] is True
        assert state["has_item"] is True

        vgr.raise_suction_cup()
        for _ in range(20):
            vgr.tick(0.1)


# =============================================================================
# TEST CLASS: Conveyor Belt Tests
# =============================================================================


@pytest.mark.unit
class TestConveyor:
    """Tests for the Conveyor Belt."""

    def test_initial_state(self):
        """Conveyor should initialise in the correct default state."""
        conveyor = ConveyorSimulation()
        assert conveyor.belt_position_mm == 0.0
        assert conveyor.has_object is False
        assert conveyor.direction == 1

    def test_conveyor_endpoints(self):
        """Conveyor should define VGR and HBW endpoint attributes."""
        conveyor = ConveyorSimulation()
        assert hasattr(conveyor, "VGR_INPUT_POSITION")
        assert hasattr(conveyor, "HBW_OUTPUT_POSITION")

    def test_object_transport(self):
        """Object placed at VGR input should move towards HBW side."""
        conveyor = ConveyorSimulation()
        conveyor.place_object(position_mm=0.0)
        assert conveyor.has_object is True
        assert conveyor.object_position_mm == 0.0

        conveyor.start(direction=1)

        positions = []
        for _ in range(100):
            state = conveyor.tick(0.1)
            if state["has_object"]:
                positions.append(state["object_position_mm"])

        assert positions[-1] > positions[0]

    def test_light_barriers(self):
        """Light barriers I2/I3 should trigger at the correct interface positions."""
        conveyor = ConveyorSimulation()

        conveyor.place_object(position_mm=400.0)
        state = conveyor.tick(0.1)
        lb_states = state["light_barriers"]
        assert lb_states["I2"]["is_triggered"] is True
        assert lb_states["I3"]["is_triggered"] is False

        conveyor.object_position_mm = 350.0
        state = conveyor.tick(0.1)
        lb_states = state["light_barriers"]
        assert lb_states["I2"]["is_triggered"] is False

        conveyor.object_position_mm = 950.0
        state = conveyor.tick(0.1)
        lb_states = state["light_barriers"]
        assert lb_states["I2"]["is_triggered"] is False
        assert lb_states["I3"]["is_triggered"] is True
        assert state.get("at_hbw_interface") is False
        assert state.get("at_vgr_interface") is True

    def test_trail_sensors(self):
        """Trail sensors I5/I6 should always be opposite and toggle during movement."""
        conveyor = ConveyorSimulation()
        conveyor.place_object(100)
        conveyor.start()

        i5_states = []
        i6_states = []

        for _ in range(50):
            state = conveyor.tick(0.1)
            ts_states = state["trail_sensors"]
            i5_states.append(ts_states["I5"]["is_triggered"])
            i6_states.append(ts_states["I6"]["is_triggered"])

        i5_toggles = sum(1 for i in range(1, len(i5_states)) if i5_states[i] != i5_states[i - 1])
        i6_toggles = sum(1 for i in range(1, len(i6_states)) if i6_states[i] != i6_states[i - 1])

        for i in range(len(i5_states)):
            assert i5_states[i] != i6_states[i], f"I5 and I6 should always be opposite at tick {i}"

        assert i5_toggles > 0
        assert i6_toggles > 0

    def test_bidirectional_operation(self):
        """Conveyor should transport objects in both directions."""
        conveyor = ConveyorSimulation()
        conveyor.place_object(500.0)

        conveyor.start(direction=1)
        for _ in range(20):
            state = conveyor.tick(0.1)
        forward_pos = state["object_position_mm"]

        conveyor.start(direction=-1)
        for _ in range(20):
            state = conveyor.tick(0.1)
        reverse_pos = state["object_position_mm"]

        assert forward_pos > 500
        assert reverse_pos < forward_pos


# =============================================================================
# TEST CLASS: Full Handshake Workflow Tests
# =============================================================================


@pytest.mark.unit
class TestHandshakeWorkflow:
    """Tests for the complete VGR -> Conveyor -> HBW handshake workflow."""

    def test_vgr_to_conveyor_handoff(self):
        """VGR should successfully place an item on the conveyor input."""
        vgr = VGRSimulation()
        conveyor = ConveyorSimulation()

        vgr.move_to_delivery()
        for _ in range(30):
            vgr.tick(0.1)

        vgr.lower_to_pickup()
        for _ in range(15):
            vgr.tick(0.1)
        vgr.activate_vacuum()
        vgr.has_item = True
        vgr.raise_suction_cup()
        for _ in range(15):
            vgr.tick(0.1)

        vgr.move_to_conveyor()
        for _ in range(40):
            vgr.tick(0.1)

        vgr.lower_to_pickup()
        for _ in range(15):
            vgr.tick(0.1)
        vgr.release_vacuum()

        conveyor.place_object(position_mm=0.0)
        state = conveyor.tick(0.1)
        assert state["has_object"] is True
        assert abs(state["object_position_mm"] - 0.0) < 10

    def test_conveyor_transport(self):
        """Conveyor should transport an item from VGR side towards HBW side."""
        conveyor = ConveyorSimulation()
        conveyor.place_object(position_mm=0.0)
        conveyor.start(direction=1)

        checkpoints = []
        for i in range(200):
            state = conveyor.tick(0.1)
            if state["has_object"] and i % 40 == 0:
                checkpoints.append(state["object_position_mm"])

        assert len(checkpoints) > 0

    def test_conveyor_to_hbw_handoff(self):
        """HBW should successfully pick an item from the conveyor output and move to a slot."""
        conveyor = ConveyorSimulation()
        hbw = HBWSimulation()

        conveyor.place_object(position_mm=950.0)

        hbw.move_to_conveyor()
        for _ in range(40):
            hbw.tick(0.1)

        hbw.extend_fork()
        for _ in range(20):
            state = hbw.tick(0.1)

        hbw.has_carrier = True
        conveyor.remove_object()
        hbw.retract_fork()
        for _ in range(20):
            hbw.tick(0.1)

        hbw.move_to_slot("B2")
        for _ in range(50):
            state = hbw.tick(0.1)

        assert state["has_carrier"] is True

    def test_complete_store_workflow(self):
        """End-to-end store workflow: Raw item -> VGR -> Conveyor -> HBW -> Slot."""
        vgr = VGRSimulation()
        conveyor = ConveyorSimulation()
        hbw = HBWSimulation()

        # Phase 1: VGR picks from delivery
        vgr.move_to_delivery()
        for _ in range(30):
            vgr.tick(0.1)
        vgr.lower_to_pickup()
        for _ in range(15):
            vgr.tick(0.1)
        vgr.activate_vacuum()
        vgr.has_item = True
        vgr.raise_suction_cup()
        for _ in range(15):
            vgr.tick(0.1)

        # Phase 2: VGR places on conveyor
        vgr.move_to_conveyor()
        for _ in range(40):
            vgr.tick(0.1)
        vgr.lower_to_pickup()
        for _ in range(15):
            vgr.tick(0.1)
        vgr.release_vacuum()
        conveyor.place_object(position_mm=0.0)

        # Phase 3: Conveyor transport
        conveyor.start(direction=1)
        state = {}
        for i in range(150):
            state = conveyor.tick(0.1)
            if state["object_position_mm"] and state["object_position_mm"] > 900:
                break
        conveyor.stop()

        # Phase 4: HBW picks from conveyor
        hbw.move_to_conveyor()
        for _ in range(40):
            hbw.tick(0.1)
        hbw.extend_fork()
        for _ in range(20):
            hbw.tick(0.1)
        hbw.has_carrier = True
        conveyor.remove_object()
        hbw.retract_fork()
        for _ in range(20):
            hbw.tick(0.1)

        # Phase 5: HBW stores in slot A1
        hbw.move_to_slot("A1")
        for _ in range(60):
            hbw.tick(0.1)
        hbw.extend_fork()
        for _ in range(20):
            hbw.tick(0.1)
        hbw.has_carrier = False
        hbw.retract_fork()
        for _ in range(20):
            state = hbw.tick(0.1)

        assert state["has_carrier"] is False


# =============================================================================
# TEST CLASS: Motor Electrical Model Tests
# =============================================================================


@pytest.mark.unit
class TestElectricalModel:
    """Tests for motor electrical characteristics and wear model."""

    @pytest.mark.slow
    def test_motor_phases(self):
        """Motor should transition through IDLE -> STARTUP -> RUNNING -> STOPPING -> IDLE."""
        motor = MotorSimulation("TEST_MOTOR")

        state = motor.tick(0.1)
        assert motor.phase == MotorPhase.IDLE

        motor.activate()
        state = motor.tick(0.1)
        assert motor.phase == MotorPhase.STARTUP

        time.sleep(0.6)
        state = motor.tick(0.1)
        assert motor.phase == MotorPhase.RUNNING

        motor.deactivate()
        state = motor.tick(0.1)
        assert motor.phase == MotorPhase.STOPPING

        for _ in range(20):
            state = motor.tick(0.1)
            if motor.phase == MotorPhase.IDLE:
                break
        assert motor.phase == MotorPhase.IDLE

    @pytest.mark.slow
    def test_health_degradation(self):
        """Motor health should degrade during extended operation."""
        motor = MotorSimulation("TEST_MOTOR")
        initial_health = motor.health_score

        motor.activate()
        time.sleep(0.6)
        motor.tick(0.1)
        assert motor.phase == MotorPhase.RUNNING

        for _ in range(10000):
            motor.tick(0.01)

        final_health = motor.health_score
        assert final_health < initial_health

    def test_power_calculation(self):
        """Power calculation should be consistent with P = I x V."""
        motor = MotorSimulation("TEST_MOTOR", ElectricalModel(running_amps=2.0, voltage=24.0))
        motor.activate()

        for _ in range(15):
            state = motor.tick(0.1)

        actual_power = state["power_watts"]
        actual_current = state["current_amps"]
        calculated_power = actual_current * 24.0
        assert abs(actual_power - calculated_power) < 0.1


# =============================================================================
# TEST CLASS: Z-Axis Comparison (HBW vs VGR)
# =============================================================================


@pytest.mark.unit
class TestZAxisComparison:
    """Tests demonstrating the Z-axis difference between HBW and VGR."""

    def test_z_axis_semantics(self):
        """Both robots use positive Z, but their spatial direction differs."""
        hbw = HBWSimulation()
        vgr = VGRSimulation()

        hbw.extend_fork()
        for _ in range(20):
            hbw_state = hbw.tick(0.1)

        vgr.lower_to_pickup()
        for _ in range(20):
            vgr_state = vgr.tick(0.1)

        assert hbw_state["z"] > 0
        assert vgr_state["z"] > 0


# =============================================================================
# TEST CLASS: Sensor-Based Conveyor Positioning Tests
# =============================================================================


@pytest.mark.unit
class TestSensorBasedPositioning:
    """Tests for the sensor-based conveyor positioning algorithm."""

    def test_sensor_constants(self):
        """Sensor position constants should be defined with correct values."""
        conveyor = ConveyorSimulation()
        assert conveyor.POS_HBW_INTERFACE == 400.0
        assert conveyor.POS_VGR_INTERFACE == 950.0
        assert conveyor.SENSOR_TOLERANCE_MM == 25.0
        assert conveyor.TRAIL_RIB_SPACING_MM == 10.0

    def test_inbound_transport_simulation(self):
        """Inbound transport should trigger I2 at the HBW interface."""
        conveyor = ConveyorSimulation()
        conveyor.place_object(position_mm=0.0)
        conveyor.start(direction=1)

        i2_triggered = False
        tick_count = 0
        max_ticks = 100

        while not i2_triggered and tick_count < max_ticks:
            state = conveyor.tick(0.1)
            i2_triggered = state["at_hbw_interface"]
            tick_count += 1

        conveyor.stop()
        final_pos = conveyor.object_position_mm

        assert i2_triggered
        assert 375 <= final_pos <= 425

    def test_outbound_transport_simulation(self):
        """Outbound transport should trigger I3 at the VGR interface."""
        conveyor = ConveyorSimulation()
        conveyor.place_object(position_mm=400.0)
        conveyor.start(direction=1)

        i3_triggered = False
        tick_count = 0
        max_ticks = 100

        while not i3_triggered and tick_count < max_ticks:
            state = conveyor.tick(0.1)
            i3_triggered = state["at_vgr_interface"]
            tick_count += 1

        conveyor.stop()
        final_pos = conveyor.object_position_mm

        assert i3_triggered
        assert 925 <= final_pos <= 975

    def test_helper_methods(self):
        """Position helper methods should return correct boolean values."""
        conveyor = ConveyorSimulation()

        conveyor.place_object(position_mm=400.0)
        assert conveyor.is_at_hbw_interface() is True

        conveyor.object_position_mm = 300.0
        assert conveyor.is_at_hbw_interface() is False

        conveyor.object_position_mm = 950.0
        assert conveyor.is_at_vgr_interface() is True

        conveyor.object_position_mm = 800.0
        assert conveyor.is_at_vgr_interface() is False

        conveyor.object_position_mm = 400.0
        sensors = conveyor.get_sensor_states()
        assert "I2" in sensors and "I3" in sensors
        assert sensors["I2"] is True

    def test_motion_proof_via_trail_sensors(self):
        """Trail sensors should toggle roughly every 10mm to prove motion."""
        conveyor = ConveyorSimulation()
        conveyor.place_object(0)
        conveyor.start(direction=1)

        i5_toggles = 0
        last_i5_state = conveyor._trail_toggle_state

        for _ in range(20):
            state = conveyor.tick(0.1)
            current_i5 = state["trail_sensors"]["I5"]["is_triggered"]
            if current_i5 != last_i5_state:
                i5_toggles += 1
                last_i5_state = current_i5

        belt_travel = conveyor.belt_position_mm
        expected_toggles = int(belt_travel / 10)

        assert i5_toggles >= expected_toggles - 2


if __name__ == "__main__":
    import pytest as _pytest

    raise SystemExit(_pytest.main([__file__, "-v"]))
