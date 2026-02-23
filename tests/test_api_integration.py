#!/usr/bin/env python3
"""
STF Digital Twin - API Integration Tests (pytest)

Validates the complete working cycle of the STF Digital Twin API.
All tests in this module require a running API server.

Set STF_API_URL env var to override the default http://localhost:8000.
"""

import os
import sys
from typing import Any, Dict, Optional

import pytest
import requests

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Default configuration
DEFAULT_API_URL = os.environ.get("STF_API_URL", "http://localhost:8000")


class STFTestClient:
    """HTTP client for interacting with the STF API."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.timeout = 10

    def get(self, endpoint: str, params: Dict = None) -> requests.Response:
        """Send a GET request to the API."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        return self.session.get(url, params=params, timeout=self.timeout)

    def post(self, endpoint: str, data: Dict = None) -> requests.Response:
        """Send a POST request to the API."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        return self.session.post(url, json=data, timeout=self.timeout)


@pytest.fixture(scope="module")
def client():
    """Shared API client for integration tests."""
    return STFTestClient(DEFAULT_API_URL)


@pytest.mark.integration
class TestAPIHealth:
    """Test the API health and connectivity."""

    def test_health_check(self, client):
        """API should be healthy and responding."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data


@pytest.mark.integration
class TestSystemInitialization:
    """Test system initialization and seeding."""

    def test_initialize_system(self, client):
        """System initialization should succeed."""
        response = client.post("/maintenance/initialize")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success", False)

    def test_reset_system(self, client):
        """System reset should succeed."""
        response = client.post("/maintenance/reset")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success", False)


@pytest.mark.integration
class TestInventoryManagement:
    """Test inventory-related operations."""

    def test_get_inventory(self, client):
        """Inventory should return a non-empty list with expected slots."""
        client.post("/maintenance/initialize")
        response = client.get("/inventory")
        assert response.status_code == 200
        inventory = response.json()
        assert isinstance(inventory, list)
        assert len(inventory) > 0

        slot_names = [slot["slot_name"] for slot in inventory]
        for slot in ["A1", "A2", "A3", "B1", "B2", "B3", "C1", "C2", "C3"]:
            assert slot in slot_names

    def test_get_dashboard_data(self, client):
        """Dashboard data should contain all expected keys."""
        response = client.get("/dashboard/data")
        assert response.status_code == 200
        data = response.json()

        for key in ["inventory", "hardware", "motors", "sensors", "logs", "energy", "stats"]:
            assert key in data

        stats = data["stats"]
        assert "total_slots" in stats
        assert "occupied_slots" in stats


@pytest.mark.integration
class TestComponentSpecs:
    """Test component specification endpoints."""

    def test_get_all_component_specs(self, client):
        """Component specs endpoint should return a list with required fields."""
        client.post("/maintenance/initialize")
        response = client.get("/components/specs")
        assert response.status_code == 200
        specs = response.json()
        assert isinstance(specs, list)
        assert len(specs) > 0

        for spec in specs:
            assert "id" in spec
            assert "name" in spec
            assert "subsystem" in spec
            assert "component_type" in spec


@pytest.mark.integration
class TestMotorAndSensorStates:
    """Test motor and sensor state endpoints."""

    def test_get_motor_states(self, client):
        """Motor states endpoint should return valid motor data."""
        client.post("/maintenance/initialize")
        response = client.get("/motors/states")
        assert response.status_code == 200
        motors = response.json()
        assert isinstance(motors, list)

        for motor in motors:
            assert "component_id" in motor
            assert "current_amps" in motor
            assert "health_score" in motor
            assert "is_active" in motor

    def test_get_sensor_states(self, client):
        """Sensor states endpoint should return valid sensor data."""
        response = client.get("/sensors/states")
        assert response.status_code == 200
        sensors = response.json()
        assert isinstance(sensors, list)

        for sensor in sensors:
            assert "component_id" in sensor
            assert "is_triggered" in sensor
            assert "trigger_count" in sensor


