"""
STF Digital Twin - Mock HBW (High-Bay Warehouse) Hardware Simulation
AsyncIO-based physics simulation at 10Hz with MQTT and FastAPI integration
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

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

# Physics constants
TICK_RATE = 10  # Hz
TICK_INTERVAL = 1.0 / TICK_RATE
MOVEMENT_SPEED = 10  # units per tick
POSITION_TOLERANCE = 1.0
MAX_POSITION = 500
MIN_POSITION = 0


class HardwareStatus(Enum):
    IDLE = "IDLE"
    MOVING = "MOVING"
    ERROR = "ERROR"
    MAINTENANCE = "MAINTENANCE"


@dataclass
class Position:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass
class HardwareState:
    device_id: str
    position: Position
    target: Optional[Position]
    status: HardwareStatus
    gripper_closed: bool = False
    last_error: Optional[str] = None


class MockHBW:
    """
    Mock High-Bay Warehouse hardware simulation.
    Simulates physics at 10Hz, responds to MQTT commands,
    and syncs state with FastAPI backend.
    """
    
    def __init__(self, device_id: str = "HBW"):
        self.device_id = device_id
        self.state = HardwareState(
            device_id=device_id,
            position=Position(0, 0, 0),
            target=None,
            status=HardwareStatus.IDLE,
        )
        self.running = False
        self.mqtt_client: Optional[mqtt.Client] = None
        self.http_client: Optional[httpx.AsyncClient] = None
        self.last_api_sync = 0
        self.api_sync_interval = 1.0  # Sync with API every second
        
        # Energy tracking
        self.energy_joules = 0.0
        self.idle_power = 5.0  # Watts when idle
        self.moving_power = 50.0  # Watts when moving
    
    def setup_mqtt(self):
        """Initialize MQTT client"""
        if not MQTT_AVAILABLE:
            return
        
        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"mock_{self.device_id}")
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_message = self._on_mqtt_message
        
        try:
            self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.mqtt_client.loop_start()
            print(f"[{self.device_id}] Connected to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
        except Exception as e:
            print(f"[{self.device_id}] MQTT connection failed: {e}")
            self.mqtt_client = None
    
    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties=None):
        """MQTT connection callback (paho-mqtt v2.x compatible)"""
        if reason_code == 0 or str(reason_code) == "Success":
            # Subscribe to command topics
            topics = [
                f"stf/{self.device_id.lower()}/cmd/move_x",
                f"stf/{self.device_id.lower()}/cmd/move_y",
                f"stf/{self.device_id.lower()}/cmd/move",
                f"stf/{self.device_id.lower()}/cmd/gripper",
                "stf/global/req/reset",
            ]
            for topic in topics:
                client.subscribe(topic)
                print(f"[{self.device_id}] Subscribed to {topic}")
    
    def _on_mqtt_message(self, client, userdata, msg):
        """Handle incoming MQTT messages"""
        try:
            payload = json.loads(msg.payload.decode())
            topic = msg.topic
            
            if "move_x" in topic:
                self._handle_move_x(payload)
            elif "move_y" in topic:
                self._handle_move_y(payload)
            elif "move" in topic:
                self._handle_move(payload)
            elif "gripper" in topic:
                self._handle_gripper(payload)
            elif "reset" in topic:
                self._handle_reset()
                
        except json.JSONDecodeError:
            print(f"[{self.device_id}] Invalid JSON in message")
        except Exception as e:
            print(f"[{self.device_id}] Error handling message: {e}")
    
    def _handle_move_x(self, payload: dict):
        """Handle X-axis move command"""
        target_x = payload.get("target", 0)
        target_x = max(MIN_POSITION, min(MAX_POSITION, target_x))
        
        if self.state.target is None:
            self.state.target = Position(target_x, self.state.position.y, self.state.position.z)
        else:
            self.state.target.x = target_x
        
        self.state.status = HardwareStatus.MOVING
        print(f"[{self.device_id}] Moving X to {target_x}")
    
    def _handle_move_y(self, payload: dict):
        """Handle Y-axis move command"""
        target_y = payload.get("target", 0)
        target_y = max(MIN_POSITION, min(MAX_POSITION, target_y))
        
        if self.state.target is None:
            self.state.target = Position(self.state.position.x, target_y, self.state.position.z)
        else:
            self.state.target.y = target_y
        
        self.state.status = HardwareStatus.MOVING
        print(f"[{self.device_id}] Moving Y to {target_y}")
    
    def _handle_move(self, payload: dict):
        """Handle combined X/Y move command"""
        target_x = payload.get("targetX", payload.get("x", self.state.position.x))
        target_y = payload.get("targetY", payload.get("y", self.state.position.y))
        
        target_x = max(MIN_POSITION, min(MAX_POSITION, target_x))
        target_y = max(MIN_POSITION, min(MAX_POSITION, target_y))
        
        self.state.target = Position(target_x, target_y, self.state.position.z)
        self.state.status = HardwareStatus.MOVING
        print(f"[{self.device_id}] Moving to ({target_x}, {target_y})")
    
    def _handle_gripper(self, payload: dict):
        """Handle gripper command"""
        action = payload.get("action", "").lower()
        if action == "close":
            self.state.gripper_closed = True
            print(f"[{self.device_id}] Gripper closed")
        elif action == "open":
            self.state.gripper_closed = False
            print(f"[{self.device_id}] Gripper opened")
    
    def _handle_reset(self):
        """Handle reset command"""
        self.state.target = Position(0, 0, 0)
        self.state.status = HardwareStatus.MOVING
        print(f"[{self.device_id}] Resetting to home position")
    
    def _update_physics(self, dt: float):
        """Update physics simulation"""
        if self.state.target is None:
            # Calculate energy for idle state
            self.energy_joules += self.idle_power * dt
            return
        
        pos = self.state.position
        target = self.state.target
        
        # Calculate distance to target
        dx = target.x - pos.x
        dy = target.y - pos.y
        dz = target.z - pos.z
        
        distance = (dx**2 + dy**2 + dz**2) ** 0.5
        
        if distance <= POSITION_TOLERANCE:
            # Arrived at target
            pos.x = target.x
            pos.y = target.y
            pos.z = target.z
            self.state.target = None
            self.state.status = HardwareStatus.IDLE
            print(f"[{self.device_id}] Arrived at ({pos.x}, {pos.y})")
            
            # Idle energy
            self.energy_joules += self.idle_power * dt
        else:
            # Move towards target
            move_distance = min(MOVEMENT_SPEED, distance)
            ratio = move_distance / distance
            
            pos.x += dx * ratio
            pos.y += dy * ratio
            pos.z += dz * ratio
            
            # Moving energy
            self.energy_joules += self.moving_power * dt
    
    def _publish_status(self):
        """Publish status to MQTT"""
        if not self.mqtt_client:
            return
        
        status_data = {
            "device_id": self.device_id,
            "x": self.state.position.x,
            "y": self.state.position.y,
            "z": self.state.position.z,
            "status": self.state.status.value,
            "gripper_closed": self.state.gripper_closed,
            "moving": self.state.status == HardwareStatus.MOVING,
            "timestamp": time.time(),
        }
        
        topic = f"stf/{self.device_id.lower()}/status"
        self.mqtt_client.publish(topic, json.dumps(status_data))
    
    async def _sync_with_api(self):
        """Sync state with FastAPI backend"""
        if not self.http_client:
            return
        
        try:
            # Update hardware state
            await self.http_client.post(
                f"{API_URL}/hardware/state",
                json={
                    "device_id": self.device_id,
                    "x": self.state.position.x,
                    "y": self.state.position.y,
                    "z": self.state.position.z,
                    "status": self.state.status.value,
                }
            )
            
            # Record telemetry
            await self.http_client.post(
                f"{API_URL}/telemetry",
                json={
                    "device_id": self.device_id,
                    "metric_name": "position_x",
                    "metric_value": self.state.position.x,
                    "unit": "mm",
                }
            )
            
            # Record energy
            await self.http_client.post(
                f"{API_URL}/energy",
                json={
                    "device_id": self.device_id,
                    "joules": self.energy_joules,
                    "voltage": 24.0,
                }
            )
            
        except Exception as e:
            print(f"[{self.device_id}] API sync error: {e}")
    
    async def run(self):
        """Main simulation loop"""
        self.running = True
        self.setup_mqtt()
        
        async with httpx.AsyncClient() as client:
            self.http_client = client
            
            print(f"[{self.device_id}] Starting simulation at {TICK_RATE}Hz")
            
            last_tick = time.time()
            
            while self.running:
                current_time = time.time()
                dt = current_time - last_tick
                
                # Update physics
                self._update_physics(dt)
                
                # Publish MQTT status every tick
                self._publish_status()
                
                # Sync with API periodically
                if current_time - self.last_api_sync >= self.api_sync_interval:
                    await self._sync_with_api()
                    self.last_api_sync = current_time
                
                last_tick = current_time
                
                # Wait for next tick
                elapsed = time.time() - current_time
                sleep_time = max(0, TICK_INTERVAL - elapsed)
                await asyncio.sleep(sleep_time)
        
        # Cleanup
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
    
    def stop(self):
        """Stop the simulation"""
        self.running = False


class MockConveyor(MockHBW):
    """Mock Conveyor simulation"""
    
    def __init__(self):
        super().__init__(device_id="CONVEYOR")
        self.belt_position = 0.0
        self.belt_speed = 5.0  # units per tick
        self.belt_running = False
    
    def _on_mqtt_message(self, client, userdata, msg):
        """Handle conveyor-specific messages"""
        try:
            payload = json.loads(msg.payload.decode())
            topic = msg.topic
            
            if "start" in topic:
                self.belt_running = True
                self.state.status = HardwareStatus.MOVING
                print(f"[{self.device_id}] Belt started")
            elif "stop" in topic:
                self.belt_running = False
                self.state.status = HardwareStatus.IDLE
                print(f"[{self.device_id}] Belt stopped")
            else:
                super()._on_mqtt_message(client, userdata, msg)
                
        except Exception as e:
            print(f"[{self.device_id}] Error: {e}")
    
    def _update_physics(self, dt: float):
        """Update conveyor physics"""
        if self.belt_running:
            self.belt_position += self.belt_speed
            self.state.position.x = self.belt_position % MAX_POSITION
            self.energy_joules += self.moving_power * dt
        else:
            self.energy_joules += self.idle_power * dt


class MockVGR(MockHBW):
    """Mock VGR (Vacuum Gripper Robot) simulation"""
    
    def __init__(self):
        super().__init__(device_id="VGR")
        self.vacuum_active = False
    
    def _on_mqtt_message(self, client, userdata, msg):
        """Handle VGR-specific messages"""
        try:
            payload = json.loads(msg.payload.decode())
            topic = msg.topic
            
            if "vacuum" in topic:
                action = payload.get("action", "").lower()
                self.vacuum_active = action == "on"
                print(f"[{self.device_id}] Vacuum {'activated' if self.vacuum_active else 'deactivated'}")
            else:
                super()._on_mqtt_message(client, userdata, msg)
                
        except Exception as e:
            print(f"[{self.device_id}] Error: {e}")


async def main():
    """Run all mock hardware simulations"""
    print("=" * 60)
    print("STF Digital Twin - Mock Hardware Simulation")
    print("=" * 60)
    print(f"API URL: {API_URL}")
    print(f"MQTT Broker: {MQTT_BROKER}:{MQTT_PORT}")
    print(f"Tick Rate: {TICK_RATE}Hz")
    print("=" * 60)
    
    # Create mock devices
    hbw = MockHBW()
    vgr = MockVGR()
    conveyor = MockConveyor()
    
    # Run all simulations concurrently
    try:
        await asyncio.gather(
            hbw.run(),
            vgr.run(),
            conveyor.run(),
        )
    except KeyboardInterrupt:
        print("\nShutting down simulations...")
        hbw.stop()
        vgr.stop()
        conveyor.stop()


if __name__ == "__main__":
    asyncio.run(main())
