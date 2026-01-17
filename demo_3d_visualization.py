"""
STF Digital Twin - Standalone 3D Visualization Demo
This demo showcases the 3D warehouse visualization capabilities
Run with: streamlit run demo_3d_visualization.py
"""

import streamlit as st
import plotly.graph_objects as go
import numpy as np
import time
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

# Page Configuration
st.set_page_config(
    page_title="3D Warehouse Demo",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================================
# GLASSMORPHISM CSS
# ============================================================================

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

.stApp {
    background: linear-gradient(135deg, #0a0a1a 0%, #1a1a2e 50%, #0f0f23 100%);
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}

#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}

.glass-card {
    background: rgba(255, 255, 255, 0.03);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 24px;
    padding: 24px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
    margin-bottom: 20px;
}

.header-title {
    font-size: 32px;
    font-weight: 700;
    color: #ffffff;
    margin-bottom: 8px;
    background: linear-gradient(135deg, #00ff88 0%, #00cc6a 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.header-subtitle {
    font-size: 14px;
    color: rgba(255, 255, 255, 0.5);
}

.status-badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
}

.status-active {
    background: linear-gradient(135deg, #00ff88 0%, #00cc6a 100%);
    color: #000;
}

.status-idle {
    background: rgba(112, 161, 255, 0.2);
    color: #70a1ff;
}

.metric-card {
    background: rgba(255, 255, 255, 0.05);
    border-radius: 16px;
    padding: 16px;
    text-align: center;
    margin-bottom: 12px;
}

.metric-value {
    font-size: 28px;
    font-weight: 600;
    color: #00ff88;
}

.metric-label {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.5);
    text-transform: uppercase;
    letter-spacing: 1px;
}

.slot-indicator {
    display: inline-block;
    width: 40px;
    height: 40px;
    border-radius: 8px;
    margin: 4px;
    text-align: center;
    line-height: 40px;
    font-weight: 600;
    font-size: 12px;
}

.slot-empty { background: rgba(255,255,255,0.05); color: rgba(255,255,255,0.3); }
.slot-raw { background: rgba(255,215,0,0.3); color: #FFD700; }
.slot-baked { background: rgba(255,140,0,0.3); color: #FF8C00; }
.slot-packaged { background: rgba(50,205,50,0.3); color: #32CD32; }

.control-btn {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    padding: 12px 24px;
    color: white;
    cursor: pointer;
    transition: all 0.3s ease;
}

.control-btn:hover {
    background: rgba(255, 255, 255, 0.1);
    transform: translateY(-2px);
}

.animation-panel {
    background: rgba(0, 255, 136, 0.05);
    border: 1px solid rgba(0, 255, 136, 0.2);
    border-radius: 12px;
    padding: 16px;
    margin-top: 16px;
}
</style>
""", unsafe_allow_html=True)


# ============================================================================
# SIMULATION STATE
# ============================================================================

class RobotState(Enum):
    IDLE = "IDLE"
    MOVING_X = "MOVING_X"
    MOVING_Y = "MOVING_Y"
    EXTENDING = "EXTENDING"
    RETRACTING = "RETRACTING"
    GRIPPING = "GRIPPING"


@dataclass
class SimulationState:
    """Holds the current simulation state"""
    robot_x: float = 150.0
    robot_y: float = 200.0
    target_x: float = 150.0
    target_y: float = 200.0
    gripper_extended: bool = False
    gripper_holding: bool = False
    belt_position: float = 0.0
    belt_running: bool = False
    robot_state: RobotState = RobotState.IDLE
    
    # Inventory (slot_name -> cookie_status)
    inventory: Dict[str, str] = None
    
    def __post_init__(self):
        if self.inventory is None:
            self.inventory = {
                'A1': 'RAW_DOUGH', 'A2': 'BAKED', 'A3': 'PACKAGED',
                'B1': 'RAW_DOUGH', 'B2': '', 'B3': 'BAKED',
                'C1': '', 'C2': 'RAW_DOUGH', 'C3': '',
            }


# Initialize session state
if 'sim_state' not in st.session_state:
    st.session_state.sim_state = SimulationState()

if 'animation_running' not in st.session_state:
    st.session_state.animation_running = False


# ============================================================================
# 3D GEOMETRY BUILDER
# ============================================================================

def create_box_mesh(center: Tuple[float, float, float], 
                    size: Tuple[float, float, float]) -> Dict:
    """Create a 3D box mesh vertices and faces"""
    cx, cy, cz = center
    sx, sy, sz = size
    
    vertices = np.array([
        [cx - sx/2, cy - sy/2, cz - sz/2],
        [cx + sx/2, cy - sy/2, cz - sz/2],
        [cx + sx/2, cy + sy/2, cz - sz/2],
        [cx - sx/2, cy + sy/2, cz - sz/2],
        [cx - sx/2, cy - sy/2, cz + sz/2],
        [cx + sx/2, cy - sy/2, cz + sz/2],
        [cx + sx/2, cy + sy/2, cz + sz/2],
        [cx - sx/2, cy + sy/2, cz + sz/2],
    ])
    
    i = [0, 0, 4, 4, 0, 0, 1, 1, 0, 0, 3, 3]
    j = [1, 2, 5, 6, 1, 4, 2, 5, 3, 4, 2, 6]
    k = [2, 3, 6, 7, 4, 5, 5, 6, 4, 7, 6, 7]
    
    return {'x': vertices[:, 0], 'y': vertices[:, 1], 'z': vertices[:, 2], 'i': i, 'j': j, 'k': k}


def create_warehouse_figure(state: SimulationState) -> go.Figure:
    """Create the complete 3D warehouse visualization"""
    
    fig = go.Figure()
    
    # Dimensions
    rack_width = 300
    rack_height = 400
    rack_depth = 200
    slot_size = 80
    
    # Color mapping for inventory
    status_colors = {
        '': '#1a1a2e',
        'RAW_DOUGH': '#FFD700',
        'BAKED': '#FF8C00',
        'PACKAGED': '#32CD32',
    }
    
    # Floor
    floor = create_box_mesh((rack_width/2 + 100, -5, rack_depth/2), (600, 10, 400))
    fig.add_trace(go.Mesh3d(
        x=floor['x'], y=floor['y'], z=floor['z'],
        i=floor['i'], j=floor['j'], k=floor['k'],
        color='#0a0a15', opacity=0.5, hoverinfo='skip'
    ))
    
    # Rack vertical posts
    for px, pz in [(0, 0), (rack_width, 0), (0, rack_depth), (rack_width, rack_depth)]:
        post = create_box_mesh((px, rack_height/2, pz), (10, rack_height, 10))
        fig.add_trace(go.Mesh3d(
            x=post['x'], y=post['y'], z=post['z'],
            i=post['i'], j=post['j'], k=post['k'],
            color='#2a2a3a', opacity=0.9, name='Rack Post', hoverinfo='name'
        ))
    
    # Rack shelves
    for row in range(4):
        y = row * (rack_height / 3)
        shelf = create_box_mesh((rack_width/2, y, rack_depth/2), (rack_width + 20, 5, rack_depth + 20))
        fig.add_trace(go.Mesh3d(
            x=shelf['x'], y=shelf['y'], z=shelf['z'],
            i=shelf['i'], j=shelf['j'], k=shelf['k'],
            color='#1a1a2e', opacity=0.8, name=f'Shelf {row}', hoverinfo='name'
        ))
    
    # Storage slots with inventory
    slot_names = [['A1', 'A2', 'A3'], ['B1', 'B2', 'B3'], ['C1', 'C2', 'C3']]
    for row in range(3):
        for col in range(3):
            x = col * (rack_width / 3) + slot_size/2 + 10
            y = row * (rack_height / 3) + slot_size/2 + 10
            z = rack_depth / 2
            
            slot_name = slot_names[row][col]
            cookie_status = state.inventory.get(slot_name, '')
            color = status_colors.get(cookie_status, '#1a1a2e')
            
            slot = create_box_mesh((x, y, z), (slot_size - 10, slot_size - 10, slot_size - 10))
            fig.add_trace(go.Mesh3d(
                x=slot['x'], y=slot['y'], z=slot['z'],
                i=slot['i'], j=slot['j'], k=slot['k'],
                color=color, opacity=0.85,
                name=f'{slot_name}: {cookie_status or "Empty"}',
                hoverinfo='name'
            ))
    
    # Robot carriage
    carriage = create_box_mesh((state.robot_x, state.robot_y, -50), (60, 80, 40))
    fig.add_trace(go.Mesh3d(
        x=carriage['x'], y=carriage['y'], z=carriage['z'],
        i=carriage['i'], j=carriage['j'], k=carriage['k'],
        color='#e74c3c', opacity=1.0, name='Robot Carriage', hoverinfo='name'
    ))
    
    # Telescopic arm
    arm_length = 110 if state.gripper_extended else 60
    arm = create_box_mesh((state.robot_x, state.robot_y, -50 + arm_length/2 + 20), (30, 30, arm_length))
    fig.add_trace(go.Mesh3d(
        x=arm['x'], y=arm['y'], z=arm['z'],
        i=arm['i'], j=arm['j'], k=arm['k'],
        color='#c0392b', opacity=1.0, name='Telescopic Arm', hoverinfo='name'
    ))
    
    # Gripper
    gripper_z = -50 + arm_length + 30
    gripper_color = '#27ae60' if state.gripper_holding else '#f39c12'
    gripper = create_box_mesh((state.robot_x, state.robot_y, gripper_z), (50, 20, 20))
    fig.add_trace(go.Mesh3d(
        x=gripper['x'], y=gripper['y'], z=gripper['z'],
        i=gripper['i'], j=gripper['j'], k=gripper['k'],
        color=gripper_color, opacity=1.0,
        name=f'Gripper {"(Holding)" if state.gripper_holding else ""}',
        hoverinfo='name'
    ))
    
    # Conveyor belt
    belt_base = create_box_mesh((rack_width + 150, 50, rack_depth/2), (200, 20, 80))
    fig.add_trace(go.Mesh3d(
        x=belt_base['x'], y=belt_base['y'], z=belt_base['z'],
        i=belt_base['i'], j=belt_base['j'], k=belt_base['k'],
        color='#2c3e50', opacity=0.9, name='Conveyor Base', hoverinfo='name'
    ))
    
    # Belt item (moving)
    belt_x = rack_width + 50 + (state.belt_position / 1000) * 200
    belt_item = create_box_mesh((belt_x, 65, rack_depth/2), (30, 10, 60))
    fig.add_trace(go.Mesh3d(
        x=belt_item['x'], y=belt_item['y'], z=belt_item['z'],
        i=belt_item['i'], j=belt_item['j'], k=belt_item['k'],
        color='#00ff88' if state.belt_running else '#555555', opacity=0.9,
        name=f'Belt Position: {state.belt_position:.0f}mm',
        hoverinfo='name'
    ))
    
    # Sensors on conveyor
    for i, (sx, name) in enumerate([
        (rack_width + 60, 'L1 Entry'),
        (rack_width + 110, 'L2 Process'),
        (rack_width + 170, 'L3 Exit'),
        (rack_width + 230, 'L4 Overflow'),
    ]):
        # Check if sensor is triggered
        sensor_triggered = (
            (i == 0 and 0 <= state.belt_position <= 100) or
            (i == 1 and 300 <= state.belt_position <= 400) or
            (i == 2 and 600 <= state.belt_position <= 700) or
            (i == 3 and 900 <= state.belt_position <= 1000)
        )
        sensor_color = '#00ff88' if sensor_triggered else '#3498db'
        
        sensor = create_box_mesh((sx, 80, rack_depth/2 + 50), (10, 15, 10))
        fig.add_trace(go.Mesh3d(
            x=sensor['x'], y=sensor['y'], z=sensor['z'],
            i=sensor['i'], j=sensor['j'], k=sensor['k'],
            color=sensor_color, opacity=0.8, name=name, hoverinfo='name'
        ))
    
    # Guide rails
    h_rail = create_box_mesh((rack_width/2, -2, -80), (rack_width + 50, 8, 20))
    fig.add_trace(go.Mesh3d(
        x=h_rail['x'], y=h_rail['y'], z=h_rail['z'],
        i=h_rail['i'], j=h_rail['j'], k=h_rail['k'],
        color='#34495e', opacity=0.9, name='Horizontal Rail', hoverinfo='name'
    ))
    
    v_rail = create_box_mesh((-30, rack_height/2, -80), (20, rack_height + 50, 20))
    fig.add_trace(go.Mesh3d(
        x=v_rail['x'], y=v_rail['y'], z=v_rail['z'],
        i=v_rail['i'], j=v_rail['j'], k=v_rail['k'],
        color='#34495e', opacity=0.9, name='Vertical Rail', hoverinfo='name'
    ))
    
    # Layout configuration
    fig.update_layout(
        scene=dict(
            xaxis=dict(title='X (mm)', backgroundcolor='rgba(10,10,26,0)', gridcolor='rgba(255,255,255,0.1)'),
            yaxis=dict(title='Y (mm)', backgroundcolor='rgba(10,10,26,0)', gridcolor='rgba(255,255,255,0.1)'),
            zaxis=dict(title='Z (mm)', backgroundcolor='rgba(10,10,26,0)', gridcolor='rgba(255,255,255,0.1)'),
            camera=dict(eye=dict(x=1.5, y=1.5, z=1.2)),
            aspectmode='data',
        ),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=False,
        height=650,
    )
    
    return fig


# ============================================================================
# ANIMATION FUNCTIONS
# ============================================================================

def run_demo_sequence():
    """Run a demo sequence showing robot operations"""
    state = st.session_state.sim_state
    
    # Sequence: Move to A1, extend gripper, retract, move to conveyor
    sequences = [
        # Move to slot A1
        {'target_x': 50, 'target_y': 50, 'steps': 20},
        # Extend gripper
        {'gripper_extended': True, 'steps': 10},
        # Grip item
        {'gripper_holding': True, 'steps': 5},
        # Retract
        {'gripper_extended': False, 'steps': 10},
        # Move to conveyor
        {'target_x': 250, 'target_y': 50, 'steps': 20},
        # Extend and release
        {'gripper_extended': True, 'steps': 10},
        {'gripper_holding': False, 'steps': 5},
        {'gripper_extended': False, 'steps': 10},
        # Return home
        {'target_x': 150, 'target_y': 200, 'steps': 20},
    ]
    
    return sequences


# ============================================================================
# MAIN APPLICATION
# ============================================================================

def main():
    state = st.session_state.sim_state
    
    # Header
    st.markdown("""
    <div class="glass-card">
        <div class="header-title">🏭 High-Bay Warehouse 3D Demo</div>
        <div class="header-subtitle">Interactive 3D visualization of the STF Digital Twin system</div>
    </div>
    """, unsafe_allow_html=True)
    
    # Sidebar controls
    with st.sidebar:
        st.markdown("## 🎮 Controls")
        
        st.markdown("### Robot Position")
        new_x = st.slider("X (Horizontal)", 0, 300, int(state.robot_x), 10)
        new_y = st.slider("Y (Vertical)", 0, 400, int(state.robot_y), 10)
        
        if new_x != state.robot_x or new_y != state.robot_y:
            state.robot_x = new_x
            state.robot_y = new_y
        
        st.markdown("### Gripper")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔽 Extend"):
                state.gripper_extended = True
        with col2:
            if st.button("🔼 Retract"):
                state.gripper_extended = False
        
        grip_col1, grip_col2 = st.columns(2)
        with grip_col1:
            if st.button("✊ Grip"):
                state.gripper_holding = True
        with grip_col2:
            if st.button("🖐️ Release"):
                state.gripper_holding = False
        
        st.markdown("---")
        st.markdown("### Conveyor Belt")
        state.belt_position = st.slider("Belt Position (mm)", 0, 1000, int(state.belt_position), 50)
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("▶️ Start"):
                state.belt_running = True
        with col2:
            if st.button("⏹️ Stop"):
                state.belt_running = False
        
        st.markdown("---")
        st.markdown("### Quick Actions")
        
        if st.button("🏠 Home Position"):
            state.robot_x = 150
            state.robot_y = 200
            state.gripper_extended = False
            state.gripper_holding = False
        
        if st.button("📦 Go to A1"):
            state.robot_x = 50
            state.robot_y = 50
        
        if st.button("📦 Go to B2"):
            state.robot_x = 150
            state.robot_y = 180
        
        if st.button("🔄 Reset All"):
            st.session_state.sim_state = SimulationState()
            st.rerun()
    
    # Main content
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # 3D Visualization
        fig = create_warehouse_figure(state)
        st.plotly_chart(fig, use_container_width=True, config={
            'displayModeBar': True,
            'modeBarButtonsToRemove': ['lasso2d', 'select2d'],
        })
    
    with col2:
        # Status panel
        st.markdown("""
        <div class="glass-card">
            <h4 style="color: white; margin-bottom: 16px;">📊 System Status</h4>
        </div>
        """, unsafe_allow_html=True)
        
        # Robot status
        robot_status = "MOVING" if (state.robot_x != state.target_x or state.robot_y != state.target_y) else "IDLE"
        status_class = "status-active" if robot_status == "MOVING" else "status-idle"
        
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Robot Status</div>
            <span class="status-badge {status_class}">{robot_status}</span>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Position</div>
            <div class="metric-value">X:{state.robot_x:.0f} Y:{state.robot_y:.0f}</div>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Gripper</div>
            <div class="metric-value">{'Extended' if state.gripper_extended else 'Retracted'}</div>
            <div style="color: {'#27ae60' if state.gripper_holding else '#e74c3c'};">
                {'Holding Item' if state.gripper_holding else 'Empty'}
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Conveyor</div>
            <div class="metric-value">{state.belt_position:.0f}mm</div>
            <span class="status-badge {'status-active' if state.belt_running else 'status-idle'}">
                {'RUNNING' if state.belt_running else 'STOPPED'}
            </span>
        </div>
        """, unsafe_allow_html=True)
        
        # Inventory grid
        st.markdown("""
        <div class="metric-card">
            <div class="metric-label">Inventory Grid</div>
        </div>
        """, unsafe_allow_html=True)
        
        slot_names = [['C1', 'C2', 'C3'], ['B1', 'B2', 'B3'], ['A1', 'A2', 'A3']]
        for row in slot_names:
            cols = st.columns(3)
            for i, slot_name in enumerate(row):
                status = state.inventory.get(slot_name, '')
                status_class = {
                    '': 'slot-empty',
                    'RAW_DOUGH': 'slot-raw',
                    'BAKED': 'slot-baked',
                    'PACKAGED': 'slot-packaged',
                }.get(status, 'slot-empty')
                
                with cols[i]:
                    st.markdown(f"""
                    <div class="slot-indicator {status_class}">{slot_name}</div>
                    """, unsafe_allow_html=True)
    
    # Footer
    st.markdown("---")
    st.markdown("""
    <div style="text-align: center; color: rgba(255,255,255,0.4); font-size: 12px;">
        <p>🎯 <b>Controls:</b> Click and drag to rotate | Scroll to zoom | Double-click to reset view</p>
        <p>Built with Plotly 3D + Streamlit | STF Digital Twin Demo</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Auto-update belt if running
    if state.belt_running:
        state.belt_position = (state.belt_position + 50) % 1000
        time.sleep(0.5)
        st.rerun()


if __name__ == "__main__":
    main()
