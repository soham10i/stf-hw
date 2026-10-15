"""End-to-end cycle test: the full material flow through the Brennofen.

Drives the live runtime headless at 50x and asserts the carrier comes out the
other end baked and delivered, with the oven returned to its receive-ready
state (slider out, door open, lamp off).
"""

from __future__ import annotations

import asyncio

from services.api.runtime import SimRuntime
from stf_layout import load_layout


def test_cycle_phases_include_the_oven() -> None:
    rt = SimRuntime()
    actions = [p.action for p in rt._build_cycle("B2") if p.kind == "oven"]
    assert actions == ["slide_in", "bake", "slide_out"]
    holders = [p.holder for p in rt._build_cycle("B2") if p.kind == "carrier"]
    assert holders[0] == "slot:B2"
    # the carrier must visit the oven between the first grip and delivery
    assert holders.index("oven") > holders.index("suction")
    assert holders[-1] == "delivery"


def test_cycle_bakes_and_delivers() -> None:
    async def run() -> tuple[SimRuntime, dict]:
        rt = SimRuntime(time_scale=50)
        await rt.start()
        rt.submit("cycle", "B2")
        orders: list[dict] = []
        for _ in range(20000):  # generous wall-clock budget at 50x
            await asyncio.sleep(0.02)
            orders = rt.orders()
            if orders and orders[-1]["status"] in ("completed", "failed"):
                break
        await rt.stop()
        return rt, orders[-1]

    rt, order = asyncio.run(run())
    assert order["status"] == "completed", order.get("error")

    frame = rt.latest_frame()
    assert frame["carrier"]["holder"] == "delivery"
    # oven back to receive-ready: slider out, door open, lamp off
    oven = frame["oven"]
    assert oven["slider"] > 0.95
    assert oven["door"] > 0.95
    assert oven["lamp"] is False
    # crane parked at the belt transfer, gripper stowed home
    joints = frame["joints"]
    assert joints["hbw.travel"] == load_layout().joint("hbw.travel").at("rest")
    assert joints["vgr.reach"] == 10.0
    assert joints["vgr.plunge"] == 155.0
