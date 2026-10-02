"""
Headless live sim runner.

    PYTHONPATH=packages python -m services.sim.live --slot B2 --op retrieve

Steps the kernel in real time and prints the crane's live state to the
terminal. This is not the eventual sim service - that one publishes to Redis
and MQTT (Phase 4) - but it drives the real physics at the real clock, so it is
an honest way to watch the twin move before the browser front end exists.

Pass --fast to run as quickly as the CPU allows (useful for a full cycle in a
few seconds); the physics is identical, only the wall-clock pacing changes.
"""

from __future__ import annotations

import argparse
import sys
import time

from stf_kernel import Kernel, plan_home, plan_retrieve, plan_store
from stf_layout import JointKind, Layout, get_layout

# ANSI helpers - the runner is meant to be watched, so it earns a little colour.
CLEAR = "\033[2J\033[H"
DIM = "\033[2m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


def _bar(value: float, lo: float, hi: float, width: int = 30) -> str:
    span = hi - lo or 1.0
    filled = max(0, min(width, round((value - lo) / span * width)))
    return "█" * filled + "░" * (width - filled)


def _render(layout: Layout, kernel: Kernel, label: str) -> str:
    state = kernel.backend.snapshot()
    lines = [
        f"{BOLD}Smart Tabletop Factory - live kernel{RESET}   "
        f"{DIM}layout {layout.fingerprint()}{RESET}",
        f"{DIM}{label}{RESET}",
        "",
        f"  t = {state.sim_time:6.2f}s    tick {state.tick:6d}    "
        f"{'RUNNING' if state.busy else 'IDLE':>8}",
        "",
    ]

    for ref in layout.joint_refs():
        joint = layout.joint(ref)
        lo, hi = joint.limits
        pos = state.joints[ref]
        err = state.tracking_error[ref]
        unit = "mm" if joint.kind is JointKind.PRISMATIC else "deg"
        err_col = RED if abs(err) > 1.0 else (YELLOW if abs(err) > 0.1 else GREEN)
        lines.append(
            f"  {ref:<12} {_bar(pos, lo, hi)} "
            f"{pos:7.1f}{unit:<3} "
            f"{err_col}err {err:+6.2f}{RESET}"
        )

    lines.append("")
    lines.append(f"  {DIM}motor            amps   health   phase{RESET}")
    for cid in layout.motor_ids():
        m = state.motors.get(cid)
        if not m:
            continue
        health = m["health_score"]
        h_col = GREEN if health > 0.8 else (YELLOW if health > 0.5 else RED)
        lines.append(
            f"  {cid:<14} {m['current_amps']:5.2f}A  "
            f"{h_col}{health:6.3f}{RESET}  {m['phase']:<8}"
        )

    belt = state.belt_position_mm
    lines.append("")
    lines.append(f"  belt         {_bar(belt, 0, layout.conveyor.length_mm)} {belt:6.1f}mm")
    sensors = " ".join(
        f"{('%s' % ('▲' if v else '·'))}{name}" for name, v in sorted(state.sensors.items())
    )
    lines.append(f"  sensors      {sensors}")
    lines.append("")
    lines.append(f"{DIM}Ctrl-C to stop{RESET}")
    return "\n".join(lines)


def build_plan(layout: Layout, op: str, slot: str):
    if op == "retrieve":
        return plan_retrieve(layout, slot)
    if op == "store":
        return plan_store(layout, slot)
    if op == "home":
        return plan_home(layout)
    raise SystemExit(f"unknown op {op!r}; use retrieve, store or home")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the STF kernel live in the terminal")
    parser.add_argument("--slot", default="B2", help="target slot (A1..C3)")
    parser.add_argument("--op", default="retrieve", choices=["retrieve", "store", "home"])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--fast", action="store_true", help="run flat out instead of real time")
    parser.add_argument("--fps", type=float, default=20.0, help="screen refresh rate")
    args = parser.parse_args(argv)

    layout = get_layout()
    kernel = Kernel(layout, seed=args.seed)
    trajectory = build_plan(layout, args.op, args.slot)
    kernel.load(trajectory)

    label = f"{args.op}:{args.slot}   plan {trajectory.duration:.1f}s, {len(trajectory)} segments"
    frame_interval = 1.0 / args.fps
    last_draw = 0.0

    print(f"{layout.joint('hbw.travel').drive.max_speed:.2f} mm/s crane - "
          f"{trajectory.describe().splitlines()[0]}", file=sys.stderr)

    try:
        while True:
            step_start = time.perf_counter()
            state = kernel.step()

            now = time.perf_counter()
            if now - last_draw >= frame_interval or not state.busy:
                sys.stdout.write(CLEAR + _render(layout, kernel, label))
                sys.stdout.flush()
                last_draw = now

            if not state.busy:
                print(f"\n{GREEN}done in {state.sim_time:.2f}s{RESET}")
                return 0

            if not args.fast:
                # Pace to the kernel's own timestep so 1 sim-second == 1 real-second.
                elapsed = time.perf_counter() - step_start
                time.sleep(max(0.0, kernel.dt - elapsed))
    except KeyboardInterrupt:
        print(f"\n{DIM}stopped{RESET}")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
