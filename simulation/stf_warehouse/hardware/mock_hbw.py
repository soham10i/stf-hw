"""
STF Digital Twin - Mock High-Bay Warehouse (HBW) Hardware Simulation
AsyncIO-based physics simulation at 10Hz with MQTT communication
"""

import asyncio
import json
import logging
import signal
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("MockHBW")

# Import configuration
sys.path.insert(0, str(__file__).rsplit("/", 3)[0])
from stf_warehouse.config import (
    API_BASE_URL,
    MQTT_BROKER,
    MQTT_PORT,
    MQTTTopics,
    SimulationConfig,
    EnergyConfig,
    HardwareStatus,
    Devices,
)

# Try to import MQTT library
try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    logger.warning("paho-mqtt not installed. Running in HTTP-only mode.")
    MQTT_AVAILABLE = False


@dataclass
class HBWState:
    """Current state of the HBW robot"""
    x_pos: float = 0.0
    y_pos: float = 0.0
    target_x: Optional[float] = None
    target_y: Optional[float] = None
    status: str = HardwareStatus.IDLE
    gripper_closed: bool = False
    last_update: float = field(default_factory=time.time)
    
    @property
    def is_moving(self) -> bool:
        return self.target_x is not None or self.target_y is not None
    
    def to_dict(self) -> dict:
        return {
            "deviceId": Devices.HBW,
            "x": self.x_pos,
            "y": self.y_pos,
            "targetX": self.target_x,
            "targetY": self.target_y,
            "moving": self.is_moving,
            "status": self.status,
            "gripperClosed": self.gripper_closed,
            "timestamp": time.time(),
        }


