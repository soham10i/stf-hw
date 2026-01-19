# ST-HW System Documentation

This document provides a comprehensive overview of the ST-HW (Smart Tabletop Factory Hardware) system, including its architecture, modules, APIs, MQTT communication, and database schema.

## 1. System Architecture

The ST-HW system is designed with a decoupled, event-driven architecture that separates the user interface, backend logic, and hardware control. This design enhances scalability, reliability, and maintainability.

The core components of the architecture are:

-   **Frontend Dashboard (Streamlit)**: A web-based user interface for monitoring and controlling the factory.
-   **Backend API (FastAPI)**: A RESTful API that provides endpoints for the frontend to interact with the system.
-   **Main Controller**: A Python script that processes commands from a queue, ensuring sequential and orderly execution of tasks.
-   **Database (SQLite)**: A local SQLite database (`stf_digital_twin.db`) that stores the system's state, including inventory, hardware status, and logs. MySQL is optionally supported for production deployments.
-   **MQTT Broker (Mosquitto)**: A message broker that facilitates communication between the main controller and the hardware.
-   **Hardware (Mock/Physical)**: The physical or simulated hardware components of the factory.

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

## 2. Module Descriptions

### 2.1. API (`api/`)

The API module, built with FastAPI, serves as the primary interface for the frontend. It exposes a set of RESTful endpoints for managing the factory's resources and operations. The API is responsible for handling user requests, validating data, and interacting with the database.

**Key Files:**

-   `api/main.py`: Defines all the API endpoints, data models (Pydantic), and WebSocket communication for real-time updates.

### 2.2. Controller (`controller/`)

The controller is the brain of the system. It's a standalone Python script that continuously polls the database for pending commands and executes them in a sequential manner. This ensures that operations are performed in the correct order and prevents conflicts between different parts of the system.

**Key Files:**

-   `controller/main_controller.py`: Implements the main control loop, command execution logic, and communication with the hardware via MQTT.

### 2.3. Dashboard (`dashboard/`)

The dashboard is a web-based user interface built with Streamlit. It provides a real-time view of the factory's status, including inventory, hardware positions, and system logs. Users can also use the dashboard to issue commands to the factory, such as storing or retrieving cookies.

**Key Files:**

-   `dashboard/app.py`: The main dashboard application, displaying real-time data.
-   `dashboard/pages/analytics.py`: A separate page for historical data analysis and visualization.

### 2.4. Database (`database/`)

The database module defines the data models (SQLAlchemy) and provides functions for interacting with the database. It uses SQLite by default (storing data in `stf_digital_twin.db`), with optional MySQL support for production.

**Key Files:**

-   `database/models.py`: Defines the SQLAlchemy models for all the tables in the database.
-   `database/connection.py`: Manages the database connection and session.

### 2.5. Hardware (`hardware/`)

The hardware module contains the simulation code for the factory's hardware components. This allows the system to be tested and developed without the need for physical hardware.

**Key Files:**

-   `hardware/mock_factory.py`: Simulates the behavior of the conveyor, HBW (High-Bay Warehouse), and VGR (Vacuum Gripper Robot).

### 2.6. Scripts (`scripts/`)

The scripts module contains utility scripts for tasks such as generating historical data for testing and demonstration purposes.

**Key Files:**

-   `scripts/generate_history.py`: A script to populate the database with synthetic data.

## 3. API Endpoints

The following table lists the main API endpoints provided by the system:

| Endpoint | Method | Description |
|---|---|---|
| `/ws` | WebSocket | Real-time updates for the dashboard. |
| `/components/specs` | GET | Get static specification data for all components. |
| `/motors/state` | POST | Update motor state and broadcast via WebSocket. |
| `/sensors/state` | POST | Update sensor state and broadcast via WebSocket. |
| `/conveyor/state` | POST | Update full conveyor state (motor + sensors) and broadcast. |
| `/hardware/state` | POST | Update hardware state and broadcast via WebSocket. |
| `/telemetry` | POST | Record telemetry data. |
| `/energy` | POST | Record energy consumption data. |
| `/inventory` | GET | Get the current inventory status. |
| `/order/store` | POST | Store a cookie in the warehouse. |
| `/order/retrieve` | POST | Retrieve a cookie from the warehouse. |
| `/order/process` | POST | Process a cookie (e.g., from raw dough to baked). |
| `/dashboard/data` | GET | Get all data required for the dashboard. |
| `/maintenance/initialize` | POST | Initialize the system with default data. |
| `/maintenance/reset` | POST | Reset the system to its initial state. |
| `/maintenance/emergency-stop` | POST | Trigger an emergency stop of all hardware. |
| `/health` | GET | Health check for the API. |

