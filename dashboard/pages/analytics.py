"""
STF Digital Twin - Historical Analytics Page
Time-series visualization for telemetry data, energy consumption, and predictive maintenance.

Features:
- Real database integration (falls back to sample data if unavailable)
- Motor health degradation visualization
- Breakdown scenario detection (Day 12 Motor Failure, Day 25 Sensor Drift)
- Predictive maintenance alerts when health_score < 0.5
- Energy consumption analysis (V x A x Time)
"""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests
import os

# Page configuration
st.set_page_config(
    page_title="STF Analytics",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for Glassmorphism styling
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    .stApp {
        background: linear-gradient(135deg, #0a0f1a 0%, #1a1f2e 50%, #0d1117 100%);
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    
    .glass-card {
        background: rgba(255, 255, 255, 0.03);
        backdrop-filter: blur(20px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 16px;
        padding: 24px;
        margin-bottom: 20px;
    }
    
    .metric-card {
        background: rgba(0, 210, 190, 0.08);
        backdrop-filter: blur(12px);
        border: 1px solid rgba(0, 210, 190, 0.2);
        border-radius: 12px;
        padding: 20px;
        text-align: center;
    }
    
    .metric-value {
        font-size: 2.5rem;
        font-weight: 700;
        color: #00d2be;
        margin: 0;
    }
    
    .metric-label {
        font-size: 0.875rem;
        color: rgba(255, 255, 255, 0.6);
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-top: 8px;
    }
    
    .alert-critical {
        background: rgba(255, 107, 107, 0.15);
        border-left: 4px solid #ff6b6b;
        padding: 16px;
        border-radius: 8px;
        margin-bottom: 12px;
    }
    
    .alert-warning {
        background: rgba(255, 217, 61, 0.15);
        border-left: 4px solid #ffd93d;
        padding: 16px;
        border-radius: 8px;
        margin-bottom: 12px;
    }
    
    .alert-info {
        background: rgba(0, 210, 190, 0.15);
        border-left: 4px solid #00d2be;
        padding: 16px;
        border-radius: 8px;
        margin-bottom: 12px;
    }
    
    h1, h2, h3 { color: #ffffff !important; font-weight: 600; }
    
    .page-title {
        font-size: 2rem;
        background: linear-gradient(135deg, #00d2be 0%, #00a896 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 8px;
    }
    
    .page-subtitle {
        color: rgba(255, 255, 255, 0.5);
        font-size: 1rem;
        margin-bottom: 32px;
    }
    
    .breakdown-indicator {
        background: rgba(255, 107, 107, 0.2);
        border: 2px solid #ff6b6b;
        border-radius: 8px;
        padding: 12px 20px;
        margin: 8px 0;
        display: inline-block;
    }
</style>
""", unsafe_allow_html=True)

# API Configuration
API_URL = os.environ.get("STF_API_URL", "http://localhost:8000")

# Constants for breakdown scenarios
BREAKDOWN_DAY_MOTOR = 12
BREAKDOWN_DAY_SENSOR = 25


def fetch_api_data(endpoint: str, params: dict = None):
    """Fetch data from API with error handling."""
    try:
        response = requests.get(f"{API_URL}/{endpoint}", params=params, timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        st.sidebar.warning(f"API unavailable: Using sample data")
    return None


def fetch_telemetry_from_db(days: int) -> pd.DataFrame:
    """Fetch telemetry data from database via API."""
    data = fetch_api_data("telemetry/history", {"days": days})
    if data:
        return pd.DataFrame(data)
    return generate_sample_telemetry_data(days)


def fetch_energy_from_db(days: int) -> pd.DataFrame:
    """Fetch energy data from database via API."""
    data = fetch_api_data("energy/history", {"days": days})
    if data:
        return pd.DataFrame(data)
    return generate_sample_energy_data(days)


def fetch_alerts_from_db(days: int) -> pd.DataFrame:
    """Fetch alerts from database via API."""
    data = fetch_api_data("alerts", {"days": days})
    if data:
        return pd.DataFrame(data)
    return generate_sample_alerts(days)


def fetch_motor_health_from_db() -> pd.DataFrame:
    """Fetch motor health data from database via API."""
    data = fetch_api_data("motors/health")
    if data:
        return pd.DataFrame(data)
    return generate_sample_motor_health()


def generate_sample_telemetry_data(days: int = 30) -> pd.DataFrame:
    """Generate sample telemetry data with breakdown scenarios."""
    np.random.seed(42)
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    timestamps = pd.date_range(start=start_date, end=end_date, freq='1h')
    
    data = []
    for i, ts in enumerate(timestamps):
        day_num = (ts - start_date).days + 1
        hour = ts.hour
        
        # Activity pattern
        if 9 <= hour <= 17:
            activity = 1.0
        elif 6 <= hour <= 9 or 17 <= hour <= 21:
            activity = 0.6
        else:
            activity = 0.2
        
        # Motor health telemetry
        for motor_id in ["HBW_M1_X", "HBW_M2_Y", "CONV_M1", "VGR_M1_ARM"]:
            # Base health degradation
            base_health = 1.0 - (day_num * 0.001)
            
            # Inject motor failure on Day 12 for CONV_M1
            if motor_id == "CONV_M1" and day_num == BREAKDOWN_DAY_MOTOR:
                if 8 <= hour <= 12:
                    health = max(0.4, 0.9 - ((hour - 8) * 0.125))
                    current = 4.5 + np.random.uniform(-0.3, 0.3)
                else:
                    health = 0.4 + np.random.uniform(-0.02, 0.02)
                    current = 2.5 + np.random.uniform(-0.5, 0.5)
            elif motor_id == "CONV_M1" and day_num > BREAKDOWN_DAY_MOTOR:
                # Post-failure degraded state
                health = 0.4 + np.random.uniform(-0.05, 0.05)
                current = 2.0 + np.random.uniform(-0.3, 0.3)
            else:
                health = base_health + np.random.uniform(-0.02, 0.02)
                current = (0.8 + np.random.uniform(0, 0.7)) * activity
            
            data.append({
                'timestamp': ts,
                'device_id': motor_id,
                'metric_name': 'health_score',
                'metric_value': max(0.1, min(1.0, health)),
                'unit': '%'
            })
            data.append({
                'timestamp': ts,
                'device_id': motor_id,
                'metric_name': 'current_amps',
                'metric_value': current,
                'unit': 'A'
            })
        
        # Sensor telemetry - inject ghost readings on Day 25
        for sensor_id in ["CONV_L1_ENTRY", "CONV_L2_PROCESS", "CONV_L3_EXIT"]:
            trigger_count = int(np.random.poisson(3) * activity)
            
            # Inject sensor drift on Day 25
            if sensor_id == "CONV_L2_PROCESS" and day_num == BREAKDOWN_DAY_SENSOR:
                ghost_triggers = np.random.randint(5, 15)
                trigger_count += ghost_triggers
            
            data.append({
                'timestamp': ts,
                'device_id': sensor_id,
                'metric_name': 'trigger_count',
                'metric_value': trigger_count,
                'unit': 'count'
            })
    
    return pd.DataFrame(data)


def generate_sample_energy_data(days: int = 30) -> pd.DataFrame:
    """Generate sample energy data with breakdown scenarios."""
    np.random.seed(42)
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    timestamps = pd.date_range(start=start_date, end=end_date, freq='1h')
    
    data = []
    for ts in timestamps:
        day_num = (ts - start_date).days + 1
        hour = ts.hour
        
        # Activity pattern
        if 9 <= hour <= 17:
            activity = 1.0
        elif 6 <= hour <= 9 or 17 <= hour <= 21:
            activity = 0.6
        else:
            activity = 0.2
        
        for device in ['HBW', 'VGR', 'CONVEYOR']:
            device_factor = {'HBW': 1.0, 'VGR': 0.7, 'CONVEYOR': 0.5}[device]
            
            # Inject high energy on Day 12 for conveyor
            if device == 'CONVEYOR' and day_num == BREAKDOWN_DAY_MOTOR and 8 <= hour <= 12:
                current = 4.5 + np.random.uniform(-0.3, 0.3)
                joules = 24.0 * current * 3600  # V * A * seconds
            else:
                current = np.random.uniform(0.8, 1.5) * activity * device_factor
                joules = 24.0 * current * 3600 * np.random.uniform(0.3, 0.8)
            
            data.append({
                'timestamp': ts,
                'device_id': device,
                'joules': joules,
                'voltage': 24.0 + np.random.uniform(-0.5, 0.5),
                'current_amps': current,
                'power_watts': 24.0 * current
            })
    
    return pd.DataFrame(data)


def generate_sample_alerts(days: int = 30) -> pd.DataFrame:
    """Generate sample alerts including breakdown scenarios."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    alerts = []
    
    # Day 12: Motor failure alerts
    motor_failure_date = start_date + timedelta(days=BREAKDOWN_DAY_MOTOR - 1)
    alerts.extend([
        {
            'timestamp': motor_failure_date + timedelta(hours=8),
            'alert_type': 'OVERCURRENT',
            'severity': 'WARNING',
            'title': 'High Current Detected: CONV_M1',
            'message': 'Motor current at 4.5A exceeds normal range (1.5A)',
            'component_id': 'CONV_M1',
            'acknowledged': True
        },
        {
            'timestamp': motor_failure_date + timedelta(hours=10),
            'alert_type': 'HEALTH_DEGRADATION',
            'severity': 'CRITICAL',
            'title': 'Rapid Health Degradation: CONV_M1',
            'message': 'Motor health dropped to 40%. Immediate inspection required.',
            'component_id': 'CONV_M1',
            'acknowledged': True
        },
        {
            'timestamp': motor_failure_date + timedelta(hours=12),
            'alert_type': 'PREDICTIVE_MAINTENANCE',
            'severity': 'CRITICAL',
            'title': 'Predictive Maintenance Required: Conveyor Motor',
            'message': 'CONV_M1 health score below 50%. Schedule maintenance within 24 hours.',
            'component_id': 'CONV_M1',
            'acknowledged': False
        }
    ])
    
    # Day 25: Sensor drift alerts
    sensor_drift_date = start_date + timedelta(days=BREAKDOWN_DAY_SENSOR - 1)
    alerts.extend([
        {
            'timestamp': sensor_drift_date + timedelta(hours=14),
            'alert_type': 'SENSOR_DRIFT',
            'severity': 'WARNING',
            'title': 'Sensor Calibration Required: CONV_L2_PROCESS',
            'message': 'Multiple false triggers detected. Sensor may require recalibration.',
            'component_id': 'CONV_L2_PROCESS',
            'acknowledged': False
        }
    ])
    
    # Random maintenance alerts
    for day in range(1, days + 1):
        if np.random.random() < 0.1:  # 10% chance per day
            alert_date = start_date + timedelta(days=day - 1, hours=np.random.randint(8, 18))
            motor = np.random.choice(['HBW_M1_X', 'HBW_M2_Y', 'VGR_M1_ARM'])
            alerts.append({
                'timestamp': alert_date,
                'alert_type': 'PREDICTIVE_MAINTENANCE',
                'severity': 'INFO',
                'title': f'Scheduled Maintenance: {motor}',
                'message': f'Routine maintenance recommended for {motor}',
                'component_id': motor,
                'acknowledged': np.random.random() > 0.3
            })
    
    return pd.DataFrame(alerts)


def generate_sample_motor_health() -> pd.DataFrame:
    """Generate current motor health states."""
    motors = [
        {'component_id': 'HBW_M1_X', 'health_score': 0.92, 'current_amps': 1.2, 'runtime_hours': 720},
        {'component_id': 'HBW_M2_Y', 'health_score': 0.88, 'current_amps': 1.1, 'runtime_hours': 680},
        {'component_id': 'CONV_M1', 'health_score': 0.42, 'current_amps': 2.3, 'runtime_hours': 850},  # Degraded
        {'component_id': 'VGR_M1_ARM', 'health_score': 0.95, 'current_amps': 0.9, 'runtime_hours': 520},
        {'component_id': 'VGR_M2_GRIP', 'health_score': 0.91, 'current_amps': 0.5, 'runtime_hours': 480},
    ]
    return pd.DataFrame(motors)


def generate_sample_production_data(days: int = 30) -> pd.DataFrame:
    """Generate sample production throughput data."""
    np.random.seed(42)
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    dates = pd.date_range(start=start_date, end=end_date, freq='1D')
    
    data = []
    for date in dates:
        day_num = (date - start_date).days + 1
        day_factor = 1.0 if date.weekday() < 5 else 0.3
        
        # Reduced operations on breakdown days
        if day_num == BREAKDOWN_DAY_MOTOR:
            day_factor *= 0.5  # 50% reduction due to motor failure
        elif day_num == BREAKDOWN_DAY_SENSOR:
            day_factor *= 0.7  # 30% reduction due to sensor issues
        
        data.append({
            'date': date.date(),
            'store_operations': int(np.random.poisson(50) * day_factor),
            'retrieve_operations': int(np.random.poisson(45) * day_factor),
            'process_operations': int(np.random.poisson(40) * day_factor),
            'total_operations': int(np.random.poisson(135) * day_factor),
            'avg_cycle_time': np.random.uniform(15, 25) * (1.5 if day_num in [BREAKDOWN_DAY_MOTOR, BREAKDOWN_DAY_SENSOR] else 1.0),
            'uptime_percent': np.random.uniform(60, 75) if day_num == BREAKDOWN_DAY_MOTOR else (
                np.random.uniform(75, 85) if day_num == BREAKDOWN_DAY_SENSOR else np.random.uniform(92, 99.5)
            )
        })
    
    return pd.DataFrame(data)


# Sidebar
with st.sidebar:
    st.markdown("### 📊 Analytics Settings")
    st.markdown("---")
    
    # Date range selection
    st.markdown("**Date Range**")
    date_range = st.selectbox(
        "Select period",
        ["Last 7 Days", "Last 14 Days", "Last 30 Days", "Last 90 Days"],
        index=2
    )
    
    days_map = {
        "Last 7 Days": 7,
        "Last 14 Days": 14,
        "Last 30 Days": 30,
        "Last 90 Days": 90
    }
    days = days_map.get(date_range, 30)
    
    st.markdown("---")
    
    # Device filter
    st.markdown("**Device Filter**")
    devices = st.multiselect(
        "Select devices",
        ["HBW", "VGR", "CONVEYOR"],
        default=["HBW", "VGR", "CONVEYOR"]
    )
    
    st.markdown("---")
    
    # Show breakdown indicators
    st.markdown("**Breakdown Scenarios**")
    show_breakdowns = st.checkbox("Highlight breakdown events", value=True)
    
    st.markdown("---")
    
    # Refresh button
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.rerun()
    
    st.markdown("---")
    
    # Navigation
    st.markdown("**Navigation**")
    if st.button("← Back to Dashboard", use_container_width=True):
        st.switch_page("app.py")


# Main content
st.markdown('<h1 class="page-title">Historical Analytics</h1>', unsafe_allow_html=True)
st.markdown('<p class="page-subtitle">Time-series visualization, breakdown analysis, and predictive maintenance</p>', unsafe_allow_html=True)

# Load data
telemetry_df = fetch_telemetry_from_db(days)
energy_df = fetch_energy_from_db(days)
production_df = generate_sample_production_data(days)
alerts_df = fetch_alerts_from_db(days)
motor_health_df = fetch_motor_health_from_db()

# Convert timestamp columns
if 'timestamp' in telemetry_df.columns:
    telemetry_df['timestamp'] = pd.to_datetime(telemetry_df['timestamp'])
if 'timestamp' in energy_df.columns:
    energy_df['timestamp'] = pd.to_datetime(energy_df['timestamp'])
if 'timestamp' in alerts_df.columns:
    alerts_df['timestamp'] = pd.to_datetime(alerts_df['timestamp'])

# Filter by devices
if 'device_id' in energy_df.columns:
    energy_df = energy_df[energy_df['device_id'].isin(devices)]

# Breakdown Scenario Summary
if show_breakdowns:
    st.markdown("### ⚠️ Breakdown Scenario Summary")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        <div class="alert-critical">
            <strong>Day 12: Motor Failure (CONV_M1)</strong><br>
            <span style="color: rgba(255,255,255,0.7);">
            Current spike to 4.5A (normal: 1.5A)<br>
            Health degradation: 90% → 40%<br>
            Production impact: -50%
            </span>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("""
        <div class="alert-warning">
            <strong>Day 25: Sensor Drift (CONV_L2_PROCESS)</strong><br>
            <span style="color: rgba(255,255,255,0.7);">
            Ghost triggers: 5-15 per hour (normal: 0-3)<br>
            False positives causing workflow interruptions<br>
            Production impact: -30%
            </span>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)

# KPI Summary Cards
st.markdown("### 📈 Key Performance Indicators")

col1, col2, col3, col4 = st.columns(4)

with col1:
    total_energy = energy_df['joules'].sum() / 1000000 if 'joules' in energy_df.columns else 0
    st.markdown(f"""
    <div class="metric-card">
        <p class="metric-value">{total_energy:,.1f}</p>
        <p class="metric-label">Total Energy (MJ)</p>
    </div>
    """, unsafe_allow_html=True)

with col2:
    total_operations = production_df['total_operations'].sum() if 'total_operations' in production_df.columns else 0
    st.markdown(f"""
    <div class="metric-card">
        <p class="metric-value">{total_operations:,}</p>
        <p class="metric-label">Total Operations</p>
    </div>
    """, unsafe_allow_html=True)

with col3:
    avg_uptime = production_df['uptime_percent'].mean() if 'uptime_percent' in production_df.columns else 0
    st.markdown(f"""
    <div class="metric-card">
        <p class="metric-value">{avg_uptime:.1f}%</p>
        <p class="metric-label">Avg Uptime</p>
    </div>
    """, unsafe_allow_html=True)

with col4:
    critical_alerts = len(alerts_df[alerts_df['severity'] == 'CRITICAL']) if 'severity' in alerts_df.columns else 0
    st.markdown(f"""
    <div class="metric-card">
        <p class="metric-value" style="color: {'#ff6b6b' if critical_alerts > 0 else '#00d2be'};">{critical_alerts}</p>
        <p class="metric-label">Critical Alerts</p>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# Tabs for different analytics views
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🔧 Motor Health", 
    "⚡ Energy Analysis", 
    "🏭 Production Metrics", 
    "🚨 Alerts & Events",
    "🔮 Predictive Insights"
])

with tab1:
    st.markdown("### Motor Health Degradation Over Time")
    
    # Filter motor health telemetry
    health_df = telemetry_df[telemetry_df['metric_name'] == 'health_score'].copy()
    
    if not health_df.empty:
        # Health score over time
        fig_health = px.line(
            health_df,
            x='timestamp',
            y='metric_value',
            color='device_id',
            title='Motor Health Score Over Time',
            labels={'metric_value': 'Health Score', 'timestamp': 'Date'},
            color_discrete_sequence=['#00d2be', '#ff6b6b', '#ffd93d', '#9b59b6', '#3498db']
        )
        
        # Add threshold line at 0.5
        fig_health.add_hline(
            y=0.5, 
            line_dash="dash", 
            line_color="#ff6b6b",
            annotation_text="Maintenance Threshold (50%)",
            annotation_position="top right"
        )
        
        # Add breakdown markers
        if show_breakdowns:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            breakdown_date = start_date + timedelta(days=BREAKDOWN_DAY_MOTOR - 1)
            
            fig_health.add_vline(
                x=breakdown_date.isoformat(),
                line_dash="dot",
                line_color="#ff6b6b",
                annotation_text="Motor Failure",
                annotation_position="top"
            )
        
        fig_health.update_layout(
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            font_color='rgba(255,255,255,0.8)',
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            xaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
            yaxis=dict(gridcolor='rgba(255,255,255,0.05)', range=[0, 1.1])
        )
        st.plotly_chart(fig_health, use_container_width=True)
    
    # Current motor health status
    st.markdown("#### Current Motor Health Status")
    
    cols = st.columns(len(motor_health_df))
    for i, (_, motor) in enumerate(motor_health_df.iterrows()):
        with cols[i % len(cols)]:
            health = motor['health_score']
            color = '#00d2be' if health >= 0.8 else ('#ffd93d' if health >= 0.5 else '#ff6b6b')
            status = 'Healthy' if health >= 0.8 else ('Warning' if health >= 0.5 else 'Critical')
            
            st.markdown(f"""
            <div style="background: rgba(255,255,255,0.03); border-radius: 12px; padding: 16px; border-left: 4px solid {color};">
                <div style="color: rgba(255,255,255,0.6); font-size: 0.75rem; text-transform: uppercase;">{motor['component_id']}</div>
                <div style="color: {color}; font-size: 2rem; font-weight: 700;">{health*100:.0f}%</div>
                <div style="color: rgba(255,255,255,0.5); font-size: 0.875rem;">
                    {motor['current_amps']:.1f}A | {motor['runtime_hours']:.0f}h runtime
                </div>
                <div style="background: rgba(255,255,255,0.1); border-radius: 4px; height: 6px; margin-top: 8px;">
                    <div style="background: {color}; width: {health*100}%; height: 100%; border-radius: 4px;"></div>
                </div>
            </div>
            """, unsafe_allow_html=True)

with tab2:
    st.markdown("### Energy Consumption Analysis")
    
    # Energy over time
    if 'timestamp' in energy_df.columns:
        energy_hourly = energy_df.groupby([pd.Grouper(key='timestamp', freq='1D'), 'device_id'])['joules'].sum().reset_index()
        energy_hourly['joules_kj'] = energy_hourly['joules'] / 1000
        
        fig_energy = px.area(
            energy_hourly,
            x='timestamp',
            y='joules_kj',
            color='device_id',
            title='Daily Energy Consumption by Device',
            labels={'joules_kj': 'Energy (kJ)', 'timestamp': 'Date'},
            color_discrete_map={'HBW': '#00d2be', 'VGR': '#ff6b6b', 'CONVEYOR': '#ffd93d'}
        )
        
        # Add breakdown marker
        if show_breakdowns:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            breakdown_date = start_date + timedelta(days=BREAKDOWN_DAY_MOTOR - 1)
            
            fig_energy.add_vline(
                x=breakdown_date.isoformat(),
                line_dash="dot",
                line_color="#ff6b6b",
                annotation_text="Motor Failure (High Energy)",
                annotation_position="top"
            )
        
        fig_energy.update_layout(
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            font_color='rgba(255,255,255,0.8)',
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            xaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
            yaxis=dict(gridcolor='rgba(255,255,255,0.05)')
        )
        st.plotly_chart(fig_energy, use_container_width=True)
    
    # Energy distribution
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Energy Distribution by Device")
        if 'device_id' in energy_df.columns:
            energy_by_device = energy_df.groupby('device_id')['joules'].sum().reset_index()
            energy_by_device['joules_mj'] = energy_by_device['joules'] / 1000000
            
            fig_pie = px.pie(
                energy_by_device,
                values='joules_mj',
                names='device_id',
                color='device_id',
                color_discrete_map={'HBW': '#00d2be', 'VGR': '#ff6b6b', 'CONVEYOR': '#ffd93d'},
                hole=0.4
            )
            fig_pie.update_layout(
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
                font_color='rgba(255,255,255,0.8)'
            )
            st.plotly_chart(fig_pie, use_container_width=True)
    
    with col2:
        st.markdown("#### Current Draw Analysis")
        if 'current_amps' in energy_df.columns and 'timestamp' in energy_df.columns:
            current_df = energy_df.groupby([pd.Grouper(key='timestamp', freq='1D'), 'device_id'])['current_amps'].mean().reset_index()
            
            fig_current = px.line(
                current_df,
                x='timestamp',
                y='current_amps',
                color='device_id',
                title='Average Current Draw Over Time',
                labels={'current_amps': 'Current (A)', 'timestamp': 'Date'},
                color_discrete_map={'HBW': '#00d2be', 'VGR': '#ff6b6b', 'CONVEYOR': '#ffd93d'}
            )
            fig_current.update_layout(
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
                font_color='rgba(255,255,255,0.8)',
                xaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
                yaxis=dict(gridcolor='rgba(255,255,255,0.05)')
            )
            st.plotly_chart(fig_current, use_container_width=True)

with tab3:
    st.markdown("### Production Throughput")
    
    # Daily operations chart
    fig_ops = make_subplots(specs=[[{"secondary_y": True}]])
    
    fig_ops.add_trace(
        go.Bar(
            x=production_df['date'],
            y=production_df['store_operations'],
            name='Store',
            marker_color='#00d2be'
        ),
        secondary_y=False
    )
    
    fig_ops.add_trace(
        go.Bar(
            x=production_df['date'],
            y=production_df['retrieve_operations'],
            name='Retrieve',
            marker_color='#ff6b6b'
        ),
        secondary_y=False
    )
    
    fig_ops.add_trace(
        go.Bar(
            x=production_df['date'],
            y=production_df['process_operations'],
            name='Process',
            marker_color='#ffd93d'
        ),
        secondary_y=False
    )
    
    fig_ops.add_trace(
        go.Scatter(
            x=production_df['date'],
            y=production_df['uptime_percent'],
            name='Uptime %',
            line=dict(color='#9b59b6', width=3),
            mode='lines+markers'
        ),
        secondary_y=True
    )
    
    fig_ops.update_layout(
        title='Daily Operations & Uptime',
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font_color='rgba(255,255,255,0.8)',
        barmode='group',
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
        yaxis=dict(gridcolor='rgba(255,255,255,0.05)', title='Operations'),
        yaxis2=dict(gridcolor='rgba(255,255,255,0.05)', title='Uptime %', range=[0, 100])
    )
    
    # Add breakdown markers
    if show_breakdowns:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        motor_failure_date = (start_date + timedelta(days=BREAKDOWN_DAY_MOTOR - 1)).date()
        sensor_drift_date = (start_date + timedelta(days=BREAKDOWN_DAY_SENSOR - 1)).date()
        
        fig_ops.add_vline(x=motor_failure_date, line_dash="dot", line_color="#ff6b6b")
        fig_ops.add_vline(x=sensor_drift_date, line_dash="dot", line_color="#ffd93d")
    
    st.plotly_chart(fig_ops, use_container_width=True)

with tab4:
    st.markdown("### Alerts & Events Timeline")
    
    if not alerts_df.empty:
        # Sort by timestamp descending
        alerts_df = alerts_df.sort_values('timestamp', ascending=False)
        
        # Display alerts
        for _, alert in alerts_df.head(20).iterrows():
            severity = alert.get('severity', 'INFO')
            alert_class = {
                'CRITICAL': 'alert-critical',
                'WARNING': 'alert-warning',
                'INFO': 'alert-info'
            }.get(severity, 'alert-info')
            
            timestamp_str = alert['timestamp'].strftime('%Y-%m-%d %H:%M') if pd.notna(alert['timestamp']) else 'N/A'
            ack_badge = '<span style="background: #00d2be; color: #0a0f1a; padding: 2px 8px; border-radius: 4px; font-size: 0.7rem; margin-left: 8px;">ACK</span>' if alert.get('acknowledged', False) else ''
            
            st.markdown(f"""
            <div class="{alert_class}">
                <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                    <div>
                        <strong>{alert.get('title', 'Alert')}</strong>{ack_badge}<br>
                        <span style="color: rgba(255,255,255,0.7);">{alert.get('message', '')}</span>
                    </div>
                    <div style="text-align: right; color: rgba(255,255,255,0.5); font-size: 0.8rem;">
                        {timestamp_str}<br>
                        {alert.get('component_id', '')}
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No alerts found for the selected period.")

with tab5:
    st.markdown("### Predictive Maintenance Insights")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Equipment Health Forecast")
        
        # Simple linear regression forecast for motor health
        health_forecast = []
        for _, motor in motor_health_df.iterrows():
            current_health = motor['health_score']
            # Assume 0.1% degradation per day
            daily_degradation = 0.001
            
            for days_ahead in [7, 14, 30]:
                predicted_health = max(0, current_health - (daily_degradation * days_ahead))
                health_forecast.append({
                    'component_id': motor['component_id'],
                    'days_ahead': days_ahead,
                    'predicted_health': predicted_health
                })
        
        forecast_df = pd.DataFrame(health_forecast)
        
        fig_forecast = px.line(
            forecast_df,
            x='days_ahead',
            y='predicted_health',
            color='component_id',
            title='Predicted Health Score (Next 30 Days)',
            labels={'days_ahead': 'Days Ahead', 'predicted_health': 'Predicted Health'},
            markers=True
        )
        
        fig_forecast.add_hline(y=0.5, line_dash="dash", line_color="#ff6b6b", annotation_text="Maintenance Threshold")
        
        fig_forecast.update_layout(
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            font_color='rgba(255,255,255,0.8)',
            xaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
            yaxis=dict(gridcolor='rgba(255,255,255,0.05)', range=[0, 1.1])
        )
        st.plotly_chart(fig_forecast, use_container_width=True)
    
    with col2:
        st.markdown("#### Maintenance Recommendations")
        
        # Generate recommendations based on health scores
        for _, motor in motor_health_df.iterrows():
            health = motor['health_score']
            component = motor['component_id']
            
            if health < 0.5:
                priority = 'CRITICAL'
                color = '#ff6b6b'
                days_to_failure = int((health - 0.2) / 0.001)  # Rough estimate
                message = f"Immediate maintenance required. Estimated {max(0, days_to_failure)} days to failure."
            elif health < 0.7:
                priority = 'HIGH'
                color = '#ffd93d'
                days_to_failure = int((health - 0.5) / 0.001)
                message = f"Schedule maintenance within {days_to_failure} days."
            elif health < 0.85:
                priority = 'MEDIUM'
                color = '#00d2be'
                days_to_failure = int((health - 0.7) / 0.001)
                message = f"Plan maintenance in next {days_to_failure} days."
            else:
                priority = 'LOW'
                color = 'rgba(255,255,255,0.3)'
                message = "No immediate action required."
            
            st.markdown(f"""
            <div style="background: rgba(255,255,255,0.03); border-radius: 8px; padding: 12px; margin-bottom: 8px; border-left: 4px solid {color};">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <span style="color: rgba(255,255,255,0.8); font-weight: 500;">{component}</span>
                        <span style="background: {color}; color: #0a0f1a; padding: 2px 8px; border-radius: 4px; font-size: 0.7rem; margin-left: 8px;">{priority}</span>
                    </div>
                    <span style="color: {color}; font-weight: 700;">{health*100:.0f}%</span>
                </div>
                <div style="color: rgba(255,255,255,0.5); font-size: 0.8rem; margin-top: 4px;">{message}</div>
            </div>
            """, unsafe_allow_html=True)

# Export section
st.markdown("---")
st.markdown("### 📥 Export Data")

col1, col2, col3 = st.columns(3)

with col1:
    if st.button("📊 Export Energy Data", use_container_width=True):
        csv = energy_df.to_csv(index=False)
        st.download_button(
            label="Download CSV",
            data=csv,
            file_name=f"stf_energy_data_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )

with col2:
    if st.button("🏭 Export Production Data", use_container_width=True):
        csv = production_df.to_csv(index=False)
        st.download_button(
            label="Download CSV",
            data=csv,
            file_name=f"stf_production_data_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )

with col3:
    if st.button("🚨 Export Alerts", use_container_width=True):
        csv = alerts_df.to_csv(index=False)
        st.download_button(
            label="Download CSV",
            data=csv,
            file_name=f"stf_alerts_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )

# Footer
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: rgba(255,255,255,0.4); font-size: 0.875rem;">
    STF Digital Twin Analytics v3.0 • Breakdown scenarios: Day 12 (Motor), Day 25 (Sensor) • 
    <a href="/" style="color: #00d2be;">Back to Dashboard</a>
</div>
""", unsafe_allow_html=True)
