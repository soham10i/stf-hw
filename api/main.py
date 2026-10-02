"""
STF Digital Twin - FastAPI REST API with WebSocket Support
High-Fidelity Component Twin with Real-Time Updates
"""

import json
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logging_config import get_logger

logger = get_logger("api")

from database import (
    get_db, init_database, Carrier, Cookie, CookieFlavor, CookieStatus,
    InventorySlot, HardwareState, HardwareStatus, SystemLog, LogLevel,
    EnergyLog, TelemetryHistory, Alert, AlertSeverity, Command,
    ComponentRegistry, MotorState, SensorState, SubsystemType, ComponentType,
    get_slot_coordinates, seed_inventory_slots, seed_hardware_devices, seed_components,
)

app = FastAPI(
    title="STF Digital Twin API",
    description="High-Fidelity Component Twin REST API with WebSocket Support",
    version="3.0.0",
)

# ---------------------------------------------------------------------------
# CORS — configurable via environment variable (comma-separated origins)
# ---------------------------------------------------------------------------
_cors_origins = os.environ.get(
    "CORS_ORIGINS", "http://localhost:8501,http://localhost:8000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Optional API-key authentication (set STF_API_KEY env var to enable)
# ---------------------------------------------------------------------------
_api_key_env = os.environ.get("STF_API_KEY")
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: Optional[str] = Security(_api_key_header)):
    """Validate API key when STF_API_KEY is configured."""
    if _api_key_env is None:
        # Authentication not enabled — allow all requests
        return None
    if api_key is None or api_key != _api_key_env:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return api_key

# ============================================================================
# WebSocket Connection Manager
# ============================================================================

class ConnectionManager:
    """Manages WebSocket connections for real-time dashboard updates"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("WebSocket client connected. Total: %d", len(self.active_connections))
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info("WebSocket client disconnected. Total: %d", len(self.active_connections))
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        if not self.active_connections:
            return
        
        message_json = json.dumps(message, default=str)
        disconnected = []
        
        for connection in self.active_connections:
            try:
                await connection.send_text(message_json)
            except Exception as e:
                logger.warning("WebSocket broadcast error: %s", e)
                disconnected.append(connection)
        
        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)
    
    async def send_personal(self, websocket: WebSocket, message: dict):
        """Send message to specific client"""
        try:
            await websocket.send_text(json.dumps(message, default=str))
        except Exception as e:
            logger.warning("WebSocket send error: %s", e)

manager = ConnectionManager()

# ============================================================================
# Pydantic Models
# ============================================================================

class HardwareStateUpdate(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=50)
    x: float = Field(..., ge=0, le=1000)
    y: float = Field(..., ge=0, le=1000)
    z: float = Field(0.0, ge=0, le=1000)
    status: Optional[str] = None

class HardwareStateResponse(BaseModel):
    device_id: str
    current_x: float
    current_y: float
    current_z: float
    status: str
    updated_at: datetime
    class Config:
        from_attributes = True

class ComponentSpecResponse(BaseModel):
    id: str
    name: str
    subsystem: str
    component_type: str
    spec_voltage: float
    spec_max_current: float
    maintenance_interval_hours: int
    class Config:
        from_attributes = True

class MotorStateUpdate(BaseModel):
    component_id: str = Field(..., min_length=1, max_length=50)
    current_amps: float = Field(..., ge=0, le=20)
    voltage: float = Field(24.0, ge=0, le=48)
    is_active: bool = False
    health_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    accumulated_runtime_sec: Optional[float] = Field(None, ge=0)

class MotorStateResponse(BaseModel):
    component_id: str
    current_amps: float
    voltage: float
    health_score: float
    accumulated_runtime_sec: float
    is_active: bool
    time_to_failure_hours: Optional[float] = None
    class Config:
        from_attributes = True

class SensorStateUpdate(BaseModel):
    component_id: str = Field(..., min_length=1, max_length=50)
    is_triggered: bool

class SensorStateResponse(BaseModel):
    component_id: str
    is_triggered: bool
    trigger_count: int
    last_trigger_time: Optional[datetime]
    class Config:
        from_attributes = True

class ConveyorStateUpdate(BaseModel):
    belt_position_mm: float
    motor_amps: float
    motor_active: bool
    sensors: Dict[str, bool]  # L1, L2, L3, L4

class TelemetryData(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=50)
    metric_name: str = Field(..., min_length=1, max_length=100)
    metric_value: float
    unit: Optional[str] = Field(None, max_length=20)

class EnergyData(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=50)
    joules: float = Field(..., ge=0)
    voltage: float = Field(24.0, ge=0, le=48)
    current_amps: Optional[float] = Field(None, ge=0, le=20)
    power_watts: Optional[float] = Field(None, ge=0)

class InventorySlotResponse(BaseModel):
    slot_name: str
    x_pos: int
    y_pos: int
    carrier_id: Optional[int]
    cookie_flavor: Optional[str]
    cookie_status: Optional[str]
    class Config:
        from_attributes = True

class SystemLogResponse(BaseModel):
    id: int
    timestamp: datetime
    level: str
    source: Optional[str]
    message: str
    class Config:
        from_attributes = True

class EnergyStatsResponse(BaseModel):
    total_joules: float
    total_kwh: float
    devices: dict

class DashboardDataResponse(BaseModel):
    inventory: List[InventorySlotResponse]
    hardware: List[HardwareStateResponse]
    motors: List[MotorStateResponse]
    sensors: List[SensorStateResponse]
    logs: List[SystemLogResponse]
    energy: EnergyStatsResponse
    stats: dict
    conveyor: dict

class StoreRequest(BaseModel):
    slot_name: Optional[str] = None
    flavor: str = "CHOCO"

class RetrieveRequest(BaseModel):
    slot_name: str

class ProcessOrderRequest(BaseModel):
    source_slot: Optional[str] = None  # Auto-selects first RAW_DOUGH slot if not provided
    flavor: Optional[str] = None  # Optional flavor filter for auto-selection

class CommandResponse(BaseModel):
    success: bool
    message: str
    command_id: Optional[int] = None
    slot_name: Optional[str] = None
    batch_uuid: Optional[str] = None

class CommandStatusUpdate(BaseModel):
    """Validated model for command status updates (replaces raw dict)."""
    status: str = Field(..., pattern="^(PENDING|IN_PROGRESS|COMPLETED|FAILED)$")
    message: Optional[str] = Field(None, max_length=500)

# ============================================================================
# WebSocket Endpoint
# ============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time dashboard updates"""
    await manager.connect(websocket)
    
    try:
        # Send initial state on connect
        db = next(get_db())
        initial_data = get_full_dashboard_state(db)
        await manager.send_personal(websocket, {
            "type": "initial_state",
            "data": initial_data
        })
        
        while True:
            # Keep connection alive and handle incoming messages
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message.get("type") == "ping":
                await manager.send_personal(websocket, {"type": "pong"})
            elif message.get("type") == "request_state":
                db = next(get_db())
                state = get_full_dashboard_state(db)
                await manager.send_personal(websocket, {
                    "type": "state_update",
                    "data": state
                })
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        manager.disconnect(websocket)

