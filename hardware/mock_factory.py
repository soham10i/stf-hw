"""
STF Digital Twin - Mock Factory Physics Engine
High-Fidelity Component Simulation with Electrical Characteristics and Wear Model
"""

import asyncio
import json
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, Callable

import httpx
import paho.mqtt.client as mqtt

from utils.logging_config import get_logger

logger = get_logger("hardware")

# Configuration (environment-variable driven)
API_URL = os.environ.get("STF_API_URL", "http://localhost:8000")
MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
TICK_RATE = 10  # Hz (100ms per tick)
TICK_INTERVAL = 1.0 / TICK_RATE


class MotorPhase(Enum):
    """Motor operational phases with different current draws"""
    IDLE = "IDLE"
    STARTUP = "STARTUP"  # Inrush current spike
    RUNNING = "RUNNING"  # Steady state
    STOPPING = "STOPPING"


@dataclass
class ElectricalModel:
    """Electrical characteristics for motors"""
    idle_amps: float = 0.05
    startup_amps: float = 2.5  # Inrush spike
    running_amps: float = 1.2  # Steady state
    startup_duration_ms: int = 500
    voltage: float = 24.0
    
    # Anomaly thresholds
    bearing_failure_amps: float = 3.5  # High current when bearings fail
    health_anomaly_threshold: float = 0.8  # Health score below this triggers anomalies


@dataclass
class MotorSimulation:
    """Simulates a single motor with physics"""
    component_id: str
    electrical: ElectricalModel = field(default_factory=ElectricalModel)
    
    # State
    phase: MotorPhase = MotorPhase.IDLE
    current_amps: float = 0.05
    health_score: float = 1.0
    accumulated_runtime_sec: float = 0.0
    
    # Internal
    startup_start_time: float = 0.0
    is_active: bool = False
    velocity: float = 0.0  # mm/s
    max_velocity: float = 100.0  # mm/s
    
    def activate(self):
        """Start the motor"""
        if self.phase == MotorPhase.IDLE:
            self.phase = MotorPhase.STARTUP
            self.startup_start_time = time.time()
            self.is_active = True
    
    def deactivate(self):
        """Stop the motor"""
        self.phase = MotorPhase.STOPPING
        self.is_active = False
    
    def tick(self, dt: float) -> Dict:
        """Update motor state for one tick"""
        # Phase transitions
        if self.phase == MotorPhase.STARTUP:
            elapsed_ms = (time.time() - self.startup_start_time) * 1000
            if elapsed_ms >= self.electrical.startup_duration_ms:
                self.phase = MotorPhase.RUNNING
        
        elif self.phase == MotorPhase.STOPPING:
            self.velocity = max(0, self.velocity - self.max_velocity * dt * 2)
            if self.velocity <= 0:
                self.phase = MotorPhase.IDLE
        
        # Calculate current draw based on phase
        if self.phase == MotorPhase.IDLE:
            self.current_amps = self.electrical.idle_amps
            self.velocity = 0
        
        elif self.phase == MotorPhase.STARTUP:
            self.current_amps = self.electrical.startup_amps
            self.velocity = min(self.max_velocity, self.velocity + self.max_velocity * dt * 4)
        
        elif self.phase == MotorPhase.RUNNING:
            self.current_amps = self.electrical.running_amps
            self.velocity = self.max_velocity
            
            # Health degradation during operation
            self.accumulated_runtime_sec += dt
            self.health_score = max(0.0, self.health_score - 0.0001 * dt)
            
            # Anomaly injection for degraded motors
            if self.health_score < self.electrical.health_anomaly_threshold:
                if random.random() < 0.05:  # 5% chance per tick
                    self.current_amps = self.electrical.bearing_failure_amps
            
            # Micro-stoppages for severely degraded motors
            if self.health_score < 0.5:
                if random.random() < 0.02:  # 2% chance per tick
                    self.velocity = 0
        
        # Calculate power
        power_watts = self.current_amps * self.electrical.voltage
        energy_joules = power_watts * dt
        
        return {
            "component_id": self.component_id,
            "current_amps": round(self.current_amps, 3),
            "voltage": self.electrical.voltage,
            "health_score": round(self.health_score, 4),
            "accumulated_runtime_sec": round(self.accumulated_runtime_sec, 1),
            "is_active": self.is_active,
            "velocity": round(self.velocity, 2),
            "power_watts": round(power_watts, 2),
            "energy_joules": round(energy_joules, 4),
            "phase": self.phase.value,
        }


@dataclass
class LightBarrierSimulation:
    """
    Simulates a Light Barrier (Lichtschranke) sensor.
    Through-beam optical sensor for presence detection at entry/exit points.
    Inputs: I_2 (inner), I_3 (outer)
    """
    component_id: str
    trigger_start_mm: float
    trigger_end_mm: float
    
    is_triggered: bool = False
    trigger_count: int = 0
    beam_strength: float = 1.0  # Signal strength 0.0-1.0
    last_trigger_time: float = 0.0
    
    def update(self, position_mm: float, has_object: bool = True) -> Dict:
        """Check if light barrier beam is broken by object"""
        was_triggered = self.is_triggered
        in_zone = self.trigger_start_mm <= position_mm <= self.trigger_end_mm
        self.is_triggered = in_zone and has_object
        
        # Simulate beam strength degradation when blocked
        if self.is_triggered:
            self.beam_strength = 0.1 + random.random() * 0.1  # Low when blocked
            self.last_trigger_time = time.time()
        else:
            self.beam_strength = 0.95 + random.random() * 0.05  # High when clear
        
        # Count rising edges (object entering beam)
        if self.is_triggered and not was_triggered:
            self.trigger_count += 1
        
        return {
            "component_id": self.component_id,
            "sensor_type": "LIGHT_BARRIER",
            "is_triggered": self.is_triggered,
            "trigger_count": self.trigger_count,
            "beam_strength": round(self.beam_strength, 3),
        }


