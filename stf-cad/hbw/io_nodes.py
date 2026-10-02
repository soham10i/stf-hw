"""
Upgrade 3 - a remote I/O node on every module (STF_VARIANT=up3).

Each module's adapter PCB stays (it carries the ft motor relays and the
terminal strip every device cable is proven to reach). Its ST3 connector now
lands on a remote I/O node right beside it - a Modbus TCP bus coupler with I/O
slices on a short DIN rail - instead of a 34-way bundle to the cabinet. Only an
Ethernet cable and the 24 V feeds run to the cabinet.

  slices   sized from the module's own I/O list (controller.json, the
           Belegungsplan): DI 8-ch, DO 8-ch, AI 2-ch (the Farbsensor), a
           counter slice per encoder (A/B up to 1 kHz), a field-supply slice
           that takes the actuator 24 V switched by K1/K2 (Upgrade 2)
  spare    >= 20 % of every channel type left free (checked)
  place    searched, not typed: the free spot nearest the module's PCB, fully
           on its own plate, >= 10 mm from every part and every swept hazard
           zone (safety.hazards), outside the VGR arm's swept outline
  proofs   every signal on exactly one channel; spare per type; clearance; and
           - because the nodes join upgrade.factory_parts() - check_cross, the
           VGR tour, the buffer tour and the wiring router all see them

Sizes are 750-series-like and ASSUMED: coupler 51 x 100 x 72, slice
12 x 100 x 68, end module 12 x 100 x 68 (along rail x across x height).
"""
import json
import math
import os
from dataclasses import dataclass

from variant import UP3, UP4, UP5

CH = {"DI": 8, "DO": 8, "AI": 2, "CNT": 1, "IOL": 4}
SPARE_MIN = 0.20
COUPLER = (51.0, 100.0, 72.0)
SLICE = (12.0, 100.0, 68.0)
RAIL_H = 7.5
CLEAR = 10.0
STEP = 5.0
CTL = os.path.expanduser("~/workspace/stf-hw/web/public/controller.json")


@dataclass
class Part:
    name: str
    group: str
    kind: str
    p: tuple
    s: tuple
    colour: str = "grey"
    support: str = "plate"
    frame: str = "world"
    tag: str = ""
    mech: str = ""
    note: str = ""

    def local_aabb(self):
        x, y, z = self.p
        dx, dy, dz = self.s
        return (x, y, z, x + dx, y + dy, z + dz)


def signals(module):
    """The module's I/O by type, from its ST3 terminal list (the Belegungsplan)."""
    st3 = json.load(open(CTL))["modules"][module]["st3"]
    out = {"DI": [], "DO": [], "AI": [], "CNT": []}
    enc = []
    for term, sig in sorted(st3.items(), key=lambda kv: int(kv[0])):
        if sig.startswith("Q"):
            out["DO"].append(sig)
        elif sig.startswith("B"):
            enc.append(sig)
        elif sig == "A4":
            out["AI"].append(sig)                 # the Farbsensor: analogue 0-2 V
        else:
            out["DI"].append(sig)                 # I*, and the HBW's A1/A2 IR trail sensors
    for k in range(0, len(enc), 2):               # B1/B2 = one encoder's A/B channels
        out["CNT"].append("/".join(enc[k:k + 2]))
    if UP4 and module == "hbw":                   # Upgrade 4: the RFID heads (control.py)
        out["IOL"] = ["RF1", "RF2"]
    if UP5:                                       # Upgrade 5: reed, vacuum and pressure switches
        import control
        out["DI"] += sorted(control.U5_SENSORS.get(module, {}), key=lambda x: int(x[1:]))
    return out


def slices(module):
    """[(slice id, type, [signals on its channels])] with >= 20 % spare per type."""
    sig = signals(module)
    out = []
    for t in ("DI", "DO", "AI", "CNT", "IOL"):
        n = len(sig.get(t, ()))
        if n == 0:
            continue
        k = math.ceil(n * (1 + SPARE_MIN) / CH[t])
        for i in range(k):
            chans = sig[t][i * CH[t]:(i + 1) * CH[t]]
            out.append((f"{t}{i + 1}", t, chans + [None] * (CH[t] - len(chans))))
    return out


def node_length(module):
    # coupler + field-supply slice + I/O slices + end module
    return COUPLER[0] + SLICE[0] + len(slices(module)) * SLICE[0] + SLICE[0]