class MockHBW:
    """
    Mock High-Bay Warehouse Robot Simulation
    
    Simulates physics at 10Hz:
    - Responds to MQTT movement commands
    - Publishes telemetry status
    - Communicates with backend API for state persistence
    """
    
    def __init__(self):
        self.state = HBWState()
        self.config = SimulationConfig()
        self.energy_config = EnergyConfig()
        self.running = False
        self.mqtt_client: Optional[mqtt.Client] = None
        self.http_client: Optional[httpx.AsyncClient] = None
        self.tick_count = 0
        self.total_energy = 0.0
        
    async def start(self):
        """Start the simulation"""
        logger.info("Starting Mock HBW Simulation...")
        self.running = True
        
        # Initialize HTTP client
        self.http_client = httpx.AsyncClient(timeout=10.0)
        
        # Initialize MQTT if available
        if MQTT_AVAILABLE:
            self._setup_mqtt()
        
        # Run the main simulation loop
        try:
            await self._simulation_loop()
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the simulation"""
        logger.info("Stopping Mock HBW Simulation...")
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
            # Subscribe to command topics
            client.subscribe(MQTTTopics.HBW_CMD_MOVE_X)
            client.subscribe(MQTTTopics.HBW_CMD_MOVE_Y)
            client.subscribe(MQTTTopics.HBW_CMD_MOVE)
            client.subscribe(MQTTTopics.HBW_CMD_GRIPPER)
            client.subscribe(MQTTTopics.GLOBAL_REQ_RESET)
            logger.info("Subscribed to HBW command topics")
        else:
            logger.error(f"MQTT connection failed with code: {reason_code}")
    
    def _on_mqtt_message(self, client, userdata, msg):
        """MQTT message callback"""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode())
            logger.debug(f"Received MQTT message on {topic}: {payload}")
            
            if topic == MQTTTopics.HBW_CMD_MOVE_X:
                self._handle_move_x(payload)
            elif topic == MQTTTopics.HBW_CMD_MOVE_Y:
                self._handle_move_y(payload)
            elif topic == MQTTTopics.HBW_CMD_MOVE:
                self._handle_move(payload)
            elif topic == MQTTTopics.HBW_CMD_GRIPPER:
                self._handle_gripper(payload)
            elif topic == MQTTTopics.GLOBAL_REQ_RESET:
                self._handle_reset()
                
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in MQTT message: {e}")
        except Exception as e:
            logger.error(f"Error handling MQTT message: {e}")
    
    def _handle_move_x(self, payload: dict):
        """Handle X-axis movement command"""
        target = payload.get("target")
        if target is not None:
            target = max(self.config.MIN_POSITION, min(self.config.MAX_POSITION, float(target)))
            self.state.target_x = target
            self.state.status = HardwareStatus.MOVING
            logger.info(f"Moving X to {target}")
    
    def _handle_move_y(self, payload: dict):
        """Handle Y-axis movement command"""
        target = payload.get("target")
        if target is not None:
            target = max(self.config.MIN_POSITION, min(self.config.MAX_POSITION, float(target)))
            self.state.target_y = target
            self.state.status = HardwareStatus.MOVING
            logger.info(f"Moving Y to {target}")
    
    def _handle_move(self, payload: dict):
        """Handle combined X,Y movement command"""
        target_x = payload.get("targetX") or payload.get("target_x")
        target_y = payload.get("targetY") or payload.get("target_y")
        
        if target_x is not None:
            self.state.target_x = max(self.config.MIN_POSITION, min(self.config.MAX_POSITION, float(target_x)))
        if target_y is not None:
            self.state.target_y = max(self.config.MIN_POSITION, min(self.config.MAX_POSITION, float(target_y)))
        
        if self.state.target_x is not None or self.state.target_y is not None:
            self.state.status = HardwareStatus.MOVING
            logger.info(f"Moving to ({self.state.target_x}, {self.state.target_y})")
    
    def _handle_gripper(self, payload: dict):
        """Handle gripper command"""
        action = payload.get("action", "").lower()
        if action == "close":
            self.state.gripper_closed = True
            logger.info("Gripper closed")
        elif action == "open":
            self.state.gripper_closed = False
            logger.info("Gripper opened")
    
    def _handle_reset(self):
        """Handle reset command"""
        self.state = HBWState()
        self.total_energy = 0.0
        logger.info("HBW reset to initial state")
    
    async def _simulation_loop(self):
        """Main physics simulation loop at 10Hz"""
        logger.info(f"Starting simulation loop at {self.config.TICK_RATE_HZ}Hz")
        
        while self.running:
            start_time = time.time()
            
            # Update physics
            self._update_physics()
            
            # Calculate energy consumption
            self._calculate_energy()
            
            # Publish telemetry
            await self._publish_telemetry()
            
            # Update backend state (every 10 ticks = 1 second)
            if self.tick_count % 10 == 0:
                await self._update_backend_state()
            
            self.tick_count += 1
            
            # Sleep to maintain tick rate
            elapsed = time.time() - start_time
            sleep_time = max(0, self.config.TICK_INTERVAL_S - elapsed)
            await asyncio.sleep(sleep_time)
    
    def _update_physics(self):
        """Update position based on physics simulation"""
        moved = False
        
        # Update X position
        if self.state.target_x is not None:
            diff_x = self.state.target_x - self.state.x_pos
            if abs(diff_x) <= self.config.POSITION_TOLERANCE:
                self.state.x_pos = self.state.target_x
                self.state.target_x = None
            else:
                direction = 1 if diff_x > 0 else -1
                step = min(abs(diff_x), self.config.MOVEMENT_SPEED)
                self.state.x_pos += direction * step
                moved = True
        
        # Update Y position
        if self.state.target_y is not None:
            diff_y = self.state.target_y - self.state.y_pos
            if abs(diff_y) <= self.config.POSITION_TOLERANCE:
                self.state.y_pos = self.state.target_y
                self.state.target_y = None
            else:
                direction = 1 if diff_y > 0 else -1
                step = min(abs(diff_y), self.config.MOVEMENT_SPEED)
                self.state.y_pos += direction * step
                moved = True
        
        # Update status
        if not moved and self.state.target_x is None and self.state.target_y is None:
            if self.state.status == HardwareStatus.MOVING:
                self.state.status = HardwareStatus.IDLE
                logger.info(f"Arrived at position ({self.state.x_pos}, {self.state.y_pos})")
        
        self.state.last_update = time.time()
    
    def _calculate_energy(self):
        """Calculate energy consumption for this tick"""
        if self.state.is_moving:
            power = self.energy_config.MOVING_POWER_W
        else:
            power = self.energy_config.IDLE_POWER_W
        
        # Energy = Power * Time (in Watt-seconds)
        energy = power * self.config.TICK_INTERVAL_S
        self.total_energy += energy
    
    async def _publish_telemetry(self):
        """Publish telemetry via MQTT"""
        if self.mqtt_client and self.mqtt_client.is_connected():
            telemetry = self.state.to_dict()
            self.mqtt_client.publish(
                MQTTTopics.HBW_STATUS,
                json.dumps(telemetry),
                qos=0
            )
    
    async def _update_backend_state(self):
        """Update hardware state in the backend via HTTP API"""
        if not self.http_client:
            return
        
        try:
            # Update hardware state
            payload = {
                "deviceId": Devices.HBW,
                "currentPositionX": self.state.x_pos,
                "currentPositionY": self.state.y_pos,
                "targetPositionX": self.state.target_x,
                "targetPositionY": self.state.target_y,
                "status": self.state.status,
            }
            
            response = await self.http_client.post(
                f"{API_BASE_URL}/hardware.updateState",
                json=payload
            )
            
            if response.status_code != 200:
                logger.debug(f"Backend update response: {response.status_code}")
            
            # Record telemetry
            telemetry_payload = {
                "deviceId": Devices.HBW,
                "positionX": self.state.x_pos,
                "positionY": self.state.y_pos,
                "isMoving": self.state.is_moving,
                "speed": self.config.MOVEMENT_SPEED if self.state.is_moving else 0,
            }
            
            await self.http_client.post(
                f"{API_BASE_URL}/telemetry.record",
                json=telemetry_payload
            )
            
            # Record energy consumption (every 10 seconds)
            if self.tick_count % 100 == 0:
                energy_payload = {
                    "deviceId": Devices.HBW,
                    "energyConsumed": self.total_energy / 3600,  # Convert to Wh
                    "voltage": self.energy_config.VOLTAGE_V,
                    "current": (self.energy_config.MOVING_POWER_W if self.state.is_moving 
                               else self.energy_config.IDLE_POWER_W) / self.energy_config.VOLTAGE_V,
                }
                
                await self.http_client.post(
                    f"{API_BASE_URL}/energy.record",
                    json=energy_payload
                )
                
        except httpx.RequestError as e:
            logger.debug(f"Failed to update backend: {e}")
        except Exception as e:
            logger.error(f"Error updating backend: {e}")
    
    def set_target(self, x: Optional[float] = None, y: Optional[float] = None):
        """Programmatically set movement target"""
        if x is not None:
            self.state.target_x = max(self.config.MIN_POSITION, min(self.config.MAX_POSITION, x))
        if y is not None:
            self.state.target_y = max(self.config.MIN_POSITION, min(self.config.MAX_POSITION, y))
        
        if self.state.target_x is not None or self.state.target_y is not None:
            self.state.status = HardwareStatus.MOVING


async def main():
    """Main entry point"""
    hbw = MockHBW()
    
    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(hbw.stop()))
    
    await hbw.start()


if __name__ == "__main__":
    asyncio.run(main())
