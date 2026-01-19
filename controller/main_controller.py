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
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Optional, Dict, List, Tuple

import httpx

# Optional MQTT support
try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    print("Warning: paho-mqtt not installed. MQTT features disabled.")

# Import kinematic constants from database models
from database.models import (
    SLOT_COORDINATES_3D, SLOT_COORDINATES_2D,
    REST_POS, CONVEYOR_POS,
    PULSES_PER_MM, Z_RETRACTED, Z_CARRY, Z_EXTENDED,
)

# Configuration
API_URL = os.environ.get("STF_API_URL", "http://localhost:8000")
MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "1.0"))  # seconds

# Legacy coordinate mapping (for backward compatibility)
SLOT_COORDINATES = SLOT_COORDINATES_2D

# Zone coordinates (legacy 2D)
ZONES = {
    "PICKUP": (25, 25),       # Cookie pickup zone
    "CONVEYOR": (CONVEYOR_POS[0], CONVEYOR_POS[1]),  # Conveyor handoff zone
    "OVEN": (350, 100),       # Oven zone
    "HOME": (REST_POS[0], REST_POS[1]),  # Home position
}


# =============================================================================
# KINEMATIC CONTROLLER - Pulse Calculation and Sequence Generation
# =============================================================================

@dataclass
class MotionStep:
    """Represents a single motion step in a sequence."""
    axis: str           # 'X', 'Y', or 'Z'
    target_mm: float    # Target position in mm
    pulses: int         # Encoder pulses for this move
    direction: int      # 1 = positive, -1 = negative, 0 = no move
    description: str    # Human-readable description