def get_full_dashboard_state(db: Session) -> dict:
    """Get complete dashboard state for WebSocket"""
    # Inventory
    slots = db.query(InventorySlot).all()
    inventory = []
    occupied_count = 0
    for slot in slots:
        cookie_flavor, cookie_status = None, None
        if slot.carrier_id:
            occupied_count += 1
            carrier = db.query(Carrier).filter(Carrier.id == slot.carrier_id).first()
            if carrier:
                cookie = db.query(Cookie).filter(Cookie.carrier_id == carrier.id).first()
                if cookie:
                    cookie_flavor = cookie.flavor.value
                    cookie_status = cookie.status.value
        inventory.append({
            "slot_name": slot.slot_name, "x_pos": slot.x_pos, "y_pos": slot.y_pos,
            "carrier_id": slot.carrier_id, "cookie_flavor": cookie_flavor, "cookie_status": cookie_status,
        })
    
    # Hardware
    devices = db.query(HardwareState).all()
    hardware = [{
        "device_id": hw.device_id, "current_x": hw.current_x, "current_y": hw.current_y,
        "current_z": hw.current_z, "status": hw.status.value, "updated_at": hw.updated_at.isoformat(),
    } for hw in devices]
    
    # Motors with health data
    motors = []
    motor_states = db.query(MotorState).all()
    for ms in motor_states:
        comp = db.query(ComponentRegistry).filter(ComponentRegistry.id == ms.component_id).first()
        ttf = None
        if comp and ms.health_score > 0:
            # Estimate time to failure based on health degradation rate
            remaining_health = ms.health_score - 0.5  # Failure threshold
            if remaining_health > 0:
                ttf = remaining_health / 0.0001 / 3600  # hours until health_score = 0.5
        motors.append({
            "component_id": ms.component_id,
            "current_amps": ms.current_amps,
            "voltage": ms.voltage,
            "health_score": ms.health_score,
            "accumulated_runtime_sec": ms.accumulated_runtime_sec,
            "is_active": ms.is_active,
            "time_to_failure_hours": ttf,
            "spec_max_current": comp.spec_max_current if comp else 5.0,
        })
    
    # Sensors
    sensors = []
    sensor_states = db.query(SensorState).all()
    for ss in sensor_states:
        sensors.append({
            "component_id": ss.component_id,
            "is_triggered": ss.is_triggered,
            "trigger_count": ss.trigger_count,
            "last_trigger_time": ss.last_trigger_time.isoformat() if ss.last_trigger_time else None,
        })
    
    # Conveyor state (from motor and sensors)
    conv_motor = db.query(MotorState).filter(MotorState.component_id == "CONV_M1").first()
    conveyor = {
        "belt_position_mm": 0,  # Will be updated by simulation
        "motor_active": conv_motor.is_active if conv_motor else False,
        "motor_amps": conv_motor.current_amps if conv_motor else 0,
        "sensors": {
            "L1": next((s["is_triggered"] for s in sensors if s["component_id"] == "CONV_L1_ENTRY"), False),
            "L2": next((s["is_triggered"] for s in sensors if s["component_id"] == "CONV_L2_PROCESS"), False),
            "L3": next((s["is_triggered"] for s in sensors if s["component_id"] == "CONV_L3_EXIT"), False),
            "L4": next((s["is_triggered"] for s in sensors if s["component_id"] == "CONV_L4_OVERFLOW"), False),
        }
    }
    
    # Logs
    recent_logs = db.query(SystemLog).order_by(desc(SystemLog.timestamp)).limit(10).all()
    logs = [{
        "id": log.id, "timestamp": log.timestamp.isoformat(), "level": log.level.value,
        "source": log.source, "message": log.message
    } for log in recent_logs]
    
    # Energy
    since = datetime.utcnow() - timedelta(hours=24)
    total_energy = db.query(func.sum(EnergyLog.joules)).filter(EnergyLog.timestamp >= since).scalar() or 0.0
    device_energy = db.query(EnergyLog.device_id, func.sum(EnergyLog.joules).label("total")).filter(
        EnergyLog.timestamp >= since).group_by(EnergyLog.device_id).all()
    energy = {
        "total_joules": total_energy,
        "total_kwh": total_energy / 3600000,
        "devices": {d.device_id: d.total for d in device_energy},
    }
    
    # Stats
    cookie_counts = db.query(Cookie.status, func.count(Cookie.batch_uuid)).group_by(Cookie.status).all()
    cookie_stats = {status.value: count for status, count in cookie_counts}
    active_alerts = db.query(func.count(Alert.id)).filter(Alert.acknowledged == False).scalar() or 0
    
    stats = {
        "total_slots": len(slots),
        "occupied_slots": occupied_count,
        "available_slots": len(slots) - occupied_count,
        "total_cookies": sum(cookie_stats.values()),
        "raw_dough_cookies": cookie_stats.get("RAW_DOUGH", 0),
        "baked_cookies": cookie_stats.get("BAKED", 0),
        "packaged_cookies": cookie_stats.get("PACKAGED", 0),
        "active_devices": len([h for h in hardware if h["status"] != "ERROR"]),
        "active_alerts": active_alerts,
        "system_healthy": active_alerts == 0 and all(h["status"] != "ERROR" for h in hardware),
    }
    
    return {
        "inventory": inventory,
        "hardware": hardware,
        "motors": motors,
        "sensors": sensors,
        "conveyor": conveyor,
        "logs": logs,
        "energy": energy,
        "stats": stats,
        "timestamp": datetime.utcnow().isoformat(),
    }

