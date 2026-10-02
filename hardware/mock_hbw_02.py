import asyncio
import json
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import paho.mqtt.client as mqtt

# --- 1. CONFIGURATION (Aligned with  HiveMQ Broker) ---
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
TICK_RATE = 10  # 10Hz physics simulation
TICK_INTERVAL = 1.0 / TICK_RATE
MOVEMENT_SPEED = 15.0 

class HardwareStatus(Enum):
    IDLE = "IDLE"
    MOVING = "MOVING"
    ERROR = "ERROR"

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

class MockHBW:
    def _init_(self, device_id: str = "HBW"):
        self.device_id = device_id
        self.state = HardwareState(
            device_id=device_id,
            position=Position(0, 0, 0),
            target=None,
            status=HardwareStatus.IDLE,
        )
        self.running = False
        
        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_message = self._on_mqtt_message

    def _on_mqtt_connect(self, client, userdata, flags, rc, props=None):
        print(f">>> [PHYSICS] Connected to Broker: {MQTT_BROKER}")
        # Subscribes to the commands Controller sends
        client.subscribe("stf/hrl/commands")

    def _on_mqtt_message(self, client, userdata, msg):
        cmd = msg.payload.decode().strip().lower()
        print(f"\n[PHYSICS LAYER] Received Command: {cmd}")

        # --- High-Fidelity Logic (Responding to your Controller) ---
        if cmd == "startup":
            print(" -> INITIALIZING: Homing motors and checking electrical draw...")
            self.state.status = HardwareStatus.MOVING
            self.state.target = Position(0, 0, 0)
        
        elif "deliver" in cmd:
            print(" -> DISPATCH: Activating  Gripper (Virtual)...\n Cookie Dispatched")
            self.state.gripper_closed = True
            self.state.status = HardwareStatus.MOVING

    def _update_physics(self, dt: float):
        """Moves the crane toward target (X, Y) at 10Hz i .e 10 times per second"""
        if self.state.status == HardwareStatus.MOVING:
            # Simple physics: increment position until target reached
            
            self.state.position.x += 1.0 # Simulated move
            if self.state.position.x > 50: # Simulated completion
                self.state.status = HardwareStatus.IDLE

    def _publish_status(self):
        """Sends telemetry back to the broker for the dashboard"""
        status_data = {
            "device_id": self.device_id,
            "x": self.state.position.x,
            "y": self.state.position.y,
            "status": self.state.status.value,
            "gripper": "CLOSED" if self.state.gripper_closed else "OPEN",
            "energy_joules": round(time.time() % 100, 2) # Simulated energy
        }
        self.mqtt_client.publish("stf/hrl/telemetry", json.dumps(status_data))

    async def run(self):
        self.running = True
        self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT)
        self.mqtt_client.loop_start()
        
        print(f"[{self.device_id}] Simulation Active at {TICK_RATE}Hz")
        while self.running:
            self._update_physics(TICK_INTERVAL)
            self._publish_status()
            await asyncio.sleep(TICK_INTERVAL)

async def main():
    print("=" * 60)
    print("   STF DIGITAL TWIN - HIGH-FIDELITY PHYSICS SHADOW   ")
    print("=" * 60)
    hbw = MockHBW()
    await hbw.run()

if __name__ == "_main_":
    asyncio.run(main())
    