@dataclass
class HBWPosition:
    """Current position state of the HBW robot."""
    x: float = REST_POS[0]
    y: float = REST_POS[1]
    z: float = REST_POS[2]
    
    def as_tuple(self) -> Tuple[float, float, float]:
        return (self.x, self.y, self.z)
    
    def update(self, x: float = None, y: float = None, z: float = None):
        if x is not None:
            self.x = x
        if y is not None:
            self.y = y
        if z is not None:
            self.z = z


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
    
    PULSES_PER_MM = PULSES_PER_MM  # 18.75
    
    def __init__(self):
        self.current_pos = HBWPosition()
        self.is_carrying_mold = False
    
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
    
    def generate_retrieve_sequence(self, slot_name: str) -> List[Dict]:
        """
        Generate a "square path" sequence to retrieve a mold from a slot to the conveyor.
        
        The robot never moves diagonally inside the rack area. Movement sequence:
        1. Approach: Move X,Y to slot position (Y-10mm to go under mold), Z=retracted
        2. Extend: Move Z to 50 (enter slot)
        3. Lift: Move Y to slot Y+10mm (pick up mold)
        4. Retract: Move Z to 25 (carry position)
        5. Travel: Move X to conveyor X (400mm), keep Y steady
        6. Align Drop: Move Y to conveyor Y+10 (hover above belt)
        7. Place: Move Y to conveyor Y-5 (drop on belt)
        8. Home: Retract Z to 10, move X,Y to REST_POS
        
        Parameters
        ----------
        slot_name : str
            Name of the slot (A1-C3).
        
        Returns
        -------
        List[Dict]
            List of command dictionaries with keys:
            - axis: 'X', 'Y', or 'Z'
            - target: target position in mm
            - pulses: encoder pulses
            - direction: movement direction
            - description: step description
        """
        if slot_name not in SLOT_COORDINATES_3D:
            raise ValueError(f"Invalid slot name: {slot_name}")
        
        slot_x, slot_y, slot_z = SLOT_COORDINATES_3D[slot_name]
        conv_x, conv_y, conv_z = CONVEYOR_POS
        rest_x, rest_y, rest_z = REST_POS
        
        sequence = []
        
        # Track simulated position through sequence
        sim_x, sim_y, sim_z = self.current_pos.as_tuple()
        
        def add_step(axis: str, target: float, desc: str):
            nonlocal sim_x, sim_y, sim_z
            if axis == 'X':
                pulses, direction = self.calc_pulses(target, sim_x)
                sim_x = target
            elif axis == 'Y':
                pulses, direction = self.calc_pulses(target, sim_y)
                sim_y = target
            elif axis == 'Z':
                pulses, direction = self.calc_pulses(target, sim_z)
                sim_z = target
            else:
                raise ValueError(f"Invalid axis: {axis}")
            
            if pulses > 0:  # Only add non-zero moves
                sequence.append({
                    'axis': axis,
                    'target': target,
                    'pulses': pulses,
                    'direction': direction,
                    'description': desc,
                    'position': {'x': sim_x, 'y': sim_y, 'z': sim_z},
                })
        
        # === RETRIEVE SEQUENCE (Slot -> Conveyor) ===
        
        # Step 1: Ensure Z is retracted for safe travel
        add_step('Z', Z_RETRACTED, "Retract Z for safe travel")
        
        # Step 2: Move X to slot column
        add_step('X', slot_x, f"Move X to slot {slot_name} column")
        
        # Step 3: Move Y to under the mold (slot Y - 10mm)
        approach_y = slot_y - 10
        add_step('Y', approach_y, f"Approach Y (under mold at {slot_name})")
        
        # Step 4: Extend Z into slot
        add_step('Z', Z_EXTENDED, "Extend Z into slot")
        
        # Step 5: Lift Y to pick up mold (slot Y + 10mm)
        lift_y = slot_y + 10
        add_step('Y', lift_y, "Lift Y to pick up mold")
        
        # Step 6: Retract Z to carry position
        add_step('Z', Z_CARRY, "Retract Z to carry position")
        
        # Step 7: Travel X to conveyor (keep Y steady)
        add_step('X', conv_x, "Travel X to conveyor")
        
        # Step 8: Align Y for drop (conveyor Y + 10mm to hover above)
        hover_y = conv_y + 10
        add_step('Y', hover_y, "Align Y above conveyor")
        
        # Step 9: Lower Y to place on belt (conveyor Y - 5mm)
        place_y = conv_y - 5
        add_step('Y', place_y, "Lower Y to place on belt")
        
        # Step 10: Home sequence - retract Z first
        add_step('Z', Z_RETRACTED, "Retract Z after placing")
        
        # Step 11: Return to rest X
        add_step('X', rest_x, "Return X to rest position")
        
        # Step 12: Return to rest Y
        add_step('Y', rest_y, "Return Y to rest position")
        
        return sequence
    
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
            List of command dictionaries.
        """
        if slot_name not in SLOT_COORDINATES_3D:
            raise ValueError(f"Invalid slot name: {slot_name}")
        
        slot_x, slot_y, slot_z = SLOT_COORDINATES_3D[slot_name]
        conv_x, conv_y, conv_z = CONVEYOR_POS
        rest_x, rest_y, rest_z = REST_POS
        
        sequence = []
        sim_x, sim_y, sim_z = self.current_pos.as_tuple()
        
        def add_step(axis: str, target: float, desc: str):
            nonlocal sim_x, sim_y, sim_z
            if axis == 'X':
                pulses, direction = self.calc_pulses(target, sim_x)
                sim_x = target
            elif axis == 'Y':
                pulses, direction = self.calc_pulses(target, sim_y)
                sim_y = target
            elif axis == 'Z':
                pulses, direction = self.calc_pulses(target, sim_z)
                sim_z = target
            else:
                raise ValueError(f"Invalid axis: {axis}")
            
            if pulses > 0:
                sequence.append({
                    'axis': axis,
                    'target': target,
                    'pulses': pulses,
                    'direction': direction,
                    'description': desc,
                    'position': {'x': sim_x, 'y': sim_y, 'z': sim_z},
                })
        
        # === STORE SEQUENCE (Conveyor -> Slot) ===
        
        # Step 1: Ensure Z is at carry height
        add_step('Z', Z_CARRY, "Set Z to carry height")
        
        # Step 2: Move X to conveyor
        add_step('X', conv_x, "Move X to conveyor")
        
        # Step 3: Move Y to under mold position (conveyor Y - 10mm)
        pickup_y = conv_y - 10
        add_step('Y', pickup_y, "Move Y under mold at conveyor")
        
        # Step 4: Lift Y to pick up mold
        lift_y = conv_y + 5
        add_step('Y', lift_y, "Lift Y to pick up mold from belt")
        
        # Step 5: Travel X to slot column
        add_step('X', slot_x, f"Travel X to slot {slot_name} column")
        
        # Step 6: Move Y above slot (slot Y + 10mm)
        above_slot_y = slot_y + 10
        add_step('Y', above_slot_y, f"Move Y above slot {slot_name}")
        
        # Step 7: Extend Z into slot
        add_step('Z', Z_EXTENDED, "Extend Z into slot")
        
        # Step 8: Lower Y to place mold (slot Y - 10mm to release)
        place_y = slot_y - 10
        add_step('Y', place_y, "Lower Y to release mold in slot")
        
        # Step 9: Retract Z
        add_step('Z', Z_RETRACTED, "Retract Z after storing")
        
        # Step 10: Return to rest
        add_step('X', rest_x, "Return X to rest position")
        add_step('Y', rest_y, "Return Y to rest position")
        
        return sequence
    
    def update_position(self, x: float = None, y: float = None, z: float = None):
        """Update the tracked position of the robot."""
        self.current_pos.update(x, y, z)


# =============================================================================
# FSM States
# =============================================================================

class ControllerState(Enum):
    """Finite State Machine states for the controller."""
    IDLE = auto()
    POLLING = auto()
    EXECUTING = auto()
    EXECUTING_SEQUENCE = auto()  # New: executing kinematic sequence
    MOVING_TO_SLOT = auto()
    PICKING = auto()
    MOVING_TO_CONVEYOR = auto()
    PLACING = auto()
    WAITING_OVEN = auto()
    RETURNING = auto()
    ERROR = auto()
    EMERGENCY_STOP = auto()


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
    
    def setup_mqtt(self):
        """Initialize MQTT client for hardware communication."""
        if not MQTT_AVAILABLE:
            print("[Controller] MQTT not available - running in simulation mode")
            return
        
        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="stf_controller")
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_message = self._on_mqtt_message
        
        try:
            self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.mqtt_client.loop_start()
            print(f"[Controller] Connected to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
        except Exception as e:
            print(f"[Controller] MQTT connection failed: {e}")
            self.mqtt_client = None
    
    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties=None):
        """Handle MQTT connection and subscribe to topics."""
        if reason_code == 0 or str(reason_code) == "Success":
            topics = [
                "stf/hbw/status",
                "stf/vgr/status", 
                "stf/conveyor/status",
                "stf/global/emergency",
            ]
            for topic in topics:
                client.subscribe(topic)
            print("[Controller] Subscribed to hardware status topics")
    
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
            print(f"[Controller] Invalid JSON in MQTT message")
        except Exception as e:
            print(f"[Controller] Error handling MQTT message: {e}")
    
    def _update_hardware_position(self, payload: dict):
        """Update tracked hardware position from MQTT status."""
        device_id = payload.get("device_id")
        if device_id:
            self.hardware_positions[device_id] = HardwarePosition(
                device_id=device_id,
                x=payload.get("x", 0),
                y=payload.get("y", 0),
                z=payload.get("z", 0),
                status=payload.get("status", "UNKNOWN"),
            )
    
    def _handle_emergency_stop(self):
        """Activate emergency stop mode."""
        self.emergency_stop_active = True
        self.state = ControllerState.EMERGENCY_STOP
        
        if self.mqtt_client:
            for device in ["hbw", "vgr", "conveyor"]:
                self.mqtt_client.publish(f"stf/{device}/cmd/stop", json.dumps({"action": "stop"}))
        
        print("[Controller] *** EMERGENCY STOP ACTIVATED ***")
    
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
            print(f"[Controller] API update error: {e}")
        
        # Send MQTT command
        if self.mqtt_client:
            topic = f"stf/{device_id.lower()}/cmd/move"
            payload = {"x": x, "y": y, "z": 0}
            self.mqtt_client.publish(topic, json.dumps(payload))
        
        print(f"[Controller] MOVE {device_id} -> ({x}, {y})")
        return True
    
    async def _send_gripper_command(self, device_id: str, action: str):
        """Send gripper command (open/close/extend/retract)."""
        if self.mqtt_client:
            topic = f"stf/{device_id.lower()}/cmd/gripper"
            payload = {"action": action}
            self.mqtt_client.publish(topic, json.dumps(payload))
        
        print(f"[Controller] GRIPPER {device_id} -> {action}")
    
    async def _send_conveyor_command(self, action: str, speed: float = 100):
        """Send conveyor belt command."""
        if self.mqtt_client:
            topic = "stf/conveyor/cmd/belt"
            payload = {"action": action, "speed": speed}
            self.mqtt_client.publish(topic, json.dumps(payload))
        
        print(f"[Controller] CONVEYOR -> {action}")
    
    async def _wait_for_idle(self, device_id: str, timeout: float = 30.0) -> bool:
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
        start_time = time.time()
        while time.time() - start_time < timeout:
            # Check API for current status
            try:
                response = await self.http_client.get(f"{API_URL}/hardware/states")
                if response.status_code == 200:
                    states = response.json()
                    for hw in states:
                        if hw["device_id"] == device_id and hw["status"] == "IDLE":
                            return True
            except Exception:
                pass
            
            await asyncio.sleep(0.5)
        
        print(f"[Controller] Timeout waiting for {device_id} to be IDLE")
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
            print(f"[Controller] Error polling commands: {e}")
        
        return None
    
    async def _update_command_status(self, command_id: int, status: str, message: str = ""):
        """Update command status in the database."""
        try:
            await self.http_client.post(
                f"{API_URL}/commands/{command_id}/status",
                json={"status": status, "message": message}
            )
        except Exception as e:
            print(f"[Controller] Error updating command status: {e}")
    
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
        self.state = ControllerState.EXECUTING_SEQUENCE
        
        print(f"\n[Kinematic] Starting sequence: {description}")
        print(f"[Kinematic] Total steps: {len(sequence)}")
        print("=" * 60)
        
        for i, step in enumerate(sequence):
            axis = step['axis']
            target = step['target']
            pulses = step['pulses']
            direction = step['direction']
            desc = step['description']
            pos = step['position']
            
            dir_str = "+" if direction > 0 else "-" if direction < 0 else "="
            
            print(f"\n[Step {i+1}/{len(sequence)}] {desc}")
            print(f"  Axis: {axis}, Target: {target:.1f}mm, Pulses: {pulses}, Dir: {dir_str}")
            print(f"  New Position: X={pos['x']:.1f}, Y={pos['y']:.1f}, Z={pos['z']:.1f}")
            
            # Send MQTT command for this axis movement
            await self._send_axis_move_command("HBW", axis, target, pulses, direction)
            
            # Update API with new position
            await self._update_hardware_position_api("HBW", pos['x'], pos['y'], pos['z'], "MOVING")
            
            # Wait for hardware to complete movement
            await self._wait_for_idle("HBW", timeout=15)
            
            # Update position tracking
            self.kinematics.update_position(x=pos['x'], y=pos['y'], z=pos['z'])
            
            # Update API status to IDLE
            await self._update_hardware_position_api("HBW", pos['x'], pos['y'], pos['z'], "IDLE")
        
        print(f"\n[Kinematic] Sequence complete: {description}")
        print("=" * 60)
        
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
            topic = f"stf/{device_id.lower()}/cmd/move"
            payload = {
                'x': pos_update['x'],
                'y': pos_update['y'],
                'z': pos_update['z'],
                'axis': axis,
                'pulses': pulses,
                'direction': direction,
            }
            self.mqtt_client.publish(topic, json.dumps(payload))
            print(f"  [MQTT] Published: {topic} = {payload}")
        
        return True
    
    async def _update_hardware_position_api(self, device_id: str, x: float, y: float, z: float, status: str):
        """Update hardware position in the API."""
        try:
            await self.http_client.post(
                f"{API_URL}/hardware/state",
                json={"device_id": device_id, "x": x, "y": y, "z": z, "status": status}
            )
        except Exception as e:
            print(f"[Controller] API position update error: {e}")
    
    async def _execute_process_command(self, cmd: QueuedCommand):
        """
        Execute a PROCESS command (RAW_DOUGH -> BAKED) using kinematic sequences.
        
        Workflow using square-path motion:
        1. Retrieve mold from slot to conveyor (kinematic sequence)
        2. Run oven cycle on conveyor
        3. Store mold back from conveyor to slot (kinematic sequence)
        """
        slot_name = cmd.target_slot
        if not slot_name or slot_name not in SLOT_COORDINATES_3D:
            print(f"[Controller] Invalid slot: {slot_name}")
            return False
        
        self.command_start_time = time.time()
        
        try:
            # =============================================
            # Phase 1: Retrieve mold from slot to conveyor
            # =============================================
            self.state = ControllerState.MOVING_TO_SLOT
            print(f"\n{'='*60}")
            print(f"[Controller] PROCESS: Retrieving mold from {slot_name}")
            print(f"{'='*60}")
            
            retrieve_sequence = self.kinematics.generate_retrieve_sequence(slot_name)
            success = await self._execute_kinematic_sequence(
                retrieve_sequence, 
                f"Retrieve from {slot_name}"
            )
            
            if not success:
                print(f"[Controller] Failed to retrieve from {slot_name}")
                return False
            
            # =============================================
            # Phase 2: Run oven cycle (conveyor simulation)
            # =============================================
            self.state = ControllerState.WAITING_OVEN
            print(f"\n[Controller] Starting oven cycle...")
            await self._send_conveyor_command("start")
            await asyncio.sleep(3.0)  # Simulated baking time
            await self._send_conveyor_command("stop")
            print(f"[Controller] Oven cycle complete")
            
            # =============================================
            # Phase 3: Store mold back from conveyor to slot
            # =============================================
            self.state = ControllerState.RETURNING
            print(f"\n{'='*60}")
            print(f"[Controller] PROCESS: Storing baked mold back to {slot_name}")
            print(f"{'='*60}")
            
            store_sequence = self.kinematics.generate_store_sequence(slot_name)
            success = await self._execute_kinematic_sequence(
                store_sequence, 
                f"Store to {slot_name}"
            )
            
            if not success:
                print(f"[Controller] Failed to store to {slot_name}")
                return False
            
            # =============================================
            # Complete
            # =============================================
            elapsed_time = time.time() - self.command_start_time
            energy_joules = 24.0 * 1.5 * elapsed_time  # V * A * s
            await self._log_energy(energy_joules, elapsed_time)
            
            print(f"\n[Controller] PROCESS complete for {slot_name}")
            print(f"  Duration: {elapsed_time:.1f}s, Energy: {energy_joules:.1f}J")
            
            return True
            
        except Exception as e:
            print(f"[Controller] Error executing PROCESS: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def _execute_store_command(self, cmd: QueuedCommand):
        """Execute a STORE command using kinematic sequence."""
        slot_name = cmd.target_slot
        if not slot_name or slot_name not in SLOT_COORDINATES_3D:
            print(f"[Controller] Invalid slot: {slot_name}")
            return False
        
        self.command_start_time = time.time()
        
        try:
            print(f"\n{'='*60}")
            print(f"[Controller] STORE: Moving mold to {slot_name}")
            print(f"{'='*60}")
            
            store_sequence = self.kinematics.generate_store_sequence(slot_name)
            success = await self._execute_kinematic_sequence(
                store_sequence, 
                f"Store to {slot_name}"
            )
            await asyncio.sleep(0.5)
            
            elapsed_time = time.time() - self.command_start_time
            energy_joules = 24.0 * 1.2 * elapsed_time
            await self._log_energy(energy_joules, elapsed_time)
            
            print(f"[Controller] STORE complete for {slot_name}")
            return True
            
        except Exception as e:
            print(f"[Controller] Error executing STORE: {e}")
            return False
    
    async def _execute_retrieve_command(self, cmd: QueuedCommand):
        """Execute a RETRIEVE command using kinematic sequence."""
        slot_name = cmd.target_slot
        if not slot_name or slot_name not in SLOT_COORDINATES_3D:
            print(f"[Controller] Invalid slot: {slot_name}")
            return False
        
        self.command_start_time = time.time()
        
        try:
            print(f"\n{'='*60}")
            print(f"[Controller] RETRIEVE: Moving mold from {slot_name} to conveyor")
            print(f"{'='*60}")
            
            retrieve_sequence = self.kinematics.generate_retrieve_sequence(slot_name)
            success = await self._execute_kinematic_sequence(
                retrieve_sequence, 
                f"Retrieve from {slot_name}"
            )
            
            if not success:
                print(f"[Controller] Failed to retrieve from {slot_name}")
                return False
            
            elapsed_time = time.time() - self.command_start_time
            energy_joules = 24.0 * 1.2 * elapsed_time
            await self._log_energy(energy_joules, elapsed_time)
            
            print(f"[Controller] RETRIEVE complete for {slot_name}")
            return True
            
        except Exception as e:
            print(f"[Controller] Error executing RETRIEVE: {e}")
            return False
    
    async def _log_energy(self, joules: float, duration_sec: float):
        """Log energy consumption to API."""
        try:
            await self.http_client.post(
                f"{API_URL}/energy",
                json={
                    "device_id": "HBW",
                    "joules": joules,
                    "voltage": 24.0,
                    "current_amps": joules / (24.0 * duration_sec) if duration_sec > 0 else 0,
                    "power_watts": joules / duration_sec if duration_sec > 0 else 0,
                }
            )
        except Exception as e:
            print(f"[Controller] Energy log error: {e}")
    
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
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            self.http_client = client
            
            print("=" * 60)
            print("STF Digital Twin - Command Queue Controller")
            print("=" * 60)
            print(f"API URL: {API_URL}")
            print(f"Poll Interval: {POLL_INTERVAL}s")
            print("=" * 60)
            
            while self.running:
                try:
                    if self.emergency_stop_active:
                        print("[Controller] Emergency stop active - waiting for reset")
                        await asyncio.sleep(5.0)
                        continue
                    
                    # Poll for pending commands
                    self.state = ControllerState.POLLING
                    cmd = await self._poll_pending_commands()
                    
                    if cmd:
                        print(f"\n[Controller] Processing command #{cmd.id}: {cmd.command_type}")
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
                            print(f"[Controller] Unknown command type: {cmd.command_type}")
                        
                        # Update final status
                        final_status = "COMPLETED" if success else "FAILED"
                        await self._update_command_status(cmd.id, final_status)
                        
                        self.current_command = None
                    
                    # Return to idle
                    self.state = ControllerState.IDLE
                    await asyncio.sleep(POLL_INTERVAL)
                    
                except Exception as e:
                    print(f"[Controller] Error in main loop: {e}")
                    self.state = ControllerState.ERROR
                    await asyncio.sleep(2.0)
        
        # Cleanup
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        
        print("[Controller] Shutdown complete")
    
    def stop(self):
        """Stop the controller gracefully."""
        self.running = False


async def main():
    """Entry point for the controller."""
    controller = MainController()
    
    try:
        await controller.run()
    except KeyboardInterrupt:
        print("\n[Controller] Interrupted by user")
        controller.stop()


if __name__ == "__main__":
    asyncio.run(main())
