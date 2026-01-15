# STF Digital Twin - Simulation Services

## Overview

The Smart Tabletop Factory (STF) Digital Twin is a comprehensive warehouse automation simulation system that provides:

- **Hardware-in-the-Loop (HIL) Simulation**: AsyncIO-based physics simulation at 10Hz
- **MQTT Communication**: Real-time command/telemetry exchange via Mosquitto broker
- **Safety Interlocks**: Collision prevention and safety monitoring
- **Energy Monitoring**: Virtual energy consumption tracking for predictive maintenance

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Web Dashboard                             │
│                   (React + Recharts + tRPC)                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Backend API (tRPC)                         │
│              Inventory, Orders, Hardware, Alerts                │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   MySQL DB      │  │  MQTT Broker    │  │  Controller     │
│   (TiDB)        │  │  (Mosquitto)    │  │  (Python)       │
└─────────────────┘  └─────────────────┘  └─────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  Mock Hardware  │
                    │  (Python/AsyncIO)│
                    └─────────────────┘
```

## Directory Structure

```
simulation/
├── docker-compose.yml      # Docker infrastructure (MySQL, MQTT, Adminer)
├── requirements.txt        # Python dependencies
├── run_simulation.sh       # Startup script
├── mosquitto/
│   └── config/
│       └── mosquitto.conf  # MQTT broker configuration
└── stf_warehouse/
    ├── __init__.py
    ├── config.py           # Coordinate mappings and constants
    ├── hardware/
    │   ├── __init__.py
    │   └── mock_hbw.py     # AsyncIO physics simulation
    └── controller/
        ├── __init__.py
        └── main_controller.py  # FSM logic and safety interlocks
```

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (optional, for local MQTT/MySQL)
- pip or pipx for Python package management

### Installation

1. Install Python dependencies:
```bash
cd simulation
pip install -r requirements.txt
```

2. (Optional) Start Docker infrastructure:
```bash
docker-compose up -d
```

### Running the Simulation

#### Option 1: Using the run script
```bash
./run_simulation.sh all
```

#### Option 2: Manual startup (separate terminals)

**Terminal 1 - Mock Hardware:**
```bash
cd simulation
python -m stf_warehouse.hardware.mock_hbw
```

**Terminal 2 - Controller:**
```bash
cd simulation
python -m stf_warehouse.controller.main_controller
```

### Stopping Services

```bash
./run_simulation.sh stop
```

Or manually:
```bash
pkill -f 'stf_warehouse'
docker-compose down
```

## MQTT Topics

### Command Topics (Subscribed by Mock Hardware)

| Topic | Payload | Description |
|-------|---------|-------------|
| `stf/hbw/cmd/move_x` | `{"target": 100}` | Move X-axis to position |
| `stf/hbw/cmd/move_y` | `{"target": 200}` | Move Y-axis to position |
| `stf/hbw/cmd/move` | `{"targetX": 100, "targetY": 200}` | Combined X,Y move |
| `stf/hbw/cmd/gripper` | `{"action": "close"}` | Gripper control |

### Status Topics (Published by Mock Hardware)

| Topic | Payload | Description |
|-------|---------|-------------|
| `stf/hbw/status` | `{"x": 100, "y": 200, "moving": true, "status": "MOVING"}` | HBW telemetry |
| `stf/conveyor/status` | `{"position": 50, "status": "IDLE"}` | Conveyor status |

### High-Level Request Topics (Subscribed by Controller)

| Topic | Payload | Description |
|-------|---------|-------------|
| `stf/global/req/retrieve` | `{"slot": "A1"}` | Retrieve from slot |
| `stf/global/req/store` | `{"slot": "B2"}` | Store to slot |
| `stf/global/req/reset` | `{}` | Reset all hardware |

## Coordinate Mapping

The warehouse uses a 3x3 grid with the following slot-to-coordinate mapping:

| Slot | X | Y |
|------|---|---|
| A1 | 100 | 100 |
| A2 | 200 | 100 |
| A3 | 300 | 100 |
| B1 | 100 | 200 |
| B2 | 200 | 200 |
| B3 | 300 | 200 |
| C1 | 100 | 300 |
| C2 | 200 | 300 |
| C3 | 300 | 300 |

## Simulation Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| Tick Rate | 10 Hz | Physics update frequency |
| Movement Speed | 10 units/tick | Robot movement speed |
| Max Position | 500 | Maximum coordinate value |
| Min Position | 0 | Minimum coordinate value |
| Position Tolerance | 1.0 | Arrival detection threshold |

## Energy Calculation

Virtual energy consumption is calculated based on:

- **Idle Power**: 5W when stationary
- **Moving Power**: 50W during movement
- **Operating Voltage**: 24V
- **Motor Efficiency**: 85%

Energy is logged to the database every 10 seconds for trend analysis.

## Safety Interlocks

The controller implements collision prevention:

1. **HBW-Conveyor Interlock**: HBW cannot move while conveyor is active
2. **VGR Conflict Detection**: Checks for position conflicts between devices
3. **Carrier Lock**: Prevents operations on locked carriers

## API Integration

The simulation services communicate with the web backend via HTTP:

- `POST /api/trpc/hardware.updateState` - Update hardware state
- `POST /api/trpc/telemetry.record` - Record telemetry data
- `POST /api/trpc/energy.record` - Log energy consumption
- `POST /api/trpc/alerts.create` - Create alerts
- `GET /api/trpc/commands.pending` - Fetch pending commands

## Troubleshooting

### MQTT Connection Failed
- Ensure Mosquitto is running: `docker-compose ps`
- Check port 1883 is available: `netstat -an | grep 1883`

### API Connection Failed
- Verify the web app is running on port 3000
- Check API_BASE_URL in configuration

### Python Import Errors
- Ensure you're running from the `simulation` directory
- Install dependencies: `pip install -r requirements.txt`

## Development

### Adding New Hardware Devices

1. Create a new module in `stf_warehouse/hardware/`
2. Implement the physics simulation loop
3. Subscribe to relevant MQTT topics
4. Publish telemetry to status topics

### Extending the Controller

1. Add new state to `ControllerState` enum
2. Implement state transition logic
3. Add safety checks in `SafetyInterlock` class
4. Handle new MQTT topics in message callback
