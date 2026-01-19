# ST-HW System Documentation

**Author:** Manus AI
**Version:** 1.0
**Date:** January 2026

---

## Table of Contents

1. [System Architecture](#1-system-architecture)
2. [Module Descriptions](#2-module-descriptions)
3. [API Endpoints Reference](#3-api-endpoints-reference)
4. [MQTT Communication Protocol](#4-mqtt-communication-protocol)
5. [Database Schema](#5-database-schema)
6. [Complete Working Cycle Example](#6-complete-working-cycle-example)
7. [Code-Level Walkthrough](#7-code-level-walkthrough)

---

## 1. System Architecture

The ST-HW (Smart Tabletop Factory Hardware) system implements a decoupled, event-driven architecture that separates the user interface, backend logic, and hardware control layers. This design philosophy enhances scalability, reliability, and maintainability across all system components.

### 1.1. High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     STF Digital Twin v3.0 - Command Queue Architecture      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────────────────┐  │
│  │  Streamlit   │───►│     FastAPI      │───►│        MySQL/SQLite      │  │
│  │  Dashboard   │    │  (Queue Command) │    │    (Commands Table)      │  │
│  │  (Port 8501) │    │   (Port 8000)    │    │      (Port 3306)         │  │
│  └──────────────┘    └──────────────────┘    └───────────▲──────────────┘  │
│         │                    │                           │                  │
│         │ WebSocket          │ REST API                  │ Polls            │
│         ▼                    ▼                           │                  │
│  ┌──────────────────────────────────────────────────────┴────────────────┐  │
│  │                 Main Controller (Command Queue Processor)              │  │
│  │  • Polls database for PENDING commands                                │  │
│  │  • Executes commands sequentially using FSM logic                     │  │
│  │  • Updates command status (IN_PROGRESS -> COMPLETED/FAILED)           │  │
│  │  • Publishes hardware commands via MQTT                               │  │
│  └────────────────────────────────┬──────────────────────────────────────┘  │
│                                   │ MQTT Publish/Subscribe                  │
│                                   ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                    MQTT Broker - Mosquitto (Port 1883)                │  │
│  │                    WebSocket Support (Port 9001)                      │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│           │                       │                       │                 │
│           ▼                       ▼                       ▼                 │
│  ┌──────────────┐        ┌──────────────┐        ┌──────────────┐          │
│  │   Mock HBW   │        │   Mock VGR   │        │   Conveyor   │          │
│  │  (10Hz sim)  │        │  (10Hz sim)  │        │  (10Hz sim)  │          │
│  └──────────────┘        └──────────────┘        └──────────────┘          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2. Core Components

The system comprises six primary components that work together to provide a complete digital twin solution:

| Component                    | Technology   | Port      | Description                               |
| ---------------------------- | ------------ | --------- | ----------------------------------------- |
| **Frontend Dashboard** | Streamlit    | 8501      | Web-based UI for monitoring and control   |
| **Backend API**        | FastAPI      | 8000      | RESTful API with WebSocket support        |
| **Database**           | MySQL/SQLite | 3306      | Persistent storage for state and logs     |
| **MQTT Broker**        | Mosquitto    | 1883/9001 | Message broker for hardware communication |
| **Main Controller**    | Python       | N/A       | Command queue processor with FSM logic    |
| **Mock Hardware**      | Python       | N/A       | Physics-based hardware simulation         |

---

## 2. Module Descriptions

### 2.1. API Module (`api/`)

The API module serves as the primary interface between the frontend and the backend systems. Built with FastAPI, it provides high-performance RESTful endpoints with automatic OpenAPI documentation.

**Key Responsibilities:**

- Handle HTTP requests from the dashboard
- Validate incoming data using Pydantic models
- Queue commands in the database for asynchronous execution
- Provide real-time updates via WebSocket connections
- Record telemetry and energy consumption data

**Main File:** `api/main.py`

### 2.2. Controller Module (`controller/`)

The controller is the orchestration layer of the system. It implements a command queue pattern that ensures reliable, sequential execution of factory operations.

**Key Responsibilities:**

- Poll the database for pending commands
- Execute commands using Finite State Machine (FSM) logic
- Communicate with hardware via MQTT
- Update command status upon completion or failure
- Handle error conditions and retries

**Main File:** `controller/main_controller.py`

### 2.3. Dashboard Module (`dashboard/`)

The dashboard provides a real-time visualization of the factory's state. It uses Streamlit for rapid development and Plotly for interactive charts.

**Key Responsibilities:**

- Display real-time inventory status
- Visualize hardware positions on a 2D graph
- Show motor health and sensor states
- Provide control buttons for user actions
- Display system logs and alerts

**Main Files:**

- `dashboard/app.py` - Main dashboard application
- `dashboard/pages/analytics.py` - Historical analytics page

### 2.4. Database Module (`database/`)

The database module defines the data models and provides functions for database interaction. It uses SQLAlchemy ORM for database abstraction.

**Key Responsibilities:**

- Define table schemas using SQLAlchemy models
- Manage database connections and sessions
- Provide seed functions for initial data
- Support both MySQL and SQLite backends

**Main Files:**

- `database/models.py` - SQLAlchemy model definitions
- `database/connection.py` - Connection management

### 2.5. Hardware Module (`hardware/`)

The hardware module contains the simulation code for the factory's physical components. It provides a high-fidelity physics engine that mimics real hardware behavior.

**Key Responsibilities:**

- Simulate motor physics (startup, running, stopping phases)
- Model electrical characteristics (current draw, power consumption)
- Simulate sensor behavior (light barriers, trail sensors)
- Implement health degradation over time
- Respond to MQTT commands

**Main File:** `hardware/mock_factory.py`

### 2.6. Scripts Module (`scripts/`)

The scripts module contains utility scripts for development and testing purposes.

**Key Files:**

- `scripts/generate_history.py` - Generate synthetic historical data

---

## 3. API Endpoints Reference

### 3.1. WebSocket Endpoint

| Endpoint                   | Description                     |
| -------------------------- | ------------------------------- |
| `ws://localhost:8000/ws` | Real-time updates for dashboard |

### 3.2. Component Endpoints

| Endpoint              | Method | Description                                       |
| --------------------- | ------ | ------------------------------------------------- |
| `/components/specs` | GET    | Get static specification data for all components  |
| `/motors/state`     | POST   | Update motor state and broadcast via WebSocket    |
| `/motors/states`    | GET    | Get all motor states                              |
| `/sensors/state`    | POST   | Update sensor state and broadcast via WebSocket   |
| `/sensors/states`   | GET    | Get all sensor states                             |
| `/conveyor/state`   | POST   | Update full conveyor state (motor + sensors)      |
| `/hardware/state`   | POST   | Update hardware state and broadcast via WebSocket |
| `/hardware/states`  | GET    | Get all hardware states                           |

### 3.3. Telemetry Endpoints

| Endpoint       | Method | Description                    |
| -------------- | ------ | ------------------------------ |
| `/telemetry` | POST   | Record telemetry data          |
| `/energy`    | POST   | Record energy consumption data |

### 3.4. Inventory Endpoints

| Endpoint       | Method | Description                      |
| -------------- | ------ | -------------------------------- |
| `/inventory` | GET    | Get the current inventory status |

### 3.5. Order Endpoints

| Endpoint            | Method | Description                           |
| ------------------- | ------ | ------------------------------------- |
| `/order/store`    | POST   | Store a cookie in the warehouse       |
| `/order/retrieve` | POST   | Retrieve a cookie from the warehouse  |
| `/order/process`  | POST   | Process a cookie (RAW_DOUGH -> BAKED) |

### 3.6. Dashboard Endpoints

| Endpoint            | Method | Description                             |
| ------------------- | ------ | --------------------------------------- |
| `/dashboard/data` | GET    | Get all data required for the dashboard |

### 3.7. Maintenance Endpoints

| Endpoint                        | Method | Description                               |
| ------------------------------- | ------ | ----------------------------------------- |
| `/maintenance/initialize`     | POST   | Initialize the system with default data   |
| `/maintenance/reset`          | POST   | Reset the system to its initial state     |
| `/maintenance/emergency-stop` | POST   | Trigger an emergency stop of all hardware |

### 3.8. Health Endpoint

| Endpoint    | Method | Description              |
| ----------- | ------ | ------------------------ |
| `/health` | GET    | Health check for the API |

---

## 4. MQTT Communication Protocol

### 4.1. Broker Configuration

The system uses Mosquitto as the MQTT broker with the following configuration:

| Parameter                | Value                   |
| ------------------------ | ----------------------- |
| **Host**           | localhost               |
| **MQTT Port**      | 1883                    |
| **WebSocket Port** | 9001                    |
| **Authentication** | Anonymous (development) |

### 4.2. Command Topics (Controller → Hardware)

| Topic                             | Payload Example                   | Description            |
| --------------------------------- | --------------------------------- | ---------------------- |
| `stf/conveyor/cmd/start`        | `{"direction": 1}`              | Start conveyor belt    |
| `stf/conveyor/cmd/stop`         | `{}`                            | Stop conveyor belt     |
| `stf/hbw/cmd/move`              | `{"x": 100, "y": 200, "z": 50}` | Move HBW to position   |
| `stf/hbw/cmd/stop`              | `{}`                            | Stop HBW movement      |
| `stf/hbw/cmd/gripper`           | `{"close": true}`               | Control gripper        |
| `stf/vgr/cmd/move`              | `{"x": 100, "y": 200, "z": 50}` | Move VGR to position   |
| `stf/vgr/cmd/stop`              | `{}`                            | Stop VGR movement      |
| `stf/vgr/cmd/vacuum`            | `{"activate": true}`            | Control vacuum gripper |
| `stf/global/req/reset`          | `{}`                            | Reset all hardware     |
| `stf/global/req/emergency_stop` | `{}`                            | Emergency stop         |

### 4.3. Status Topics (Hardware → Controller)

| Topic                    | Description                                    |
| ------------------------ | ---------------------------------------------- |
| `stf/conveyor/status`  | Conveyor state (belt position, motor, sensors) |
| `stf/hbw/status`       | HBW state (position, motors, gripper)          |
| `stf/vgr/status`       | VGR state (position, motors, vacuum)           |
| `stf/global/emergency` | Emergency stop events                          |

### 4.4. Status Payload Examples

**Conveyor Status:**

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

**HBW Status:**

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

---

## 5. Database Schema

### 5.1. Core Tables

| Table                  | Description                         |
| ---------------------- | ----------------------------------- |
| `py_carriers`        | Cookie carriers/containers          |
| `py_cookies`         | Cookie information (flavor, status) |
| `py_inventory_slots` | Warehouse storage slots (A1-C3)     |
| `py_commands`        | Command queue for execution         |

### 5.2. Hardware State Tables

| Table                     | Description                         |
| ------------------------- | ----------------------------------- |
| `py_component_registry` | Registry of all hardware components |
| `py_motor_states`       | Current state of all motors         |
| `py_sensor_states`      | Current state of all sensors        |
| `py_hardware_states`    | State of main hardware devices      |

### 5.3. Logging Tables

| Table                    | Description                     |
| ------------------------ | ------------------------------- |
| `py_system_logs`       | System event logs               |
| `py_energy_logs`       | Energy consumption logs         |
| `py_telemetry_history` | Historical telemetry data       |
| `py_alerts`            | System alerts and notifications |

### 5.4. Command Table Schema

The `py_commands` table is central to the command queue architecture:

| Column           | Type     | Description                             |
| ---------------- | -------- | --------------------------------------- |
| `id`           | Integer  | Primary key                             |
| `command_type` | String   | Type (STORE, RETRIEVE, PROCESS)         |
| `target_slot`  | String   | Target inventory slot (e.g., A1)        |
| `payload_json` | JSON     | Additional parameters                   |
| `status`       | String   | PENDING, IN_PROGRESS, COMPLETED, FAILED |
| `created_at`   | DateTime | When command was queued                 |
| `executed_at`  | DateTime | When execution started                  |
| `completed_at` | DateTime | When command finished                   |
| `message`      | String   | Result or error message                 |

---

## 6. Complete Working Cycle Example

This section describes a complete working cycle from user action to hardware response.

### 6.1. Scenario: Processing a Cookie (RAW_DOUGH → BAKED)

**Step 1: User Action**
The user clicks the "Bake Cookie" button on the dashboard for slot 'A1'.

**Step 2: API Request**
The dashboard sends a POST request:

```http
POST /order/process
Content-Type: application/json

{
  "source_slot": "A1"
}
```

**Step 3: Command Queued**
The API creates a new command in the database:

```sql
INSERT INTO py_commands (command_type, target_slot, status, created_at)
VALUES ('PROCESS', 'A1', 'PENDING', NOW());
```

**Step 4: Controller Polling**
The main controller polls the database:

```sql
SELECT * FROM py_commands 
WHERE status = 'PENDING' 
ORDER BY created_at ASC 
LIMIT 1;
```

**Step 5: Command Execution**
The controller updates the status and begins execution:

```sql
UPDATE py_commands SET status = 'IN_PROGRESS', executed_at = NOW() WHERE id = ?;
```

**Step 6: Hardware Commands**
The controller sends MQTT commands in sequence:

1. Move HBW to slot A1:

   ```
   Topic: stf/hbw/cmd/move
   Payload: {"x": 100, "y": 100, "z": 0}
   ```
2. Close gripper to pick cookie:

   ```
   Topic: stf/hbw/cmd/gripper
   Payload: {"close": true}
   ```
3. Move to conveyor position:

   ```
   Topic: stf/hbw/cmd/move
   Payload: {"x": 350, "y": 200, "z": 0}
   ```
4. Start conveyor for baking:

   ```
   Topic: stf/conveyor/cmd/start
   Payload: {"direction": 1}
   ```
5. Wait for baking cycle (simulated)
6. Return cookie to slot

**Step 7: Status Update**
Upon completion:

```sql
UPDATE py_commands 
SET status = 'COMPLETED', completed_at = NOW(), message = 'Cookie baked successfully'
WHERE id = ?;
```

**Step 8: Dashboard Update**
The dashboard receives real-time updates via WebSocket and reflects the changes in the UI.

---

## 7. Code-Level Walkthrough

### 7.1. API Endpoint (api/main.py)

```python
@app.post("/order/process")
async def process_cookie(request: ProcessRequest, db: Session = Depends(get_db)):
    """Queue a PROCESS command for a cookie."""
    # Validate slot exists and has a RAW_DOUGH cookie
    slot = db.query(InventorySlot).filter_by(slot_name=request.source_slot).first()
    if not slot or not slot.carrier:
        raise HTTPException(status_code=404, detail="Slot empty or not found")
  
    # Create command in queue
    command = Command(
        command_type="PROCESS",
        target_slot=request.source_slot,
        payload_json=json.dumps({"action": "bake"}),
        status="PENDING",
        created_at=datetime.utcnow()
    )
    db.add(command)
    db.commit()
  
    return {"success": True, "command_id": command.id, "message": "Process command queued"}
```

### 7.2. Controller Processing (controller/main_controller.py)

```python
async def process_command(self, command: Command):
    """Execute a PROCESS command."""
    self.update_status(command, "IN_PROGRESS")
  
    try:
        # Get slot coordinates
        coords = get_slot_coordinates(command.target_slot)
      
        # Move to slot
        await self.move_hbw(coords["x"], coords["y"], 0)
        await self.wait_for_arrival("HBW")
      
        # Pick cookie
        await self.gripper_close()
        await asyncio.sleep(0.5)
      
        # Move to conveyor
        await self.move_hbw(350, 200, 0)
        await self.wait_for_arrival("HBW")
      
        # Place on conveyor
        await self.gripper_open()
      
        # Start baking process
        await self.start_conveyor(direction=1)
        await asyncio.sleep(5)  # Simulated bake time
        await self.stop_conveyor()
      
        # Pick baked cookie
        await self.gripper_close()
      
        # Return to slot
        await self.move_hbw(coords["x"], coords["y"], 0)
        await self.wait_for_arrival("HBW")
        await self.gripper_open()
      
        # Update cookie status in database
        self.update_cookie_status(command.target_slot, "BAKED")
      
        self.update_status(command, "COMPLETED", "Cookie baked successfully")
      
    except Exception as e:
        self.update_status(command, "FAILED", str(e))
```

### 7.3. MQTT Communication (hardware/mock_factory.py)

```python
def on_message(self, client, userdata, msg):
    """Handle incoming MQTT commands."""
    topic = msg.topic
    payload = json.loads(msg.payload.decode())
  
    if topic == "stf/hbw/cmd/move":
        self.hbw.move_to(payload["x"], payload["y"], payload["z"])
    elif topic == "stf/hbw/cmd/gripper":
        self.hbw.gripper_closed = payload.get("close", False)
    elif topic == "stf/conveyor/cmd/start":
        self.conveyor.start(payload.get("direction", 1))
    elif topic == "stf/conveyor/cmd/stop":
        self.conveyor.stop()

def publish_status(self):
    """Publish current hardware status via MQTT."""
    # Conveyor status
    conveyor_state = self.conveyor.tick(self.tick_interval)
    self.client.publish("stf/conveyor/status", json.dumps(conveyor_state))
  
    # HBW status
    hbw_state = self.hbw.tick(self.tick_interval)
    self.client.publish("stf/hbw/status", json.dumps(hbw_state))
```

---

## Appendix A: Running the System

### A.1. Prerequisites

- Python 3.11+
- Docker and Docker Compose
- Node.js (optional, for Node-RED integration)

### A.2. Quick Start (with SQLite)

This setup uses the local SQLite database file (`stf_digital_twin.db`).

```bash
# Install Python dependencies
pip install -r requirements.txt

# Initialize database (if it doesn't exist)
python scripts/generate_history.py

# Start API server
# The API will automatically use the SQLite database
uvicorn api.main:app --host 0.0.0.0 --port 8000

# Start controller (in separate terminal)
python controller/main_controller.py

# Start mock hardware (in separate terminal)
python hardware/mock_factory.py

# Start dashboard (in separate terminal)
streamlit run dashboard/app.py
```

### A.3. Quick Start (with Docker - MySQL + Mosquitto)

This setup uses Docker to run MySQL and Mosquitto services.

```bash
# Set environment variables for MySQL
export DATABASE_URL="mysql+pymysql://stf_user:stf_password@localhost:3306/stf_warehouse"

# Start infrastructure (MySQL + Mosquitto)
docker-compose up -d

# Install Python dependencies
pip install -r requirements.txt

# Initialize database
python scripts/generate_history.py

# Start API server
uvicorn api.main:app --host 0.0.0.0 --port 8000

# Start controller (in separate terminal)
python controller/main_controller.py

# Start mock hardware (in separate terminal)
python hardware/mock_factory.py

# Start dashboard (in separate terminal)
streamlit run dashboard/app.py
```

### A.4. Running Tests

To run the validation test suite with the default SQLite database:

```bash
# Run tests with default SQLite DB
python test.py --api-url http://localhost:8000
```

To specify a different SQLite database file:

```bash
# Run tests with a specific SQLite DB file
python test.py --api-url http://localhost:8000 --db-path /path/to/your/database.db
```

---

## Appendix B: Troubleshooting

| Issue                      | Solution                                            |
| -------------------------- | --------------------------------------------------- |
| API not responding         | Check if uvicorn is running on port 8000            |
| Database connection failed | Verify MySQL is running and credentials are correct |
| MQTT connection refused    | Ensure Mosquitto is running on port 1883            |
| Dashboard not updating     | Check WebSocket connection in browser console       |
| Commands stuck in PENDING  | Verify controller is running and polling database   |

---

*Document generated by Manus AI - January 2026*
