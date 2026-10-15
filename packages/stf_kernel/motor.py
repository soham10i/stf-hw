"""
Electro-mechanical motor model.

Ported from ``MotorSimulation`` in ``hardware/mock_factory.py``. The inrush /
steady-state current behaviour and the wear model were the most physically
credible part of the original code and the numbers are unchanged.

Two things were wrong with the original and are fixed here:

* It called ``time.time()`` inside the tick to decide when the startup inrush
  ended, which made the physics depend on wall-clock scheduling and therefore
  irreproducible. Startup is now measured in accumulated simulation time.
* It drew from the global ``random`` module, so two runs with the same seed
  diverged as soon as anything else in the process consumed randomness. Each
  motor now owns an independent generator.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

from stf_layout import Electrical

#: Health lost per second of running. From the original model: at this rate a
#: motor crosses the 0.8 anomaly threshold after ~556 hours of motion.
HEALTH_DECAY_PER_SEC = 0.0001

#: Below the anomaly threshold, the chance per second that a worn bearing draws
#: a current spike. The original expressed this per 10 Hz tick (5%); it is
#: converted to a rate here so the behaviour no longer depends on tick rate.
BEARING_SPIKE_RATE_HZ = 0.5

#: Below this health, the motor intermittently stalls for a moment.
MICRO_STOPPAGE_HEALTH = 0.5
MICRO_STOPPAGE_RATE_HZ = 0.2


class MotorPhase(str, Enum):
    IDLE = "IDLE"
    STARTUP = "STARTUP"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"


@dataclass(slots=True)
class Motor:
    """One motor's electrical and wear state."""

    component_id: str
    electrical: Electrical
    rng: np.random.Generator

    phase: MotorPhase = MotorPhase.IDLE
    current_amps: float = 0.0
    health_score: float = 1.0
    accumulated_runtime_sec: float = 0.0
    energy_joules: float = 0.0

    #: Seconds spent in STARTUP so far. Replaces the old wall-clock timestamp.
    _startup_elapsed: float = 0.0
    #: Set for one tick when a worn motor stalls; the kernel reads it to hold
    #: the axis still, which is what makes wear visible as tracking error.
    stalled: bool = False

    def __post_init__(self) -> None:
        self.current_amps = self.electrical.idle_amps

    @property
    def is_active(self) -> bool:
        return self.phase in (MotorPhase.STARTUP, MotorPhase.RUNNING)

    @property
    def at_speed(self) -> bool:
        """True once the inrush is over and the motor can deliver full torque."""
        return self.phase is MotorPhase.RUNNING and not self.stalled

    def demand(self, active: bool) -> None:
        """Tell the motor whether its axis currently wants to move."""
        if active:
            if self.phase in (MotorPhase.IDLE, MotorPhase.STOPPING):
                self.phase = MotorPhase.STARTUP
                self._startup_elapsed = 0.0
        elif self.phase in (MotorPhase.STARTUP, MotorPhase.RUNNING):
            self.phase = MotorPhase.STOPPING

    def tick(self, dt: float) -> None:
        """Advance one timestep. Pure function of state, dt and this motor's RNG."""
        self.stalled = False

        if self.phase is MotorPhase.STARTUP:
            self._startup_elapsed += dt
            if self._startup_elapsed * 1000.0 >= self.electrical.startup_duration_ms:
                self.phase = MotorPhase.RUNNING
        elif self.phase is MotorPhase.STOPPING:
            self.phase = MotorPhase.IDLE

        if self.phase is MotorPhase.IDLE:
            self.current_amps = self.electrical.idle_amps
        elif self.phase is MotorPhase.STARTUP:
            self.current_amps = self.electrical.startup_amps
        elif self.phase is MotorPhase.STOPPING:
            self.current_amps = self.electrical.idle_amps
        else:
            self.current_amps = self.electrical.running_amps
            self.accumulated_runtime_sec += dt
            self.health_score = max(0.0, self.health_score - HEALTH_DECAY_PER_SEC * dt)

            if self.health_score < self.electrical.health_anomaly_threshold:
                if self.rng.random() < BEARING_SPIKE_RATE_HZ * dt:
                    self.current_amps = self.electrical.bearing_failure_amps

            if self.health_score < MICRO_STOPPAGE_HEALTH:
                if self.rng.random() < MICRO_STOPPAGE_RATE_HZ * dt:
                    self.stalled = True

        self.energy_joules += self.power_watts * dt

    @property
    def power_watts(self) -> float:
        return self.current_amps * self.electrical.voltage

    @property
    def time_to_failure_hours(self) -> float | None:
        """
        Hours of running left before health reaches the 0.5 stall threshold.

        The original computed this in the API layer as
        ``(health - 0.5) / 0.0001 / 3600``; it belongs with the wear model.
        """
        if self.health_score <= MICRO_STOPPAGE_HEALTH:
            return 0.0
        return (self.health_score - MICRO_STOPPAGE_HEALTH) / HEALTH_DECAY_PER_SEC / 3600.0

    def snapshot(self) -> dict[str, float | str | bool]:
        return {
            "component_id": self.component_id,
            "phase": self.phase.value,
            "current_amps": round(self.current_amps, 4),
            "voltage": self.electrical.voltage,
            "power_watts": round(self.power_watts, 3),
            "energy_joules": round(self.energy_joules, 3),
            "health_score": round(self.health_score, 6),
            "accumulated_runtime_sec": round(self.accumulated_runtime_sec, 3),
            "is_active": self.is_active,
            "stalled": self.stalled,
        }


__all__ = [
    "BEARING_SPIKE_RATE_HZ",
    "HEALTH_DECAY_PER_SEC",
    "MICRO_STOPPAGE_HEALTH",
    "MICRO_STOPPAGE_RATE_HZ",
    "Motor",
    "MotorPhase",
]
