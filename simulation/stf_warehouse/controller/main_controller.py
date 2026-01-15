"""
STF Digital Twin - Main Controller
Finite State Machine logic, command translation, and safety interlocks
"""

import asyncio
import json
import logging
import signal
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any

import httpx

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Controller")

# Import configuration
sys.path.insert(0, str(__file__).rsplit("/", 3)[0])
from stf_warehouse.config import (
    API_BASE_URL,
    MQTT_BROKER,
    MQTT_PORT,
    MQTTTopics,
    SLOT_COORDINATES,
    SimulationConfig,
    EnergyConfig,
    HardwareStatus,
    CommandStatus,
    Devices,
    get_slot_coordinates,
)

# Try to import MQTT library
try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    logger.warning("paho-mqtt not installed. Running in HTTP-only mode.")
    MQTT_AVAILABLE = False


class ControllerState(Enum):
    """Controller FSM states"""
    IDLE = "IDLE"
    RETRIEVING = "RETRIEVING"
    STORING = "STORING"
    MOVING = "MOVING"
    ERROR = "ERROR"
    MAINTENANCE = "MAINTENANCE"


@dataclass
class HardwareSnapshot:
    """Snapshot of hardware state"""
    device_id: str
    position_x: float = 0.0
    position_y: float = 0.0
    status: str = HardwareStatus.IDLE
    is_locked: bool = False
    last_update: float = field(default_factory=time.time)


@dataclass
class ControllerContext:
    """Controller context and state"""
    state: ControllerState = ControllerState.IDLE
    current_command_id: Optional[int] = None
    target_slot: Optional[str] = None
    hardware_states: Dict[str, HardwareSnapshot] = field(default_factory=dict)
    last_energy_log: float = field(default_factory=time.time)


class SafetyInterlock:
    """
    Safety interlock system for collision prevention
    """
    
    def __init__(self, context: ControllerContext):
        self.context = context
    
    def can_move_hbw(self) -> tuple[bool, str]:
        """Check if HBW can safely move"""
        # Check if conveyor is interacting
        conveyor = self.context.hardware_states.get(Devices.CONVEYOR)
        if conveyor and conveyor.status == HardwareStatus.MOVING:
            return False, "Conveyor is moving - HBW blocked for safety"
        
        # Check if VGR is in HBW zone
        vgr = self.context.hardware_states.get(Devices.VGR)
        if vgr and vgr.status == HardwareStatus.MOVING:
            # Check if VGR is near HBW position
            hbw = self.context.hardware_states.get(Devices.HBW)
            if hbw and self._positions_conflict(hbw, vgr):
                return False, "VGR in conflict zone - HBW blocked for safety"
        
        return True, "OK"
    
    def can_move_conveyor(self) -> tuple[bool, str]:
        """Check if conveyor can safely move"""
        hbw = self.context.hardware_states.get(Devices.HBW)
        if hbw and hbw.status == HardwareStatus.MOVING:
            return False, "HBW is moving - Conveyor blocked for safety"
        
        return True, "OK"
    
    def can_retrieve(self, slot_name: str) -> tuple[bool, str]:
        """Check if retrieval operation is safe"""
        can_move, reason = self.can_move_hbw()
        if not can_move:
            return False, reason
        
        # Additional checks for retrieval
        hbw = self.context.hardware_states.get(Devices.HBW)
        if hbw and hbw.is_locked:
            return False, "HBW is locked by another operation"
        
        return True, "OK"
    
    def can_store(self, slot_name: str) -> tuple[bool, str]:
        """Check if storage operation is safe"""
        can_move, reason = self.can_move_hbw()
        if not can_move:
            return False, reason
        
        return True, "OK"
    
    def _positions_conflict(self, hw1: HardwareSnapshot, hw2: HardwareSnapshot, threshold: float = 50.0) -> bool:
        """Check if two hardware positions conflict"""
        dx = abs(hw1.position_x - hw2.position_x)
        dy = abs(hw1.position_y - hw2.position_y)
        return dx < threshold and dy < threshold


