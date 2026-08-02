"""
Schema for the canonical factory layout.

This module defines the *only* place where factory geometry is allowed to live.
Before this existed the repository carried four mutually contradictory slot
coordinate tables (``database/models.py`` had two, ``hardware/mock_factory.py``
a third with the rack rows inverted, and ``dashboard/app.py`` a fourth), so the
planner, the physics and the renderer each believed in a different factory.

Everything downstream - the kinematic planner, the simulation kernel, the REST
payload the browser builds its scene graph from, and the URDF exporter - reads
these models. Nothing may hardcode a coordinate; ``tests/test_layout_invariants``
enforces that with a source-tree scan.

Conventions, declared once and never re-litigated:

* Lengths are millimetres, angles degrees, time seconds, current amps.
* The world frame is right-handed with **+Z up**, origin at the front-bottom-left
  corner of the rack.
* Joints are *named* (``lift``, ``fork``, ``plunge``, ``swivel``), never "the Z
  axis". The old code called the HBW fork and the VGR suction column both "Z"
  even though one is horizontal and the other vertical, which is how the two
  kinematic engines silently disagreed.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = 1


class _Frozen(BaseModel):
    """Layout data is immutable once loaded - it is configuration, not state."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class JointKind(str, Enum):
    PRISMATIC = "prismatic"
    REVOLUTE = "revolute"


class Axis(str, Enum):
    """Unit axis a joint travels along (prismatic) or rotates about (revolute)."""

    X_POS = "+x"
    X_NEG = "-x"
    Y_POS = "+y"
    Y_NEG = "-y"
    Z_POS = "+z"
    Z_NEG = "-z"

    def unit(self) -> tuple[float, float, float]:
        sign = -1.0 if self.value[0] == "-" else 1.0
        return {
            "x": (sign, 0.0, 0.0),
            "y": (0.0, sign, 0.0),
            "z": (0.0, 0.0, sign),
        }[self.value[1]]


class Pose(_Frozen):
    """A translation in world millimetres. Rotations are carried by joints."""

    xyz: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def translated(self, dx: float = 0.0, dy: float = 0.0, dz: float = 0.0) -> Pose:
        x, y, z = self.xyz
        return Pose(xyz=(x + dx, y + dy, z + dz))


class Drive(_Frozen):
    """
    Encoder-motor drivetrain.

    The repository previously hardcoded ``max_velocity = 100.0`` mm/s in the
    simulator while the lab calibration recorded in
    ``hardware/hbw_withfaults_simulation.py`` implied 14.27 mm/s - the simulation
    ran 7.01x faster than the real machine, and every cycle time and energy
    figure it ever reported was wrong by that factor. Speed is therefore
    *derived* here and cannot be overridden.
    """

    pulses_per_rev: int = Field(gt=0, description="Encoder pulses per output-shaft revolution")
    motor_rpm: float = Field(gt=0, description="Free-running output shaft speed")

    # Exactly one of these, depending on joint kind.
    spindle_pitch_mm: float | None = Field(
        default=None, gt=0, description="Linear travel per revolution"
    )
    gear_ratio: float | None = Field(
        default=None,
        gt=0,
        description="Reduction: motor revolutions per output revolution (57 means 57:1)",
    )

    @property
    def pulses_per_mm(self) -> float:
        if self.spindle_pitch_mm is None:
            raise AttributeError("pulses_per_mm is only defined for a prismatic drive")
        return self.pulses_per_rev / self.spindle_pitch_mm

    @property
    def pulses_per_deg(self) -> float:
        """Encoder counts per degree of *output* rotation, after the reduction."""
        if self.gear_ratio is None:
            raise AttributeError("pulses_per_deg is only defined for a revolute drive")
        return (self.pulses_per_rev * self.gear_ratio) / 360.0

    @property
    def sec_per_pulse(self) -> float:
        return 60.0 / (self.motor_rpm * self.pulses_per_rev)

    @property
    def _pulses_per_unit(self) -> float:
        return self.pulses_per_mm if self.spindle_pitch_mm is not None else self.pulses_per_deg

    @property
    def max_speed(self) -> float:
        """mm/s for a prismatic drive, deg/s for a revolute one."""
        return 1.0 / (self.sec_per_pulse * self._pulses_per_unit)

    def units_per_pulse(self) -> float:
        """Smallest commandable increment - the honest positioning tolerance."""
        return 1.0 / self._pulses_per_unit


