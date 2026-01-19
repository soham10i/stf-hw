"""
STF Digital Twin - Synthetic Data Generator

Generates 30 days of historical data for the Analytics Dashboard, including:
- ~50 orders per day (inventory in/out events)
- Energy consumption logs (Voltage x Amps x Time)
- Motor health degradation over time
- Two breakdown scenarios:
  - Day 12: Motor Failure (CONV_M1 spike to 4.5A, health drops to 40%)
  - Day 25: Sensor Drift (CONV_L2_PROCESS ghost readings)
- Predictive maintenance alerts when health_score < 0.5

Usage:
    python scripts/generate_history.py [--days 30] [--orders-per-day 50]
"""

import argparse
import json
import os
import random
import sys
from datetime import datetime, timedelta
from typing import List, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import (
    Base, Carrier, Cookie, CookieFlavor, CookieStatus,
    InventorySlot, HardwareState, HardwareStatus, SystemLog, LogLevel,
    EnergyLog, TelemetryHistory, Alert, AlertSeverity, Command,
    ComponentRegistry, MotorState, SensorState, SubsystemType, ComponentType,
    seed_inventory_slots, seed_components, seed_hardware_devices,
)

# Configuration
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./stf_digital_twin.db")

# Constants
FLAVORS = list(CookieFlavor)
SLOTS = ["A1", "A2", "A3", "B1", "B2", "B3", "C1", "C2", "C3"]
MOTORS = ["HBW_M1_X", "HBW_M2_Y", "CONV_M1", "VGR_M1_ARM", "VGR_M2_GRIP"]
SENSORS = ["CONV_L1_ENTRY", "CONV_L2_PROCESS", "CONV_L3_EXIT", "CONV_L4_OVERFLOW"]

# Breakdown scenarios
BREAKDOWN_DAY_MOTOR = 12  # Day 12: Motor failure
BREAKDOWN_DAY_SENSOR = 25  # Day 25: Sensor drift


def create_session():
    """Create database session."""
    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def seed_core_tables(db):
    """Seed all core operational tables."""
    print("\n  Seeding core tables...")
    
    # Seed inventory slots (A1-C3)
    print("    - Inventory slots (A1-C3)")
    seed_inventory_slots(db)
    
    # Seed component registry + motor states + sensor states
    print("    - Component registry, motor states, sensor states")
    seed_components(db)
    
    # Seed hardware devices (HBW, VGR, CONVEYOR)
    print("    - Hardware devices (HBW, VGR, CONVEYOR)")
    seed_hardware_devices(db)
    
    print("  Core tables seeded successfully!\n")


def generate_order_event(
    db,
    timestamp: datetime,
    order_type: str,
    slot_name: str,
    flavor: CookieFlavor,
) -> None:
    """
    Generate a single order event with associated records.
    
    Parameters
    ----------
    db : Session
        Database session.
    timestamp : datetime
        Event timestamp.
    order_type : str
        Type of order (STORE, RETRIEVE, PROCESS).
    slot_name : str
        Target slot name.
    flavor : CookieFlavor
        Cookie flavor.
    """
    # Create command record
    command = Command(
        command_type=order_type,
        target_slot=slot_name,
        payload_json=json.dumps({"flavor": flavor.value, "generated": True}),
        status="COMPLETED",
        created_at=timestamp,
        executed_at=timestamp + timedelta(seconds=random.randint(1, 5)),
        completed_at=timestamp + timedelta(seconds=random.randint(10, 30)),
    )
    db.add(command)
    
    # Create system log
    log = SystemLog(
        timestamp=timestamp,
        level=LogLevel.INFO,
        source="CONTROLLER",
        message=f"[SYNTHETIC] {order_type} {flavor.value} in {slot_name}",
    )
    db.add(log)


