# STF Digital Twin - Project TODO

## Database Layer
- [x] Carrier table (id, current_zone, is_locked)
- [x] Cookie table (batch_uuid, carrier_id, flavor, expiry_date, status)
- [x] InventorySlot table (slot_name, x_pos, y_pos, carrier_id)
- [x] HardwareState table (device_id, current_position, status)
- [x] TelemetryHistory table (time-series optimized for trend analysis)
- [x] EnergyLog table (energy consumption tracking)
- [x] AlertLog table (critical events and notifications)

## Backend API (tRPC)
- [x] GET inventory - list all slots with carrier/cookie info
- [x] POST order/create - create cookie and assign to carrier
- [x] POST maintenance/reset - reset hardware positions
- [x] Hardware state management procedures
- [x] Telemetry data ingestion endpoints
- [x] Alert/notification triggers
- [x] Historical data queries for analytics

## Dashboard UI
- [x] Industrial dark theme design
- [x] Live 2D visualization of robot positions (scatter plot)
- [x] Inventory grid display (3x3) with color-coded slots
- [x] Control panel with Store/Retrieve buttons
- [x] Auto-refresh mechanism (1 second interval)
- [x] Hardware status indicators
- [x] Energy consumption display
- [x] Alert notifications panel
- [x] Historical trend charts

