"""
STF-2 controls: the Beckhoff EtherCAT I/O, derived from line_model (never typed).

  io_list()        every signal: the model's tags + the I/O a bought part implies
                   (heated heads have a thermocouple, an ejector has a valve and a
                   vacuum switch, every axis needs a home switch). Implied points that
                   have no solid in the CAD yet are flagged `cad=False`.
  terminals()      EL terminals per signal kind, sized for >= 20 % spare channels;
                   E-bus current summed along each rail, EL9410 refresh where needed
  power()          24 V logic, 24 V heater, 48 V motor and 230 V heater budgets
                   (<= 80 % of every supply / breaker), DO channel currents
  cabinet()        DIN rail rows in the enclosure under the deck: widths with >= 20 %
                   rail spare, row pitch + ducts inside the plate, device depth inside
                   the enclosure height -> CAB is proven, not guessed
  wiring()         terminal-level wiring table: device -> cable -> EL terminal point,
                   cable length from the layout, voltage drop on every DC supply cable
  twincat()        TwinCAT 3 Structured Text skeletons: GVL with every I/O mapped,
                   master axis, band + depositor geared to it, delta C transfer,
                   oven PID, QC/kicker, delta tracking, lanes/stacker/shuttle, AMR ports

Run: python3 plc_io.py   -> plc/io_list.csv, plc/wiring.csv, plc/cabinet.json, plc/*.st
Refuses to write if any proof fails. NOT compiled in TwinCAT here - skeletons to be
imported into a TwinCAT 3 project; the NC kinematic / conveyor-tracking functions need
the licence level confirmed with Beckhoff (TF5110-TF5113 class).
"""
import csv
import json
import math
import os
import sys
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hardware as H
import line_model as M

L = M.L
OUT = os.path.join(HERE, "plc")
SPARE_MIN = 0.20            # >= 20 % spare channels per signal kind, and rail length
KIND_TERMINAL = OrderedDict([          # signal kind -> terminal type
    ("DI", "EL1809"), ("DO", "EL2809"), ("AI", "EL3064"), ("TC", "EL3314"), ("IOL", "EL6224"),
    ("ENC", "EL5101"), ("STEP", "EL7047"), ("DITS", "EL1252"), ("DOTS", "EL2252"),
    ("SI", "EL1904"), ("SO", "EL2904"),              # TwinSAFE (Upgrade S-1)
])
SAFE_KINDS = ("SI", "SO")
LOGIC_PSU = ["SDR-120-24"]                       # chosen by power(): the smallest SDR 24 V that keeps <= 80 %
TIMESTAMPED = ("I8", "I9")       # position latches: a 3 ms filtered EL1809 cannot latch the master position


@dataclass
class IO:
    tag: str                 # plant tag (from the model where it exists)
    kind: str                # DI DO AI TC IOL ENC STEP ETH
    part: str                # model part it belongs to ('' = none in the CAD yet)
    module: str
    desc: str
    hw: str
    load_A: float = 0.0      # current drawn from its channel (DO) or supply (sensors)
    supply: str = "24V"      # 24V logic / 24V heat / 48V / 230V
    cad: bool = True         # has a solid in the model
    pos: tuple = (0.0, 0.0, 0.0)
    extra: dict = field(default_factory=dict)
    slot: str = ""           # assigned terminal: -KFn chX


def _centre(p):
    b = p.aabb()
    return tuple((b[i] + b[i + 3]) / 2 for i in range(3))


def _oven_tables():
    """(elements by tag, phase by tag) of the CURRENT model - not frozen at import (verify_plan perturbs L)."""
    _, els, plan, _ = M.oven_power()
    return {e["tag"]: e for e in els}, {tag: ph for ph, items in plan.items() for tag, _ in items}


def io_list():
    ELEM, PHASE = _oven_tables()
    parts = M.build(with_product=False)
    by = {p.name: p for p in parts}
    out = []
    seen = set()

    def add(io):
        out.append(io)

    for p in parts:
        if not p.tag or p.group in ("puck",):
            continue
        t, hw = p.tag, p.hw
        c = _centre(p)
        if hw.startswith("ISO6432"):
            if t in seen:                               # e.g. a fork pair on one valve
                continue
            seen.add(t)
            add(IO(t, "DO", p.name, p.module, f"valve coil ({hw.split(' ')[0]})", "SY3000 coil",
                   H.LOADS["valve_coil"]["I"], pos=c))
            if L.get("PA1"):                            # PA-1: every stroke is observed (timing, wear, did it act)
                for end in ("S1", "S2"):
                    add(IO(f"{t}.{end}", "DI", p.name, p.module,
                           f"reed switch {'retracted' if end == 'S1' else 'extended'} ({hw.split(' ')[0]})", "reed",
                           H.FIELD["reed"]["I"], pos=c))
        elif "17HS" in hw:
            motor = next(k for k in H.STEPPER if k in hw)
            add(IO(t, "STEP", p.name, p.module, f"stepper {hw}", motor, supply="48V", pos=c,
                   extra=dict(motor=motor, encoder="E1000" in hw)))
        elif hw in ("diffuse_M12", "reed"):
            add(IO(t, "DITS" if t in TIMESTAMPED else "DI", p.name, p.module, p.note[:60] or hw, hw,
                   H.FIELD[hw]["I"], pos=c))
        elif hw == "ir_pyrometer":
            add(IO(t, "AI", p.name, p.module, "product temperature 0..10 V", hw, H.FIELD[hw]["I"], pos=c))
        elif hw == "tof_level":
            add(IO(t, "IOL", p.name, p.module, "ToF level (IO-Link)", hw, H.FIELD[hw]["I"], pos=c))
        elif hw == "nfc_head":
            add(IO(t, "IOL", p.name, p.module, "RFID/NFC head (IO-Link)", hw, H.FIELD[hw]["I"], pos=c))
        elif hw == "encoder_wheel":
            add(IO(t, "ENC", p.name, p.module, "master encoder, 1024 ppr RS422", hw, H.FIELD[hw]["I"], pos=c))
        elif hw == "colour_sensor":
            for ch in "RGB":
                add(IO(f"{t}.{ch}", "AI", p.name, p.module, f"colour {ch} 0..10 V", hw,
                       H.FIELD[hw]["I"] / 3, pos=c))
        elif hw == "tc_K":
            add(IO(t, "TC", p.name, p.module, "oven zone thermocouple K (duplex: this element -> PID)", hw, pos=c,
                   extra=dict(zone=f"Z{t[-1]}")))
        elif hw == "tubular":
            e = ELEM[t]
            add(IO(t, "DO", p.name, p.module, f"oven element SSR ({e['P']:.0f} W 230 V, {PHASE[t]})", "SSR_AC25",
                   H.SSR_AC25["ctl_A"], pos=c, extra=dict(mains_W=e["P"], zone=e["zone"], phase=PHASE[t], face=e["face"])))
        elif hw == "OVEN_FAN":
            add(IO(t, "DO", p.name, p.module, f"oven circulation fan 230 V {H.OVEN_FAN['P']:g} W ({PHASE[t]}), "
                   "coupling relay", "RELAY6", H.RELAY6["ctl_A"], pos=c,
                   extra=dict(mains_W=H.OVEN_FAN["P"], zone=f"Z{t[-1]}", phase=PHASE[t], fan=True)))
        elif hw == "COOL_FAN":
            add(IO(t, "DO", p.name, p.module, "band cooling fan 24 V", hw, H.COOL_FAN["I"], pos=c))
        elif hw == "exhaust_fan":
            add(IO(t, "DO", p.name, p.module, "oven vapour exhaust fan 24 V EC", hw, H.LOADS["exhaust_fan"]["I"], pos=c))
        elif hw == "ringlight":
            add(IO(t, "DO", p.name, p.module, "ring light 24 V", hw, H.LOADS["ringlight"]["I"], pos=c))
        elif hw == "sealer_head":
            add(IO(t, "DO", p.name, p.module, "sealing head DC SSR (24 V 60 W)", "SSR_DC", H.SSR_DC["ctl_A"], pos=c,
                   extra=dict(heat_A=H.LOADS["sealer_head"]["I"])))
            add(IO(f"{t}.TC", "TC", p.name, p.module, "sealing head thermocouple (integrated)", "tc_K", pos=c))
        elif "FRL" in hw:
            if L.get("SAFE1"):                          # S-1: a TwinSAFE output, monitored (SF3)
                add(IO(t, "SO", p.name, p.module, "soft-start / dump valve: safe exhaust of all air (SF3)", hw,
                       H.LOADS["valve_coil"]["I"] * 2, pos=c, extra=dict(sf="SF1 SF2 SF3")))
                add(IO(f"{t}.FB", "SI", p.name, p.module, "dump valve position switch (exhausted)", hw,
                       H.FIELD["reed"]["I"], pos=c, extra=dict(sf="SF3")))
            else:
                add(IO(t, "DO", p.name, p.module, "soft-start / dump valve (safe exhaust)", hw,
                       H.LOADS["valve_coil"]["I"] * 2, pos=c, extra=dict(safety=True)))
        elif "cup" in hw:
            add(IO(f"{t}", "DO", p.name, p.module, "vacuum ejector valve", "SY3000 coil",
                   H.LOADS["valve_coil"]["I"], pos=c))
            if L.get("PA1"):
                add(IO(f"{t}.P", "IOL", p.name, p.module, "vacuum level (analogue grip quality)", "vac_iol",
                       H.FIELD["vac_iol"]["I"], pos=c))
            else:
                add(IO(f"{t}.OK", "DI", p.name, p.module, "vacuum switch: part gripped", "vac_switch",
                       H.FIELD["vac_switch"]["I"], pos=c))
        elif "camera" in hw:
            add(IO(t, "ETH", p.name, p.module, "GigE camera -> edge PC", hw, pos=c))
            if L.get("PA1"):                            # hardware trigger at a master-axis position, DC-stamped
                add(IO(f"{t}.TRG", "DOTS", p.name, p.module, "camera trigger (timestamped)", "trigger", 0.01, pos=c))
    # home switches every axis needs (not drawn yet)
    homes = [(f"B{10 + i}", f"M_shuttle_{f}", f"shuttle {f} home") for i, f in enumerate(M.FLAV)] + \
        [(f"B{20 + k}", n.name, f"{n.name} arm index") for k, n in
         enumerate(p for p in parts if "_motor_" in p.name and p.group.startswith("delta_"))]
    for tag, pn, d in homes:
        add(IO(tag, "DI", pn, by[pn].module, d, "diffuse_M12", H.FIELD["diffuse_M12"]["I"], cad=False,
               pos=_centre(by[pn])))
    # heater break (V-1): one current transducer per phase of the oven element feed, in the cabinet
    for ph in sorted({PHASE[t] for t in ELEM}):
        add(IO(f"BC{ph[-1]}", "AI", "", "M3_oven", f"oven element feed {ph} current 0..{H.CT_AC['range']:g} A (heater break)",
               "CT_AC", H.CT_AC["I"], cad=False, pos=_centre(by["cabinet_floor"]), extra=dict(feed_phase=ph, cabinet=True)))
    if L.get("SAFE1"):
        _safety_io(parts, by, out, add)
    else:
        # pre-S-1: a safety relay placeholder
        add(IO("S0", "DI", "", "M8_control", "E-stop chain OK (safety relay output)", "PNOZ", 0.0, cad=False,
               pos=_centre(by["cabinet_floor"])))
        add(IO("S1", "DI", "", "M8_control", "safety relay reset / feedback", "PNOZ", 0.0, cad=False,
               pos=_centre(by["cabinet_floor"])))
    return out


