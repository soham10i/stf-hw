"""
Upgrade 14, step 3 - the cell's Sparkplug B namespace and its Unified Namespace topics,
generated from the compiled PLC program's I/O image (web/public/sil/plc.json), the same
source as the OPC UA address space (opcua/model.py).

Sparkplug B (Eclipse Sparkplug 3.0, ISO/IEC 20237:2023):
    spBv1.0/STF/{NBIRTH|NDATA|NDEATH|NCMD}/Cell-U12
    spBv1.0/STF/{DBIRTH|DDATA|DDEATH|DCMD}/Cell-U12/{HBW|VGR|Oven|Sorting}
  The edge node (the cell) carries the order, the safety relay, its identity and the two
  Node Control commands; each module is a device with its inputs, outputs, encoders and
  unit sequencers. Every metric has an alias (unique across the node) except
  'Node Control/Rebirth', which the specification forbids to alias.

Unified Namespace (ISA-95 levels, plain JSON, retained):
    stf-hw/virtual-site/bakery/line-1/cell-u12/{node|hbw|vgr|oven|sorting}/<metric path>
  written by the primary host application (uns/host.py) from the Sparkplug data, so a client
  that subscribes late gets the whole current state from the retained messages alone.
"""
import json
from dataclasses import dataclass, field

from sil.stream import PHASES, SIL, state_names

NAMESPACE = "spBv1.0"
GROUP = "STF"
EDGE = "Cell-U12"
HOST_ID = "stf-scada"                                   # the primary host application
UNS_ROOT = "stf-hw/virtual-site/bakery/line-1/cell-u12"
CELL_ASSET = "https://soham10i.github.io/stf-hw/asset/stf-cell-u12"   # the AAS asset id (aas/build.py)

DEVICES = {"hbw": "HBW", "vgr": "VGR", "oven": "Oven", "sorting": "Sorting"}
UNIT_MODULE = {"crane": "hbw", "belt": "hbw", "arm": "vgr", "door": "oven", "sauger": "oven", "turntable": "oven",
               "ovenbelt": "oven", "line": "sorting"}
EU = {"travel": ("mm", 0, 665), "lift": ("mm", 0, 400), "plunge": ("mm", 84, 540), "reach": ("mm", 0, 400),
      "swivel": ("deg", -180, 180)}

# Sparkplug B DataType (sparkplug_b.proto)
INT16, UINT32, UINT64, FLOAT, DOUBLE, BOOLEAN, STRING = 2, 7, 8, 9, 10, 11, 12
REBIRTH, RESTART, BDSEQ = "Node Control/Rebirth", "Node Control/Restart Order", "bdSeq"


@dataclass
class Metric:
    name: str
    dtype: int
    device: str | None                     # None: an edge node metric
    get: object = None                     # stream line -> value (None: set by the edge itself)
    alias: int | None = None
    props: dict = field(default_factory=dict)
    uns: str | None = None                 # the UNS topic (None: not published there)


def topic(kind, device=None, group=GROUP, edge=EDGE):
    return "/".join([NAMESPACE, group, kind, edge] + ([device] if device else []))


def state_topic(host_id=HOST_ID):
    return f"{NAMESPACE}/STATE/{host_id}"


def _uns(device, name):
    return f"{UNS_ROOT}/{(device or 'node').lower()}/" + name.lower().replace(" ", "-")