async def broadcast_state_update(db: Session, update_type: str, data: dict):
    """Broadcast state update to all WebSocket clients"""
    await manager.broadcast({
        "type": update_type,
        "data": data,
        "timestamp": datetime.utcnow().isoformat(),
    })

# ============================================================================
# Startup
# ============================================================================

@app.on_event("startup")
async def startup_event():
    try:
        init_database(seed_data=True)
        logger.info("STF Digital Twin API v3.0 started with WebSocket support")
    except Exception as e:
        logger.warning("Database init warning: %s", e)

# ============================================================================
# Component Registry Endpoints
# ============================================================================

@app.get("/components/specs", response_model=List[ComponentSpecResponse], tags=["Components"])
def get_component_specs(db: Session = Depends(get_db)):
    """Get static specification data for all components"""
    components = db.query(ComponentRegistry).all()
    return [
        ComponentSpecResponse(
            id=c.id, name=c.name, subsystem=c.subsystem.value,
            component_type=c.component_type.value, spec_voltage=c.spec_voltage,
            spec_max_current=c.spec_max_current, maintenance_interval_hours=c.maintenance_interval_hours,
        ) for c in components
    ]

@app.get("/components/specs/{subsystem}", response_model=List[ComponentSpecResponse], tags=["Components"])
def get_subsystem_specs(subsystem: str, db: Session = Depends(get_db)):
    """Get component specs for a specific subsystem"""
    try:
        subsystem_enum = SubsystemType[subsystem.upper()]
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Invalid subsystem: {subsystem}")
    
    components = db.query(ComponentRegistry).filter(ComponentRegistry.subsystem == subsystem_enum).all()
    return [
        ComponentSpecResponse(
            id=c.id, name=c.name, subsystem=c.subsystem.value,
            component_type=c.component_type.value, spec_voltage=c.spec_voltage,
            spec_max_current=c.spec_max_current, maintenance_interval_hours=c.maintenance_interval_hours,
        ) for c in components
    ]

