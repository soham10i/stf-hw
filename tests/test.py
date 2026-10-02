#!/usr/bin/env python3
"""
STF Digital Twin - System Validation Test Suite

This test script validates the complete working cycle of the STF Digital Twin system.
It tests the following components:
1. Database initialization and seeding
2. API endpoints (store, retrieve, process)
3. Command queue processing
4. Inventory management
5. Hardware state updates

Usage:
    python test.py [--api-url http://localhost:8000] [--db-path ./stf_digital_twin.db]

Requirements:
    - The API server must be running (uvicorn api.main:app --port 8000)
    - SQLite database file must be accessible (default: ./stf_digital_twin.db)
    - Alternatively, set DATABASE_URL environment variable to use a different database

"""

import argparse
import json
import os
import sys
import time
import unittest
from datetime import datetime
from typing import Optional, Dict, Any

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


class TestAPIHealth(unittest.TestCase):
    """Test the API health and connectivity."""
    
    @classmethod
    def setUpClass(cls):
        cls.client = STFTestClient(DEFAULT_API_URL)
    
    def test_01_health_check(self):
        """Test that the API is healthy and responding."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "healthy")
        self.assertIn("version", data)
        print(f"  ✓ API is healthy (version: {data['version']})")


class TestSystemInitialization(unittest.TestCase):
    """Test system initialization and seeding."""
    
    @classmethod
    def setUpClass(cls):
        cls.client = STFTestClient(DEFAULT_API_URL)
    
    def test_01_initialize_system(self):
        """Test system initialization."""
        response = self.client.post("/maintenance/initialize")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success", False))
        print(f"  ✓ System initialized: {data.get('message', 'OK')}")
    
    def test_02_reset_system(self):
        """Test system reset."""
        response = self.client.post("/maintenance/reset")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success", False))
        print(f"  ✓ System reset: {data.get('message', 'OK')}")


class TestInventoryManagement(unittest.TestCase):
    """Test inventory-related operations."""
    
    @classmethod
    def setUpClass(cls):
        cls.client = STFTestClient(DEFAULT_API_URL)
        # Initialize system first
        cls.client.post("/maintenance/initialize")
    
    def test_01_get_inventory(self):
        """Test fetching the inventory."""
        response = self.client.get("/inventory")
        self.assertEqual(response.status_code, 200)
        inventory = response.json()
        self.assertIsInstance(inventory, list)
        self.assertGreater(len(inventory), 0)
        
        # Check that we have the expected slots
        slot_names = [slot["slot_name"] for slot in inventory]
        expected_slots = ["A1", "A2", "A3", "B1", "B2", "B3", "C1", "C2", "C3"]
        for slot in expected_slots:
            self.assertIn(slot, slot_names)
        
        print(f"  ✓ Inventory retrieved: {len(inventory)} slots")
    
    def test_02_get_dashboard_data(self):
        """Test fetching the full dashboard data."""
        response = self.client.get("/dashboard/data")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Check that all expected keys are present
        expected_keys = ["inventory", "hardware", "motors", "sensors", "logs", "energy", "stats"]
        for key in expected_keys:
            self.assertIn(key, data)
        
        # Check stats
        stats = data["stats"]
        self.assertIn("total_slots", stats)
        self.assertIn("occupied_slots", stats)
        
        print(f"  ✓ Dashboard data retrieved: {stats['occupied_slots']}/{stats['total_slots']} slots occupied")


class TestComponentSpecs(unittest.TestCase):
    """Test component specification endpoints."""
    
    @classmethod
    def setUpClass(cls):
        cls.client = STFTestClient(DEFAULT_API_URL)
        cls.client.post("/maintenance/initialize")
    
    def test_01_get_all_component_specs(self):
        """Test fetching all component specifications."""
        response = self.client.get("/components/specs")
        self.assertEqual(response.status_code, 200)
        specs = response.json()
        self.assertIsInstance(specs, list)
        self.assertGreater(len(specs), 0)
        
        # Check that each spec has the required fields
        for spec in specs:
            self.assertIn("id", spec)
            self.assertIn("name", spec)
            self.assertIn("subsystem", spec)
            self.assertIn("component_type", spec)
        
        print(f"  ✓ Component specs retrieved: {len(specs)} components")


class TestMotorAndSensorStates(unittest.TestCase):
    """Test motor and sensor state endpoints."""
    
    @classmethod
    def setUpClass(cls):
        cls.client = STFTestClient(DEFAULT_API_URL)
        cls.client.post("/maintenance/initialize")
    
    def test_01_get_motor_states(self):
        """Test fetching all motor states."""
        response = self.client.get("/motors/states")
        self.assertEqual(response.status_code, 200)
        motors = response.json()
        self.assertIsInstance(motors, list)
        
        # Check that each motor has the required fields
        for motor in motors:
            self.assertIn("component_id", motor)
            self.assertIn("current_amps", motor)
            self.assertIn("health_score", motor)
            self.assertIn("is_active", motor)
        
        print(f"  ✓ Motor states retrieved: {len(motors)} motors")
    
    def test_02_get_sensor_states(self):
        """Test fetching all sensor states."""
        response = self.client.get("/sensors/states")
        self.assertEqual(response.status_code, 200)
        sensors = response.json()
        self.assertIsInstance(sensors, list)
        
        # Check that each sensor has the required fields
        for sensor in sensors:
            self.assertIn("component_id", sensor)
            self.assertIn("is_triggered", sensor)
            self.assertIn("trigger_count", sensor)
        
        print(f"  ✓ Sensor states retrieved: {len(sensors)} sensors")


class TestHardwareStates(unittest.TestCase):
    """Test hardware state endpoints."""
    
    @classmethod
    def setUpClass(cls):
        cls.client = STFTestClient(DEFAULT_API_URL)
        cls.client.post("/maintenance/initialize")
    
    def test_01_get_hardware_states(self):
        """Test fetching all hardware states."""
        response = self.client.get("/hardware/states")
        self.assertEqual(response.status_code, 200)
        hardware = response.json()
        self.assertIsInstance(hardware, list)
        
        # Check that we have the expected hardware devices
        device_ids = [hw["device_id"] for hw in hardware]
        expected_devices = ["HBW", "VGR", "CONVEYOR"]
        for device in expected_devices:
            self.assertIn(device, device_ids)
        
        print(f"  ✓ Hardware states retrieved: {len(hardware)} devices")
    
    def test_02_update_hardware_state(self):
        """Test updating a hardware state."""
        update_data = {
            "device_id": "HBW",
            "x": 100.0,
            "y": 200.0,
            "z": 0.0,
            "status": "IDLE"
        }
        response = self.client.post("/hardware/state", data=update_data)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertEqual(data["device_id"], "HBW")
        self.assertEqual(data["current_x"], 100.0)
        self.assertEqual(data["current_y"], 200.0)
        
        print(f"  ✓ Hardware state updated: HBW at ({data['current_x']}, {data['current_y']})")


class TestOrderOperations(unittest.TestCase):
    """Test order operations (store, retrieve, process)."""
    
    @classmethod
    def setUpClass(cls):
        cls.client = STFTestClient(DEFAULT_API_URL)
        # Reset the system to ensure a clean state
        cls.client.post("/maintenance/reset")
        cls.client.post("/maintenance/initialize")
    
    def test_01_store_cookie(self):
        """Test storing a cookie."""
        store_data = {
            "flavor": "VANILLA"
        }
        response = self.client.post("/order/store", data=store_data)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data.get("success", False))
        self.assertIn("slot_name", data)
        self.assertIn("batch_uuid", data)
        
        # Store the slot name for later tests
        self.__class__.stored_slot = data.get("slot_name")
        self.__class__.stored_batch_uuid = data.get("batch_uuid")
        
        print(f"  ✓ Cookie stored in slot {data['slot_name']} (batch: {data['batch_uuid'][:8]}...)")
    
    def test_02_retrieve_cookie(self):
        """Test retrieving a cookie."""
        # First, get the inventory to find an occupied slot
        response = self.client.get("/inventory")
        inventory = response.json()
        
        # Find an occupied slot
        occupied_slot = None
        for slot in inventory:
            if slot.get("carrier_id") is not None:
                occupied_slot = slot["slot_name"]
                break
        
        if occupied_slot is None:
            self.skipTest("No occupied slots available for retrieval test")
        
        retrieve_data = {
            "slot_name": occupied_slot
        }
        response = self.client.post("/order/retrieve", data=retrieve_data)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data.get("success", False))
        print(f"  ✓ Cookie retrieved from slot {occupied_slot}")
    
    def test_03_process_cookie(self):
        """Test processing a cookie (RAW_DOUGH -> BAKED)."""
        # First, get the inventory to find a slot with RAW_DOUGH
        response = self.client.get("/inventory")
        inventory = response.json()
        
        # Find a slot with RAW_DOUGH
        raw_dough_slot = None
        for slot in inventory:
            if slot.get("cookie_status") == "RAW_DOUGH":
                raw_dough_slot = slot["slot_name"]
                break
        
        if raw_dough_slot is None:
            self.skipTest("No RAW_DOUGH cookies available for processing test")
        
        process_data = {
            "source_slot": raw_dough_slot
        }
        response = self.client.post("/order/process", data=process_data)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data.get("success", False))
        print(f"  ✓ Cookie from slot {raw_dough_slot} queued for processing")


class TestTelemetryAndEnergy(unittest.TestCase):
    """Test telemetry and energy logging endpoints."""
    
    @classmethod
    def setUpClass(cls):
        cls.client = STFTestClient(DEFAULT_API_URL)
        cls.client.post("/maintenance/initialize")
    
    def test_01_record_telemetry(self):
        """Test recording telemetry data."""
        telemetry_data = {
            "device_id": "HBW",
            "metric_name": "test_metric",
            "metric_value": 42.0,
            "unit": "test_unit"
        }
        response = self.client.post("/telemetry", data=telemetry_data)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data.get("success", False))
        print(f"  ✓ Telemetry recorded: {telemetry_data['metric_name']} = {telemetry_data['metric_value']}")
    
    def test_02_record_energy(self):
        """Test recording energy consumption data."""
        energy_data = {
            "device_id": "HBW",
            "joules": 100.0,
            "voltage": 24.0,
            "current_amps": 1.5,
            "power_watts": 36.0
        }
        response = self.client.post("/energy", data=energy_data)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data.get("success", False))
        print(f"  ✓ Energy recorded: {energy_data['joules']} J at {energy_data['power_watts']} W")


class TestEmergencyStop(unittest.TestCase):
    """Test emergency stop functionality."""
    
    @classmethod
    def setUpClass(cls):
        cls.client = STFTestClient(DEFAULT_API_URL)
        cls.client.post("/maintenance/initialize")
    
    def test_01_emergency_stop(self):
        """Test emergency stop."""
        response = self.client.post("/maintenance/emergency-stop")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data.get("success", False))
        print(f"  ✓ Emergency stop activated: {data.get('message', 'OK')}")
    
    def test_02_reset_after_emergency(self):
        """Test reset after emergency stop."""
        response = self.client.post("/maintenance/reset")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data.get("success", False))
        print(f"  ✓ System reset after emergency: {data.get('message', 'OK')}")


def run_tests(api_url: str):
    """Run all tests and print a summary."""
    global DEFAULT_API_URL
    DEFAULT_API_URL = api_url
    
    print("=" * 70)
    print("STF Digital Twin - System Validation Test Suite")
    print("=" * 70)
    print(f"API URL: {api_url}")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("=" * 70)
    
    # Create a test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test classes in order
    test_classes = [
        TestAPIHealth,
        TestSystemInitialization,
        TestInventoryManagement,
        TestComponentSpecs,
        TestMotorAndSensorStates,
        TestHardwareStates,
        TestOrderOperations,
        TestTelemetryAndEnergy,
        TestEmergencyStop,
    ]
    
    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)
    
    # Run the tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    
    if result.wasSuccessful():
        print("\n✓ All tests passed!")
        return 0
    else:
        print("\n✗ Some tests failed.")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="STF Digital Twin Test Suite")
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"API base URL (default: {DEFAULT_API_URL})"
    )
    parser.add_argument(
        "--db-path",
        default="./stf_digital_twin.db",
        help="Path to SQLite database file (default: ./stf_digital_twin.db)"
    )
    args = parser.parse_args()
    
    # Set DATABASE_URL environment variable if db-path is provided
    if args.db_path:
        os.environ["DATABASE_URL"] = f"sqlite:///{args.db_path}"
        print(f"Using SQLite database: {args.db_path}")
    
    sys.exit(run_tests(args.api_url))
