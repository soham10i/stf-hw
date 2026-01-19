"""
STF Digital Twin - High-Fidelity Component Dashboard
Industrial Apple Glassmorphism Design with WebSocket Real-Time Updates
"""

import streamlit as st
# from streamlit_autorefresh import st_autorefresh  # Disabled for manual refresh
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import time
import os
import json
import threading
import queue
from typing import Optional, Dict, Any

# Configuration
API_URL = os.environ.get("STF_API_URL", "http://localhost:8000")
WS_URL = os.environ.get("STF_WS_URL", "ws://localhost:8000/ws")
REFRESH_INTERVAL = 2000  # milliseconds for auto-refresh (not used in manual mode)

# Page Configuration
st.set_page_config(
    page_title="STF Digital Twin",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ============================================================================
# GLASSMORPHISM CSS - Industrial Apple Design
# ============================================================================

GLASSMORPHISM_CSS = """
<style>
/* Import Google Font */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* Global Styles */
.stApp {
    background: linear-gradient(135deg, #0a0a1a 0%, #1a1a2e 50%, #0f0f23 100%);
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}

/* Hide Streamlit branding */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}

/* Ensure all interactive elements are accessible */
button, input, select, textarea, .stButton, .stSelectbox, .stTextInput {
    pointer-events: auto !important;
    position: relative;
    z-index: 10;
}

/* Glass Card Base */
.glass-card {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 24px;
    padding: 24px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
    transition: all 0.3s ease;
}

.glass-card:hover {
    background: rgba(255, 255, 255, 0.08);
    border-color: rgba(255, 255, 255, 0.15);
}

/* KPI Card */
.kpi-card {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 20px;
    padding: 20px 24px;
    text-align: center;
}

.kpi-value {
    font-size: 42px;
    font-weight: 600;
    color: #ffffff;
    margin: 8px 0;
    letter-spacing: -1px;
}

.kpi-label {
    font-size: 13px;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.5);
    text-transform: uppercase;
    letter-spacing: 1px;
}

/* Status Colors */
.status-active { color: #00ff88; text-shadow: 0 0 20px rgba(0, 255, 136, 0.5); }
.status-error { color: #ff4757; text-shadow: 0 0 20px rgba(255, 71, 87, 0.5); }
.status-warning { color: #ffa502; text-shadow: 0 0 20px rgba(255, 165, 2, 0.5); }
.status-idle { color: #70a1ff; text-shadow: 0 0 20px rgba(112, 161, 255, 0.5); }

/* Header */
.header-container {
    background: rgba(255, 255, 255, 0.03);
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    padding: 16px 32px;
    margin: -1rem -1rem 2rem -1rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.header-title {
    font-size: 24px;
    font-weight: 600;
    color: #ffffff;
    display: flex;
    align-items: center;
    gap: 12px;
}

.live-badge {
    background: linear-gradient(135deg, #00ff88 0%, #00cc6a 100%);
    color: #000;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
    animation: pulse 2s infinite;
}

@keyframes pulse {
    0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(0, 255, 136, 0.4); }
    50% { opacity: 0.8; box-shadow: 0 0 0 10px rgba(0, 255, 136, 0); }
}

/* Conveyor Belt Progress */
.conveyor-container {
    background: rgba(255, 255, 255, 0.03);
    border-radius: 16px;
    padding: 16px;
    margin: 16px 0;
}

.conveyor-belt {
    height: 40px;
    background: linear-gradient(90deg, 
        rgba(255,255,255,0.05) 0%, 
        rgba(255,255,255,0.1) 50%, 
        rgba(255,255,255,0.05) 100%);
    border-radius: 8px;
    position: relative;
    overflow: hidden;
    border: 1px solid rgba(255,255,255,0.1);
}

.conveyor-progress {
    height: 100%;
    background: linear-gradient(90deg, #00ff88, #00cc6a);
    border-radius: 8px;
    transition: width 0.3s ease;
}

.sensor-indicator {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    font-weight: 600;
    margin: 0 4px;
    transition: all 0.3s ease;
}

.sensor-on {
    background: linear-gradient(135deg, #00ff88, #00cc6a);
    color: #000;
    box-shadow: 0 0 20px rgba(0, 255, 136, 0.5);
}

.sensor-off {
    background: rgba(255, 255, 255, 0.1);
    color: rgba(255, 255, 255, 0.5);
}

/* Motor Health Card */
.motor-card {
    background: rgba(255, 255, 255, 0.03);
    border-radius: 16px;
    padding: 16px;
    margin-bottom: 12px;
    border: 1px solid rgba(255, 255, 255, 0.08);
}

.motor-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
}

.motor-name {
    font-weight: 600;
    color: #ffffff;
    font-size: 14px;
}

.motor-status {
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 600;
}

.motor-active {
    background: rgba(0, 255, 136, 0.2);
    color: #00ff88;
}

.motor-idle {
    background: rgba(112, 161, 255, 0.2);
    color: #70a1ff;
}

.health-bar-container {
    height: 8px;
    background: rgba(255, 255, 255, 0.1);
    border-radius: 4px;
    overflow: hidden;
    margin: 8px 0;
}

.health-bar {
    height: 100%;
    border-radius: 4px;
    transition: width 0.3s ease;
}

.health-good { background: linear-gradient(90deg, #00ff88, #00cc6a); }
.health-warning { background: linear-gradient(90deg, #ffa502, #ff7f00); }
.health-critical { background: linear-gradient(90deg, #ff4757, #ff3344); }

/* Inventory Grid Slot */
.slot-card {
    background: rgba(255, 255, 255, 0.03);
    backdrop-filter: blur(15px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 16px;
    padding: 16px;
    text-align: center;
    min-height: 100px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    transition: all 0.3s ease;
}

.slot-card:hover {
    background: rgba(255, 255, 255, 0.06);
    transform: scale(1.02);
}

.slot-name {
    font-size: 18px;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.9);
    margin-bottom: 8px;
}

.slot-empty { border-color: rgba(255, 255, 255, 0.05); }
.slot-choco { border-color: rgba(139, 90, 43, 0.5); box-shadow: inset 0 0 30px rgba(139, 90, 43, 0.2); }
.slot-vanilla { border-color: rgba(255, 235, 180, 0.5); box-shadow: inset 0 0 30px rgba(255, 235, 180, 0.2); }
.slot-strawberry { border-color: rgba(255, 105, 180, 0.5); box-shadow: inset 0 0 30px rgba(255, 105, 180, 0.2); }

.cookie-indicator {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    margin-top: 8px;
    box-shadow: 0 0 15px rgba(0,0,0,0.3);
}

/* RAW_DOUGH - Cream/beige dough color for all flavors */
.cookie-raw { background: radial-gradient(circle, #F5DEB3 0%, #DEB887 50%, #D2B48C 100%); box-shadow: 0 0 15px rgba(222, 184, 135, 0.5); }

/* BAKED cookies - Flavor specific colors */
.cookie-choco { background: radial-gradient(circle, #5D4037 0%, #3E2723 50%, #2C1810 100%); box-shadow: 0 0 15px rgba(93, 64, 55, 0.6); }
.cookie-vanilla { background: radial-gradient(circle, #FFFEF0 0%, #FFF8E7 50%, #F5F5DC 100%); box-shadow: 0 0 15px rgba(255, 255, 240, 0.6); }
.cookie-strawberry { background: radial-gradient(circle, #FF69B4 0%, #FF1493 50%, #DB7093 100%); box-shadow: 0 0 15px rgba(255, 105, 180, 0.6); }

/* Cookie Status Badge */
.cookie-status {
    font-size: 9px;
    padding: 2px 6px;
    border-radius: 8px;
    margin-top: 4px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.status-raw_dough { background: rgba(255, 193, 7, 0.2); color: #ffc107; }
.status-baked { background: rgba(255, 152, 0, 0.2); color: #ff9800; }
.status-packaged { background: rgba(76, 175, 80, 0.2); color: #4caf50; }

/* Log Entry */
.log-entry {
    background: rgba(255, 255, 255, 0.02);
    border-left: 3px solid #70a1ff;
    padding: 8px 12px;
    margin: 4px 0;
    border-radius: 0 8px 8px 0;
    font-size: 12px;
    color: rgba(255, 255, 255, 0.7);
}

.log-entry-error { border-left-color: #ff4757; }
.log-entry-warning { border-left-color: #ffa502; }
.log-entry-critical { border-left-color: #ff4757; background: rgba(255, 71, 87, 0.1); }

/* Power Gauge */
.power-gauge {
    background: rgba(255, 255, 255, 0.03);
    border-radius: 16px;
    padding: 16px;
    text-align: center;
}

.power-value {
    font-size: 32px;
    font-weight: 600;
    color: #00ff88;
}

.power-label {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.5);
    text-transform: uppercase;
}

/* Streamlit Overrides */
.stMetric {
    background: rgba(255, 255, 255, 0.03) !important;
    backdrop-filter: blur(20px) !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    border-radius: 20px !important;
    padding: 20px !important;
}

.stMetric label {
    color: rgba(255, 255, 255, 0.5) !important;
    font-size: 13px !important;
    text-transform: uppercase !important;
    letter-spacing: 1px !important;
}

.stMetric [data-testid="stMetricValue"] {
    font-size: 36px !important;
    font-weight: 600 !important;
    color: #ffffff !important;
}

div[data-testid="stVerticalBlock"] > div {
    background: transparent !important;
}

.stButton > button {
    background: rgba(255, 255, 255, 0.05) !important;
    backdrop-filter: blur(10px) !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    border-radius: 12px !important;
    color: #ffffff !important;
    font-weight: 500 !important;
    padding: 12px 24px !important;
    transition: all 0.3s ease !important;
}

.stButton > button:hover {
    background: rgba(255, 255, 255, 0.1) !important;
    border-color: rgba(255, 255, 255, 0.2) !important;
    transform: translateY(-2px) !important;
}

.stSelectbox > div > div {
    background: rgba(255, 255, 255, 0.05) !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    border-radius: 12px !important;
    color: #ffffff !important;
}

/* Section Title */
.section-title {
    font-size: 16px;
    font-weight: 600;
    color: rgba(255, 255, 255, 0.9);
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 8px;
}

.section-title::before {
    content: '';
    width: 4px;
    height: 20px;
    background: linear-gradient(180deg, #00ff88 0%, #00cc6a 100%);
    border-radius: 2px;
}

/* TTF Badge */
.ttf-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 8px;
    font-size: 10px;
    font-weight: 600;
}

.ttf-good { background: rgba(0, 255, 136, 0.2); color: #00ff88; }
.ttf-warning { background: rgba(255, 165, 2, 0.2); color: #ffa502; }
.ttf-critical { background: rgba(255, 71, 87, 0.2); color: #ff4757; }
</style>
"""

# Inject CSS
st.markdown(GLASSMORPHISM_CSS, unsafe_allow_html=True)

# ============================================================================
# API Functions
# ============================================================================

def fetch_dashboard_data():
    """Fetch all dashboard data from API"""
    try:
        response = requests.get(f"{API_URL}/dashboard/data", timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        st.error(f"API Error: {e}")
    return None

def store_cookie(flavor: str, slot_name: str = None):
    """Store a cookie"""
    try:
        payload = {"flavor": flavor}
        if slot_name:
            payload["slot_name"] = slot_name
        response = requests.post(f"{API_URL}/order/store", json=payload, timeout=5)
        return response.json()
    except Exception as e:
        return {"success": False, "message": str(e)}

def retrieve_cookie(slot_name: str):
    """Retrieve a cookie"""
    try:
        response = requests.post(f"{API_URL}/order/retrieve", json={"slot_name": slot_name}, timeout=5)
        return response.json()
    except Exception as e:
        return {"success": False, "message": str(e)}

def process_cookie(slot_name: str):
    """Process a cookie (RAW_DOUGH -> BAKED)"""
    try:
        response = requests.post(f"{API_URL}/order/process", json={"source_slot": slot_name}, timeout=5)
        return response.json()
    except Exception as e:
        return {"success": False, "message": str(e)}

def emergency_stop():
    """Trigger emergency stop"""
    try:
        response = requests.post(f"{API_URL}/maintenance/emergency-stop", timeout=5)
        return response.json()
    except Exception as e:
        return {"success": False, "message": str(e)}

def reset_system():
    """Reset the system"""
    try:
        response = requests.post(f"{API_URL}/maintenance/reset", timeout=5)
        return response.json()
    except Exception as e:
        return {"success": False, "message": str(e)}

def initialize_system():
    """Initialize the system"""
    try:
        response = requests.post(f"{API_URL}/maintenance/initialize", timeout=5)
        return response.json()
    except Exception as e:
        return {"success": False, "message": str(e)}

# ============================================================================
# Helper Functions
# ============================================================================

def get_health_class(health_score: float) -> str:
    """Get CSS class based on health score"""
    if health_score >= 0.8:
        return "health-good"
    elif health_score >= 0.5:
        return "health-warning"
    return "health-critical"

def get_ttf_class(ttf_hours: Optional[float]) -> str:
    """Get CSS class based on time to failure"""
    if ttf_hours is None:
        return "ttf-good"
    if ttf_hours > 100:
        return "ttf-good"
    elif ttf_hours > 20:
        return "ttf-warning"
    return "ttf-critical"

def format_ttf(ttf_hours: Optional[float]) -> str:
    """Format time to failure for display"""
    if ttf_hours is None:
        return "N/A"
    if ttf_hours > 1000:
        return f"{ttf_hours/1000:.1f}k hrs"
    return f"{ttf_hours:.0f} hrs"

# ============================================================================
# Dashboard Layout
# ============================================================================

# Header
st.markdown("""
<div class="header-container">
    <div class="header-title">
        🏭 STF Digital Twin
        <span class="live-badge">● Live</span>
    </div>
    <div style="color: rgba(255,255,255,0.5); font-size: 13px;">
        High-Fidelity Component Twin • Industrial Automation
    </div>
</div>
""", unsafe_allow_html=True)

# Fetch data
data = fetch_dashboard_data()

if data:
    stats = data.get("stats", {})
    inventory = data.get("inventory", [])
    hardware = data.get("hardware", [])
    motors = data.get("motors", [])
    sensors = data.get("sensors", [])
    conveyor = data.get("conveyor", {})
    logs = data.get("logs", [])
    energy = data.get("energy", {})
    
    # ========================================================================
    # Row 1: KPI Cards
    # ========================================================================
    
    st.markdown('<div class="section-title">System Overview</div>', unsafe_allow_html=True)
    
    kpi_cols = st.columns(5)
    
    with kpi_cols[0]:
        occupied = stats.get("occupied_slots", 0)
        total = stats.get("total_slots", 9)
        st.metric(
            label="Inventory",
            value=f"{occupied}/{total}",
            delta=f"{total - occupied} available"
        )
    
    with kpi_cols[1]:
        raw = stats.get("raw_dough_cookies", 0)
        baked = stats.get("baked_cookies", 0)
        st.metric(
            label="Production",
            value=f"{baked} baked",
            delta=f"{raw} raw dough"
        )
    
    with kpi_cols[2]:
        kwh = energy.get("total_kwh", 0)
        st.metric(
            label="Energy Usage",
            value=f"{kwh:.3f} kWh",
            delta="Last 24h"
        )
    
    with kpi_cols[3]:
        # Calculate average motor health
        if motors:
            avg_health = sum(m.get("health_score", 1.0) for m in motors) / len(motors)
            health_pct = f"{avg_health * 100:.0f}%"
        else:
            health_pct = "N/A"
        st.metric(
            label="Avg Motor Health",
            value=health_pct,
            delta=f"{len(motors)} motors"
        )
    
    with kpi_cols[4]:
        healthy = stats.get("system_healthy", False)
        status_text = "✓ Healthy" if healthy else "⚠ Alert"
        st.metric(
            label="System Status",
            value=status_text,
            delta=f"{stats.get('active_devices', 0)} devices"
        )
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # ========================================================================
    # Row 2: Conveyor Belt + Motor Health
    # ========================================================================
    
    conveyor_cols = st.columns([2, 1])
    
    with conveyor_cols[0]:
        st.markdown('<div class="section-title">Conveyor Belt System</div>', unsafe_allow_html=True)
        
        # Conveyor belt progress bar
        belt_pct = conveyor.get("belt_position_pct", 0)
        motor_active = conveyor.get("motor_active", False)
        motor_amps = conveyor.get("motor_amps", 0)
        sensor_states = conveyor.get("sensors", {})
        
        st.markdown(f"""
        <div class="conveyor-container">
            <div style="display: flex; justify-content: space-between; margin-bottom: 12px;">
                <span style="color: rgba(255,255,255,0.7);">Belt Position: <strong>{belt_pct:.1f}%</strong></span>
                <span style="color: {'#00ff88' if motor_active else 'rgba(255,255,255,0.5)'};">
                    Motor: <strong>{'RUNNING' if motor_active else 'IDLE'}</strong> ({motor_amps:.2f}A)
                </span>
            </div>
            <div class="conveyor-belt">
                <div class="conveyor-progress" style="width: {belt_pct}%;"></div>
            </div>
            <div style="display: flex; justify-content: space-between; margin-top: 12px; padding: 0 20px;">
                <div class="sensor-indicator {'sensor-on' if sensor_states.get('L1', False) else 'sensor-off'}">L1</div>
                <div class="sensor-indicator {'sensor-on' if sensor_states.get('L2', False) else 'sensor-off'}">L2</div>
                <div class="sensor-indicator {'sensor-on' if sensor_states.get('L3', False) else 'sensor-off'}">L3</div>
                <div class="sensor-indicator {'sensor-on' if sensor_states.get('L4', False) else 'sensor-off'}">L4</div>
            </div>
            <div style="display: flex; justify-content: space-between; margin-top: 4px; padding: 0 12px; font-size: 10px; color: rgba(255,255,255,0.4);">
                <span>Entry</span>
                <span>Process</span>
                <span>Exit</span>
                <span>Overflow</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with conveyor_cols[1]:
        st.markdown('<div class="section-title">Live Power</div>', unsafe_allow_html=True)
        
        # Calculate total current draw from all active motors
        total_amps = sum(m.get("current_amps", 0) for m in motors)
        total_watts = total_amps * 24  # 24V system
        
        # Get max current for gauge
        max_amps = sum(m.get("spec_max_current", 5.0) for m in motors)
        
        # Power gauge
        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=total_amps,
            number={"suffix": " A", "font": {"size": 32, "color": "#00ff88"}},
            gauge={
                "axis": {"range": [0, max_amps], "tickcolor": "rgba(255,255,255,0.3)"},
                "bar": {"color": "#00ff88"},
                "bgcolor": "rgba(255,255,255,0.05)",
                "borderwidth": 0,
                "steps": [
                    {"range": [0, max_amps * 0.6], "color": "rgba(0,255,136,0.1)"},
                    {"range": [max_amps * 0.6, max_amps * 0.8], "color": "rgba(255,165,2,0.1)"},
                    {"range": [max_amps * 0.8, max_amps], "color": "rgba(255,71,87,0.1)"},
                ],
                "threshold": {
                    "line": {"color": "#ff4757", "width": 2},
                    "thickness": 0.75,
                    "value": max_amps * 0.9
                }
            }
        ))
        
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            font={"color": "rgba(255,255,255,0.7)"},
            height=200,
            margin=dict(l=20, r=20, t=30, b=20)
        )
        
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        
        st.markdown(f"""
        <div style="text-align: center; color: rgba(255,255,255,0.5); font-size: 12px;">
            Power: <strong style="color: #00ff88;">{total_watts:.1f}W</strong> • 
            Limit: {max_amps:.1f}A
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # ========================================================================
    # Row 3: Motor Health + Robot Position + Inventory
    # ========================================================================
    
    main_cols = st.columns([1, 2, 1])
    
    # Motor Health Cards
    with main_cols[0]:
        st.markdown('<div class="section-title">Motor Health</div>', unsafe_allow_html=True)
        
        for motor in motors[:6]:  # Show first 6 motors
            comp_id = motor.get("component_id", "Unknown")
            health = motor.get("health_score", 1.0)
            is_active = motor.get("is_active", False)
            current = motor.get("current_amps", 0)
            ttf = motor.get("time_to_failure_hours")
            
            health_class = get_health_class(health)
            ttf_class = get_ttf_class(ttf)
            status_class = "motor-active" if is_active else "motor-idle"
            
            st.markdown(f"""
            <div class="motor-card">
                <div class="motor-header">
                    <span class="motor-name">{comp_id}</span>
                    <span class="motor-status {status_class}">{'● ON' if is_active else '○ OFF'}</span>
                </div>
                <div class="health-bar-container">
                    <div class="health-bar {health_class}" style="width: {health * 100}%;"></div>
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 11px; color: rgba(255,255,255,0.5);">
                    <span>Health: {health * 100:.0f}%</span>
                    <span class="ttf-badge {ttf_class}">TTF: {format_ttf(ttf)}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
    
    # Robot Position Monitor
    with main_cols[1]:
        st.markdown('<div class="section-title">Robot Position Monitor</div>', unsafe_allow_html=True)
        
        if hardware:
            hw_df = pd.DataFrame([
                {
                    "Device": h["device_id"],
                    "X": h["current_x"],
                    "Y": h["current_y"],
                    "Status": h["status"]
                }
                for h in hardware
            ])
            
            color_map = {
                "IDLE": "#00ff88",
                "MOVING": "#ffa502",
                "ERROR": "#ff4757",
                "MAINTENANCE": "#70a1ff"
            }
            
            fig = go.Figure()
            
            # Add grid lines for slots
            for slot in inventory:
                fig.add_shape(
                    type="rect",
                    x0=slot["x_pos"] - 40, y0=slot["y_pos"] - 40,
                    x1=slot["x_pos"] + 40, y1=slot["y_pos"] + 40,
                    line=dict(color="rgba(255,255,255,0.1)", width=1),
                    fillcolor="rgba(255,255,255,0.02)"
                )
                fig.add_annotation(
                    x=slot["x_pos"], y=slot["y_pos"],
                    text=slot["slot_name"],
                    showarrow=False,
                    font=dict(color="rgba(255,255,255,0.3)", size=10)
                )
            
            # Add robot markers
            for _, row in hw_df.iterrows():
                fig.add_trace(go.Scatter(
                    x=[row["X"]],
                    y=[row["Y"]],
                    mode="markers+text",
                    marker=dict(
                        size=20,
                        color=color_map.get(row["Status"], "#70a1ff"),
                        symbol="diamond",
                        line=dict(color="white", width=2)
                    ),
                    text=[row["Device"]],
                    textposition="top center",
                    textfont=dict(color="white", size=11),
                    name=row["Device"],
                    hovertemplate=f"<b>{row['Device']}</b><br>X: {row['X']}<br>Y: {row['Y']}<br>Status: {row['Status']}<extra></extra>"
                ))
            
            fig.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(
                    range=[-20, 420],
                    showgrid=True,
                    gridcolor="rgba(255,255,255,0.05)",
                    zeroline=False,
                    color="rgba(255,255,255,0.5)"
                ),
                yaxis=dict(
                    range=[-20, 420],
                    showgrid=True,
                    gridcolor="rgba(255,255,255,0.05)",
                    zeroline=False,
                    color="rgba(255,255,255,0.5)"
                ),
                showlegend=False,
                margin=dict(l=40, r=40, t=20, b=40),
                height=350
            )
            
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("No hardware data available")
    
    # Inventory Grid
    with main_cols[2]:
        st.markdown('<div class="section-title">Rack Grid</div>', unsafe_allow_html=True)
        
        grid_rows = [["A1", "A2", "A3"], ["B1", "B2", "B3"], ["C1", "C2", "C3"]]
        inv_lookup = {s["slot_name"]: s for s in inventory}
        
        for row in grid_rows:
            cols = st.columns(3)
            for i, slot_name in enumerate(row):
                with cols[i]:
                    slot_data = inv_lookup.get(slot_name, {})
                    flavor = slot_data.get("cookie_flavor")
                    status = slot_data.get("cookie_status", "")
                    
                    if flavor:
                        flavor_lower = flavor.lower()
                        status_lower = status.lower() if status else ""
                        slot_class = f"slot-{flavor_lower}"
                        
                        # RAW_DOUGH = cream color, BAKED = flavor-specific color
                        if status_lower == "raw_dough":
                            cookie_class = "cookie-raw"  # Cream dough color
                        else:
                            cookie_class = f"cookie-{flavor_lower}"  # Baked: choco/vanilla/strawberry
                        
                        cookie_html = f'<div class="cookie-indicator {cookie_class}"></div>'
                        status_class = f"status-{status_lower}" if status else ""
                        status_html = f'<span class="cookie-status {status_class}">{status}</span>' if status else ""
                    else:
                        slot_class = "slot-empty"
                        cookie_html = '<div style="color: rgba(255,255,255,0.3); font-size: 12px;">Empty</div>'
                        status_html = ""
                    
                    st.markdown(f"""
                    <div class="slot-card {slot_class}">
                        <div class="slot-name">{slot_name}</div>
                        {cookie_html}
                        {status_html}
                    </div>
                    """, unsafe_allow_html=True)
        
        # Legend
        st.markdown("""
        <div style="display: flex; gap: 12px; margin-top: 16px; justify-content: center; flex-wrap: wrap;">
            <div style="display: flex; align-items: center; gap: 4px;">
                <div style="width: 10px; height: 10px; border-radius: 50%; background: #DEB887;"></div>
                <span style="color: rgba(255,255,255,0.5); font-size: 10px;">Raw Dough</span>
            </div>
            <div style="display: flex; align-items: center; gap: 4px;">
                <div style="width: 10px; height: 10px; border-radius: 50%; background: #3E2723;"></div>
                <span style="color: rgba(255,255,255,0.5); font-size: 10px;">Choco</span>
            </div>
            <div style="display: flex; align-items: center; gap: 4px;">
                <div style="width: 10px; height: 10px; border-radius: 50%; background: #FFFEF0; border: 1px solid rgba(255,255,255,0.3);"></div>
                <span style="color: rgba(255,255,255,0.5); font-size: 10px;">Vanilla</span>
            </div>
            <div style="display: flex; align-items: center; gap: 4px;">
                <div style="width: 10px; height: 10px; border-radius: 50%; background: #FF69B4;"></div>
                <span style="color: rgba(255,255,255,0.5); font-size: 10px;">Strawberry</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # ========================================================================
    # Row 4: Control Deck + Logs
    # ========================================================================
    
    bottom_cols = st.columns([1, 1, 1])
    
    # Control Deck
    with bottom_cols[0]:
        st.markdown('<div class="section-title">Control Deck</div>', unsafe_allow_html=True)
        
        # Flavor selection
        flavor = st.selectbox("Cookie Flavor", ["CHOCO", "VANILLA", "STRAWBERRY"], label_visibility="collapsed")
        
        ctrl_cols = st.columns(2)
        with ctrl_cols[0]:
            if st.button("🍪 Store", use_container_width=True):
                result = store_cookie(flavor)
                if result.get("success"):
                    st.success(f"Stored in {result.get('slot_name')}")
                else:
                    st.error(result.get("message"))
        
        with ctrl_cols[1]:
            slot_to_retrieve = st.selectbox(
                "Retrieve from",
                [s["slot_name"] for s in inventory if s.get("carrier_id")],
                label_visibility="collapsed",
                key="retrieve_slot"
            )
        
        if st.button("📤 Retrieve", use_container_width=True):
            if slot_to_retrieve:
                result = retrieve_cookie(slot_to_retrieve)
                if result.get("success"):
                    st.success(result.get("message"))
                else:
                    st.error(result.get("message"))
        
        # Process cookie (RAW_DOUGH -> BAKED)
        raw_slots = [s["slot_name"] for s in inventory if s.get("cookie_status") == "RAW_DOUGH"]
        if raw_slots:
            slot_to_process = st.selectbox("Process (Bake)", raw_slots, label_visibility="collapsed", key="process_slot")
            if st.button("🔥 Bake Cookie", use_container_width=True):
                result = process_cookie(slot_to_process)
                if result.get("success"):
                    st.success("Cookie baked!")
                else:
                    st.error(result.get("message"))
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        emg_cols = st.columns(3)
        with emg_cols[0]:
            if st.button("⚙️ Init", use_container_width=True):
                result = initialize_system()
                st.info(result.get("message", "Initialized"))
        
        with emg_cols[1]:
            if st.button("🔄 Reset", use_container_width=True):
                result = reset_system()
                st.info(result.get("message", "Reset"))
        
        with emg_cols[2]:
            if st.button("🛑 E-STOP", use_container_width=True, type="primary"):
                result = emergency_stop()
                st.warning("Emergency stop!")
    
    # Hardware Status
    with bottom_cols[1]:
        st.markdown('<div class="section-title">Hardware Status</div>', unsafe_allow_html=True)
        
        for hw in hardware:
            status = hw["status"]
            status_color = {
                "IDLE": "#00ff88",
                "MOVING": "#ffa502",
                "ERROR": "#ff4757",
                "MAINTENANCE": "#70a1ff"
            }.get(status, "#70a1ff")
            
            st.markdown(f"""
            <div style="
                background: rgba(255,255,255,0.03);
                border-radius: 12px;
                padding: 12px 16px;
                margin-bottom: 8px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            ">
                <div>
                    <div style="font-weight: 600; color: #fff; font-size: 14px;">{hw['device_id']}</div>
                    <div style="font-size: 11px; color: rgba(255,255,255,0.5);">
                        X: {hw['current_x']:.0f} Y: {hw['current_y']:.0f} Z: {hw['current_z']:.0f}
                    </div>
                </div>
                <div style="
                    background: {status_color}20;
                    color: {status_color};
                    padding: 4px 12px;
                    border-radius: 12px;
                    font-size: 11px;
                    font-weight: 600;
                ">{status}</div>
            </div>
            """, unsafe_allow_html=True)
    
    # System Logs
    with bottom_cols[2]:
        st.markdown('<div class="section-title">System Logs</div>', unsafe_allow_html=True)
        
        log_container = st.container()
        with log_container:
            for log in logs[:8]:
                level = log.get("level", "INFO")
                level_class = {
                    "ERROR": "log-entry-error",
                    "WARNING": "log-entry-warning",
                    "CRITICAL": "log-entry-critical"
                }.get(level, "")
                
                timestamp = log.get("timestamp", "")
                if timestamp:
                    try:
                        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                        time_str = dt.strftime("%H:%M:%S")
                    except:
                        time_str = timestamp[:8]
                else:
                    time_str = ""
                
                st.markdown(f"""
                <div class="log-entry {level_class}">
                    <span style="color: rgba(255,255,255,0.4); font-size: 10px;">{time_str}</span>
                    <span style="margin-left: 8px;">{log.get('message', '')}</span>
                </div>
                """, unsafe_allow_html=True)

else:
    # No data - show initialization prompt
    st.markdown("""
    <div style="
        text-align: center;
        padding: 60px 40px;
        background: rgba(255,255,255,0.03);
        border-radius: 24px;
        margin: 40px auto;
        max-width: 500px;
    ">
        <div style="font-size: 48px; margin-bottom: 20px;">🏭</div>
        <div style="font-size: 24px; font-weight: 600; color: #fff; margin-bottom: 12px;">
            STF Digital Twin
        </div>
        <div style="color: rgba(255,255,255,0.5); margin-bottom: 24px;">
            No data available. Initialize the system to begin.
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button("⚙️ Initialize System", use_container_width=True):
            result = initialize_system()
            if result.get("success"):
                st.success("System initialized! Refreshing...")
                time.sleep(1)
                st.rerun()
            else:
                st.error(result.get("message", "Initialization failed"))

# Footer with refresh info
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: rgba(255,255,255,0.4); font-size: 12px; padding: 10px;">
    STF Digital Twin v2.0 • Auto-refreshing every 2 seconds
</div>
""", unsafe_allow_html=True)
