# SQLite Database Setup Guide

This guide explains how to use the ST-HW system with SQLite databases instead of MySQL.

## Overview

The ST-HW system supports both MySQL and SQLite databases. By default, if no `DATABASE_URL` environment variable is set, the system will use a local SQLite database file named `stf_digital_twin.db`.

## Database Files

The system uses the following SQLite database files:

| Database File | Purpose |
|---------------|---------|
| `stf_digital_twin.db` | Main operational database containing inventory, commands, hardware states, and logs |
| `stf_warehouse.db` | Alternative database file (same schema as stf_digital_twin.db) |

Both databases have identical schemas and can be used interchangeably.

## Configuration

### Method 1: Using Default SQLite (Recommended)

Simply run the system without setting any environment variables. The system will automatically create and use `./stf_digital_twin.db`.

```bash
# No configuration needed - just start the services
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### Method 2: Specifying a Custom SQLite Database

Set the `DATABASE_URL` environment variable to point to your SQLite database file:

```bash
# Use a specific SQLite database file
export DATABASE_URL="sqlite:///./stf_warehouse.db"

# Or use an absolute path
export DATABASE_URL="sqlite:////home/user/databases/my_factory.db"

# Start the API server
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### Method 3: Using MySQL (Docker)

If you prefer to use MySQL instead of SQLite:

```bash
# Start MySQL with Docker Compose
docker-compose up -d mysql

# Set the DATABASE_URL for MySQL
export DATABASE_URL="mysql+pymysql://stf_user:stf_password@localhost:3306/stf_warehouse"

# Start the API server
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

## Database Schema

The SQLite database contains the following tables:

### Core Tables

- `py_carriers` - Cookie carriers/containers
- `py_cookies` - Cookie information (flavor, status, batch UUID)
- `py_inventory_slots` - Warehouse storage slots (A1-C3)
- `py_commands` - Command queue for asynchronous execution

### Hardware State Tables

- `py_component_registry` - Registry of all hardware components
- `py_motor_states` - Current state of all motors
- `py_sensor_states` - Current state of all sensors
- `py_hardware_states` - State of main hardware devices (HBW, VGR, Conveyor)

### Logging Tables

- `py_system_logs` - System event logs
- `py_energy_logs` - Energy consumption logs
- `py_telemetry_history` - Historical telemetry data
- `py_alerts` - System alerts and notifications

## Initializing the Database

If you're starting with a fresh database, you need to initialize it with the required tables and seed data:

```bash
# Initialize the database with seed data
python scripts/generate_history.py

# Or use the API endpoint
curl -X POST http://localhost:8000/maintenance/initialize
```

## Inspecting the Database

You can use the `sqlite3` command-line tool to inspect the database:

```bash
# Open the database
sqlite3 stf_digital_twin.db

# List all tables
.tables

# View schema of a specific table
.schema py_commands

# Query data
SELECT * FROM py_inventory_slots;

# Exit
.quit
```

## Backing Up the Database

SQLite databases are single files, making backups simple:

```bash
# Create a backup
cp stf_digital_twin.db stf_digital_twin_backup_$(date +%Y%m%d).db

# Or use SQLite's backup command
sqlite3 stf_digital_twin.db ".backup stf_digital_twin_backup.db"
```

## Running Tests with SQLite

The test suite supports SQLite databases:

```bash
# Run tests with the default SQLite database
python test.py --api-url http://localhost:8000

# Run tests with a specific SQLite database file
python test.py --api-url http://localhost:8000 --db-path ./stf_warehouse.db

# Run tests with an absolute path
python test.py --api-url http://localhost:8000 --db-path /home/user/databases/test.db
```

## Advantages of SQLite

**Pros:**
- No separate database server required
- Simple setup - just a single file
- Perfect for development and testing
- Easy to backup and share
- Zero configuration
- Portable across platforms

**Cons:**
- Not suitable for high-concurrency production environments
- Limited scalability compared to MySQL
- No network access (local file only)

## Advantages of MySQL

**Pros:**
- Better for production environments
- Supports multiple concurrent connections
- Better scalability
- Network access support
- Advanced features (replication, clustering)

**Cons:**
- Requires separate database server
- More complex setup
- Requires configuration and credentials

## Switching Between SQLite and MySQL

To switch from SQLite to MySQL:

```bash
# 1. Export data from SQLite (if needed)
sqlite3 stf_digital_twin.db .dump > backup.sql

# 2. Start MySQL
docker-compose up -d mysql

# 3. Set DATABASE_URL
export DATABASE_URL="mysql+pymysql://stf_user:stf_password@localhost:3306/stf_warehouse"

# 4. Initialize MySQL database
python scripts/generate_history.py

# 5. Start services
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

To switch from MySQL to SQLite:

```bash
# 1. Unset DATABASE_URL (or set it to SQLite)
unset DATABASE_URL
# OR
export DATABASE_URL="sqlite:///./stf_digital_twin.db"

# 2. Initialize SQLite database
python scripts/generate_history.py

# 3. Start services
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

## Troubleshooting

### Database is locked

If you see "database is locked" errors:

1. Make sure only one process is writing to the database at a time
2. Close any SQLite browser tools that might have the database open
3. Check for zombie processes: `ps aux | grep python`

### Database file not found

If the system can't find the database file:

1. Check the current working directory: `pwd`
2. Use an absolute path in DATABASE_URL
3. Verify the file exists: `ls -la *.db`

### Permission denied

If you get permission errors:

```bash
# Fix file permissions
chmod 644 stf_digital_twin.db

# Fix directory permissions
chmod 755 $(dirname stf_digital_twin.db)
```

---

*Document generated by Manus AI - January 2026*
