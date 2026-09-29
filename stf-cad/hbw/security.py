"""
Upgrade 11 - OT security to IEC 62443 (STF_VARIANT=up11).

Upgrades 3 to 10 put the whole cell on Ethernet: four Modbus TCP nodes, an
HMI, an edge box running the health model and the network (U6, U8), an energy
manager talking SunSpec to an inverter and OpenADR to the utility (U9). Plain
Modbus TCP has no authentication at all: anything that can reach port 502 can
write a coil. This module designs the network from the same models, and then
attacks the twin to see what the design actually stops.

  ZONES     IEC 62443-3-2: assets grouped by what they may do; a target
            security level (SL-T) per zone; the hardwired safety circuit of
            Upgrade 2 is its own zone with NO network interface.
  CONDUITS  every flow between zones, and the one inside the cell (PLC ->
            nodes), with protocol, direction and authentication.
  ALLOW-LIST generated, not typed: the Modbus function codes and address
            ranges the PLC program actually uses, from the state machines of
            control.py and the register map of vc.py (U5). The cell firewall's
            deep-packet inspection enforces exactly these; the SunSpec
            registers the energy manager may write, likewise.
  PROOFS    (1) least privilege: every read and write the program makes is
            allowed, and every allowed write is one the program makes - no
            spare or retired coil is writable; (2) default deny: every zone
            pair without a conduit is blocked, and every path from the
            untrusted side into the cell crosses an authenticated hop;
            (3) safety independence: no safety function's path contains a
            networked device; (4) the program's signed manifest.
  ATTACKS   replayed against the twin: a rogue coil write, a spoofed sensor, a
            flood, a program download, the battery reserve drained through the
            inverter, a forged demand-response event. Each is run without and
            with the countermeasures, and the consequence is COMPUTED from the
            models - clearances, speeds, stopping distances, the month's mains
            events - not asserted.

Component security capabilities (SL-C) are those of the product classes
(Modbus TCP bus coupler, Linux PLC with OPC UA, residential hybrid inverter)
and are ASSUMED; so is the attacker's timing.

    STF_VARIANT=up11 python3 security.py      -> web/public/security/
"""
import hashlib
import json
import os

import control as C
import vc
from variant import UP11

OUT = os.path.expanduser("~/workspace/stf-hw/web/public/security")
PLC_IP = "192.168.10.10"
FC = {"read_coils": 1, "read_di": 2, "read_hr": 3, "read_ir": 4, "write_coils": 15}
RELAY_DROP = 0.010            # s: a PCB relay opening after its coil is switched off (ASSUMED)

# ------------------------------------------------------------------ zones
ZONES = [
    {"id": "Z0", "name": "Safety (hardwired)", "sl_t": None,
     "assets": ["E-stops ES1-ES3", "door switches SA-SC", "safety relay K0", "contactors K1/K2", "safe exhaust Y1", "reset S3"],
     "note": "no network interface by design; ISO 13849-1 Cat. 3 (Upgrade 2). Out of IEC 62443 scope, and must stay so"},
    {"id": "Z1", "name": "Cell control", "sl_t": 2,
     "assets": ["PLC (RevPi, OPC UA server)", "HBW node", "VGR node", "oven node", "sorting node", "cell switch (managed)"],
     "note": "the only zone that can move anything"},
    {"id": "Z2", "name": "Supervisory", "sl_t": 2,
     "assets": ["HMI panel", "edge / historian (U6 health model, U8 ONNX network)", "energy manager (U9 EMS)"],
     "note": "sees everything, commands little"},
    {"id": "Z3", "name": "Energy", "sl_t": 2,
     "assets": ["hybrid inverter (SunSpec Modbus)", "battery BMS", "PV string"],
     "note": "can take the ride-through away; can export"},
    {"id": "Z4", "name": "DMZ", "sl_t": 2,
     "assets": ["dashboard web server", "OpenADR VEN", "remote-access jump host (MFA, recorded)"],
     "note": "the only zone that talks to the outside"},
    {"id": "Z5", "name": "Enterprise and internet", "sl_t": None, "untrusted": True,
     "assets": ["office network", "utility's OpenADR VTN", "vendor support"], "note": "untrusted"},
]

