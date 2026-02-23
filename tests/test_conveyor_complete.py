"""
STF Digital Twin - Complete Conveyor Belt Operation Test (pytest)

Tests the COMPLETE working of the conveyor belt system:
1. Inbound Transport: VGR -> HBW (item placed by VGR, picked up by HBW)
2. Outbound Transport: HBW -> VGR (item placed by HBW, picked up by VGR)
3. Congestion Avoidance: What happens when interfaces are blocked

Conveyor Belt Specifications:
- Belt length: 120mm (~12cm realistic Fischertechnik conveyor)
- I2: Triggers at HBW interface (~105mm +-10mm)
- I3: Triggers at VGR interface (~15mm +-10mm)
- I5/I6: Toggle every 5mm to prove physical motion
"""

import os
import sys
import time

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hardware.mock_factory import ConveyorSimulation, MotorPhase


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
        self.log.append(message)

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
        """Move item from VGR side to HBW side (inbound transport)."""
        result = {
            "success": False,
            "direction": "INBOUND (VGR -> HBW)",
            "start_position": self.conveyor.object_position_mm,
            "final_position": None,
            "sensor_triggered": None,
            "ticks": 0,
            "error": None,
        }

        sensors = self.get_sensor_states()
        if sensors["I2"]:
            result["error"] = "CONGESTION: I2 already triggered (HBW interface blocked)"
            return result

        self._log("Congestion check passed (I2 clear)")
        self.conveyor.start(direction=1)
        self._log("Motor M1 started (direction: INWARD/Q1)")

        start_time = time.time()
        ticks = 0

        while time.time() - start_time < self.TIMEOUT_SECONDS:
            state = self.conveyor.tick(self.TICK_INTERVAL)
            ticks += 1

            if state["at_hbw_interface"]:
                self.conveyor.stop()
                self._log(f"I2 triggered at position {state['object_position_mm']:.1f}mm")
                result["success"] = True
                result["final_position"] = state["object_position_mm"]
                result["sensor_triggered"] = "I2"
                result["ticks"] = ticks
                return result

        self.conveyor.stop()
        result["error"] = f"TIMEOUT: I2 not triggered within {self.TIMEOUT_SECONDS}s (belt jammed?)"
        result["final_position"] = self.conveyor.object_position_mm
        result["ticks"] = ticks
        return result

    def move_outbound(self) -> dict:
        """Move item from HBW side to VGR side (outbound transport)."""
        result = {
            "success": False,
            "direction": "OUTBOUND (HBW -> VGR)",
            "start_position": self.conveyor.object_position_mm,
            "final_position": None,
            "sensor_triggered": None,
            "ticks": 0,
            "error": None,
        }

        sensors = self.get_sensor_states()
        if sensors["I3"]:
            result["error"] = "CONGESTION: I3 already triggered (VGR interface blocked)"
            return result

        self._log("Congestion check passed (I3 clear)")
        self.conveyor.start(direction=-1)
        self._log("Motor M1 started (direction: OUTWARD/Q2)")

        start_time = time.time()
        ticks = 0

        while time.time() - start_time < self.TIMEOUT_SECONDS:
            state = self.conveyor.tick(self.TICK_INTERVAL)
            ticks += 1

            if state["at_vgr_interface"]:
                self.conveyor.stop()
                self._log(f"I3 triggered at position {state['object_position_mm']:.1f}mm")
                result["success"] = True
                result["final_position"] = state["object_position_mm"]
                result["sensor_triggered"] = "I3"
                result["ticks"] = ticks
                return result

        self.conveyor.stop()
        result["error"] = f"TIMEOUT: I3 not triggered within {self.TIMEOUT_SECONDS}s (belt jammed?)"
        result["final_position"] = self.conveyor.object_position_mm
        result["ticks"] = ticks
        return result


# =============================================================================
# TEST SCENARIOS
# =============================================================================