@dataclass
class TrailSensorSimulation:
    """
    Simulates a Trail Sensor (Spursensor) for track/line following.
    Reflective optical sensor that detects conveyor track markings.
    Inputs: I_5 (bottom), I_6 (top)
    """
    component_id: str
    track_center_mm: float  # Center position of track
    track_width_mm: float = 50.0  # Width of detectable track
    
    is_triggered: bool = False  # True when track is detected
    trigger_count: int = 0
    reflectance_value: float = 0.0  # 0.0-1.0 analog value
    track_position: str = "LOST"  # CENTER, LEFT, RIGHT, LOST
    
    def update(self, object_position_mm: float, belt_position_mm: float) -> Dict:
        """
        Trail sensor reads reflectance to determine track position.
        Higher reflectance = on track, lower = off track
        """
        was_triggered = self.is_triggered
        
        # Calculate distance from track center (belt movement affects this)
        offset_from_center = (belt_position_mm % 100) - 50  # Simulate periodic track marks
        distance_from_track = abs(offset_from_center)
        
        # Determine if on track
        on_track = distance_from_track <= self.track_width_mm / 2
        self.is_triggered = on_track
        
        # Calculate reflectance (higher when centered on track)
        if on_track:
            # Reflectance decreases as we move away from center
            self.reflectance_value = 1.0 - (distance_from_track / (self.track_width_mm / 2)) * 0.5
            self.reflectance_value += random.uniform(-0.02, 0.02)  # Add noise
            self.reflectance_value = max(0.5, min(1.0, self.reflectance_value))
            
            # Determine position relative to track center
            if abs(offset_from_center) < 5:
                self.track_position = "CENTER"
            elif offset_from_center < 0:
                self.track_position = "LEFT"
            else:
                self.track_position = "RIGHT"
        else:
            self.reflectance_value = random.uniform(0.05, 0.15)  # Low reflectance off track
            self.track_position = "LOST"
        
        # Count transitions onto track
        if self.is_triggered and not was_triggered:
            self.trigger_count += 1
        
        return {
            "component_id": self.component_id,
            "sensor_type": "TRAIL_SENSOR",
            "is_triggered": self.is_triggered,
            "trigger_count": self.trigger_count,
            "reflectance_value": round(self.reflectance_value, 3),
            "track_position": self.track_position,
        }


# Keep legacy alias for backward compatibility
@dataclass
class SensorSimulation:
    """Legacy sensor simulation - wraps LightBarrierSimulation"""
    component_id: str
    trigger_start_mm: float
    trigger_end_mm: float
    
    is_triggered: bool = False
    trigger_count: int = 0
    
    def update(self, position_mm: float) -> bool:
        """Check if sensor is triggered by position"""
        was_triggered = self.is_triggered
        self.is_triggered = self.trigger_start_mm <= position_mm <= self.trigger_end_mm
        
        # Count rising edges
        if self.is_triggered and not was_triggered:
            self.trigger_count += 1
        
        return self.is_triggered