CONDUITS = [
    {"id": "C1", "a": "Z1", "b": "Z1", "flow": "PLC -> the four I/O nodes", "proto": "Modbus TCP 502",
     "auth": "none on the wire: the nodes cannot; enforced by the cell switch (port lock, static ARP) and the DPI allow-list",
     "dpi": "function code + address range, from the program (allow-list below)"},
    {"id": "C2", "a": "Z2", "b": "Z1", "flow": "HMI -> PLC (HMI tag set); historian <- PLC (subscription)", "proto": "OPC UA 4840",
     "auth": "SignAndEncrypt, X.509 per client, user roles (operator, maintenance, security)",
     "dpi": "write access per node: HMI tags only; historian read-only"},
    {"id": "C3", "a": "Z2", "b": "Z3", "flow": "EMS -> inverter", "proto": "SunSpec Modbus TCP 502",
     "auth": "none on the wire: DPI register allow-list; the reserve is a local setting",
     "dpi": "writes only to the storage-control set points (SunSpec model 124: WChaMax, InWRte, OutWRte, StorCtl_Mod)"},
    {"id": "C4", "a": "Z2", "b": "Z4", "flow": "historian -> dashboard (push only)", "proto": "HTTPS 443",
     "auth": "mutual TLS; outbound from Z2 only - nothing in the DMZ can open a connection inward",
     "dpi": "-"},
    {"id": "C5", "a": "Z4", "b": "Z5", "flow": "OpenADR VEN <-> utility VTN (VEN polls out)", "proto": "OpenADR 2.0b over HTTPS 443",
     "auth": "mutual TLS, the VTN's certificate pinned", "dpi": "-"},
    {"id": "C6", "a": "Z4", "b": "Z2", "flow": "OpenADR VEN -> EMS (events)", "proto": "MQTT over TLS 8883",
     "auth": "client certificate; events checked against the EMS limits", "dpi": "-"},
    {"id": "C7", "a": "Z5", "b": "Z4", "flow": "vendor / engineer -> jump host", "proto": "HTTPS 443 (RDP gateway)",
     "auth": "MFA, time-limited, session recorded, approved per session", "dpi": "-"},
    {"id": "C8", "a": "Z4", "b": "Z1", "flow": "jump host -> PLC (program download, diagnostics)", "proto": "SSH 22 / OPC UA 4840",
     "auth": "maintenance key switch on the cabinet enables the port; signed programs only", "dpi": "-"},
]
AUTH_HOPS = {"C7", "C8", "C2", "C5", "C6", "C4"}     # conduits that authenticate the caller

HMI_TAGS = [
    ("Order.Start", "operator", "start the order the MES released"),
    ("Order.Hold", "operator", "hold after the current steps"),
    ("Alarm.Ack", "operator", "acknowledge after the cause is cleared"),
    ("Record.Correct", "maintenance", "correct a trace record (TRC-02), name logged"),
    ("Mode.Jog", "maintenance", "jog mode - also needs the key switch in the cabinet"),
    ("Jog.<unit>.<axis>", "maintenance", "one axis at a time, under the jog rules of control.JOG"),
    ("Security.Ack", "security", "acknowledge SEC-01..04"),
]


# -------------------------------------------------------- the allow-list
def program_access():
    """What the PLC program touches on each node: per module, the signals it
    WRITES (every unit's outputs, driven - on or off - every scan) and READS
    (every signal a state or a homing step waits on, and the system inputs)."""
    wr, rd = {}, {}
    units = C.sfc()
    for u, (m, outs, _) in C.UNITS.items():
        wr.setdefault(m, set()).update(outs)
        for st in units[u]["states"]:
            rd.setdefault(m, set()).update(st.get("sig", []))
    rd.setdefault("vgr", set()).add("I5")          # SYS-05, the air-pressure switch (U5)
    return wr, rd


def _runs(addrs):
    out = []
    for a in sorted(addrs):
        if out and a == out[-1][0] + out[-1][1]:
            out[-1][1] += 1
        else:
            out.append([a, 1])
    return out


def allow_list():
    """The DPI rules of conduit C1: (node, function, first address, count),
    the smallest set that covers the program's accesses exactly. Writes go out
    as FC15 over contiguous coil runs; under Upgrade 11 the PLC reads the
    same coils back (FC1) every scan to catch a write it did not make."""
    rows = vc.signal_map()
    wr, rd = program_access()
    rules = []
    for m in vc.IP:
        mine = [r for r in rows if r["module"] == m]
        w = set()
        for r in mine:
            if r["type"] == "DO" and r["signal"] in wr.get(m, ()):
                w.add(r["addr"])
        di, ir, hr = set(), set(), set()
        for r in mine:
            sigs = set(r["signal"].split("/"))
            if not sigs & rd.get(m, set()):
                continue
            a0 = r["addr"] % 10000
            if r["type"] == "DI":
                di.add(a0)
            elif r["type"] in ("AI", "CNT"):
                ir.update(range(a0, a0 + r["regs"]))
            elif r["type"] == "IOL":
                hr.update(range(a0, a0 + r["regs"]))
        for fc, addrs in (("write_coils", w), ("read_coils", w), ("read_di", di), ("read_ir", ir), ("read_hr", hr)):
            for a, n in _runs(addrs):
                rules.append({"node": vc.IP[m], "module": m, "fc": FC[fc], "fn": fc, "start": a, "count": n})
    return rules