class MainController:
    """
    Main Controller for STF Digital Twin
    
    Responsibilities:
    - Translate high-level commands to low-level hardware instructions
    - Implement safety interlocks for collision prevention
    - Log energy consumption
    - Manage FSM state transitions
    """
    
    def __init__(self):
        self.context = ControllerContext()
        self.safety = SafetyInterlock(self.context)
        self.config = SimulationConfig()
        self.energy_config = EnergyConfig()
        self.running = False
        self.mqtt_client: Optional[mqtt.Client] = None
        self.http_client: Optional[httpx.AsyncClient] = None
        self.tick_count = 0
    
    async def start(self):
        """Start the controller"""
        logger.info("Starting Main Controller...")
        self.running = True
        
        # Initialize HTTP client
        self.http_client = httpx.AsyncClient(timeout=10.0)
        
        # Initialize MQTT if available
        if MQTT_AVAILABLE:
            self._setup_mqtt()
        
        # Run the main control loop
        try:
            await self._control_loop()
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the controller"""
        logger.info("Stopping Main Controller...")
        self.running = False
        
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        
        if self.http_client:
            await self.http_client.aclose()
    
    def _setup_mqtt(self):
        """Setup MQTT client and subscriptions"""
        try:
            self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            self.mqtt_client.on_connect = self._on_mqtt_connect
            self.mqtt_client.on_message = self._on_mqtt_message
            
            logger.info(f"Connecting to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
            self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.mqtt_client.loop_start()
        except Exception as e:
            logger.warning(f"Failed to connect to MQTT broker: {e}")
            self.mqtt_client = None
    
    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        """MQTT connection callback"""
        if reason_code == 0:
            logger.info("Connected to MQTT broker")
            # Subscribe to high-level request topics
            client.subscribe(MQTTTopics.GLOBAL_REQ_RETRIEVE)
            client.subscribe(MQTTTopics.GLOBAL_REQ_STORE)
            client.subscribe(MQTTTopics.GLOBAL_REQ_RESET)
            # Subscribe to hardware status topics
            client.subscribe(MQTTTopics.HBW_STATUS)
            client.subscribe(MQTTTopics.CONVEYOR_STATUS)
            client.subscribe(MQTTTopics.VGR_STATUS)
            logger.info("Subscribed to control topics")
        else:
            logger.error(f"MQTT connection failed with code: {reason_code}")
    
    def _on_mqtt_message(self, client, userdata, msg):
        """MQTT message callback"""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode())
            logger.debug(f"Received message on {topic}: {payload}")
            
            # Handle high-level requests
            if topic == MQTTTopics.GLOBAL_REQ_RETRIEVE:
                asyncio.create_task(self._handle_retrieve_request(payload))
            elif topic == MQTTTopics.GLOBAL_REQ_STORE:
                asyncio.create_task(self._handle_store_request(payload))
            elif topic == MQTTTopics.GLOBAL_REQ_RESET:
                asyncio.create_task(self._handle_reset_request())
            
            # Handle hardware status updates
            elif topic == MQTTTopics.HBW_STATUS:
                self._update_hardware_state(Devices.HBW, payload)
            elif topic == MQTTTopics.CONVEYOR_STATUS:
                self._update_hardware_state(Devices.CONVEYOR, payload)
            elif topic == MQTTTopics.VGR_STATUS:
                self._update_hardware_state(Devices.VGR, payload)
                
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in message: {e}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    def _update_hardware_state(self, device_id: str, payload: dict):
        """Update hardware state from telemetry"""
        self.context.hardware_states[device_id] = HardwareSnapshot(
            device_id=device_id,
            position_x=payload.get("x", 0),
            position_y=payload.get("y", 0),
            status=payload.get("status", HardwareStatus.IDLE),
            last_update=time.time(),
        )
    
    async def _handle_retrieve_request(self, payload: dict):
        """Handle retrieve request from high-level command"""
        slot_name = payload.get("slot")
        if not slot_name:
            logger.error("Retrieve request missing slot name")
            return
        
        logger.info(f"Processing retrieve request for slot {slot_name}")
        
        # Check safety interlock
        can_retrieve, reason = self.safety.can_retrieve(slot_name)
        if not can_retrieve:
            logger.warning(f"Retrieve blocked: {reason}")
            await self._create_alert("COLLISION_PREVENTION", "WARNING", Devices.HBW, reason)
            return
        
        # Get slot coordinates
        try:
            x, y = get_slot_coordinates(slot_name)
        except ValueError as e:
            logger.error(f"Invalid slot: {e}")
            return
        
        # Update controller state
        self.context.state = ControllerState.RETRIEVING
        self.context.target_slot = slot_name
        
        # Send low-level move command
        await self._send_move_command(x, y)
        
        logger.info(f"Sent move command to ({x}, {y}) for slot {slot_name}")
    
    async def _handle_store_request(self, payload: dict):
        """Handle store request from high-level command"""
        slot_name = payload.get("slot")
        if not slot_name:
            logger.error("Store request missing slot name")
            return
        
        logger.info(f"Processing store request for slot {slot_name}")
        
        # Check safety interlock
        can_store, reason = self.safety.can_store(slot_name)
        if not can_store:
            logger.warning(f"Store blocked: {reason}")
            await self._create_alert("COLLISION_PREVENTION", "WARNING", Devices.HBW, reason)
            return
        
        # Get slot coordinates
        try:
            x, y = get_slot_coordinates(slot_name)
        except ValueError as e:
            logger.error(f"Invalid slot: {e}")
            return
        
        # Update controller state
        self.context.state = ControllerState.STORING
        self.context.target_slot = slot_name
        
        # Send low-level move command
        await self._send_move_command(x, y)
        
        logger.info(f"Sent move command to ({x}, {y}) for slot {slot_name}")
    
    async def _handle_reset_request(self):
        """Handle system reset request"""
        logger.info("Processing reset request")
        
        self.context.state = ControllerState.IDLE
        self.context.target_slot = None
        self.context.current_command_id = None
        
        # Send reset command to hardware
        if self.mqtt_client:
            self.mqtt_client.publish(
                MQTTTopics.HBW_CMD_MOVE,
                json.dumps({"targetX": 0, "targetY": 0}),
                qos=1
            )
        
        # Reset via API
        try:
            await self.http_client.post(f"{API_BASE_URL}/maintenance.reset")
        except Exception as e:
            logger.error(f"Failed to reset via API: {e}")
    
    async def _send_move_command(self, x: float, y: float):
        """Send move command to HBW"""
        command = {"targetX": x, "targetY": y}
        
        # Send via MQTT
        if self.mqtt_client and self.mqtt_client.is_connected():
            self.mqtt_client.publish(
                MQTTTopics.HBW_CMD_MOVE,
                json.dumps(command),
                qos=1
            )
        
        # Also update via API
        try:
            await self.http_client.post(
                f"{API_BASE_URL}/hardware.moveHBW",
                json={"targetX": x, "targetY": y}
            )
        except Exception as e:
            logger.debug(f"API move command failed: {e}")
    
    async def _create_alert(self, alert_type: str, severity: str, device_id: Optional[str], message: str):
        """Create an alert via API"""
        try:
            await self.http_client.post(
                f"{API_BASE_URL}/alerts.create",
                json={
                    "alertType": alert_type,
                    "severity": severity,
                    "deviceId": device_id,
                    "message": message,
                }
            )
        except Exception as e:
            logger.error(f"Failed to create alert: {e}")
    
    async def _control_loop(self):
        """Main control loop"""
        logger.info("Starting control loop...")
        
        while self.running:
            start_time = time.time()
            
            # Poll for pending commands from API
            await self._process_pending_commands()
            
            # Check hardware health
            await self._check_hardware_health()
            
            # Log energy periodically (every 10 seconds)
            if time.time() - self.context.last_energy_log > 10:
                await self._log_energy()
                self.context.last_energy_log = time.time()
            
            # Update state based on hardware status
            await self._update_controller_state()
            
            self.tick_count += 1
            
            # Sleep for control loop interval (1 second)
            elapsed = time.time() - start_time
            await asyncio.sleep(max(0, 1.0 - elapsed))
    
    async def _process_pending_commands(self):
        """Process pending commands from the backend"""
        try:
            response = await self.http_client.get(f"{API_BASE_URL}/commands.pending")
            if response.status_code == 200:
                data = response.json()
                commands = data.get("result", {}).get("data", [])
                
                for cmd in commands:
                    await self._execute_command(cmd)
        except Exception as e:
            logger.debug(f"Failed to fetch pending commands: {e}")
    
    async def _execute_command(self, command: dict):
        """Execute a pending command"""
        cmd_type = command.get("commandType")
        cmd_id = command.get("id")
        payload = json.loads(command.get("payload", "{}")) if command.get("payload") else {}
        
        logger.info(f"Executing command {cmd_id}: {cmd_type}")
        
        try:
            if cmd_type == "MOVE_TO_SLOT":
                slot_name = payload.get("slotName")
                if slot_name:
                    x, y = get_slot_coordinates(slot_name)
                    await self._send_move_command(x, y)
            
            elif cmd_type == "RETRIEVE":
                slot_name = payload.get("slotName")
                if slot_name:
                    await self._handle_retrieve_request({"slot": slot_name})
            
            elif cmd_type == "STORE":
                slot_name = payload.get("slotName")
                if slot_name:
                    await self._handle_store_request({"slot": slot_name})
            
            # Update command status
            await self.http_client.post(
                f"{API_BASE_URL}/commands.updateStatus",
                json={"commandId": cmd_id, "status": CommandStatus.EXECUTING}
            )
            
        except Exception as e:
            logger.error(f"Failed to execute command {cmd_id}: {e}")
            await self.http_client.post(
                f"{API_BASE_URL}/commands.updateStatus",
                json={"commandId": cmd_id, "status": CommandStatus.FAILED, "errorMessage": str(e)}
            )
    
    async def _check_hardware_health(self):
        """Check hardware health and create alerts if needed"""
        for device_id, state in self.context.hardware_states.items():
            # Check for stale heartbeat
            if time.time() - state.last_update > 5.0:
                logger.warning(f"Device {device_id} heartbeat timeout")
                await self._create_alert(
                    "HARDWARE_ERROR",
                    "WARNING",
                    device_id,
                    f"No heartbeat from {device_id} for 5 seconds"
                )
            
            # Check for error status
            if state.status == HardwareStatus.ERROR:
                await self._create_alert(
                    "HARDWARE_ERROR",
                    "CRITICAL",
                    device_id,
                    f"Device {device_id} reported error status"
                )
    
    async def _log_energy(self):
        """Log energy consumption for all devices"""
        for device_id, state in self.context.hardware_states.items():
            # Calculate virtual energy based on status
            if state.status == HardwareStatus.MOVING:
                power = self.energy_config.MOVING_POWER_W
            else:
                power = self.energy_config.IDLE_POWER_W
            
            # Energy for 10 seconds in Wh
            energy = (power * 10) / 3600
            
            try:
                await self.http_client.post(
                    f"{API_BASE_URL}/energy.record",
                    json={
                        "deviceId": device_id,
                        "energyConsumed": energy,
                        "voltage": self.energy_config.VOLTAGE_V,
                        "current": power / self.energy_config.VOLTAGE_V,
                    }
                )
            except Exception as e:
                logger.debug(f"Failed to log energy for {device_id}: {e}")
    
    async def _update_controller_state(self):
        """Update controller state based on hardware status"""
        hbw = self.context.hardware_states.get(Devices.HBW)
        
        if not hbw:
            return
        
        # Check if current operation is complete
        if self.context.state in (ControllerState.RETRIEVING, ControllerState.STORING, ControllerState.MOVING):
            if hbw.status == HardwareStatus.IDLE:
                logger.info(f"Operation complete, returning to IDLE state")
                self.context.state = ControllerState.IDLE
                self.context.target_slot = None
                
                # Mark command as complete
                if self.context.current_command_id:
                    try:
                        await self.http_client.post(
                            f"{API_BASE_URL}/commands.updateStatus",
                            json={"commandId": self.context.current_command_id, "status": CommandStatus.COMPLETED}
                        )
                    except Exception:
                        pass
                    self.context.current_command_id = None


async def main():
    """Main entry point"""
    controller = MainController()
    
    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(controller.stop()))
    
    await controller.start()


if __name__ == "__main__":
    asyncio.run(main())
