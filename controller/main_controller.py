"""
STF Digital Twin - Main Controller with Command Queue Architecture

This controller implements the "Global Controller" pattern:
    User (UI) -> API (Queue) -> Controller (Poll) -> MQTT (Execute) -> Hardware (Physics)

The controller polls the database for PENDING commands and executes them sequentially,
ensuring proper coordination between subsystems and preventing race conditions.

Kinematic Model:
    - 3-axis Cartesian robot (HBW) with X, Y, Z axes
    - Encoder motor: 75 pulses/rev, 4mm spindle pitch = 18.75 pulses/mm
    - Square path movement (no diagonal moves inside rack)

MQTT Topics:
    Subscribe: stf/{hbw,vgr,conveyor}/status, stf/global/emergency
    Publish:   stf/{device}/cmd/{move,gripper,stop}, stf/conveyor/cmd/{belt,motor}
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Optional, Dict, List, Tuple

import httpx

from utils.logging_config import get_logger

logger = get_logger("controller")

# Optional MQTT support
try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    logger.warning("paho-mqtt not installed. MQTT features disabled.")

# Import kinematic constants from database models
from database.models import (
    SLOT_COORDINATES_3D,
    REST_POS, CONVEYOR_POS,
    PULSES_PER_MM, Z_RETRACTED, Z_CARRY, Z_EXTENDED,
)


# =============================================================================
# CONFIGURATION CONSTANTS
# =============================================================================

# API and MQTT Configuration
API_URL = os.environ.get("STF_API_URL", "http://localhost:8000")
MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "1.0"))  # seconds

# MQTT Topic Prefixes
MQTT_TOPIC_PREFIX = "stf"
MQTT_CMD_MOVE = "cmd/move"
MQTT_CMD_GRIPPER = "cmd/gripper"
MQTT_CMD_STOP = "cmd/stop"
MQTT_CMD_BELT = "cmd/belt"
MQTT_CMD_MOTOR = "cmd/motor"

# Hardware Devices
DEVICE_HBW = "hbw"
DEVICE_VGR = "vgr"
DEVICE_CONVEYOR = "conveyor"

# Timing Constants
DEFAULT_MOVE_TIMEOUT_SEC = 30.0
CONVEYOR_TIMEOUT_SEC = 5.0
SENSOR_POLL_INTERVAL_SEC = 0.1  # 10Hz polling
OVEN_CYCLE_DURATION_SEC = 3.0

# Energy Calculation Constants
MOTOR_VOLTAGE = 24.0  # Volts
MOTOR_CURRENT_MOVE = 1.2  # Amps during movement
MOTOR_CURRENT_PROCESS = 1.5  # Amps during processing

# Conveyor Belt Constants (120mm belt - matches hardware/mock_factory.py)
CONVEYOR_BELT_LENGTH_MM = 120.0
CONVEYOR_HBW_INTERFACE_POS = (400, 100, 25)  # Global factory position
CONVEYOR_VGR_INTERFACE_POS = (400, 100, 25)  # Same global position


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class HBWPosition:
    """Current position state of the HBW robot."""
    x: float = REST_POS[0]
    y: float = REST_POS[1]
    z: float = REST_POS[2]
    
    def as_tuple(self) -> Tuple[float, float, float]:
        """Return position as (x, y, z) tuple."""
        return (self.x, self.y, self.z)
    
    def update(self, x: float = None, y: float = None, z: float = None):
        """Update position coordinates (None values are ignored)."""
        if x is not None:
            self.x = x
        if y is not None:
            self.y = y
        if z is not None:
            self.z = z


@dataclass
class HardwarePosition:
    """Tracks the current position and status of a hardware device."""
    device_id: str
    x: float
    y: float
    z: float
    status: str


@dataclass
class QueuedCommand:
    """Represents a command from the database queue."""
    id: int
    command_type: str
    target_slot: Optional[str]
    payload: dict
    status: str
    created_at: datetime


class KinematicController:
    """
    Kinematic controller for the HBW 3-axis Cartesian robot.
    
    Hardware Specifications:
    - Motor: Fischertechnik Encoder Motor 24V (144643)
    - Encoder: 75 pulses per revolution (output shaft)
    - Spindle: 4mm pitch (linear travel per revolution)
    - Resolution: 18.75 pulses/mm
    
    Coordinate System:
    - X: Horizontal travel along rack (100-400mm)
    - Y: Vertical travel (100-300mm for slots, 90-100mm for conveyor)
    - Z: Arm extension (10=retracted, 25=carry, 50=extended)
    """
    
    # Position offset constants for pick/place operations
    APPROACH_OFFSET_MM = 10.0   # Approach from below
    LIFT_OFFSET_MM = 10.0       # Lift above slot
    HOVER_OFFSET_MM = 10.0      # Hover above conveyor
    PLACE_OFFSET_MM = 5.0       # Lower to place
    
    def __init__(self):
        self.current_pos = HBWPosition()
        self._sequence: List[Dict] = []
        self._sim_pos: Dict[str, float] = {}
    
    @staticmethod
    def calc_pulses(target_mm: float, current_mm: float) -> Tuple[int, int]:
        """
        Calculate encoder pulses needed to move from current to target position.
        
        Parameters
        ----------
        target_mm : float
            Target position in millimeters.
        current_mm : float
            Current position in millimeters.
        
        Returns
        -------
        Tuple[int, int]
            (pulses, direction) where:
            - pulses: Absolute number of encoder pulses (always positive)
            - direction: 1 for positive movement, -1 for negative, 0 for no move
        """
        delta_mm = target_mm - current_mm
        
        if abs(delta_mm) < 0.1:  # Dead zone for small movements
            return (0, 0)
        
        pulses = int(abs(delta_mm) * PULSES_PER_MM)
        direction = 1 if delta_mm > 0 else -1
        
        return (pulses, direction)
    
    def _add_motion_step(self, axis: str, target: float, description: str):
        """
        Add a motion step to the current sequence (internal helper).
        
        Parameters
        ----------
        axis : str
            Axis to move ('X', 'Y', or 'Z').
        target : float
            Target position in mm.
        description : str
            Human-readable description.
        """
        current = self._sim_pos.get(axis.lower(), 0)
        pulses, direction = self.calc_pulses(target, current)
        
        # Update simulated position
        self._sim_pos[axis.lower()] = target
        
        # Only add non-zero moves
        if pulses > 0:
            self._sequence.append({
                'axis': axis,
                'target': target,
                'pulses': pulses,
                'direction': direction,
                'description': description,
                'position': {
                    'x': self._sim_pos['x'],
                    'y': self._sim_pos['y'],
                    'z': self._sim_pos['z'],
                },
            })
    
    def _init_sequence(self):
        """Initialize a new sequence with current position."""
        self._sequence = []
        x, y, z = self.current_pos.as_tuple()
        self._sim_pos = {'x': x, 'y': y, 'z': z}
    
    def generate_retrieve_sequence(self, slot_name: str) -> List[Dict]:
        """
        Generate a "square path" sequence to retrieve a mold from a slot to the conveyor.
        
        The robot never moves diagonally inside the rack area.
        
        Parameters
        ----------
        slot_name : str
            Name of the slot (A1-C3).
        
        Returns
        -------
        List[Dict]
            List of motion step dictionaries.
        
        Raises
        ------
        ValueError
            If slot_name is not valid.
        """
        if slot_name not in SLOT_COORDINATES_3D:
            raise ValueError(f"Invalid slot name: {slot_name}. Valid slots: {list(SLOT_COORDINATES_3D.keys())}")
        
        slot_x, slot_y, _ = SLOT_COORDINATES_3D[slot_name]
        conv_x, conv_y, _ = CONVEYOR_POS
        rest_x, rest_y, _ = REST_POS
        
        self._init_sequence()
        
        # === RETRIEVE SEQUENCE (Slot -> Conveyor) ===
        
        # Phase 1: Safe travel to slot
        self._add_motion_step('Z', Z_RETRACTED, "Retract Z for safe travel")
        self._add_motion_step('X', slot_x, f"Move X to slot {slot_name} column")
        
        # Phase 2: Pick up mold
        self._add_motion_step('Y', slot_y - self.APPROACH_OFFSET_MM, f"Approach Y (under mold at {slot_name})")
        self._add_motion_step('Z', Z_EXTENDED, "Extend Z into slot")
        self._add_motion_step('Y', slot_y + self.LIFT_OFFSET_MM, "Lift Y to pick up mold")
        self._add_motion_step('Z', Z_CARRY, "Retract Z to carry position")
        
        # Phase 3: Travel to conveyor and place
        self._add_motion_step('X', conv_x, "Travel X to conveyor")
        self._add_motion_step('Y', conv_y + self.HOVER_OFFSET_MM, "Align Y above conveyor")
        self._add_motion_step('Y', conv_y - self.PLACE_OFFSET_MM, "Lower Y to place on belt")
        
        # Phase 4: Return home
        self._add_motion_step('Z', Z_RETRACTED, "Retract Z after placing")
        self._add_motion_step('X', rest_x, "Return X to rest position")
        self._add_motion_step('Y', rest_y, "Return Y to rest position")
        
        return self._sequence.copy()
    
    def generate_store_sequence(self, slot_name: str) -> List[Dict]:
        """
        Generate a "square path" sequence to store a mold from conveyor to a slot.
        
        Reverse of retrieve: Conveyor -> Slot
        
        Parameters
        ----------
        slot_name : str
            Name of the target slot (A1-C3).
        
        Returns
        -------
        List[Dict]
            List of motion step dictionaries.
        
        Raises
        ------
        ValueError
            If slot_name is not valid.
        """
        if slot_name not in SLOT_COORDINATES_3D:
            raise ValueError(f"Invalid slot name: {slot_name}. Valid slots: {list(SLOT_COORDINATES_3D.keys())}")
        
        slot_x, slot_y, _ = SLOT_COORDINATES_3D[slot_name]
        conv_x, conv_y, _ = CONVEYOR_POS
        rest_x, rest_y, _ = REST_POS
        
        self._init_sequence()
        
        # === STORE SEQUENCE (Conveyor -> Slot) ===
        
        # Phase 1: Pick up from conveyor
        self._add_motion_step('Z', Z_CARRY, "Set Z to carry height")
        self._add_motion_step('X', conv_x, "Move X to conveyor")
        self._add_motion_step('Y', conv_y - self.APPROACH_OFFSET_MM, "Move Y under mold at conveyor")
        self._add_motion_step('Y', conv_y + self.PLACE_OFFSET_MM, "Lift Y to pick up mold from belt")
        
        # Phase 2: Travel to slot
        self._add_motion_step('X', slot_x, f"Travel X to slot {slot_name} column")
        self._add_motion_step('Y', slot_y + self.LIFT_OFFSET_MM, f"Move Y above slot {slot_name}")
        
        # Phase 3: Place in slot
        self._add_motion_step('Z', Z_EXTENDED, "Extend Z into slot")
        self._add_motion_step('Y', slot_y - self.APPROACH_OFFSET_MM, "Lower Y to release mold in slot")
        self._add_motion_step('Z', Z_RETRACTED, "Retract Z after storing")
        
        # Phase 4: Return home
        self._add_motion_step('X', rest_x, "Return X to rest position")
        self._add_motion_step('Y', rest_y, "Return Y to rest position")
        
        return self._sequence.copy()
    
    def update_position(self, x: float = None, y: float = None, z: float = None):
        """Update the tracked position of the robot."""
        self.current_pos.update(x, y, z)


# =============================================================================
# FSM States
# =============================================================================

class ControllerState(Enum):
    """Finite State Machine states for the controller."""
    IDLE = auto()              # Controller is waiting for commands
    POLLING = auto()           # Polling database for pending commands
    EXECUTING = auto()         # Processing a command
    EXECUTING_SEQUENCE = auto()  # Executing kinematic motion sequence
    WAITING_OVEN = auto()      # Waiting for oven/processing cycle
    ERROR = auto()             # Error state (recoverable)
    EMERGENCY_STOP = auto()    # Emergency stop activated (manual reset required)


class MainController:
    """
    Main Controller for the STF Digital Twin.
    
    Implements the Command Queue architecture where:
    1. API endpoints create commands with status='PENDING'
    2. Controller polls for PENDING commands
    3. Commands are executed sequentially using kinematic sequences
    4. Status is updated to 'COMPLETED' or 'FAILED'
    
    Attributes
    ----------
    state : ControllerState
        Current FSM state of the controller.
    http_client : httpx.AsyncClient
        Async HTTP client for API communication.
    mqtt_client : mqtt.Client
        MQTT client for hardware communication.
    kinematics : KinematicController
        Kinematic controller for pulse calculations and sequence generation.
    running : bool
        Flag indicating if the controller loop is running.
    """
    
    def __init__(self):
        self.state = ControllerState.IDLE
        self.current_command: Optional[QueuedCommand] = None
        self.hardware_positions: Dict[str, HardwarePosition] = {}
        self.mqtt_client: Optional[mqtt.Client] = None
        self.http_client: Optional[httpx.AsyncClient] = None
        self.running = False
        
        # Kinematic controller for 3-axis motion
        self.kinematics = KinematicController()
        
        # Safety flags
        self.emergency_stop_active = False
        
        # Energy tracking
        self.total_energy_joules = 0.0
        self.command_start_time: Optional[float] = None
    
    # =========================================================================
    # MQTT Setup and Handlers
    # =========================================================================
    
    def setup_mqtt(self) -> bool:
        """
        Initialize MQTT client for hardware communication.
        
        Returns
        -------
        bool
            True if MQTT connected successfully, False otherwise.
        """
        if not MQTT_AVAILABLE:
            logger.info("[Controller] MQTT not available - running in simulation mode")
            return False
        
        try:
            self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="stf_controller")
            self.mqtt_client.on_connect = self._on_mqtt_connect
            self.mqtt_client.on_message = self._on_mqtt_message
            
            self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.mqtt_client.loop_start()
            logger.info("[Controller] Connected to MQTT broker at %s:%s", MQTT_BROKER, MQTT_PORT)
            return True
        except Exception as e:
            logger.error("[Controller] MQTT connection failed: %s", e)
            self.mqtt_client = None
            return False
    
    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties=None):
        """Handle MQTT connection and subscribe to topics."""
        try:
            if reason_code == 0 or str(reason_code) == "Success":
                topics = [
                    "stf/hbw/status",
                    "stf/vgr/status", 
                    "stf/conveyor/status",
                    "stf/global/emergency",
                ]
                for topic in topics:
                    client.subscribe(topic)
                logger.info("[Controller] Subscribed to hardware status topics")
            else:
                logger.error("[Controller] MQTT connection failed with reason: %s", reason_code)
        except Exception as e:
            logger.error("[Controller] Error in MQTT connect handler: %s", e)
    
    def _on_mqtt_message(self, client, userdata, msg):
        """Handle incoming MQTT messages from hardware."""
        try:
            payload = json.loads(msg.payload.decode())
            topic = msg.topic
            
            if "/status" in topic:
                self._update_hardware_position(payload)
            elif "emergency" in topic:
                self._handle_emergency_stop()
                
        except json.JSONDecodeError:
            logger.error("[Controller] Invalid JSON in MQTT message")
        except Exception as e:
            logger.error("[Controller] Error handling MQTT message: %s", e)
    
    def _update_hardware_position(self, payload: dict):
        """Update tracked hardware position from MQTT status."""
        try:
            device_id = payload.get("device_id")
            if device_id:
                self.hardware_positions[device_id] = HardwarePosition(
                    device_id=device_id,
                    x=float(payload.get("x", 0)),
                    y=float(payload.get("y", 0)),
                    z=float(payload.get("z", 0)),
                    status=str(payload.get("status", "UNKNOWN")),
                )
        except (TypeError, ValueError) as e:
            logger.error("[Controller] Error parsing hardware position: %s", e)
    
    def _handle_emergency_stop(self):
        """Activate emergency stop mode."""
        self.emergency_stop_active = True
        self.state = ControllerState.EMERGENCY_STOP
        
        if self.mqtt_client:
            try:
                for device in [DEVICE_HBW, DEVICE_VGR, DEVICE_CONVEYOR]:
                    topic = f"{MQTT_TOPIC_PREFIX}/{device}/{MQTT_CMD_STOP}"
                    self.mqtt_client.publish(topic, json.dumps({"action": "stop"}))
            except Exception as e:
                logger.error("[Controller] MQTT emergency stop error: %s", e)
        
        logger.critical("[Controller] *** EMERGENCY STOP ACTIVATED ***")
    
    # =========================================================================
    # Hardware Command Methods
    # =========================================================================
    
    async def _send_move_command(self, device_id: str, x: float, y: float) -> bool:
        """
        Send move command to hardware via MQTT and API.
        
        Parameters
        ----------
        device_id : str
            Target device (e.g., 'HBW', 'VGR').
        x : float
            Target X position in mm.
        y : float
            Target Y position in mm.
        
        Returns
        -------
        bool
            True if command was sent successfully.
        """
        # Update API
        try:
            await self.http_client.post(
                f"{API_URL}/hardware/state",
                json={"device_id": device_id, "x": x, "y": y, "z": 0, "status": "MOVING"}
            )
        except Exception as e:
            logger.error("[Controller] API update error: %s", e)
        
        # Send MQTT command
        if self.mqtt_client:
            try:
                topic = f"{MQTT_TOPIC_PREFIX}/{device_id.lower()}/{MQTT_CMD_MOVE}"
                payload = {"x": x, "y": y, "z": 0}
                self.mqtt_client.publish(topic, json.dumps(payload))
            except Exception as e:
                logger.error("[Controller] MQTT move command error: %s", e)
        
        logger.info("[Controller] MOVE %s -> (%s, %s)", device_id, x, y)
        return True
    
    async def _send_gripper_command(self, device_id: str, action: str):
        """Send gripper command (open/close/extend/retract)."""
        if self.mqtt_client:
            try:
                topic = f"{MQTT_TOPIC_PREFIX}/{device_id.lower()}/{MQTT_CMD_GRIPPER}"
                payload = {"action": action}
                self.mqtt_client.publish(topic, json.dumps(payload))
            except Exception as e:
                logger.error("[Controller] MQTT gripper command error: %s", e)
        
        logger.info("[Controller] GRIPPER %s -> %s", device_id, action)
    
    async def _send_conveyor_command(self, action: str, speed: float = 100):
        """Send conveyor belt command."""
        if self.mqtt_client:
            try:
                topic = f"{MQTT_TOPIC_PREFIX}/{DEVICE_CONVEYOR}/{MQTT_CMD_BELT}"
                payload = {"action": action, "speed": speed}
                self.mqtt_client.publish(topic, json.dumps(payload))
            except Exception as e:
                logger.error("[Controller] MQTT conveyor command error: %s", e)
        
        logger.info("[Controller] CONVEYOR -> %s", action)
    
    # =========================================================================
    # SENSOR-BASED CONVEYOR CONTROL
    # These methods use Light Barrier sensors (I2, I3) for positioning
    # instead of encoder-based position tracking.
    # =========================================================================

    async def _get_conveyor_sensors(self) -> Dict[str, bool]:
        """
        Fetch current conveyor sensor states from API.
        
        Returns
        -------
        Dict[str, bool]
            Sensor states: {"I2": bool, "I3": bool, "I5": bool, "I6": bool}
        
        Raises
        ------
        RuntimeError
            If unable to fetch sensor states from API.
        """
        try:
            response = await self.http_client.get(f"{API_URL}/hardware/states")
            if response.status_code == 200:
                states = response.json()
                for hw in states:
                    if hw.get("device_id") == "CONVEYOR":
                        light_barriers = hw.get("light_barriers", {})
                        return {
                            "I2": light_barriers.get("I2", {}).get("is_triggered", False),
                            "I3": light_barriers.get("I3", {}).get("is_triggered", False),
                            "I5": hw.get("trail_sensors", {}).get("I5", {}).get("is_triggered", False),
                            "I6": hw.get("trail_sensors", {}).get("I6", {}).get("is_triggered", False),
                        }
        except Exception as e:
            logger.error("[Controller] Error fetching conveyor sensors: %s", e)
        
        raise RuntimeError("Unable to fetch conveyor sensor states")
    
    async def move_conveyor_inbound(self) -> Dict:
        """
        Move item from VGR side to HBW side (inbound transport).
        
        Direction: VGR → HBW (forward, direction=1)
        Monitors: I2 sensor (triggers when item reaches HBW interface at ~105mm on 120mm belt)
        
        Workflow:
        1. Congestion Check: Verify I2 is not already triggered (slot not blocked)
        2. Start: Send MQTT command to start Motor M1 (forward/inward)
        3. Monitor: Poll I2 sensor in a loop
        4. Stop: When I2 triggers, immediately stop motor
        5. State: Update carrier state to HBW interface position (400, 100, 25)
        6. Safety: 5-second timeout with automatic stop if reached
        
        Returns
        -------
        Dict
            Result with "success" bool, "message" str, and "position" tuple.
        
        Raises
        ------
        RuntimeError
            If HBW interface is blocked (I2 already triggered) or timeout occurs.
        """
        logger.info("[Controller] CONVEYOR INBOUND: VGR → HBW transport starting...")
        
        # Step 1: Congestion Check
        try:
            sensors = await self._get_conveyor_sensors()
            if sensors["I2"]:
                raise RuntimeError("Conveyor INBOUND blocked: I2 sensor triggered (HBW interface occupied)")
        except RuntimeError:
            raise
        except Exception as e:
            logger.warning("[Controller] Warning: Could not check congestion: %s", e)
        
        # Step 2: Start motor (forward direction = 1)
        await self._send_conveyor_command("start_forward", speed=100)
        if self.mqtt_client:
            try:
                topic = f"{MQTT_TOPIC_PREFIX}/{DEVICE_CONVEYOR}/{MQTT_CMD_MOTOR}"
                payload = {"action": "start", "direction": 1, "motor": "M1"}  # Q1/Inwards
                self.mqtt_client.publish(topic, json.dumps(payload))
            except Exception as e:
                logger.error("[Controller] MQTT motor start error: %s", e)
        
        logger.info("[Controller] CONVEYOR M1 started (direction: INWARD/Q1)")
        
        # Step 3: Monitor I2 sensor with timeout
        start_time = time.time()
        i2_triggered = False
        
        while time.time() - start_time < CONVEYOR_TIMEOUT_SEC:
            try:
                sensors = await self._get_conveyor_sensors()
                if sensors["I2"]:
                    i2_triggered = True
                    break
            except Exception as e:
                logger.error("[Controller] Sensor poll error: %s", e)
            
            await asyncio.sleep(SENSOR_POLL_INTERVAL_SEC)  # Poll at 10Hz
        
        # Step 4: Stop motor immediately
        await self._send_conveyor_command("stop")
        if self.mqtt_client:
            try:
                topic = f"{MQTT_TOPIC_PREFIX}/{DEVICE_CONVEYOR}/{MQTT_CMD_MOTOR}"
                payload = {"action": "stop", "motor": "M1"}
                self.mqtt_client.publish(topic, json.dumps(payload))
            except Exception as e:
                logger.error("[Controller] MQTT motor stop error: %s", e)
        
        logger.info("[Controller] CONVEYOR M1 stopped")
        
        # Step 5: Check result and update state
        if not i2_triggered:
            raise RuntimeError(f"Conveyor JAMMED: I2 not triggered within {CONVEYOR_TIMEOUT_SEC}s timeout")
        
        # Update state: item is now at HBW interface
        position = CONVEYOR_HBW_INTERFACE_POS
        logger.info("[Controller] CONVEYOR INBOUND complete: Item at HBW interface %s", position)
        
        # Update API with new carrier position
        try:
            await self.http_client.post(
                f"{API_URL}/hardware/state",
                json={
                    "device_id": "CONVEYOR",
                    "x": position[0],
                    "y": position[1],
                    "z": position[2],
                    "status": "IDLE",
                    "message": "Item at HBW interface (I2 triggered)"
                }
            )
        except Exception as e:
            logger.error("[Controller] API state update error: %s", e)
        
        return {
            "success": True,
            "message": "Item transported to HBW interface",
            "position": position,
            "sensor_triggered": "I2"
        }
    
    async def move_conveyor_outbound(self) -> Dict:
        """
        Move item from HBW side to VGR side (outbound transport).
        
        Direction: HBW → VGR (reverse, direction=-1)
        Monitors: I3 sensor (triggers when item reaches VGR interface at ~15mm on 120mm belt)
        
        Workflow:
        1. Congestion Check: Verify I3 is not already triggered (exit not blocked)
        2. Start: Send MQTT command to start Motor M1 (reverse/outward)
        3. Monitor: Poll I3 sensor in a loop
        4. Stop: When I3 triggers, immediately stop motor
        5. Safety: 5-second timeout with automatic stop if reached
        
        Returns
        -------
        Dict
            Result with "success" bool, "message" str.
        
        Raises
        ------
        RuntimeError
            If VGR interface is blocked (I3 already triggered) or timeout occurs.
        """
        logger.info("[Controller] CONVEYOR OUTBOUND: HBW → VGR transport starting...")
        
        # Step 1: Congestion Check
        try:
            sensors = await self._get_conveyor_sensors()
            if sensors["I3"]:
                raise RuntimeError("Conveyor OUTBOUND blocked: I3 sensor triggered (VGR interface occupied)")
        except RuntimeError:
            raise
        except Exception as e:
            logger.warning("[Controller] Warning: Could not check congestion: %s", e)
        
        # Step 2: Start motor (reverse direction = -1)
        await self._send_conveyor_command("start_reverse", speed=100)
        if self.mqtt_client:
            try:
                topic = f"{MQTT_TOPIC_PREFIX}/{DEVICE_CONVEYOR}/{MQTT_CMD_MOTOR}"
                payload = {"action": "start", "direction": -1, "motor": "M1"}  # Q2/Outwards
                self.mqtt_client.publish(topic, json.dumps(payload))
            except Exception as e:
                logger.error("[Controller] MQTT motor start error: %s", e)
        
        logger.info("[Controller] CONVEYOR M1 started (direction: OUTWARD/Q2)")
        
        # Step 3: Monitor I3 sensor with timeout
        start_time = time.time()
        i3_triggered = False
        
        while time.time() - start_time < CONVEYOR_TIMEOUT_SEC:
            try:
                sensors = await self._get_conveyor_sensors()
                if sensors["I3"]:
                    i3_triggered = True
                    break
            except Exception as e:
                logger.error("[Controller] Sensor poll error: %s", e)
            
            await asyncio.sleep(SENSOR_POLL_INTERVAL_SEC)  # Poll at 10Hz
        
        # Step 4: Stop motor immediately
        await self._send_conveyor_command("stop")
        if self.mqtt_client:
            try:
                topic = f"{MQTT_TOPIC_PREFIX}/{DEVICE_CONVEYOR}/{MQTT_CMD_MOTOR}"
                payload = {"action": "stop", "motor": "M1"}
                self.mqtt_client.publish(topic, json.dumps(payload))
            except Exception as e:
                logger.error("[Controller] MQTT motor stop error: %s", e)
        
        logger.info("[Controller] CONVEYOR M1 stopped")
        
        # Step 5: Check result
        if not i3_triggered:
            raise RuntimeError(f"Conveyor JAMMED: I3 not triggered within {CONVEYOR_TIMEOUT_SEC}s timeout")
        
        logger.info("[Controller] CONVEYOR OUTBOUND complete: Item at VGR interface (I3 triggered)")
        
        # Update API state - VGR interface at same global position
        vgr_pos = CONVEYOR_VGR_INTERFACE_POS
        try:
            await self.http_client.post(
                f"{API_URL}/hardware/state",
                json={
                    "device_id": "CONVEYOR",
                    "x": vgr_pos[0],
                    "y": vgr_pos[1],
                    "z": vgr_pos[2],
                    "status": "IDLE",
                    "message": "Item at VGR interface (I3 triggered)"
                }
            )
        except Exception as e:
            logger.error("[Controller] API state update error: %s", e)
        
        return {
            "success": True,
            "message": "Item transported to VGR interface",
            "sensor_triggered": "I3"
        }

    async def _wait_for_idle(self, device_id: str, timeout: float = DEFAULT_MOVE_TIMEOUT_SEC) -> bool:
        """
        Wait for a device to return to IDLE status.
        
        Parameters
        ----------
        device_id : str
            Device to wait for.
        timeout : float
            Maximum wait time in seconds.
        
        Returns
        -------
        bool
            True if device is IDLE, False if timeout.
        """
        if not self.http_client:
            logger.info("[Controller] HTTP client not available for %s status check", device_id)
            return False
            
        start_time = time.time()
        while time.time() - start_time < timeout:
            # Check API for current status
            try:
                response = await self.http_client.get(f"{API_URL}/hardware/states")
                if response.status_code == 200:
                    states = response.json()
                    for hw in states:
                        if hw.get("device_id") == device_id and hw.get("status") == "IDLE":
                            return True
            except Exception as e:
                logger.error("[Controller] Error checking %s status: %s", device_id, e)
            
            await asyncio.sleep(0.5)
        
        logger.warning("[Controller] Timeout waiting for %s to be IDLE", device_id)
        return False
    
    # =========================================================================
    # Command Queue Polling
    # =========================================================================
    
    async def _poll_pending_commands(self) -> Optional[QueuedCommand]:
        """
        Poll the database for the oldest PENDING command.
        
        Returns
        -------
        Optional[QueuedCommand]
            The next command to execute, or None if queue is empty.
        """
        try:
            # Query API for pending commands
            response = await self.http_client.get(
                f"{API_URL}/commands/pending",
                params={"limit": 1}
            )
            
            if response.status_code == 200:
                commands = response.json()
                if commands and len(commands) > 0:
                    cmd = commands[0]
                    return QueuedCommand(
                        id=cmd["id"],
                        command_type=cmd["command_type"],
                        target_slot=cmd.get("target_slot"),
                        payload=json.loads(cmd.get("payload_json", "{}")),
                        status=cmd["status"],
                        created_at=datetime.fromisoformat(cmd["created_at"].replace("Z", "+00:00")),
                    )
            elif response.status_code == 404:
                # Endpoint doesn't exist yet - use dashboard data
                pass
                
        except Exception as e:
            logger.error("[Controller] Error polling commands: %s", e)
        
        return None
    
    async def _update_command_status(self, command_id: int, status: str, message: str = ""):
        """Update command status in the database."""
        try:
            await self.http_client.post(
                f"{API_URL}/commands/{command_id}/status",
                json={"status": status, "message": message}
            )
        except Exception as e:
            logger.error("[Controller] Error updating command status: %s", e)
    
    # =========================================================================
    # Command Execution - Kinematic Sequence Execution
    # =========================================================================
    
    async def _execute_kinematic_sequence(self, sequence: List[Dict], description: str = "") -> bool:
        """
        Execute a kinematic motion sequence step by step.
        
        Each step is executed one axis at a time, waiting for IDLE status
        before proceeding to the next step. This ensures "square path" motion
        without diagonal movements.
        
        Parameters
        ----------
        sequence : List[Dict]
            List of motion steps from KinematicController.
        description : str
            Human-readable description of the sequence.
        
        Returns
        -------
        bool
            True if sequence completed successfully, False on error.
        """
        if not sequence:
            logger.warning("[Kinematic] Warning: Empty sequence for '%s'", description)
            return True
            
        self.state = ControllerState.EXECUTING_SEQUENCE
        
        logger.info("\n[Kinematic] Starting sequence: %s", description)
        logger.info("[Kinematic] Total steps: %s", len(sequence))
        logger.info("=" * 60)
        
        for i, step in enumerate(sequence):
            try:
                axis = step['axis']
                target = step['target']
                pulses = step['pulses']
                direction = step['direction']
                desc = step['description']
                pos = step['position']
                
                dir_str = "+" if direction > 0 else "-" if direction < 0 else "="
                
                logger.info("\n[Step %s/%s] %s", i+1, len(sequence), desc)
                logger.info("  Axis: %s, Target: %.1fmm, Pulses: %s, Dir: %s", axis, target, pulses, dir_str)
                logger.info("  New Position: X=%.1f, Y=%.1f, Z=%.1f", pos['x'], pos['y'], pos['z'])
                
                # Send MQTT command for this axis movement
                await self._send_axis_move_command("HBW", axis, target, pulses, direction)
                
                # Update API with new position
                await self._update_hardware_position_api("HBW", pos['x'], pos['y'], pos['z'], "MOVING")
                
                # Wait for hardware to complete movement
                if not await self._wait_for_idle("HBW", timeout=DEFAULT_MOVE_TIMEOUT_SEC):
                    logger.warning("[Kinematic] Step %s timed out waiting for IDLE", i+1)
                    return False
                
                # Update position tracking
                self.kinematics.update_position(x=pos['x'], y=pos['y'], z=pos['z'])
                
                # Update API status to IDLE
                await self._update_hardware_position_api("HBW", pos['x'], pos['y'], pos['z'], "IDLE")
                
            except KeyError as e:
                logger.error("[Kinematic] Step %s missing required field: %s", i+1, e)
                return False
            except Exception as e:
                logger.error("[Kinematic] Step %s failed with error: %s", i+1, e)
                return False
        
        logger.info("\n[Kinematic] Sequence complete: %s", description)
        logger.info("=" * 60)
        
        return True
    
    async def _send_axis_move_command(self, device_id: str, axis: str, target_mm: float, 
                                       pulses: int, direction: int) -> bool:
        """
        Send a single-axis move command via MQTT.
        
        Parameters
        ----------
        device_id : str
            Target device (e.g., 'HBW').
        axis : str
            Axis to move ('X', 'Y', or 'Z').
        target_mm : float
            Target position in mm.
        pulses : int
            Encoder pulses for this movement.
        direction : int
            Movement direction (1=positive, -1=negative).
        
        Returns
        -------
        bool
            True if command was sent successfully.
        """
        # Build position update based on axis
        pos_update = {
            'x': self.kinematics.current_pos.x,
            'y': self.kinematics.current_pos.y,
            'z': self.kinematics.current_pos.z,
        }
        pos_update[axis.lower()] = target_mm
        
        # Send MQTT command with kinematic data
        if self.mqtt_client:
            try:
                topic = f"{MQTT_TOPIC_PREFIX}/{device_id.lower()}/{MQTT_CMD_MOVE}"
                payload = {
                    'x': pos_update['x'],
                    'y': pos_update['y'],
                    'z': pos_update['z'],
                    'axis': axis,
                    'pulses': pulses,
                    'direction': direction,
                }
                self.mqtt_client.publish(topic, json.dumps(payload))
                logger.info("  [MQTT] Published: %s = %s", topic, payload)
            except Exception as e:
                logger.error("[Controller] MQTT axis move error: %s", e)
        
        return True
    
    async def _update_hardware_position_api(self, device_id: str, x: float, y: float, z: float, status: str):
        """Update hardware position in the API."""
        try:
            await self.http_client.post(
                f"{API_URL}/hardware/state",
                json={"device_id": device_id, "x": x, "y": y, "z": z, "status": status}
            )
        except Exception as e:
            logger.error("[Controller] API position update error: %s", e)
    
    async def _execute_process_command(self, cmd: QueuedCommand) -> bool:
        """
        Execute a PROCESS command (RAW_DOUGH -> BAKED) using kinematic sequences.
        
        Workflow using square-path motion:
        1. Retrieve mold from slot to conveyor (kinematic sequence)
        2. Run oven cycle on conveyor
        3. Store mold back from conveyor to slot (kinematic sequence)
        
        Parameters
        ----------
        cmd : QueuedCommand
            The command to execute.
        
        Returns
        -------
        bool
            True if command completed successfully, False on error.
        """
        slot_name = cmd.target_slot
        if not slot_name or slot_name not in SLOT_COORDINATES_3D:
            logger.error("[Controller] Invalid slot: %s", slot_name)
            return False
        
        self.command_start_time = time.time()
        
        try:
            # =============================================
            # Phase 1: Retrieve mold from slot to conveyor
            # =============================================
            self.state = ControllerState.EXECUTING
            logger.info("\n%s", '='*60)
            logger.info("[Controller] PROCESS: Retrieving mold from %s", slot_name)
            logger.info("%s", '='*60)
            
            retrieve_sequence = self.kinematics.generate_retrieve_sequence(slot_name)
            success = await self._execute_kinematic_sequence(
                retrieve_sequence, 
                f"Retrieve from {slot_name}"
            )
            
            if not success:
                logger.error("[Controller] Failed to retrieve from %s", slot_name)
                return False
            
            # =============================================
            # Phase 2: Run oven cycle (conveyor simulation)
            # =============================================
            self.state = ControllerState.WAITING_OVEN
            logger.info("\n[Controller] Starting oven cycle...")
            await self._send_conveyor_command("start")
            await asyncio.sleep(OVEN_CYCLE_DURATION_SEC)
            await self._send_conveyor_command("stop")
            logger.info("[Controller] Oven cycle complete")
            
            # =============================================
            # Phase 3: Store mold back from conveyor to slot
            # =============================================
            self.state = ControllerState.EXECUTING
            logger.info("\n%s", '='*60)
            logger.info("[Controller] PROCESS: Storing baked mold back to %s", slot_name)
            logger.info("%s", '='*60)
            
            store_sequence = self.kinematics.generate_store_sequence(slot_name)
            success = await self._execute_kinematic_sequence(
                store_sequence, 
                f"Store to {slot_name}"
            )
            
            if not success:
                logger.error("[Controller] Failed to store to %s", slot_name)
                return False
            
            # =============================================
            # Complete
            # =============================================
            elapsed_time = time.time() - self.command_start_time
            energy_joules = MOTOR_VOLTAGE * MOTOR_CURRENT_PROCESS * elapsed_time  # V * A * s
            await self._log_energy(energy_joules, elapsed_time)
            
            logger.info("\n[Controller] PROCESS complete for %s", slot_name)
            logger.info("  Duration: %.1fs, Energy: %.1fJ", elapsed_time, energy_joules)
            
            return True
            
        except Exception as e:
            logger.error("[Controller] Error executing PROCESS: %s", e)
            return False
    
    async def _execute_store_command(self, cmd: QueuedCommand) -> bool:
        """
        Execute a STORE command using kinematic sequence.
        
        Moves a mold from the conveyor to the specified slot.
        
        Parameters
        ----------
        cmd : QueuedCommand
            The command to execute.
        
        Returns
        -------
        bool
            True if command completed successfully, False on error.
        """
        slot_name = cmd.target_slot
        if not slot_name or slot_name not in SLOT_COORDINATES_3D:
            logger.error("[Controller] Invalid slot: %s", slot_name)
            return False
        
        self.command_start_time = time.time()
        
        try:
            logger.info("\n%s", '='*60)
            logger.info("[Controller] STORE: Moving mold to %s", slot_name)
            logger.info("%s", '='*60)
            
            store_sequence = self.kinematics.generate_store_sequence(slot_name)
            success = await self._execute_kinematic_sequence(
                store_sequence, 
                f"Store to {slot_name}"
            )
            await asyncio.sleep(0.5)
            
            elapsed_time = time.time() - self.command_start_time
            energy_joules = MOTOR_VOLTAGE * MOTOR_CURRENT_MOVE * elapsed_time
            await self._log_energy(energy_joules, elapsed_time)
            
            logger.info("[Controller] STORE complete for %s", slot_name)
            return True
            
        except Exception as e:
            logger.error("[Controller] Error executing STORE: %s", e)
            return False
    
    async def _execute_retrieve_command(self, cmd: QueuedCommand) -> bool:
        """
        Execute a RETRIEVE command using kinematic sequence.
        
        Moves a mold from the specified slot to the conveyor.
        
        Parameters
        ----------
        cmd : QueuedCommand
            The command to execute.
        
        Returns
        -------
        bool
            True if command completed successfully, False on error.
        """
        slot_name = cmd.target_slot
        if not slot_name or slot_name not in SLOT_COORDINATES_3D:
            logger.error("[Controller] Invalid slot: %s", slot_name)
            return False
        
        self.command_start_time = time.time()
        
        try:
            logger.info("\n%s", '='*60)
            logger.info("[Controller] RETRIEVE: Moving mold from %s to conveyor", slot_name)
            logger.info("%s", '='*60)
            
            retrieve_sequence = self.kinematics.generate_retrieve_sequence(slot_name)
            success = await self._execute_kinematic_sequence(
                retrieve_sequence, 
                f"Retrieve from {slot_name}"
            )
            
            if not success:
                logger.error("[Controller] Failed to retrieve from %s", slot_name)
                return False
            
            elapsed_time = time.time() - self.command_start_time
            energy_joules = MOTOR_VOLTAGE * MOTOR_CURRENT_MOVE * elapsed_time
            await self._log_energy(energy_joules, elapsed_time)
            
            logger.info("[Controller] RETRIEVE complete for %s", slot_name)
            return True
            
        except Exception as e:
            logger.error("[Controller] Error executing RETRIEVE: %s", e)
            return False
    
    async def _log_energy(self, joules: float, duration_sec: float):
        """Log energy consumption to API."""
        try:
            await self.http_client.post(
                f"{API_URL}/energy",
                json={
                    "device_id": "HBW",
                    "joules": joules,
                    "voltage": MOTOR_VOLTAGE,
                    "current_amps": joules / (MOTOR_VOLTAGE * duration_sec) if duration_sec > 0 else 0,
                    "power_watts": joules / duration_sec if duration_sec > 0 else 0,
                }
            )
        except Exception as e:
            logger.error("[Controller] Energy log error: %s", e)
    
    # =========================================================================
    # Main Control Loop
    # =========================================================================
    
    async def run(self):
        """
        Main controller loop implementing the Command Queue pattern.
        
        Loop Steps:
        1. Poll for PENDING commands
        2. Execute command (if found)
        3. Update command status
        4. Repeat
        """
        self.running = True
        self.setup_mqtt()
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                self.http_client = client
                
                logger.info("=" * 60)
                logger.info("STF Digital Twin - Command Queue Controller")
                logger.info("=" * 60)
                logger.info("API URL: %s", API_URL)
                logger.info("MQTT Broker: %s:%s", MQTT_BROKER, MQTT_PORT)
                logger.info("Poll Interval: %ss", POLL_INTERVAL)
                logger.info("=" * 60)
                
                while self.running:
                    try:
                        if self.emergency_stop_active:
                            logger.critical("[Controller] Emergency stop active - waiting for reset")
                            await asyncio.sleep(5.0)
                            continue
                        
                        # Poll for pending commands
                        self.state = ControllerState.POLLING
                        cmd = await self._poll_pending_commands()
                        
                        if cmd:
                            logger.info("\n[Controller] Processing command #%s: %s", cmd.id, cmd.command_type)
                            self.current_command = cmd
                            self.state = ControllerState.EXECUTING
                            
                            # Update status to IN_PROGRESS
                            await self._update_command_status(cmd.id, "IN_PROGRESS")
                            
                            # Execute based on command type
                            success = False
                            if cmd.command_type == "PROCESS":
                                success = await self._execute_process_command(cmd)
                            elif cmd.command_type == "STORE":
                                success = await self._execute_store_command(cmd)
                            elif cmd.command_type == "RETRIEVE":
                                success = await self._execute_retrieve_command(cmd)
                            else:
                                logger.info("[Controller] Unknown command type: %s", cmd.command_type)
                            
                            # Update final status
                            final_status = "COMPLETED" if success else "FAILED"
                            await self._update_command_status(cmd.id, final_status)
                            
                            self.current_command = None
                        
                        # Return to idle
                        self.state = ControllerState.IDLE
                        await asyncio.sleep(POLL_INTERVAL)
                        
                    except Exception as e:
                        logger.error("[Controller] Error in main loop: %s", e)
                        self.state = ControllerState.ERROR
                        await asyncio.sleep(2.0)
        
        finally:
            # Cleanup MQTT connection
            self._cleanup_mqtt()
        
        logger.info("[Controller] Shutdown complete")
    
    def _cleanup_mqtt(self):
        """Clean up MQTT client connection."""
        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception as e:
                logger.error("[Controller] MQTT cleanup error: %s", e)
            finally:
                self.mqtt_client = None
    
    def stop(self):
        """Stop the controller gracefully."""
        self.running = False


async def main():
    """Entry point for the controller."""
    controller = MainController()
    
    try:
        await controller.run()
    except KeyboardInterrupt:
        logger.info("\n[Controller] Interrupted by user")
        controller.stop()


if __name__ == "__main__":
    asyncio.run(main())