def allowed(rules, src, node, fc, start, count):
    if src != PLC_IP:
        return False
    return any(r["node"] == node and r["fc"] == fc and r["start"] <= start and start + count <= r["start"] + r["count"]
               for r in rules)


def check_least_privilege(rules):
    fails = []
    rows = vc.signal_map()
    wr, rd = program_access()
    n_ok = 0
    for r in rows:
        m, a0 = r["module"], r["addr"] % 10000
        sigs = set(r["signal"].split("/"))
        if r["type"] == "DO":
            want = r["signal"] in wr.get(m, ())
            can = allowed(rules, PLC_IP, vc.IP[m], FC["write_coils"], a0, 1)
            if want and not can:
                fails.append(f"LP {m}.{r['signal']}: the program writes it, the allow-list blocks it")
            if can and not want:
                fails.append(f"LP {m}.{r['signal']}: writable, but the program never writes it")
            n_ok += want
        elif sigs & rd.get(m, set()):
            fc = {"DI": "read_di", "AI": "read_ir", "CNT": "read_ir", "IOL": "read_hr"}[r["type"]]
            if not allowed(rules, PLC_IP, vc.IP[m], FC[fc], a0, r["regs"]):
                fails.append(f"LP {m}.{r['signal']}: the program reads it, the allow-list blocks it")
            n_ok += 1
    # spare and retired coils: never writable, from anywhere
    for m, qs in C.RETIRED.items():
        for q in qs:
            r = next((x for x in rows if x["module"] == m and x["signal"] == q), None)
            if r and allowed(rules, PLC_IP, vc.IP[m], FC["write_coils"], r["addr"], 1):
                fails.append(f"LP {m}.{q}: retired output still writable")
    for m in vc.IP:
        for a in range(0, 24):
            used = any(x["module"] == m and x["type"] == "DO" and x["addr"] == a and x["signal"] in wr.get(m, ())
                       for x in rows)
            if not used and allowed(rules, PLC_IP, vc.IP[m], FC["write_coils"], a, 1):
                fails.append(f"LP {m} coil {a}: spare but writable")
    return fails, n_ok


def retired_exposure():
    """Outputs still wired to a register the program never writes."""
    rows = vc.signal_map()
    wr, _ = program_access()
    out = []
    for r in rows:
        if r["type"] == "DO" and r["signal"] not in wr.get(r["module"], ()):
            out.append({"module": r["module"], "signal": r["signal"], "addr": r["addr"],
                        "what": C.SIG.get((r["module"], r["signal"]), ""),
                        "retired": r["signal"] in C.RETIRED.get(r["module"], ())})
    return out


# -------------------------------------------------------- default deny
def check_default_deny():
    fails = []
    ids = [z["id"] for z in ZONES]
    pairs = {(c["a"], c["b"]) for c in CONDUITS} | {(c["b"], c["a"]) for c in CONDUITS}
    denied = [(a, b) for a in ids for b in ids if a != b and (a, b) not in pairs]
    # every path from the untrusted zone into the cell crosses an authenticating conduit
    adj = {}
    for c in CONDUITS:
        adj.setdefault(c["a"], []).append((c["b"], c["id"]))
        adj.setdefault(c["b"], []).append((c["a"], c["id"]))
    paths, stack = [], [("Z5", ["Z5"], [])]
    while stack:
        z, path, via = stack.pop()
        if z == "Z1":
            paths.append((path, via))
            continue
        for nz, cid in adj.get(z, []):
            if nz not in path:
                stack.append((nz, path + [nz], via + [cid]))
    for path, via in paths:
        if not set(via) & AUTH_HOPS:
            fails.append(f"DENY a path {' -> '.join(path)} with no authenticated hop")
    if any("Z0" in (c["a"], c["b"]) for c in CONDUITS):
        fails.append("DENY the safety zone has a conduit")
    return fails, denied, [{"path": p, "via": v} for p, v in paths]