def catalogue():
    """Every metric of the cell, in birth order, with its alias and how to read it from a stream line."""
    meta = json.load(open(SIL / "plc.json"))
    sil = json.load(open(SIL / "sil.json"))
    io, units, jobs = meta["io"], meta["units"], meta["jobs"]
    names = state_names()
    ms: list[Metric] = []

    # ---- the edge node: identity, the order, the safety relay, the Node Control commands
    ms += [Metric(BDSEQ, UINT64, None), Metric(REBIRTH, BOOLEAN, None, lambda d: False),
           Metric(RESTART, BOOLEAN, None, lambda d: False,
                  props={"description": "write true: the simulated order restarts from power-up"}),
           Metric("Properties/ProductInstanceUri", STRING, None, lambda d: CELL_ASSET,
                  props={"description": "the Asset Administration Shell's asset id (IEC 63278)"}),
           Metric("Properties/SoftwareRevision", STRING, None, lambda d: f"PLC {sil['wasm_sha']}"),
           Metric("Production/Phase", STRING, None, lambda d: PHASES.get(d["phase"], "?")),
           Metric("Production/JobsCompleted", UINT32, None, lambda d: int(d["jobs"])),
           Metric("Production/MachineTime", DOUBLE, None, lambda d: float(d["t"]), props={"engUnit": "s"}),
           Metric("Production/OrderTime", DOUBLE, None, None, props={"engUnit": "s"}),   # the edge keeps the homing time
           Metric("Production/Run", UINT32, None, lambda d: int(d["run"])),
           Metric("Production/State", STRING, None, None,
                  props={"description": "MachineryItemState (OPC 40001-1): Executing, NotExecuting, OutOfService"})]
    for i, e in enumerate(io["ix"]):
        if e["module"] == "cell":
            ms.append(Metric(f"Safety/{e['signal']}", BOOLEAN, None, (lambda i: lambda d: bool(d["ix"][i]))(i),
                             props={"description": e["desc"], "address": e["addr"]}))

    # ---- the modules: one device each
    for mod, dev in DEVICES.items():
        for area, folder in (("ix", "Inputs"), ("qx", "Outputs")):
            for i, e in enumerate(io[area]):
                if e["module"] == mod:
                    ms.append(Metric(f"{folder}/{e['signal']}", BOOLEAN, dev,
                                     (lambda a, i: lambda d: bool(d[a][i]))(area, i),
                                     props={"description": e["desc"], "address": e["addr"]}))
        for i, e in enumerate(io["id"]):
            if UNIT_MODULE[e["unit"]] == mod:
                u, lo, hi = EU[e["axis"]]
                ms.append(Metric(f"Encoders/{e['unit']}/{e['axis']}", FLOAT, dev, (lambda i: lambda d: float(d["id"][i]))(i),
                                 props={"description": e["desc"], "address": e["addr"], "engUnit": u,
                                        "engLow": float(lo), "engHigh": float(hi)}))
        for i, e in enumerate(io["iw"]):
            if e["name"].startswith(mod + "_"):
                tag = e["name"].split("_", 1)[1]
                extra = {"engUnit": "mV", "engLow": 0.0, "engHigh": 2000.0} if tag == "A4" else {}
                ms.append(Metric(f"Inputs/{tag}", INT16, dev, (lambda i: lambda d: int(d["iw"][i]))(i),
                                 props={"description": e["desc"], "address": e["addr"], **extra}))
        for k, u in enumerate(units):
            if UNIT_MODULE[u] != mod:
                continue
            st = (lambda k: lambda d: d["units"][k][0])(k)
            ms += [Metric(f"Units/{u}/State", INT16, dev, lambda d, st=st: int(st(d))),
                   Metric(f"Units/{u}/StateText", STRING, dev,
                          lambda d, st=st, u=u: "ready" if st(d) == 100 else names.get(u, {}).get(st(d), "")),
                   Metric(f"Units/{u}/Job", STRING, dev,
                          (lambda k: lambda d: jobs[d["units"][k][1] - 1] if d["units"][k][1] else "")(k)),
                   Metric(f"Units/{u}/Busy", BOOLEAN, dev, lambda d, st=st: st(d) >= 1000),
                   Metric(f"Units/{u}/Fault", BOOLEAN, dev, lambda d, st=st: st(d) == 910),
                   Metric(f"Units/{u}/Alarm", INT16, dev, (lambda k: lambda d: int(d["units"][k][2]))(k))]

    alias = 1
    for m in ms:
        if m.name != REBIRTH:
            m.alias, alias = alias, alias + 1
        if m.name not in (BDSEQ, REBIRTH, RESTART):
            m.uns = _uns(m.device, m.name)
    return ms


def by_device(ms):
    out: dict[str | None, list[Metric]] = {}
    for m in ms:
        out.setdefault(m.device, []).append(m)
    return out
