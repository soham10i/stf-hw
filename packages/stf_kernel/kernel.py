"""
The simulation kernel.

Owns authoritative factory state and advances it on a fixed timestep. Headless
and synchronous by design: no HTTP, no database, no MQTT, no clock. The
original simulator awaited fourteen HTTP POSTs from inside a 100 ms tick budget,
so its physics jittered with network latency; here I/O is somebody else's job.

The :class:`PhysicsBackend` protocol is the seam that makes the engine
swappable. :class:`InProcessBackend` is the Python implementation; a
``WebotsBackend`` satisfying the same protocol can be dropped in later without
anything upstream noticing, because the layout - not the backend - defines the
geometry both would use.

Determinism is a hard requirement, not a nice-to-have: golden-trajectory tests
and reproducible fault demos both depend on it. Same seed, same layout, same
tick count implies bitwise-identical state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np

from stf_layout import ComponentType, Joint, Layout

from .motor import Motor
from .trajectory import Trajectory

#: Physics timestep. 100 Hz decouples integration accuracy from the ~30 Hz rate
#: at which state is published to browsers.
DEFAULT_TICK_HZ = 100.0

#: An axis within this distance of its command is considered arrived. The
#: original used a flat 1 mm band, which at 18.75 pulses/mm is 19 encoder
#: counts - coarse enough to mask real positioning error. One pulse is the
#: honest tolerance.
ARRIVAL_PULSES = 1.0


@dataclass(slots=True)
class JointRuntime:
    """Live state of one actuated axis."""

    ref: str
    spec: Joint
    position: float
    commanded: float
    motor: Motor | None = None
    velocity: float = 0.0
    max_tracking_error: float = 0.0

    @property
    def tracking_error(self) -> float:
        """
        Commanded minus actual.

        This is the signal a real digital twin watches: it grows when a motor is
        worn, stalling, or loaded beyond its torque budget. The original system
        could not compute it at all, because the planner and the simulator kept
        separate notions of position.
        """
        return self.commanded - self.position

    @property
    def arrival_tolerance(self) -> float:
        return ARRIVAL_PULSES * self.spec.drive.units_per_pulse()

    @property
    def arrived(self) -> bool:
        return abs(self.tracking_error) <= self.arrival_tolerance


@dataclass
class WorldState:
    """An immutable-by-convention snapshot of the whole factory at one instant."""

    tick: int
    sim_time: float
    joints: dict[str, float]
    commanded: dict[str, float]
    velocities: dict[str, float]
    tracking_error: dict[str, float]
    motors: dict[str, dict]
    belt_position_mm: float
    belt_object_mm: float | None
    sensors: dict[str, bool]
    busy: bool

    def as_vector(self, order: list[str]) -> np.ndarray:
        """Joint positions in the layout's canonical wire order."""
        return np.array([self.joints[ref] for ref in order], dtype=np.float64)


@runtime_checkable
class PhysicsBackend(Protocol):
    """
    Contract every physics engine must satisfy.

    Deliberately tiny. Anything richer would leak the in-process
    implementation's assumptions and defeat the purpose of the seam.
    """

    def reset(self, layout: Layout, seed: int) -> WorldState: ...

    def load(self, trajectory: Trajectory) -> None: ...

    def step(self, dt: float) -> WorldState: ...

    @property
    def busy(self) -> bool: ...