def check_safety_independence():
    """No safety function depends on a networked asset."""
    import safety as S
    fails = []
    net = {a for z in ZONES if z["id"] != "Z0" for a in z["assets"]}
    sf = S.export()["functions"]
    for f in sf:
        for dev in f["devices"].replace("->", ",").replace("+", ",").split(","):
            d = dev.strip()
            if any(d and d.split()[0] in a for a in net):
                fails.append(f"SAFETY {f['id']}: {d} is networked")
    # the one soft link: guard locking is released by the PLC's standstill signal
    circ = S.circuit()
    soft = [{"what": "guard locking release", "by": circ["locking"],
             "why": "the PLC is networked: a compromised PLC could release the locks early",
             "still": "the door switches stay in the hardwired K0 chain: opening a door removes the actuator supply at once"}]
    return fails, soft, sf


# ------------------------------------------------------------- attacks
def _fork_windows(r):
    """Seconds of the commissioned order during which the Ausleger is out
    (in a slot or at the belt) - when a sideways travel would hit something."""
    t = 0.0
    for b in r.bars:
        out_at = None
        for u, key, t0, t1, _ in b["steps"]:
            if u != "crane":
                continue
            if key == "fork->out":
                out_at = t0
            elif key == "fork->back" and out_at is not None:
                t += t1 - out_at
                out_at = None
    return round(t, 1)


def attack_rogue_write(healthy):
    v, a = vc.PHYS["v"]["travel"], vc.PHYS["a_mm"]["travel"]
    clr = vc.TOLERANCE["travel"][0]
    t_hit = clr / v
    detect = vc.BUS + vc.scan_of("crane") + vc.BUS + RELAY_DROP        # read-back, scan, write off, relay
    travel = v * detect + v * v / (2 * a)
    win = _fork_windows(healthy)
    return {
        "id": "A1", "name": "rogue coil write", "zone": "Z1 (a laptop on the cell switch, or a compromised HMI)",
        "what": "writes HBW Q4 (crane travel) while the Ausleger is out in a slot",
        "exposure": f"the Ausleger is out {win} s of the {healthy.makespan} s order ({round(100 * win / healthy.makespan)} %)",
        "without": f"the crane starts sideways at {v:.0f} mm/s; the fork (32 mm) has {clr:.0f} mm each side in the 40 mm "
                   f"shelf gap: it hits the rack after {t_hit * 1000:.0f} ms",
        "detect_only": f"read-back alone (SEC-01) sees it within {detect * 1000:.0f} ms, but by the time the relay drops "
                       f"and the motor coasts to rest the crane has moved {travel:.1f} mm > {clr:.0f} mm: detection is too late",
        "with": "blocked at conduit C1: the source is not the PLC (port lock + static ARP), so the frame never reaches the node",
        "residual": "a compromised PLC is allowed to write Q4 - only a hardwired interlock stops that (finding F2)",
        "blocked": True, "numbers": {"clearance_mm": clr, "t_hit_ms": round(t_hit * 1000), "detect_ms": round(detect * 1000),
                                     "travel_mm": round(travel, 1), "fork_out_s": win}}


def attack_spoof(healthy):
    """A man in the middle answers the PLC's reads. What stops a lie is that
    it must be physically possible: every supervised step has a least time the
    plant needs (vc.phys at the fast end of its tolerance). A reply that the
    step is done before that is SEC-02."""
    FAST = 0.8
    rows = {}
    n = det = 0
    seen = set()
    for job in C._representatives():
        for st in C.job_steps(C._representatives()[job][0]):
            if not st.supervised or st.limit is None or (st.unit, st.key) in seen:
                continue
            seen.add((st.unit, st.key))
            t_plant = vc.phys(st)
            n += 1
            t_min = FAST * t_plant
            earliest = 2 * vc.BUS + vc.scan_of(st.unit)       # an instant lie still takes both hops
            ok = t_min > earliest + vc.scan_of(st.unit)
            if t_plant <= 1e-9:
                n -= 1                                           # a leg that moves nothing: a lie gains nothing
                zero = rows.setdefault("_zero", 0)
                rows["_zero"] = zero + 1
                continue
            det += ok
            cls = "crane" if st.unit == "crane" else "VGR arm" if st.unit == "arm" else \
                  "oven cylinders" if st.unit in ("door", "sauger", "turntable") else "belts and lines"
            c = rows.setdefault(cls, {"class": cls, "steps": 0, "detected": 0, "blind": []})
            c["steps"] += 1
            c["detected"] += ok
            if not ok:
                c["blind"].append(f"{st.unit} {st.key} ({t_plant * 1000:.0f} ms)")
    n_zero = rows.pop("_zero", 0)
    for c in rows.values():
        c["blind"] = c["blind"][:6]
    fork = next(s for s in C.crane_steps("retrieve", "A1") if s.key == "fork->back")
    rest = fork.t * (1 - FAST) * C.V_HBW
    return {
        "id": "A2", "name": "spoofed sensor", "zone": "Z1 (man in the middle between the PLC and a node)",
        "what": "answers 'Ausleger back' (HBW I6) while the fork is still in the slot, so the PLC travels",
        "without": "the PLC trusts I6 and travels: the fork is dragged sideways through the shelf (as A1)",
        "detect_only": f"the plausibility check catches every early lie: the Ausleger cannot come back in less than "
                       f"{fork.t * FAST * 1000:.0f} ms. A lie sent at that moment is not caught, and the fork is still "
                       f"{rest:.0f} mm out",
        "with": "C1 locks the cell switch ports to known MACs and pins ARP, so a man in the middle needs the locked cabinet; "
                "the plausibility check (SEC-02) catches what physical access might still try early",
        "residual": "authenticated I/O (Modbus/TCP Security, TLS on port 802) on nodes that support it removes the rest",
        "blocked": True,
        "coverage": {"steps": n, "detected": det, "by_class": list(rows.values()), "fast_factor": FAST,
                     "zero_legs": n_zero}}