def heaters(ios):
    """Every heated unit with its own safety temperature limiter (SF4): an oven ZONE (carried by its TC; its
    elements are fed through the zone contactor KHn whose coil runs through the STB contact) or a 24 V
    sealing head (the STB contact in its load path)."""
    out = []
    for io in ios:
        if io.kind == "TC" and io.extra.get("zone"):
            io.extra["zone_W"] = sum(e.extra["mains_W"] for e in ios if e.extra.get("zone") == io.extra["zone"]
                                     and e.extra.get("mains_W") and not e.extra.get("fan"))
            out.append(io)
        elif io.kind == "DO" and io.extra.get("heat_A"):
            out.append(io)
    return out


def oven_zones(ios):
    """[(zone, TC io, [element ios], fan io)] in zone order."""
    out = []
    for io in sorted((i for i in ios if i.kind == "TC" and i.extra.get("zone")), key=lambda i: i.extra["zone"]):
        z = io.extra["zone"]
        els = [e for e in ios if e.extra.get("zone") == z and e.extra.get("mains_W") and not e.extra.get("fan")]
        fan = next((e for e in ios if e.extra.get("zone") == z and e.extra.get("fan")), None)
        out.append((z, io, els, fan))
    return out


def zones(parts=None):
    """Port zones: {port: dict(motors=[tags], valves=[tags])} from L['PORT_ZONE'] part groups."""
    parts = parts if parts is not None else M.build(with_product=False)
    out = {}
    for port, groups in L["PORT_ZONE"].items():
        mot = sorted({p.tag for p in parts if p.group in groups and "17HS" in p.hw and p.tag})
        val = sorted({p.tag for p in parts if p.group in groups and p.tag
                      and (p.hw.startswith("ISO6432") or p.hw == "trapdoor unit")})
        out[port] = dict(motors=mot, valves=val)
    return out


BASE_CONTACTORS = (      # tag, what it switches, safety functions
    ("K1", "48 V motor supply, channel 1 (all EL7047)", "SF1 SF2 SF6"),
    ("K2", "48 V motor supply, channel 2 (in series with K1)", "SF1 SF2 SF6"),
    ("K3", "400 V oven feed + 24 V heater PSU, channel 1 (3-pole)", "SF1"),
    ("K4", "400 V oven feed + 24 V heater PSU, channel 2 (in series with K3)", "SF1"),
)


def contactors():
    """K1..K4 + one zone contactor per AMR port whose zone has motors (in port order)."""
    out = list(BASE_CONTACTORS)
    for port, z in zones().items():
        if z["motors"]:
            out.append((f"K{len(out) + 1}", f"48 V branch of the {port}-port zone ({', '.join(z['motors'])})", "SF6"))
    return tuple(out)


def zone_valves():
    """(tag, port) of the safe exhaust valve of every port zone that has pneumatics."""
    out = []
    for port, z in zones().items():
        if z["valves"]:
            out.append((f"Y{len(out) + 1}", port))
    return out


def _safety_io(parts, by, ios, add):
    """Upgrade S-1 TwinSAFE I/O: operator devices, guard locking, light curtains + muting, contactors
    with mirror-contact monitoring (EDM), zone exhaust valves, the reject drawer, STL trip feedback."""
    cab = _centre(by["cabinet_floor"])
    S = H.SAFE
    for p in parts:
        t, hw = p.tag, p.hw
        if not t:
            continue
        c = _centre(p)
        if hw == "estop":
            for ch in "AB":
                add(IO(f"{t}.{ch}", "SI", p.name, p.module, f"E-stop NC contact {ch} (SF1, 2-channel)", hw,
                       pos=c, extra=dict(sf="SF1")))
        elif hw == "reset":
            add(IO(t, "SI", p.name, p.module, "reset pushbutton (manual reset on the falling edge)", hw,
                   S["reset"]["I"], pos=c, extra=dict(sf="SF1 SF2 SF6")))
        elif hw == "guard_lock":
            for ch in "AB":
                add(IO(f"{t}.{ch}", "SI", p.name, p.module, f"door closed AND locked, OSSD {ch} (SF2)", hw,
                       S["guard_lock"]["I"] / 2, pos=c, extra=dict(sf="SF2")))
            add(IO(f"{t}.UNL", "SO", p.name, p.module, "unlock solenoid (power-to-unlock, only at standstill)", hw,
                   S["guard_lock"]["I_lock"], pos=c, extra=dict(sf="SF2")))
        elif hw == "airlock_door":
            port = {"S30": "boxes", "S31": "out", "S32": "out"}[t]
            what = "inner" if t == "S32" else "outer"
            for ch in "AB":
                add(IO(f"{t}.{ch}", "SI", p.name, p.module, f"{port} airlock {what} door closed AND locked, OSSD {ch}",
                       hw, S["airlock_door"]["I"] / 2, pos=c, extra=dict(sf="SF6", port=port)))
            add(IO(f"{t}.UNL", "SO", p.name, p.module, f"{port} airlock {what} door lock release (interlocked)", hw,
                   S["airlock_door"]["I_lock"], pos=c, extra=dict(sf="SF6", port=port)))
            add(IO(f"{t}.DRV", "DO", p.name, p.module, f"{port} airlock {what} door drive valve (force-limited)",
                   "SY3000 coil", H.LOADS["valve_coil"]["I"], pos=c))
        elif hw == "trapdoor unit":           # safety sensor: the boxes airlock's inner side is SF6 (PLr c)
            for ch in "AB":
                add(IO(f"{t}.CL{ch}", "SI", p.name, p.module, f"trapdoor closed, safety sensor OSSD {ch}", "trapdoor",
                       S["trapdoor"]["I"] / 2, pos=c, extra=dict(sf="SF6", port="boxes")))
            add(IO(t, "DO", p.name, p.module, "trapdoor valve (spring-return closes on exhaust)", "SY3000 coil",
                   H.LOADS["valve_coil"]["I"], pos=c))
        elif hw == "light_curtain":
            port = p.name.split("_")[1]
            plate = by["port_boxes" if port == "boxes" else "port_out"]
            for ch in "AB":
                add(IO(f"{t}.{ch}", "SI", p.name, p.module, f"light curtain OSSD {ch} ({port} port, SF6)", hw,
                       S["light_curtain"]["I"] / 2, pos=c, extra=dict(sf="SF6", port=port)))
            for k in (1, 2):
                add(IO(f"{t}.MUT{k}", "SI", plate.name, plate.module, f"muting sensor {k}: AMR docked at {port}",
                       "muting", S["muting"]["I"], cad=False, pos=_centre(plate), extra=dict(sf="SF6", port=port)))
    if L.get("AIRLOCK"):                             # AMR dock sensors: standard inputs (the doors are the safety)
        for port, plate in (("boxes", "port_boxes"), ("out", "port_out")):
            for k in (1, 2):
                add(IO(f"{port.upper()}.DOCK{k}", "DI", plate, by[plate].module, f"AMR docked at {port} ({k})", "dock",
                       S["dock"]["I"], cad=False, pos=_centre(by[plate])))
    bin_ = by["reject_bin_wall_front"]
    for ch in "AB":
        add(IO(f"S34.{ch}", "SI", bin_.name, bin_.module, f"reject drawer in place, OSSD {ch}", "drawer_switch",
               S["drawer_switch"]["I"] / 2, cad=False, pos=_centre(bin_), extra=dict(sf="SF6")))
    for tag, what, sf in contactors():
        add(IO(tag, "SO", "", "M8_control", f"contactor coil: {what}", "contactor", S["contactor"]["coil_A"],
               cad=False, pos=cab, extra=dict(sf=sf, cabinet=True)))       # DIN device: the cabinet's
                                                                                  # contents are not drawn
    edms = [("K1K2.EDM", "K1 + K2 mirror contacts in series"), ("K3K4.EDM", "K3 + K4 mirror contacts")] + \
        [(f"{tag}.EDM", f"{tag} mirror contact") for tag, _, _ in contactors()[4:]]
    for edm, what in edms:
        add(IO(edm, "SI", "", "M8_control", f"EDM: {what} (welded contact detection)", "contactor", 0.005,
               cad=False, pos=cab, extra=dict(sf="SF1 SF2 SF6", cabinet=True)))
    isl = by["valve_island"]
    for tag, port in zone_valves():
        add(IO(tag, "SO", isl.name, isl.module, f"safe exhaust of the {port}-port pressure zone (SF6)",
               "zone_valve", S["zone_valve"]["I"], pos=_centre(isl), extra=dict(sf="SF6", port=port)))
        add(IO(f"{tag}.FB", "SI", isl.name, isl.module, f"{port} zone valve position switch (exhausted)",
               "zone_valve", H.FIELD["reed"]["I"], pos=_centre(isl), extra=dict(sf="SF6", port=port)))
    for io in heaters(ios):
        how = f"its contact is in the coil of zone contactor KH{io.tag[-1]}" if io.extra.get("zone") else \
            "its relay contact is in the heater load path"
        add(IO(f"{io.tag}.STL", "DI", io.part, io.module, "safety temperature limiter tripped (SF4, own element "
               f"of a duplex thermocouple; {how})", "stl",
               S["stl"]["P"] / 24.0, pos=io.pos, extra=dict(sf="SF4", stl=True, cabinet=True)))


