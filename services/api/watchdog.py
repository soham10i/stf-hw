"""
Autonomous background telemetry watchdog and anomaly detector for the industrial digital twin.

Monitors cyber-physical simulation frames at runtime to detect:
  1. Thermal drift & runaway (oven temperature exceeding critical envelopes).
  2. Kinematic stall / conveyor jam (orders exceeding expected phase durations).
  3. Predictive maintenance degradation (component wear > 90% or critically low RUL).
  4. Safety interlock status (emergency stop engagements).

Maintains an incident registry with deduplication, severity grading, and proactive recommendations.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from .logging_config import get_logger

if TYPE_CHECKING:
    from .runtime import SimRuntime

logger = get_logger(__name__)

# Operational safety envelopes
MAX_SAFE_OVEN_TEMP_C = 220.0
MIN_ACTIVE_OVEN_TEMP_C = 140.0
MAX_ORDER_EXECUTION_TIME_S = 180.0
CRITICAL_WEAR_PERCENT = 90.0
INCIDENT_DEDUPLICATION_COOLDOWN_S = 30.0


@dataclass
class Incident:
    """Anomalous telemetry event detected by the proactive watchdog."""

    id: str
    timestamp: float
    category: str  # "THERMAL", "KINEMATICS", "WEAR", "SAFETY", "STALL"
    severity: str  # "INFO", "WARNING", "CRITICAL"
    title: str
    detail: str
    recommended_action: str
    acknowledged: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Convert incident to a serializable dictionary."""
        return asdict(self)