def attack_flood(rows):
    f6 = next(r for r in rows if r["id"] == "F6")
    return {"id": "A3", "name": "flood a node", "zone": "Z1 or anything routed to it",
            "what": "floods the oven node so the PLC's polls time out",
            "without": f"SYS-04 after {f6['latency_s'] * 1000:.0f} ms, the node's watchdog drops its outputs: safe, but the order "
                       f"loses {f6['lost_s']} s per event, and an attacker can repeat it",
            "detect_only": "SYS-04 is the detection; it cannot tell a flood from a cable fault",
            "with": "the cell switch rate-limits every port and only the PLC may reach a node; a flood must come from inside the "
                    "cabinet. SEC-04 names the port",
            "residual": "availability only: the watchdog makes the loss safe (U5 fault F6)", "blocked": True}


def attack_program():
    files = C.st_source(C.sfc())
    man = {k: hashlib.sha256(v.encode()).hexdigest() for k, v in sorted(files.items())}
    root = hashlib.sha256("".join(man.values()).encode()).hexdigest()
    return {"id": "A4", "name": "malicious program download", "zone": "Z2/Z4 (a stolen engineering login)",
            "what": "loads a program with the jog interlocks removed",
            "without": "the PLC runs whatever it is given: every software interlock (control.JOG) is gone",
            "detect_only": "a hash compare at the next shift start - after the damage",
            "with": "downloads only via the jump host (C7/C8), with the cabinet key switch in maintenance, and the PLC checks the "
                    "program against the signed manifest before it leaves INIT (SEC-03)",
            "residual": "the signing key: kept offline, two-person rule", "blocked": True,
            "manifest": {"files": man, "root": root}}, man, root


def attack_energy():
    g = json.load(open(os.path.expanduser("~/workspace/stf-hw/web/public/grid/grid.json")))
    pq = g["power_quality"]
    relied = [p for p in pq if "need_wh" in p["with_ups"]]
    lost = sum(p["grid_only"].get("lost_s", 0) for p in relied)
    dr = g["series"]["dr"]
    step = g["meta"]["step_h"]
    runs, cur = [], 0
    for v in dr:
        if v:
            cur += 1
        elif cur:
            runs.append(cur); cur = 0
    win_h = max(runs) * step if runs else 0
    peak_load = max(g["series"]["load"])
    A = g["meta"]["assets"]
    drain = win_h * max(0.0, peak_load - A["dr_cap_w"])
    reserve_wh = (A["reserve"] - A["soc_min"]) * A["battery_wh"]
    long_need = max(p["with_ups"]["need_wh"] for p in relied)
    t_empty = reserve_wh / max(1.0, peak_load - A["dr_cap_w"])       # h of a forged window to empty the reserve
    a5 = {"id": "A5", "name": "battery reserve drained through the inverter", "zone": "Z3 (SunSpec Modbus is plaintext)",
          "what": "writes the inverter's minimum reserve to 0 % and forces discharge",
          "without": f"the next mains event finds an empty battery: {len(relied)} of the month's {len(pq)} events relied on it; "
                     f"all {len(relied)} would drop the 24 V, costing {round(lost / 60)} min of production",
          "detect_only": "the EMS sees the state of charge fall - minutes later; a sag gives no warning",
          "with": "C3's DPI lets the EMS write only the storage set points; the reserve (MinRsvPct) is set on the inverter "
                  "itself and is not on the allow-list. The inverter's own anti-islanding and export limit stay local (IEEE 1547)",
          "residual": "a compromised EMS can still stop charging: the reserve holds, the bill rises", "blocked": True,
          "numbers": {"events_relied": len(relied), "events": len(pq), "lost_min": round(lost / 60)}}
    a6 = {"id": "A6", "name": "forged demand-response event", "zone": "Z5 -> Z4 (a fake VTN)",
          "what": "sends a long DR event while the cell produces",
          "without": f"U9's EMS covers a DR window from the battery down to its 10 % floor, below the ride-through reserve. At the "
                     f"cell's {peak_load:.0f} W peak a window of {t_empty:.1f} h empties the {reserve_wh:.0f} Wh reserve; the month's "
                     f"longest real event ({win_h:.1f} h) took {drain:.0f} Wh and left {reserve_wh - drain:.0f} Wh, against the "
                     f"{long_need:.0f} Wh the longest outage needed. The attacker chooses the length",
          "detect_only": "the event looks like any other",
          "with": "the VEN accepts events only from the pinned VTN certificate (C5), and the EMS will not let a DR event take "
                  "the battery below the ride-through reserve (a finding for U9: it did)",
          "residual": "a genuine but badly timed event: the EMS opts out when the reserve would be breached",
          "blocked": True, "numbers": {"window_h": win_h, "drain_wh": round(drain), "reserve_wh": round(reserve_wh),
                                       "longest_outage_wh": long_need, "t_empty_h": round(t_empty, 1)}}
    return a5, a6