def generate_energy_log(
    db,
    timestamp: datetime,
    device_id: str,
    duration_sec: float,
    current_amps: float,
    voltage: float = 24.0,
) -> None:
    """
    Generate energy consumption log.
    
    Energy (Joules) = Voltage x Current x Time
    
    Parameters
    ----------
    db : Session
        Database session.
    timestamp : datetime
        Event timestamp.
    device_id : str
        Device identifier.
    duration_sec : float
        Operation duration in seconds.
    current_amps : float
        Current draw in Amps.
    voltage : float
        Voltage (default 24V).
    """
    joules = voltage * current_amps * duration_sec
    power_watts = voltage * current_amps
    
    energy_log = EnergyLog(
        timestamp=timestamp,
        device_id=device_id,
        joules=joules,
        voltage=voltage,
        current_amps=current_amps,
        power_watts=power_watts,
    )
    db.add(energy_log)


def generate_telemetry(
    db,
    timestamp: datetime,
    device_id: str,
    metric_name: str,
    metric_value: float,
    unit: str = None,
) -> None:
    """Generate telemetry history record."""
    telemetry = TelemetryHistory(
        timestamp=timestamp,
        device_id=device_id,
        metric_name=metric_name,
        metric_value=metric_value,
        unit=unit,
    )
    db.add(telemetry)


def generate_motor_state_history(
    db,
    timestamp: datetime,
    component_id: str,
    health_score: float,
    current_amps: float,
    is_active: bool,
    accumulated_runtime: float,
) -> None:
    """Generate motor state telemetry."""
    # Health score telemetry
    generate_telemetry(db, timestamp, component_id, "health_score", health_score, "%")
    generate_telemetry(db, timestamp, component_id, "current_amps", current_amps, "A")
    generate_telemetry(db, timestamp, component_id, "runtime", accumulated_runtime, "s")


def generate_alert(
    db,
    timestamp: datetime,
    alert_type: str,
    severity: AlertSeverity,
    title: str,
    message: str,
    component_id: str = None,
) -> None:
    """Generate an alert record."""
    alert = Alert(
        created_at=timestamp,
        alert_type=alert_type,
        severity=severity,
        title=title,
        message=message,
        device_id=component_id,
        acknowledged=random.random() > 0.3,  # 70% acknowledged
        acknowledged_at=timestamp + timedelta(hours=random.randint(1, 24)) if random.random() > 0.3 else None,
    )
    db.add(alert)


def simulate_motor_failure(db, day: int, base_date: datetime) -> dict:
    """
    Simulate motor failure scenario on Day 12.
    
    Scenario A: CONV_M1 Motor Failure
    - Current spikes to 4.5A for 4 hours
    - Health score drops from 90% to 40%
    
    Returns
    -------
    dict
        Updated motor states for the day.
    """
    motor_states = {}
    
    if day == BREAKDOWN_DAY_MOTOR:
        print(f"  [!] Day {day}: Simulating CONV_M1 motor failure")
        
        # Generate 4 hours of high current readings
        failure_start = base_date + timedelta(hours=8)  # Start at 8 AM
        
        for hour in range(4):
            ts = failure_start + timedelta(hours=hour)
            
            # High current spike
            current = 4.5 + random.uniform(-0.2, 0.2)
            generate_energy_log(db, ts, "CONV_M1", 3600, current)
            
            # Rapid health degradation
            health = 0.9 - (hour * 0.125)  # 90% -> 40% over 4 hours
            generate_motor_state_history(
                db, ts, "CONV_M1",
                health_score=health,
                current_amps=current,
                is_active=True,
                accumulated_runtime=hour * 3600,
            )
            
            # Generate warning alerts
            if hour == 0:
                generate_alert(
                    db, ts, "OVERCURRENT", AlertSeverity.MEDIUM,
                    "High Current Detected: CONV_M1",
                    f"Motor current at {current:.2f}A exceeds normal operating range (1.5A)",
                    "CONV_M1"
                )
            elif hour == 2:
                generate_alert(
                    db, ts, "HEALTH_DEGRADATION", AlertSeverity.CRITICAL,
                    "Rapid Health Degradation: CONV_M1",
                    f"Motor health dropped to {health*100:.0f}%. Immediate inspection required.",
                    "CONV_M1"
                )
        
        motor_states["CONV_M1"] = {"health": 0.4, "current": 4.5}
        
        # Generate predictive maintenance alert
        generate_alert(
            db, failure_start + timedelta(hours=4),
            "PREDICTIVE_MAINTENANCE", AlertSeverity.CRITICAL,
            "Predictive Maintenance Required: Conveyor Motor",
            "CONV_M1 health score below 50%. Schedule maintenance within 24 hours to prevent failure.",
            "CONV_M1"
        )
    
    return motor_states


