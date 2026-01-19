# STF Digital Twin v3.0

A **High-Fidelity Component Twin** for warehouse automation featuring a Command Queue architecture, electrical simulation, mechanical wear modeling, synthetic data generation, and an advanced analytics dashboard.

## Overview

The Smart Tabletop Factory (STF) Digital Twin simulates a high-bay warehouse automation system with hardware-in-the-loop capabilities. It provides real-time monitoring, control, predictive maintenance, and analytics for industrial automation scenarios. This version introduces a robust Command Queue architecture for reliable, sequential execution of complex tasks.

## Architecture

The system is built on a decoupled, event-driven architecture:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     STF Digital Twin v3.0 - Command Queue Architecture    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────┐          │
│  │  Streamlit   │───►│     FastAPI      │───►│   SQLite     │          │
│  │  Dashboard   │    │  (Queue Command) │    │  (.db file)  │          │
│  │  (Port 8501) │    │   (Port 8000)    │    │              │          │
│  └──────────────┘    └──────────────────┘    └──────▲───────┘          │
│                                                     │ (Polls)           │
│                                                     │                   │
│  ┌──────────────────────────────────────────────────┴─────────────────┐  │
│  │              Main Controller (Command Queue Processor)             │  │
│  │  • Polls DB for PENDING commands                                  │  │
│  │  • Executes commands sequentially (FSM logic)                     │  │
│  │  • Updates command status (IN_PROGRESS -> COMPLETED/FAILED)       │  │
│  └──────────────────────────────────┬─────────────────────────────────┘  │
│                                     │ (Publishes)                       │
│                                     ▼                                   │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    MQTT Broker (Port 1883)                        │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│         │ (Subscribes)         │                    │                     │
│         ▼                    ▼                    ▼                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐             │
│  │   Mock HBW   │    │   Mock VGR   │    │  Conveyor    │             │
│  │  (10Hz sim)  │    │  (10Hz sim)  │    │  (10Hz sim)  │             │
│  └──────────────┘    └──────────────┘    └──────────────┘             │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Key Features

### Command Queue Architecture
- **Reliable Execution**: API endpoints queue commands in the database with `PENDING` status.
- **Decoupled Controller**: The `main_controller` polls the database for pending commands, ensuring sequential and non-blocking execution.
- **State Management**: Commands are updated to `IN_PROGRESS`, `COMPLETED`, or `FAILED`, providing a full audit trail.
- **Auto-Slot Selection**: The `/order/process` endpoint can now automatically select a `RAW_DOUGH` cookie if no `source_slot` is specified.

### Synthetic Data Generation
- **1-Month Historical Data**: The `scripts/generate_history.py` script populates the database with 30 days of realistic data.
- **Breakdown Scenarios**:
  - **Day 12: Motor Failure**: `CONV_M1` current spikes to 4.5A and health degrades to 40%.
  - **Day 25: Sensor Drift**: `CONV_L2_PROCESS` generates intermittent ghost readings.
- **Rich Data**: Includes order events, energy logs, motor health degradation, and predictive maintenance alerts.

### Enhanced Analytics Dashboard
- **Real Database Integration**: Charts now pull historical data directly from the database.
- **Breakdown Visualization**: Key charts now highlight the Day 12 motor failure and Day 25 sensor drift events.
- **Motor Health View**: A dedicated tab for tracking motor health degradation over time and viewing current status.
- **Alerts & Events**: A new tab to display critical, warning, and info alerts with timestamps.
- **Predictive Insights**: Health forecast chart and maintenance recommendations based on current health scores.

## Quick Start

### Prerequisites
- Python 3.9+ (3.11 recommended)
- (Optional) MySQL 8.0+ or Docker for production use

### Installation
```bash
git clone <repository-url> stf_project
cd stf_project
python -m venv venv
source venv/bin/activate  # Linux/macOS
# .\venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

### Configuration
Create a `.env` file in the project root (optional - defaults to SQLite):
```env
# Default: SQLite local database (no configuration needed)
DATABASE_URL=sqlite:///./stf_digital_twin.db

# For MySQL (optional):
# DATABASE_URL=mysql+pymysql://stf_user:stf_password@localhost:3306/stf_warehouse

STF_API_URL=http://localhost:8000
STF_WS_URL=ws://localhost:8000/ws
MQTT_BROKER=localhost
MQTT_PORT=1883
```

### Generate Historical Data
Run the synthetic data generator to populate the database:
```bash
python scripts/generate_history.py --days 30 --orders-per-day 50
```

### Start Services
**Option 1: Run script (Linux/macOS)**
```bash
./run_all.sh
```

**Option 2: Manual startup (4 terminals)**
```bash
# Terminal 1 - FastAPI Server
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 - Mock Hardware
python -m hardware.mock_factory

# Terminal 3 - Main Controller
python -m controller.main_controller

# Terminal 4 - Streamlit Dashboard
streamlit run dashboard/app.py
```

### Access Points
| Service          | URL                             |
| ---------------- | ------------------------------- |
| Dashboard        | http://localhost:8501           |
| Analytics        | http://localhost:8501/analytics |
| API Docs         | http://localhost:8000/docs      |

## Project Structure
```
stf_project/
├── api/                    # FastAPI REST API + WebSocket
├── controller/             # Command Queue controller
├── dashboard/              # Streamlit UI
│   ├── app.py            # Main dashboard
│   └── pages/
│       └── analytics.py  # Enhanced historical analytics
├── database/               # SQLAlchemy models
├── hardware/               # Mock hardware simulation
├── scripts/                # Data generation scripts
│   └── generate_history.py # Synthetic data generator
├── docs/                   # Documentation
├── mosquitto/              # MQTT broker config
├── docker-compose.yml      # Docker services
├── requirements.txt        # Python dependencies
└── run_all.sh              # Startup script
```

## API Endpoints (Updated)
| Endpoint                        | Method | Description                                    |
| ------------------------------- | ------ | ---------------------------------------------- |
| `/commands/pending`             | GET    | Get pending commands for the controller        |
| `/commands/{id}/status`         | POST   | Update the status of a command                 |
| `/order/process`                | POST   | Queue a process command (auto-slot supported)  |

(Other endpoints remain the same)

## License

MIT License