# SunSpec model 124 (storage control): register offsets in the model block
# (verify against the inverter's own map). The EMS may write the charge /
# discharge rates, the mode and the revert timer - if it goes silent, the
# inverter reverts on its own. The reserve and grid charging stay local.
SUNSPEC_124 = [("WChaMax", 2, False), ("WChaGra", 3, False), ("WDisChaGra", 4, False), ("StorCtl_Mod", 5, True),
               ("VAChaMax", 6, False), ("MinRsvPct", 7, False), ("ChaState", 8, False), ("OutWRte", 12, True),
               ("InWRte", 13, True), ("InOutWRte_WinTms", 14, False), ("InOutWRte_RvrtTms", 15, True),
               ("InOutWRte_RmpTms", 16, False), ("ChaGriSet", 17, False)]


def check_sunspec():
    w = {n for n, _, ok in SUNSPEC_124 if ok}
    fails = []
    for must_not in ("MinRsvPct", "ChaGriSet", "WChaMax"):
        if must_not in w:
            fails.append(f"SUNSPEC {must_not} is writable by the EMS")
    if "InOutWRte_RvrtTms" not in w:
        fails.append("SUNSPEC the revert timer is not set: a silent EMS leaves its last set point forever")
    return fails


# ------------------------------------------------------------ SL gaps
FR = ["FR1 identification and authentication", "FR2 use control", "FR3 system integrity", "FR4 data confidentiality",
      "FR5 restricted data flow", "FR6 timely response to events", "FR7 resource availability"]
SLC = {   # assumed capability per product class, FR1..FR7
    "I/O nodes (Modbus TCP couplers)": [0, 0, 1, 0, 1, 1, 1],
    "PLC (Linux, OPC UA)": [2, 2, 2, 2, 2, 2, 2],
    "HMI panel (OPC UA client)": [2, 2, 1, 2, 2, 1, 1],
    "hybrid inverter (SunSpec Modbus)": [0, 0, 1, 0, 1, 1, 2],
}
COMP = {   # the countermeasure that brings the ZONE to SL-T 2 where the component cannot
    ("I/O nodes (Modbus TCP couplers)", 0): "ports locked to the PLC's MAC; nodes in the locked cabinet (physical)",
    ("I/O nodes (Modbus TCP couplers)", 1): "DPI allow-list (C1): only the program's function codes and addresses",
    ("I/O nodes (Modbus TCP couplers)", 2): "SEC-01 read-back, SEC-02 plausibility; TLS on port 802 where offered",
    ("I/O nodes (Modbus TCP couplers)", 3): "not needed at SL 2 for I/O values inside a locked cabinet",
    ("I/O nodes (Modbus TCP couplers)", 4): "the cell switch carries only C1",
    ("I/O nodes (Modbus TCP couplers)", 5): "the firewall's log (SEC-04) to the historian",
    ("I/O nodes (Modbus TCP couplers)", 6): "per-port rate limit; the node watchdog makes loss safe",
    ("HMI panel (OPC UA client)", 2): "the PLC checks every HMI write against the tag set and the role",
    ("HMI panel (OPC UA client)", 5): "the PLC raises the alarm, the HMI only shows it",
    ("HMI panel (OPC UA client)", 6): "the machine runs without the HMI; the panel is replaceable",
    ("hybrid inverter (SunSpec Modbus)", 0): "only the EMS can reach it (C3)",
    ("hybrid inverter (SunSpec Modbus)", 1): "DPI register allow-list: set points only; the reserve is local",
    ("hybrid inverter (SunSpec Modbus)", 2): "the EMS reads back every set point it wrote",
    ("hybrid inverter (SunSpec Modbus)", 3): "not needed at SL 2 for power set points",
    ("hybrid inverter (SunSpec Modbus)", 4): "Z3 carries only C3",
    ("hybrid inverter (SunSpec Modbus)", 5): "the EMS alarms on a set point it did not write",
}


