"""
STF Digital Twin - Configuration Module
Coordinate mappings and system constants
"""

import os
from dataclasses import dataclass
from typing import Dict, Tuple

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# API Configuration
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:3000/api/trpc")

# MQTT Configuration
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

# Database Configuration (for direct access if needed)
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Coordinate Mapping for Warehouse Slots (3x3 Grid)
SLOT_COORDINATES: Dict[str, Tuple[int, int]] = {
    "A1": (100, 100),
    "A2": (200, 100),
    "A3": (300, 100),
    "B1": (100, 200),
    "B2": (200, 200),
    "B3": (300, 200),
    "C1": (100, 300),
    "C2": (200, 300),
    "C3": (300, 300),
}

# Reverse mapping: coordinates to slot name
COORDINATES_TO_SLOT: Dict[Tuple[int, int], str] = {
    coords: slot for slot, coords in SLOT_COORDINATES.items()
}

# Hardware Device IDs
class Devices:
    HBW = "HBW"
    CONVEYOR = "CONVEYOR"
    VGR = "VGR"

# Zone Names
class Zones:
    HBW = "HBW"
    CONVEYOR = "CONVEYOR"
    VGR = "VGR"
    OVEN = "OVEN"

# MQTT Topics
class MQTTTopics:
    # Command topics (subscribed by mock hardware)
    HBW_CMD_MOVE_X = "stf/hbw/cmd/move_x"
    HBW_CMD_MOVE_Y = "stf/hbw/cmd/move_y"
    HBW_CMD_MOVE = "stf/hbw/cmd/move"  # Combined X,Y move
    HBW_CMD_GRIPPER = "stf/hbw/cmd/gripper"
    CONVEYOR_CMD = "stf/conveyor/cmd"
    VGR_CMD = "stf/vgr/cmd"
    
    # Status topics (published by mock hardware)
    HBW_STATUS = "stf/hbw/status"
    CONVEYOR_STATUS = "stf/conveyor/status"
    VGR_STATUS = "stf/vgr/status"
    
    # High-level request topics (subscribed by controller)
    GLOBAL_REQ_RETRIEVE = "stf/global/req/retrieve"
    GLOBAL_REQ_STORE = "stf/global/req/store"
    GLOBAL_REQ_RESET = "stf/global/req/reset"

# Simulation Parameters
@dataclass
class SimulationConfig:
    """Physics simulation configuration"""
    TICK_RATE_HZ: float = 10.0  # 10 Hz simulation
    TICK_INTERVAL_S: float = 0.1  # 100ms per tick
    MOVEMENT_SPEED: float = 10.0  # Units per tick
    MAX_POSITION: float = 500.0
    MIN_POSITION: float = 0.0
    POSITION_TOLERANCE: float = 1.0  # Consider arrived if within this distance

# Energy Calculation Constants
@dataclass
class EnergyConfig:
    """Energy consumption parameters"""
    IDLE_POWER_W: float = 5.0  # Watts when idle
    MOVING_POWER_W: float = 50.0  # Watts when moving
    VOLTAGE_V: float = 24.0  # Operating voltage
    EFFICIENCY: float = 0.85  # Motor efficiency

# Alert Thresholds
@dataclass
class AlertThresholds:
    """Thresholds for generating alerts"""
    LOW_INVENTORY_SLOTS: int = 2
    CRITICAL_INVENTORY_SLOTS: int = 1
    HIGH_ENERGY_CONSUMPTION_W: float = 100.0
    HEARTBEAT_TIMEOUT_S: float = 5.0

# Cookie Flavors
FLAVORS = ["CHOCO", "VANILLA", "STRAWBERRY"]

# Cookie Status
class CookieStatus:
    BAKING = "BAKING"
    STORED = "STORED"
    SHIPPED = "SHIPPED"

# Hardware Status
class HardwareStatus:
    IDLE = "IDLE"
    MOVING = "MOVING"
    ERROR = "ERROR"
    MAINTENANCE = "MAINTENANCE"

# Command Status
class CommandStatus:
    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

def get_slot_coordinates(slot_name: str) -> Tuple[int, int]:
    """Get X,Y coordinates for a slot name"""
    if slot_name not in SLOT_COORDINATES:
        raise ValueError(f"Invalid slot name: {slot_name}")
    return SLOT_COORDINATES[slot_name]

def get_slot_name(x: int, y: int) -> str | None:
    """Get slot name from coordinates (with tolerance)"""
    for slot, (sx, sy) in SLOT_COORDINATES.items():
        if abs(x - sx) < 10 and abs(y - sy) < 10:
            return slot
    return None

def calculate_distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Calculate Euclidean distance between two points"""
    return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