# ------------------------------------------------------------ terminals
def terminals(ios):
    """Terminals per kind with >= 20 % spare; assign channels. Returns (rails, rows, fails)."""
    fails, rows = [], []
    by_kind = defaultdict(list)
    for io in ios:
        by_kind[io.kind].append(io)
    rail1 = [("CX2100-0004", "-TB0", "CX power supply / E-bus"), ("CX2020", "-KF0", "embedded PC")]
    rail2 = [("EK1100", "-KF100", "EtherCAT coupler (motor rail)")]
    rail3 = [("EK1100", "-KF200", "EtherCAT coupler (TwinSAFE rail)"), ("EL6910", "-KF201", "TwinSAFE logic")] \
        if any(io.kind in SAFE_KINDS for io in ios) else []
    n_kf = 1
    for kind, term in KIND_TERMINAL.items():
        sig = sorted(by_kind.get(kind, []), key=lambda i: (i.module, i.tag))
        if not sig:
            continue
        ch = H.BECKHOFF[term]["ch"]
        need = len(sig)
        n = max(1, math.ceil(need / (1 - SPARE_MIN) / ch - 1e-9))   # >= 20 % of the INSTALLED channels free
        spare = (n * ch - need) / (n * ch)
        ok = spare >= SPARE_MIN - 1e-9
        rows.append((kind, term, need, n, n * ch, spare, ok))
        if not ok:
            fails.append(f"SPARE {kind}: {spare:.0%} < {SPARE_MIN:.0%}")
        for k in range(n):
            name = f"-KF{n_kf}"
            (rail2 if kind == "STEP" else rail3 if kind in SAFE_KINDS else rail1).append(
                (term, name, f"{kind} {k + 1}/{n}"))
            for c in range(ch):
                idx = k * ch + c
                if idx < need:
                    sig[idx].slot = f"{name} ch{c + 1}"
            n_kf += 1
    # E-bus: sum along each rail, a refresh terminal (EL9410) when the budget runs out
    out = []
    for rail in [r for r in (rail1, rail2, rail3) if r]:
        avail = -H.BECKHOFF[rail[0][0]]["ebus"] if H.BECKHOFF[rail[0][0]]["ebus"] < 0 else 0
        seq = [rail[0]]
        for item in rail[1:]:
            draw = H.BECKHOFF[item[0]]["ebus"]
            if draw > avail:
                seq.append(("EL9410", f"-TB{len(out) + 10}{len(seq)}", "E-bus refresh 2 A"))
                avail = 2000
            avail -= draw
            seq.append(item)
        seq.append(("EL9011", "", "end cap"))
        out.append(seq)
        if avail < 0:
            fails.append("EBUS budget exceeded")
    for seq in out:
        load = 0
        cap = 0
        for t, n, _ in seq:
            e = H.BECKHOFF[t]["ebus"]
            if e < 0:
                cap, load = -e, 0
            else:
                load += e
                if load > cap:
                    fails.append(f"EBUS {n}: {load} mA > {cap} mA")
    return out, rows, fails


# ------------------------------------------------------------ power
def power(ios):
    rows, fails = [], []

    def row(name, value, limit, ok, note):
        rows.append((name, value, limit, ok, note))
        if not ok:
            fails.append(f"POWER {name}: {value} vs {limit} - {note}")

    # DO channel currents
    for io in ios:
        if io.kind in ("DO", "DOTS") and io.load_A > H.BECKHOFF["EL2809"]["I_ch"]:
            fails.append(f"DO {io.tag} draws {io.load_A} A > EL2809 0.5 A")
    worst = max(io.load_A for io in ios if io.kind == "DO")
    row("DO channel current (worst)", f"{worst:.2f} A", "<= EL2809 0.5 A", worst <= 0.5, "heaters via SSRs")
    so = [io for io in ios if io.kind == "SO"]
    if so:
        w_so = max(so, key=lambda io: io.load_A)
        lim = H.BECKHOFF["EL2904"]["I_ch"]
        row("safe output current (worst)", f"{w_so.load_A:.2f} A ({w_so.tag})", f"<= EL2904 {lim:g} A",
            w_so.load_A <= lim, "contactor coils, unlock solenoids, zone valves driven directly")
    # 24 V logic
    n_term = sum(1 for io in ios) / 8
    logic = sum(io.load_A for io in ios if io.kind in ("DI", "DO", "AI", "IOL", "ENC", "DITS", "DOTS", "SI", "SO")) \
        + (H.CX_POWER["CX2020"] + H.CX_POWER["EK1100"] * (2 if so else 1) + H.CX_POWER["terminal"] * n_term) / 24.0 \
        + 0.2                                                   # enclosure filter fan (always on)
    fit = [k for k in ("SDR-120-24", "SDR-240-24", "SDR-480-24") if logic <= H.PSU_LOAD_MAX * H.PSU[k]["I"]]
    LOGIC_PSU[0] = fit[0] if fit else "SDR-480-24"
    psu = H.PSU[LOGIC_PSU[0]]
    row("24 V logic supply", f"{logic:.2f} A", f"<= {H.PSU_LOAD_MAX:.0%} of {LOGIC_PSU[0]} {psu['I']:g} A",
        logic <= H.PSU_LOAD_MAX * psu["I"], "PC, terminals, sensors, IO-Link, coils, fans, light"
        + (", safety devices + contactor coils + STLs" if so else ""))
    heat = sum(io.extra.get("heat_A", 0.0) for io in ios)
    psu2 = H.PSU["SDR-480-24"]
    row("24 V heater supply", f"{heat:.2f} A", f"<= {H.PSU_LOAD_MAX:.0%} of SDR-480-24 {psu2['I']:g} A",
        heat <= H.PSU_LOAD_MAX * psu2["I"], "3 sealing heads via DC SSRs")
    # 48 V motors: copper loss of both phases + 20 % driver loss, from the supply
    motors = [io for io in ios if io.kind == "STEP"]
    p48 = sum(1.2 * 2 * H.STEPPER[io.extra["motor"]]["I"] ** 2 * H.STEPPER[io.extra["motor"]]["R"] for io in motors)
    i48 = p48 / 48.0
    psu3 = H.PSU["SDR-480P-48"]
    row("48 V motor supply", f"{i48:.2f} A ({p48:.0f} W)", f"<= {H.PSU_LOAD_MAX:.0%} of SDR-480P-48 {psu3['I']:g} A",
        i48 <= H.PSU_LOAD_MAX * psu3["I"], f"{len(motors)} steppers, all at hold current (worst case)")
    worst_i = max(H.STEPPER[io.extra["motor"]]["I"] for io in motors)
    row("stepper phase current", f"{worst_i:g} A", f"<= EL7047 {H.BECKHOFF['EL7047']['I_max']:g} A",
        worst_i <= H.BECKHOFF["EL7047"]["I_max"], "")
    # 400 V 3N~ oven supply: every 230 V load on its phase (elements + circulation fans), per phase and zone
    S = H.SUPPLY
    ph_W = {ph: sum(io.extra["mains_W"] for io in ios if io.extra.get("phase") == ph) for ph in ("L1", "L2", "L3")}
    psu_in = H.PSU["SDR-480-24"]["U"] * H.PSU["SDR-480-24"]["I"] / H.PSU_EFF
    ph_W["L1"] += psu_in                                   # the 24 V heater PSU hangs on L1 (sealing heads)
    for ph, w in ph_W.items():
        row(f"oven feed {ph}", f"{w / S['U']:.2f} A ({w:.0f} W)", f"<= {S['load_max']:.0%} of {S['I']:g} A",
            w / S["U"] <= S["load_max"] * S["I"], "elements + fans" + (" + 24 V heater PSU" if ph == "L1" else ""))
    mains = max(ph_W.values()) / S["U"]
    for z, tc, els, fan in oven_zones(ios):
        zw = {ph: sum(e.extra["mains_W"] for e in els + ([fan] if fan else []) if e.extra["phase"] == ph) for ph in ph_W}
        zi = max(zw.values()) / S["U"]
        row(f"{z} feed (3-pole C16 + KH{z[-1]})", f"{zi:.2f} A worst phase", f"<= C16 / KH AC-1 {H.ZONE_CONTACTOR['AC1']:g} A",
            zi <= 16.0 * 0.8 and zi <= H.ZONE_CONTACTOR["AC1"], f"{len(els)} elements on " +
            ", ".join(f"{p} {w:.0f} W" for p, w in zw.items() if w))
    if so:
        C = H.SAFE["contactor"]
        row("K1/K2 48 V (DC-1)", f"{psu3['I']:g} A", f"<= {C['DC1_48']:g} A", psu3["I"] <= C["DC1_48"],
            "rated at the 48 V PSU's full rating (worst case), 1 pole each, in series")
        zs = zones()
        for tag, what, _ in contactors()[4:]:
            port = next(p_ for p_ in zs if f"{p_}-port" in what)
            iz = sum(H.STEPPER[io.extra["motor"]]["I"] * 2 for io in motors if io.tag in zs[port]["motors"])
            row(f"{tag} {port} zone (DC-1)", f"{iz:.1f} A", f"<= {C['DC1_48']:g} A", iz <= C["DC1_48"],
                f"{len(zs[port]['motors'])} motors, both phases at rated current")
        row("K3/K4 oven feed (AC-1, 3-pole)", f"{mains:.2f} A worst phase", f"<= {C['AC1']:g} A", mains <= C["AC1"],
            "every element + fan + the 24 V heater PSU input, per pole")
        st = H.SAFE["stl"]
        def stl_load(io):              # an oven zone's STB switches the zone contactor coil, a head its load
            return H.ZONE_CONTACTOR["coil_A"] if io.extra.get("zone") else io.extra.get("heat_A", 0.0)
        for io in heaters(ios):
            if stl_load(io) > st["I_DC24"]:
                row(f"STL contact {io.tag}", f"{stl_load(io):.2f} A", "<= 3 A", False, "")
        worst = max(heaters(ios), key=stl_load)
        row("STL relay contact (worst unit)", f"{stl_load(worst):.2f} A ({worst.tag})", f"<= {st['I_DC24']:g} A",
            stl_load(worst) <= st["I_DC24"], f"{len(heaters(ios))} heated units: oven zones via KH coils "
            f"({max(io.extra.get('zone_W', 0) for io in heaters(ios)):.0f} W max), sealing heads in the load path")
    return rows, fails


