"""
STF Digital Twin - Glassmorphism Dashboard
Industrial Apple Design with Frosted Glass Effects
"""

import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import time
import os

# Configuration
API_URL = os.environ.get("STF_API_URL", "http://localhost:8000")
REFRESH_INTERVAL = 2  # seconds

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
@import url('https://fonts.googleapis.com/css2?family=SF+Pro+Display:wght@300;400;500;600;700&display=swap');
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

/* Glass Card Base */
.glass-card {
    background: rgba(255, 255, 255, 0.03);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 24px;
    padding: 24px;
    box-shadow: 
        0 8px 32px rgba(0, 0, 0, 0.3),
        inset 0 1px 0 rgba(255, 255, 255, 0.05);
    transition: all 0.3s ease;
}

.glass-card:hover {
    background: rgba(255, 255, 255, 0.05);
    border-color: rgba(255, 255, 255, 0.12);
    transform: translateY(-2px);
}

/* KPI Card */
.kpi-card {
    background: rgba(255, 255, 255, 0.03);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 20px;
    padding: 20px 24px;
    text-align: center;
    box-shadow: 0 4px 30px rgba(0, 0, 0, 0.2);
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
    background: rgba(255, 255, 255, 0.02);
    backdrop-filter: blur(20px);
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
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

.slot-empty {
    border-color: rgba(255, 255, 255, 0.05);
}

.slot-choco {
    border-color: rgba(139, 90, 43, 0.5);
    box-shadow: inset 0 0 30px rgba(139, 90, 43, 0.2);
}

.slot-vanilla {
    border-color: rgba(255, 235, 180, 0.5);
    box-shadow: inset 0 0 30px rgba(255, 235, 180, 0.2);
}

.slot-strawberry {
    border-color: rgba(255, 105, 180, 0.5);
    box-shadow: inset 0 0 30px rgba(255, 105, 180, 0.2);
}

.cookie-indicator {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    margin-top: 8px;
    box-shadow: 0 0 20px currentColor;
}

.cookie-choco { background: radial-gradient(circle, #8B5A2B 0%, #5D3A1A 100%); }
.cookie-vanilla { background: radial-gradient(circle, #FFFACD 0%, #F5DEB3 100%); }
.cookie-strawberry { background: radial-gradient(circle, #FF69B4 0%, #FF1493 100%); }

/* Control Button */
.control-btn {
    background: rgba(255, 255, 255, 0.05);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    padding: 12px 24px;
    color: #ffffff;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.3s ease;
}

.control-btn:hover {
    background: rgba(255, 255, 255, 0.1);
    transform: translateY(-2px);
}

.control-btn-primary {
    background: linear-gradient(135deg, #00ff88 0%, #00cc6a 100%);
    color: #000;
    border: none;
}

.control-btn-danger {
    background: linear-gradient(135deg, #ff4757 0%, #ff3344 100%);
    color: #fff;
    border: none;
}

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
        Industrial Automation Control System
    </div>
</div>
""", unsafe_allow_html=True)

# Fetch data
data = fetch_dashboard_data()

if data:
    stats = data.get("stats", {})
    inventory = data.get("inventory", [])
    hardware = data.get("hardware", [])
    logs = data.get("logs", [])
    energy = data.get("energy", {})
    
    # ========================================================================
    # Row 1: KPI Cards
    # ========================================================================
    
    st.markdown('<div class="section-title">System Overview</div>', unsafe_allow_html=True)
    
    kpi_cols = st.columns(4)
    
    with kpi_cols[0]:
        occupied = stats.get("occupied_slots", 0)
        total = stats.get("total_slots", 9)
        st.metric(
            label="Inventory",
            value=f"{occupied}/{total}",
            delta=f"{total - occupied} available"
        )
    
    with kpi_cols[1]:
        st.metric(
            label="Stored Cookies",
            value=stats.get("stored_cookies", 0),
            delta="Active batches"
        )
    
    with kpi_cols[2]:
        kwh = energy.get("total_kwh", 0)
        st.metric(
            label="Energy Usage",
            value=f"{kwh:.3f} kWh",
            delta="Last 24h"
        )
    
    with kpi_cols[3]:
        healthy = stats.get("system_healthy", False)
        status_text = "✓ Healthy" if healthy else "⚠ Alert"
        st.metric(
            label="System Health",
            value=status_text,
            delta=f"{stats.get('active_devices', 0)} devices online"
        )
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # ========================================================================
    # Row 2: Main View (Robot Position + Inventory Grid)
    # ========================================================================
    
    main_cols = st.columns([2, 1])
    
    # Left: Robot Position Monitor
    with main_cols[0]:
        st.markdown('<div class="section-title">Robot Position Monitor</div>', unsafe_allow_html=True)
        
        # Create scatter plot for robot positions
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
            
            # Color mapping for status
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
    
    # Right: Inventory Grid
    with main_cols[1]:
        st.markdown('<div class="section-title">Rack Grid</div>', unsafe_allow_html=True)
        
        # Create 3x3 grid
        grid_rows = [["A1", "A2", "A3"], ["B1", "B2", "B3"], ["C1", "C2", "C3"]]
        
        # Create inventory lookup
        inv_lookup = {s["slot_name"]: s for s in inventory}
        
        for row in grid_rows:
            cols = st.columns(3)
            for i, slot_name in enumerate(row):
                with cols[i]:
                    slot_data = inv_lookup.get(slot_name, {})
                    flavor = slot_data.get("cookie_flavor")
                    
                    # Determine slot styling
                    if flavor:
                        flavor_lower = flavor.lower()
                        slot_class = f"slot-{flavor_lower}"
                        cookie_class = f"cookie-{flavor_lower}"
                        cookie_html = f'<div class="cookie-indicator {cookie_class}"></div>'
                        flavor_text = flavor
                    else:
                        slot_class = "slot-empty"
                        cookie_html = '<div style="color: rgba(255,255,255,0.3); font-size: 12px;">Empty</div>'
                        flavor_text = ""
                    
                    st.markdown(f"""
                    <div class="slot-card {slot_class}">
                        <div class="slot-name">{slot_name}</div>
                        {cookie_html}
                        <div style="font-size: 10px; color: rgba(255,255,255,0.5); margin-top: 4px;">{flavor_text}</div>
                    </div>
                    """, unsafe_allow_html=True)
        
        # Legend
        st.markdown("""
        <div style="display: flex; gap: 16px; margin-top: 16px; justify-content: center;">
            <div style="display: flex; align-items: center; gap: 6px;">
                <div style="width: 12px; height: 12px; border-radius: 50%; background: #8B5A2B;"></div>
                <span style="color: rgba(255,255,255,0.5); font-size: 11px;">Choco</span>
            </div>
            <div style="display: flex; align-items: center; gap: 6px;">
                <div style="width: 12px; height: 12px; border-radius: 50%; background: #FFFACD;"></div>
                <span style="color: rgba(255,255,255,0.5); font-size: 11px;">Vanilla</span>
            </div>
            <div style="display: flex; align-items: center; gap: 6px;">
                <div style="width: 12px; height: 12px; border-radius: 50%; background: #FF69B4;"></div>
                <span style="color: rgba(255,255,255,0.5); font-size: 11px;">Strawberry</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # ========================================================================
    # Row 3: Control Deck + Hardware Status + Logs
    # ========================================================================
    
    bottom_cols = st.columns([1, 1, 1])
    
    # Control Deck
    with bottom_cols[0]:
        st.markdown('<div class="section-title">Control Deck</div>', unsafe_allow_html=True)
        
        # Flavor selection
        flavor = st.selectbox("Cookie Flavor", ["CHOCO", "VANILLA", "STRAWBERRY"], label_visibility="collapsed")
        
        ctrl_cols = st.columns(2)
        with ctrl_cols[0]:
            if st.button("🍪 Store Random", use_container_width=True):
                result = store_cookie(flavor)
                if result.get("success"):
                    st.success(f"Stored in {result.get('slot_name')}")
                else:
                    st.error(result.get("message"))
        
        with ctrl_cols[1]:
            slot_to_retrieve = st.selectbox(
                "Retrieve from",
                [s["slot_name"] for s in inventory if s.get("carrier_id")],
                label_visibility="collapsed"
            )
        
        if st.button("📤 Retrieve", use_container_width=True):
            if slot_to_retrieve:
                result = retrieve_cookie(slot_to_retrieve)
                if result.get("success"):
                    st.success(result.get("message"))
                else:
                    st.error(result.get("message"))
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        emg_cols = st.columns(2)
        with emg_cols[0]:
            if st.button("🔄 Reset", use_container_width=True):
                result = reset_system()
                st.info(result.get("message", "Reset initiated"))
        
        with emg_cols[1]:
            if st.button("🛑 E-STOP", use_container_width=True, type="primary"):
                result = emergency_stop()
                st.warning("Emergency stop activated!")
    
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
                    <div style="font-weight: 600; color: #fff;">{hw['device_id']}</div>
                    <div style="font-size: 11px; color: rgba(255,255,255,0.5);">
                        ({hw['current_x']:.0f}, {hw['current_y']:.0f})
                    </div>
                </div>
                <div style="
                    background: {status_color}20;
                    color: {status_color};
                    padding: 4px 12px;
                    border-radius: 20px;
                    font-size: 11px;
                    font-weight: 600;
                ">{status}</div>
            </div>
            """, unsafe_allow_html=True)
    
    # Recent Logs
    with bottom_cols[2]:
        st.markdown('<div class="section-title">Recent Activity</div>', unsafe_allow_html=True)
        
        for log in logs[:5]:
            level = log.get("level", "INFO")
            level_color = {
                "INFO": "#70a1ff",
                "WARNING": "#ffa502",
                "ERROR": "#ff4757",
                "CRITICAL": "#ff4757"
            }.get(level, "#70a1ff")
            
            timestamp = log.get("timestamp", "")
            if isinstance(timestamp, str):
                try:
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    time_str = dt.strftime("%H:%M:%S")
                except:
                    time_str = timestamp[:8]
            else:
                time_str = str(timestamp)[:8]
            
            st.markdown(f"""
            <div class="log-entry" style="border-left-color: {level_color};">
                <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                    <span style="color: {level_color}; font-weight: 600; font-size: 10px;">{level}</span>
                    <span style="color: rgba(255,255,255,0.3); font-size: 10px;">{time_str}</span>
                </div>
                <div>{log.get('message', '')[:50]}</div>
            </div>
            """, unsafe_allow_html=True)

else:
    st.error("Unable to connect to API. Make sure the FastAPI server is running.")
    st.info(f"Expected API URL: {API_URL}")

# Auto-refresh using Streamlit's native rerun
time.sleep(REFRESH_INTERVAL)
st.rerun()

# Footer
st.markdown("""
<div style="
    text-align: center;
    padding: 20px;
    color: rgba(255,255,255,0.3);
    font-size: 11px;
    margin-top: 40px;
">
    STF Digital Twin v2.0 • Industrial Apple Design • Powered by FastAPI + Streamlit
</div>
""", unsafe_allow_html=True)