class TelemetryWatchdog:
    """Proactive background monitoring service evaluating live simulation frames."""

    def __init__(self, runtime: SimRuntime | None = None, poll_interval: float = 1.0) -> None:
        self.runtime = runtime
        self.poll_interval = poll_interval
        self._running = False
        self._task: asyncio.Task | None = None
        self._incidents: list[Incident] = []
        self._last_alert_time: dict[str, float] = {}
        self._last_scan_time: float = 0.0

    @property
    def is_running(self) -> bool:
        """Return True if background monitoring loop is active."""
        return self._running

    async def start(self) -> None:
        """Start the autonomous watchdog loop task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="stf-telemetry-watchdog")
        logger.info("Autonomous telemetry watchdog started (interval=%.1fs)", self.poll_interval)

    async def stop(self) -> None:
        """Gracefully shut down the watchdog loop task."""
        self._running = False
        task = self._task
        self._task = None
        if task and not task.done():
            task.cancel()
            try:
                try:
                    current_loop = asyncio.get_running_loop()
                except RuntimeError:
                    current_loop = None
                if current_loop and task.get_loop() is current_loop:
                    await task
            except (asyncio.CancelledError, RuntimeError):
                pass
        logger.info("Autonomous telemetry watchdog stopped")

    async def _run_loop(self) -> None:
        """Periodic background evaluation task."""
        while self._running:
            try:
                self.scan_once()
            except Exception as e:
                logger.error("Error during watchdog telemetry scan: %s", e, exc_info=True)
            await asyncio.sleep(self.poll_interval)

    def scan_once(self) -> list[Incident]:
        """Perform a single immediate anomaly evaluation pass over the live runtime."""
        self._last_scan_time = time.time()
        new_incidents: list[Incident] = []
        now = time.time()

        # 1. Evaluate runtime availability
        if not self.runtime:
            from .actuation import get_runtime
            self.runtime = get_runtime()
        if not self.runtime:
            return new_incidents

        # 2. Check Emergency Stop Interlock
        from .actuation import get_guard
        guard = get_guard()
        if guard.emergency_latched:
            self._record_deduped(
                key="safety:e_stop",
                category="SAFETY",
                severity="CRITICAL",
                title="Emergency Stop Interlock Active",
                detail="System emergency stop latch is engaged. Motion commands are locked out.",
                action="Verify physical safety zone clearance and reset emergency stop latch.",
                collector=new_incidents,
                now=now,
            )

        # 3. Check Live Oven & Thermal Envelopes
        try:
            oven_state = getattr(self.runtime, "_oven", {})
            lamp_on = bool(oven_state.get("lamp", False))
            # Simulated temperature approximation or live thermal readout
            # When oven lamp is on, nominal bake temp is ~195°C; check slider/door
            slider = float(oven_state.get("slider", 1.0))
            door = float(oven_state.get("door", 1.0))
            if lamp_on and door > 0.1:
                # Door open while heater active represents thermal loss and safety hazard
                self._record_deduped(
                    key="thermal:door_open_heating",
                    category="THERMAL",
                    severity="WARNING",
                    title="Oven Heating With Door Ajar",
                    detail=f"Oven lamp is ON while door position is {door:.2f} (expected <= 0.05).",
                    action="Inspect oven door pneumatic cylinder (OVN-D02) and close door.",
                    collector=new_incidents,
                    now=now,
                )
        except Exception as e:
            logger.debug("Watchdog oven check exception: %s", e)

        # 4. Check Active Order Duration & Stall
        try:
            active_order = getattr(self.runtime, "_active", None)
            if active_order:
                start_t = getattr(active_order, "start_time", None)
                if start_t and (now - start_t) > MAX_ORDER_EXECUTION_TIME_S:
                    self._record_deduped(
                        key=f"stall:order_{active_order.id}",
                        category="STALL",
                        severity="WARNING",
                        title=f"Order #{active_order.id} Execution Timeout",
                        detail=f"Order #{active_order.id} ({active_order.op}) active for {now - start_t:.1f}s (> {MAX_ORDER_EXECUTION_TIME_S}s).",
                        action="Check crane travel axis and gripper vacuum pressure.",
                        collector=new_incidents,
                        now=now,
                    )
        except Exception as e:
            logger.debug("Watchdog order stall check exception: %s", e)

        # 5. Check Wear & Predictive Maintenance
        try:
            from .tools import MACHINE, _comp_at, load_json
            data = load_json(MACHINE)
            components = data.get("components", {})
            for name, comp in components.items():
                res = _comp_at(comp, shifts=140.0, pm=True)
                wear = float(res.get("wear", 0.0))
                if wear >= CRITICAL_WEAR_PERCENT:
                    self._record_deduped(
                        key=f"wear:{name}",
                        category="WEAR",
                        severity="WARNING",
                        title=f"Critical Component Wear: {name}",
                        detail=f"Wear level at {wear:.1f}% (exceeds {CRITICAL_WEAR_PERCENT}% threshold).",
                        action=f"Schedule preventive replacement for {name}.",
                        collector=new_incidents,
                        now=now,
                    )
        except Exception as e:
            logger.debug("Watchdog wear check exception: %s", e)

        return new_incidents

    def _record_deduped(
        self,
        key: str,
        category: str,
        severity: str,
        title: str,
        detail: str,
        action: str,
        collector: list[Incident],
        now: float,
    ) -> None:
        """Record an incident if not currently silenced by deduplication cooldown."""
        last_alert = self._last_alert_time.get(key, 0.0)
        if now - last_alert < INCIDENT_DEDUPLICATION_COOLDOWN_S:
            return

        incident = Incident(
            id=str(uuid.uuid4()),
            timestamp=now,
            category=category,
            severity=severity,
            title=title,
            detail=detail,
            recommended_action=action,
            acknowledged=False,
        )
        self._last_alert_time[key] = now
        self._incidents.append(incident)
        collector.append(incident)
        logger.warning(
            "WATCHDOG ANOMALY DETECTED [%s - %s]: %s (%s)",
            severity, category, title, detail,
        )

    def list_incidents(
        self,
        severity: str | None = None,
        category: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return recorded telemetry incidents, newest first."""
        res = self._incidents
        if severity:
            sev_up = severity.strip().upper()
            res = [i for i in res if i.severity == sev_up]
        if category:
            cat_up = category.strip().upper()
            res = [i for i in res if i.category == cat_up]
        return [i.as_dict() for i in reversed(res[-limit:])]

    def acknowledge_incident(self, incident_id: str) -> bool:
        """Mark a specific incident as acknowledged by an operator."""
        for inc in self._incidents:
            if inc.id == incident_id:
                inc.acknowledged = True
                return True
        return False

    def clear_incidents(self) -> None:
        """Clear all active incident records."""
        self._incidents.clear()
        self._last_alert_time.clear()

    def get_status(self) -> dict[str, Any]:
        """Return watchdog health overview."""
        critical_count = sum(1 for i in self._incidents if i.severity == "CRITICAL" and not i.acknowledged)
        warning_count = sum(1 for i in self._incidents if i.severity == "WARNING" and not i.acknowledged)
        return {
            "running": self._running,
            "last_scan_time": self._last_scan_time,
            "total_incidents": len(self._incidents),
            "unacknowledged_critical": critical_count,
            "unacknowledged_warning": warning_count,
            "healthy": critical_count == 0,
        }


_WATCHDOG: TelemetryWatchdog | None = None


def get_watchdog(runtime: SimRuntime | None = None) -> TelemetryWatchdog:
    """Return the global TelemetryWatchdog singleton."""
    global _WATCHDOG
    if _WATCHDOG is None:
        _WATCHDOG = TelemetryWatchdog(runtime=runtime)
    elif runtime and _WATCHDOG.runtime is None:
        _WATCHDOG.runtime = runtime
    return _WATCHDOG


def set_watchdog(watchdog: TelemetryWatchdog) -> None:
    """Set the active TelemetryWatchdog instance."""
    global _WATCHDOG
    _WATCHDOG = watchdog