def simulate_sensor_drift(db, day: int, base_date: datetime) -> None:
    """
    Simulate sensor drift scenario on Day 25.
    
    Scenario B: CONV_L2_PROCESS Sensor Drift
    - Intermittent ghost readings when belt is idle
    - Simulates sensor malfunction/calibration issue
    """
    if day == BREAKDOWN_DAY_SENSOR:
        print(f"  [!] Day {day}: Simulating CONV_L2_PROCESS sensor drift")
        
        # Generate ghost readings throughout the day
        for hour in range(24):
            ts = base_date + timedelta(hours=hour)
            
            # Random ghost triggers (more frequent during certain hours)
            ghost_count = random.randint(3, 8) if 10 <= hour <= 18 else random.randint(0, 2)
            
            for _ in range(ghost_count):
                ghost_ts = ts + timedelta(minutes=random.randint(0, 59))
                
                # Log ghost reading
                generate_telemetry(
                    db, ghost_ts, "CONV_L2_PROCESS",
                    "ghost_trigger", 1.0, "count"
                )
                
                # System log
                log = SystemLog(
                    timestamp=ghost_ts,
                    level=LogLevel.WARNING,
                    source="SENSOR",
                    message=f"[SYNTHETIC] Ghost trigger on CONV_L2_PROCESS (belt idle)",
                )
                db.add(log)
        
        # Generate drift alert
        generate_alert(
            db, base_date + timedelta(hours=14),
            "SENSOR_DRIFT", AlertSeverity.MEDIUM,
            "Sensor Calibration Required: CONV_L2_PROCESS",
            "Multiple false triggers detected. Sensor may require recalibration or replacement.",
            "CONV_L2_PROCESS"
        )


def generate_daily_data(
    db,
    day: int,
    base_date: datetime,
    orders_per_day: int,
    motor_health: dict,
) -> dict:
    """
    Generate all data for a single day.
    
    Parameters
    ----------
    db : Session
        Database session.
    day : int
        Day number (1-30).
    base_date : datetime
        Start of the day.
    orders_per_day : int
        Target number of orders.
    motor_health : dict
        Current motor health states.
    
    Returns
    -------
    dict
        Updated motor health states.
    """
    print(f"  Generating Day {day}: {base_date.strftime('%Y-%m-%d')}")
    
    # Simulate breakdown scenarios
    breakdown_states = simulate_motor_failure(db, day, base_date)
    simulate_sensor_drift(db, day, base_date)
    
    # Update motor health from breakdown
    for motor_id, state in breakdown_states.items():
        motor_health[motor_id] = state
    
    # Generate orders throughout the day (8 AM - 6 PM)
    work_hours = 10  # 8 AM to 6 PM
    orders_generated = 0
    
    for i in range(orders_per_day):
        # Random time during work hours
        hour_offset = random.uniform(0, work_hours)
        order_time = base_date + timedelta(hours=8 + hour_offset)
        
        # Random order type
        order_type = random.choices(
            ["STORE", "RETRIEVE", "PROCESS"],
            weights=[0.3, 0.3, 0.4]  # 40% process orders
        )[0]
        
        slot = random.choice(SLOTS)
        flavor = random.choice(FLAVORS)
        
        generate_order_event(db, order_time, order_type, slot, flavor)
        orders_generated += 1
        
        # Generate associated energy consumption
        duration = random.uniform(5, 30)  # 5-30 seconds per operation
        
        # Normal current draw (varies by operation)
        if order_type == "PROCESS":
            current = random.uniform(1.2, 1.8)  # Higher for processing
        else:
            current = random.uniform(0.8, 1.2)
        
        # Check for motor failure day - use elevated current
        if day == BREAKDOWN_DAY_MOTOR and "CONV_M1" in motor_health:
            if random.random() > 0.5:  # 50% of operations affected
                current = random.uniform(3.5, 4.5)
        
        generate_energy_log(db, order_time, "HBW", duration, current)
        
        # Also log conveyor energy for process orders
        if order_type == "PROCESS":
            conv_current = motor_health.get("CONV_M1", {}).get("current", random.uniform(1.0, 1.5))
            generate_energy_log(db, order_time, "CONV_M1", duration * 0.5, conv_current)
    
    # Generate hourly motor health telemetry
    for hour in range(24):
        ts = base_date + timedelta(hours=hour)
        
        for motor_id in MOTORS:
            # Get or calculate health score
            if motor_id in motor_health:
                health = motor_health[motor_id].get("health", 1.0)
            else:
                # Normal degradation: ~0.01% per hour
                base_health = 1.0 - (day * 0.001)
                health = max(0.5, base_health + random.uniform(-0.02, 0.02))
            
            # Normal current when not in failure
            if motor_id in motor_health and "current" in motor_health[motor_id]:
                current = motor_health[motor_id]["current"]
            else:
                current = random.uniform(0.05, 0.3) if hour < 8 or hour > 18 else random.uniform(0.8, 1.5)
            
            generate_motor_state_history(
                db, ts, motor_id,
                health_score=health,
                current_amps=current,
                is_active=8 <= hour <= 18,
                accumulated_runtime=day * 10 * 3600 + hour * 600,  # Rough estimate
            )
            
            # Generate predictive maintenance alert if health < 0.5
            if health < 0.5 and hour == 12:  # Check at noon
                generate_alert(
                    db, ts, "PREDICTIVE_MAINTENANCE", AlertSeverity.MEDIUM,
                    f"Predictive Maintenance Required: {motor_id}",
                    f"Health score at {health*100:.0f}%. Schedule maintenance to prevent failure.",
                    motor_id
                )
    
    # Commit daily data
    db.commit()
    
    return motor_health