# ------------------------------------------------------------ cabinet
@dataclass
class Dev:
    name: str
    type: str
    w: float
    h: float
    d: float
    row: int
    x: float = 0.0
    note: str = ""


def cabinet(rails):
    """DIN layout on the enclosure's mounting plate (horizontal, under the deck):
    rows run along x; a device's 'height' lies along y, its depth stands up (z)."""
    cx, cy, cw, cd, ch = L["CAB"]
    inner_w, inner_d = cw - 3 - 2 * 15, cd - 3 - 2 * 15       # 15 mm margin to the walls
    inner_h = ch - 1.5 - 2 - 1.5                              # floor, plate, back wall
    duct = H.DUCT
    rows = defaultdict(list)
    # row 0: supplies, breakers, SSRs, safety relay
    rows[0] += [Dev("-QB0", "main switch", H.MCB_W * 4, 90, 70, 0, note="4-pole main switch 16 A + RCD 30 mA type A"),
                Dev("-FC3", "MCB", H.MCB_W, 90, 70, 0, note="PSUs C6")]
    zs = oven_zones(IOS)
    rows[0] += [Dev(f"-FC{10 + k}", "MCB 3-pole", H.MCB3["w"], 90, 70, 0, note=f"{z} feed C16") for k, (z, *_) in
                enumerate(zs)]
    for k, tb in ((LOGIC_PSU[0], "-TB1"), ("SDR-480-24", "-TB2"), ("SDR-480P-48", "-TB3")):
        p = H.PSU[k]
        rows[0].append(Dev(tb, k, p["w"], p["h"], p["d"], 0))
    safe = any(io.kind in SAFE_KINDS for io in IOS)
    if not safe:
        rows[0].append(Dev("-KF90", "safety relay", H.SAFETY_RELAY["w"], H.SAFETY_RELAY["h"], H.SAFETY_RELAY["d"], 0,
                           note="E-stop: 48 V cut + dump valve (concept open)"))
    ssr_row = []
    for z, tc, els, fan in zs:
        ssr_row += [Dev(f"-QA{e.tag}", "SSR AC 25 A", H.SSR_AC25["w"], H.SSR_AC25["h"], H.SSR_AC25["d"], 0,
                        note=f"{e.tag} {e.extra['phase']}") for e in els]
        if fan:
            ssr_row.append(Dev(f"-KA{fan.tag}", "relay 6.2", H.RELAY6["w"], H.RELAY6["h"], H.RELAY6["d"], 0,
                               note=f"{fan.tag} {fan.extra['phase']}"))
    ssr_row += [Dev(f"-{io.tag}", "current transducer", H.CT_AC["w"], H.CT_AC["h"], H.CT_AC["d"], 0,
                    note=f"element feed {io.extra['feed_phase']}") for io in IOS if io.hw == "CT_AC"]
    for t in sorted(io.tag for io in IOS if io.extra.get("heat_A")):
        ssr_row.append(Dev(f"-QA{t}", "SSR DC", H.SSR_DC["w"], H.SSR_DC["h"], H.SSR_DC["d"], 0, note=t))
    # bus segments (each starts with its CX / EK1100) packed first-fit onto DIN rows, 20 % spare kept
    cap = (cw - 3 - 2 * 15) / (1 + SPARE_MIN)
    seg_w = [sum(H.BECKHOFF[t]["w"] for t, _, _ in rail) for rail in rails]
    din = []
    for r in sorted(range(len(rails)), key=lambda r: -seg_w[r]):
        k = next((i for i, d in enumerate(din) if sum(seg_w[j] for j in d) + seg_w[r] <= cap + 1e-6), None)
        if k is None:
            din.append([r])
        else:
            din[k].append(r)
    for i, d in enumerate(din):
        for r in sorted(d):
            for t, n, note in rails[r]:
                b = H.BECKHOFF[t]
                rows[1 + i].append(Dev(n or "end", t, b["w"], b.get("h", H.EL_H), b.get("d", H.EL_D), 1 + i,
                                       note=note))
    n_dist = sum(1 for io in IOS if io.kind in ("DI", "DO", "IOL", "AI", "ENC", "DITS", "DOTS", "SI", "SO")
                 and not io.extra.get("cabinet"))
    rows[1 + len(din)] = [Dev(d.name, d.type, d.w, d.h, d.d, 1 + len(din), note=d.note) for d in ssr_row]
    r0 = 2 + len(din)
    if safe:      # S-1: one row of double-level blocks (+24 V over 0 V) instead of two single rows
        tb = H.TERMINAL_BLOCK2
        rows[r0] = [Dev(f"-XD1.{k + 1}", "PTTB 2.5", tb["pitch"], tb["h"], tb["d"], r0, note="+24 V / 0 V")
                    for k in range(n_dist)]
        C, T = H.SAFE["contactor"], H.SAFE["stl"]
        rows[r0 + 1] = [Dev(f"-Q{tag}", "contactor", C["w"], C["h"], C["d"], r0 + 1, note=what)
                        for tag, what, _ in contactors()]
        Z = H.ZONE_CONTACTOR
        rows[r0 + 1] += [Dev(f"-QKH{z[-1]}", "zone contactor", Z["w"], Z["h"], Z["d"], r0 + 1, note=f"{z} (coil via STB)")
                         for z, *_ in zs]
        rows[r0 + 1] += [Dev(f"-BT{k + 1}", "STL", T["w"], T["h"], T["d"], r0 + 1, note=io.tag)
                         for k, io in enumerate(heaters(IOS))]
    else:
        rows[r0] = [Dev(f"-XD1.{k + 1}", "PT 2.5", H.TERMINAL_BLOCK["pitch"], 50.0, 40.0, r0,
                        note="+24 V distribution") for k in range(n_dist)]
        rows[r0 + 1] = [Dev(f"-XD2.{k + 1}", "PT 2.5", H.TERMINAL_BLOCK["pitch"], 50.0, 40.0, r0 + 1,
                            note="0 V distribution") for k in range(n_dist)]
    fails, out = [], []
    y = cy + 1.5 + 15
    pitch = []
    for r in sorted(rows):
        devs = rows[r]
        width = sum(d.w for d in devs)
        hmax = max(d.h for d in devs)
        dmax = max(d.d + H.RAIL["h"] for d in devs)
        if width * (1 + SPARE_MIN) > inner_w + 1e-6:
            fails.append(f"CABINET row {r}: {width:.0f} mm + 20 % spare > rail {inner_w:.0f} mm")
        if dmax > inner_h + 1e-6:
            fails.append(f"CABINET row {r}: device depth {dmax:.0f} > enclosure height {inner_h:.0f}")
        x = cx + 1.5 + 15
        for d in devs:
            d.x = x
            x += d.w
        out.append(dict(row=r, y=y, h=hmax, width=width, rail=inner_w, spare=1 - width / inner_w,
                        devices=[dict(name=d.name, type=d.type, x=round(d.x, 1), w=d.w, h=d.h, d=d.d, note=d.note)
                                 for d in devs]))
        pitch.append(hmax)
        y += hmax + duct["w"]
    used = y - duct["w"] - (cy + 1.5 + 15)
    if used > inner_d + 1e-6:
        fails.append(f"CABINET rows need {used:.0f} mm, plate has {inner_d:.0f} mm")
    # heat: PSU losses + PC + terminals + stepper drivers (20 % of motor power) + SSR drops
    ploss = sum(H.PSU_LOAD_MAX * H.PSU[k]["U"] * H.PSU[k]["I"] * (1 - H.PSU_EFF) for k in
                (LOGIC_PSU[0], "SDR-480-24", "SDR-480P-48"))
    if safe:                                   # contactor coils are energised whenever the line runs; STLs
        ploss += (len(contactors()) + len(zs)) * 24.0 * H.SAFE["contactor"]["coil_A"] + \
            len(heaters(IOS)) * H.SAFE["stl"]["P"]
    ploss += sum(H.SSR_AC25["U_drop"] * io.extra["mains_W"] / H.SUPPLY["U"] for io in IOS
                 if io.hw == "SSR_AC25")                                     # element SSRs, at full on
    ploss += H.CX_POWER["CX2020"] + H.CX_POWER["terminal"] * sum(len(r) for r in rails)
    ploss += sum(0.2 * 2 * H.STEPPER[io.extra["motor"]]["I"] ** 2 * H.STEPPER[io.extra["motor"]]["R"]
                 for io in IOS if io.kind == "STEP")
    ploss += sum(1.2 * io.extra.get("heat_A", 0.0) for io in IOS)          # DC SSR ~1.2 V drop
    area = (2 * (cw * ch + cd * ch) + cw * cd) / 1e6                          # the top is the deck: no exchange
    dT = ploss / (H.THERMAL["k"] * area)
    fan = dT > H.THERMAL["dT_max"]
    dT_fan = ploss / (1.2 * 1005 * H.THERMAL["fan_m3h"] / 3600) if fan else dT
    if dT_fan > H.THERMAL["dT_max"]:
        fails.append(f"THERMAL enclosure dT {dT_fan:.1f} K > {H.THERMAL['dT_max']:g} K")
    therm = dict(loss_W=round(ploss, 1), area_m2=round(area, 2), dT_natural=round(dT, 1), fan=fan,
                 dT=round(dT_fan, 1))
    return out, fails, dict(inner_w=inner_w, inner_d=inner_d, inner_h=inner_h, used_d=used, thermal=therm)


# ------------------------------------------------------------ wiring
CABLE_OF = {"DI": "M12-3", "DO": "M12-3", "AI": "M12-4", "TC": "tc-K", "IOL": "iol-4", "ENC": "enc-8",
            "STEP": "motor-4", "ETH": "gige", "DITS": "M12-3", "DOTS": "M12-3", "SI": "M12-5", "SO": "M12-3"}


