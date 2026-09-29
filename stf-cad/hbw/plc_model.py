"""
The PLC cabinet the four 24 V adapter PCBs connect to - on the table corner in
front of the oven, where the 2x layout left room (2026-09-27).

Sizes are from the datasheets in ~/stf/docs/hw where they exist:
  RevPi Core / RevPi DIO  96 x 22.5 x 110.5 mm (H x W x D), EN 50022 DIN rail
                          (Datenblatt_RevPi_Cores.pdf, Datenblatt_RevPi_DIO.pdf)
  Mean Well WDR-120-24    40 x 125.2 x 113.5 mm (W x H x D) - Mean Well catalogue,
                          the WDR sheet in the repo prints no dimensions (assumed)
  RevPi AIO               same housing as the DIO (assumed: no AIO datasheet here)

Why this many modules (536634 p.2 totals): 26 digital + 10 counter inputs = 36,
35 outputs, 1 analogue input. A DIO has 14 in / 14 out, so three DIOs (42 / 42),
and the Farbsensor's analogue A4 needs the AIO.

Module frame: origin at the cabinet plate's corner, factory axes (translated
only). The DIN rail lies ON the table: the modules stand on it with their
connector face UP, the way a cabinet backplate would look laid flat.
"""
from dataclasses import dataclass
from itertools import combinations

from variant import UP2, UP3

C = dict(
    PLATE=(300.0, 380.0, 10.0),
    RAIL=(35.0, 330.0, 7.5),        # TS35 x 7.5, runs along +Y
    RAIL_X=120.0,                   # rail centre line
    REVPI=(96.0, 22.5, 110.5),      # H x W x D laid flat: x = 96, y = 22.5, z = 110.5
    PSU=(125.2, 40.0, 113.5),
    TERMINAL=(60.0, 6.2, 45.0),     # one feed-through terminal (Reihenklemme)
    N_TERMINALS=12,
)
MODULES = ["PSU WDR-120-24", "RevPi Core 3", "RevPi DIO 1", "RevPi DIO 2", "RevPi DIO 3", "RevPi AIO"]


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
        x, y, z = self.p; dx, dy, dz = self.s
        return (x, y, z, x + dx, y + dy, z + dz)


RAIL_SPARE_MIN = 0.20      # EN 60204-1 practice: >= 20 % of every rail left free


def _build_up3():
    """Upgrade 3 cabinet (EN 60204-1). The three DIOs and the AIO leave: the
    module I/O now lives in a remote I/O node on each module (io_nodes.py), so
    the rail carries PSU, controller, an Ethernet switch for the four nodes, a
    4-channel electronic breaker (one fused 24 V feed per module), the feed
    terminals and Upgrade 2's safety relay + contactors. PE is its own busbar;
    power and signal wiring run in separate ducts."""
    q = C; out = []; A = out.append
    A(Part("plc_plate", "frame", "box", (0, 0, -q["PLATE"][2]), q["PLATE"], "slate", "table"))
    rw, _, rh = q["RAIL"]; rx = q["RAIL_X"] - rw / 2
    r0, rl = 15.0, 355.0
    A(Part("din_rail", "rail", "box", (rx, r0, 0), (rw, rl, rh), "steel", "plate",
           note=f"TS35 x 7.5 top-hat rail, {rl:.0f} mm"))
    X = q["RAIL_X"]
    y = r0 + 8.0
    items = [
        ("psu_wdr120", q["PSU"], "grey", "Mean Well WDR-120-24: 24 V / 5 A", 5.0),
        ("revpi_core_3", q["REVPI"], "revpi", "RevPi Core 3 - Modbus TCP master for the four remote I/O nodes", 0.5),
        ("eth_switch", (96.0, 30.0, 95.0), "revpi", "5-port unmanaged industrial Ethernet switch: 4 nodes + controller (assumed size)", 0.5),
        ("ecb_4ch", (96.0, 45.0, 90.0), "grey", "4-channel electronic circuit breaker: one fused, monitored 24 V feed per module (assumed size)", 1.0),
    ]
    for nm, s_, col, note, gap in items:
        A(Part(nm, "cab", "box", (X - s_[0] / 2, y, rh), s_, col, "din_rail", note=note))
        y += s_[1] + gap
    tl, tw, th = q["TERMINAL"]
    for k in range(6):
        A(Part(f"terminal_{k + 1}", "cab", "box", (X - tl / 2, y, rh), (tl, tw, th),
               "blue" if k in (0, 3) else "grey", "din_rail",
               note="feed-through terminal: sensor +24 V / actuator +24 V (via K1/K2) / 0 V"))
        y += tw
    y += 1.5
    for nm, s_, col, note in (
            ("safety_relay_K0", (96.0, 22.5, 110.5), "yellow",
             "safety relay, 2-channel, monitored manual reset, EDM input (Upgrade 2)"),
            ("contactor_K1", (90.0, 22.5, 100.0), "grey", "force-guided contactor K1 (Upgrade 2)"),
            ("contactor_K2", (90.0, 22.5, 100.0), "grey", "force-guided contactor K2 (Upgrade 2)")):
        A(Part(nm, "cab", "box", (X - s_[0] / 2, y, rh), s_, col, "din_rail", note=note))
        y += s_[1] + 1.5
    A(Part("pe_busbar", "pe", "box", (18.0, 30.0, 0), (12.0, 320.0, 12.0), "pe", "plate",
           note="PE busbar, its own bar (EN 60204-1 5.2 / 8.2): every PE conductor lands here, not on the rail"))
    A(Part("duct_power", "duct", "box", (186.0, 15.0, 0), (26.0, 355.0, 60.0), "grey", "plate",
           note="power duct: mains, 24 V feeds, PE - separated from signal wiring (EN 60204-1 13.1)"))
    A(Part("cable_duct", "duct", "box", (224.0, 15.0, 0), (60.0, 355.0, 60.0), "grey", "plate",
           note="signal duct: Ethernet to the four nodes, safety circuit, controller I/O"))
    return out