# ------------------------------------------------------------- placement
def _obstacles():
    """Every solid a node could hit, factory frame: all module parts at their
    authoring / parked pose, the PLC cabinet, Upgrade 1's air station and
    buffer, and every swept hazard zone."""
    import factory_layout as FL, hbw_model as HM, oven_model as OM, sorting_model as SM
    import vgr_model as VG, plc_model as PM, upgrade as U, safety as SF
    boxes = []
    for p in HM.build(HM.P["CV_X"], 260.0, 0.0):
        if p.group == "frame":
            continue
        a = p.aabb()
        c0, c1 = FL.to_factory(a[0], a[1]), FL.to_factory(a[3], a[4])
        boxes.append((min(c0[0], c1[0]), min(c0[1], c1[1]), a[2], max(c0[0], c1[0]), max(c0[1], c1[1]), a[5]))
    vx, vy = FL.VGR_AT
    for p in VG.build():
        if p.group == "frame" or p.frame != "world":
            continue
        a = p.local_aabb()
        boxes.append((a[0] + vx, a[1] + vy, a[2], a[3] + vx, a[4] + vy, a[5]))
    for p in OM.build():
        if p.group != "frame":
            boxes.append(FL.oven_box(p.local_aabb()))
    for p in SM.build():
        if p.group == "frame":
            continue
        a = p.local_aabb()
        c0, c1 = FL.to_factory_sort(a[0], a[1]), FL.to_factory_sort(a[3], a[4])
        boxes.append((min(c0[0], c1[0]), min(c0[1], c1[1]), a[2], max(c0[0], c1[0]), max(c0[1], c1[1]), a[5]))
    x, y, w, d = FL.plc_rect()
    boxes.append((x, y, -1, x + w, y + d, 400))
    boxes += [a for _, _, a in U.factory_parts(include_io=False)]
    zones = SF.hazards()
    for h in zones:
        if h["zone"] and not h.get("cyl"):
            boxes.append(tuple(h["zone"]))
    vgr_poly = next(h["cyl"]["poly"] for h in zones if h.get("cyl"))
    return boxes, vgr_poly


def _in_poly(x, y, poly):
    inside = False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


_placed = {}


def place(module):
    """Factory (x0, y0, along) of the node: the free spot nearest the PCB."""
    if module in _placed:
        return _placed[module]
    import factory_layout as FL, wiring as W
    doc_parts = _module_parts(module)
    pcb = next(d for d in doc_parts if "pcb" in d["n"].lower())
    pb = W._box_f(pcb, W._tf(module))
    pc = ((pb[0] + pb[3]) / 2, (pb[1] + pb[4]) / 2)
    rects = {"hbw": FL.module_rect(), "vgr": FL.vgr_rect(), "oven": FL.oven_rect(), "sorting": FL.sort_rect()}
    boxes, poly = _obstacles()
    L, D, H = node_length(module), COUPLER[1], COUPLER[2] + RAIL_H

    def search(area, extra):
        rx, ry, rw, rd = area
        best = None
        for along in ("x", "y"):
            w, d = (L, D) if along == "x" else (D, L)
            x = rx + 5
            while x + w <= rx + rw - 5:
                y = ry + 5
                while y + d <= ry + rd - 5:
                    c = (x + w / 2, y + d / 2)
                    dist = math.hypot(c[0] - pc[0], c[1] - pc[1])
                    if best is None or dist < best[0]:
                        nb = (x - CLEAR, y - CLEAR, 0, x + w + CLEAR, y + d + CLEAR, H + CLEAR)
                        ok = all(min(nb[3], b[3]) - max(nb[0], b[0]) <= 0 or min(nb[4], b[4]) - max(nb[1], b[1]) <= 0
                                 or min(nb[5], b[5]) - max(nb[2], b[2]) <= 0 for b in boxes + extra)
                        if ok:
                            corners = [(x, y), (x + w, y), (x, y + d), (x + w, y + d), c]
                            ok = not any(_in_poly(px, py, poly) for px, py in corners)
                        if ok:
                            best = (dist, (x, y, along))
                    y += STEP
                x += STEP
        return best

    # 1st choice: on the module's own plate
    best = search(rects[module], [])
    where = "own plate"
    if best is None:
        # the VGR's plate lies wholly under its own arm's sweep: then the nearest
        # clear spot on the table that is on no OTHER module's plate
        others = [(r[0], r[1], -1, r[0] + r[2], r[1] + r[3], 1000) for m, r in rects.items() if m != module]
        best = search((0.0, 0.0, FL.PLATE[0], FL.PLATE[1]), others)
        where = "table, off every other plate"
    if best is None:
        raise RuntimeError(f"io_nodes: no free spot for the {module} node")
    _placed[module] = (*best[1], where)
    return _placed[module]


def _module_parts(module):
    """The module's parts as exported dicts (for the PCB position)."""
    import hbw_model as HM, oven_model as OM, sorting_model as SM, vgr_model as VG
    from hbw_frames import by_frame
    src = {"hbw": [p for fr in by_frame().values() for p in fr], "vgr": VG.build(),
           "oven": OM.build(), "sorting": SM.build()}[module]
    out = []
    for p in src:
        out.append({"n": p.name, "k": p.kind, "p": list(p.p),
                    "s": [p.s[0], p.s[1], p.s[2]] if p.kind == "box" else list(p.s)})
    return out