def wiring(ios):
    """One row per conductor group: device -> cable -> terminal. Length = plan
    Manhattan to the nearest enclosure edge + height + 0.5 m inside + 0.3 m loop."""
    cx, cy, cw, cd, ch = L["CAB"]
    rows, fails = [], []
    for k, io in enumerate(ios):
        x, y, z = io.pos
        dx = 0.0 if cx <= x <= cx + cw else min(abs(x - cx), abs(x - cx - cw))
        dy = 0.0 if cy <= y <= cy + cd else min(abs(y - cy), abs(y - cy - cd))
        length = (dx + dy + max(z, 0.0) + L["TABLE"][2]) / 1000 + 0.5 + 0.3
        cab = CABLE_OF[io.kind] if not io.hw.startswith("SSR_AC") else "M12-3"
        if io.hw == "guard_lock":
            cab = "M12-8"
        if io.extra.get("cabinet"):
            cab = "wire-0.75"
            length = 0.8
        n, mm2, od = H.CABLE[cab]
        cores = {"DI": "BN +24V / BU 0V / BK signal", "DO": "BK signal / BU 0V", "AI": "BN +24V / BU 0V / BK signal",
                 "TC": "GN + / WH -", "IOL": "BN L+ / BU L- / BK C/Q", "ENC": "A /A B /B Z /Z 5V 0V",
                 "STEP": "A1 A2 B1 B2", "ETH": "Cat6", "DITS": "BN +24V / BU 0V / BK signal",
                 "DOTS": "BK trigger / BU 0V", "SI": "test pulse out / safe input (2-ch devices: 2 x)",
                 "SO": "safe output / 0V"}[io.kind]
        if cab == "wire-0.75":
            cores = "cabinet wiring H07V-K 0.75"
        rows.append(dict(W=f"W{k + 1:03d}", tag=io.tag, part=io.part, module=io.module, kind=io.kind, desc=io.desc,
                         terminal=io.slot or ("edge PC switch" if io.kind == "ETH" else ""), cable=cab,
                         cores=cores, mm2=mm2, length_m=round(length, 2), cad=io.cad))
        # DC supply drop: the load current over both conductors
        if io.kind == "STEP":
            I = H.STEPPER[io.extra["motor"]]["I"]
            dv = 2 * length * I * H.CU_RHO / mm2
            if dv / 48.0 > H.VDROP_MAX:
                fails.append(f"VDROP {io.tag}: {dv:.2f} V = {dv / 48:.1%} > {H.VDROP_MAX:.0%}")
        elif io.load_A > 0:
            dv = 2 * length * io.load_A * H.CU_RHO / mm2
            if dv / 24.0 > H.VDROP_MAX:
                fails.append(f"VDROP {io.tag}: {dv:.2f} V = {dv / 24:.1%} > {H.VDROP_MAX:.0%}")
        if not io.slot and io.kind != "ETH":
            fails.append(f"UNASSIGNED {io.tag} ({io.kind})")
    # the valve island: one 25-pole cable from the island to the cabinet (coils share it)
    return rows, fails


# ------------------------------------------------------------ TwinCAT
def _var(io):
    t = io.tag.replace(".", "_").replace("-", "_")
    return {"DI": f"i{t}", "DO": f"q{t}", "AI": f"ai{t}", "TC": f"tc{t}", "IOL": f"iol{t}", "ENC": f"enc{t}",
            "STEP": f"ax{t}", "ETH": f"cam{t}", "DITS": f"its{t}", "DOTS": f"qts{t}", "SI": f"si{t}",
            "SO": f"so{t}"}[io.kind]


def twincat(ios):
    """Structured Text skeletons (IEC 61131-3), one file per POU."""
    files = {}
    lines = ["// GVL_IO - generated by plc_io.py from line_model: every signal, mapped in the I/O tree",
             "{attribute 'qualified_only'}", "VAR_GLOBAL"]
    typ = {"DI": "BOOL", "DO": "BOOL", "AI": "INT", "TC": "INT", "IOL": "ARRAY[0..31] OF BYTE",
           "ENC": "UDINT", "STEP": "AXIS_REF", "ETH": "BOOL", "DITS": "ST_TsInput", "DOTS": "ST_TsOutput"}
    for io in ios:
        if io.kind == "ETH":
            continue
        if io.kind in SAFE_KINDS:            # owned by the TwinSAFE project on the EL6910 - never written here
            lines.append(f"    // {io.kind} {io.tag:14s} {io.slot:14s} {io.part:28s} {io.desc}  [TwinSAFE]")
            continue
        at = "AT %I*" if io.kind in ("DI", "AI", "TC", "IOL", "ENC", "DITS") else \
            ("AT %Q*" if io.kind in ("DO", "DOTS") else "")
        lines.append(f"    {_var(io):24s} {at:7s}: {typ[io.kind]};   // {io.slot:14s} {io.part:28s} {io.desc}"
                     + ("  [implied, not in CAD]" if not io.cad else ""))
    lines.append("END_VAR")
    files["GVL_IO.st"] = "\n".join(lines) + "\n"
    v = {io.tag: _var(io) for io in ios}
    takt = M.takt()
    files["MAIN.st"] = f"""// MAIN - one cycle of every station agent; all stations run on ONE time base (the master axis)
PROGRAM MAIN
VAR
    fbMaster  : FB_MasterAxis;
    fbOven    : FB_Oven;          // zones, elements, fans, warm-up gate (oven.py recipe)
    fbBand    : FB_Band;          // band + depositor + topping, geared to the master
    fbTransfer: FB_Transfer;      // delta C: band row -> passing puck, NFC write
    fbQC      : FB_QC;
    fbPickA, fbPickB : FB_DeltaPicker;
    fbLane    : ARRAY[0..2] OF FB_Lane;
    fbPorts   : FB_AmrPorts;
    fbSafety  : FB_SafetyIf;      // S-1: standard side of the TwinSAFE project (requests + status only)
END_VAR
fbSafety();                      // first: every station below runs only while fbSafety.bRunEnable
fbMaster(axDrive := GVL_IO.{v['Q1']}, nEncoder := GVL_IO.{v['B1']});
fbOven(bRunEnable := fbSafety.bRunEnable, aContent := fbBand.aZoneContent);   // last cycle's content
fbBand(axBand := GVL_IO.{v['Q40']}, axRolls := GVL_IO.{v['Q41']}, axMaster := fbMaster.axMaster,
       bOvenReady := fbOven.bReady);
fbTransfer(fMasterPos := fbMaster.fPos, fBandPos := fbBand.fPos, bPuckFull := GVL_IO.{v['I1']});
fbQC(fMasterPos := fbMaster.fPos);
fbPickA(fMasterPos := fbMaster.fPos, bUpstream := TRUE);
fbPickB(fMasterPos := fbMaster.fPos, bUpstream := FALSE, bPartnerMissed := fbPickA.bMissed);
fbPorts();
"""
    files["FB_MasterAxis.st"] = f"""// FB_MasterAxis - the electronic line shaft. The chain NEVER stops (no stop path in the
// automatic mode, only losses). v = {L['V']:g} mm/s, pitch = {L['PITCH']:g} mm -> takt {takt:.2f} s.
// The master position is the MEASURING-WHEEL encoder B1 (EL5101), not the drive's own encoder,
// so sprocket slip shows as a drift between the two (health signal).
FUNCTION_BLOCK FB_MasterAxis
VAR_INPUT
    axDrive  : AXIS_REF;          // Q1 on EL7047 (closed loop)
    nEncoder : UDINT;             // B1 counts
END_VAR
VAR_OUTPUT
    axMaster : AXIS_REF;          // NC encoder axis on B1 (virtual master for gearing / cams)
    fPos     : LREAL;             // mm along the loop, modulo N*P
    fDrift   : LREAL;             // drive encoder - B1, mm (slip monitor)
END_VAR
VAR
    fbPower : MC_Power; fbVel : MC_MoveVelocity;
END_VAR
fbPower(Axis := axDrive, Enable := TRUE, Enable_Positive := TRUE, Enable_Negative := FALSE);
fbVel(Axis := axDrive, Execute := fbPower.Status, Velocity := {L['V']:.1f}, Acceleration := 20, Deceleration := 20,
      Direction := MC_Positive_Direction);
fPos := LMOD(axMaster.NcToPlc.ActPos, {L['N'] * L['PITCH']:.1f});
fDrift := axDrive.NcToPlc.ActPos - axMaster.NcToPlc.ActPos;
"""
    zs = oven_zones(ios)
    st = M.stations()
    zl = M.zone_len()
    el_lines = []
    for z, tc, els, fan in zs:
        el_lines.append(f"//   {z} {L['OVEN_ZONES'][int(z[1]) - 1]['T']:g} C: TC {tc.tag} -> " +
                        ", ".join(f"{e.tag} {e.extra['mains_W']:.0f} W {e.extra['face']} {e.extra['phase']}" for e in els)
                        + (f"; fan {fan.tag}" if fan else ""))
    loads = M.oven_power()[0]
    import oven_ctrl as OC
    pl_ = OC.Plant()
    gains = OC.tune(pl_)
    C_ = OC.CTRL
    zn = len(zs)
    # element order = oven_ctrl's (the slices the heater-break check expects)
    order = [e["tag"] for z_ in pl_.zel for e in z_]
    byt = {e.tag: e for z, tc, els, fan in zs for e in els}
    zs = [(z, tc, sorted(els, key=lambda e: order.index(e.tag)), fan) for z, tc, els, fan in zs]
    flat = [(k, i, e) for k, (z, tc, els, fan) in enumerate(zs) for i, e in enumerate(els)]
    ne = len(flat)
    phs = sorted({e.extra["phase"] for _, _, e in flat})
    cts = sorted((io for io in IOS if io.hw == "CT_AC"), key=lambda io: io.extra["feed_phase"])
    U, CT = H.SUPPLY["U"], H.CT_AC
    fan_A = {ph: sum(H.OVEN_FAN["P"] for z, tc, els, fan in zs if fan and fan.extra["phase"] == ph) / U for ph in phs}
    thr = {ph: 0.5 * min(e.extra["mains_W"] for _, _, e in flat if e.extra["phase"] == ph) / U for ph in phs}
    files["FB_Oven.st"] = f"""// FB_Oven - {zn} zones. Per zone: FEED-FORWARD of the band load (from the band content FB_Band tracks,
// row by row) + PI on the zone TC (SIMC-tuned on the oven_ctrl.py model) with conditional-integration
// anti-windup -> 2 s time-proportioning PWM on every element SSR of the zone. Cold start: set point ramp
// {C_['RAMP']:g} K/min with the ramp power fed forward.
// LEARNING feed-forward (upgrade V-1): calm at the set point (+-{C_['LEARN_BAND']:g} K for {C_['LEARN_HOLD']:g} s) on an empty band the PI
// share moves into aW0 (base load error, W), on a full band into aA1 (product load factor), time constant
// {C_['LEARN_TAU']:g} s; the integrator gives the same amount back. Both are PERSISTENT (oven_ctrl S6: +-20 % model error).
// HEATER BREAK: current transducers {', '.join(io.tag for io in cts)} on L1-L3 of the element feed. The expected phase current
// (every element in its PWM slice + the fans) lagged by the transducer's {CT['t_resp']:g} s; short by > half the
// smallest element of the phase for {C_['HB_HOLD']:g} s -> alarm; the elements in their slice through the short are
// the candidates, an element seen conducting while the phase reads right is cleared -> named (oven_ctrl S4).
// A named element leaves its zone's model (power, gain); if the rest cannot carry the full load, bReady drops
// and FB_Band stops the depositor. The STB (SF4) is hardware.
""" + "\n".join(el_lines) + f"""
// Steady load at {3600 / takt:.0f} cookies/h: """ + ", ".join(f"{z['zone']} {z['total']:.0f} W" for z in loads) + f""".
// The recipe holds +-{L['BAKE_MARGIN']:g} K (oven.py bake window); bReady = every zone inside it for 60 s.
FUNCTION_BLOCK FB_Oven
VAR_INPUT  bRunEnable : BOOL; aContent : ARRAY[0..{zn - 1}] OF LREAL;     // 0..1 zone filled (from FB_Band) END_VAR
VAR_OUTPUT bReady : BOOL; aTemp : ARRAY[0..{zn - 1}] OF LREAL; aDuty : ARRAY[0..{zn - 1}] OF LREAL;
           aElementAlarm : ARRAY[0..{zn - 1}] OF BOOL; aBroken : ARRAY[0..{ne - 1}] OF BOOL; bHold : BOOL;
           fPower_W : LREAL; END_VAR
VAR PERSISTENT
    aW0 : ARRAY[0..{zn - 1}] OF LREAL;                                   // W, learned base-load error
    aA1 : ARRAY[0..{zn - 1}] OF LREAL := [{', '.join('1.0' for _ in range(zn))}];   // learned product-load factor
END_VAR
VAR
    aSet  : ARRAY[0..{zn - 1}] OF LREAL := [{', '.join(f"{t:.1f}" for t in pl_.Ts)}];      // degC (oven.py recipe)
    aKc   : ARRAY[0..{zn - 1}] OF LREAL := [{', '.join(f"{g['Kc']:.4f}" for g in gains)}];  // 1/K
    aTi   : ARRAY[0..{zn - 1}] OF LREAL := [{', '.join(f"{g['Ti']:.0f}" for g in gains)}];  // s
    aP    : ARRAY[0..{zn - 1}] OF LREAL := [{', '.join(f"{p:.0f}" for p in pl_.P)}];        // W installed
    aC    : ARRAY[0..{zn - 1}] OF LREAL := [{', '.join(f"{c:.0f}" for c in pl_.C)}];        // J/K
    aLoadEmpty, aLoadFull : ARRAY[0..{zn - 1}] OF LREAL := [{', '.join(f"{pl_.load(k, pl_.Ts[k], 0.0):.0f}" for k in range(zn))}], [{', '.join(f"{pl_.load(k, pl_.Ts[k], 1.0):.0f}" for k in range(zn))}];
    aSp, aI, aLost, aCalm : ARRAY[0..{zn - 1}] OF LREAL;   // aSp := aTemp at power-up (the ramp starts where the zone is)
    fRamp : LREAL := {C_['RAMP'] / 60:.4f};    // K/s
    // elements, flattened in slice order: zone, slice i of n, phase 0..2 = L1..L3, W
    aElZone  : ARRAY[0..{ne - 1}] OF INT := [{', '.join(str(k) for k, i, e in flat)}];
    aElSlice : ARRAY[0..{ne - 1}] OF LREAL := [{', '.join(f"{i}.0 / {len(zs[k][2])}.0" for k, i, e in flat)}];
    aElPh    : ARRAY[0..{ne - 1}] OF INT := [{', '.join(str(phs.index(e.extra['phase'])) for k, i, e in flat)}];
    aElW     : ARRAY[0..{ne - 1}] OF LREAL := [{', '.join(f"{e.extra['mains_W']:.0f}" for k, i, e in flat)}];
    aOn, aCand : ARRAY[0..{ne - 1}] OF BOOL;
    aFanA : ARRAY[0..2] OF LREAL := [{', '.join(f"{fan_A[ph]:.3f}" for ph in phs)}];   // A, fans on the feed
    aThrA : ARRAY[0..2] OF LREAL := [{', '.join(f"{thr[ph]:.3f}" for ph in phs)}];   // A, half the smallest element
    aExp, aExpLag, aMeas, aShort : ARRAY[0..2] OF LREAL;
    aPhAlarm, aShortOn : ARRAY[0..2] OF BOOL;
    aOnT : ARRAY[0..{ne - 1}] OF LREAL;  aRecent, aTry, aOnLast : ARRAY[0..{ne - 1}] OF BOOL;
    aSince, aAlarmT, aProbeT, aProbeMax : ARRAY[0..2] OF LREAL;
    aProbe : ARRAY[0..2] OF INT := [-1, -1, -1];
    fNow_s, fPhase, dW, fProd : LREAL;     // fNow_s: task time in s (TwinCAT system time)
    tStable : TON; k, i, j, n, m : INT; e, uff, u : LREAL; bRamp, bAnyAlarm, bSame, bSettled : BOOL;
END_VAR
""" + "".join(f"aTemp[{k}] := INT_TO_LREAL(GVL_IO.{v[tc.tag]}) / 10.0;\n" for k, (z, tc, els, fan) in enumerate(zs)) + \
"".join(f"aMeas[{j}] := INT_TO_LREAL(GVL_IO.{v[io.tag]}) / 32767.0 * {CT['range']:.1f};   // A, {io.extra['feed_phase']}\n"
        for j, io in enumerate(cts)) + \