class Joint(_Frozen):
    """
    One actuated degree of freedom.

    ``limits`` are in millimetres for prismatic joints and degrees for revolute
    ones, expressed in the joint's own coordinate - i.e. always measured from
    the home/reference-switch position along ``axis``.
    """

    kind: JointKind = JointKind.PRISMATIC
    axis: Axis
    limits: tuple[float, float]
    home: float = 0.0
    drive: Drive
    reference_switch: str | None = Field(default=None, description="Digital input id, e.g. 'I2'")
    motor_id: str | None = Field(default=None, description="Component registry id, e.g. 'HBW_X'")
    positions: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Named waypoints along this joint, e.g. the fork's "
            "retracted/carry/extended stops. The planner reads these instead of "
            "hardcoding Z_RETRACTED/Z_CARRY/Z_EXTENDED as the old controller did."
        ),
    )

    @model_validator(mode="after")
    def _check(self) -> Joint:
        lo, hi = self.limits
        if lo >= hi:
            raise ValueError(f"limits must be increasing, got {self.limits}")
        if not lo <= self.home <= hi:
            raise ValueError(f"home {self.home} outside limits {self.limits}")
        for name, value in self.positions.items():
            if not lo <= value <= hi:
                raise ValueError(f"named position {name}={value} outside limits {self.limits}")
        if self.kind is JointKind.PRISMATIC and self.drive.spindle_pitch_mm is None:
            raise ValueError("a prismatic joint needs drive.spindle_pitch_mm")
        if self.kind is JointKind.REVOLUTE and self.drive.gear_ratio is None:
            raise ValueError("a revolute joint needs drive.gear_ratio")
        return self

    @property
    def span(self) -> float:
        return self.limits[1] - self.limits[0]

    def clamp(self, value: float) -> float:
        lo, hi = self.limits
        return min(hi, max(lo, value))

    def contains(self, value: float) -> bool:
        lo, hi = self.limits
        return lo <= value <= hi

    def at(self, position_name: str) -> float:
        """Resolve a named waypoint, e.g. ``layout.joint('hbw.fork').at('extended')``."""
        try:
            return self.positions[position_name]
        except KeyError as exc:
            known = sorted(self.positions)
            raise KeyError(f"no named position {position_name!r}; known: {known}") from exc

    def pulses_for(self, delta: float) -> int:
        """Encoder pulses for a signed displacement, truncated as the firmware does."""
        per_unit = (
            self.drive.pulses_per_mm
            if self.kind is JointKind.PRISMATIC
            else self.drive.pulses_per_deg
        )
        return int(abs(delta) * per_unit)


class DeviceKind(str, Enum):
    CARTESIAN_STACKER = "cartesian_stacker"
    CYLINDRICAL_ARM = "cylindrical_arm"
    BELT = "belt"


class Device(_Frozen):
    """A robot: a base pose plus an ordered chain of joints."""

    kind: DeviceKind
    base: Pose = Pose()
    joints: dict[str, Joint]
    tool: str | None = Field(default=None, description="'fork' | 'suction' | None")

    @model_validator(mode="after")
    def _non_empty(self) -> Device:
        if not self.joints:
            raise ValueError("a device needs at least one joint")
        return self

    def joint_names(self) -> list[str]:
        return list(self.joints.keys())


class RowOrder(str, Enum):
    """
    Whether rack row A sits at the bottom or the top.

    This single field is the fix for the repository's worst geometry defect:
    ``database/models.py`` placed row A at the bottom while
    ``hardware/mock_factory.py`` placed it at the top, so a retrieve from A1
    planned against one shelf and executed against another.
    """

    BOTTOM_UP = "bottom_up"
    TOP_DOWN = "top_down"


class RackAxisSpec(_Frozen):
    count: int = Field(gt=0)
    pitch: float = Field(gt=0, description="Centre-to-centre spacing in mm")
    labels: list[str]

    @model_validator(mode="after")
    def _labels_match(self) -> RackAxisSpec:
        if len(self.labels) != self.count:
            raise ValueError(f"{self.count} positions but {len(self.labels)} labels")
        return self


