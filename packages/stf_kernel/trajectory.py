"""
Timed motion segments.

The original codebase had two kinematic engines that never met: an analytic
pulse-counting planner in ``controller/main_controller.py`` that moved one axis
at a time, and a first-order Euler integrator in ``hardware/mock_factory.py``
that moved all three simultaneously at a hardcoded speed. Neither validated
against the other, so a "step" meant something different on each side.

This module is the contract between them. The planner emits a
:class:`Trajectory`; the kernel tracks it and reports the deviation. The
difference between commanded and achieved position becomes a first-class
``tracking_error`` signal - which is what a real digital twin actually monitors.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from stf_layout import Joint, JointKind, Layout

#: Ramp rates, expressed as multiples of a joint's top speed per second.
#: Taken from the original motor model, which did ``v += max_velocity * dt * 4``
#: on spin-up and ``v -= max_velocity * dt * 2`` on spin-down - i.e. roughly
#: 0.25 s to reach speed and 0.5 s to stop.
ACCEL_FACTOR = 4.0
DECEL_FACTOR = 2.0

#: Displacements below this are dropped. The original planner used a 0.1 mm
#: dead zone; kept, because at 18.75 pulses/mm anything smaller is under two
#: encoder counts and the firmware would not act on it either.
DEAD_ZONE = 0.1


@dataclass(frozen=True, slots=True)
class Segment:
    """
    A single-joint move with a trapezoidal velocity profile.

    Single-joint by construction: the HBW is a stacker crane whose safe
    choreography depends on axes moving in sequence, not on a diagonal shortcut.
    The original planner called this a "square path" and it is preserved here.
    """

    joint: str
    start: float
    target: float
    duration: float
    pulses: int
    direction: int
    peak_speed: float
    description: str = ""

    @property
    def delta(self) -> float:
        return self.target - self.start

    def position_at(self, t: float) -> float:
        """
        Commanded position ``t`` seconds into this segment.

        Integrates the same trapezoid the duration was computed from, so a
        segment sampled at its own duration lands exactly on ``target``.
        """
        if t <= 0.0:
            return self.start
        if t >= self.duration:
            return self.target

        v = self.peak_speed
        a = _accel(v)
        d = _decel(v)
        t_a = v / a
        t_d = v / d
        dist = abs(self.delta)
        s_a = 0.5 * a * t_a * t_a
        s_d = 0.5 * d * t_d * t_d
        t_cruise = max(0.0, (dist - s_a - s_d) / v) if v > 0 else 0.0

        if t < t_a:
            travelled = 0.5 * a * t * t
        elif t < t_a + t_cruise:
            travelled = s_a + v * (t - t_a)
        else:
            td = t - t_a - t_cruise
            travelled = s_a + v * t_cruise + (v * td - 0.5 * d * td * td)

        return self.start + math.copysign(min(travelled, dist), self.delta)


@dataclass(frozen=True, slots=True)
class Trajectory:
    """An ordered plan. Segments execute one after another."""

    name: str
    segments: tuple[Segment, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.segments)

    def __iter__(self):
        return iter(self.segments)

    @property
    def duration(self) -> float:
        return sum(s.duration for s in self.segments)

    @property
    def total_pulses(self) -> int:
        return sum(s.pulses for s in self.segments)

    def final_targets(self) -> dict[str, float]:
        """Where each joint ends up. Used to assert the plan is self-consistent."""
        out: dict[str, float] = {}
        for seg in self.segments:
            out[seg.joint] = seg.target
        return out

    def sample(self, t: float) -> dict[str, float]:
        """
        Commanded position of every joint touched, ``t`` seconds in.

        Joints hold their last commanded value once their segment completes,
        which is what a real axis controller does between moves.
        """
        out: dict[str, float] = {}
        elapsed = 0.0
        for seg in self.segments:
            if t >= elapsed + seg.duration:
                out[seg.joint] = seg.target
            elif t <= elapsed:
                out.setdefault(seg.joint, seg.start)
            else:
                out[seg.joint] = seg.position_at(t - elapsed)
            elapsed += seg.duration
        return out

    def describe(self) -> str:
        lines = [f"{self.name}: {len(self.segments)} segments, {self.duration:.2f}s"]
        elapsed = 0.0
        for i, seg in enumerate(self.segments, 1):
            elapsed += seg.duration
            lines.append(
                f"  {i:2d}. {seg.joint:<12} {seg.start:7.1f} -> {seg.target:7.1f} "
                f"({seg.pulses:5d}p, {seg.duration:5.2f}s, t={elapsed:6.2f}s)  {seg.description}"
            )
        return "\n".join(lines)


def _accel(top_speed: float) -> float:
    return ACCEL_FACTOR * top_speed


def _decel(top_speed: float) -> float:
    return DECEL_FACTOR * top_speed


def profile_duration(distance: float, top_speed: float) -> tuple[float, float]:
    """
    Duration and peak speed of a trapezoidal move over ``distance``.

    Short moves never reach top speed; they get a triangular profile whose peak
    is solved from the accel/decel split. Returning the peak lets
    :meth:`Segment.position_at` reconstruct the exact same curve.
    """
    distance = abs(distance)
    if distance <= 0.0 or top_speed <= 0.0:
        return 0.0, 0.0

    a = _accel(top_speed)
    d = _decel(top_speed)
    s_a = top_speed * top_speed / (2.0 * a)
    s_d = top_speed * top_speed / (2.0 * d)

    if distance >= s_a + s_d:
        cruise = (distance - s_a - s_d) / top_speed
        return top_speed / a + cruise + top_speed / d, top_speed

    peak = math.sqrt(2.0 * distance * a * d / (a + d))
    return peak / a + peak / d, peak


def make_segment(
    layout: Layout,
    joint_ref: str,
    start: float,
    target: float,
    description: str = "",
) -> Segment | None:
    """
    Build one segment, or ``None`` if the move is inside the dead zone.

    Raises if the target is outside the joint's limits - a plan that commands an
    axis past its physical stop should fail here, loudly, rather than as a
    mid-demo timeout.
    """
    joint: Joint = layout.joint(joint_ref)

    if not joint.contains(target):
        raise ValueError(
            f"{joint_ref}: target {target} is outside limits {joint.limits}"
        )

    delta = target - start
    if abs(delta) < DEAD_ZONE:
        return None

    top_speed = joint.drive.max_speed
    duration, peak = profile_duration(delta, top_speed)

    return Segment(
        joint=joint_ref,
        start=start,
        target=target,
        duration=duration,
        pulses=joint.pulses_for(delta),
        direction=1 if delta > 0 else -1,
        peak_speed=peak,
        description=description,
    )


def units_of(joint: Joint) -> str:
    return "mm" if joint.kind is JointKind.PRISMATIC else "deg"


__all__ = [
    "ACCEL_FACTOR",
    "DEAD_ZONE",
    "DECEL_FACTOR",
    "Segment",
    "Trajectory",
    "make_segment",
    "profile_duration",
    "units_of",
]