# ============================================================================
# Motor State Endpoints
# ============================================================================

@app.post("/motors/state", response_model=MotorStateResponse, tags=["Motors"])
async def update_motor_state(data: MotorStateUpdate, db: Session = Depends(get_db)):
    """Update motor state and broadcast via WebSocket"""
    motor = db.query(MotorState).filter(MotorState.component_id == data.component_id).first()
    if not motor:
        raise HTTPException(status_code=404, detail=f"Motor {data.component_id} not found")
    
    motor.current_amps = data.current_amps
    motor.voltage = data.voltage
    motor.is_active = data.is_active
    
    if data.health_score is not None:
        motor.health_score = max(0.0, min(1.0, data.health_score))
    if data.accumulated_runtime_sec is not None:
        motor.accumulated_runtime_sec = data.accumulated_runtime_sec
    
    motor.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(motor)
    
    # Get spec for TTF calculation
    comp = db.query(ComponentRegistry).filter(ComponentRegistry.id == data.component_id).first()
    ttf = None
    if motor.health_score > 0.5:
        ttf = (motor.health_score - 0.5) / 0.0001 / 3600
    
    response = MotorStateResponse(
        component_id=motor.component_id, current_amps=motor.current_amps,
        voltage=motor.voltage, health_score=motor.health_score,
        accumulated_runtime_sec=motor.accumulated_runtime_sec, is_active=motor.is_active,
        time_to_failure_hours=ttf,
    )
    
    # Broadcast update
    await broadcast_state_update(db, "motor_update", {
        "component_id": motor.component_id,
        "current_amps": motor.current_amps,
        "voltage": motor.voltage,
        "health_score": motor.health_score,
        "is_active": motor.is_active,
        "spec_max_current": comp.spec_max_current if comp else 5.0,
    })
    
    return response

@app.get("/motors/states", response_model=List[MotorStateResponse], tags=["Motors"])
def get_all_motor_states(db: Session = Depends(get_db)):
    """Get all motor states with health data"""
    motors = db.query(MotorState).all()
    result = []
    for m in motors:
        comp = db.query(ComponentRegistry).filter(ComponentRegistry.id == m.component_id).first()
        ttf = None
        if m.health_score > 0.5:
            ttf = (m.health_score - 0.5) / 0.0001 / 3600
        result.append(MotorStateResponse(
            component_id=m.component_id, current_amps=m.current_amps,
            voltage=m.voltage, health_score=m.health_score,
            accumulated_runtime_sec=m.accumulated_runtime_sec, is_active=m.is_active,
            time_to_failure_hours=ttf,
        ))
    return result

# ============================================================================
# Sensor State Endpoints
# ============================================================================

@app.post("/sensors/state", response_model=SensorStateResponse, tags=["Sensors"])
async def update_sensor_state(data: SensorStateUpdate, db: Session = Depends(get_db)):
    """Update sensor state and broadcast via WebSocket"""
    sensor = db.query(SensorState).filter(SensorState.component_id == data.component_id).first()
    if not sensor:
        raise HTTPException(status_code=404, detail=f"Sensor {data.component_id} not found")
    
    # Track trigger events
    if data.is_triggered and not sensor.is_triggered:
        sensor.trigger_count += 1
        sensor.last_trigger_time = datetime.utcnow()
    
    sensor.is_triggered = data.is_triggered
    sensor.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(sensor)
    
    response = SensorStateResponse(
        component_id=sensor.component_id, is_triggered=sensor.is_triggered,
        trigger_count=sensor.trigger_count, last_trigger_time=sensor.last_trigger_time,
    )
    
    # Broadcast update
    await broadcast_state_update(db, "sensor_update", {
        "component_id": sensor.component_id,
        "is_triggered": sensor.is_triggered,
        "trigger_count": sensor.trigger_count,
    })
    
    return response

