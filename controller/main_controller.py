"""
STF Digital Twin - Main Controller
FSM logic, command translation, safety interlocks, and energy logging
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Dict, List

import httpx

# Optional MQTT support
try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    print("Warning: paho-mqtt not installed. MQTT features disabled.")

# Configuration
API_URL = os.environ.get("STF_API_URL", "http://localhost:8000")
MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))

# Coordinate mapping (slot name -> physical X/Y)
SLOT_COORDINATES = {
    "A1": (100, 100), "A2": (200, 100), "A3": (300, 100),
    "B1": (100, 200), "B2": (200, 200), "B3": (300, 200),
    "C1": (100, 300), "C2": (200, 300), "C3": (300, 300),
}

# Safety zones (areas where collision prevention is active)
SAFETY_ZONES = {
    "PICKUP": {"x_min": 0, "x_max": 50, "y_min": 0, "y_max": 50},
    "DROPOFF": {"x_min": 350, "x_max": 400, "y_min": 350, "y_max": 400},
}


class ControllerState(Enum):
    """Finite State Machine states"""
    IDLE = auto()
    MOVING_TO_PICKUP = auto()
    PICKING = auto()
    MOVING_TO_SLOT = auto()
    PLACING = auto()
    MOVING_TO_DROPOFF = auto()
    RETRIEVING = auto()
    ERROR = auto()
    EMERGENCY_STOP = auto()


@dataclass
class HardwarePosition:
    device_id: str
    x: float
    y: float
    z: float
    status: str


@dataclass
class Command:
    command_type: str  # STORE, RETRIEVE
    slot_name: str
    flavor: Optional[str] = None
    batch_uuid: Optional[str] = None


class MainController:
    """
    Main controller for the STF Digital Twin.
    Implements FSM logic, translates high-level commands to hardware instructions,
    and enforces safety interlocks.
    """
    
    def __init__(self):
        self.state = ControllerState.IDLE
        self.current_command: Optional[Command] = None
        self.hardware_positions: Dict[str, HardwarePosition] = {}
        self.mqtt_client: Optional[mqtt.Client] = None
        self.http_client: Optional[httpx.AsyncClient] = None
        self.running = False
        
        # Safety tracking
        self.collision_prevention_active = False
        self.emergency_stop_active = False
        
        # Energy tracking
        self.total_energy_joules = 0.0
        
        # Command queue
        self.command_queue: List[Command] = []
    
    def setup_mqtt(self):
        """Initialize MQTT client"""
        if not MQTT_AVAILABLE:
            return
        
        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="stf_controller")
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_message = self._on_mqtt_message
        
        try:
            self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.mqtt_client.loop_start()
            print(f"[Controller] Connected to MQTT broker")
        except Exception as e:
            print(f"[Controller] MQTT connection failed: {e}")
            self.mqtt_client = None
    
    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties=None):
        """
        MQTT connection callback handler for paho-mqtt v2.x.

        Establishes subscription to hardware status and command topics upon successful connection.

        Topics subscribed:
            - stf/hbw/status: High-Bay Warehouse (HBW) status updates
            - stf/vgr/status: Vacuum Gripper Robot (VGR) status updates
            - stf/conveyor/status: Conveyor system status updates
            - stf/global/cmd/#: Global command topic (wildcard subscription for all command subtopics)

        Args:
            client: MQTT client instance
            userdata: User-defined data passed to callbacks
            flags: Response flags sent by broker
            reason_code: Connection result code (0 or "Success" indicates successful connection)
            properties: MQTT v5.0 properties (optional)

        Returns:
            None
        """
        """MQTT connection callback (paho-mqtt v2.x compatible)"""
        if reason_code == 0 or str(reason_code) == "Success":
            # Subscribe to hardware status topics
            topics = [
                "stf/hbw/status",
                "stf/vgr/status",
                "stf/conveyor/status",
                "stf/global/cmd/#",
            ]
            for topic in topics:
                client.subscribe(topic)
                print(f"[Controller] Subscribed to {topic}")
    
    def _on_mqtt_message(self, client, userdata, msg):
        """Handle incoming MQTT messages"""
        try:
            payload = json.loads(msg.payload.decode())
            topic = msg.topic
            
            if "/status" in topic:
                self._update_hardware_position(payload)
            elif "emergency_stop" in topic:
                self._handle_emergency_stop()
            elif "store" in topic:
                self._queue_store_command(payload)
            elif "retrieve" in topic:
                self._queue_retrieve_command(payload)
                
        except json.JSONDecodeError:
            print(f"[Controller] Invalid JSON in message")
        except Exception as e:
            print(f"[Controller] Error handling message: {e}")
    
    def _update_hardware_position(self, payload: dict):
        """Update tracked hardware position"""
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
        """Handle emergency stop command"""
        self.emergency_stop_active = True
        self.state = ControllerState.EMERGENCY_STOP
        
        # Send stop commands to all hardware
        if self.mqtt_client:
            for device in ["hbw", "vgr", "conveyor"]:
                self.mqtt_client.publish(f"stf/{device}/cmd/stop", json.dumps({"action": "stop"}))
        
        print("[Controller] EMERGENCY STOP ACTIVATED")
    
    def _queue_store_command(self, payload: dict):
        """Queue a store command"""
        slot_name = payload.get("slot_name")
        flavor = payload.get("flavor", "CHOCO")
        
        if slot_name and slot_name in SLOT_COORDINATES:
            cmd = Command(
                command_type="STORE",
                slot_name=slot_name,
                flavor=flavor,
            )
            self.command_queue.append(cmd)
            print(f"[Controller] Queued STORE command for {slot_name}")
    
    def _queue_retrieve_command(self, payload: dict):
        """Queue a retrieve command"""
        slot_name = payload.get("slot_name")
        
        if slot_name and slot_name in SLOT_COORDINATES:
            cmd = Command(
                command_type="RETRIEVE",
                slot_name=slot_name,
            )
            self.command_queue.append(cmd)
            print(f"[Controller] Queued RETRIEVE command for {slot_name}")
    
    def _check_collision(self, target_x: float, target_y: float, device_id: str) -> bool:
        """
        Check if moving to target position would cause collision.
        Returns True if collision detected (movement should be blocked).
        """
        for other_id, pos in self.hardware_positions.items():
            if other_id == device_id:
                continue
            
            # Check if other device is within safety distance
            distance = ((pos.x - target_x) ** 2 + (pos.y - target_y) ** 2) ** 0.5
            if distance < 50:  # Safety distance in mm
                print(f"[Controller] COLLISION PREVENTION: {device_id} blocked from ({target_x}, {target_y})")
                self.collision_prevention_active = True
                return True
        
        self.collision_prevention_active = False
        return False
    
    def _send_move_command(self, device_id: str, x: float, y: float):
        """Send move command to hardware via MQTT"""
        if self._check_collision(x, y, device_id):
            print(f"[Controller] Move blocked due to collision prevention")
            return False
        
        if self.mqtt_client:
            topic = f"stf/{device_id.lower()}/cmd/move"
            payload = {"targetX": x, "targetY": y}
            self.mqtt_client.publish(topic, json.dumps(payload))
            print(f"[Controller] Sent move command to {device_id}: ({x}, {y})")
            return True
        return False
    
    def _send_gripper_command(self, device_id: str, action: str):
        """Send gripper command to hardware via MQTT"""
        if self.mqtt_client:
            topic = f"stf/{device_id.lower()}/cmd/gripper"
            payload = {"action": action}
            self.mqtt_client.publish(topic, json.dumps(payload))
            print(f"[Controller] Sent gripper {action} to {device_id}")
    
    async def _execute_store_command(self, cmd: Command):
        """Execute a store command through FSM states"""
        target_coords = SLOT_COORDINATES.get(cmd.slot_name)
        if not target_coords:
            print(f"[Controller] Invalid slot: {cmd.slot_name}")
            return
        
        target_x, target_y = target_coords
        
        # State: MOVING_TO_PICKUP
        self.state = ControllerState.MOVING_TO_PICKUP
        print(f"[Controller] State: MOVING_TO_PICKUP")
        
        # Move HBW to pickup zone
        self._send_move_command("HBW", 25, 25)
        await asyncio.sleep(2)  # Wait for movement
        
        # State: PICKING
        self.state = ControllerState.PICKING
        print(f"[Controller] State: PICKING")
        
        self._send_gripper_command("HBW", "close")
        await asyncio.sleep(0.5)
        
        # State: MOVING_TO_SLOT
        self.state = ControllerState.MOVING_TO_SLOT
        print(f"[Controller] State: MOVING_TO_SLOT ({cmd.slot_name})")
        
        self._send_move_command("HBW", target_x, target_y)
        await asyncio.sleep(3)  # Wait for movement
        
        # State: PLACING
        self.state = ControllerState.PLACING
        print(f"[Controller] State: PLACING")
        
        self._send_gripper_command("HBW", "open")
        await asyncio.sleep(0.5)
        
        # Return to idle
        self.state = ControllerState.IDLE
        print(f"[Controller] STORE complete for {cmd.slot_name}")
        
        # Log to API
        await self._log_command_completion(cmd)
    
    async def _execute_retrieve_command(self, cmd: Command):
        """Execute a retrieve command through FSM states"""
        target_coords = SLOT_COORDINATES.get(cmd.slot_name)
        if not target_coords:
            print(f"[Controller] Invalid slot: {cmd.slot_name}")
            return
        
        target_x, target_y = target_coords
        
        # State: MOVING_TO_SLOT
        self.state = ControllerState.MOVING_TO_SLOT
        print(f"[Controller] State: MOVING_TO_SLOT ({cmd.slot_name})")
        
        self._send_move_command("HBW", target_x, target_y)
        await asyncio.sleep(3)
        
        # State: RETRIEVING
        self.state = ControllerState.RETRIEVING
        print(f"[Controller] State: RETRIEVING")
        
        self._send_gripper_command("HBW", "close")
        await asyncio.sleep(0.5)
        
        # State: MOVING_TO_DROPOFF
        self.state = ControllerState.MOVING_TO_DROPOFF
        print(f"[Controller] State: MOVING_TO_DROPOFF")
        
        self._send_move_command("HBW", 375, 375)
        await asyncio.sleep(3)
        
        # Release
        self._send_gripper_command("HBW", "open")
        await asyncio.sleep(0.5)
        
        # Return to idle
        self.state = ControllerState.IDLE
        print(f"[Controller] RETRIEVE complete for {cmd.slot_name}")
        
        await self._log_command_completion(cmd)
    
    async def _log_command_completion(self, cmd: Command):
        """Log command completion to API"""
        if not self.http_client:
            return
        
        try:
            await self.http_client.post(
                f"{API_URL}/system/log",
                params={
                    "level": "INFO",
                    "source": "CONTROLLER",
                    "message": f"Completed {cmd.command_type} for {cmd.slot_name}",
                }
            )
        except Exception as e:
            print(f"[Controller] API log error: {e}")
    
    async def _process_command_queue(self):
        """Process commands from the queue"""
        if self.state != ControllerState.IDLE:
            return
        
        if self.emergency_stop_active:
            return
        
        if not self.command_queue:
            return
        
        cmd = self.command_queue.pop(0)
        self.current_command = cmd
        
        if cmd.command_type == "STORE":
            await self._execute_store_command(cmd)
        elif cmd.command_type == "RETRIEVE":
            await self._execute_retrieve_command(cmd)
        
        self.current_command = None
    
    async def _sync_with_api(self):
        """Sync controller state with API"""
        if not self.http_client:
            return
        
        try:
            # Get pending commands from API
            response = await self.http_client.get(f"{API_URL}/dashboard/data")
            if response.status_code == 200:
                data = response.json()
                # Update hardware positions from API
                for hw in data.get("hardware", []):
                    self.hardware_positions[hw["device_id"]] = HardwarePosition(
                        device_id=hw["device_id"],
                        x=hw["current_x"],
                        y=hw["current_y"],
                        z=hw["current_z"],
                        status=hw["status"],
                    )
        except Exception as e:
            print(f"[Controller] API sync error: {e}")
    
    async def run(self):
        """Main controller loop"""
        self.running = True
        self.setup_mqtt()
        
        async with httpx.AsyncClient() as client:
            self.http_client = client
            
            print("[Controller] Starting main loop")
            print(f"[Controller] API URL: {API_URL}")
            
            while self.running:
                try:
                    # Sync with API
                    await self._sync_with_api()
                    
                    # Process command queue
                    await self._process_command_queue()
                    
                    # Status update
                    if self.state != ControllerState.IDLE:
                        print(f"[Controller] Current state: {self.state.name}")
                    
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    print(f"[Controller] Error in main loop: {e}")
                    self.state = ControllerState.ERROR
                    await asyncio.sleep(1)
        
        # Cleanup
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
    
    def stop(self):
        """Stop the controller"""
        self.running = False


async def main():
    """Run the main controller"""
    print("=" * 60)
    print("STF Digital Twin - Main Controller")
    print("=" * 60)
    print(f"API URL: {API_URL}")
    print(f"MQTT Broker: {MQTT_BROKER}:{MQTT_PORT}")
    print("=" * 60)
    
    controller = MainController()
    
    try:
        await controller.run()
    except KeyboardInterrupt:
        print("\nShutting down controller...")
        controller.stop()


if __name__ == "__main__":
    asyncio.run(main())