class ConveyorSimulation:
    """
    Simulates the Conveyor Belt - the bridge between VGR and HBW.
    
    Physical Description:
    - A motorized belt that transports items between the two robots
    - VGR operates at the INPUT end (places items)
    - HBW operates at the OUTPUT end (picks up items)
    - The robots NEVER interact directly - only through this conveyor
    
    Sensor Systems:
    - Light Barriers (Lichtschranke): I_2 inner, I_3 outer - presence detection
    - Trail Sensors (Spursensor): I_5 bottom, I_6 top - track position
    
    The Handshake Flow:
    ┌─────────┐                        ┌─────────┐
    │   VGR   │  ──places item──>  ──> │   HBW   │
    │ (Input) │     0mm      BELT      │(Output) │
    │  Side   │              120mm     │  Side   │
    └─────────┘                        └─────────┘
    
    Global Factory Coordinates:
    - Origin (0,0) is at LEFT of storage rack
    - Storage slots: X=100-300mm, Y=100-300mm  
    - Conveyor is at global position ~(400, 100, 25)
    - VGR drops items at one end, HBW picks from other end
    
    Direction: 
    - Forward (1): VGR side → HBW side (normal operation)
    - Reverse (-1): HBW side → VGR side (for retrieval)
    
    Sensor-Based Positioning (no encoder):
    - The conveyor does NOT use encoder positioning
    - Position is determined by Light Barriers (I2, I3) and Trail Sensors (I5, I6)
    - I2 (Inner/HBW side): Triggers when object is at HBW interface (~105mm)
    - I3 (Outer/VGR side): Triggers when object is at VGR interface (~15mm)
    - I5/I6 (Trail): Toggle every 5mm of belt movement to prove motion
    
    Belt Length: ~120mm (realistic Fischertechnik conveyor ~12cm)
    """
    
    # Conveyor endpoints (mm)
    VGR_INPUT_POSITION = 0.0      # Where VGR drops items (local belt coordinate)
    HBW_OUTPUT_POSITION = 120.0   # Where HBW picks up items (local belt coordinate)
    BELT_LENGTH_MM = 120.0        # Total belt length (~12cm Fischertechnik conveyor)
    
    # ============================================
    # SENSOR-BASED POSITION CONSTANTS
    # Local belt coordinates (0 = VGR end, 120 = HBW end)
    # Maps to global factory position ~(400, 100, 25)
    # ============================================
    POS_HBW_INTERFACE = 105.0     # HBW pickup position (I2 triggers here)
    POS_VGR_INTERFACE = 15.0      # VGR dropoff position (I3 triggers here)
    SENSOR_TOLERANCE_MM = 10.0    # ±10mm trigger zone for light barriers
    TRAIL_RIB_SPACING_MM = 5.0    # Trail sensors toggle every 5mm
    
    def __init__(self):
        self.belt_position_mm: float = 0.0
        self.object_position_mm: float = 0.0  # Cookie/carrier position on belt
        self.belt_length_mm: float = self.BELT_LENGTH_MM  # 120mm
        self.direction: int = 1  # 1 = forward (VGR→HBW), -1 = reverse (HBW→VGR)
        self.has_object: bool = False  # Whether an item is on the belt
        
        # Motor
        self.motor = MotorSimulation(
            component_id="CONV_M1",
            electrical=ElectricalModel(
                idle_amps=0.05,
                startup_amps=2.5,
                running_amps=1.2,
                startup_duration_ms=500,
            )
        )
        
        # ============================================
        # LIGHT BARRIERS (Lichtschranke) - I_2, I_3
        # Through-beam sensors at HBW and VGR interface points
        # Trigger zone: ±10mm of interface position
        # ============================================
        self.light_barriers = {
            # I2 (Inner/HBW side): Triggers at POS_HBW_INTERFACE ±10mm (95-115mm)
            "I2": LightBarrierSimulation(
                "CONV_LB_I2", 
                self.POS_HBW_INTERFACE - self.SENSOR_TOLERANCE_MM,  # 95mm
                self.POS_HBW_INTERFACE + self.SENSOR_TOLERANCE_MM   # 115mm
            ),
            # I3 (Outer/VGR side): Triggers at POS_VGR_INTERFACE ±10mm (5-25mm)
            "I3": LightBarrierSimulation(
                "CONV_LB_I3", 
                self.POS_VGR_INTERFACE - self.SENSOR_TOLERANCE_MM,  # 5mm
                self.POS_VGR_INTERFACE + self.SENSOR_TOLERANCE_MM   # 25mm
            ),
        }
        
        # ============================================
        # TRAIL SENSORS (Spursensor) - I_5, I_6
        # Simulates "rib detection" - toggles every 5mm of movement
        # I5 and I6 alternate states to prove physical movement
        # ============================================
        self.trail_sensors = {
            "I5": TrailSensorSimulation("CONV_TS_I5", track_center_mm=60, track_width_mm=20),  # Bottom sensor
            "I6": TrailSensorSimulation("CONV_TS_I6", track_center_mm=60, track_width_mm=20),  # Top sensor
        }
        
        # Trail sensor state for rib detection simulation
        self._last_rib_position_mm = 0.0  # Track when we last toggled
        self._trail_toggle_state = False   # Current toggle state (I5=state, I6=!state)
        
        # Legacy light barrier zones (for backward compatibility with dashboard L1-L4)
        # Scaled to 120mm belt length
        self.sensors = {
            "L1": SensorSimulation("CONV_L1_ENTRY", 0, 15),       # Entry: 0-15mm
            "L2": SensorSimulation("CONV_L2_PROCESS", 40, 50),   # Process: 40-50mm
            "L3": SensorSimulation("CONV_L3_EXIT", 70, 80),      # Exit: 70-80mm
            "L4": SensorSimulation("CONV_L4_OVERFLOW", 105, 120), # Overflow: 105-120mm
        }
    
    def place_object(self, position_mm: float = 0.0):
        """Place an object (cookie) on the conveyor"""
        self.has_object = True
        self.object_position_mm = position_mm
    
    def remove_object(self):
        """Remove object from conveyor"""
        self.has_object = False
        self.object_position_mm = 0.0
    
    def start(self, direction: int = 1):
        """Start conveyor in specified direction"""
        self.direction = direction
        self.motor.activate()
    
    def stop(self):
        """Stop conveyor"""
        self.motor.deactivate()
    
    # =========================================================================
    # SENSOR-BASED POSITION METHODS
    # =========================================================================
    
    def is_at_hbw_interface(self) -> bool:
        """
        Check if object is at HBW interface position (ready for pickup).
        
        Returns
        -------
        bool
            True if object is within ±25mm of POS_HBW_INTERFACE (400mm).
        """
        if not self.has_object:
            return False
        return abs(self.object_position_mm - self.POS_HBW_INTERFACE) <= self.SENSOR_TOLERANCE_MM
    
    def is_at_vgr_interface(self) -> bool:
        """
        Check if object is at VGR interface position (ready for dropoff).
        
        Returns
        -------
        bool
            True if object is within ±25mm of POS_VGR_INTERFACE (950mm).
        """
        if not self.has_object:
            return False
        return abs(self.object_position_mm - self.POS_VGR_INTERFACE) <= self.SENSOR_TOLERANCE_MM
    
    def get_sensor_states(self) -> Dict[str, bool]:
        """
        Get current state of all position-relevant sensors.
        
        Returns
        -------
        Dict[str, bool]
            Dictionary with sensor IDs and their triggered states:
            - I2: True when object at HBW interface
            - I3: True when object at VGR interface
            - I5/I6: Trail sensor states (alternating for motion proof)
        """
        return {
            "I2": self.is_at_hbw_interface(),
            "I3": self.is_at_vgr_interface(),
            "I5": self._trail_toggle_state,
            "I6": not self._trail_toggle_state,
        }

    def tick(self, dt: float) -> Dict:
        """
        Update conveyor state for one tick with sensor-based positioning.
        
        Sensor Logic:
        - I2 (Inner/HBW): True when object is at POS_HBW_INTERFACE ±25mm (375-425mm)
        - I3 (Outer/VGR): True when object is at POS_VGR_INTERFACE ±25mm (925-975mm)
        - I5/I6 (Trail): Toggle every 10mm of belt movement (rib detection)
        
        Returns
        -------
        Dict
            Complete conveyor state including all sensor readings.
        """
        # Update motor
        motor_state = self.motor.tick(dt)
        
        # Track movement for trail sensors
        movement = 0.0
        
        # Update belt position based on motor velocity
        if self.motor.velocity > 0:
            movement = self.motor.velocity * dt * self.direction
            self.belt_position_mm += movement
            
            # Move object with belt
            if self.has_object:
                self.object_position_mm += movement
            
            # Wrap around belt position
            if self.belt_position_mm > self.belt_length_mm:
                self.belt_position_mm = 0
            elif self.belt_position_mm < 0:
                self.belt_position_mm = self.belt_length_mm
                
            # Check if object exited belt
            if self.has_object and (self.object_position_mm > self.belt_length_mm or self.object_position_mm < 0):
                self.has_object = False
        
        # ============================================
        # SENSOR-BASED POSITIONING LOGIC
        # ============================================
        
        # --- Light Barriers (I2, I3) ---
        # I2 triggers when object is within ±25mm of HBW interface (400mm)
        # I3 triggers when object is within ±25mm of VGR interface (950mm)
        light_barrier_states = {}
        for key, lb in self.light_barriers.items():
            light_barrier_states[key] = lb.update(self.object_position_mm, self.has_object)
        
        # --- Trail Sensors (I5, I6) - Rib Detection ---
        # Toggle every TRAIL_RIB_SPACING_MM (10mm) of belt movement
        # I5 and I6 alternate states to prove physical movement
        if abs(self.belt_position_mm - self._last_rib_position_mm) >= self.TRAIL_RIB_SPACING_MM:
            self._trail_toggle_state = not self._trail_toggle_state
            self._last_rib_position_mm = self.belt_position_mm
        
        # Override trail sensor states with rib detection simulation
        trail_sensor_states = {
            "I5": {
                "component_id": self.trail_sensors["I5"].component_id,
                "sensor_type": "TRAIL_SENSOR",
                "is_triggered": self._trail_toggle_state,
                "trigger_count": int(self.belt_position_mm / self.TRAIL_RIB_SPACING_MM),
                "reflectance_value": 0.9 if self._trail_toggle_state else 0.1,
                "track_position": "CENTER" if self._trail_toggle_state else "LOST",
            },
            "I6": {
                "component_id": self.trail_sensors["I6"].component_id,
                "sensor_type": "TRAIL_SENSOR",
                "is_triggered": not self._trail_toggle_state,  # Alternates with I5
                "trigger_count": int(self.belt_position_mm / self.TRAIL_RIB_SPACING_MM),
                "reflectance_value": 0.1 if self._trail_toggle_state else 0.9,
                "track_position": "LOST" if self._trail_toggle_state else "CENTER",
            },
        }
        
        # Update legacy sensors (L1-L4) for backward compatibility
        legacy_sensor_states = {}
        for key, sensor in self.sensors.items():
            legacy_sensor_states[key] = sensor.update(self.object_position_mm if self.has_object else self.belt_position_mm)
        
        return {
            "belt_position_mm": round(self.belt_position_mm, 1),
            "object_position_mm": round(self.object_position_mm, 1) if self.has_object else None,
            "has_object": self.has_object,
            "belt_position_pct": round(self.belt_position_mm / 10, 1),
            "direction": self.direction,
            "motor": motor_state,
            # New sensor systems with sensor-based positioning
            "light_barriers": light_barrier_states,  # Lichtschranke (I_2, I_3)
            "trail_sensors": trail_sensor_states,    # Spursensor (I_5, I_6) with rib detection
            # Legacy for backward compatibility
            "sensors": legacy_sensor_states,
            # Convenience flags for controller logic
            "at_hbw_interface": light_barrier_states["I2"]["is_triggered"],
            "at_vgr_interface": light_barrier_states["I3"]["is_triggered"],
        }