@app.get("/sensors/states", response_model=List[SensorStateResponse], tags=["Sensors"])
def get_all_sensor_states(db: Session = Depends(get_db)):
    """Get all sensor states"""
    sensors = db.query(SensorState).all()
    return [
        SensorStateResponse(
            component_id=s.component_id, is_triggered=s.is_triggered,
            trigger_count=s.trigger_count, last_trigger_time=s.last_trigger_time,
        ) for s in sensors
    ]

# ============================================================================
# Conveyor State Endpoint
# ============================================================================

@app.post("/conveyor/state", tags=["Conveyor"])
async def update_conveyor_state(data: ConveyorStateUpdate, db: Session = Depends(get_db)):
    """Update full conveyor state (motor + sensors) and broadcast"""
    # Update motor
    motor = db.query(MotorState).filter(MotorState.component_id == "CONV_M1").first()
    if motor:
        motor.current_amps = data.motor_amps
        motor.is_active = data.motor_active
        motor.updated_at = datetime.utcnow()
    
    # Update sensors based on belt position
    sensor_map = {
        "L1": "CONV_L1_ENTRY",
        "L2": "CONV_L2_PROCESS",
        "L3": "CONV_L3_EXIT",
        "L4": "CONV_L4_OVERFLOW",
    }
    
    for key, component_id in sensor_map.items():
        sensor = db.query(SensorState).filter(SensorState.component_id == component_id).first()
        if sensor:
            new_state = data.sensors.get(key, False)
            if new_state and not sensor.is_triggered:
                sensor.trigger_count += 1
                sensor.last_trigger_time = datetime.utcnow()
            sensor.is_triggered = new_state
            sensor.updated_at = datetime.utcnow()
    
    db.commit()
    
    # Broadcast full conveyor state
    await broadcast_state_update(db, "conveyor_update", {
        "belt_position_mm": data.belt_position_mm,
        "belt_position_pct": data.belt_position_mm / 10,  # 0-100%
        "motor_active": data.motor_active,
        "motor_amps": data.motor_amps,
        "sensors": data.sensors,
    })
    
    return {"success": True, "belt_position_mm": data.belt_position_mm}

# ============================================================================
# Hardware Endpoints (Legacy + Enhanced)
# ============================================================================

@app.post("/hardware/state", response_model=HardwareStateResponse, tags=["Hardware"])
async def update_hardware_state(data: HardwareStateUpdate, db: Session = Depends(get_db)):
    hw = db.query(HardwareState).filter(HardwareState.device_id == data.device_id).first()
    if not hw:
        hw = HardwareState(
            device_id=data.device_id,
            current_x=data.x, current_y=data.y, current_z=data.z,
            status=HardwareStatus[data.status] if data.status else HardwareStatus.IDLE,
        )
        db.add(hw)
    else:
        hw.current_x = data.x
        hw.current_y = data.y
        hw.current_z = data.z
        if data.status:
            hw.status = HardwareStatus[data.status]
        hw.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(hw)
    
    response = HardwareStateResponse(
        device_id=hw.device_id, current_x=hw.current_x, current_y=hw.current_y,
        current_z=hw.current_z, status=hw.status.value, updated_at=hw.updated_at,
    )
    
    # Broadcast update
    await broadcast_state_update(db, "hardware_update", {
        "device_id": hw.device_id,
        "current_x": hw.current_x,
        "current_y": hw.current_y,
        "current_z": hw.current_z,
        "status": hw.status.value,
    })
    
    return response

@app.get("/hardware/states", response_model=List[HardwareStateResponse], tags=["Hardware"])
def get_all_hardware_states(db: Session = Depends(get_db)):
    devices = db.query(HardwareState).all()
    return [
        HardwareStateResponse(
            device_id=hw.device_id, current_x=hw.current_x, current_y=hw.current_y,
            current_z=hw.current_z, status=hw.status.value, updated_at=hw.updated_at,
        ) for hw in devices
    ]

# ============================================================================
# Telemetry & Energy Endpoints
# ============================================================================

@app.post("/telemetry", tags=["Telemetry"])
async def record_telemetry(data: TelemetryData, db: Session = Depends(get_db)):
    telemetry = TelemetryHistory(
        device_id=data.device_id, metric_name=data.metric_name,
        metric_value=data.metric_value, unit=data.unit,
    )
    db.add(telemetry)
    db.commit()
    
    # Broadcast telemetry update
    await broadcast_state_update(db, "telemetry_update", {
        "device_id": data.device_id,
        "metric_name": data.metric_name,
        "metric_value": data.metric_value,
        "unit": data.unit,
    })
    
    return {"success": True, "id": telemetry.id}

