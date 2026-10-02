# STF Digital Twin - AI Coding Instructions

## Architecture Overview
This is a **Smart Tabletop Factory Digital Twin** for warehouse automation with a Command Queue architecture:
- **FastAPI** ([api/main.py](api/main.py)) - REST API + WebSocket server on port 8000
- **Streamlit Dashboard** ([dashboard/app.py](dashboard/app.py)) - UI on port 8501
- **Main Controller** ([controller/main_controller.py](controller/main_controller.py)) - Polls DB for commands, executes via MQTT
- **Mock Hardware** ([hardware/mock_factory.py](hardware/mock_factory.py)) - 10Hz physics simulation with electrical/wear models

Data flow: `Dashboard → API (queues command) → DB → Controller (polls) → MQTT → Hardware simulators`

## Database (SQLAlchemy + SQLite)
**Local SQLite storage** - all data persists to `stf_digital_twin.db` in project root. No database server required - just run the app and the .db file is created automatically.

### Key Patterns
```python
# Connection setup (database/connection.py)
from database import get_db, get_session

# FastAPI dependency injection - use for API endpoints
@app.get("/endpoint")
def endpoint(db: Session = Depends(get_db)):
    return db.query(Model).all()

# Context manager for scripts/services - use for standalone scripts
from database.connection import get_session
with get_session() as session:
    session.add(new_record)
    # Auto-commits on exit, rolls back on exception
```

### Models ([database/models.py](database/models.py))
Tables use `py_` prefix: `py_carriers`, `py_cookies`, `py_commands`, `py_hardware_states`, etc.

Core entities: `Carrier`, `Cookie`, `InventorySlot`, `Command`, `HardwareState`, `ComponentRegistry`, `MotorState`, `SensorState`, `Alert`, `SystemLog`, `EnergyLog`, `TelemetryHistory`

Enums: `CookieFlavor`, `CookieStatus`, `HardwareStatus`, `SubsystemType`, `ComponentType`, `SensorType`, `AlertSeverity`, `LogLevel`

### Database Initialization
```python
from database.connection import init_database
init_database(seed_data=True)  # Creates tables + seeds inventory slots & hardware devices
```

## Running the System
```bash
# Full stack (recommended)
.\run_all.bat   # Windows
./run_all.sh    # Linux/macOS

# Individual services
uvicorn api.main:app --port 8000 --reload      # API
python -m hardware.mock_factory                 # Hardware sim
python -m controller.main_controller            # Controller
streamlit run dashboard/app.py                  # Dashboard
```

## Command Queue Pattern
Commands flow through the database for reliable execution:
1. API creates `Command` with `status="PENDING"`
2. Controller polls for `PENDING`, sets `IN_PROGRESS`
3. Executes via MQTT to hardware, updates to `COMPLETED`/`FAILED`

```python
# Creating a command (api/main.py pattern)
command = Command(
    command_type="FETCH_COOKIE",
    target_slot="A1",
    payload_json=json.dumps({"source": "A1"}),
    status="PENDING"
)
db.add(command)
db.commit()
```

## Hardware Simulation
- **Subsystems**: HBW (High-Bay Warehouse), VGR (Vacuum Gripper Robot), CONVEYOR
- **Components**: Motors track current/health/runtime, Sensors track trigger counts
- **Coordinate system**: 9 slots (A1-C3) mapped to (x, y) coordinates in `SLOT_COORDINATES`

## Environment Variables
```env
DATABASE_URL=sqlite:///./stf_digital_twin.db  # Default, or mysql+pymysql://...
STF_API_URL=http://localhost:8000
MQTT_BROKER=localhost
MQTT_PORT=1883
```

## Testing & Data Generation
```bash
python scripts/generate_history.py --days 30   # Generate historical data
python scripts/demo_sensors.py                  # Sensor demo
python test.py                                  # Basic tests
```
