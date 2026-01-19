#!/usr/bin/env python3
"""
STF Digital Twin - Sensor Demo Script
Demonstrates Light Barriers (Lichtschranke) and Trail Sensors (Spursensor)

This script simulates:
1. Lichtschranke (I_2, I_3) - Through-beam optical sensors for presence detection
2. Spursensor (I_5, I_6) - Reflective line-following sensors for track position
"""

import sys
import os
import time

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from hardware.mock_factory import (
    ConveyorSimulation,
    LightBarrierSimulation,
    TrailSensorSimulation,
)
from database import (
    get_session, init_database, SensorState, SensorType,
    ComponentRegistry, TelemetryHistory
)


def print_sensor_state(label: str, state: dict, sensor_type: str):
    """Pretty print sensor state"""
    if sensor_type == "LIGHT_BARRIER":
        icon = "🔴" if state["is_triggered"] else "🟢"
        print(f"  {icon} {label} (Lichtschranke): triggered={state['is_triggered']}, "
              f"beam={state['beam_strength']:.2f}, count={state['trigger_count']}")
    else:
        positions = {"CENTER": "⬤", "LEFT": "◀", "RIGHT": "▶", "LOST": "✖"}
        icon = positions.get(state["track_position"], "?")
        print(f"  {icon} {label} (Spursensor): on_track={state['is_triggered']}, "
              f"reflectance={state['reflectance_value']:.2f}, pos={state['track_position']}")


def save_sensor_telemetry(session, sensor_id: str, state: dict, sensor_type: str):
    """Save sensor state to telemetry history"""
    timestamp = datetime.utcnow()
    
    if sensor_type == "LIGHT_BARRIER":
        # Save beam strength
        telemetry = TelemetryHistory(
            device_id=sensor_id,
            metric_name="beam_strength",
            metric_value=state["beam_strength"],
            unit="ratio",
            timestamp=timestamp
        )
        session.add(telemetry)
        
        # Save triggered state as 0/1
        telemetry2 = TelemetryHistory(
            device_id=sensor_id,
            metric_name="is_triggered",
            metric_value=1.0 if state["is_triggered"] else 0.0,
            unit="bool",
            timestamp=timestamp
        )
        session.add(telemetry2)
        
    else:  # TRAIL_SENSOR
        # Save reflectance value
        telemetry = TelemetryHistory(
            device_id=sensor_id,
            metric_name="reflectance_value",
            metric_value=state["reflectance_value"],
            unit="ratio",
            timestamp=timestamp
        )
        session.add(telemetry)
        
        # Encode track position as numeric (-1=LEFT, 0=CENTER, 1=RIGHT, -99=LOST)
        pos_map = {"LEFT": -1, "CENTER": 0, "RIGHT": 1, "LOST": -99}
        telemetry2 = TelemetryHistory(
            device_id=sensor_id,
            metric_name="track_position",
            metric_value=pos_map.get(state["track_position"], -99),
            unit="position",
            timestamp=timestamp
        )
        session.add(telemetry2)


def update_sensor_db_state(session, sensor_id: str, state: dict, sensor_type_enum: SensorType):
    """Update sensor state in database"""
    sensor_state = session.query(SensorState).filter_by(component_id=sensor_id).first()
    
    if sensor_state:
        sensor_state.is_triggered = state["is_triggered"]
        sensor_state.trigger_count = state["trigger_count"]
        
        if state["is_triggered"]:
            sensor_state.last_trigger_time = datetime.utcnow()
        
        if sensor_type_enum == SensorType.LIGHT_BARRIER:
            sensor_state.beam_strength = state.get("beam_strength")
        elif sensor_type_enum == SensorType.TRAIL_SENSOR:
            sensor_state.reflectance_value = state.get("reflectance_value")
            sensor_state.track_position = state.get("track_position")


