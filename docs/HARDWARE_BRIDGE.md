# Hardware Bridge Documentation

This document describes how to connect the STF Digital Twin to real hardware using Node-RED and Revolution Pi (RevPi) industrial controllers.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         STF Digital Twin                                 │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────────┐  │
│  │  Streamlit  │    │   FastAPI   │    │      MySQL Database         │  │
│  │  Dashboard  │◄──►│   + WebSocket│◄──►│  (State, Telemetry, Logs)  │  │
│  └─────────────┘    └──────┬──────┘    └─────────────────────────────┘  │
│                            │                                             │
│                            │ REST API / WebSocket                        │
│                            ▼                                             │
│                    ┌───────────────┐                                     │
│                    │ MQTT Broker   │                                     │
│                    │ (Mosquitto)   │                                     │
│                    └───────┬───────┘                                     │
└────────────────────────────┼────────────────────────────────────────────┘
                             │
                             │ MQTT Topics
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Hardware Bridge                                  │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                        Node-RED                                  │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │    │
│  │  │ MQTT In/Out  │  │ Function     │  │ RevPi DIO/AIO Nodes  │   │    │
│  │  │ Nodes        │◄─┤ Nodes        │◄─┤ (piControl)          │   │    │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘   │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    Revolution Pi (RevPi)                         │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │    │
│  │  │ RevPi Core   │  │ RevPi DIO    │  │ RevPi AIO            │   │    │
│  │  │ (Controller) │◄─┤ (Digital I/O)│◄─┤ (Analog I/O)         │   │    │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘   │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    Physical Hardware                             │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │    │
│  │  │ HBW Motors   │  │ Conveyor     │  │ VGR Pneumatics       │   │    │
│  │  │ (X, Y, Z)    │  │ Belt + Sensors│  │ (Compressor, Valve)  │   │    │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘   │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
```

## MQTT Topic Structure

### Command Topics (Digital Twin → Hardware)

| Topic | Payload | Description |
|-------|---------|-------------|
| `stf/conveyor/cmd/start` | `{"direction": 1}` | Start conveyor (1=forward, -1=reverse) |
| `stf/conveyor/cmd/stop` | `{}` | Stop conveyor |
| `stf/hbw/cmd/move` | `{"x": 100, "y": 200, "z": 50}` | Move HBW to position |
| `stf/hbw/cmd/stop` | `{}` | Stop HBW movement |
| `stf/hbw/cmd/gripper` | `{"close": true}` | Open/close gripper |
| `stf/vgr/cmd/move` | `{"x": 100, "y": 200, "z": 50}` | Move VGR to position |
| `stf/vgr/cmd/stop` | `{}` | Stop VGR movement |
| `stf/vgr/cmd/vacuum` | `{"activate": true}` | Activate/release vacuum |
| `stf/global/req/reset` | `{}` | Reset all hardware |
| `stf/global/req/emergency_stop` | `{}` | Emergency stop all |

### Status Topics (Hardware → Digital Twin)

| Topic | Payload | Description |
|-------|---------|-------------|
| `stf/conveyor/status` | See below | Conveyor state |
| `stf/hbw/status` | See below | HBW state |
| `stf/vgr/status` | See below | VGR state |

#### Conveyor Status Payload
```json
{
  "belt_position_mm": 450.5,
  "belt_position_pct": 45.05,
  "direction": 1,
  "motor": {
    "component_id": "CONV_M1",
    "current_amps": 1.2,
    "voltage": 24.0,
    "health_score": 0.95,
    "is_active": true,
    "phase": "RUNNING"
  },
  "sensors": {
    "L1": false,
    "L2": true,
    "L3": false,
    "L4": false
  }
}
```

#### HBW Status Payload
```json
{
  "device_id": "HBW",
  "x": 150.0,
  "y": 200.0,
  "z": 50.0,
  "status": "MOVING",
  "motors": {
    "X": {"current_amps": 1.5, "health_score": 0.92, "is_active": true},
    "Y": {"current_amps": 1.5, "health_score": 0.88, "is_active": true},
    "Z": {"current_amps": 0.0, "health_score": 0.95, "is_active": false}
  },
  "ref_switch": false,
  "gripper_closed": true,
  "total_power_watts": 72.0
}
```

## Node-RED Integration

### Prerequisites

1. **Node-RED** installed on RevPi or gateway device
2. **node-red-contrib-revpi-nodes** for RevPi I/O access
3. **node-red-contrib-mqtt** for MQTT communication

### Installation on RevPi

```bash
# Install Node-RED
bash <(curl -sL https://raw.githubusercontent.com/node-red/linux-installers/master/deb/update-nodejs-and-nodered)

# Install RevPi nodes
cd ~/.node-red
npm install node-red-contrib-revpi-nodes

# Enable and start Node-RED
sudo systemctl enable nodered
sudo systemctl start nodered
```

### Example Flow: Conveyor Control

```json
[
  {
    "id": "mqtt_conveyor_cmd",
    "type": "mqtt in",
    "topic": "stf/conveyor/cmd/#",
    "broker": "mqtt_broker",
    "name": "Conveyor Commands"
  },
  {
    "id": "parse_conveyor_cmd",
    "type": "function",
    "name": "Parse Command",
    "func": "const topic = msg.topic.split('/');\nconst action = topic[3];\nmsg.action = action;\nmsg.payload = JSON.parse(msg.payload || '{}');\nreturn msg;"
  },
  {
    "id": "conveyor_motor_control",
    "type": "revpi-output",
    "name": "Conveyor Motor",
    "outputpin": "O_1",
    "overwritealiases": true
  },
  {
    "id": "conveyor_direction",
    "type": "revpi-output",
    "name": "Direction Relay",
    "outputpin": "O_2",
    "overwritealiases": true
  }
]
```

### Example Flow: Sensor Reading

```json
[
  {
    "id": "sensor_l1_input",
    "type": "revpi-input",
    "name": "Sensor L1",
    "inputpin": "I_1",
    "debounce": 50
  },
  {
    "id": "sensor_l2_input",
    "type": "revpi-input",
    "name": "Sensor L2",
    "inputpin": "I_2",
    "debounce": 50
  },
  {
    "id": "aggregate_sensors",
    "type": "function",
    "name": "Aggregate Sensors",
    "func": "// Collect sensor states\ncontext.sensors = context.sensors || {};\ncontext.sensors[msg.topic] = msg.payload;\n\n// Publish aggregated state\nmsg.payload = JSON.stringify({\n  L1: context.sensors.L1 || false,\n  L2: context.sensors.L2 || false,\n  L3: context.sensors.L3 || false,\n  L4: context.sensors.L4 || false\n});\nmsg.topic = 'stf/conveyor/sensors';\nreturn msg;"
  },
  {
    "id": "mqtt_sensor_out",
    "type": "mqtt out",
    "topic": "",
    "broker": "mqtt_broker",
    "name": "Publish Sensors"
  }
]
```

### Example Flow: Motor Current Monitoring (Analog)

```json
[
  {
    "id": "motor_current_aio",
    "type": "revpi-input",
    "name": "Motor Current ADC",
    "inputpin": "InputValue_1",
    "debounce": 100
  },
  {
    "id": "convert_current",
    "type": "function",
    "name": "Convert to Amps",
    "func": "// ADC value to current (0-10V = 0-5A)\nconst adcValue = msg.payload;\nconst voltage = (adcValue / 32767) * 10; // 16-bit ADC, 0-10V\nconst current = voltage / 2; // 2V/A sensor\n\nmsg.payload = {\n  component_id: 'CONV_M1',\n  current_amps: current,\n  voltage: 24.0,\n  is_active: current > 0.1\n};\nreturn msg;"
  },
  {
    "id": "mqtt_motor_status",
    "type": "mqtt out",
    "topic": "stf/conveyor/motor/status",
    "broker": "mqtt_broker"
  }
]
```

## RevPi I/O Mapping

### Digital Inputs (RevPi DIO)

| Pin | Signal | Description |
|-----|--------|-------------|
| I_1 | CONV_L1 | Conveyor Entry Sensor |
| I_2 | CONV_L2 | Conveyor Process Sensor |
| I_3 | CONV_L3 | Conveyor Exit Sensor |
| I_4 | CONV_L4 | Conveyor Overflow Sensor |
| I_5 | HBW_REF | HBW Reference Switch |
| I_6 | HBW_GRIP | HBW Gripper Closed |
| I_7 | VGR_VAC | VGR Vacuum Detected |
| I_8 | ESTOP | Emergency Stop Button |

### Digital Outputs (RevPi DIO)

| Pin | Signal | Description |
|-----|--------|-------------|
| O_1 | CONV_M1_EN | Conveyor Motor Enable |
| O_2 | CONV_M1_DIR | Conveyor Motor Direction |
| O_3 | HBW_X_EN | HBW X-Axis Enable |
| O_4 | HBW_X_DIR | HBW X-Axis Direction |
| O_5 | HBW_Y_EN | HBW Y-Axis Enable |
| O_6 | HBW_Y_DIR | HBW Y-Axis Direction |
| O_7 | HBW_Z_EN | HBW Z-Axis Enable |
| O_8 | HBW_Z_DIR | HBW Z-Axis Direction |
| O_9 | HBW_GRIP | HBW Gripper Solenoid |
| O_10 | VGR_COMP | VGR Compressor |
| O_11 | VGR_VALVE | VGR Vacuum Valve |

### Analog Inputs (RevPi AIO)

| Channel | Signal | Range | Description |
|---------|--------|-------|-------------|
| AI_1 | CONV_M1_I | 0-10V | Conveyor Motor Current (0-5A) |
| AI_2 | HBW_X_I | 0-10V | HBW X-Motor Current |
| AI_3 | HBW_Y_I | 0-10V | HBW Y-Motor Current |
| AI_4 | HBW_Z_I | 0-10V | HBW Z-Motor Current |
| AI_5 | VGR_COMP_I | 0-10V | VGR Compressor Current |
| AI_6 | HBW_X_POS | 0-10V | HBW X-Position Encoder |
| AI_7 | HBW_Y_POS | 0-10V | HBW Y-Position Encoder |
| AI_8 | HBW_Z_POS | 0-10V | HBW Z-Position Encoder |

## Safety Considerations

### Emergency Stop Implementation

The hardware bridge must implement a fail-safe emergency stop:

```javascript
// Node-RED Function: Emergency Stop Handler
const estopTriggered = msg.payload;

if (estopTriggered) {
    // Immediately disable all motor outputs
    node.send([
        {payload: false, topic: 'O_1'},  // Conveyor
        {payload: false, topic: 'O_3'},  // HBW X
        {payload: false, topic: 'O_5'},  // HBW Y
        {payload: false, topic: 'O_7'},  // HBW Z
        {payload: false, topic: 'O_10'}, // VGR Compressor
        {payload: false, topic: 'O_11'}  // VGR Valve
    ]);
    
    // Notify Digital Twin
    msg.topic = 'stf/global/status/emergency_stop';
    msg.payload = JSON.stringify({
        timestamp: new Date().toISOString(),
        source: 'hardware',
        message: 'Emergency stop activated'
    });
    return msg;
}
```

### Watchdog Timer

Implement a watchdog to detect communication failures:

```javascript
// Node-RED Function: Watchdog
const WATCHDOG_TIMEOUT = 5000; // 5 seconds

let lastHeartbeat = context.get('lastHeartbeat') || 0;
const now = Date.now();

if (msg.topic === 'stf/heartbeat') {
    context.set('lastHeartbeat', now);
    return null;
}

// Check watchdog on timer
if (now - lastHeartbeat > WATCHDOG_TIMEOUT) {
    // Communication lost - safe shutdown
    msg.payload = {
        action: 'safe_shutdown',
        reason: 'watchdog_timeout'
    };
    return msg;
}
```

## Testing the Bridge

### 1. Verify MQTT Connectivity

```bash
# Subscribe to all STF topics
mosquitto_sub -h localhost -t "stf/#" -v

# Publish test command
mosquitto_pub -h localhost -t "stf/conveyor/cmd/start" -m '{"direction": 1}'
```

### 2. Test Node-RED Flow

1. Open Node-RED at `http://revpi-ip:1880`
2. Import the example flows
3. Deploy and monitor debug output
4. Verify I/O changes on RevPi

### 3. End-to-End Test

1. Start the Digital Twin (FastAPI + Streamlit)
2. Start the mock_factory.py simulation
3. Verify MQTT messages flow correctly
4. Replace mock_factory with Node-RED bridge
5. Test physical hardware response

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| No MQTT messages | Broker not running | `sudo systemctl start mosquitto` |
| RevPi nodes not found | Package not installed | `npm install node-red-contrib-revpi-nodes` |
| I/O not responding | piControl not running | `sudo systemctl restart picontrol` |
| Current reading wrong | ADC calibration | Adjust conversion formula |
| Motors not moving | Safety interlock | Check E-STOP and enable signals |

### Debug Commands

```bash
# Check RevPi I/O status
piTest -r

# Monitor specific input
piTest -r I_1

# Set output manually
piTest -w O_1,1

# Check MQTT broker status
sudo systemctl status mosquitto

# View Node-RED logs
journalctl -u nodered -f
```

## Next Steps

1. **Calibrate Sensors**: Adjust ADC conversion formulas based on actual sensor specifications
2. **Tune PID Controllers**: Implement position control loops for precise robot movement
3. **Add Redundancy**: Implement dual-channel safety for critical functions
4. **Monitor Performance**: Track latency between Digital Twin and hardware
5. **Document Wiring**: Create detailed electrical schematics for the installation
