"""
Shared pytest fixtures for STF Digital Twin tests.
"""

import os
import sys

import pytest

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from controller.main_controller import KinematicController
except ImportError:
    KinematicController = None  # type: ignore[assignment]

try:
    from hardware.mock_factory import (
        ConveyorSimulation,
        HBWSimulation,
        MotorSimulation,
        VGRSimulation,
    )
except ImportError:
    ConveyorSimulation = None  # type: ignore[assignment]
    HBWSimulation = None  # type: ignore[assignment]
    MotorSimulation = None  # type: ignore[assignment]
    VGRSimulation = None  # type: ignore[assignment]

try:
    from dataclasses import dataclass
    from typing import Dict

    @dataclass
    class SimulatedPosition:
        """Tracks simulated robot position during test."""

        x: float
        y: float
        z: float

        def as_tuple(self):
            return (self.x, self.y, self.z)

        def update_from_step(self, step: Dict):
            """Update position based on a kinematic step."""
            axis = step["axis"]
            target = step["target"]
            if axis == "X":
                self.x = target
            elif axis == "Y":
                self.y = target
            elif axis == "Z":
                self.z = target

except Exception:
    SimulatedPosition = None  # type: ignore[assignment]


@pytest.fixture
def kinematic_controller():
    """Return a fresh KinematicController instance."""
    if KinematicController is None:
        pytest.skip("KinematicController not available")
    return KinematicController()


@pytest.fixture
def conveyor():
    """Return a fresh ConveyorSimulation instance."""
    if ConveyorSimulation is None:
        pytest.skip("ConveyorSimulation not available")
    return ConveyorSimulation()


@pytest.fixture
def hbw():
    """Return a fresh HBWSimulation instance."""
    if HBWSimulation is None:
        pytest.skip("HBWSimulation not available")
    return HBWSimulation()


@pytest.fixture
def vgr():
    """Return a fresh VGRSimulation instance."""
    if VGRSimulation is None:
        pytest.skip("VGRSimulation not available")
    return VGRSimulation()


@pytest.fixture
def motor():
    """Return a fresh MotorSimulation instance."""
    if MotorSimulation is None:
        pytest.skip("MotorSimulation not available")
    return MotorSimulation("TEST_MOTOR")


@pytest.fixture
def simulated_position():
    """Return a factory function for creating SimulatedPosition instances."""
    if SimulatedPosition is None:
        pytest.skip("SimulatedPosition not available")

    def _factory(x: float, y: float, z: float) -> SimulatedPosition:
        return SimulatedPosition(x=x, y=y, z=z)

    return _factory


@pytest.fixture
def api_client():
    """Return an STFTestClient pointing at the configured API URL."""
    try:
        import requests  # noqa: F401
    except ImportError:
        pytest.skip("requests not available")

    # Import inline to avoid import errors when requests is unavailable
    from tests.test_api_integration import STFTestClient  # noqa: PLC0415

    api_url = os.environ.get("STF_API_URL", "http://localhost:8000")
    return STFTestClient(api_url)
