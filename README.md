# STF Digital Twin

A comprehensive warehouse automation digital twin system featuring real-time hardware simulation, MQTT communication, and an Industrial Apple Glassmorphism dashboard with historical analytics.

## Overview

The Smart Tabletop Factory (STF) Digital Twin simulates a high-bay warehouse automation system with hardware-in-the-loop capabilities. It provides real-time monitoring, control, and analytics for industrial automation scenarios.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     STF Digital Twin                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐     │
│  │  Streamlit   │    │   FastAPI    │    │    MySQL     │     │
│  │  Dashboard   │◄──►│   REST API   │◄──►│   Database   │     │
│  │  (Port 8501) │    │  (Port 8000) │    │  (Port 3306) │     │
│  └──────────────┘    └──────────────┘    └──────────────┘     │
│         │                   │                                  │
│         ▼                   ▼                                  │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │                  MQTT Broker (Port 1883)                 │ │
│  └──────────────────────────────────────────────────────────┘ │
│         │                   │                   │              │
│         ▼                   ▼                   ▼              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐     │
│  │   Mock HBW   │    │   Mock VGR   │    │  Mock Conv.  │     │
│  │  (10Hz sim)  │    │  (10Hz sim)  │    │  (10Hz sim)  │     │
│  └──────────────┘    └──────────────┘    └──────────────┘     │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │              Main Controller (FSM Logic)                  │ │
│  │  • Command translation  • Safety interlocks               │ │
│  │  • Collision prevention • Energy logging                  │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Features

### Main Dashboard

- **Industrial Apple Glassmorphism** design with frosted glass effects
- **Live 2D robot position** monitoring with scatter plot
- **3x3 inventory grid** with color-coded cookie flavors
- **Control panel** for store/retrieve operations
- **Hardware status** indicators with real-time updates
- **System logs** display with severity levels
- **Energy consumption** metrics
- **Auto-refresh** every 2 seconds

### Analytics Page

- **Energy consumption** time-series charts by device
- **Production throughput** visualization with daily/weekly trends
- **Hardware utilization** heatmaps showing activity patterns
- **Predictive maintenance** insights with health scores
- **Anomaly detection** visualization
- **Data export** functionality (CSV format)
- **Date range filtering** (24h, 7d, 30d, 90d, custom)

### Simulation

- **AsyncIO-based physics** at 10Hz tick rate
- **MQTT communication** for hardware commands/telemetry
- **FSM controller** with 9 operational states
- **Collision prevention** safety interlocks
- **Energy consumption** tracking per device

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
MQTT_BROKER=localhost
MQTT_PORT=1883
```

### Start Services

**Option 1: Run script (Linux/macOS)**

```bash
./run_all.sh
```

**Option 2: Manual startup (4 terminals)**

```bash
# Terminal 1 - FastAPI Server
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 - Mock Hardware
python -m hardware.mock_hbw

# Terminal 3 - Main Controller
python -m controller.main_controller

# Terminal 4 - Streamlit Dashboard
streamlit run dashboard/app.py
```

**Option 3: Docker infrastructure**

```bash
docker-compose up -d  # Starts MySQL + Mosquitto + Adminer
```

### Access Points

| Service          | URL                             |
| ---------------- | ------------------------------- |
| Dashboard        | http://localhost:8501           |
| Analytics        | http://localhost:8501/analytics |
| API Docs         | http://localhost:8000/docs      |
| Adminer (Docker) | http://localhost:8080           |

## Project Structure

```
stf_project/
├── api/                    # FastAPI REST API
│   └── main.py            # API endpoints
├── controller/            # Main controller
│   └── main_controller.py # FSM logic & safety
├── dashboard/             # Streamlit UI
│   ├── app.py            # Main dashboard
│   └── pages/
│       └── analytics.py  # Historical analytics
├── database/             # SQLAlchemy models
│   ├── models.py        # ORM models
│   └── connection.py    # DB connection
├── hardware/             # Mock hardware
│   └── mock_hbw.py      # 10Hz simulation
├── docs/                 # Documentation
│   └── SETUP.md         # Detailed setup guide
├── mosquitto/           # MQTT broker config
├── docker-compose.yml   # Docker services
├── requirements.txt     # Python dependencies
└── run_all.sh          # Startup script
```

## API Endpoints

| Endpoint                        | Method | Description           |
| ------------------------------- | ------ | --------------------- |
| `/health`                     | GET    | Health check          |
| `/dashboard/data`             | GET    | All dashboard data    |
| `/inventory`                  | GET    | List inventory slots  |
| `/hardware/states`            | GET    | All hardware states   |
| `/hardware/state`             | POST   | Update hardware state |
| `/order/store`                | POST   | Store a cookie        |
| `/order/retrieve`             | POST   | Retrieve a cookie     |
| `/telemetry`                  | POST   | Record telemetry      |
| `/energy`                     | POST   | Record energy usage   |
| `/maintenance/reset`          | POST   | Reset system          |
| `/maintenance/emergency-stop` | POST   | Emergency stop        |

## Database Schema

| Table                    | Description        |
| ------------------------ | ------------------ |
| `py_carriers`          | Carrier entities   |
| `py_cookies`           | Cookie batches     |
| `py_inventory_slots`   | 3x3 rack grid      |
| `py_hardware_states`   | Device positions   |
| `py_system_logs`       | System logs        |
| `py_energy_logs`       | Energy consumption |
| `py_telemetry_history` | Time-series data   |
| `py_alerts`            | System alerts      |
| `py_commands`          | Command history    |

## Coordinate System

| Slot | X (mm) | Y (mm) |
| ---- | ------ | ------ |
| A1   | 100    | 100    |
| A2   | 200    | 100    |
| A3   | 300    | 100    |
| B1   | 100    | 200    |
| B2   | 200    | 200    |
| B3   | 300    | 200    |
| C1   | 100    | 300    |
| C2   | 200    | 300    |
| C3   | 300    | 300    |

## Safety Features

- **Collision Prevention**: Blocks movements that would cause hardware collision
- **Emergency Stop**: Immediately halts all hardware operations
- **Alert System**: Logs critical events with severity levels
- **FSM Logic**: Ensures proper state transitions

## Documentation

For detailed setup instructions including:

- Windows installation guide
- macOS installation guide
- Local MySQL setup
- Docker alternative
- Troubleshooting

See **[docs/SETUP.md](docs/SETUP.md)**

## License

MIT License