@pytest.mark.unit
class TestConveyorInbound:
    """Tests for inbound transport (VGR -> HBW)."""

    def test_inbound_transport(self):
        """Complete inbound transport: item placed at 0mm arrives at HBW interface."""
        controller = ConveyorController()
        controller.conveyor.place_object(position_mm=0.0)

        result = controller.move_inbound()

        assert result["success"], f"Inbound transport failed: {result['error']}"
        assert result["sensor_triggered"] == "I2"
        # Final position should be near HBW interface
        assert result["final_position"] is not None


@pytest.mark.unit
class TestConveyorOutbound:
    """Tests for outbound transport (HBW -> VGR)."""

    def test_outbound_transport(self):
        """Complete outbound transport: item placed at 105mm arrives at VGR interface."""
        controller = ConveyorController()
        controller.conveyor.place_object(position_mm=105.0)

        result = controller.move_outbound()

        assert result["success"], f"Outbound transport failed: {result['error']}"
        assert result["sensor_triggered"] == "I3"
        assert result["final_position"] is not None


@pytest.mark.unit
class TestConveyorCongestion:
    """Tests for congestion avoidance."""

    def test_hbw_blocked(self):
        """Inbound transport should be rejected when HBW interface is already blocked."""
        controller = ConveyorController()
        controller.conveyor.place_object(position_mm=105.0)
        controller.conveyor.tick(0.1)  # Update state

        sensors = controller.get_sensor_states()
        assert sensors["I2"], "Test setup failed - I2 should be triggered"

        result = controller.move_inbound()

        assert not result["success"]
        assert result["error"] is not None
        assert "CONGESTION" in result["error"]

    def test_vgr_blocked(self):
        """Outbound transport should be rejected when VGR interface is already blocked."""
        controller = ConveyorController()
        controller.conveyor.place_object(position_mm=15.0)
        controller.conveyor.tick(0)  # Update state

        sensors = controller.get_sensor_states()
        assert sensors["I3"], "Test setup failed - I3 should be triggered"

        result = controller.move_outbound()

        assert not result["success"]
        assert result["error"] is not None
        assert "CONGESTION" in result["error"]


@pytest.mark.unit
class TestConveyorRoundTrip:
    """Tests for complete round trips."""

    def test_full_round_trip(self):
        """Complete round trip: VGR -> HBW -> VGR."""
        # Phase 1: VGR -> HBW
        controller1 = ConveyorController()
        controller1.conveyor.place_object(position_mm=0.0)
        result1 = controller1.move_inbound()
        assert result1["success"], f"Phase 1 failed: {result1['error']}"

        controller1.conveyor.remove_object()

        # Phase 2: HBW -> VGR
        controller2 = ConveyorController()
        controller2.conveyor.place_object(position_mm=105.0)
        result2 = controller2.move_outbound()
        assert result2["success"], f"Phase 2 failed: {result2['error']}"

        controller2.conveyor.remove_object()


@pytest.mark.unit
class TestTrailSensors:
    """Tests for trail sensor motion proof."""

    def test_motion_proof(self):
        """Trail sensors I5/I6 should alternate during belt movement."""
        controller = ConveyorController()
        controller.conveyor.place_object(position_mm=0.0)
        controller.conveyor.start(direction=1)

        last_i5 = None
        motion_events = 0

        for _ in range(30):
            state = controller.conveyor.tick(0.1)
            pos = state["object_position_mm"]
            if pos is None:
                break
            i5 = state["trail_sensors"]["I5"]["is_triggered"]
            if last_i5 is not None and i5 != last_i5:
                motion_events += 1
            last_i5 = i5

        controller.conveyor.stop()

        belt_travel = controller.conveyor.belt_position_mm
        expected_toggles = int(belt_travel / 5)

        assert motion_events >= expected_toggles - 2, (
            f"Expected ~{expected_toggles} toggles, got {motion_events}"
        )


if __name__ == "__main__":
    import pytest as _pytest

    raise SystemExit(_pytest.main([__file__, "-v"]))
