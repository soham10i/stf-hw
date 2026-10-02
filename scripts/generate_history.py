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

# Enhanced Breakdown scenarios for ~70% system health
BREAKDOWN_SCENARIOS = {
    5: {"type": "MOTOR_OVERTEMP", "component": "HBW_M1_X", "severity": "MEDIUM", "health_impact": 0.08},
    8: {"type": "SENSOR_INTERMITTENT", "component": "CONV_L1_ENTRY", "severity": "LOW", "health_impact": 0.03},
    12: {"type": "MOTOR_FAILURE", "component": "CONV_M1", "severity": "CRITICAL", "health_impact": 0.15},
    15: {"type": "GRIPPER_MALFUNCTION", "component": "VGR_M2_GRIP", "severity": "MEDIUM", "health_impact": 0.07},
    18: {"type": "AXIS_VIBRATION", "component": "HBW_M2_Y", "severity": "MEDIUM", "health_impact": 0.05},
    22: {"type": "BELT_SLIPPAGE", "component": "CONV_M1", "severity": "LOW", "health_impact": 0.04},
    25: {"type": "SENSOR_DRIFT", "component": "CONV_L2_PROCESS", "severity": "MEDIUM", "health_impact": 0.06},
    28: {"type": "MOTOR_BEARING_WEAR", "component": "VGR_M1_ARM", "severity": "MEDIUM", "health_impact": 0.05},
}

# Breakdown scenarios - legacy support
BREAKDOWN_DAY_MOTOR = 12  # Day 12: Motor failure
BREAKDOWN_DAY_SENSOR = 25  # Day 25: Sensor drift

# Target system health ~70% (cumulative degradation)
BASE_SYSTEM_HEALTH = 0.95
DAILY_DEGRADATION = 0.008  # Natural wear per day (~70% by day 30)


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