## 4. MQTT Communication

MQTT is used for communication between the main controller and the hardware. The controller publishes commands to specific topics, and the hardware subscribes to these topics to receive instructions. The hardware then publishes its status to other topics, which the controller subscribes to for monitoring.

### 4.1. Command Topics (Controller -> Hardware)

| Topic | Description |
|---|---|
| `stf/hbw/cmd/move` | Move the High-Bay Warehouse (HBW) to a specific position. |
| `stf/hbw/cmd/gripper` | Control the HBW's gripper (open/close). |
| `stf/conveyor/cmd/belt` | Control the conveyor belt (start/stop). |

### 4.2. Status Topics (Hardware -> Controller)

| Topic | Description |
|---|---|
| `stf/hbw/status` | Publishes the current status of the HBW (position, etc.). |
| `stf/vgr/status` | Publishes the current status of the VGR. |
| `stf/conveyor/status` | Publishes the current status of the conveyor. |
| `stf/global/emergency` | Publishes emergency stop events. |

## 5. Database Interaction

The system uses a database (MySQL or SQLite) to store its state. The database schema is defined using SQLAlchemy ORM, which maps Python classes to database tables.

The main tables in the database are:

-   `py_carriers`: Stores information about the carriers that hold cookies.
-   `py_cookies`: Stores information about the cookies, including their flavor and status.
-   `py_inventory_slots`: Represents the storage slots in the warehouse.
-   `py_component_registry`: A registry of all hardware components in the system.
-   `py_motor_states`: Stores the current state of all motors.
-   `py_sensor_states`: Stores the current state of all sensors.
-   `py_hardware_states`: Stores the current state of the main hardware components (HBW, VGR, Conveyor).
-   `py_system_logs`: A log of all system events.
-   `py_energy_logs`: A log of energy consumption data.
-   `py_telemetry_history`: A history of telemetry data from the hardware.
-   `py_alerts`: A log of system alerts.
-   `py_commands`: The command queue, which stores commands to be executed by the controller.

## 6. Complete Working Cycle Example

This section describes a complete working cycle of the system, from a user request to the final hardware action.

**Scenario:** A user wants to process a raw dough cookie.

1.  **User Action**: The user clicks the "Bake Cookie" button on the dashboard for a specific slot (e.g., 'A1').
2.  **API Request**: The dashboard sends a `POST` request to the `/order/process` endpoint with the `source_slot` set to 'A1'.
3.  **Command Queued**: The API creates a new command in the `py_commands` table with `command_type` as 'PROCESS', `target_slot` as 'A1', and `status` as 'PENDING'.
4.  **Controller Polling**: The `main_controller` polls the database and finds the pending command.
5.  **Command Execution**: The controller updates the command's status to 'IN_PROGRESS' and begins executing the 'PROCESS' command workflow:
    a.  **Move to Slot**: The controller publishes a message to the `stf/hbw/cmd/move` MQTT topic to move the HBW to the coordinates of slot 'A1'.
    b.  **Pick Cookie**: The controller sends a sequence of gripper commands via MQTT to pick up the cookie.
    c.  **Move to Conveyor**: The controller moves the HBW to the conveyor's position.
    d.  **Place on Conveyor**: The controller places the cookie on the conveyor.
    e.  **Start Conveyor**: The controller starts the conveyor to simulate the baking process.
    f.  **Wait for Baking**: The controller waits for a simulated baking time.
    g.  **Pick from Conveyor**: The controller picks the baked cookie from the conveyor.
    h.  **Return to Slot**: The controller returns the baked cookie to its original slot.
6.  **Status Update**: Once the entire process is complete, the controller updates the command's status to 'COMPLETED' in the database.
7.  **Dashboard Update**: The dashboard, which is connected to the API via WebSocket, receives real-time updates throughout this process and reflects the changes in the UI (e.g., the cookie's status changes from 'RAW_DOUGH' to 'BAKED').

This example demonstrates the decoupled nature of the system, where the API, controller, and hardware work together through a combination of REST, WebSockets, a database, and MQTT.