f"""bAnyAlarm := {' OR '.join([f'aPhAlarm[{j}]' for j in range(len(phs))] + [f'aElementAlarm[{k}]' for k in range(zn)])};   // learning frozen until repaired
FOR k := 0 TO {zn - 1} DO
    aSp[k] := MIN(aSet[k], aSp[k] + fRamp * 0.01);  bRamp := aSp[k] < aSet[k];        // 10 ms task
    e := aSp[k] - aTemp[k];
    fProd := aContent[k] * (aLoadFull[k] - aLoadEmpty[k]);
    uff := (aLoadEmpty[k] + aW0[k] + aA1[k] * fProd + SEL(bRamp, 0.0, aC[k] * fRamp)) / (aP[k] - aLost[k]);
    u := uff + aKc[k] * aP[k] / (aP[k] - aLost[k]) * (e + aI[k] / aTi[k]);
    IF (u > 0.0 AND u < 1.0) OR (u >= 1.0 AND e < 0.0) OR (u <= 0.0 AND e > 0.0) THEN aI[k] := aI[k] + e * 0.01; END_IF
    aDuty[k] := LIMIT(0.0, u, 1.0);
    // learning feed-forward
    IF ABS(e) < {C_['LEARN_BAND']:g} AND NOT bRamp THEN aCalm[k] := aCalm[k] + 0.01; ELSE aCalm[k] := 0.0; END_IF
    IF aCalm[k] > {C_['LEARN_HOLD']:g} AND NOT bAnyAlarm AND (aContent[k] < 0.05 OR aContent[k] > 0.95) THEN
        dW := (aDuty[k] - uff) * aP[k] * 0.01 / {C_['LEARN_TAU']:g};
        IF aContent[k] < 0.05 THEN
            aW0[k] := aW0[k] + dW;
        ELSIF fProd > 1.0 THEN
            u := LIMIT({C_['A1_MIN']:g}, aA1[k] + dW / fProd, {C_['A1_MAX']:g});
            dW := (u - aA1[k]) * fProd;  aA1[k] := u;
        END_IF
        aI[k] := aI[k] - dW / aP[k] / aKc[k] * aTi[k];
    END_IF
END_FOR
// time-proportioning, 2 s period: element i of n in a zone conducts in its own slice of the period (phase
// [i/n, i/n + duty)) - the zone gets its duty, the phases see the load spread instead of all at once
fPhase := LMOD(fNow_s / 2.0, 1.0);
FOR j := 0 TO 2 DO aExp[j] := SEL(bRunEnable, 0.0, aFanA[j]); END_FOR
FOR i := 0 TO {ne - 1} DO
    aOn[i] := F_InSlice(fPhase, aElSlice[i], aDuty[aElZone[i]]) AND bRunEnable AND NOT aBroken[i]
              AND aProbe[aElPh[i]] <> i;                       // a probed candidate is held off
    IF aOn[i] THEN aExp[aElPh[i]] := aExp[aElPh[i]] + aElW[i] / {U:g}; END_IF
END_FOR
""" + "".join(f"GVL_IO.{v[e.tag]} := aOn[{n}];   // {zs[k][0]}\n" for n, (k, i, e) in enumerate(flat)) + \
"".join(f"GVL_IO.{v[fan.tag]} := bRunEnable;   // {z} circulation fan\n" for z, tc, els, fan in zs if fan) + \
f"""// heater break: expected vs measured phase current (oven_ctrl._HeaterBreak, line for line)
FOR i := 0 TO {ne - 1} DO
    IF aOn[i] THEN aOnT[i] := fNow_s; END_IF
    aRecent[i] := fNow_s - aOnT[i] <= {CT['t_resp']:g};      // the reading lags: on at some time in t_resp
END_FOR
FOR j := 0 TO 2 DO
    bSame := TRUE;                                            // same elements on as last cycle?
    FOR i := 0 TO {ne - 1} DO IF aElPh[i] = j AND aOn[i] <> aOnLast[i] THEN bSame := FALSE; END_IF END_FOR
    IF NOT bSame THEN aSince[j] := fNow_s; END_IF
    bSettled := ABS(aExp[j] - aExpLag[j]) < 0.1 * aThrA[j];
    aExpLag[j] := aExpLag[j] + (aExp[j] - aExpLag[j]) * 0.01 / {CT['t_resp'] / 3:.3f};
    IF aProbe[j] >= 0 THEN                                     // active probe: candidate aProbe[j] held off
        IF fNow_s - aProbeT[j] >= {CT['t_resp']:g} THEN aProbeMax[j] := MAX(aProbeMax[j], aExpLag[j] - aMeas[j]); END_IF
        IF fNow_s - aProbeT[j] >= {C_['PWM'] + CT['t_resp']:g} THEN     // a full period: its slice came
            IF aProbeMax[j] < 0.5 * aThrA[j] THEN                  // the short vanished: it is the one
                FOR i := 0 TO {ne - 1} DO aCand[i] := aCand[i] AND (aElPh[i] <> j OR i = aProbe[j]); END_FOR
            ELSE
                aCand[aProbe[j]] := FALSE;
            END_IF
            aProbe[j] := -1;
        END_IF
    ELSIF aExpLag[j] - aMeas[j] > aThrA[j] THEN
        aShort[j] := aShort[j] + 0.01;
        FOR i := 0 TO {ne - 1} DO
            IF aElPh[i] = j THEN aTry[i] := SEL(aShortOn[j], aRecent[i], aTry[i] AND aRecent[i]); END_IF
        END_FOR
        aShortOn[j] := TRUE;
        IF aShort[j] >= {C_['HB_HOLD']:g} THEN
            IF NOT aPhAlarm[j] THEN
                aPhAlarm[j] := TRUE;  aAlarmT[j] := fNow_s;
                FOR i := 0 TO {ne - 1} DO IF aElPh[i] = j THEN aCand[i] := aTry[i]; END_IF END_FOR
            ELSE
                FOR i := 0 TO {ne - 1} DO IF aElPh[i] = j THEN aCand[i] := aCand[i] AND aTry[i]; END_IF END_FOR
            END_IF
        END_IF
    ELSE
        IF bSettled AND fNow_s - aSince[j] >= {CT['t_resp']:g} AND aExpLag[j] - aMeas[j] < 0.2 * aThrA[j] AND aPhAlarm[j] THEN
            FOR i := 0 TO {ne - 1} DO
                IF aElPh[i] = j AND aOn[i] THEN aCand[i] := FALSE; END_IF     // conducted, phase read right: not it
            END_FOR
        END_IF
        IF aShort[j] < {C_['HB_HOLD']:g} THEN aShortOn[j] := FALSE; END_IF
        aShort[j] := 0.0;
    END_IF
    IF aPhAlarm[j] THEN
        n := 0;  m := -1;
        FOR i := 0 TO {ne - 1} DO IF aElPh[i] = j AND aCand[i] THEN n := n + 1; IF m < 0 THEN m := i; END_IF END_IF END_FOR
        IF n = 0 THEN                                          // contradiction: start the diagnosis again
            aPhAlarm[j] := FALSE;  aShortOn[j] := FALSE;  aProbe[j] := -1;
        ELSIF n = 1 THEN                                       // named
            aBroken[m] := TRUE;  aLost[aElZone[m]] := aLost[aElZone[m]] + aElW[m];  aCand[m] := FALSE;
            aElementAlarm[aElZone[m]] := TRUE;  aPhAlarm[j] := FALSE;  aShortOn[j] := FALSE;  aProbe[j] := -1;
        ELSIF aProbe[j] < 0 AND fNow_s - aAlarmT[j] >= {C_['HB_PROBE_AFTER']:g} THEN
            aProbe[j] := m;  aProbeT[j] := fNow_s;  aProbeMax[j] := -1.0E9;   // the slices cannot tell: probe
        END_IF
    END_IF
END_FOR
FOR i := 0 TO {ne - 1} DO aOnLast[i] := aOn[i]; END_FOR
// a zone whose remaining elements cannot carry the full band at {C_['U_MAX']:.0%} duty: hold the depositor
bHold := FALSE;
FOR k := 0 TO {zn - 1} DO
    IF (aP[k] - aLost[k]) * {C_['U_MAX']:g} < aLoadFull[k] + aW0[k] + (aA1[k] - 1.0) * (aLoadFull[k] - aLoadEmpty[k]) THEN bHold := TRUE; END_IF
END_FOR
fPower_W := 0.0;
FOR k := 0 TO {zn - 1} DO fPower_W := fPower_W + aDuty[k] * (aP[k] - aLost[k]); END_FOR
tStable(IN := """ + " AND ".join(f"ABS(aTemp[{k}] - aSet[{k}]) < {L['BAKE_MARGIN']:g}" for k in range(zn)) + """, PT := T#60S);
bReady := tStable.Q AND NOT bHold;
"""
    files["F_InSlice.st"] = """// F_InSlice - TRUE while fPhase (0..1 of the PWM period) lies in [fStart, fStart + fDuty), wrapping at 1
FUNCTION F_InSlice : BOOL
VAR_INPUT fPhase, fStart, fDuty : LREAL; END_VAR
F_InSlice := LMOD(fPhase - fStart + 1.0, 1.0) < fDuty;
"""
    files["FB_Band.st"] = f"""// FB_Band - the mesh band ({M.band_v():.3f} mm/s) and the depositor rolls are GEARED to the master axis:
// one row of {L['BAND']['rows']} per {L['BAND']['rows']} pucks ({L['BAND']['rows'] * takt:.0f} s). The wire is cammed from the rolls.
// Topping: rows k and k+3 get flavour k (Q2/Q3/Q4), {st['top'] - st['dep']:.0f} mm after the die.
// A cold oven (bOvenReady FALSE) stops the depositor, never the band: what is in the oven bakes out.
FUNCTION_BLOCK FB_Band
VAR_INPUT axBand : AXIS_REF; axRolls : AXIS_REF; axMaster : AXIS_REF; bOvenReady : BOOL; END_VAR
VAR_OUTPUT fPos : LREAL; aZoneContent : ARRAY[0..{len(L['OVEN_ZONES']) - 1}] OF LREAL; END_VAR   // 0..1 per zone, from the rows cut
VAR fbGearBand, fbGearRolls : MC_GearIn; END_VAR
fbGearBand(Master := axMaster, Slave := axBand, Execute := TRUE, RatioNumerator := {M.band_v() * 1000:.0f},
           RatioDenominator := {L['V'] * 1000:.0f});
fbGearRolls(Master := axMaster, Slave := axRolls, Execute := bOvenReady, RatioNumerator := 1, RatioDenominator := 1);
fPos := axBand.NcToPlc.ActPos;
"""
    files["FB_Transfer.st"] = f"""// FB_Transfer - delta C takes the cookies of the row in the pick window ({L['PICK_W']:g} mm = {L['PICK_W'] / M.band_v():.0f} s,
// >= {L['BAND']['rows']} takts) in row order (W R B W R B) and places each into the next empty puck on the bend
// ({L['PLACE_TH'][0]:g}..{L['PLACE_TH'][1]:g} deg). I1 = puck already full (recirculating): skip it, the cookie waits.
// NFC-W writes flavour (band row), batch and the bake log (zone temperatures, IR1) into the tag; I9 confirms.
FUNCTION_BLOCK FB_Transfer
VAR_INPUT fMasterPos : LREAL; fBandPos : LREAL; bPuckFull : BOOL; END_VAR
VAR nRow : UINT; nNext : UINT; END_VAR
"""
    files["FB_QC.st"] = f"""// FB_QC - camera verdict (edge PC via ADS) + colour sensor; kick on the fly.
// Camera -> kicker = {L['CAM_X'] - L['KICK_X']:.0f} mm = {(L['CAM_X'] - L['KICK_X']) / L['V']:.1f} s >= AI latency {L['AI_LATENCY']:g} s.
FUNCTION_BLOCK FB_QC
VAR_INPUT fMasterPos : LREAL; END_VAR
VAR fKickPos : LREAL := {M.s_back(L['KICK_X']):.1f}; aReject : ARRAY[0..{L['N'] - 1}] OF BOOL; END_VAR
// verdict k arrives -> aReject[k] := TRUE; write NFC-W2; when puck k reaches fKickPos: pulse GVL_IO.{v['Q18']} {int(L['KICK_T'] * 1000)} ms
"""
    files["FB_DeltaPicker.st"] = f"""// FB_DeltaPicker - conveyor tracking pick of a moving cookie, place into the lane pocket.
// Kinematics: the NC delta transformation (TF5110-class, licence to confirm) with conveyor
// tracking coupled to the master axis; the tracking camera CAM2 gives pose + phase. A is
// upstream and picks; B catches what A missed (N+1). Placement budget: backlash + steps
// {''}<= DELTA_REP (proven in line_model.sizing with the Jacobian).
FUNCTION_BLOCK FB_DeltaPicker
VAR_INPUT fMasterPos : LREAL; bUpstream : BOOL; bPartnerMissed : BOOL; END_VAR
VAR_OUTPUT bMissed : BOOL; END_VAR
VAR eState : (WAIT, TRACK, GRIP, LIFT, PLACE, RELEASE, HOME); END_VAR
// GRIP: vacuum valve ON, wait for the vacuum switch (.OK); no OK within {L['T_GRAB']:g} s -> bMissed (the cookie recirculates)
"""
    files["FB_Lane.st"] = f"""// FB_Lane - index one tray pitch when a tray is full; seal in the index pause ({L['SEAL_T']:g} s <= {L['T_INDEX']:g} s);
// stacker lifts each pack through the pawls; the lift counter says 'cassette full' at {M.cass_cap()} packs;
// shuttle swap (OPEN DESIGN ISSUE: a single bar cannot exchange two cassettes - see joints/README).
FUNCTION_BLOCK FB_Lane
VAR_INPUT nLane : INT; END_VAR
VAR nPacks : INT; END_VAR
"""
    files["DUT_PhysicalAI.st"] = """// timestamped I/O and the record every learned model is trained on
TYPE ST_TsInput : STRUCT bNewEdge : BOOL; nTimestamp : ULINT; END_STRUCT END_TYPE     // EL1252 (DC ns)
TYPE ST_TsOutput : STRUCT bArm : BOOL; nFireAt : ULINT; END_STRUCT END_TYPE          // EL2252 (DC ns)
TYPE ST_PuckEvent : STRUCT
    nPuck : UINT; sNfc : STRING(16); nDcTime : ULINT; fMasterPos : LREAL;
    eStation : E_Station; aSignals : ARRAY[0..15] OF REAL; nImageId : UDINT; eOutcome : E_Outcome;
END_STRUCT END_TYPE
"""
    files["FB_CameraTrigger.st"] = f"""// FB_CameraTrigger - fire every camera at a puck's master position via EL2252 (DC time), so each image
// is exactly aligned with the puck (NFC id), the master position and every other sensor sample.
FUNCTION_BLOCK FB_CameraTrigger
VAR_INPUT fMasterPos : LREAL; fTriggerPos : LREAL; END_VAR
VAR_IN_OUT stOut : ST_TsOutput; END_VAR
// nFireAt := DC time now + (fTriggerPos - fMasterPos) / {L['V']:g} mm/s -> the terminal fires on the ns
"""
    files["FB_DataTag.st"] = """// FB_DataTag - one ST_PuckEvent per puck per station, written to the edge PC (ADS / TwinCAT Database
// Server). Outcome labels come from the machine itself: I9 landed, vacuum level, reed timings, QC verdict,
// pack camera 'seated' - self-labelling data for every learned model.
FUNCTION_BLOCK FB_DataTag
"""
    files["FB_Policy.st"] = """// FB_Policy - a learned model evaluated IN the real-time task (TwinCAT 3 Machine Learning inference,
// ONNX, Tc3_MLL FB_MllPrediction - licence TF3800/TF3810 to confirm). Used for fast, bounded decisions:
// drop lead per tube, kick / pass, grip retry. Its output ALWAYS passes FB_SafeEnvelope.
FUNCTION_BLOCK FB_Policy
VAR fbPredict : FB_MllPrediction; END_VAR
"""
    files["FB_SafeEnvelope.st"] = """// FB_SafeEnvelope - hard, non-learned limits every policy output is clamped to (position windows,
// speeds, forces from line_model). It is NOT the safety function: guarding + TwinSAFE are (SAFETY_CONCEPT.md).
FUNCTION_BLOCK FB_SafeEnvelope
"""
    if any(io.kind in SAFE_KINDS for io in ios):
        doors = ", ".join(d[0] for d in L["DOORS"])
        ss1 = safety_ss1()
        files["FB_SafetyIf.st"] = f"""// FB_SafetyIf - the STANDARD side of the TwinSAFE project (EL6910). It never switches a safe
// output: it sends REQUESTS (unlock a door, mute a port, reset) and reads STATUS via the EL6910's
// standard process data. The safety functions themselves (SF1..SF6, SAFETY_CONCEPT.md, safety.py) are
// configured in the TwinSAFE editor from safety/safety_functions.csv.
//   SS1: on any stop demand the NC ramps every axis down (MC_Stop), then TwinSAFE drops K1/K2 after
//        {ss1:.2f} s (longest ramp + {L['SS1_MARGIN']:g} s margin, proven in safety.py).
//   Doors {doors}: unlock request -> TwinSAFE unlocks only after every encoder reports standstill for
//        {L['UNLOCK_STILL']:g} s (the standard encoders are a plausibility input; see SAFETY_CONCEPT open items).
//   Ports: airlocks (S-1b) - FB_Airlock sequences them; TwinSAFE enforces the interlocks
//        (outer door unlocks only with the inner side shut and the zone at safe standstill).
FUNCTION_BLOCK FB_SafetyIf
VAR_OUTPUT
    bRunEnable   : BOOL;          // no stop demand active, all doors locked, all resets done
    bStopDemand  : BOOL;          // SS1 in progress -> every station: MC_Stop now
    aDoorLocked  : ARRAY[0..{len(L['DOORS']) - 1}] OF BOOL;
    aPortMuted   : ARRAY[0..{len(L['PORT_OPEN']) - 1}] OF BOOL;
END_VAR
VAR
    aUnlockReq   : ARRAY[0..{len(L['DOORS']) - 1}] OF BOOL;   // from the HMI
    aMuteReq     : ARRAY[0..{len(L['PORT_OPEN']) - 1}] OF BOOL;   // from FB_AmrPorts when an AMR is due
END_VAR
"""
    if L.get("AIRLOCK"):
        files["FB_Airlock.st"] = f"""// FB_Airlock - standard-side sequence of the two AMR airlocks. It only REQUESTS; the TwinSAFE
// project (SF6) refuses any unlock that breaks the interlock, so a bug here cannot open both sides.
//
// OUT (cassettes), per lane, started by the lift counter {L['CASS_LEAD']:g} s before full (the AMR is called then):
//   1 carrier: full cassette stacker -> chamber ({L['CASS_X'][1] - L['CASS_X'][0]:g} mm at {L['SHUTTLE_V']:g} mm/s)
//   2 request S32 close + lock (inner door); TwinSAFE drops K5 (shuttles)
//   3 AMR docked (OUT.DOCK1/2) -> request S31 unlock + open (outer door)
//   4 AMR swaps full <-> empty ({L['AMR_EXCH']:g} s [assumed]); S31 close + lock
//   5 request S32 unlock + open; K5 on; carrier: empty chamber -> stacker
//   exchange {M.cass_swap_t():.0f} s; the stacker platform holds {M.transfer_buffer()} sealed pack meanwhile, so a robot on
//   time costs no production. Lanes run a third of a fill apart (CASS_STAGGER) so exchanges never coincide.
// BOXES (tray stacks): AMR docked -> trapdoors closed (Q42..Q44.CL) + Y1 exhausted -> S30 unlock + open;
//   AMR sets stacks in the chamber; S30 close + lock -> Y1 on -> trapdoor over each low magazine drops its stack.
FUNCTION_BLOCK FB_Airlock
VAR_INPUT nLaneFull : INT; bAmrDocked : BOOL; END_VAR
VAR eOut : (IDLE, CARRY_OUT, INNER_CLOSE, OUTER_OPEN, SWAP, OUTER_CLOSE, INNER_OPEN, CARRY_IN); END_VAR
"""
    files["FB_AmrPorts.st"] = """// FB_AmrPorts - every buffer raises a task with a DEADLINE (its autonomy left):
// hopper level (IO-Link ToF), cassette full (lift counter), tray magazine, reject drawer level.
// Earliest deadline first; one visit serves every pending task at a port (line_sim proves it).
FUNCTION_BLOCK FB_AmrPorts
"""
    return files


