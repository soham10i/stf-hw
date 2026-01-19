"""
STF Digital Twin - Mock Factory Physics Engine
High-Fidelity Component Simulation with Electrical Characteristics and Wear Model
"""

import asyncio
import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, Callable

import httpx
import paho.mqtt.client as mqtt

# Configuration
API_URL = "http://localhost:8000"
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
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
    Simulates the conveyor belt with motor and dual sensor systems:
    - Light Barriers (Lichtschranke): I_2 inner, I_3 outer - for presence detection
    - Trail Sensors (Spursensor): I_5 bottom, I_6 top - for track position
    """
    
    def __init__(self):
        self.belt_position_mm: float = 0.0
        self.object_position_mm: float = 0.0  # Cookie/object position on belt
        self.belt_length_mm: float = 1000.0
        self.direction: int = 1  # 1 = forward, -1 = reverse
        self.has_object: bool = False  # Whether an object is on the belt
        
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
        # Through-beam sensors at entry/exit points
        # ============================================
        self.light_barriers = {
            "I2": LightBarrierSimulation("CONV_LB_I2", 0, 100),      # Inner: 0-100mm (entry)
            "I3": LightBarrierSimulation("CONV_LB_I3", 900, 1000),   # Outer: 900-1000mm (exit)
        }
        
        # ============================================
        # TRAIL SENSORS (Spursensor) - I_5, I_6
        # Reflective sensors for track following
        # ============================================
        self.trail_sensors = {
            "I5": TrailSensorSimulation("CONV_TS_I5", track_center_mm=500, track_width_mm=50),  # Bottom sensor
            "I6": TrailSensorSimulation("CONV_TS_I6", track_center_mm=500, track_width_mm=50),  # Top sensor
        }
        
        # Legacy light barrier zones (for backward compatibility with dashboard L1-L4)
        self.sensors = {
            "L1": SensorSimulation("CONV_L1_ENTRY", 0, 50),      # Entry: 0-50mm
            "L2": SensorSimulation("CONV_L2_PROCESS", 300, 350), # Process: 300-350mm
            "L3": SensorSimulation("CONV_L3_EXIT", 600, 650),    # Exit: 600-650mm
            "L4": SensorSimulation("CONV_L4_OVERFLOW", 950, 1000), # Overflow: 950-1000mm
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
    
    def tick(self, dt: float) -> Dict:
        """Update conveyor state for one tick"""
        # Update motor
        motor_state = self.motor.tick(dt)
        
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
        # Update Light Barriers (Lichtschranke)
        # ============================================
        light_barrier_states = {}
        for key, lb in self.light_barriers.items():
            light_barrier_states[key] = lb.update(self.object_position_mm, self.has_object)
        
        # ============================================
        # Update Trail Sensors (Spursensor)
        # ============================================
        trail_sensor_states = {}
        for key, ts in self.trail_sensors.items():
            trail_sensor_states[key] = ts.update(self.object_position_mm, self.belt_position_mm)
        
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
            # New sensor systems
            "light_barriers": light_barrier_states,  # Lichtschranke (I_2, I_3)
            "trail_sensors": trail_sensor_states,    # Spursensor (I_5, I_6)
            # Legacy for backward compatibility
            "sensors": legacy_sensor_states,
        }


class HBWSimulation:
    """Simulates the High-Bay Warehouse (Cantilever) robot"""
    
    def __init__(self):
        # Position state
        self.x: float = 0.0
        self.y: float = 0.0
        self.z: float = 0.0
        
        self.target_x: Optional[float] = None
        self.target_y: Optional[float] = None
        self.target_z: Optional[float] = None
        
        # Motors
        self.motors = {
            "X": MotorSimulation("HBW_X", ElectricalModel(running_amps=1.5)),
            "Y": MotorSimulation("HBW_Y", ElectricalModel(running_amps=1.5)),
            "Z": MotorSimulation("HBW_Z", ElectricalModel(running_amps=1.0)),
        }
        
        # Reference switch
        self.ref_switch_triggered = False
        
        # Gripper state
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
            "x": round(self.x, 1),
            "y": round(self.y, 1),
            "z": round(self.z, 1),
            "status": status,
            "motors": motor_states,
            "ref_switch": self.ref_switch_triggered,
            "gripper_closed": self.gripper_closed,
            "total_power_watts": round(total_power, 2),
            "total_energy_joules": round(total_energy, 4),
        }


class VGRSimulation:
    """Simulates the Vacuum Gripper Robot"""
    
    def __init__(self):
        # Position state
        self.x: float = 0.0
        self.y: float = 0.0
        self.z: float = 0.0
        
        self.target_x: Optional[float] = None
        self.target_y: Optional[float] = None
        self.target_z: Optional[float] = None
        
        # Motors
        self.motors = {
            "X": MotorSimulation("VGR_X", ElectricalModel(running_amps=1.2)),
            "Y": MotorSimulation("VGR_Y", ElectricalModel(running_amps=1.2)),
            "Z": MotorSimulation("VGR_Z", ElectricalModel(running_amps=0.8)),
        }
        
        # Pneumatics
        self.compressor = MotorSimulation("VGR_COMP", ElectricalModel(
            idle_amps=0.1,
            startup_amps=4.0,
            running_amps=2.5,
        ))
        self.valve_open = False
        self.vacuum_active = False
    
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
        """Activate vacuum gripper"""
        self.compressor.activate()
        self.valve_open = True
        self.vacuum_active = True
    
    def release_vacuum(self):
        """Release vacuum gripper"""
        self.compressor.deactivate()
        self.valve_open = False
        self.vacuum_active = False
    
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
            "x": round(self.x, 1),
            "y": round(self.y, 1),
            "z": round(self.z, 1),
            "status": status,
            "motors": motor_states,
            "compressor": comp_state,
            "valve_open": self.valve_open,
            "vacuum_active": self.vacuum_active,
            "total_power_watts": round(total_power, 2),
            "total_energy_joules": round(total_energy, 4),
        }


class MockFactory:
    """Main factory simulation coordinating all subsystems"""
    
    def __init__(self, api_url: str = API_URL, mqtt_broker: str = MQTT_BROKER):
        self.api_url = api_url
        self.mqtt_broker = mqtt_broker
        
        # Subsystems
        self.conveyor = ConveyorSimulation()
        self.hbw = HBWSimulation()
        self.vgr = VGRSimulation()
        
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
            print("[MQTT] Connected to broker")
            # Subscribe to command topics
            client.subscribe("stf/+/cmd/#")
            client.subscribe("stf/global/req/#")
        else:
            print(f"[MQTT] Connection failed: {reason_code}")
    
    def _on_mqtt_message(self, client, userdata, msg):
        """Handle incoming MQTT commands"""
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode())
        except:
            payload = msg.payload.decode()
        
        print(f"[MQTT] Received: {topic} = {payload}")
        
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
        
        elif device == "hbw" and cmd_type == "cmd":
            if action == "move":
                x = payload.get("x", self.hbw.x)
                y = payload.get("y", self.hbw.y)
                z = payload.get("z", self.hbw.z)
                self.hbw.move_to(x, y, z)
            elif action == "stop":
                self.hbw.stop()
            elif action == "gripper":
                self.hbw.gripper_closed = payload.get("close", False)
        
        elif device == "vgr" and cmd_type == "cmd":
            if action == "move":
                x = payload.get("x", self.vgr.x)
                y = payload.get("y", self.vgr.y)
                z = payload.get("z", self.vgr.z)
                self.vgr.move_to(x, y, z)
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
        print("[Factory] All subsystems reset")
    
    def _emergency_stop(self):
        """Emergency stop all subsystems"""
        self.conveyor.stop()
        self.hbw.stop()
        self.vgr.stop()
        self.vgr.release_vacuum()
        print("[Factory] EMERGENCY STOP")
    
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
            print(f"[API] Update error: {e}")
    
    def _publish_mqtt_status(self, conveyor_state: Dict, hbw_state: Dict, vgr_state: Dict):
        """Publish status to MQTT"""
        try:
            self.mqtt_client.publish("stf/conveyor/status", json.dumps(conveyor_state))
            self.mqtt_client.publish("stf/hbw/status", json.dumps(hbw_state))
            self.mqtt_client.publish("stf/vgr/status", json.dumps(vgr_state))
        except Exception as e:
            print(f"[MQTT] Publish error: {e}")
    
    async def run(self):
        """Main simulation loop"""
        print("[Factory] Starting Mock Factory simulation...")
        print(f"[Factory] Tick rate: {TICK_RATE} Hz")
        print(f"[Factory] API URL: {self.api_url}")
        
        # Connect MQTT
        try:
            self.mqtt_client.connect(self.mqtt_broker, MQTT_PORT, 60)
            self.mqtt_client.loop_start()
        except Exception as e:
            print(f"[MQTT] Connection error: {e}")
        
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
            print("\n[Factory] Shutting down...")
        finally:
            self.running = False
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
            if self.http_client:
                await self.http_client.aclose()
            print("[Factory] Shutdown complete")


async def main():
    """Entry point"""
    import os
    
    api_url = os.environ.get("STF_API_URL", API_URL)
    mqtt_broker = os.environ.get("MQTT_BROKER", MQTT_BROKER)
    
    factory = MockFactory(api_url=api_url, mqtt_broker=mqtt_broker)
    await factory.run()


if __name__ == "__main__":
    asyncio.run(main())
