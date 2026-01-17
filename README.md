# STF Digital Twin

A **High-Fidelity Component Twin** for warehouse automation featuring electrical simulation, mechanical wear modeling, WebSocket real-time updates, and an Industrial Apple Glassmorphism dashboard.

## Overview

The Smart Tabletop Factory (STF) Digital Twin simulates a high-bay warehouse automation system with hardware-in-the-loop capabilities. It provides real-time monitoring, control, predictive maintenance, and analytics for industrial automation scenarios.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     STF Digital Twin v3.0                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────┐          │
│  │  Streamlit   │    │     FastAPI      │    │    MySQL     │          │
│  │  Dashboard   │◄──►│  REST + WebSocket │◄──►│   Database   │          │
│  │  (Port 8501) │    │   (Port 8000)    │    │  (Port 3306) │          │
│  └──────────────┘    └──────────────────┘    └──────────────┘          │
│         │                    │                                          │
│         ▼                    ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    MQTT Broker (Port 1883)                        │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│         │                    │                    │                     │
│         ▼                    ▼                    ▼                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐             │
│  │   Mock HBW   │    │   Mock VGR   │    │  Conveyor    │             │
│  │  (10Hz sim)  │    │  (10Hz sim)  │    │  (10Hz sim)  │             │
│  │  • 4 Motors  │    │  • 5 Motors  │    │  • 5 Motors  │             │
│  │  • Health    │    │  • Vacuum    │    │  • 4 Sensors │             │
│  └──────────────┘    └──────────────┘    └──────────────┘             │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │              Main Controller (FSM Logic)                          │  │
│  │  • Command translation  • Safety interlocks                       │  │
│  │  • Collision prevention • Energy logging                          │  │
│  │  • Predictive maintenance alerts                                  │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Key Features

### High-Fidelity Component Twin

- **14 Component Registry**: HBW (4), CONVEYOR (5), VGR (5) with spec sheets
- **Electrical Simulation**: Idle (0.05A), Startup inrush (2.5A), Running (1.2A)
- **Health Degradation**: Motors degrade 0.0001 per tick when active
- **Predictive Maintenance**: Time-to-Failure (TTF) estimation
- **Anomaly Injection**: Current spikes when health_score < 0.8

### Main Dashboard

- **Industrial Apple Glassmorphism** design with frosted glass effects
- **Conveyor Belt Progress Bar** with 4 light barrier sensor indicators
- **Motor Health Cards** with health bars and TTF badges
- **Live Power Gauge** showing total current draw vs. spec limits
- **Live 2D Robot Position** monitoring with scatter plot
- **3x3 Inventory Grid** with cookie status (RAW_DOUGH → BAKED → PACKAGED)
- **Control Panel** for store/retrieve/bake operations
- **Real-time WebSocket** updates (1 second refresh)

### Analytics Page

- **Energy Consumption** time-series charts by device
- **Production Throughput** visualization with daily/weekly trends
- **Hardware Utilization** heatmaps showing activity patterns
- **Predictive Maintenance** insights with health scores
- **Anomaly Detection** visualization
- **Data Export** functionality (CSV format)
- **Date Range Filtering** (24h, 7d, 30d, 90d, custom)

### Simulation Engine

- **AsyncIO-based Physics** at 10Hz tick rate
- **Conveyor Belt Physics**: 0-1000mm position tracking
- **Light Barrier Sensors**: L1 (100mm), L2 (400mm), L3 (700mm), L4 (950mm)
- **Motor Electrical Model**: Phase-based current simulation
- **Micro-stoppages**: Random pauses when health_score < 0.5
- **MQTT Communication** for hardware commands/telemetry

## Quick Start

### Prerequisites

- Python 3.9+ (3.11 recommended)
- MySQL 8.0+ (or Docker)

### Installation

```bash
# Clone repository
git clone <repository-url> stf_project
cd stf_project

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
.\venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt
```

### Configuration

Create a `.env` file in the project root:

```env
DATABASE_URL=mysql+pymysql://stf_user:stf_password@localhost:3306/stf_warehouse
STF_API_URL=http://localhost:8000
STF_WS_URL=ws://localhost:8000/ws
MQTT_BROKER=localhost
MQTT_PORT=1883
```

### Start Services

**Option 1: Run script (Linux/macOS)**

```bash
./run_all.sh
```

**Option 2: Run script (Windows)**

```cmd
run_all.bat
```

**Option 3: Manual startup (4 terminals)**

```bash
# Terminal 1 - FastAPI Server
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 - Mock Hardware (High-Fidelity)
python -m hardware.mock_factory

# Terminal 3 - Main Controller
python -m controller.main_controller

# Terminal 4 - Streamlit Dashboard
streamlit run dashboard/app.py
```

**Option 4: Docker infrastructure**