MODULES = ("hbw", "vgr", "oven", "sorting")


def parts(module):
    """The node's parts, factory frame."""
    x0, y0, along, _ = place(module)
    out = []; A = out.append
    L, D = node_length(module), COUPLER[1]

    def box(name, a0, a1, zc, colour, note="", tag=""):
        # a0..a1 along the rail, the full node depth across it
        if along == "x":
            A(Part(name, "io", "box", (x0 + a0, y0, zc[0]), (a1 - a0, D, zc[1] - zc[0]), colour, note=note, tag=tag))
        else:
            A(Part(name, "io", "box", (x0, y0 + a0, zc[0]), (D, a1 - a0, zc[1] - zc[0]), colour, note=note, tag=tag))

    # the rail: a 35 mm strip under the stack, across its middle
    if along == "x":
        A(Part(f"io_{module}_rail", "io", "box", (x0 - 5, y0 + D / 2 - 17.5, 0), (L + 10, 35, RAIL_H), "steel",
               note="TS35 rail under the node"))
    else:
        A(Part(f"io_{module}_rail", "io", "box", (x0 + D / 2 - 17.5, y0 - 5, 0), (35, L + 10, RAIL_H), "steel",
               note="TS35 rail under the node"))
    a = 0.0
    box(f"io_{module}_coupler", a, a + COUPLER[0], (RAIL_H, RAIL_H + COUPLER[2]), "io",
        note="Modbus TCP bus coupler: 2 x RJ45 (the Ethernet line from the cabinet switch), 24 V system supply",
        tag="ETH")
    a += COUPLER[0]
    box(f"io_{module}_supply", a, a + SLICE[0], (RAIL_H, RAIL_H + SLICE[2]), "yellow",
        note="field-supply slice: actuator 24 V from K1/K2 (Upgrade 2) feeds every DO below it")
    a += SLICE[0]
    colours = {"DI": "iodi", "DO": "iodo", "AI": "ioai", "CNT": "iocnt", "IOL": "ioiol"}
    for sid, t, chans in slices(module):
        used = [c for c in chans if c]
        box(f"io_{module}_{sid}", a, a + SLICE[0], (RAIL_H, RAIL_H + SLICE[2]), colours[t],
            note=f"{t} slice, {CH[t]} ch: {', '.join(used) or '-'} ({CH[t] - len(used)} spare)")
        a += SLICE[0]
    box(f"io_{module}_end", a, a + SLICE[0], (RAIL_H, RAIL_H + SLICE[2]), "grey", note="end module")
    return out


def factory_parts():
    if not UP3:
        return []
    return [("io", p, p.local_aabb()) for m in MODULES for p in parts(m)]


def allocation():
    """Every signal -> (module, slice, channel)."""
    rows = []
    for m in MODULES:
        for sid, t, chans in slices(m):
            for k, s in enumerate(chans):
                rows.append({"module": m, "slice": sid, "type": t, "ch": k + 1, "signal": s})
    return rows


def check(verbose=True):
    fails = []
    for m in MODULES:
        sig = signals(m)
        alloc = [r["signal"] for r in allocation() if r["module"] == m and r["signal"]]
        want = [s for t in sig.values() for s in t]
        if sorted(alloc) != sorted(want):
            fails.append(f"ALLOC {m}: {sorted(set(want) ^ set(alloc))} not on exactly one channel")
        for t, lst in sig.items():
            if not lst:
                continue
            cap = sum(CH[t] for _, tt, _ in slices(m) if tt == t)
            if (cap - len(lst)) / cap < SPARE_MIN:
                fails.append(f"SPARE {m} {t}: {len(lst)}/{cap} used, < {SPARE_MIN:.0%} free")
        place(m)                                   # raises if there is no clear spot
    if verbose:
        print(f"io nodes: {len(MODULES)} nodes, {len([r for r in allocation() if r['signal']])} signals allocated")
        print("\n".join(fails) if fails else "ALL CHECKS PASS (every signal on one channel, >= 20 % spare, "
                                             "every node clear of parts, hazard zones and the VGR sweep)")
    return fails


def export():
    return {
        "nodes": {m: {"at": list(place(m)[:2]), "along": place(m)[2], "where": place(m)[3],
                      "length": node_length(m),
                      "slices": [{"id": s, "type": t, "channels": c} for s, t, c in slices(m)]}
                  for m in MODULES},
        "allocation": allocation(),
        "spare_min": SPARE_MIN,
        "sizes": "750-series-like, ASSUMED: coupler 51x100x72, slice 12x100x68",
    }