def run_demo():
    """Run the sensor demonstration"""
    print("=" * 60)
    print("STF Digital Twin - Sensor Demonstration")
    print("=" * 60)
    print()
    print("Sensor Types:")
    print("  • Lichtschranke (Light Barrier) - I_2, I_3")
    print("    Through-beam optical sensors for presence detection")
    print("  • Spursensor (Trail Sensor) - I_5, I_6")
    print("    Reflective line-following sensors for track position")
    print()
    
    # Initialize database
    print("Initializing database...")
    init_database()
    session = get_session()
    
    # Check if new sensors exist in database
    sensors_in_db = session.query(ComponentRegistry).filter(
        ComponentRegistry.id.in_(["CONV_LB_I2", "CONV_LB_I3", "CONV_TS_I5", "CONV_TS_I6"])
    ).all()
    
    if len(sensors_in_db) < 4:
        print("⚠️  New sensors not found in database. You may need to re-seed.")
        print("   Run: python -c \"from database import init_database; init_database()\"")
        print()
    else:
        print(f"✓ Found {len(sensors_in_db)} new sensor components in database")
    
    # Create conveyor simulation
    conveyor = ConveyorSimulation()
    
    print()
    print("-" * 60)
    print("DEMO 1: Object Moving Through Light Barriers")
    print("-" * 60)
    
    # Place object at start
    conveyor.place_object(position_mm=0)
    conveyor.start(direction=1)
    
    dt = 0.1  # 100ms tick
    
    print("\nStarting conveyor with object at entry...")
    print("Watching Light Barriers (I_2=entry, I_3=exit):\n")
    
    for tick in range(50):
        state = conveyor.tick(dt)
        
        # Print every 5 ticks or when triggered
        i2_triggered = state["light_barriers"]["I2"]["is_triggered"]
        i3_triggered = state["light_barriers"]["I3"]["is_triggered"]
        
        if tick % 10 == 0 or i2_triggered or i3_triggered:
            print(f"Tick {tick:3d} | Object at {state['object_position_mm']:.0f}mm")
            print_sensor_state("I_2 (Inner/Entry)", state["light_barriers"]["I2"], "LIGHT_BARRIER")
            print_sensor_state("I_3 (Outer/Exit)", state["light_barriers"]["I3"], "LIGHT_BARRIER")
            print()
            
            # Save to database
            for key, lb_state in state["light_barriers"].items():
                sensor_id = f"CONV_LB_{key}"
                save_sensor_telemetry(session, sensor_id, lb_state, "LIGHT_BARRIER")
                update_sensor_db_state(session, sensor_id, lb_state, SensorType.LIGHT_BARRIER)
        
        if not state["has_object"]:
            print("Object exited conveyor!")
            break
    
    conveyor.stop()
    session.commit()
    
    print()
    print("-" * 60)
    print("DEMO 2: Trail Sensor Track Following")
    print("-" * 60)
    
    conveyor = ConveyorSimulation()  # Fresh conveyor
    conveyor.start(direction=1)
    
    print("\nStarting belt movement to show trail sensor readings...")
    print("Trail sensors detect track marks on conveyor surface:\n")
    
    for tick in range(30):
        state = conveyor.tick(dt)
        
        if tick % 5 == 0:
            print(f"Tick {tick:3d} | Belt at {state['belt_position_mm']:.0f}mm")
            print_sensor_state("I_5 (Bottom)", state["trail_sensors"]["I5"], "TRAIL_SENSOR")
            print_sensor_state("I_6 (Top)", state["trail_sensors"]["I6"], "TRAIL_SENSOR")
            print()
            
            # Save to database
            for key, ts_state in state["trail_sensors"].items():
                sensor_id = f"CONV_TS_{key}"
                save_sensor_telemetry(session, sensor_id, ts_state, "TRAIL_SENSOR")
                update_sensor_db_state(session, sensor_id, ts_state, SensorType.TRAIL_SENSOR)
    
    conveyor.stop()
    session.commit()
    
    # Show saved data
    print()
    print("-" * 60)
    print("Saved Telemetry Data (last 10 records):")
    print("-" * 60)
    
    recent_telemetry = session.query(TelemetryHistory).filter(
        TelemetryHistory.device_id.like("CONV_%")
    ).order_by(TelemetryHistory.timestamp.desc()).limit(10).all()
    
    for t in recent_telemetry:
        print(f"  {t.device_id:15s} | {t.metric_name:20s} = {t.metric_value:8.3f} {t.unit or ''}")
    
    print()
    print("=" * 60)
    print("Demo complete! Sensor data saved to database.")
    print("=" * 60)
    
    session.close()


if __name__ == "__main__":
    run_demo()