def generate_history(days: int = 30, orders_per_day: int = 50):
    """
    Generate synthetic historical data for the specified number of days.
    
    Parameters
    ----------
    days : int
        Number of days of history to generate (default 30).
    orders_per_day : int
        Average orders per day (default 50).
    """
    print("=" * 60)
    print("STF Digital Twin - Synthetic Data Generator")
    print("=" * 60)
    print(f"Generating {days} days of history with ~{orders_per_day} orders/day")
    print(f"Database: {DATABASE_URL}")
    print("=" * 60)
    
    db = create_session()
    
    # Seed core tables first (inventory, components, motors, sensors, hardware)
    seed_core_tables(db)
    
    # Calculate date range (past N days)
    end_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = end_date - timedelta(days=days)
    
    print(f"Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    print()
    
    # Track motor health across days
    motor_health = {}
    
    # Generate data for each day
    for day in range(1, days + 1):
        current_date = start_date + timedelta(days=day - 1)
        
        # Vary orders per day (±20%)
        daily_orders = int(orders_per_day * random.uniform(0.8, 1.2))
        
        motor_health = generate_daily_data(
            db, day, current_date, daily_orders, motor_health
        )
    
    print()
    print("=" * 60)
    print("Generation Complete!")
    print("=" * 60)
    
    # Print summary
    command_count = db.query(Command).count()
    energy_count = db.query(EnergyLog).count()
    telemetry_count = db.query(TelemetryHistory).count()
    alert_count = db.query(Alert).count()
    log_count = db.query(SystemLog).count()
    
    print(f"Commands generated: {command_count}")
    print(f"Energy logs generated: {energy_count}")
    print(f"Telemetry records generated: {telemetry_count}")
    print(f"Alerts generated: {alert_count}")
    print(f"System logs generated: {log_count}")
    print()
    print("Breakdown scenarios injected:")
    print(f"  - Day {BREAKDOWN_DAY_MOTOR}: Motor Failure (CONV_M1)")
    print(f"  - Day {BREAKDOWN_DAY_SENSOR}: Sensor Drift (CONV_L2_PROCESS)")
    
    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate synthetic historical data for STF Digital Twin"
    )
    parser.add_argument(
        "--days", type=int, default=30,
        help="Number of days of history to generate (default: 30)"
    )
    parser.add_argument(
        "--orders-per-day", type=int, default=50,
        help="Average orders per day (default: 50)"
    )
    
    args = parser.parse_args()
    
    generate_history(days=args.days, orders_per_day=args.orders_per_day)