class Rack(_Frozen):
    """
    A shelf grid. Slots are *generated* from this spec.

    No slot coordinate table exists anywhere in the codebase any more - that is
    the point. Change the pitch here and the planner, the kernel, the renderer
    and the URDF all move together.
    """

    rows: RackAxisSpec
    cols: RackAxisSpec
    order: RowOrder = RowOrder.BOTTOM_UP
    origin: Pose = Pose()
    slot_envelope: tuple[float, float, float] = Field(
        default=(60.0, 50.0, 60.0), description="Interior clear size (x, y, z) in mm"
    )

    @property
    def slot_names(self) -> list[str]:
        return [f"{r}{c}" for r in self.rows.labels for c in self.cols.labels]

    def row_index(self, row_label: str) -> int:
        return self.rows.labels.index(row_label)

    def slot_pose(self, slot: str) -> Pose:
        """
        World-frame centre of a slot's opening.

        Rows run along +Z (height), columns along +X (travel). Depth (+Y) is the
        rack face, so a slot's centre sits at the rack origin's Y.
        """
        row_label, col_label = self._split(slot)
        r = self.rows.labels.index(row_label)
        c = self.cols.labels.index(col_label)

        if self.order is RowOrder.TOP_DOWN:
            r = self.rows.count - 1 - r

        ox, oy, oz = self.origin.xyz
        return Pose(xyz=(ox + c * self.cols.pitch, oy, oz + r * self.rows.pitch))

    def _split(self, slot: str) -> tuple[str, str]:
        for row_label in self.rows.labels:
            if slot.startswith(row_label):
                col_label = slot[len(row_label) :]
                if col_label in self.cols.labels:
                    return row_label, col_label
        raise KeyError(f"unknown slot {slot!r}; valid slots are {self.slot_names}")

    def contains(self, slot: str) -> bool:
        try:
            self._split(slot)
        except KeyError:
            return False
        return True


class SensorKind(str, Enum):
    LIGHT_BARRIER = "light_barrier"
    TRAIL = "trail"
    REFERENCE_SWITCH = "reference_switch"


class BeltSensor(_Frozen):
    kind: SensorKind
    at_mm: float | None = Field(default=None, ge=0, description="Position along the belt")
    tolerance_mm: float = Field(default=10.0, gt=0)
    rib_spacing_mm: float | None = Field(default=None, gt=0, description="Trail sensor rib pitch")
    inverted: bool = False

    @model_validator(mode="after")
    def _check(self) -> BeltSensor:
        if self.kind is SensorKind.LIGHT_BARRIER and self.at_mm is None:
            raise ValueError("a light barrier needs at_mm")
        if self.kind is SensorKind.TRAIL and self.rib_spacing_mm is None:
            raise ValueError("a trail sensor needs rib_spacing_mm")
        return self

    def window(self) -> tuple[float, float]:
        if self.at_mm is None:
            raise AttributeError("only a positional sensor has a trigger window")
        return (self.at_mm - self.tolerance_mm, self.at_mm + self.tolerance_mm)


class Conveyor(_Frozen):
    """
    The belt bridging the two robots.

    ``pose`` is the world position of belt-local coordinate 0 and ``axis`` is
    the direction of increasing local coordinate. Local 0 is the VGR end and
    ``length_mm`` the HBW end, which is what the original sensor constants
    (I3 at 15 mm "VGR interface", I2 at 105 mm "HBW interface") already assumed.
    """

    length_mm: float = Field(gt=0)
    width_mm: float = Field(default=40.0, gt=0)
    pose: Pose = Pose()
    axis: Axis = Axis.Y_NEG
    motor_id: str = "CONV_M1"
    max_speed_mm_s: float = Field(default=60.0, gt=0)
    sensors: dict[str, BeltSensor] = Field(default_factory=dict)

    def sensor_window(self, name: str) -> tuple[float, float]:
        return self.sensors[name].window()

    def local_to_world(self, s_mm: float) -> Pose:
        """Map a belt-local coordinate to a world pose."""
        ux, uy, uz = self.axis.unit()
        x, y, z = self.pose.xyz
        return Pose(xyz=(x + ux * s_mm, y + uy * s_mm, z + uz * s_mm))

    @property
    def hbw_end(self) -> Pose:
        return self.local_to_world(self.length_mm)

    @property
    def vgr_end(self) -> Pose:
        return self.local_to_world(0.0)


class ComponentType(str, Enum):
    MOTOR = "motor"
    SENSOR = "sensor"
    ACTUATOR = "actuator"
    COMPRESSOR = "compressor"
    VALVE = "valve"


class Electrical(_Frozen):
    """
    Ported verbatim from ``hardware/mock_factory.py::ElectricalModel``. The
    inrush/steady-state behaviour and the wear thresholds were the most
    physically credible part of the original codebase and are kept unchanged.
    """

    idle_amps: float = 0.05
    startup_amps: float = 2.5
    running_amps: float = 1.2
    startup_duration_ms: int = 500
    voltage: float = 24.0
    bearing_failure_amps: float = 3.5
    health_anomaly_threshold: float = 0.8