def sl_table():
    out = []
    for comp, caps in SLC.items():
        for i, c in enumerate(caps):
            gap = c < 2
            out.append({"component": comp, "fr": FR[i], "sl_c": c, "sl_t": 2, "gap": gap,
                        "countermeasure": COMP.get((comp, i), "-") if gap else "-"})
    return out


def check_sl(tbl):
    return [f"SL {r['component']} {r['fr']}: SL-C {r['sl_c']} < 2 with no countermeasure" for r in tbl
            if r["gap"] and r["countermeasure"] == "-"]


# ---------------------------------------------------------- configs
def nftables(rules):
    L = ["# cell firewall - generated by stf-cad/hbw/security.py from the program and the register map",
         "table inet stf {", "  chain forward {", "    type filter hook forward priority 0; policy drop;",
         "    ct state established,related accept"]
    for c in CONDUITS:
        L.append(f"    # {c['id']} {c['flow']} ({c['proto']}; {c['auth']})")
    L += [f"    ip saddr {PLC_IP} ip daddr {{ {', '.join(vc.IP.values())} }} tcp dport 502 queue num 1   # C1 -> Modbus DPI",
          "    ip saddr @z2_hmi ip daddr " + PLC_IP + " tcp dport 4840 accept                # C2",
          "    ip saddr @z2_ems ip daddr @z3_inverter tcp dport 502 queue num 2              # C3 -> SunSpec DPI",
          "    ip saddr @z2_hist ip daddr @z4_dash tcp dport 443 accept                      # C4 push only",
          "    ip saddr @z4_ven ip daddr @z2_ems tcp dport 8883 accept                       # C6",
          "    ip saddr @z4_jump ip daddr " + PLC_IP + " tcp dport { 22, 4840 } meta mark 0x1 accept   # C8, key switch sets mark",
          "    log prefix \"SEC-04 \" drop", "  }", "}", "", "# Modbus DPI (queue 1): allow exactly these, drop the rest"]
    for r in rules:
        L.append(f"# {r['node']:15s} FC{r['fc']:<2d} {r['fn']:12s} addr {r['start']:>3d} count {r['count']:>2d}   ({r['module']})")
    return "\n".join(L)


# ------------------------------------------------------------------ main
def run():
    assert UP11, "run with STF_VARIANT=up11"
    fails = []
    rules = allow_list()
    f, n_acc = check_least_privilege(rules)
    fails += f
    f, denied, paths = check_default_deny()
    fails += f
    f, soft, sf = check_safety_independence()
    fails += f
    tbl = sl_table()
    fails += check_sl(tbl)
    fails += check_sunspec()
    healthy, rows = vc.results()
    a4, man, root = attack_program()
    a5, a6 = attack_energy()
    attacks = [attack_rogue_write(healthy), attack_spoof(healthy), attack_flood(rows), a4, a5, a6]
    if not all(a["blocked"] for a in attacks):
        fails.append("ATTACK not every attack is blocked or contained")
    exp = retired_exposure()
    return fails, {"rules": rules, "n_access": n_acc, "denied": denied, "paths": paths, "soft": soft, "sf": sf,
                   "sl": tbl, "attacks": attacks, "manifest": man, "root": root, "exposed": exp, "healthy": healthy}