class HBWSimulation:
    """
    Simulates the High-Bay Warehouse (HBW) - Automated Stacker Crane.
    
    Physical Description:
    - Located INSIDE the warehouse rack structure
    - Uses a MECHANICAL FORK (Cantilever) to lift carriers from below
    - The fork slides under the carrier, then lifts it
    
    Coordinate System (separate from VGR):
    - X-axis: Horizontal movement LEFT/RIGHT along the rail (selects column)
    - Y-axis: Vertical movement UP/DOWN along the tower (selects shelf height)
    - Z-axis: HORIZONTAL telescoping IN/OUT to reach into rack slots
             (NOT vertical - this extends the fork into the storage bay)
    
    Storage Rack Layout (9 slots in 3x3 grid):
        Column:   1       2       3
        Row A:   A1      A2      A3    (Top shelf)
        Row B:   B1      B2      B3    (Middle shelf)
        Row C:   C1      C2      C3    (Bottom shelf)
    
    Conveyor Interface:
    - Picks up carriers from the OUTPUT side of the conveyor belt
    - Places carriers into storage slots A1-C3
    """
    
    # Storage slot coordinates (mm) - maps slot names to (x, y) positions
    # Z is always 0 (retracted) when not actively picking/placing
    SLOT_COORDINATES = {
        "A1": (0, 200),    "A2": (100, 200),   "A3": (200, 200),   # Top row
        "B1": (0, 100),    "B2": (100, 100),   "B3": (200, 100),   # Middle row
        "C1": (0, 0),      "C2": (100, 0),     "C3": (200, 0),     # Bottom row
    }
    
    # Conveyor pickup position (where HBW meets the conveyor output)
    CONVEYOR_PICKUP = (100, 0, 0)  # x, y, z - at conveyor level
    
    # Fork extension distance into rack slot
    FORK_EXTENSION_MM = 80.0
    
    def __init__(self):
        # Position state (HBW's own coordinate system)
        self.x: float = 0.0   # Left/Right along rail
        self.y: float = 0.0   # Up/Down on tower
        self.z: float = 0.0   # Fork extension In/Out (horizontal)
        
        self.target_x: Optional[float] = None
        self.target_y: Optional[float] = None
        self.target_z: Optional[float] = None
        
        # Motors (3 axes for stacker crane)
        self.motors = {
            "X": MotorSimulation("HBW_X", ElectricalModel(running_amps=1.5)),  # Horizontal travel
            "Y": MotorSimulation("HBW_Y", ElectricalModel(running_amps=1.5)),  # Vertical lift
            "Z": MotorSimulation("HBW_Z", ElectricalModel(running_amps=1.0)),  # Fork telescope
        }
        
        # Reference switch (home position sensor)
        self.ref_switch_triggered = False
        
        # Fork/Cantilever state (mechanical gripper)
        # True = fork extended and engaged under carrier
        # False = fork retracted
        self.gripper_closed = False
        self.has_carrier = False  # Whether a carrier is on the fork
    
    def move_to_slot(self, slot: str):
        """Move HBW to a storage slot position (A1-C3)"""
        if slot in self.SLOT_COORDINATES:
            x, y = self.SLOT_COORDINATES[slot]
            self.move_to(x, y, 0)  # Z=0 initially, extend fork separately
            return True
        return False
    
    def move_to_conveyor(self):
        """Move HBW to the conveyor pickup position"""
        x, y, z = self.CONVEYOR_PICKUP
        self.move_to(x, y, z)
    
    def extend_fork(self):
        """Extend the fork into the rack slot (Z-axis movement)"""
        self.target_z = self.FORK_EXTENSION_MM
        self.motors["Z"].activate()
        self.gripper_closed = True
    
    def retract_fork(self):
        """Retract the fork back (Z-axis to 0)"""
        self.target_z = 0
        self.motors["Z"].activate()
        self.gripper_closed = False
    
    def move_to(self, x: float, y: float, z: float):
        """Set target position"""
        self.target_x = x
        self.target_y = y
        self.target_z = z
        
        # Activate motors for axes that need to move
        if abs(x - self.x) > 1:
            self.motors["X"].activate()
        if abs(y - self.y) > 1:
            self.motors["Y"].activate()
        if abs(z - self.z) > 1:
            self.motors["Z"].activate()
    
    def stop(self):
        """Stop all motors"""
        for motor in self.motors.values():
            motor.deactivate()
        self.target_x = None
        self.target_y = None
        self.target_z = None
    
    def tick(self, dt: float) -> Dict:
        """Update HBW state for one tick"""
        motor_states = {}
        total_power = 0.0
        total_energy = 0.0
        
        # Update each motor and move towards target
        for axis, motor in self.motors.items():
            state = motor.tick(dt)
            motor_states[axis] = state
            total_power += state["power_watts"]
            total_energy += state["energy_joules"]
            
            # Move towards target
            if motor.velocity > 0:
                if axis == "X" and self.target_x is not None:
                    diff = self.target_x - self.x
                    if abs(diff) > 1:
                        self.x += (1 if diff > 0 else -1) * motor.velocity * dt
                    else:
                        self.x = self.target_x
                        motor.deactivate()
                
                elif axis == "Y" and self.target_y is not None:
                    diff = self.target_y - self.y
                    if abs(diff) > 1:
                        self.y += (1 if diff > 0 else -1) * motor.velocity * dt
                    else:
                        self.y = self.target_y
                        motor.deactivate()
                
                elif axis == "Z" and self.target_z is not None:
                    diff = self.target_z - self.z
                    if abs(diff) > 1:
                        self.z += (1 if diff > 0 else -1) * motor.velocity * dt
                    else:
                        self.z = self.target_z
                        motor.deactivate()
        
        # Check reference switch (at origin)
        self.ref_switch_triggered = (self.x < 5 and self.y < 5 and self.z < 5)
        
        # Determine overall status
        is_moving = any(m.phase != MotorPhase.IDLE for m in self.motors.values())
        status = "MOVING" if is_moving else "IDLE"
        
        return {
            "device_id": "HBW",
            "x": round(self.x, 1),              # Position on rail (Left/Right)
            "y": round(self.y, 1),              # Position on tower (Up/Down)
            "z": round(self.z, 1),              # Fork extension (In/Out - horizontal!)
            "status": status,
            "motors": motor_states,
            "ref_switch": self.ref_switch_triggered,
            "gripper_closed": self.gripper_closed,  # Fork extended/engaged
            "has_carrier": self.has_carrier,        # Carrying a carrier
            "fork_extended": self.z > 10,           # True when fork is extended
            "total_power_watts": round(total_power, 2),
            "total_energy_joules": round(total_energy, 4),
        }