class Component(_Frozen):
    """One row of what used to be ``seed_components()`` in the database."""

    subsystem: str
    type: ComponentType
    name: str | None = None
    electrical: Electrical = Electrical()
    max_current: float = 5.0
    maintenance_interval_hours: int = 1000


class RenderSpec(_Frozen):
    scene_scale: float = Field(default=0.001, gt=0, description="mm -> scene units (metres)")
    time_scale: float = Field(
        default=1.0,
        gt=0,
        description="Presentation-only speed-up. Never applied to physics.",
    )
    meshes: dict[str, str] = Field(default_factory=dict)


class FrameSpec(_Frozen):
    handedness: Literal["right"] = "right"
    up: Literal["z"] = "z"
    origin: str = "rack_front_bottom_left"


class Units(_Frozen):
    length: Literal["mm"] = "mm"
    angle: Literal["deg"] = "deg"
    time: Literal["s"] = "s"
    current: Literal["A"] = "A"
    voltage: Literal["V"] = "V"


class Station(_Frozen):
    """A named world position a device can be commanded to (oven, delivery...)."""

    pose: Pose
    description: str | None = None


class Layout(_Frozen):
    """The whole factory, as data."""

    schema_version: int = SCHEMA_VERSION
    units: Units = Units()
    frame: FrameSpec = FrameSpec()
    devices: dict[str, Device]
    racks: dict[str, Rack]
    conveyor: Conveyor
    stations: dict[str, Station] = Field(default_factory=dict)
    components: dict[str, Component] = Field(default_factory=dict)
    render: RenderSpec = RenderSpec()

    @model_validator(mode="after")
    def _check(self) -> Layout:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"layout schema_version {self.schema_version} != supported {SCHEMA_VERSION}"
            )
        for dev_name, dev in self.devices.items():
            for joint_name, joint in dev.joints.items():
                if joint.motor_id and joint.motor_id not in self.components:
                    raise ValueError(
                        f"{dev_name}.{joint_name} references unknown component {joint.motor_id!r}"
                    )
        if self.conveyor.motor_id not in self.components:
            raise ValueError(f"conveyor references unknown component {self.conveyor.motor_id!r}")
        return self

    # ---- the accessors every consumer goes through -------------------------

    @property
    def main_rack(self) -> Rack:
        return self.racks["main"]

    def slot_pose(self, slot: str) -> Pose:
        """
        Resolve a slot to a world pose. This is *the* function that must agree
        across kernel, planner, API payload and URDF; ``test_slot_frame_is_singular``
        asserts exactly that.
        """
        for rack in self.racks.values():
            if rack.contains(slot):
                return rack.slot_pose(slot)
        raise KeyError(f"unknown slot {slot!r}")

    def all_slots(self) -> list[str]:
        return [s for rack in self.racks.values() for s in rack.slot_names]

    def joint(self, ref: str) -> Joint:
        """Look up a joint by dotted reference, e.g. ``hbw.lift``."""
        device, _, joint = ref.partition(".")
        if not joint:
            raise KeyError(f"joint reference must be 'device.joint', got {ref!r}")
        try:
            return self.devices[device].joints[joint]
        except KeyError as exc:
            raise KeyError(f"unknown joint {ref!r}") from exc

    def joint_refs(self) -> list[str]:
        """
        Stable, ordered list of every joint in the factory.

        This ordering defines the wire layout of the binary hot-frame sent to
        the browser at 30 Hz, so it must be deterministic across processes.
        """
        return [
            f"{dev_name}.{joint_name}"
            for dev_name in sorted(self.devices)
            for joint_name in self.devices[dev_name].joint_names()
        ]

    def home_vector(self) -> dict[str, float]:
        return {ref: self.joint(ref).home for ref in self.joint_refs()}

    def motor_ids(self) -> list[str]:
        return sorted(cid for cid, c in self.components.items() if c.type is ComponentType.MOTOR)

    def fingerprint(self) -> str:
        """
        Content hash of the layout. Sent in the WebSocket ``hello`` frame so a
        browser holding a stale scene graph can detect it and reload rather than
        rendering the factory at coordinates that no longer exist.
        """
        import hashlib

        payload = self.model_dump_json(exclude_none=True).encode()
        return hashlib.blake2b(payload, digest_size=8).hexdigest()


__all__ = [
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
    "FrameSpec",
    "Joint",
    "JointKind",
    "Layout",
    "Pose",
    "Rack",
    "RackAxisSpec",
    "RenderSpec",
    "RowOrder",
    "SensorKind",
    "Station",
    "Units",
]
