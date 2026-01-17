"""
STF Digital Twin - 3D Visualization Page
Interactive 3D CAD-like visualization of the High-Bay Warehouse System
Using Plotly for Streamlit-native 3D rendering
"""

import streamlit as st
import plotly.graph_objects as go
import numpy as np
import requests
import os
import time
from typing import Dict, List, Tuple, Optional

# Configuration
API_URL = os.environ.get("STF_API_URL", "http://localhost:8000")

# Page Configuration
st.set_page_config(
    page_title="STF 3D Visualization",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================================
# GLASSMORPHISM CSS
# ============================================================================

GLASSMORPHISM_CSS = """
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
}

.header-title {
    font-size: 28px;
    font-weight: 600;
    color: #ffffff;
    margin-bottom: 8px;
}

.header-subtitle {
    font-size: 14px;
    color: rgba(255, 255, 255, 0.5);
}

.status-indicator {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-right: 8px;
    animation: pulse 2s infinite;
}

.status-active { background: #00ff88; box-shadow: 0 0 10px #00ff88; }
.status-idle { background: #70a1ff; box-shadow: 0 0 10px #70a1ff; }
.status-error { background: #ff4757; box-shadow: 0 0 10px #ff4757; }

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}

.control-panel {
    background: rgba(255, 255, 255, 0.03);
    border-radius: 16px;
    padding: 16px;
    margin-bottom: 16px;
}

.metric-card {
    background: rgba(255, 255, 255, 0.05);
    border-radius: 12px;
    padding: 12px;
    text-align: center;
}

.metric-value {
    font-size: 24px;
    font-weight: 600;
    color: #00ff88;
}

.metric-label {
    font-size: 11px;
    color: rgba(255, 255, 255, 0.5);
    text-transform: uppercase;
}
</style>
"""

st.markdown(GLASSMORPHISM_CSS, unsafe_allow_html=True)

# ============================================================================
# 3D WAREHOUSE GEOMETRY BUILDER
# ============================================================================

class WarehouseGeometry:
    """Generates 3D geometry for the High-Bay Warehouse system"""
    
    def __init__(self):
        # Warehouse dimensions (mm)
        self.rack_width = 300
        self.rack_height = 400
        self.rack_depth = 200
        self.slot_size = 100
        self.num_cols = 3
        self.num_rows = 3
        
        # Robot dimensions
        self.robot_size = 40
        self.gripper_length = 60
        
    def create_box_mesh(self, center: Tuple[float, float, float], 
                        size: Tuple[float, float, float],
                        color: str = 'gray') -> Dict:
        """Create a 3D box mesh for Plotly"""
        cx, cy, cz = center
        sx, sy, sz = size
        
        # 8 vertices of a box
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
        
        # 12 triangular faces (2 per side)
        i = [0, 0, 4, 4, 0, 0, 1, 1, 0, 0, 3, 3]
        j = [1, 2, 5, 6, 1, 4, 2, 5, 3, 4, 2, 6]
        k = [2, 3, 6, 7, 4, 5, 5, 6, 4, 7, 6, 7]
        
        return {
            'x': vertices[:, 0],
            'y': vertices[:, 1],
            'z': vertices[:, 2],
            'i': i,
            'j': j,
            'k': k,
            'color': color
        }
    
    def create_rack_structure(self) -> List[go.Mesh3d]:
        """Create the storage rack structure"""
        meshes = []
        
        # Vertical posts
        post_positions = [
            (0, 0), (self.rack_width, 0),
            (0, self.rack_depth), (self.rack_width, self.rack_depth)
        ]
        
        for px, pz in post_positions:
            mesh = self.create_box_mesh(
                center=(px, self.rack_height/2, pz),
                size=(10, self.rack_height, 10),
                color='#444444'
            )
            meshes.append(go.Mesh3d(
                x=mesh['x'], y=mesh['y'], z=mesh['z'],
                i=mesh['i'], j=mesh['j'], k=mesh['k'],
                color='#2a2a3a',
                opacity=0.9,
                name='Rack Post',
                hoverinfo='name'
            ))
        
        # Horizontal shelves
        for row in range(self.num_rows + 1):
            y = row * (self.rack_height / self.num_rows)
            mesh = self.create_box_mesh(
                center=(self.rack_width/2, y, self.rack_depth/2),
                size=(self.rack_width + 20, 5, self.rack_depth + 20),
                color='#333333'
            )
            meshes.append(go.Mesh3d(
                x=mesh['x'], y=mesh['y'], z=mesh['z'],
                i=mesh['i'], j=mesh['j'], k=mesh['k'],
                color='#1a1a2e',
                opacity=0.8,
                name=f'Shelf {row}',
                hoverinfo='name'
            ))
        
        return meshes
    
    def create_storage_slots(self, inventory_data: Optional[Dict] = None) -> List[go.Mesh3d]:
        """Create storage slot indicators with inventory status"""
        meshes = []
        
        slot_colors = {
            'empty': '#1a1a2e',
            'CHOCOLATE': '#8B4513',
            'VANILLA': '#F5DEB3',
            'STRAWBERRY': '#FF69B4',
            'RAW_DOUGH': '#FFD700',
            'BAKED': '#FF8C00',
            'PACKAGED': '#32CD32'
        }
        
        slot_names = [
            ['A1', 'A2', 'A3'],
            ['B1', 'B2', 'B3'],
            ['C1', 'C2', 'C3']
        ]
        
        for row in range(self.num_rows):
            for col in range(self.num_cols):
                x = col * (self.rack_width / self.num_cols) + self.slot_size/2 + 10
                y = row * (self.rack_height / self.num_rows) + self.slot_size/2 + 10
                z = self.rack_depth / 2
                
                slot_name = slot_names[row][col]
                
                # Determine slot color based on inventory
                color = slot_colors['empty']
                status = 'Empty'
                if inventory_data:
                    for slot in inventory_data.get('slots', []):
                        if slot.get('slot_name') == slot_name:
                            if slot.get('cookie'):
                                cookie = slot['cookie']
                                flavor = cookie.get('flavor', 'CHOCOLATE')
                                cookie_status = cookie.get('status', 'RAW_DOUGH')
                                color = slot_colors.get(cookie_status, slot_colors.get(flavor, '#888888'))
                                status = f"{flavor} ({cookie_status})"
                            break
                
                mesh = self.create_box_mesh(
                    center=(x, y, z),
                    size=(self.slot_size - 10, self.slot_size - 10, self.slot_size - 10),
                    color=color
                )
                meshes.append(go.Mesh3d(
                    x=mesh['x'], y=mesh['y'], z=mesh['z'],
                    i=mesh['i'], j=mesh['j'], k=mesh['k'],
                    color=color,
                    opacity=0.85,
                    name=f'{slot_name}: {status}',
                    hoverinfo='name'
                ))
        
        return meshes
    
    def create_robot_arm(self, x: float, y: float, z: float, 
                         gripper_extended: bool = False) -> List[go.Mesh3d]:
        """Create the HBW robot arm (cantilever)"""
        meshes = []
        
        # Main carriage (vertical mover)
        carriage = self.create_box_mesh(
            center=(x, y, -50),
            size=(60, 80, 40),
            color='#ff4444'
        )
        meshes.append(go.Mesh3d(
            x=carriage['x'], y=carriage['y'], z=carriage['z'],
            i=carriage['i'], j=carriage['j'], k=carriage['k'],
            color='#e74c3c',
            opacity=1.0,
            name='Robot Carriage',
            hoverinfo='name'
        ))
        
        # Telescopic arm
        arm_length = self.gripper_length + (50 if gripper_extended else 0)
        arm = self.create_box_mesh(
            center=(x, y, -50 + arm_length/2 + 20),
            size=(30, 30, arm_length),
            color='#ff6666'
        )
        meshes.append(go.Mesh3d(
            x=arm['x'], y=arm['y'], z=arm['z'],
            i=arm['i'], j=arm['j'], k=arm['k'],
            color='#c0392b',
            opacity=1.0,
            name='Telescopic Arm',
            hoverinfo='name'
        ))
        
        # Gripper
        gripper_z = -50 + arm_length + 30
        gripper = self.create_box_mesh(
            center=(x, y, gripper_z),
            size=(50, 20, 20),
            color='#ffaa00'
        )
        meshes.append(go.Mesh3d(
            x=gripper['x'], y=gripper['y'], z=gripper['z'],
            i=gripper['i'], j=gripper['j'], k=gripper['k'],
            color='#f39c12',
            opacity=1.0,
            name='Gripper',
            hoverinfo='name'
        ))
        
        return meshes
    
    def create_conveyor_belt(self, belt_position: float = 0) -> List[go.Mesh3d]:
        """Create the conveyor belt system"""
        meshes = []
        
        # Belt base
        belt_base = self.create_box_mesh(
            center=(self.rack_width + 150, 50, self.rack_depth/2),
            size=(200, 20, 80),
            color='#333333'
        )
        meshes.append(go.Mesh3d(
            x=belt_base['x'], y=belt_base['y'], z=belt_base['z'],
            i=belt_base['i'], j=belt_base['j'], k=belt_base['k'],
            color='#2c3e50',
            opacity=0.9,
            name='Conveyor Base',
            hoverinfo='name'
        ))
        
        # Belt surface (animated position)
        belt_x = self.rack_width + 50 + (belt_position / 1000) * 200
        belt_surface = self.create_box_mesh(
            center=(belt_x, 65, self.rack_depth/2),
            size=(30, 10, 60),
            color='#00ff88'
        )
        meshes.append(go.Mesh3d(
            x=belt_surface['x'], y=belt_surface['y'], z=belt_surface['z'],
            i=belt_surface['i'], j=belt_surface['j'], k=belt_surface['k'],
            color='#00ff88',
            opacity=0.9,
            name=f'Belt Position: {belt_position:.0f}mm',
            hoverinfo='name'
        ))
        
        # Sensor indicators
        sensor_positions = [
            (self.rack_width + 60, 'L1 Entry'),
            (self.rack_width + 110, 'L2 Process'),
            (self.rack_width + 170, 'L3 Exit'),
            (self.rack_width + 230, 'L4 Overflow'),
        ]
        
        for sx, name in sensor_positions:
            sensor = self.create_box_mesh(
                center=(sx, 80, self.rack_depth/2 + 50),
                size=(10, 15, 10),
                color='#00ff88'
            )
            meshes.append(go.Mesh3d(
                x=sensor['x'], y=sensor['y'], z=sensor['z'],
                i=sensor['i'], j=sensor['j'], k=sensor['k'],
                color='#3498db',
                opacity=0.8,
                name=name,
                hoverinfo='name'
            ))
        
        return meshes
    
    def create_floor_and_guides(self) -> List[go.Mesh3d]:
        """Create floor and guide rails"""
        meshes = []
        
        # Floor
        floor = self.create_box_mesh(
            center=(self.rack_width/2 + 100, -5, self.rack_depth/2),
            size=(600, 10, 400),
            color='#111122'
        )
        meshes.append(go.Mesh3d(
            x=floor['x'], y=floor['y'], z=floor['z'],
            i=floor['i'], j=floor['j'], k=floor['k'],
            color='#0a0a15',
            opacity=0.5,
            name='Floor',
            hoverinfo='skip'
        ))
        
        # Horizontal guide rail
        rail = self.create_box_mesh(
            center=(self.rack_width/2, -2, -80),
            size=(self.rack_width + 50, 8, 20),
            color='#555555'
        )
        meshes.append(go.Mesh3d(
            x=rail['x'], y=rail['y'], z=rail['z'],
            i=rail['i'], j=rail['j'], k=rail['k'],
            color='#34495e',
            opacity=0.9,
            name='Guide Rail',
            hoverinfo='name'
        ))
        
        # Vertical guide rail
        v_rail = self.create_box_mesh(
            center=(-30, self.rack_height/2, -80),
            size=(20, self.rack_height + 50, 20),
            color='#555555'
        )
        meshes.append(go.Mesh3d(
            x=v_rail['x'], y=v_rail['y'], z=v_rail['z'],
            i=v_rail['i'], j=v_rail['j'], k=v_rail['k'],
            color='#34495e',
            opacity=0.9,
            name='Vertical Guide',
            hoverinfo='name'
        ))
        
        return meshes


def create_3d_warehouse_figure(robot_x: float = 150, robot_y: float = 200, robot_z: float = 0,
                                belt_position: float = 0, gripper_extended: bool = False,
                                inventory_data: Optional[Dict] = None) -> go.Figure:
    """Create the complete 3D warehouse visualization"""
    
    geometry = WarehouseGeometry()
    
    fig = go.Figure()
    
    # Add all geometry components
    for mesh in geometry.create_floor_and_guides():
        fig.add_trace(mesh)
    
    for mesh in geometry.create_rack_structure():
        fig.add_trace(mesh)
    
    for mesh in geometry.create_storage_slots(inventory_data):
        fig.add_trace(mesh)
    
    for mesh in geometry.create_robot_arm(robot_x, robot_y, robot_z, gripper_extended):
        fig.add_trace(mesh)
    
    for mesh in geometry.create_conveyor_belt(belt_position):
        fig.add_trace(mesh)
    
    # Configure layout
    fig.update_layout(
        scene=dict(
            xaxis=dict(
                title='X (mm)',
                backgroundcolor='rgba(10, 10, 26, 0)',
                gridcolor='rgba(255, 255, 255, 0.1)',
                showbackground=True,
                zerolinecolor='rgba(255, 255, 255, 0.2)',
            ),
            yaxis=dict(
                title='Y (mm)',
                backgroundcolor='rgba(10, 10, 26, 0)',
                gridcolor='rgba(255, 255, 255, 0.1)',
                showbackground=True,
                zerolinecolor='rgba(255, 255, 255, 0.2)',
            ),
            zaxis=dict(
                title='Z (mm)',
                backgroundcolor='rgba(10, 10, 26, 0)',
                gridcolor='rgba(255, 255, 255, 0.1)',
                showbackground=True,
                zerolinecolor='rgba(255, 255, 255, 0.2)',
            ),
            camera=dict(
                eye=dict(x=1.5, y=1.5, z=1.2),
                up=dict(x=0, y=1, z=0),
            ),
            aspectmode='data',
        ),
        paper_bgcolor='rgba(0, 0, 0, 0)',
        plot_bgcolor='rgba(0, 0, 0, 0)',
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=False,
        height=700,
    )
    
    return fig


# ============================================================================
# DATA FETCHING
# ============================================================================

def fetch_dashboard_data() -> Optional[Dict]:
    """Fetch current dashboard data from API"""
    try:
        response = requests.get(f"{API_URL}/dashboard/data", timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        st.warning(f"Could not fetch live data: {e}")
    return None


def fetch_inventory_data() -> Optional[Dict]:
    """Fetch inventory data from API"""
    try:
        response = requests.get(f"{API_URL}/inventory", timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return None


# ============================================================================
# MAIN APPLICATION
# ============================================================================

def main():
    # Header
    st.markdown("""
    <div style="margin-bottom: 24px;">
        <div class="header-title">🏭 3D Warehouse Visualization</div>
        <div class="header-subtitle">Interactive CAD-like view of the High-Bay Warehouse Digital Twin</div>
    </div>
    """, unsafe_allow_html=True)
    
    # Sidebar controls
    with st.sidebar:
        st.markdown("### 🎮 Robot Controls")
        
        # Manual position controls
        robot_x = st.slider("X Position (Horizontal)", 0, 300, 150, 10)
        robot_y = st.slider("Y Position (Vertical)", 0, 400, 200, 10)
        gripper_extended = st.checkbox("Extend Gripper", False)
        
        st.markdown("---")
        st.markdown("### 🔄 Conveyor Controls")
        belt_position = st.slider("Belt Position (mm)", 0, 1000, 0, 50)
        
        st.markdown("---")
        st.markdown("### 📷 Camera Presets")
        camera_preset = st.selectbox(
            "View Angle",
            ["Isometric", "Front", "Side", "Top", "Robot Focus"]
        )
        
        st.markdown("---")
        auto_refresh = st.checkbox("Auto-refresh (1s)", False)
        
        if st.button("🔄 Refresh Data"):
            st.rerun()
    
    # Fetch live data
    dashboard_data = fetch_dashboard_data()
    inventory_data = fetch_inventory_data()
    
    # Use live data if available
    if dashboard_data:
        hardware_states = dashboard_data.get('hardware_states', [])
        for hw in hardware_states:
            if hw.get('device_id') == 'HBW':
                robot_x = hw.get('current_x', robot_x)
                robot_y = hw.get('current_y', robot_y)
        
        conveyor_state = dashboard_data.get('conveyor_state', {})
        if conveyor_state:
            belt_position = conveyor_state.get('belt_position_mm', belt_position)
    
    # Main content
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # 3D Visualization
        fig = create_3d_warehouse_figure(
            robot_x=robot_x,
            robot_y=robot_y,
            robot_z=0,
            belt_position=belt_position,
            gripper_extended=gripper_extended,
            inventory_data=inventory_data
        )
        
        # Apply camera preset
        camera_settings = {
            "Isometric": dict(eye=dict(x=1.5, y=1.5, z=1.2)),
            "Front": dict(eye=dict(x=0, y=0, z=2.5)),
            "Side": dict(eye=dict(x=2.5, y=0.5, z=0)),
            "Top": dict(eye=dict(x=0, y=2.5, z=0)),
            "Robot Focus": dict(eye=dict(x=0.8, y=0.8, z=0.8)),
        }
        fig.update_layout(scene_camera=camera_settings.get(camera_preset, camera_settings["Isometric"]))
        
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': True})
    
    with col2:
        # Status panel
        st.markdown("""
        <div class="control-panel">
            <h4 style="color: white; margin-bottom: 16px;">📊 System Status</h4>
        </div>
        """, unsafe_allow_html=True)
        
        # Robot position
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Robot Position</div>
            <div class="metric-value">X:{robot_x}</div>
            <div class="metric-value">Y:{robot_y}</div>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Belt position
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Belt Position</div>
            <div class="metric-value">{belt_position}mm</div>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Inventory summary
        if inventory_data:
            slots = inventory_data.get('slots', [])
            occupied = sum(1 for s in slots if s.get('cookie'))
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">Inventory</div>
                <div class="metric-value">{occupied}/9</div>
            </div>
            """, unsafe_allow_html=True)
        
        # Connection status
        status_class = "status-active" if dashboard_data else "status-error"
        status_text = "Connected" if dashboard_data else "Offline"
        st.markdown(f"""
        <div style="margin-top: 24px; text-align: center;">
            <span class="status-indicator {status_class}"></span>
            <span style="color: rgba(255,255,255,0.7);">{status_text}</span>
        </div>
        """, unsafe_allow_html=True)
    
    # Auto-refresh
    if auto_refresh:
        time.sleep(1)
        st.rerun()
    
    # Footer info
    st.markdown("---")
    st.markdown("""
    <div style="text-align: center; color: rgba(255,255,255,0.4); font-size: 12px;">
        <p>🎯 <b>Tip:</b> Click and drag to rotate the 3D view. Scroll to zoom. Double-click to reset.</p>
        <p>Built with Plotly 3D | STF Digital Twin v3.0</p>
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