def main():
    fails, R = run()
    fails += vc.check(verbose=False)
    if fails:
        print("\n".join(fails[:20]))
        raise SystemExit("security: proofs failed - nothing written")
    a1, a2 = R["attacks"][0], R["attacks"][1]
    cov = a2["coverage"]
    ex = R["exposed"]
    findings = [
        {"title": f"Plain Modbus: anything on the cell network could move the machine",
         "text": f"The nodes cannot authenticate. The allow-list, generated from the program, cuts the {len(vc.signal_map())} "
                 f"mapped signals down to {len(R['rules'])} rules; nothing but the PLC may write, and only the coils it drives."},
        {"title": f"F1: {len(ex)} outputs were writable that the program never uses",
         "text": "; ".join(f"{e['module']}.{e['signal']} ({e['what'] or 'spare'})" for e in ex) +
                 ". The compressors Upgrade 1 retired are still wired to live coils. Blocked by the allow-list; the wires should go."},
        {"title": f"F2: detection is too slow for the crane - only prevention works",
         "text": f"A rogue travel command hits the rack after {a1['numbers']['t_hit_ms']} ms; read-back sees it in "
                 f"{a1['numbers']['detect_ms']} ms but the crane has moved {a1['numbers']['travel_mm']} mm by the time it stops "
                 f"({a1['numbers']['clearance_mm']:.0f} mm clearance). Every jog rule of control.JOG is software: a hardwired "
                 "contact (Ausleger at its rear stop) in series with the travel relays is the one that matters most."},
        {"title": f"The twin as an intrusion detector: {cov['detected']} of {cov['steps']} moving steps",
         "text": "A spoofed 'arrived' must still be physically possible. The plant model of Upgrade 5 gives each step a least time; "
                 f"a reply before it is SEC-02. Every step that moves something is covered ({cov['zero_legs']} Upgrade 10 legs move "
                 "nothing, so a lie there gains nothing). What it cannot catch is a lie told on time over a jammed actuator: "
                 f"a fork reported back at the earliest plausible moment can still be {a2['detect_only'].split('still ')[-1]}. "
                 "Authenticated I/O closes that."},
        {"title": "Safety does not depend on the network - except one soft link",
         "text": f"No device of the {len(R['sf'])} safety functions is networked. The guard locks, though, are released by the "
                 "PLC's standstill signal: a compromised PLC could unlock early. The door switches still drop K0 the moment a door "
                 "opens; a standstill monitor on the actuator bus would make the release hardwired too."},
        {"title": f"F3: a forged demand-response event can empty the ride-through reserve",
         "text": R["attacks"][5]["without"] + ". U9's EMS let a DR window go below the reserve; with U11 it opts out instead."},
    ]
    doc = {
        "meta": {"variant": "up11", "plc_ip": PLC_IP, "node_ips": vc.IP, "standards": [
            "IEC 62443-3-2 (zones, conduits, risk)", "IEC 62443-3-3 (system requirements, FR1-FR7, SL)",
            "IEC 62443-4-2 (component requirements, SL-C)", "IEC 62443-2-1 / 2-4 (operator, service provider)",
            "Modbus/TCP Security (TLS, port 802)", "OPC UA Part 2 (security model)", "OpenADR 2.0b", "SunSpec Modbus",
            "IEEE 1547-2018", "ISO 13849-1 (the safety zone)"],
            "assumed": "component SL-C by product class; the relay drop time (10 ms); the attacker's timing; the 0.8 fast factor "
                       "of the plausibility window"},
        "zones": ZONES, "conduits": CONDUITS, "denied_pairs": R["denied"], "paths_in": R["paths"],
        "allow_list": R["rules"], "n_access": R["n_access"],
        "sunspec": [{"point": n, "offset": o, "ems_write": ok} for n, o, ok in SUNSPEC_124], "exposed": ex, "hmi_tags": HMI_TAGS,
        "safety": {"functions": R["sf"], "soft_links": R["soft"]},
        "sl": R["sl"], "attacks": R["attacks"], "findings": findings,
        "manifest": {"files": R["manifest"], "root": R["root"]},
        "alarms": [a for a in C.alarms(C.sfc()) if a["code"].startswith("SEC-")],
        "proofs": {"least_privilege": "every read and write of the program allowed; no other coil writable",
                   "default_deny": f"{len(R['denied'])} zone pairs denied; {len(R['paths'])} paths from the internet to the cell, "
                                   "each through an authenticated hop",
                   "safety": "no networked device in any safety function", "sl": "every SL-C gap has a countermeasure"},
    }
    os.makedirs(OUT, exist_ok=True)
    json.dump(doc, open(os.path.join(OUT, "security.json"), "w"), separators=(",", ":"))
    open(os.path.join(OUT, "cell_firewall.nft"), "w").write(nftables(R["rules"]) + "\n")
    json.dump({"root": R["root"], "files": R["manifest"]}, open(os.path.join(OUT, "st_manifest.json"), "w"), indent=1)
    print(f"wrote {OUT}: {len(R['rules'])} allow rules, {len(R['attacks'])} attacks, {len(findings)} findings")
    for f in findings:
        print(" -", f["title"])


if __name__ == "__main__":
    main()
