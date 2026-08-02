"""
stf_kernel - trajectory planning and deterministic physics for the factory.

    from stf_layout import get_layout
    from stf_kernel import plan_retrieve

    traj = plan_retrieve(get_layout(), "B2")
    print(traj.describe())
"""

from .kernel import (
    ARRIVAL_PULSES,
    DEFAULT_TICK_HZ,
    InProcessBackend,
    JointRuntime,
    Kernel,
    PhysicsBackend,
    WorldState,
)
from .motor import Motor, MotorPhase
from .planner import (
    DEFAULT_OFFSETS,
    FORK,
    LIFT,
    TRAVEL,
    PickPlaceOffsets,
    PlanError,
    check_square_path,
    plan_home,
    plan_retrieve,
    plan_store,
)
from .trajectory import (
    ACCEL_FACTOR,
    DEAD_ZONE,
    DECEL_FACTOR,
    Segment,
    Trajectory,
    make_segment,
    profile_duration,
)

__all__ = [
    "ACCEL_FACTOR",
    "ARRIVAL_PULSES",
    "DEAD_ZONE",
    "DECEL_FACTOR",
    "DEFAULT_OFFSETS",
    "DEFAULT_TICK_HZ",
    "FORK",
    "LIFT",
    "TRAVEL",
    "InProcessBackend",
    "JointRuntime",
    "Kernel",
    "Motor",
    "MotorPhase",
    "PhysicsBackend",
    "WorldState",
    "PickPlaceOffsets",
    "PlanError",
    "Segment",
    "Trajectory",
    "check_square_path",
    "make_segment",
    "plan_home",
    "plan_retrieve",
    "plan_store",
    "profile_duration",
]