```bash
docker-compose up -d  # Starts MySQL + Mosquitto + Adminer
```

### Access Points

| Service          | URL                             |
| ---------------- | ------------------------------- |
| Dashboard        | http://localhost:8501           |
| Analytics        | http://localhost:8501/analytics |
| API Docs         | http://localhost:8000/docs      |
| WebSocket        | ws://localhost:8000/ws          |
| Adminer (Docker) | http://localhost:8080           |

## Project Structure

```
stf_project/
├── api/                    # FastAPI REST API + WebSocket
│   └── main.py            # API endpoints & WS manager
├── controller/            # Main controller
│   └── main_controller.py # FSM logic & safety
├── dashboard/             # Streamlit UI
│   ├── app.py            # Main dashboard (Glassmorphism)
│   └── pages/
│       └── analytics.py  # Historical analytics
├── database/             # SQLAlchemy models
│   ├── models.py        # ORM models (14 tables)
│   └── connection.py    # DB connection
├── hardware/             # Mock hardware
│   ├── mock_factory.py  # High-fidelity simulation
│   └── mock_hbw.py      # Legacy HBW simulation
├── docs/                 # Documentation
│   ├── SETUP.md         # Detailed setup guide
│   └── HARDWARE_BRIDGE.md # Node-RED/RevPi integration
├── mosquitto/           # MQTT broker config
├── docker-compose.yml   # Docker services
├── requirements.txt     # Python dependencies
├── run_all.sh          # Linux/macOS startup
└── run_all.bat         # Windows startup
```

## API Endpoints

| Endpoint                        | Method | Description              |
| ------------------------------- | ------ | ------------------------ |
| `/health`                       | GET    | Health check             |
| `/ws`                           | WS     | WebSocket real-time      |
| `/dashboard/data`               | GET    | All dashboard data       |
| `/inventory`                    | GET    | List inventory slots     |
| `/components/specs`             | GET    | Component specifications |
| `/hardware/states`              | GET    | All hardware states      |
| `/hardware/state`               | POST   | Update hardware state    |
| `/motors/state`                 | POST   | Update motor state       |
| `/sensors/state`                | POST   | Update sensor state      |
| `/conveyor/state`               | POST   | Update conveyor state    |
| `/order/store`                  | POST   | Store a cookie           |
| `/order/retrieve`               | POST   | Retrieve a cookie        |
| `/order/process`                | POST   | Bake a cookie            |
| `/telemetry`                    | POST   | Record telemetry         |
| `/energy`                       | POST   | Record energy usage      |
| `/maintenance/initialize`       | POST   | Initialize system        |
| `/maintenance/reset`            | POST   | Reset system             |
| `/maintenance/emergency-stop`   | POST   | Emergency stop           |

## Database Schema

| Table                    | Description                |
| ------------------------ | -------------------------- |
| `py_carriers`            | Carrier entities           |
| `py_cookies`             | Cookie batches (lifecycle) |
| `py_inventory_slots`     | 3x3 rack grid              |
| `py_hardware_states`     | Device positions           |
| `py_component_registry`  | Component specifications   |
| `py_motor_states`        | Motor health & current     |
| `py_sensor_states`       | Sensor trigger states      |
| `py_system_logs`         | System logs                |
| `py_energy_logs`         | Energy consumption         |
| `py_telemetry_history`   | Time-series data           |
| `py_alerts`              | System alerts              |
| `py_commands`            | Command history            |

## Cookie Lifecycle

```
RAW_DOUGH → BAKED → PACKAGED → SHIPPED
    │          │         │
    └──────────┴─────────┴── Tracked in inventory
```

## Component Registry

| Subsystem | Components                                    |
| --------- | --------------------------------------------- |
| HBW       | HBW_X_MOTOR, HBW_Y_MOTOR, HBW_Z_MOTOR, HBW_GRIPPER |
| CONVEYOR  | CONV_M1, CONV_L1, CONV_L2, CONV_L3, CONV_L4  |
| VGR       | VGR_X_MOTOR, VGR_Y_MOTOR, VGR_Z_MOTOR, VGR_COMP, VGR_VALVE |

## Safety Features

- **Collision Prevention**: Blocks movements that would cause hardware collision
- **Emergency Stop**: Immediately halts all hardware operations
- **Health Monitoring**: Alerts when motor health < 0.5
- **Micro-stoppage Detection**: Logs when degraded motors pause
- **Alert System**: Logs critical events with severity levels
- **FSM Logic**: Ensures proper state transitions

## Documentation

- **[docs/SETUP.md](docs/SETUP.md)** - Windows, macOS, Linux installation
- **[docs/HARDWARE_BRIDGE.md](docs/HARDWARE_BRIDGE.md)** - Node-RED & RevPi integration

## License

MIT License
