"""
STF Digital Twin - PyVista 3D Visualization
Advanced CAD-like 3D visualization using PyVista + stpyvista
This provides more realistic rendering similar to CAD software
"""

import streamlit as st
import numpy as np
import pyvista as pv
from stpyvista import stpyvista
import requests
import os
from typing import Dict, List, Tuple, Optional

# Configuration
API_URL = os.environ.get("STF_API_URL", "http://localhost:8000")

# Page Configuration
st.set_page_config(
    page_title="STF 3D CAD View",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Set PyVista theme for better rendering
pv.global_theme.background = '#0a0a1a'
pv.global_theme.font.color = 'white'
pv.global_theme.show_edges = True
pv.global_theme.edge_color = '#333333'

# ============================================================================
# CSS STYLING
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

.header-container {
    background: rgba(255, 255, 255, 0.03);
    backdrop-filter: blur(20px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 16px;
    padding: 20px;
    margin-bottom: 20px;
}

.header-title {
    font-size: 24px;
    font-weight: 600;
    color: #ffffff;
}

.header-subtitle {
    font-size: 13px;
    color: rgba(255, 255, 255, 0.5);
}

.info-card {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 12px;
}

.metric-row {
    display: flex;
    justify-content: space-between;
    margin-bottom: 8px;
}

.metric-label {
    color: rgba(255, 255, 255, 0.5);
    font-size: 12px;
}

.metric-value {
    color: #00ff88;
    font-weight: 600;
}
</style>
""", unsafe_allow_html=True)


# ============================================================================
# PYVISTA WAREHOUSE BUILDER
# ============================================================================

class PyVistaWarehouse:
    """Creates PyVista meshes for the High-Bay Warehouse"""
    
    def __init__(self):
        # Dimensions (mm scaled to visualization units)
        self.scale = 0.01  # Convert mm to visualization units
        self.rack_width = 300 * self.scale
        self.rack_height = 400 * self.scale
        self.rack_depth = 200 * self.scale
        self.slot_size = 80 * self.scale
        self.num_cols = 3
        self.num_rows = 3
        
    def create_rack_frame(self) -> pv.PolyData:
        """Create the storage rack frame structure"""
        meshes = []
        
        # Vertical posts (4 corners)
        post_radius = 0.05
        post_positions = [
            (0, 0), (self.rack_width, 0),
            (0, self.rack_depth), (self.rack_width, self.rack_depth)
        ]
        
        for px, pz in post_positions:
            post = pv.Cylinder(
                center=(px, self.rack_height/2, pz),
                direction=(0, 1, 0),
                radius=post_radius,
                height=self.rack_height
            )
            meshes.append(post)
        
        # Horizontal beams (shelves)
        for row in range(self.num_rows + 1):
            y = row * (self.rack_height / self.num_rows)
            shelf = pv.Box(
                bounds=(
                    -0.1, self.rack_width + 0.1,
                    y - 0.02, y + 0.02,
                    -0.1, self.rack_depth + 0.1
                )
            )
            meshes.append(shelf)
        
        # Combine all meshes
        combined = meshes[0]
        for mesh in meshes[1:]:
            combined = combined.merge(mesh)
        
        return combined
    
    def create_storage_slots(self, inventory_data: Optional[Dict] = None) -> List[Tuple[pv.PolyData, str]]:
        """Create storage slot cubes with colors based on inventory"""
        slots = []
        
        color_map = {
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
                x = col * (self.rack_width / self.num_cols) + self.slot_size/2 + 0.1
                y = row * (self.rack_height / self.num_rows) + self.slot_size/2 + 0.05
                z = self.rack_depth / 2
                
                slot_name = slot_names[row][col]
                
                # Determine color
                color = color_map['empty']
                if inventory_data:
                    for slot in inventory_data.get('slots', []):
                        if slot.get('slot_name') == slot_name and slot.get('cookie'):
                            cookie = slot['cookie']
                            status = cookie.get('status', 'RAW_DOUGH')
                            color = color_map.get(status, color_map.get(cookie.get('flavor', 'CHOCOLATE'), '#888888'))
                            break
                
                cube = pv.Cube(
                    center=(x, y, z),
                    x_length=self.slot_size * 0.8,
                    y_length=self.slot_size * 0.8,
                    z_length=self.slot_size * 0.8
                )
                slots.append((cube, color))
        
        return slots
    
    def create_robot_arm(self, x: float, y: float, gripper_extended: bool = False) -> List[Tuple[pv.PolyData, str]]:
        """Create the HBW robot arm components"""
        components = []
        
        # Scale positions
        x_scaled = x * self.scale
        y_scaled = y * self.scale
        
        # Main carriage body
        carriage = pv.Box(
            bounds=(
                x_scaled - 0.3, x_scaled + 0.3,
                y_scaled - 0.4, y_scaled + 0.4,
                -0.6, -0.3
            )
        )
        components.append((carriage, '#e74c3c'))
        
        # Telescopic arm
        arm_length = 0.8 if gripper_extended else 0.5
        arm = pv.Box(
            bounds=(
                x_scaled - 0.15, x_scaled + 0.15,
                y_scaled - 0.15, y_scaled + 0.15,
                -0.3, -0.3 + arm_length
            )
        )
        components.append((arm, '#c0392b'))
        
        # Gripper
        gripper_z = -0.3 + arm_length
        gripper = pv.Box(
            bounds=(
                x_scaled - 0.25, x_scaled + 0.25,
                y_scaled - 0.1, y_scaled + 0.1,
                gripper_z, gripper_z + 0.15
            )
        )
        components.append((gripper, '#f39c12'))
        
        # Gripper fingers
        for offset in [-0.2, 0.2]:
            finger = pv.Box(
                bounds=(
                    x_scaled + offset - 0.03, x_scaled + offset + 0.03,
                    y_scaled - 0.08, y_scaled + 0.08,
                    gripper_z + 0.15, gripper_z + 0.25
                )
            )
            components.append((finger, '#f1c40f'))
        
        return components
    
    def create_conveyor(self, belt_position: float = 0) -> List[Tuple[pv.PolyData, str]]:
        """Create the conveyor belt system"""
        components = []
        
        # Belt base
        base = pv.Box(
            bounds=(
                self.rack_width + 0.5, self.rack_width + 2.5,
                0, 0.5,
                self.rack_depth/2 - 0.4, self.rack_depth/2 + 0.4
            )
        )
        components.append((base, '#2c3e50'))
        
        # Belt surface (moving part)
        belt_x = self.rack_width + 0.5 + (belt_position / 1000) * 2.0
        belt = pv.Box(
            bounds=(
                belt_x - 0.15, belt_x + 0.15,
                0.5, 0.6,
                self.rack_depth/2 - 0.3, self.rack_depth/2 + 0.3
            )
        )
        components.append((belt, '#00ff88'))
        
        # Rollers
        for rx in [self.rack_width + 0.7, self.rack_width + 1.5, self.rack_width + 2.3]:
            roller = pv.Cylinder(
                center=(rx, 0.25, self.rack_depth/2),
                direction=(0, 0, 1),
                radius=0.1,
                height=0.6
            )
            components.append((roller, '#7f8c8d'))
        
        # Sensors
        sensor_positions = [
            self.rack_width + 0.6,
            self.rack_width + 1.2,
            self.rack_width + 1.8,
            self.rack_width + 2.4,
        ]
        for sx in sensor_positions:
            sensor = pv.Cylinder(
                center=(sx, 0.7, self.rack_depth/2 + 0.5),
                direction=(0, 1, 0),
                radius=0.05,
                height=0.15
            )
            components.append((sensor, '#3498db'))
        
        return components
    
    def create_floor(self) -> pv.PolyData:
        """Create the floor plane"""
        floor = pv.Plane(
            center=(self.rack_width/2 + 1, -0.01, self.rack_depth/2),
            direction=(0, 1, 0),
            i_size=6,
            j_size=4
        )
        return floor
    
    def create_guide_rails(self) -> List[Tuple[pv.PolyData, str]]:
        """Create guide rails for robot movement"""
        rails = []
        
        # Horizontal rail
        h_rail = pv.Box(
            bounds=(
                -0.1, self.rack_width + 0.1,
                -0.05, 0.05,
                -0.8, -0.6
            )
        )
        rails.append((h_rail, '#34495e'))
        
        # Vertical rail
        v_rail = pv.Box(
            bounds=(
                -0.3, -0.1,
                -0.05, self.rack_height + 0.1,
                -0.8, -0.6
            )
        )
        rails.append((v_rail, '#34495e'))
        
        return rails


def create_pyvista_scene(robot_x: float = 150, robot_y: float = 200,
                         belt_position: float = 0, gripper_extended: bool = False,
                         inventory_data: Optional[Dict] = None) -> pv.Plotter:
    """Create the complete PyVista scene"""
    
    warehouse = PyVistaWarehouse()
    
    # Create plotter
    plotter = pv.Plotter(window_size=[800, 600])
    plotter.set_background('#0a0a1a')
    
    # Add floor
    floor = warehouse.create_floor()
    plotter.add_mesh(floor, color='#0f0f23', opacity=0.5)
    
    # Add rack frame
    rack = warehouse.create_rack_frame()
    plotter.add_mesh(rack, color='#2a2a3a', opacity=0.9)
    
    # Add storage slots
    for slot_mesh, color in warehouse.create_storage_slots(inventory_data):
        plotter.add_mesh(slot_mesh, color=color, opacity=0.85)
    
    # Add robot arm
    for component, color in warehouse.create_robot_arm(robot_x, robot_y, gripper_extended):
        plotter.add_mesh(component, color=color, opacity=1.0)
    
    # Add conveyor
    for component, color in warehouse.create_conveyor(belt_position):
        plotter.add_mesh(component, color=color, opacity=0.9)
    
    # Add guide rails
    for rail, color in warehouse.create_guide_rails():
        plotter.add_mesh(rail, color=color, opacity=0.9)
    
    # Set camera position
    plotter.camera_position = [
        (5, 4, 5),  # Camera position
        (1.5, 2, 1),  # Focal point
        (0, 1, 0)  # Up vector
    ]
    
    return plotter


# ============================================================================
# DATA FETCHING
# ============================================================================

def fetch_inventory_data() -> Optional[Dict]:
    """Fetch inventory data from API"""
    try:
        response = requests.get(f"{API_URL}/inventory", timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return None


def fetch_hardware_states() -> Optional[Dict]:
    """Fetch hardware states from API"""
    try:
        response = requests.get(f"{API_URL}/hardware/states", timeout=5)
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
    <div class="header-container">
        <div class="header-title">🔧 PyVista CAD Visualization</div>
        <div class="header-subtitle">Advanced 3D rendering with VTK backend - Similar to professional CAD software</div>
    </div>
    """, unsafe_allow_html=True)
    
    # Sidebar controls
    with st.sidebar:
        st.markdown("### 🎮 Robot Position")
        robot_x = st.slider("X (Horizontal)", 0, 300, 150, 10, key="pv_x")
        robot_y = st.slider("Y (Vertical)", 0, 400, 200, 10, key="pv_y")
        gripper_extended = st.checkbox("Extend Gripper", False, key="pv_grip")
        
        st.markdown("---")
        st.markdown("### 🔄 Conveyor")
        belt_position = st.slider("Belt Position (mm)", 0, 1000, 0, 50, key="pv_belt")
        
        st.markdown("---")
        if st.button("🔄 Refresh Data", key="pv_refresh"):
            st.rerun()
    
    # Fetch live data
    inventory_data = fetch_inventory_data()
    hardware_data = fetch_hardware_states()
    
    # Use live data if available
    if hardware_data:
        for hw in hardware_data.get('states', []):
            if hw.get('device_id') == 'HBW':
                robot_x = hw.get('current_x', robot_x)
                robot_y = hw.get('current_y', robot_y)
    
    # Main content
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.markdown("### 3D CAD View")
        
        try:
            # Create PyVista scene
            plotter = create_pyvista_scene(
                robot_x=robot_x,
                robot_y=robot_y,
                belt_position=belt_position,
                gripper_extended=gripper_extended,
                inventory_data=inventory_data
            )
            
            # Render with stpyvista
            stpyvista(plotter, key="pyvista_main")
            
        except Exception as e:
            st.error(f"PyVista rendering error: {e}")
            st.info("Note: PyVista requires a display server. Try the Plotly-based visualization instead.")
    
    with col2:
        st.markdown("### 📊 Status")
        
        st.markdown(f"""
        <div class="info-card">
            <div class="metric-row">
                <span class="metric-label">Robot X</span>
                <span class="metric-value">{robot_x} mm</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Robot Y</span>
                <span class="metric-value">{robot_y} mm</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Belt</span>
                <span class="metric-value">{belt_position} mm</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Gripper</span>
                <span class="metric-value">{'Extended' if gripper_extended else 'Retracted'}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # Inventory status
        if inventory_data:
            slots = inventory_data.get('slots', [])
            occupied = sum(1 for s in slots if s.get('cookie'))
            
            st.markdown(f"""
            <div class="info-card">
                <div class="metric-row">
                    <span class="metric-label">Inventory</span>
                    <span class="metric-value">{occupied}/9 slots</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
        
        # Connection status
        status = "🟢 Connected" if inventory_data else "🔴 Offline"
        st.markdown(f"""
        <div class="info-card">
            <div class="metric-row">
                <span class="metric-label">API Status</span>
                <span style="color: white;">{status}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    # Info section
    st.markdown("---")
    st.markdown("""
    ### ℹ️ About PyVista Visualization
    
    **PyVista** is built on top of VTK (Visualization Toolkit), the same technology used in professional CAD and scientific visualization software. It provides:
    
    - **High-quality rendering** with proper lighting and materials
    - **True 3D geometry** with mesh-based objects
    - **Interactive controls** (rotate, zoom, pan)
    - **Export capabilities** to various 3D formats
    
    **Note:** PyVista rendering requires a display server. If you see rendering errors, use the Plotly-based visualization which works in all environments.
    """)


if __name__ == "__main__":
    main()