def safety_ss1():
    """SS1 delay (s): the longest controlled ramp-down of any axis + margin (the chain and the band geared
    to it, the deltas, the shuttles and the lanes stop under NC control before the contactors remove power)."""
    ramps = [L["V"] / 20.0,                                   # master: 20 mm/s at 20 mm/s2 (FB_MasterAxis)
             L["DELTA_VMAX"] / L["DELTA_ACC"]]                # effector at peak speed
    return max(ramps) + L["SS1_MARGIN"]


IOS = []


def check(verbose=True, write=False):
    global IOS
    IOS = io_list()
    rails, trows, tf = terminals(IOS)
    prows, pf = power(IOS)
    lay, cf, dims = cabinet(rails)
    wires, wf = wiring(IOS)
    fails = tf + pf + cf + wf
    if verbose:
        kinds = defaultdict(int)
        for io in IOS:
            kinds[io.kind] += 1
        print(f"PLC I/O: {len(IOS)} signals ({', '.join(f'{k} {v}' for k, v in sorted(kinds.items()))}); "
              f"{sum(1 for io in IOS if not io.cad)} implied points not yet in the CAD")
        for kind, term, need, n, cap, spare, ok in trows:
            print(f"  [{'ok' if ok else 'FAIL'}] {kind:5s} {need:3d} used -> {n} x {term} = {cap:3d} ch, spare {spare:.0%}")
        for r, rail in enumerate(rails):
            print(f"  rail {r + 1}: " + " | ".join(t for t, n, _ in rail))
        for name, v, lim, ok, note in prows:
            print(f"  [{'ok' if ok else 'FAIL'}] {name:28s} {v:22s} {lim:36s} {note}")
        for r in lay:
            print(f"  cabinet row {r['row']}: {r['width']:.0f} / {r['rail']:.0f} mm "
                  f"({r['spare']:.0%} rail spare), row height {r['h']:.0f}")
        print(f"  enclosure {L['CAB'][2]:g} x {L['CAB'][3]:g} x {L['CAB'][4]:g}: rows use {dims['used_d']:.0f} of "
              f"{dims['inner_d']:.0f} mm, device depth <= {dims['inner_h']:.0f} mm")
        th = dims["thermal"]
        print(f"  heat: {th['loss_W']} W over {th['area_m2']} m2 -> natural dT {th['dT_natural']} K"
              + (f", with a {H.THERMAL['fan_m3h']:g} m3/h filter fan dT {th['dT']} K" if th["fan"] else "")
              + f" (limit {H.THERMAL['dT_max']:g} K)")
        tot = sum(w["length_m"] for w in wires)
        print(f"  wiring: {len(wires)} cables, {tot:.0f} m field cable")
        print("\n".join(fails) if fails else "ALL PLC PROOFS PASS (spare >= 20 %, E-bus, power, cabinet fit, "
                                            "voltage drop, every signal on a terminal)")
    if write and not fails:
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, "io_list.csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["tag", "kind", "terminal", "module", "part", "description", "hw", "load_A", "in_cad"])
            for io in IOS:
                w.writerow([io.tag, io.kind, io.slot, io.module, io.part, io.desc, io.hw, io.load_A, io.cad])
        with open(os.path.join(OUT, "wiring.csv"), "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(wires[0].keys()))
            w.writeheader()
            w.writerows(wires)
        with open(os.path.join(OUT, "cabinet.json"), "w") as fh:
            json.dump(dict(cab=L["CAB"], dims=dims, rows=lay,
                           rails=[[dict(type=t, name=n, note=no) for t, n, no in r] for r in rails]), fh, indent=1)
        for fn, txt in twincat(IOS).items():
            with open(os.path.join(OUT, fn), "w") as fh:
                fh.write(txt)
        print("wrote", OUT)
    return fails


if __name__ == "__main__":
    sys.exit(1 if check(write=True) else 0)