@app.post("/energy", tags=["Energy"])
async def record_energy(data: EnergyData, db: Session = Depends(get_db)):
    energy = EnergyLog(
        device_id=data.device_id, joules=data.joules, voltage=data.voltage,
        current_amps=data.current_amps, power_watts=data.power_watts,
    )
    db.add(energy)
    db.commit()
    
    # Broadcast energy update
    await broadcast_state_update(db, "energy_update", {
        "device_id": data.device_id,
        "joules": data.joules,
        "current_amps": data.current_amps,
        "power_watts": data.power_watts,
    })
    
    return {"success": True, "id": energy.id}

# ============================================================================
# Inventory Endpoints
# ============================================================================

@app.get("/inventory", response_model=List[InventorySlotResponse], tags=["Inventory"])
def get_inventory(db: Session = Depends(get_db)):
    slots = db.query(InventorySlot).all()
    result = []
    for slot in slots:
        cookie_flavor, cookie_status = None, None
        if slot.carrier_id:
            carrier = db.query(Carrier).filter(Carrier.id == slot.carrier_id).first()
            if carrier:
                cookie = db.query(Cookie).filter(Cookie.carrier_id == carrier.id).first()
                if cookie:
                    cookie_flavor = cookie.flavor.value
                    cookie_status = cookie.status.value
        result.append(InventorySlotResponse(
            slot_name=slot.slot_name, x_pos=slot.x_pos, y_pos=slot.y_pos,
            carrier_id=slot.carrier_id, cookie_flavor=cookie_flavor, cookie_status=cookie_status,
        ))
    return result

# ============================================================================
# Order Endpoints
# ============================================================================

@app.post("/order/store", response_model=CommandResponse, tags=["Orders"])
async def store_cookie(data: StoreRequest, db: Session = Depends(get_db)):
    if data.slot_name:
        slot = db.query(InventorySlot).filter(
            InventorySlot.slot_name == data.slot_name,
            InventorySlot.carrier_id == None
        ).first()
        if not slot:
            raise HTTPException(status_code=400, detail=f"Slot {data.slot_name} not available")
    else:
        slot = db.query(InventorySlot).filter(InventorySlot.carrier_id == None).first()
        if not slot:
            raise HTTPException(status_code=400, detail="No available slots")
    
    try:
        flavor = CookieFlavor[data.flavor.upper()]
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Invalid flavor: {data.flavor}")
    
    carrier = Carrier(current_zone="STORAGE", is_locked=False)
    db.add(carrier)
    db.flush()
    
    batch_uuid = str(uuid.uuid4())
    cookie = Cookie(batch_uuid=batch_uuid, carrier_id=carrier.id, flavor=flavor, status=CookieStatus.RAW_DOUGH)
    db.add(cookie)
    slot.carrier_id = carrier.id
    
    command = Command(
        command_type="STORE", target_slot=slot.slot_name,
        payload_json=json.dumps({"flavor": flavor.value, "batch_uuid": batch_uuid}),
        status="COMPLETED", executed_at=datetime.utcnow(), completed_at=datetime.utcnow(),
    )
    db.add(command)
    
    log = SystemLog(level=LogLevel.INFO, source="API", message=f"Stored {flavor.value} RAW_DOUGH in {slot.slot_name}")
    db.add(log)
    db.commit()
    
    # Broadcast inventory update
    await broadcast_state_update(db, "inventory_update", {
        "slot_name": slot.slot_name,
        "action": "store",
        "cookie_flavor": flavor.value,
        "cookie_status": "RAW_DOUGH",
    })
    
    return CommandResponse(success=True, message=f"Cookie stored in {slot.slot_name}",
                          command_id=command.id, slot_name=slot.slot_name, batch_uuid=batch_uuid)

@app.post("/order/retrieve", response_model=CommandResponse, tags=["Orders"])
async def retrieve_cookie(data: RetrieveRequest, db: Session = Depends(get_db)):
    slot = db.query(InventorySlot).filter(InventorySlot.slot_name == data.slot_name).first()
    if not slot:
        raise HTTPException(status_code=404, detail=f"Slot {data.slot_name} not found")
    if not slot.carrier_id:
        raise HTTPException(status_code=400, detail=f"Slot {data.slot_name} is empty")
    
    carrier = db.query(Carrier).filter(Carrier.id == slot.carrier_id).first()
    cookie = db.query(Cookie).filter(Cookie.carrier_id == carrier.id).first() if carrier else None
    batch_uuid = cookie.batch_uuid if cookie else None
    
    if cookie:
        cookie.status = CookieStatus.SHIPPED
    slot.carrier_id = None
    
    command = Command(
        command_type="RETRIEVE", target_slot=data.slot_name,
        payload_json=json.dumps({"batch_uuid": batch_uuid}),
        status="COMPLETED", executed_at=datetime.utcnow(), completed_at=datetime.utcnow(),
    )
    db.add(command)
    
    log = SystemLog(level=LogLevel.INFO, source="API", message=f"Retrieved from {data.slot_name}")
    db.add(log)
    db.commit()
    
    # Broadcast inventory update
    await broadcast_state_update(db, "inventory_update", {
        "slot_name": data.slot_name,
        "action": "retrieve",
    })
    
    return CommandResponse(success=True, message=f"Retrieved from {data.slot_name}",
                          command_id=command.id, slot_name=data.slot_name, batch_uuid=batch_uuid)