@pytest.mark.integration
class TestHardwareStates:
    """Test hardware state endpoints."""

    def test_get_hardware_states(self, client):
        """Hardware states should include HBW, VGR, and CONVEYOR devices."""
        client.post("/maintenance/initialize")
        response = client.get("/hardware/states")
        assert response.status_code == 200
        hardware = response.json()
        assert isinstance(hardware, list)

        device_ids = [hw["device_id"] for hw in hardware]
        for device in ["HBW", "VGR", "CONVEYOR"]:
            assert device in device_ids

    def test_update_hardware_state(self, client):
        """Updating hardware state should persist the new values."""
        update_data = {"device_id": "HBW", "x": 100.0, "y": 200.0, "z": 0.0, "status": "IDLE"}
        response = client.post("/hardware/state", data=update_data)
        assert response.status_code == 200
        data = response.json()

        assert data["device_id"] == "HBW"
        assert data["current_x"] == 100.0
        assert data["current_y"] == 200.0


@pytest.mark.integration
class TestOrderOperations:
    """Test order operations (store, retrieve, process)."""

    def test_store_cookie(self, client):
        """Storing a cookie should return a slot name and batch UUID."""
        client.post("/maintenance/reset")
        client.post("/maintenance/initialize")

        response = client.post("/order/store", data={"flavor": "VANILLA"})
        assert response.status_code == 200
        data = response.json()

        assert data.get("success", False)
        assert "slot_name" in data
        assert "batch_uuid" in data

    def test_retrieve_cookie(self, client):
        """Retrieving from an occupied slot should succeed."""
        client.post("/maintenance/initialize")
        response = client.get("/inventory")
        inventory = response.json()

        occupied_slot = None
        for slot in inventory:
            if slot.get("carrier_id") is not None:
                occupied_slot = slot["slot_name"]
                break

        if occupied_slot is None:
            pytest.skip("No occupied slots available for retrieval test")

        response = client.post("/order/retrieve", data={"slot_name": occupied_slot})
        assert response.status_code == 200
        data = response.json()
        assert data.get("success", False)

    def test_process_cookie(self, client):
        """Processing a RAW_DOUGH cookie should succeed."""
        response = client.get("/inventory")
        inventory = response.json()

        raw_dough_slot = None
        for slot in inventory:
            if slot.get("cookie_status") == "RAW_DOUGH":
                raw_dough_slot = slot["slot_name"]
                break

        if raw_dough_slot is None:
            pytest.skip("No RAW_DOUGH cookies available for processing test")

        response = client.post("/order/process", data={"source_slot": raw_dough_slot})
        assert response.status_code == 200
        data = response.json()
        assert data.get("success", False)


@pytest.mark.integration
class TestTelemetryAndEnergy:
    """Test telemetry and energy logging endpoints."""

    def test_record_telemetry(self, client):
        """Recording telemetry data should succeed."""
        client.post("/maintenance/initialize")
        telemetry_data = {
            "device_id": "HBW",
            "metric_name": "test_metric",
            "metric_value": 42.0,
            "unit": "test_unit",
        }
        response = client.post("/telemetry", data=telemetry_data)
        assert response.status_code == 200
        data = response.json()
        assert data.get("success", False)

    def test_record_energy(self, client):
        """Recording energy consumption data should succeed."""
        energy_data = {
            "device_id": "HBW",
            "joules": 100.0,
            "voltage": 24.0,
            "current_amps": 1.5,
            "power_watts": 36.0,
        }
        response = client.post("/energy", data=energy_data)
        assert response.status_code == 200
        data = response.json()
        assert data.get("success", False)


@pytest.mark.integration
class TestEmergencyStop:
    """Test emergency stop functionality."""

    def test_emergency_stop(self, client):
        """Emergency stop should succeed."""
        client.post("/maintenance/initialize")
        response = client.post("/maintenance/emergency-stop")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success", False)

    def test_reset_after_emergency(self, client):
        """System reset after emergency stop should succeed."""
        response = client.post("/maintenance/reset")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success", False)


if __name__ == "__main__":
    import pytest as _pytest

    raise SystemExit(_pytest.main([__file__, "-v"]))
