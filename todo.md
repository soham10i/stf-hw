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