def simulate_breakdown_scenario(db, day: int, base_date: datetime, component_health: dict) -> dict:
    """
    Simulate various breakdown scenarios throughout the 30 days.
    
    Returns updated component health states.
    """
    if day not in BREAKDOWN_SCENARIOS:
        return component_health
    
    scenario = BREAKDOWN_SCENARIOS[day]
    scenario_type = scenario["type"]
    component = scenario["component"]
    severity = scenario["severity"]
    health_impact = scenario["health_impact"]
    
    print(f"  [!] Day {day}: Simulating {scenario_type} on {component}")
    
    # Determine alert severity
    alert_severity = {
        "LOW": AlertSeverity.LOW,
        "MEDIUM": AlertSeverity.MEDIUM,
        "CRITICAL": AlertSeverity.CRITICAL
    }.get(severity, AlertSeverity.MEDIUM)
    
    # Current health before incident
    current_health = component_health.get(component, {}).get("health", 0.95)
    new_health = max(0.3, current_health - health_impact)
    
    # Generate scenario-specific data
    if scenario_type == "MOTOR_OVERTEMP":
        # Temperature spike scenario
        for hour in range(3):
            ts = base_date + timedelta(hours=10 + hour)
            temp = 75 + (hour * 10) + random.uniform(-2, 2)  # 75°C -> 95°C
            generate_telemetry(db, ts, component, "temperature", temp, "°C")
            generate_telemetry(db, ts, component, "current_amps", 2.8 + random.uniform(-0.2, 0.2), "A")
            
            log = SystemLog(
                timestamp=ts,
                level=LogLevel.WARNING,
                source="MOTOR_CONTROLLER",
                message=f"[BREAKDOWN] {component} temperature elevated: {temp:.1f}°C (threshold: 70°C)",
            )
            db.add(log)
        
        generate_alert(
            db, base_date + timedelta(hours=12), "OVERTEMPERATURE", alert_severity,
            f"Motor Overtemperature: {component}",
            f"Temperature exceeded safe operating limits. Motor throttled to prevent damage.",
            component
        )
    
    elif scenario_type == "SENSOR_INTERMITTENT":
        # Intermittent sensor failures
        for i in range(random.randint(5, 12)):
            ts = base_date + timedelta(hours=random.randint(8, 18), minutes=random.randint(0, 59))
            generate_telemetry(db, ts, component, "signal_loss", 1.0, "count")
            
            log = SystemLog(
                timestamp=ts,
                level=LogLevel.WARNING,
                source="SENSOR",
                message=f"[BREAKDOWN] {component} signal lost momentarily - possible wiring issue",
            )
            db.add(log)
        
        generate_alert(
            db, base_date + timedelta(hours=14), "SENSOR_INTERMITTENT", alert_severity,
            f"Intermittent Sensor Failure: {component}",
            f"Multiple signal losses detected. Check wiring and connections.",
            component
        )
    
    elif scenario_type == "GRIPPER_MALFUNCTION":
        # Vacuum gripper issues
        for hour in range(2):
            ts = base_date + timedelta(hours=11 + hour)
            vacuum_pressure = 0.4 - (hour * 0.15)  # Degrading vacuum
            generate_telemetry(db, ts, component, "vacuum_pressure", vacuum_pressure, "bar")
            generate_telemetry(db, ts, component, "grip_success_rate", 0.7 - (hour * 0.1), "%")
            
            log = SystemLog(
                timestamp=ts,
                level=LogLevel.ERROR,
                source="VGR_CONTROLLER",
                message=f"[BREAKDOWN] {component} vacuum pressure low: {vacuum_pressure:.2f} bar (min: 0.5 bar)",
            )
            db.add(log)
        
        generate_alert(
            db, base_date + timedelta(hours=13), "GRIPPER_MALFUNCTION", alert_severity,
            f"Gripper Malfunction: {component}",
            f"Vacuum pressure insufficient. Multiple drop events detected. Check seals and pump.",
            component
        )
    
    elif scenario_type == "AXIS_VIBRATION":
        # Excessive vibration on axis
        for hour in range(4):
            ts = base_date + timedelta(hours=9 + hour)
            vibration = 2.5 + (hour * 0.5) + random.uniform(-0.2, 0.2)  # Increasing vibration
            generate_telemetry(db, ts, component, "vibration_rms", vibration, "mm/s")
            
            log = SystemLog(
                timestamp=ts,
                level=LogLevel.WARNING,
                source="MOTOR_CONTROLLER",
                message=f"[BREAKDOWN] {component} vibration elevated: {vibration:.2f} mm/s RMS (limit: 2.0 mm/s)",
            )
            db.add(log)
        
        generate_alert(
            db, base_date + timedelta(hours=13), "EXCESSIVE_VIBRATION", alert_severity,
            f"Excessive Vibration: {component}",
            f"Vibration levels exceeding safe limits. Check bearings and alignment.",
            component
        )
    
    elif scenario_type == "BELT_SLIPPAGE":
        # Conveyor belt slippage
        for i in range(random.randint(8, 15)):
            ts = base_date + timedelta(hours=random.randint(8, 17), minutes=random.randint(0, 59))
            slip_amount = random.uniform(2, 8)  # mm of slippage
            generate_telemetry(db, ts, component, "belt_slip", slip_amount, "mm")
            
            log = SystemLog(
                timestamp=ts,
                level=LogLevel.WARNING,
                source="CONVEYOR",
                message=f"[BREAKDOWN] Belt slippage detected: {slip_amount:.1f}mm - possible tension issue",
            )
            db.add(log)
        
        generate_alert(
            db, base_date + timedelta(hours=15), "BELT_SLIPPAGE", alert_severity,
            f"Belt Slippage Detected: {component}",
            f"Multiple slippage events. Adjust belt tension or check drive roller.",
            component
        )
    
    elif scenario_type == "MOTOR_BEARING_WEAR":
        # Bearing wear signs
        for hour in range(6):
            ts = base_date + timedelta(hours=8 + hour)
            noise_db = 55 + (hour * 2) + random.uniform(-1, 1)
            generate_telemetry(db, ts, component, "acoustic_noise", noise_db, "dB")
            generate_telemetry(db, ts, component, "bearing_temp", 45 + (hour * 3), "°C")
            
            if hour >= 3:
                log = SystemLog(
                    timestamp=ts,
                    level=LogLevel.WARNING,
                    source="MOTOR_CONTROLLER",
                    message=f"[BREAKDOWN] {component} abnormal noise: {noise_db:.0f}dB - bearing wear suspected",
                )
                db.add(log)
        
        generate_alert(
            db, base_date + timedelta(hours=14), "BEARING_WEAR", alert_severity,
            f"Bearing Wear Detected: {component}",
            f"Acoustic signature indicates bearing degradation. Schedule replacement.",
            component
        )
    
    # Update component health
    component_health[component] = {"health": new_health, "last_incident": scenario_type}
    
    # Generate predictive maintenance alert for components with low health
    if new_health < 0.6:
        generate_alert(
            db, base_date + timedelta(hours=16), "PREDICTIVE_MAINTENANCE", AlertSeverity.MEDIUM,
            f"Maintenance Required: {component}",
            f"Component health at {new_health*100:.0f}%. Schedule preventive maintenance.",
            component
        )
    
    return component_health


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
    
    # Simulate ALL breakdown scenarios (new enhanced function)
    motor_health = simulate_breakdown_scenario(db, day, base_date, motor_health)
    
    # Legacy breakdown scenarios
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
    
    # Generate hourly motor health telemetry with DEGRADATION
    for hour in range(24):
        ts = base_date + timedelta(hours=hour)
        
        for motor_id in MOTORS:
            # Calculate degraded health (target ~70% by day 30)
            # Start at 95%, degrade by ~0.8% per day = ~71% by day 30
            base_health = BASE_SYSTEM_HEALTH - (day * DAILY_DEGRADATION)
            
            # Apply breakdown impacts
            if motor_id in motor_health:
                health = motor_health[motor_id].get("health", base_health)
            else:
                # Add random variation
                health = max(0.45, base_health + random.uniform(-0.03, 0.02))
            
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
            
            # Generate predictive maintenance alert if health < 0.6
            if health < 0.6 and hour == 12:  # Check at noon
                generate_alert(
                    db, ts, "PREDICTIVE_MAINTENANCE", AlertSeverity.MEDIUM,
                    f"Predictive Maintenance Required: {motor_id}",
                    f"Health score at {health*100:.0f}%. Schedule maintenance to prevent failure.",
                    motor_id
                )
    
    # Generate daily system health summary log
    avg_health = sum(
        motor_health.get(m, {}).get("health", BASE_SYSTEM_HEALTH - (day * DAILY_DEGRADATION))
        for m in MOTORS
    ) / len(MOTORS)
    
    daily_summary = SystemLog(
        timestamp=base_date + timedelta(hours=23, minutes=59),
        level=LogLevel.INFO if avg_health > 0.7 else LogLevel.WARNING,
        source="SYSTEM",
        message=f"[DAILY SUMMARY] Day {day}: Orders={orders_generated}, Avg Health={avg_health*100:.1f}%",
    )
    db.add(daily_summary)
    
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
    for day, scenario in BREAKDOWN_SCENARIOS.items():
        print(f"  - Day {day}: {scenario['type']} ({scenario['component']}) - {scenario['severity']}")
    print()
    print(f"Target system health by Day 30: ~{(BASE_SYSTEM_HEALTH - 30*DAILY_DEGRADATION)*100:.0f}%")
    
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