## Python Simulation Services
- [x] mock_hbw.py - AsyncIO physics simulation at 10Hz
- [x] MQTT client for command subscription (stf/hbw/cmd/#)
- [x] Telemetry publishing (stf/hbw/status)
- [x] main_controller.py - FSM logic and command translation
- [x] Safety interlock (collision prevention)
- [x] Energy logging calculations
- [x] Coordinate mapping system (slot name to X/Y)

## Infrastructure
- [x] Docker Compose for MySQL (port 3306)
- [x] Docker Compose for Mosquitto MQTT (port 1883)
- [x] Docker Compose for Adminer (optional)
- [x] Environment configuration (.env)
- [x] Requirements.txt for Python dependencies

## Notifications & Monitoring
- [x] Hardware error notifications
- [x] Collision prevention alerts
- [x] Inventory threshold warnings
- [x] Maintenance requirement alerts
- [x] Owner notification integration

## Documentation
- [x] README with setup instructions
- [x] Execution instructions for multi-process architecture
- [x] API documentation

## Phase 2: Python STF Digital Twin (Glassmorphism)

### SQLAlchemy Database Layer
- [x] Create stf_warehouse/database/models.py with SQLAlchemy ORM
- [x] InventorySlot model (slot_name PK, x_pos, y_pos, carrier_id FK)
- [x] Carrier model (id PK, current_zone, is_locked)
- [x] Cookie model (batch_uuid PK, flavor Enum, status Enum)
- [x] HardwareState model (device_id PK, current_x, current_y, current_z, status)
- [x] SystemLog model (id, timestamp, level, message)
- [x] EnergyLog model (id, device_id, joules, voltage, timestamp)
- [x] TelemetryHistory model (time-series optimized)
- [x] Alert model with severity levels
- [x] Command model for tracking operations

### FastAPI REST API
- [x] POST /hardware/state - Update hardware position
- [x] GET /hardware/states - Get all hardware states
- [x] POST /telemetry - Record telemetry data
- [x] POST /energy - Record energy consumption
- [x] GET /inventory - List all inventory slots
- [x] POST /order/store - Store cookie in slot
- [x] POST /order/retrieve - Retrieve cookie from slot
- [x] GET /dashboard/data - Combined dashboard data
- [x] POST /maintenance/reset - Reset hardware positions
- [x] POST /maintenance/emergency-stop - Emergency stop

### Streamlit Glassmorphism Dashboard
- [x] Industrial Apple design with frosted glass effects
- [x] Custom CSS with backdrop-filter blur
- [x] KPI cards with glass styling
- [x] Live 2D robot position scatter plot
- [x] 3x3 inventory grid with color-coded slots
- [x] Control deck with store/retrieve buttons
- [x] Hardware status panel
- [x] Recent activity log
- [x] Auto-refresh mechanism

### Mock Hardware Simulation
- [x] AsyncIO-based physics at 10Hz
- [x] MQTT command subscription
- [x] HTTP API state sync
- [x] Energy consumption tracking
- [x] MockHBW, MockVGR, MockConveyor classes

### Main Controller
- [x] FSM state machine logic
- [x] Command translation (slot to coordinates)
- [x] Collision prevention safety interlock
- [x] MQTT command publishing
- [x] API state synchronization

### Infrastructure
- [x] Docker Compose (MySQL, Mosquitto, Adminer)
- [x] Mosquitto configuration
- [x] Python requirements.txt
- [x] Run script for all services
- [x] README documentation


## Phase 3: Analytics, Cleanup & Documentation

### Historical Analytics Page
- [x] Create analytics.py Streamlit page
- [x] Energy consumption time-series charts
- [x] Production throughput visualization
- [x] Hardware utilization metrics
- [x] Predictive maintenance insights
- [x] Date range filtering
- [x] Export data functionality

### Project Cleanup
- [x] Remove React client folder
- [x] Remove tRPC server code
- [x] Remove Node.js dependencies
- [x] Reorganize as pure Python project
- [x] Update project structure

### Setup Documentation
- [x] Windows setup instructions
- [x] macOS setup instructions
- [x] Local MySQL installation guide
- [x] Docker alternative setup
- [x] Environment configuration guide
- [x] Troubleshooting section


## Phase 3: High-Fidelity Component Twin Upgrade

### Database Architecture
- [x] Create `component_registry` table (id, name, subsystem, type, spec_voltage, spec_max_current, maintenance_interval_hours)
- [x] Add `health_score` (0.0-1.0) to MotorState
- [x] Add `accumulated_runtime_sec` to MotorState
- [x] Update Cookie lifecycle states (RAW_DOUGH → BAKED → PACKAGED)
- [x] Seed 12 components: HBW (4), CONVEYOR (5), VGR (5)
- [x] Seed all 9 warehouse slots with RAW_DOUGH cookies

### Physics Engine Simulation
- [x] Rename mock_hbw.py to mock_factory.py
- [x] Implement conveyor belt physics (belt_position_mm 0-1000mm)
- [x] Implement 4 light sensors based on belt position
- [x] Implement electrical simulation (Idle: 0.05A, Startup: 2.5A, Moving: 1.2A)
- [x] Implement anomaly injection when health_score < 0.8
- [x] Implement preventive maintenance model (health degradation)
- [x] Implement micro-stoppages when health_score < 0.5

### WebSocket Real-Time API
- [x] Implement ConnectionManager for WebSocket clients
- [x] Create WebSocket endpoint at /ws
- [x] Implement broadcast strategy for hardware state updates
- [x] Add GET /components/specs endpoint
- [x] Add POST /order/process endpoint for cookie lifecycle

### Dashboard Enhancements
- [x] Replace polling with WebSocket client thread (fallback polling implemented)
- [x] Add conveyor belt progress bar visualization
- [x] Add 4 sensor indicators for conveyor
- [x] Add "Time to Failure" estimations for motors
- [x] Add live power gauge with current draw
- [x] Add spec_max_current limit line to power chart

### Hardware Bridge Documentation
- [x] Create docs/HARDWARE_BRIDGE.md
- [x] Document Node-RED strategy for RevPi integration
- [x] Explain API (MQTT) → Node-RED → RevPi DIO/AIO flow
- [x] Provide sample Node-RED flow JSON for conveyor motor


## Phase 4: 3D CAD-like Visualization

### Plotly 3D Visualization
- [x] Create `visualization_3d.py` Streamlit page
- [x] Implement 3D warehouse geometry builder
- [x] Add storage rack frame with vertical posts and shelves
- [x] Add 3x3 storage slot visualization with inventory colors
- [x] Add robot arm (carriage, telescopic arm, gripper)
- [x] Add conveyor belt with moving item
- [x] Add 4 light barrier sensor indicators
- [x] Add floor and guide rails
- [x] Implement camera presets (Isometric, Front, Side, Top, Robot Focus)
- [x] Connect to API for real-time position updates
- [x] Add auto-refresh capability

### PyVista CAD Visualization (Alternative)
- [x] Create `visualization_3d_pyvista.py` Streamlit page
- [x] Implement PyVista mesh generation for warehouse components
- [x] Add VTK-based high-quality rendering
- [x] Integrate with stpyvista for Streamlit embedding

### Standalone Demo
- [x] Create `demo_3d_visualization.py` standalone demo
- [x] Implement interactive robot controls
- [x] Add conveyor belt animation
- [x] Add inventory grid visualization
- [x] Add gripper extend/retract controls

### Documentation
- [x] Create `docs/3D_VISUALIZATION.md`
- [x] Document Plotly vs PyVista options
- [x] Document camera controls and presets
- [x] Document customization options
- [x] Update requirements.txt with 3D dependencies