@app.post("/order/process", response_model=CommandResponse, tags=["Orders"])
async def process_cookie(data: ProcessOrderRequest, db: Session = Depends(get_db)):
    """
    Process a RAW_DOUGH cookie: Storage -> Oven -> Conveyor -> BAKED.
    
    If source_slot is not provided, automatically selects the first available
    slot containing a RAW_DOUGH cookie. Optionally filters by flavor.
    
    Parameters
    ----------
    data : ProcessOrderRequest
        source_slot : Optional slot name (e.g., 'A1'). If None, auto-selects.
        flavor : Optional flavor filter for auto-selection (e.g., 'CHOCO').
    
    Returns
    -------
    CommandResponse
        Success status, command ID, slot name, and batch UUID.
    """
    # Auto-select slot if not provided
    if data.source_slot:
        slot = db.query(InventorySlot).filter(InventorySlot.slot_name == data.source_slot).first()
        if not slot:
            raise HTTPException(status_code=404, detail=f"Slot {data.source_slot} not found")
        if not slot.carrier_id:
            raise HTTPException(status_code=400, detail=f"Slot {data.source_slot} is empty")
    else:
        # Auto-select: Find first slot with RAW_DOUGH cookie
        slots = db.query(InventorySlot).filter(InventorySlot.carrier_id != None).all()
        slot = None
        for s in slots:
            carrier = db.query(Carrier).filter(Carrier.id == s.carrier_id).first()
            if carrier:
                cookie = db.query(Cookie).filter(
                    Cookie.carrier_id == carrier.id,
                    Cookie.status == CookieStatus.RAW_DOUGH
                ).first()
                if cookie:
                    # Optional flavor filter
                    if data.flavor:
                        try:
                            target_flavor = CookieFlavor[data.flavor.upper()]
                            if cookie.flavor != target_flavor:
                                continue
                        except KeyError:
                            pass
                    slot = s
                    break
        
        if not slot:
            raise HTTPException(status_code=400, detail="No RAW_DOUGH cookies available for processing")
    
    carrier = db.query(Carrier).filter(Carrier.id == slot.carrier_id).first()
    cookie = db.query(Cookie).filter(Cookie.carrier_id == carrier.id).first() if carrier else None
    
    if not cookie:
        raise HTTPException(status_code=400, detail="No cookie found in slot")
    if cookie.status != CookieStatus.RAW_DOUGH:
        raise HTTPException(status_code=400, detail=f"Cookie is not RAW_DOUGH (current: {cookie.status.value})")
    
    # Update cookie status to BAKED
    cookie.status = CookieStatus.BAKED
    batch_uuid = cookie.batch_uuid
    
    command = Command(
        command_type="PROCESS", target_slot=slot.slot_name,
        payload_json=json.dumps({"batch_uuid": batch_uuid, "new_status": "BAKED"}),
        status="PENDING",  # Queue for controller to process
    )
    db.add(command)
    
    log = SystemLog(level=LogLevel.INFO, source="API", 
                   message=f"Queued process command for {slot.slot_name} (cookie {batch_uuid[:8]}...)")
    db.add(log)
    db.commit()
    
    # Broadcast inventory update
    await broadcast_state_update(db, "inventory_update", {
        "slot_name": slot.slot_name,
        "action": "process",
        "cookie_status": "BAKED",
    })
    
    return CommandResponse(success=True, message=f"Cookie from {slot.slot_name} queued for processing",
                          command_id=command.id, slot_name=slot.slot_name, batch_uuid=batch_uuid)

# ============================================================================
# Dashboard Endpoint
# ============================================================================

@app.get("/dashboard/data", tags=["Dashboard"])
def get_dashboard_data(db: Session = Depends(get_db)):
    """Get full dashboard data (for polling fallback)"""
    return get_full_dashboard_state(db)

# ============================================================================
# Maintenance Endpoints
# ============================================================================

@app.post("/maintenance/initialize", tags=["Maintenance"])
async def initialize_system(db: Session = Depends(get_db), _key: str = Depends(verify_api_key)):
    seed_inventory_slots(db)
    seed_hardware_devices(db)
    seed_components(db)
    log = SystemLog(level=LogLevel.INFO, source="MAINTENANCE", message="System initialized with components")
    db.add(log)
    db.commit()
    
    await broadcast_state_update(db, "system_initialized", {})
    return {"success": True, "message": "System initialized with 14 components"}

