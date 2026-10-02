"""
stf_layout - the canonical description of the Smart Tabletop Factory.

Import geometry from here and nowhere else::

    from stf_layout import get_layout

    layout = get_layout()
    layout.slot_pose("A1")                  # world position of a shelf
    layout.joint("hbw.fork").at("extended") # named waypoint along a joint
    layout.joint("hbw.travel").drive.max_speed  # 14.27 mm/s, derived
"""

from .loader import (
    DEFAULT_LAYOUT_PATH,
    LayoutError,
    clear_cache,
    get_layout,
    layout_path,
    load_layout,
)
from .schema import (
    SCHEMA_VERSION,
    Axis,
    BeltSensor,
    Component,
    ComponentType,
    Conveyor,
    Device,
    DeviceKind,
    Drive,
    Electrical,
    Joint,
    JointKind,
    Layout,
    Pose,
    Rack,
    RowOrder,
    SensorKind,
    Station,
)

__all__ = [
    "DEFAULT_LAYOUT_PATH",
    "SCHEMA_VERSION",
    "Axis",
    "BeltSensor",
    "Component",
    "ComponentType",
    "Conveyor",
    "Device",
    "DeviceKind",
    "Drive",
    "Electrical",
    "Joint",
    "JointKind",
    "Layout",
    "LayoutError",
    "Pose",
    "Rack",
    "RowOrder",
    "SensorKind",
    "Station",
    "clear_cache",
    "get_layout",
    "layout_path",
    "load_layout",
]