class VGRSimulation:
    """
    Simulates the Vacuum Gripper Robot (VGR) - 3-Axis Gantry Robot.
    
    Physical Description:
    - Located OUTSIDE on the factory floor (production area)
    - Uses a PNEUMATIC SUCTION CUP to grip items from above
    - Powered by a compressor that creates vacuum pressure
    
    Coordinate System (separate from HBW):
    - X-axis: Horizontal movement LEFT/RIGHT across the gantry
    - Y-axis: Horizontal movement FRONT/BACK (toward/away from conveyor)
    - Z-axis: VERTICAL movement UP/DOWN to reach down to table/items
             (opposite of HBW - this moves the suction cup down to grab)
    
    Work Stations (VGR work area):
    - Delivery Zone: Where raw materials arrive
    - Oven/Processing: Where items are processed
    - Conveyor Input: Where VGR places items for HBW to pick up
    
    Conveyor Interface:
    - Places items onto the INPUT side of the conveyor belt
    - Items then travel to HBW on the output side
    
    The "Handshake" Flow:
    1. VGR picks up raw item (e.g., cookie dough) from delivery zone
    2. VGR places it on conveyor INPUT side
    3. Conveyor moves item from VGR side → HBW side
    4. HBW picks it up from conveyor OUTPUT side and stores in rack
    """
    
    # VGR work positions (mm) - in VGR's own coordinate system
    DELIVERY_ZONE = (0, 0, 0)        # Where raw items arrive
    OVEN_POSITION = (150, 50, 0)     # Processing station
    CONVEYOR_INPUT = (200, 100, 0)   # Where VGR drops items onto belt
    
    # Suction cup lowered height for pickup
    PICKUP_HEIGHT_MM = 50.0
    
    def __init__(self):
        # Position state (VGR's own coordinate system)
        self.x: float = 0.0   # Left/Right on gantry
        self.y: float = 0.0   # Front/Back toward conveyor
        self.z: float = 0.0   # Up/Down (vertical - suction cup height)
        
        self.target_x: Optional[float] = None
        self.target_y: Optional[float] = None
        self.target_z: Optional[float] = None
        
        # Motors (3 axes for gantry movement)
        self.motors = {
            "X": MotorSimulation("VGR_X", ElectricalModel(running_amps=1.2)),  # Gantry X
            "Y": MotorSimulation("VGR_Y", ElectricalModel(running_amps=1.2)),  # Gantry Y
            "Z": MotorSimulation("VGR_Z", ElectricalModel(running_amps=0.8)),  # Vertical lift
        }
        
        # Pneumatic system (for vacuum suction)
        self.compressor = MotorSimulation("VGR_COMP", ElectricalModel(
            idle_amps=0.1,
            startup_amps=4.0,
            running_amps=2.5,
        ))
        self.valve_open = False      # Pneumatic valve state
        self.vacuum_active = False   # Whether suction is engaged
        self.has_item = False        # Whether an item is held by suction
    
    def move_to_delivery(self):
        """Move VGR to the delivery zone to pick up raw items"""
        x, y, z = self.DELIVERY_ZONE
        self.move_to(x, y, z)
    
    def move_to_oven(self):
        """Move VGR to the oven/processing station"""
        x, y, z = self.OVEN_POSITION
        self.move_to(x, y, z)
    
    def move_to_conveyor(self):
        """Move VGR to the conveyor input to drop off items"""
        x, y, z = self.CONVEYOR_INPUT
        self.move_to(x, y, z)
    
    def lower_to_pickup(self):
        """Lower the suction cup to pickup height (Z-axis down)"""
        self.target_z = self.PICKUP_HEIGHT_MM
        self.motors["Z"].activate()
    
    def raise_suction_cup(self):
        """Raise the suction cup back up (Z-axis to 0)"""
        self.target_z = 0
        self.motors["Z"].activate()
    
    def move_to(self, x: float, y: float, z: float):
        """Set target position"""
        self.target_x = x
        self.target_y = y
        self.target_z = z
        
        if abs(x - self.x) > 1:
            self.motors["X"].activate()
        if abs(y - self.y) > 1:
            self.motors["Y"].activate()
        if abs(z - self.z) > 1:
            self.motors["Z"].activate()
    
    def activate_vacuum(self):
        """Activate vacuum gripper - engages suction to pick up item"""
        self.compressor.activate()
        self.valve_open = True
        self.vacuum_active = True
    
    def release_vacuum(self):
        """Release vacuum gripper - drops item"""
        self.compressor.deactivate()
        self.valve_open = False
        self.vacuum_active = False
        self.has_item = False  # Item is released
    
    def stop(self):
        """Stop all motors"""
        for motor in self.motors.values():
            motor.deactivate()
        self.target_x = None
        self.target_y = None
        self.target_z = None
    
    def tick(self, dt: float) -> Dict:
        """Update VGR state for one tick"""
        motor_states = {}
        total_power = 0.0
        total_energy = 0.0
        
        # Update motors
        for axis, motor in self.motors.items():
            state = motor.tick(dt)
            motor_states[axis] = state
            total_power += state["power_watts"]
            total_energy += state["energy_joules"]
            
            # Move towards target
            if motor.velocity > 0:
                if axis == "X" and self.target_x is not None:
                    diff = self.target_x - self.x
                    if abs(diff) > 1:
                        self.x += (1 if diff > 0 else -1) * motor.velocity * dt
                    else:
                        self.x = self.target_x
                        motor.deactivate()
                
                elif axis == "Y" and self.target_y is not None:
                    diff = self.target_y - self.y
                    if abs(diff) > 1:
                        self.y += (1 if diff > 0 else -1) * motor.velocity * dt
                    else:
                        self.y = self.target_y
                        motor.deactivate()
                
                elif axis == "Z" and self.target_z is not None:
                    diff = self.target_z - self.z
                    if abs(diff) > 1:
                        self.z += (1 if diff > 0 else -1) * motor.velocity * dt
                    else:
                        self.z = self.target_z
                        motor.deactivate()
        
        # Update compressor
        comp_state = self.compressor.tick(dt)
        total_power += comp_state["power_watts"]
        total_energy += comp_state["energy_joules"]
        
        # Determine overall status
        is_moving = any(m.phase != MotorPhase.IDLE for m in self.motors.values())
        status = "MOVING" if is_moving else "IDLE"
        
        return {
            "device_id": "VGR",
            "x": round(self.x, 1),              # Position on gantry (Left/Right)
            "y": round(self.y, 1),              # Position toward conveyor (Front/Back)
            "z": round(self.z, 1),              # Suction cup height (Up/Down - vertical!)
            "status": status,
            "motors": motor_states,
            "compressor": comp_state,
            "valve_open": self.valve_open,
            "vacuum_active": self.vacuum_active,
            "has_item": self.has_item,          # Whether suction cup is holding an item
            "suction_lowered": self.z > 10,     # True when suction cup is lowered
            "total_power_watts": round(total_power, 2),
            "total_energy_joules": round(total_energy, 4),
        }