@app.post("/maintenance/reset", tags=["Maintenance"])
async def reset_system(db: Session = Depends(get_db), _key: str = Depends(verify_api_key)):
    # Reset hardware positions
    devices = db.query(HardwareState).all()
    for hw in devices:
        hw.current_x = 0
        hw.current_y = 0
        hw.current_z = 0
        hw.status = HardwareStatus.IDLE
    
    # Reset motor states
    motors = db.query(MotorState).all()
    for m in motors:
        m.current_amps = 0.0
        m.is_active = False
        m.health_score = 1.0
        m.accumulated_runtime_sec = 0.0
    
    # Reset sensor states
    sensors = db.query(SensorState).all()
    for s in sensors:
        s.is_triggered = False
    
    log = SystemLog(level=LogLevel.INFO, source="MAINTENANCE", message="System reset - all components restored")
    db.add(log)
    db.commit()
    
    await broadcast_state_update(db, "system_reset", {})
    return {"success": True, "message": "System reset complete"}

@app.post("/maintenance/emergency-stop", tags=["Maintenance"])
async def emergency_stop(db: Session = Depends(get_db), _key: str = Depends(verify_api_key)):
    # Stop all hardware
    devices = db.query(HardwareState).all()
    for hw in devices:
        hw.status = HardwareStatus.ERROR
        hw.last_error = "Emergency stop"
    
    # Deactivate all motors
    motors = db.query(MotorState).all()
    for m in motors:
        m.is_active = False
        m.current_amps = 0.0
    
    alert = Alert(
        alert_type="EMERGENCY", severity=AlertSeverity.CRITICAL,
        title="Emergency Stop", message="All hardware stopped by operator",
    )
    db.add(alert)
    log = SystemLog(level=LogLevel.CRITICAL, source="SAFETY", message="EMERGENCY STOP ACTIVATED")
    db.add(log)
    db.commit()
    
    await broadcast_state_update(db, "emergency_stop", {"message": "All hardware stopped"})
    return {"success": True, "message": "Emergency stop activated"}

@app.get("/health", tags=["System"])
def health_check(db: Session = Depends(get_db)):
    """Enhanced health check with database connectivity verification."""
    checks: Dict[str, Any] = {}

    # Database connectivity
    try:
        db.execute(func.count(HardwareState.device_id)).scalar()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Component counts
    try:
        motor_count = db.query(func.count(MotorState.component_id)).scalar() or 0
        sensor_count = db.query(func.count(SensorState.component_id)).scalar() or 0
        active_alerts = (
            db.query(func.count(Alert.id))
            .filter(Alert.acknowledged == False)
            .scalar()
            or 0
        )
        checks["motors"] = motor_count
        checks["sensors"] = sensor_count
        checks["active_alerts"] = active_alerts
    except Exception:
        pass

    overall = "healthy" if checks.get("database") == "ok" else "degraded"

    return {
        "status": overall,
        "timestamp": datetime.utcnow().isoformat(),
        "version": "3.0.0",
        "websocket": "ws://localhost:8000/ws",
        "checks": checks,
    }

# ============================================================================
# Command Queue Endpoints (for Controller polling)
# ============================================================================

@app.get("/commands/pending", tags=["Commands"])
def get_pending_commands(limit: int = 1, db: Session = Depends(get_db)):
    """Get pending commands for the controller to process."""
    commands = db.query(Command).filter(
        Command.status == "PENDING"
    ).order_by(Command.created_at).limit(limit).all()
    
    return [
        {
            "id": cmd.id,
            "command_type": cmd.command_type,
            "target_slot": cmd.target_slot,
            "payload_json": cmd.payload_json,
            "status": cmd.status,
            "created_at": cmd.created_at.isoformat(),
        }
        for cmd in commands
    ]

@app.post("/commands/{command_id}/status", tags=["Commands"])
def update_command_status(
    command_id: int,
    status_update: CommandStatusUpdate,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_api_key),
):
    """Update command status (called by controller)."""
    command = db.query(Command).filter(Command.id == command_id).first()
    if not command:
        raise HTTPException(status_code=404, detail=f"Command {command_id} not found")
    
    command.status = status_update.status
    if status_update.message:
        command.error_message = status_update.message
    
    if command.status == "IN_PROGRESS":
        command.executed_at = datetime.utcnow()
    elif command.status in ["COMPLETED", "FAILED"]:
        command.completed_at = datetime.utcnow()
    
    db.commit()
    return {"success": True, "command_id": command_id, "status": command.status}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

