"""Which design variant the models build: "base" (the machine as it is),
"up1" (Upgrade 1, upgrade.py), "up2" (+ machine safety, safety.py) or "up3"
(+ remote I/O, drag chains, cabinet to EN 60204-1, io_nodes.py / chains.py) or
"up4" (+ control program, orchestrator and traceability, control.py) or
"up5" (+ virtual commissioning and the sensors it showed were missing, vc.py),
"up6" (+ condition monitoring and predictive maintenance, health.py) or
"up7" (+ lifecycle: tolerances, access, spares, structure dynamics, lifecycle.py) or
"up10" (+ throughput: split VGR jobs, dual-command crane, blended arm paths, throughput.py) or
"up11" (+ OT security to IEC 62443: zones, conduits, allow-lists, attacks on the twin, security.py) or
"up12" (+ defence in depth: hardwired interlocks, a standstill monitor, the dead wires gone, hardening.py).
Upgrades 8 and 9 are analytics over up7 (ml/, grid.py) and have no variant.
Chosen by the environment so one process builds exactly one consistent
machine - two variants never mix in one export. Levels stack: up3 contains
everything up2 and up1 have."""
import os

VARIANT = os.environ.get("STF_VARIANT", "base")
assert VARIANT in ("base", "up1", "up2", "up3", "up4", "up5", "up6", "up7", "up10", "up11", "up12"), f"unknown STF_VARIANT {VARIANT!r}"
LEVEL = {"base": 0, "up1": 1, "up2": 2, "up3": 3, "up4": 4, "up5": 5, "up6": 6, "up7": 7, "up10": 10, "up11": 11, "up12": 12}[VARIANT]
UP1 = LEVEL >= 1
UP2 = LEVEL >= 2
UP3 = LEVEL >= 3
UP4 = LEVEL >= 4
UP5 = LEVEL >= 5
UP6 = LEVEL >= 6
UP7 = LEVEL >= 7
UP10 = LEVEL >= 10
UP11 = LEVEL >= 11
UP12 = LEVEL >= 12
