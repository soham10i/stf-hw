"""
STF Digital Twin - SQLAlchemy Database Models
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional, Tuple, Dict

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime,
    ForeignKey, Enum, Text, create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
import os

Base = declarative_base()

# =============================================================================
# HBW 3-AXIS CARTESIAN ROBOT KINEMATIC CONSTANTS
# =============================================================================
# Hardware: Fischertechnik Encoder Motor 24V (144643)
# Encoder Resolution: 75 pulses per revolution (output shaft)
# Spindle Pitch: 4mm per revolution
# =============================================================================

PULSES_PER_REV = 75        # Encoder pulses per motor revolution
SPINDLE_PITCH_MM = 4.0     # Linear travel per revolution (mm)
PULSES_PER_MM = PULSES_PER_REV / SPINDLE_PITCH_MM  # = 18.75 pulses/mm

# Z-Axis Semantics (vertical arm extension)
# 10 = Retracted (Safe travel height)
# 25 = Carry (Belt/conveyor height for transport)
# 50 = Extended (Inside slot for pick/place)
Z_RETRACTED = 10   # Safe travel position
Z_CARRY = 25       # Belt height for transport
Z_EXTENDED = 50    # In-slot position for pick/place

# HBW Special Positions (X, Y, Z) in mm
REST_POS: Tuple[float, float, float] = (400.0, 90.0, 10.0)       # Home/rest position
CONVEYOR_POS: Tuple[float, float, float] = (400.0, 100.0, 25.0)  # Conveyor handoff

# 3D Slot Coordinates: slot_name -> (X, Y, Z) in mm
# X: Horizontal travel (100-300mm for slots, 400mm for conveyor)
# Y: Vertical travel (100-300mm for rows A-C)
# Z: Arm extension (50mm = inside slot)
SLOT_COORDINATES_3D: Dict[str, Tuple[float, float, float]] = {
    # Row A (Bottom, Y=100)
    "A1": (100.0, 100.0, 50.0),
    "A2": (200.0, 100.0, 50.0),
    "A3": (300.0, 100.0, 50.0),
    # Row B (Middle, Y=200)
    "B1": (100.0, 200.0, 50.0),
    "B2": (200.0, 200.0, 50.0),
    "B3": (300.0, 200.0, 50.0),
    # Row C (Top, Y=300)
    "C1": (100.0, 300.0, 50.0),
    "C2": (200.0, 300.0, 50.0),
    "C3": (300.0, 300.0, 50.0),
}

# Legacy 2D coordinates for backward compatibility
SLOT_COORDINATES_2D: Dict[str, Tuple[float, float]] = {
    name: (x, y) for name, (x, y, z) in SLOT_COORDINATES_3D.items()
}

# Enums
class CookieFlavor(PyEnum):
    CHOCO = "CHOCO"
    VANILLA = "VANILLA"
    STRAWBERRY = "STRAWBERRY"

class CookieStatus(PyEnum):
    RAW_DOUGH = "RAW_DOUGH"
    BAKED = "BAKED"
    PACKAGED = "PACKAGED"
    STORED = "STORED"
    SHIPPED = "SHIPPED"

class SubsystemType(PyEnum):
    CONVEYOR = "CONVEYOR"
    HBW = "HBW"
    VGR = "VGR"

class ComponentType(PyEnum):
    MOTOR = "MOTOR"
    SENSOR = "SENSOR"
    ACTUATOR = "ACTUATOR"
    COMPRESSOR = "COMPRESSOR"
    VALVE = "VALVE"

class SensorType(PyEnum):
    """Sensor types matching real hardware"""
    LIGHT_BARRIER = "LIGHT_BARRIER"  # Lichtschranke - Through-beam optical (I_2, I_3)
    TRAIL_SENSOR = "TRAIL_SENSOR"    # Spursensor - Reflective line-following (I_5, I_6)

class HardwareStatus(PyEnum):
    IDLE = "IDLE"
    MOVING = "MOVING"
    ERROR = "ERROR"
    MAINTENANCE = "MAINTENANCE"

class LogLevel(PyEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class AlertSeverity(PyEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

# Models
class Carrier(Base):
    __tablename__ = "py_carriers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    current_zone = Column(String(50), nullable=False, default="STORAGE")
    is_locked = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    cookies = relationship("Cookie", back_populates="carrier")
    inventory_slot = relationship("InventorySlot", back_populates="carrier", uselist=False)

class Cookie(Base):
    __tablename__ = "py_cookies"
    batch_uuid = Column(String(36), primary_key=True)
    carrier_id = Column(Integer, ForeignKey("py_carriers.id"), nullable=True)
    flavor = Column(Enum(CookieFlavor), nullable=True)
    status = Column(Enum(CookieStatus), nullable=False, default=CookieStatus.RAW_DOUGH)
    expiry_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    carrier = relationship("Carrier", back_populates="cookies")

class InventorySlot(Base):
    __tablename__ = "py_inventory_slots"
    slot_name = Column(String(10), primary_key=True)
    x_pos = Column(Integer, nullable=False)
    y_pos = Column(Integer, nullable=False)
    carrier_id = Column(Integer, ForeignKey("py_carriers.id"), nullable=True, unique=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    carrier = relationship("Carrier", back_populates="inventory_slot")

class ComponentRegistry(Base):
    """Static specification data for all hardware components"""
    __tablename__ = "py_component_registry"
    id = Column(String(50), primary_key=True)  # e.g., HBW_X, CONV_M1
    name = Column(String(100), nullable=False)
    subsystem = Column(Enum(SubsystemType), nullable=False)
    component_type = Column(Enum(ComponentType), nullable=False)
    spec_voltage = Column(Float, nullable=False, default=24.0)
    spec_max_current = Column(Float, nullable=False, default=5.0)
    maintenance_interval_hours = Column(Integer, nullable=False, default=1000)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class MotorState(Base):
    """Enhanced motor state with health tracking"""
    __tablename__ = "py_motor_states"
    component_id = Column(String(50), ForeignKey("py_component_registry.id"), primary_key=True)
    current_amps = Column(Float, nullable=False, default=0.0)
    voltage = Column(Float, nullable=False, default=24.0)
    health_score = Column(Float, nullable=False, default=1.0)  # 0.0-1.0
    accumulated_runtime_sec = Column(Float, nullable=False, default=0.0)
    is_active = Column(Boolean, nullable=False, default=False)
    last_maintenance = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    component = relationship("ComponentRegistry")

class SensorState(Base):
    """Sensor state tracking with support for different sensor types"""
    __tablename__ = "py_sensor_states"
    component_id = Column(String(50), ForeignKey("py_component_registry.id"), primary_key=True)
    sensor_type = Column(Enum(SensorType), nullable=False, default=SensorType.LIGHT_BARRIER)
    is_triggered = Column(Boolean, nullable=False, default=False)
    last_trigger_time = Column(DateTime, nullable=True)
    trigger_count = Column(Integer, nullable=False, default=0)
    
    # Trail sensor specific fields (Spursensor)
    reflectance_value = Column(Float, nullable=True)  # 0.0-1.0 for analog trail sensors
    track_position = Column(String(20), nullable=True)  # "CENTER", "LEFT", "RIGHT", "LOST"
    
    # Light barrier specific fields (Lichtschranke)
    beam_strength = Column(Float, nullable=True)  # Signal strength 0.0-1.0
    
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    component = relationship("ComponentRegistry")

class HardwareState(Base):
    __tablename__ = "py_hardware_states"
    device_id = Column(String(50), primary_key=True)
    current_x = Column(Float, nullable=False, default=0.0)
    current_y = Column(Float, nullable=False, default=0.0)
    current_z = Column(Float, nullable=False, default=0.0)
    target_x = Column(Float, nullable=True)
    target_y = Column(Float, nullable=True)
    target_z = Column(Float, nullable=True)
    status = Column(Enum(HardwareStatus), nullable=False, default=HardwareStatus.IDLE)
    last_error = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

class SystemLog(Base):
    __tablename__ = "py_system_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    level = Column(Enum(LogLevel), nullable=False, default=LogLevel.INFO)
    source = Column(String(100), nullable=True)
    message = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)

class EnergyLog(Base):
    __tablename__ = "py_energy_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String(50), nullable=False, index=True)
    joules = Column(Float, nullable=False, default=0.0)
    voltage = Column(Float, nullable=False, default=24.0)
    current_amps = Column(Float, nullable=True)
    power_watts = Column(Float, nullable=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

class TelemetryHistory(Base):
    __tablename__ = "py_telemetry_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String(50), nullable=False, index=True)
    metric_name = Column(String(100), nullable=False)
    metric_value = Column(Float, nullable=False)
    unit = Column(String(20), nullable=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

class Alert(Base):
    __tablename__ = "py_alerts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_type = Column(String(50), nullable=False)
    severity = Column(Enum(AlertSeverity), nullable=False, default=AlertSeverity.MEDIUM)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    device_id = Column(String(50), nullable=True)
    acknowledged = Column(Boolean, nullable=False, default=False)
    acknowledged_at = Column(DateTime, nullable=True)
    acknowledged_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

class Command(Base):
    __tablename__ = "py_commands"
    id = Column(Integer, primary_key=True, autoincrement=True)
    command_type = Column(String(50), nullable=False)
    target_slot = Column(String(10), nullable=True)
    payload_json = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="PENDING")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    executed_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

# Coordinate mapping
SLOT_COORDINATES = {
    "A1": (100, 100), "A2": (200, 100), "A3": (300, 100),
    "B1": (100, 200), "B2": (200, 200), "B3": (300, 200),
    "C1": (100, 300), "C2": (200, 300), "C3": (300, 300),
}

def get_slot_coordinates(slot_name: str) -> tuple:
    return SLOT_COORDINATES.get(slot_name, (0, 0))

def seed_inventory_slots(session):
    for slot_name, (x, y) in SLOT_COORDINATES.items():
        existing = session.query(InventorySlot).filter_by(slot_name=slot_name).first()
        if not existing:
            slot = InventorySlot(slot_name=slot_name, x_pos=x, y_pos=y)
            session.add(slot)
    session.commit()

def seed_components(session):
    """Seed component registry with all hardware components"""
    import uuid
    
    components = [
        # HBW (Cantilever) - 3 Motors + 1 Ref Switch
        {"id": "HBW_X", "name": "HBW X-Axis Motor", "subsystem": SubsystemType.HBW, "component_type": ComponentType.MOTOR, "spec_voltage": 24.0, "spec_max_current": 3.0, "maintenance_interval_hours": 2000},
        {"id": "HBW_Y", "name": "HBW Y-Axis Motor", "subsystem": SubsystemType.HBW, "component_type": ComponentType.MOTOR, "spec_voltage": 24.0, "spec_max_current": 3.0, "maintenance_interval_hours": 2000},
        {"id": "HBW_Z", "name": "HBW Z-Axis Motor", "subsystem": SubsystemType.HBW, "component_type": ComponentType.MOTOR, "spec_voltage": 24.0, "spec_max_current": 2.5, "maintenance_interval_hours": 2000},
        {"id": "HBW_REF_SW", "name": "HBW Reference Switch", "subsystem": SubsystemType.HBW, "component_type": ComponentType.SENSOR, "spec_voltage": 24.0, "spec_max_current": 0.1, "maintenance_interval_hours": 5000},
        
        # CONVEYOR - 1 Motor + Light Barriers (Lichtschranke) + Trail Sensors (Spursensor)
        {"id": "CONV_M1", "name": "Conveyor Motor (Bidirectional)", "subsystem": SubsystemType.CONVEYOR, "component_type": ComponentType.MOTOR, "spec_voltage": 24.0, "spec_max_current": 4.0, "maintenance_interval_hours": 1500},
        
        # Light Barriers (Lichtschranke) - Through-beam optical for presence detection (I_2, I_3)
        {"id": "CONV_LB_I2", "name": "Lichtschranke Innen (I_2)", "subsystem": SubsystemType.CONVEYOR, "component_type": ComponentType.SENSOR, "spec_voltage": 24.0, "spec_max_current": 0.05, "maintenance_interval_hours": 8000, "sensor_type": "LIGHT_BARRIER"},
        {"id": "CONV_LB_I3", "name": "Lichtschranke Außen (I_3)", "subsystem": SubsystemType.CONVEYOR, "component_type": ComponentType.SENSOR, "spec_voltage": 24.0, "spec_max_current": 0.05, "maintenance_interval_hours": 8000, "sensor_type": "LIGHT_BARRIER"},
        
        # Trail Sensors (Spursensor) - Reflective line-following for track position (I_5, I_6)
        {"id": "CONV_TS_I5", "name": "Spursensor Unten (I_5)", "subsystem": SubsystemType.CONVEYOR, "component_type": ComponentType.SENSOR, "spec_voltage": 24.0, "spec_max_current": 0.03, "maintenance_interval_hours": 10000, "sensor_type": "TRAIL_SENSOR"},
        {"id": "CONV_TS_I6", "name": "Spursensor Oben (I_6)", "subsystem": SubsystemType.CONVEYOR, "component_type": ComponentType.SENSOR, "spec_voltage": 24.0, "spec_max_current": 0.03, "maintenance_interval_hours": 10000, "sensor_type": "TRAIL_SENSOR"},
        
        # Legacy light barrier zones (keeping for backward compatibility with dashboard)
        {"id": "CONV_L1_ENTRY", "name": "Conveyor Entry Zone (L1)", "subsystem": SubsystemType.CONVEYOR, "component_type": ComponentType.SENSOR, "spec_voltage": 24.0, "spec_max_current": 0.05, "maintenance_interval_hours": 8000, "sensor_type": "LIGHT_BARRIER"},
        {"id": "CONV_L2_PROCESS", "name": "Conveyor Process Zone (L2)", "subsystem": SubsystemType.CONVEYOR, "component_type": ComponentType.SENSOR, "spec_voltage": 24.0, "spec_max_current": 0.05, "maintenance_interval_hours": 8000, "sensor_type": "LIGHT_BARRIER"},
        {"id": "CONV_L3_EXIT", "name": "Conveyor Exit Zone (L3)", "subsystem": SubsystemType.CONVEYOR, "component_type": ComponentType.SENSOR, "spec_voltage": 24.0, "spec_max_current": 0.05, "maintenance_interval_hours": 8000, "sensor_type": "LIGHT_BARRIER"},
        {"id": "CONV_L4_OVERFLOW", "name": "Conveyor Overflow Zone (L4)", "subsystem": SubsystemType.CONVEYOR, "component_type": ComponentType.SENSOR, "spec_voltage": 24.0, "spec_max_current": 0.05, "maintenance_interval_hours": 8000, "sensor_type": "LIGHT_BARRIER"},
        
        # VGR (Gripper) - 3 Motors + 1 Compressor + 1 Valve
        {"id": "VGR_X", "name": "VGR X-Axis Motor", "subsystem": SubsystemType.VGR, "component_type": ComponentType.MOTOR, "spec_voltage": 24.0, "spec_max_current": 2.5, "maintenance_interval_hours": 2000},
        {"id": "VGR_Y", "name": "VGR Y-Axis Motor", "subsystem": SubsystemType.VGR, "component_type": ComponentType.MOTOR, "spec_voltage": 24.0, "spec_max_current": 2.5, "maintenance_interval_hours": 2000},
        {"id": "VGR_Z", "name": "VGR Z-Axis Motor", "subsystem": SubsystemType.VGR, "component_type": ComponentType.MOTOR, "spec_voltage": 24.0, "spec_max_current": 2.0, "maintenance_interval_hours": 2000},
        {"id": "VGR_COMP", "name": "VGR Compressor", "subsystem": SubsystemType.VGR, "component_type": ComponentType.COMPRESSOR, "spec_voltage": 24.0, "spec_max_current": 5.0, "maintenance_interval_hours": 1000},
        {"id": "VGR_VALVE", "name": "VGR Pneumatic Valve", "subsystem": SubsystemType.VGR, "component_type": ComponentType.VALVE, "spec_voltage": 24.0, "spec_max_current": 0.5, "maintenance_interval_hours": 3000},
    ]
    
    for comp in components:
        existing = session.query(ComponentRegistry).filter_by(id=comp["id"]).first()
        if not existing:
            # Extract sensor_type before creating component (not a column in ComponentRegistry)
            sensor_type_str = comp.pop("sensor_type", None)
            
            component = ComponentRegistry(**comp)
            session.add(component)
            
            # Create motor state for motors
            if comp["component_type"] in [ComponentType.MOTOR, ComponentType.COMPRESSOR]:
                motor_state = MotorState(component_id=comp["id"])
                session.add(motor_state)
            
            # Create sensor state for sensors with proper sensor_type
            elif comp["component_type"] == ComponentType.SENSOR:
                sensor_type = SensorType.LIGHT_BARRIER  # Default
                if sensor_type_str == "TRAIL_SENSOR":
                    sensor_type = SensorType.TRAIL_SENSOR
                elif sensor_type_str == "LIGHT_BARRIER":
                    sensor_type = SensorType.LIGHT_BARRIER
                    
                sensor_state = SensorState(
                    component_id=comp["id"],
                    sensor_type=sensor_type
                )
                session.add(sensor_state)
    
    session.commit()
    
    # Seed all 9 warehouse slots with RAW_DOUGH cookies
    for slot_name in SLOT_COORDINATES.keys():
        # Create carrier
        carrier = Carrier(current_zone="STORAGE", is_locked=False)
        session.add(carrier)
        session.flush()  # Get carrier ID
        
        # Create cookie with RAW_DOUGH
        cookie = Cookie(
            batch_uuid=str(uuid.uuid4()),
            carrier_id=carrier.id,
            flavor=CookieFlavor.CHOCO,
            status=CookieStatus.RAW_DOUGH
        )
        session.add(cookie)
        
        # Assign carrier to slot
        slot = session.query(InventorySlot).filter_by(slot_name=slot_name).first()
        if slot:
            slot.carrier_id = carrier.id
    
    session.commit()

def seed_hardware_devices(session):
    devices = [
        {"device_id": "HBW", "current_x": 0, "current_y": 0, "current_z": 0},
        {"device_id": "VGR", "current_x": 0, "current_y": 0, "current_z": 0},
        {"device_id": "CONVEYOR", "current_x": 0, "current_y": 0, "current_z": 0},
    ]
    for device in devices:
        existing = session.query(HardwareState).filter_by(device_id=device["device_id"]).first()
        if not existing:
            hw = HardwareState(**device)
            session.add(hw)
    session.commit()