class MockFactory:
    """
    Main Factory Simulation - Coordinates all subsystems.
    
    Physical Layout:
    ┌────────────────────────────────────────────────────────────────┐
    │                        FACTORY FLOOR                           │
    │                                                                │
    │   ┌─────────────┐                      ┌─────────────────────┐ │
    │   │             │                      │   STORAGE RACK      │ │
    │   │     VGR     │    CONVEYOR BELT     │  ┌───┬───┬───┐      │ │
    │   │   (Vacuum   │ ===================> │  │A1 │A2 │A3 │      │ │
    │   │   Gripper)  │   Items flow this    │  ├───┼───┼───┤  HBW │ │
    │   │             │   way normally       │  │B1 │B2 │B3 │(Fork)│ │
    │   │   Suction   │                      │  ├───┼───┼───┤      │ │
    │   │   Cup ↓↑    │   INPUT ──> OUTPUT   │  │C1 │C2 │C3 │      │ │
    │   │             │                      │  └───┴───┴───┘      │ │
    │   └─────────────┘                      └─────────────────────┘ │
    │        ▲                                        ▲              │
    │        │                                        │              │
    │   Z = Vertical                            Z = Horizontal       │
    │   (up/down)                               (in/out of rack)     │
    └────────────────────────────────────────────────────────────────┘
    
    The two robots NEVER touch each other - the Conveyor Belt is the bridge.
    """
    
    def __init__(self, api_url: str = API_URL, mqtt_broker: str = MQTT_BROKER):
        self.api_url = api_url
        self.mqtt_broker = mqtt_broker
        
        # Subsystems (two separate robots + conveyor bridge)
        self.conveyor = ConveyorSimulation()  # The bridge between robots
        self.hbw = HBWSimulation()            # Storage robot (inside rack)
        self.vgr = VGRSimulation()            # Production robot (factory floor)
        
        # HTTP client
        self.http_client: Optional[httpx.AsyncClient] = None
        
        # MQTT client
        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="mock_factory")
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_message = self._on_mqtt_message
        
        # State
        self.running = False
        self.tick_count = 0
        self.last_api_update = 0.0
        self.api_update_interval = 0.5  # Update API every 500ms
    
    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties=None):
        """MQTT connection callback"""
        if reason_code == 0:
            logger.info("[MQTT] Connected to broker")
            # Subscribe to command topics
            client.subscribe("stf/+/cmd/#")
            client.subscribe("stf/global/req/#")
        else:
            logger.error("[MQTT] Connection failed: %s", reason_code)
    
    def _on_mqtt_message(self, client, userdata, msg):
        """Handle incoming MQTT commands"""
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode())
        except:
            payload = msg.payload.decode()
        
        logger.info("[MQTT] Received: %s = %s", topic, payload)
        
        # Parse topic
        parts = topic.split("/")
        if len(parts) < 3:
            return
        
        device = parts[1]
        cmd_type = parts[2] if len(parts) > 2 else None
        action = parts[3] if len(parts) > 3 else None
        
        # Handle commands
        if device == "conveyor" and cmd_type == "cmd":
            if action == "start":
                direction = payload.get("direction", 1) if isinstance(payload, dict) else 1
                self.conveyor.start(direction)
            elif action == "stop":
                self.conveyor.stop()
            elif action == "belt":
                # Handle belt commands from controller
                belt_action = payload.get("action", "") if isinstance(payload, dict) else ""
                if belt_action == "start":
                    direction = payload.get("direction", 1)
                    self.conveyor.start(direction)
                elif belt_action == "stop":
                    self.conveyor.stop()
        
        elif device == "hbw" and cmd_type == "cmd":
            if action == "move":
                x = payload.get("x", self.hbw.x) if isinstance(payload, dict) else self.hbw.x
                y = payload.get("y", self.hbw.y) if isinstance(payload, dict) else self.hbw.y
                z = payload.get("z", self.hbw.z) if isinstance(payload, dict) else self.hbw.z
                self.hbw.move_to(x, y, z)
                logger.info("[HBW] Moving to (%s, %s, %s)", x, y, z)
            elif action == "stop":
                self.hbw.stop()
            elif action == "gripper":
                gripper_action = payload.get("action", "") if isinstance(payload, dict) else ""
                if gripper_action in ["close", "extend"]:
                    self.hbw.gripper_closed = True
                elif gripper_action in ["open", "retract"]:
                    self.hbw.gripper_closed = False
                logger.info("[HBW] Gripper: %s -> closed=%s", gripper_action, self.hbw.gripper_closed)
        
        elif device == "vgr" and cmd_type == "cmd":
            if action == "move":
                x = payload.get("x", self.vgr.x) if isinstance(payload, dict) else self.vgr.x
                y = payload.get("y", self.vgr.y) if isinstance(payload, dict) else self.vgr.y
                z = payload.get("z", self.vgr.z) if isinstance(payload, dict) else self.vgr.z
                self.vgr.move_to(x, y, z)
                logger.info("[VGR] Moving to (%s, %s, %s)", x, y, z)
            elif action == "stop":
                self.vgr.stop()
            elif action == "vacuum":
                if payload.get("activate", False):
                    self.vgr.activate_vacuum()
                else:
                    self.vgr.release_vacuum()
        
        elif device == "global" and cmd_type == "req":
            if action == "reset":
                self._reset_all()
            elif action == "emergency_stop":
                self._emergency_stop()
    
    def _reset_all(self):
        """Reset all subsystems to initial state"""
        self.conveyor = ConveyorSimulation()
        self.hbw = HBWSimulation()
        self.vgr = VGRSimulation()
        logger.info("[Factory] All subsystems reset")
    
    def _emergency_stop(self):
        """Emergency stop all subsystems"""
        self.conveyor.stop()
        self.hbw.stop()
        self.vgr.stop()
        self.vgr.release_vacuum()
        logger.critical("[Factory] EMERGENCY STOP")
    
    async def _update_api(self, conveyor_state: Dict, hbw_state: Dict, vgr_state: Dict):
        """Send state updates to API"""
        if not self.http_client:
            return
        
        try:
            # Update conveyor state
            await self.http_client.post(f"{self.api_url}/conveyor/state", json={
                "belt_position_mm": conveyor_state["belt_position_mm"],
                "motor_amps": conveyor_state["motor"]["current_amps"],
                "motor_active": conveyor_state["motor"]["is_active"],
                "sensors": conveyor_state["sensors"],
            })
            
            # Update motor states
            for motor_state in [conveyor_state["motor"]] + list(hbw_state["motors"].values()) + list(vgr_state["motors"].values()):
                await self.http_client.post(f"{self.api_url}/motors/state", json={
                    "component_id": motor_state["component_id"],
                    "current_amps": motor_state["current_amps"],
                    "voltage": motor_state["voltage"],
                    "is_active": motor_state["is_active"],
                    "health_score": motor_state["health_score"],
                    "accumulated_runtime_sec": motor_state["accumulated_runtime_sec"],
                })
            
            # Update VGR compressor
            await self.http_client.post(f"{self.api_url}/motors/state", json={
                "component_id": vgr_state["compressor"]["component_id"],
                "current_amps": vgr_state["compressor"]["current_amps"],
                "voltage": vgr_state["compressor"]["voltage"],
                "is_active": vgr_state["compressor"]["is_active"],
                "health_score": vgr_state["compressor"]["health_score"],
                "accumulated_runtime_sec": vgr_state["compressor"]["accumulated_runtime_sec"],
            })
            
            # Update hardware positions
            await self.http_client.post(f"{self.api_url}/hardware/state", json={
                "device_id": "HBW",
                "x": hbw_state["x"],
                "y": hbw_state["y"],
                "z": hbw_state["z"],
                "status": hbw_state["status"],
            })
            
            await self.http_client.post(f"{self.api_url}/hardware/state", json={
                "device_id": "VGR",
                "x": vgr_state["x"],
                "y": vgr_state["y"],
                "z": vgr_state["z"],
                "status": vgr_state["status"],
            })
            
            await self.http_client.post(f"{self.api_url}/hardware/state", json={
                "device_id": "CONVEYOR",
                "x": conveyor_state["belt_position_mm"],
                "y": 0,
                "z": 0,
                "status": "MOVING" if conveyor_state["motor"]["is_active"] else "IDLE",
            })
            
            # Record energy
            total_energy = (
                conveyor_state["motor"]["energy_joules"] +
                hbw_state["total_energy_joules"] +
                vgr_state["total_energy_joules"]
            )
            if total_energy > 0:
                await self.http_client.post(f"{self.api_url}/energy", json={
                    "device_id": "FACTORY",
                    "joules": total_energy,
                    "voltage": 24.0,
                })
        
        except Exception as e:
            logger.error("[API] Update error: %s", e)
    
    def _publish_mqtt_status(self, conveyor_state: Dict, hbw_state: Dict, vgr_state: Dict):
        """Publish status to MQTT"""
        try:
            self.mqtt_client.publish("stf/conveyor/status", json.dumps(conveyor_state))
            self.mqtt_client.publish("stf/hbw/status", json.dumps(hbw_state))
            self.mqtt_client.publish("stf/vgr/status", json.dumps(vgr_state))
        except Exception as e:
            logger.error("[MQTT] Publish error: %s", e)
    
    async def run(self):
        """Main simulation loop"""
        logger.info("[Factory] Starting Mock Factory simulation...")
        logger.info("[Factory] Tick rate: %s Hz", TICK_RATE)
        logger.info("[Factory] API URL: %s", self.api_url)
        
        # Connect MQTT
        try:
            self.mqtt_client.connect(self.mqtt_broker, MQTT_PORT, 60)
            self.mqtt_client.loop_start()
        except Exception as e:
            logger.error("[MQTT] Connection error: %s", e)
        
        # Create HTTP client
        self.http_client = httpx.AsyncClient(timeout=5.0)
        
        self.running = True
        last_tick = time.time()
        
        try:
            while self.running:
                current_time = time.time()
                dt = current_time - last_tick
                last_tick = current_time
                
                # Update all subsystems
                conveyor_state = self.conveyor.tick(dt)
                hbw_state = self.hbw.tick(dt)
                vgr_state = self.vgr.tick(dt)
                
                # Publish MQTT status every tick
                self._publish_mqtt_status(conveyor_state, hbw_state, vgr_state)
                
                # Update API at lower rate
                if current_time - self.last_api_update >= self.api_update_interval:
                    await self._update_api(conveyor_state, hbw_state, vgr_state)
                    self.last_api_update = current_time
                
                self.tick_count += 1
                
                # Maintain tick rate
                elapsed = time.time() - current_time
                sleep_time = max(0, TICK_INTERVAL - elapsed)
                await asyncio.sleep(sleep_time)
        
        except KeyboardInterrupt:
            logger.info("\n[Factory] Shutting down...")
        finally:
            self.running = False
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
            if self.http_client:
                await self.http_client.aclose()
            logger.info("[Factory] Shutdown complete")


async def main():
    """Entry point"""
    import os
    
    api_url = os.environ.get("STF_API_URL", API_URL)
    mqtt_broker = os.environ.get("MQTT_BROKER", MQTT_BROKER)
    
    factory = MockFactory(api_url=api_url, mqtt_broker=mqtt_broker)
    await factory.run()


if __name__ == "__main__":
    asyncio.run(main())

