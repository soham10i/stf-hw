# 3D Visualization for STF Digital Twin

This document describes the 3D visualization capabilities added to the STF Digital Twin project, providing CAD-like views of the High-Bay Warehouse system.

## Overview

The STF Digital Twin now includes interactive 3D visualization of the warehouse system, allowing users to view and interact with the digital twin in a manner similar to professional CAD software. Two implementation approaches are provided to accommodate different deployment scenarios.

## Available Visualization Options

### Option 1: Plotly 3D (Recommended)

**File:** `dashboard/pages/visualization_3d.py`

Plotly provides browser-native 3D rendering that works in all environments without additional dependencies. This is the recommended option for most deployments.

**Features:**
- Interactive 3D view with rotate, zoom, and pan controls
- Real-time updates from the API
- Camera presets (Isometric, Front, Side, Top, Robot Focus)
- Color-coded inventory slots based on cookie status
- Animated conveyor belt position
- Robot arm with telescopic gripper visualization

**Usage:**
```bash
# Run as part of the main dashboard
streamlit run dashboard/app.py
# Navigate to "3D Visualization" in the sidebar
```

### Option 2: PyVista (Advanced CAD-like)

**File:** `dashboard/pages/visualization_3d_pyvista.py`

PyVista is built on VTK (Visualization Toolkit), the same technology used in professional CAD and scientific visualization software. It provides higher-quality rendering but requires a display server.

**Features:**
- High-quality mesh rendering with proper lighting
- True 3D geometry with cylinders, boxes, and complex shapes
- Professional CAD-like appearance
- Export capabilities to various 3D formats

**Requirements:**
- Display server (X11 or virtual framebuffer)
- Additional dependencies: `pyvista`, `stpyvista`, `vtk`

**Usage:**
```bash
# Install dependencies
pip install pyvista stpyvista

# Run the dashboard
streamlit run dashboard/app.py
# Navigate to "PyVista CAD View" in the sidebar
```

### Option 3: Standalone Demo

**File:** `demo_3d_visualization.py`

A self-contained demo that showcases the 3D visualization without requiring the full API backend. Useful for demonstrations and testing.

**Usage:**
```bash
streamlit run demo_3d_visualization.py
```

## Architecture

### Geometry Builder

The 3D visualization uses a modular geometry builder that creates mesh objects for each component:

```
WarehouseGeometry
├── create_rack_structure()      # Storage rack frame
├── create_storage_slots()       # 3x3 inventory grid
├── create_robot_arm()           # HBW cantilever robot
├── create_conveyor_belt()       # Conveyor with sensors
├── create_floor_and_guides()    # Floor and guide rails
```

### Component Mapping

| Physical Component | 3D Representation | Color |
|-------------------|-------------------|-------|
| Rack Posts | Vertical boxes | #2a2a3a |
| Shelves | Horizontal planes | #1a1a2e |
| Empty Slot | Transparent cube | #1a1a2e |
| RAW_DOUGH Cookie | Yellow cube | #FFD700 |
| BAKED Cookie | Orange cube | #FF8C00 |
| PACKAGED Cookie | Green cube | #32CD32 |
| Robot Carriage | Red box | #e74c3c |
| Telescopic Arm | Dark red box | #c0392b |
| Gripper | Orange/Green box | #f39c12/#27ae60 |
| Conveyor Base | Dark blue box | #2c3e50 |
| Belt Item | Green box | #00ff88 |
| Sensors | Blue cylinders | #3498db |

### Real-Time Updates

The visualization connects to the FastAPI backend to fetch live data:

```python
# Fetch hardware states
GET /hardware/states -> robot position (X, Y, Z)

# Fetch inventory
GET /inventory -> slot occupancy and cookie status

# Fetch conveyor state
GET /dashboard/data -> belt_position_mm, sensor states
```

## Camera Controls

### Plotly Controls
- **Rotate:** Click and drag
- **Zoom:** Scroll wheel
- **Pan:** Shift + click and drag
- **Reset:** Double-click

### Camera Presets
| Preset | Eye Position | Use Case |
|--------|--------------|----------|
| Isometric | (1.5, 1.5, 1.2) | Default overview |
| Front | (0, 0, 2.5) | View from front |
| Side | (2.5, 0.5, 0) | Side profile |
| Top | (0, 2.5, 0) | Bird's eye view |
| Robot Focus | (0.8, 0.8, 0.8) | Close-up on robot |

## Customization

### Adding New Components

To add a new component to the visualization:

1. Create a mesh generation method in `WarehouseGeometry`:
```python
def create_new_component(self, position, size):
    mesh = self.create_box_mesh(center=position, size=size)
    return go.Mesh3d(
        x=mesh['x'], y=mesh['y'], z=mesh['z'],
        i=mesh['i'], j=mesh['j'], k=mesh['k'],
        color='#color',
        opacity=0.9,
        name='Component Name',
        hoverinfo='name'
    )
```

2. Add the component to the figure in `create_3d_warehouse_figure()`:
```python
fig.add_trace(geometry.create_new_component(pos, size))
```

### Changing Colors

Colors are defined as hex strings. Update the color mappings in:
- `status_colors` dict for inventory states
- Individual component colors in mesh creation calls

### Adjusting Dimensions

Physical dimensions are defined in the `WarehouseGeometry` class:
```python
self.rack_width = 300   # mm
self.rack_height = 400  # mm
self.rack_depth = 200   # mm
self.slot_size = 100    # mm
```

## Performance Considerations

### Plotly Performance
- Renders efficiently with up to ~100 mesh objects
- Auto-refresh at 1Hz is recommended for smooth updates
- Disable auto-refresh when not needed to reduce CPU usage

### PyVista Performance
- Higher quality but more resource-intensive
- Requires WebGL support in browser
- May have issues in headless environments

## Troubleshooting

### "PyVista rendering error"
- Ensure a display server is available
- Try using the Plotly visualization instead
- For headless servers, install `xvfb`: `apt-get install xvfb`

### Slow rendering
- Reduce the number of mesh objects
- Lower the refresh rate
- Disable auto-refresh when not actively monitoring

### Colors not updating
- Check API connectivity
- Verify the inventory endpoint returns correct data
- Clear browser cache and reload

## Future Enhancements

Potential improvements for the 3D visualization:

1. **Animation System**: Smooth transitions for robot movement
2. **Collision Detection**: Visual warnings for potential collisions
3. **Path Planning Visualization**: Show planned robot paths
4. **VR/AR Support**: Integration with WebXR for immersive viewing
5. **Export to CAD Formats**: Save scenes as STEP, STL, or OBJ files
6. **Real-time Shadows**: Dynamic shadow casting for better depth perception