class InProcessBackend:
    """Pure-Python physics. The default backend."""

    def __init__(self, layout: Layout, seed: int = 0) -> None:
        self._layout = layout
        self._seed = seed
        self._joints: dict[str, JointRuntime] = {}
        self._motors: dict[str, Motor] = {}
        self._trajectory: Trajectory | None = None
        self._traj_elapsed = 0.0
        self._tick = 0
        self._sim_time = 0.0
        self._belt_mm = 0.0
        self._belt_object: float | None = None
        self._belt_running = False
        self._belt_direction = 1
        self.reset(layout, seed)

    # -- lifecycle ---------------------------------------------------------

    def reset(self, layout: Layout, seed: int) -> WorldState:
        """
        Rebuild all state from the layout.

        Each component gets an independent RNG stream spawned from one seed, so
        adding a component perturbs only its own stream. Sharing a single
        generator would mean any layout edit invalidated every golden file.
        """
        self._layout = layout
        self._seed = seed
        self._tick = 0
        self._sim_time = 0.0
        self._trajectory = None
        self._traj_elapsed = 0.0
        self._belt_mm = 0.0
        self._belt_object = None
        self._belt_running = False
        self._belt_direction = 1

        component_ids = sorted(layout.components)
        streams = np.random.SeedSequence(seed).spawn(len(component_ids))
        rngs = {
            cid: np.random.default_rng(stream)
            for cid, stream in zip(component_ids, streams, strict=True)
        }

        self._motors = {
            cid: Motor(
                component_id=cid,
                electrical=layout.components[cid].electrical,
                rng=rngs[cid],
            )
            for cid in component_ids
            if layout.components[cid].type
            in (ComponentType.MOTOR, ComponentType.COMPRESSOR)
        }

        home = layout.home_vector()
        self._joints = {
            ref: JointRuntime(
                ref=ref,
                spec=layout.joint(ref),
                position=home[ref],
                commanded=home[ref],
                motor=self._motors.get(layout.joint(ref).motor_id or ""),
            )
            for ref in layout.joint_refs()
        }
        return self.snapshot()

    def load(self, trajectory: Trajectory) -> None:
        """Begin executing a trajectory, replacing any in progress."""
        self._trajectory = trajectory
        self._traj_elapsed = 0.0

    @property
    def busy(self) -> bool:
        if self._trajectory is None:
            return False
        if self._traj_elapsed < self._trajectory.duration:
            return True
        # The plan has run out of time but an axis may still be catching up,
        # which is exactly what a worn motor does.
        return any(not j.arrived for j in self._joints.values())

    # -- belt --------------------------------------------------------------

    def set_belt(self, running: bool, direction: int = 1) -> None:
        self._belt_running = running
        self._belt_direction = 1 if direction >= 0 else -1
        motor = self._motors.get(self._layout.conveyor.motor_id)
        if motor is not None:
            motor.demand(running)

    def place_on_belt(self, position_mm: float = 0.0) -> None:
        self._belt_object = position_mm

    def clear_belt(self) -> None:
        self._belt_object = None

    # -- integration -------------------------------------------------------

    def step(self, dt: float) -> WorldState:
        self._tick += 1
        self._sim_time += dt

        if self._trajectory is not None:
            self._traj_elapsed += dt
            for ref, value in self._trajectory.sample(self._traj_elapsed).items():
                self._joints[ref].commanded = value

        for joint in self._joints.values():
            self._advance_joint(joint, dt)

        self._advance_belt(dt)

        for motor in self._motors.values():
            motor.tick(dt)

        return self.snapshot()

    def _advance_joint(self, joint: JointRuntime, dt: float) -> None:
        """
        Drive one axis toward its command.

        The axis is rate-limited to the drive's derived top speed, so a plan
        that commands motion faster than the hardware can deliver produces
        tracking error rather than teleportation - which is precisely what the
        old integrator did when it moved at a hardcoded 100 mm/s.
        """
        motor = joint.motor
        error = joint.tracking_error

        if abs(error) <= joint.arrival_tolerance:
            joint.position = joint.commanded
            joint.velocity = 0.0
            if motor is not None:
                motor.demand(False)
            return

        if motor is not None:
            motor.demand(True)
            if not motor.at_speed:
                # Still drawing inrush, or stalled by wear: no torque, no motion.
                joint.velocity = 0.0
                joint.max_tracking_error = max(joint.max_tracking_error, abs(error))
                return

        top_speed = joint.spec.drive.max_speed
        step = min(abs(error), top_speed * dt)
        joint.position += step * (1.0 if error > 0 else -1.0)
        joint.velocity = (step / dt) * (1.0 if error > 0 else -1.0) if dt > 0 else 0.0
        joint.position = joint.spec.clamp(joint.position)
        joint.max_tracking_error = max(joint.max_tracking_error, abs(joint.tracking_error))

    def _advance_belt(self, dt: float) -> None:
        if not self._belt_running:
            return
        motor = self._motors.get(self._layout.conveyor.motor_id)
        if motor is not None and not motor.at_speed:
            return

        conveyor = self._layout.conveyor
        step = conveyor.max_speed_mm_s * dt * self._belt_direction
        self._belt_mm = (self._belt_mm + step) % conveyor.length_mm

        if self._belt_object is not None:
            self._belt_object += step
            if not 0.0 <= self._belt_object <= conveyor.length_mm:
                self._belt_object = None  # carried off the end

    # -- observation -------------------------------------------------------

    def _read_sensors(self) -> dict[str, bool]:
        """
        Evaluate the belt sensors.

        Light barriers break when the carrier is inside their window. Trail
        sensors toggle every rib of belt travel, giving the motion proof the
        controller uses to detect a jam - I6 is wired inverted, so the pair
        reading the same value means the belt has stopped.
        """
        conveyor = self._layout.conveyor
        out: dict[str, bool] = {}

        for name, sensor in conveyor.sensors.items():
            if sensor.at_mm is not None:
                lo, hi = sensor.window()
                out[name] = self._belt_object is not None and lo <= self._belt_object <= hi
            else:
                ribs = int(self._belt_mm // (sensor.rib_spacing_mm or 1.0))
                state = bool(ribs % 2)
                out[name] = (not state) if sensor.inverted else state
        return out

    def snapshot(self) -> WorldState:
        return WorldState(
            tick=self._tick,
            sim_time=self._sim_time,
            joints={ref: j.position for ref, j in self._joints.items()},
            commanded={ref: j.commanded for ref, j in self._joints.items()},
            velocities={ref: j.velocity for ref, j in self._joints.items()},
            tracking_error={ref: j.tracking_error for ref, j in self._joints.items()},
            motors={cid: m.snapshot() for cid, m in self._motors.items()},
            belt_position_mm=self._belt_mm,
            belt_object_mm=self._belt_object,
            sensors=self._read_sensors(),
            busy=self.busy,
        )

    def max_tracking_error(self) -> float:
        return max((j.max_tracking_error for j in self._joints.values()), default=0.0)


@dataclass
class Kernel:
    """
    Fixed-timestep driver around a :class:`PhysicsBackend`.

    Uses an accumulator so physics always advances in equal steps regardless of
    how coarsely or irregularly it is driven. The original loop integrated with
    ``dt = now - last_tick``, which made the simulation's behaviour a function
    of process scheduling - two runs of the same scenario gave different answers.
    """

    layout: Layout
    seed: int = 0
    tick_hz: float = DEFAULT_TICK_HZ
    backend: PhysicsBackend = field(init=False)
    _accumulator: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        self.backend = InProcessBackend(self.layout, self.seed)

    @property
    def dt(self) -> float:
        return 1.0 / self.tick_hz

    def load(self, trajectory: Trajectory) -> None:
        self.backend.load(trajectory)

    def step(self) -> WorldState:
        """Advance exactly one physics tick."""
        return self.backend.step(self.dt)

    def advance(self, seconds: float) -> WorldState:
        """
        Advance by wall-time, in whole ticks.

        Leftover time is carried in the accumulator rather than applied as a
        short step, which is what keeps the timestep fixed.
        """
        self._accumulator += seconds
        state = self.backend.snapshot() if hasattr(self.backend, "snapshot") else None
        while self._accumulator >= self.dt:
            state = self.backend.step(self.dt)
            self._accumulator -= self.dt
        return state if state is not None else self.backend.step(self.dt)

    def run_trajectory(self, trajectory: Trajectory, max_seconds: float = 600.0) -> WorldState:
        """
        Execute a trajectory to completion.

        Returns the final state. Raises if the plan does not finish within
        ``max_seconds`` - a stuck axis should surface as a test failure, not as
        an infinite loop.
        """
        self.load(trajectory)
        limit = int(max_seconds * self.tick_hz)
        state = self.backend.step(self.dt)
        for _ in range(limit):
            if not self.backend.busy:
                return state
            state = self.backend.step(self.dt)
        raise TimeoutError(
            f"trajectory {trajectory.name!r} did not settle within {max_seconds}s"
        )


__all__ = [
    "ARRIVAL_PULSES",
    "DEFAULT_TICK_HZ",
    "InProcessBackend",
    "JointRuntime",
    "Kernel",
    "PhysicsBackend",
    "WorldState",
]