def rail_fill(parts=None):
    """(used mm, rail mm, fraction free) of the DIN rail."""
    parts = parts or build()
    rail = next(p for p in parts if p.name == "din_rail")
    on = [p for p in parts if p.support == "din_rail"]
    lo = min(p.p[1] for p in on); hi = max(p.p[1] + p.s[1] for p in on)
    used = hi - lo
    return used, rail.s[1], 1.0 - used / rail.s[1]


def build():
    if UP3:
        return _build_up3()
    q = C; out = []; A = out.append
    A(Part("plc_plate", "frame", "box", (0, 0, -q["PLATE"][2]), q["PLATE"], "slate", "table"))
    rw, rl, rh = q["RAIL"]; rx = q["RAIL_X"] - rw / 2
    A(Part("din_rail", "rail", "box", (rx, 25, 0), (rw, rl, rh), "steel", "plate",
           note="TS35 x 7.5 top-hat rail (EN 50022)"))
    y = 35.0
    px, py, pz = q["PSU"]
    A(Part("psu_wdr120", "cab", "box", (q["RAIL_X"] - px / 2, y, rh), (px, py, pz), "grey", "din_rail",
           note="Mean Well WDR-120-24: 24 V / 5 A for the factory's 4.8 A (p.2)"))
    y += py + 5
    for nm in MODULES[1:]:
        hx, wy, dz = q["REVPI"]
        slug = nm.lower().replace(" ", "_")
        A(Part(slug, "cab", "box", (q["RAIL_X"] - hx / 2, y, rh), (hx, wy, dz),
               "revpi", "din_rail", note=f"{nm} - 96 x 22.5 x 110.5 mm (datasheet)"))
        y += wy + 0.5
    y += 8
    tl, tw, th = q["TERMINAL"]
    for k in range(q["N_TERMINALS"]):
        A(Part(f"terminal_{k + 1}", "cab", "box", (q["RAIL_X"] - tl / 2, y + k * tw, rh), (tl, tw, th),
               "grey" if k % 3 else "blue", "din_rail",
               note="feed-through terminal: +24 V / GND distribution to the four adapter PCBs"))
    if UP2:
        # Upgrade 2: the safety chain on the same rail, after the terminals -
        # a dual-channel safety relay and the two force-guided contactors that
        # switch the ACTUATOR 24 V (motors, valves) off; sensors stay powered
        y = y + q["N_TERMINALS"] * tw + 5.5
        for nm, s_, col, note in (
                ("safety_relay_K0", (96.0, 22.5, 110.5), "yellow",
                 "safety relay, 2-channel, monitored manual reset, EDM input - E-stop + guard chain"),
                ("contactor_K1", (90.0, 22.5, 100.0), "grey",
                 "force-guided contactor K1: actuator +24 V, channel 1 (NC mirror contact -> EDM)"),
                ("contactor_K2", (90.0, 22.5, 100.0), "grey",
                 "force-guided contactor K2: actuator +24 V, channel 2, in series with K1")):
            A(Part(nm, "cab", "box", (q["RAIL_X"] - s_[0] / 2, y, rh), s_, col, "din_rail", note=note))
            y += s_[1] + 1.5
    A(Part("cable_duct", "duct", "box", (220, 25, 0), (40, 330, 60), "grey", "plate",
           note="slotted wiring duct: the ribbon cables from the four PCBs arrive here"))
    return out


def check(verbose=True):
    fails = []
    parts = build()
    for a, b in combinations([p for p in parts if p.group != "frame"], 2):
        if {a.group, b.group} in ({"cab", "rail"},) or a.group == b.group == "rail":
            continue
        A_, B_ = a.local_aabb(), b.local_aabb()
        d = [min(A_[i + 3], B_[i + 3]) - max(A_[i], B_[i]) for i in range(3)]
        if min(d) > 0.05:
            fails.append(f"INTERFERENCE {a.name} x {b.name} = {min(d):.1f} mm")
    for p in parts:
        a = p.local_aabb()
        if p.group != "frame" and (a[0] < 0 or a[1] < 0 or a[3] > C["PLATE"][0] or a[4] > C["PLATE"][1]):
            fails.append(f"OFF-PLATE {p.name}")
    if UP3:
        used, rl, free = rail_fill(parts)
        if free < RAIL_SPARE_MIN:
            fails.append(f"RAIL {used:.0f} of {rl:.0f} mm used - only {free:.0%} free, "
                         f"EN 60204-1 practice wants >= {RAIL_SPARE_MIN:.0%}")
    if verbose:
        print(f"parts: {len(parts)}")
        print("\n".join(fails) if fails else "ALL CHECKS PASS (no interference, nothing off the plate)")
    return fails


if __name__ == "__main__":
    import sys
    sys.exit(1 if check() else 0)
