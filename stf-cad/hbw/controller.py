"""
The PLC interface of the STF: the fischertechnik 24V adaptor PCB ("Adapterplatine
24V") that sits between each module and its controller.

Source: 536634-Factory-simulation-24V-extended-description.pdf (stf/docs/hw),
pages cited per block. Transcribed once, here; the web Controller tab reads the
JSON this writes, and reconcile() checks it against the factory MODEL - every
terminal in the official wiring plan must exist on a part in the model, and the
model must not carry I/O the plan does not have (those are reported, not hidden).

    python3 controller.py   ->  ~/workspace/stf-hw/web/public/controller.json
"""
import json, os, re

OUT = os.path.expanduser("~/workspace/stf-hw/web/public/controller.json")
DOC = "536634-Factory-simulation-24V-extended-description.pdf"

# ------------------------------------------------------------ board (p.4)
BOARD = {
    "name": "Adapterplatine 24V / adaptor PCB 24V",
    "blocks": {
        "ST1": "pin header to the model (ribbon cable)",
        "ST2": "pin header to the model (ribbon cable)",
        "ST3": "17x2 pin header to the PLC (34 pins)",
        "terminals": "terminals 1-30 to the PLC (alternative to ST3)",
        "R1-R8": "relays, 4 pairs, for reversing bidirectional motors",
        "V1-V4": "terminals for the solenoid valves",
    },
    "page": 4,
}

# ----------------------------------------------- PLC electricals (p.3, 35-38)
PLC = {
    "inputs": "P-lesend / sinking input: the sensor switches +24 V onto the input",
    "outputs": "P-schaltend / sourcing output: the PLC switches +24 V to the load, load to GND",
    "other_controllers": ["interface to the adaptor PCB compatible with 24 V",
                          "cycle time at least 10 ms"],
    "power": {
        "1": "+24 V for the motor changeover relays -> diode -> '+24V Motor'",
        "2": "+24 V for the sensors -> diode -> 0.2 A resettable fuse -> '+24V Sensor'",
        "3": "GND", "4": "GND",
        "note": "internal supplies are protected against reverse polarity and overload",
    },
    "rules": [
        "Light barriers: max 5 mA through the phototransistor, or it cannot pull the "
        "input to 24 V; if needed, a resistor in parallel, value found experimentally.",
        "Unidirectional loads (lamps, valves, compressors, 1-way motors) are switched "
        "directly by the PLC; a freewheel diode is integrated for inductive loads.",
        "Bidirectional motors: two outputs drive two changeover relays; each relay "
        "puts one motor lead on +24V Motor or GND. Each motor has a resettable fuse.",
        "Motor speed: a reduced voltage on terminal 1 slows the motors - for ALL "
        "bidirectional motors at once (there is only one terminal).",
        "Encoders (vacuum gripper and warehouse only): quadrature A/B, push-pull 0/24 V; "
        "single-channel counting uses B1, B3 or B5.",
        "Trail sensor: digital 0/24 V. Colour sensor: analogue, see discrepancies.",
    ],
    "pages": [3, 35, 36, 37, 38],
}

NC = None   # "nicht belegt / not used"

# Per module: requirements, the ST3 header (= terminals 1..30, pins 31/32 free,
# 33/34 GND), the ribbon pinouts, relays and valves. Pin tuples are
# (pin, terminal, signal, function). terminal "3,4" = GND, "2" = +24V sensor.
MODULES = {
    "hbw": {
        "name": "Automated High-Bay Warehouse 24V", "ft": "536631", "short": "HRL",
        "req": {"supply": "24 V / 1.2 A", "page": 6,
                "digital_in": {"reference switches": ["I1", "I4", "I5", "I6"],
                               "light barriers": ["I2", "I3"],
                               "trail sensor": ["A1", "A2"]},
                "counter_in": {"encoders": ["B1", "B2", "B3", "B4"]},
                "analog_in": {},
                "outputs": {"bidirectional motors": ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8"]}},
        "st3": {5: "I1", 6: "I2", 7: "I3", 8: "I4", 9: "A1", 10: "A2", 11: "B1", 12: "B2",
                13: "B3", 14: "B4", 15: "I5", 16: "I6", 17: "Q1", 18: "Q2", 19: "Q3", 20: "Q4",
                21: "Q5", 22: "Q6", 23: "Q7", 24: "Q8"},
        "st1": [(1, "5", "I1", "reference switch horizontal"), (2, "2", "+24V", "sensor supply"),
                (3, "6", "I2", "phototransistor inside"), (4, "2", "+24V", "sensor supply"),
                (5, "7", "I3", "phototransistor outside"), (6, "2", "+24V", "sensor supply"),
                (7, "17", "Q1", "conveyor belt forward (M1)"), (8, "18", "Q2", "conveyor belt backward (M1)"),
                (9, "3,4", "GND", "trail sensor supply"), (10, "2", "9V", "trail sensor supply, 9 V made from 24 V"),
                (11, "9", "A1", "trail sensor 1 (lower)"), (12, "10", "A2", "trail sensor 2 (upper)"),
                (13, "3,4", "GND", "light-barrier lamps"), (14, "2", "+24V", "light-barrier lamps"),
                (15, "19", "Q3", "horizontal towards rack (M2)"), (16, "20", "Q4", "horizontal towards belt (M2)"),
                (17, "3,4", "GND", "encoder horizontal supply"), (18, "2", "+24V", "encoder horizontal supply"),
                (19, "11", "B1", "encoder horizontal signal A"), (20, "12", "B2", "encoder horizontal signal B")],
        "st2": [(1, "8", "I4", "reference switch vertical"), (2, "2", "+24V", "sensor supply"),
                (3, "21", "Q5", "vertical axis down (M3)"), (4, "22", "Q6", "vertical axis up (M3)"),
                (5, "3,4", "GND", "encoder vertical supply"), (6, "2", "+24V", "encoder vertical supply"),
                (7, "13", "B3", "encoder vertical signal A"), (8, "14", "B4", "encoder vertical signal B"),
                (9, "15", "I5", "reference switch cantilever front"), (10, "2", "+24V", "sensor supply"),
                (11, "23", "Q7", "cantilever forward (M4)"), (12, "24", "Q8", "cantilever back (M4)"),
                (13, "16", "I6", "reference switch cantilever back"), (14, "2", "+24V", "sensor supply")],
        "relays": {"R1/R2": ("conveyor belt", "Q1", "Q2", "M1"), "R3/R4": ("horizontal", "Q3", "Q4", "M2"),
                   "R5/R6": ("vertical", "Q5", "Q6", "M3"), "R7/R8": ("cantilever", "Q7", "Q8", "M4")},
        "valves": {},
        "encoders": {"M2": ("B1", "B2"), "M3": ("B3", "B4")},
        "pages": [6, 7, 8, 9, 10, 11],
    },
    "vgr": {
        "name": "Vacuum Gripper Robot 24V", "ft": "536630", "short": "VKG",
        "req": {"supply": "24 V / approx. 0.9 A", "page": 29,
                "digital_in": {"reference switches": ["I1", "I2", "I3"]},
                "counter_in": {"encoders": ["B1", "B2", "B3", "B4", "B5", "B6"]},
                "analog_in": {},
                "outputs": {"bidirectional motors": ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"],
                            "compressor": ["Q7"], "solenoid valves": ["Q8"]}},
        "st3": {5: "I1", 6: "I2", 7: "I3", 9: "B1", 10: "B2", 11: "B3", 12: "B4", 13: "B5",
                14: "B6", 17: "Q1", 18: "Q2", 19: "Q3", 20: "Q4", 21: "Q5", 22: "Q6", 23: "Q7", 24: "Q8"},
        "st1": [(1, "17", "Q1", "vertical up (M1)"), (2, "18", "Q2", "vertical down (M1)"),
                (3, "3,4", "GND", "encoder supply"), (4, "2", "+24V", "encoder supply"),
                (5, "9", "B1", "encoder vertical signal A"), (6, "10", "B2", "encoder vertical signal B"),
                (7, "5", "I1", "reference vertical"), (8, "2", "+24V", "sensor supply"),
                (9, "19", "Q3", "horizontal backward (M2)"), (10, "20", "Q4", "horizontal forward (M2)"),
                (11, "3,4", "GND", "encoder supply"), (12, "2", "+24V", "encoder supply"),
                (13, "11", "B3", "encoder horizontal signal A"), (14, "12", "B4", "encoder horizontal signal B"),
                (15, "6", "I2", "reference horizontal"), (16, "2", "+24V", "sensor supply")],
        "st2": [(1, "7", "I3", "reference rotate"), (2, "2", "+24V", "sensor supply"),
                (3, "21", "Q5", "rotate clockwise (M3)"), (4, "22", "Q6", "rotate counter-clockwise (M3)"),
                (5, "3,4", "GND", "encoder supply"), (6, "2", "+24V", "encoder supply"),
                (7, "13", "B5", "encoder rotate signal A"), (8, "14", "B6", "encoder rotate signal B"),
                (9, "3,4", "GND", "compressor"), (10, "23", "Q7", "compressor")],
        "relays": {"R1/R2": ("vertical", "Q1", "Q2", "M1"), "R3/R4": ("horizontal", "Q3", "Q4", "M2"),
                   "R5/R6": ("turntable / rotate", "Q5", "Q6", "M3"), "R7/R8": None},
        "valves": {"V1": ("vacuum", "Q8", "24")},
        "encoders": {"M1": ("B1", "B2"), "M2": ("B3", "B4"), "M3": ("B5", "B6")},
        "pages": [29, 30, 31, 32, 33],
    },
    "oven": {
        "name": "Multi Processing Station with Oven 24V", "ft": "536632", "short": "FBS",
        "req": {"supply": "24 V / approx. 1.6 A", "page": 13,
                "digital_in": {"reference switches": ["I1", "I2", "I4", "I5", "I6", "I7", "I8"],
                               "light barriers": ["I3", "I9"]},
                "counter_in": {}, "analog_in": {},
                "outputs": {"unidirectional motors": ["Q3", "Q4"],
                            "bidirectional motors": ["Q1", "Q2", "Q5", "Q6", "Q7", "Q8"],
                            "lamp": ["Q9"], "compressor": ["Q10"],
                            "solenoid valves": ["Q11", "Q12", "Q13", "Q14"]}},
        "st3": {5: "I1", 6: "I2", 7: "I3", 8: "I4", 9: "I5", 10: "I6", 11: "I7", 12: "I8", 13: "I9",
                17: "Q1", 18: "Q2", 19: "Q3", 20: "Q4", 21: "Q5", 22: "Q6", 23: "Q7", 24: "Q8",
                25: "Q9", 26: "Q10", 27: "Q11", 28: "Q12", 29: "Q13", 30: "Q14"},
        "st1": [(1, "5", "I1", "reference turntable (vacuum position)"), (2, "2", "+24V", "sensor supply"),
                (3, "6", "I2", "reference turntable (belt position)"), (4, "2", "+24V", "sensor supply"),
                (5, "7", "I3", "light barrier end of conveyor belt"), (6, "2", "+24V", "sensor supply"),
                (7, "17", "Q1", "turntable clockwise (M1)"), (8, "18", "Q2", "turntable counter-clockwise (M1)"),
                (9, "3,4", "GND", "light-barrier lamp"), (10, "2", "+24V", "light-barrier lamp"),
                (11, "9", "I5", "reference vacuum (turntable position)"), (12, "2", "+24V", "sensor supply"),
                (13, "8", "I4", "reference turntable (saw position)"), (14, "2", "+24V", "sensor supply"),
                (15, "3,4", "GND", "conveyor belt motor return"), (16, "19", "Q3", "conveyor belt (M2)"),
                (17, "3,4", "GND", "saw motor return"), (18, "20", "Q4", "saw (M3)"),
                (19, NC, NC, "not used"), (20, NC, NC, "not used")],
        "st2": [(1, NC, NC, "not used"), (2, NC, NC, "not used"),
                (3, "21", "Q5", "oven feeder retract (M4)"), (4, "22", "Q6", "oven feeder extend (M4)"),
                (5, "10", "I6", "oven feeder inside"), (6, "2", "+24V", "sensor supply"),
                (7, "11", "I7", "oven feeder outside"), (8, "2", "+24V", "sensor supply"),
                (9, "12", "I8", "vacuum at oven"), (10, "2", "+24V", "sensor supply"),
                (11, "23", "Q7", "vacuum towards oven (M5)"), (12, "24", "Q8", "vacuum towards turntable (M5)"),
                (13, "3,4", "GND", "oven lamp return"), (14, "25", "Q9", "oven lamp"),
                (15, "3,4", "GND", "compressor return"), (16, "26", "Q10", "compressor"),
                (17, "13", "I9", "light barrier oven"), (18, "2", "+24V", "sensor supply"),
                (19, "3,4", "GND", "light-barrier lamp"), (20, "2", "+24V", "light-barrier lamp")],
        "relays": {"R1/R2": ("turntable", "Q1", "Q2", "M1"), "R3/R4": None,
                   "R5/R6": ("oven feeder", "Q5", "Q6", "M4"), "R7/R8": ("gripper / vacuum carriage", "Q7", "Q8", "M5")},
        "valves": {"V1": ("vacuum", "Q11", "27"), "V2": ("lowering", "Q12", "28"),
                   "V3": ("oven door", "Q13", "29"), "V4": ("pusher turntable", "Q14", "30")},
        "encoders": {},
        "pages": [13, 14, 15, 16, 17, 18],
    },
    "sorting": {
        "name": "Sorting Line with Detection 24V", "ft": "536633", "short": "BSO",
        "req": {"supply": "24 V / 1.1 A", "page": 21,
                "digital_in": {"reference switches": ["I1"],
                               "light barriers": ["I2", "I3", "I5", "I6", "I7"]},
                "counter_in": {}, "analog_in": {"colour sensor": ["A4"]},
                "outputs": {"unidirectional motors": ["Q1"], "compressor": ["Q2"],
                            "solenoid valves": ["Q3", "Q4", "Q5"]}},
        "st3": {5: "I1", 6: "I2", 7: "I3", 9: "A4", 10: "I5", 11: "I6", 12: "I7",
                17: "Q1", 18: "Q2", 20: "Q3", 21: "Q4", 22: "Q5"},
        "st1": [(1, "5", "I1", "pulse counter (Impulstaster)"), (2, "2", "+24V", "sensor supply"),
                (3, "6", "I2", "light barrier inlet"), (4, "2", "+24V", "sensor supply"),
                (5, "7", "I3", "light barrier behind colour sensor"), (6, "2", "+24V", "sensor supply"),
                (7, "3,4", "GND", "compressor return"), (8, "18", "Q2", "compressor"),
                (9, "3,4", "GND", "belt motor return"), (10, "17", "Q1", "conveyor belt"),
                (11, "3,4", "GND", "colour sensor"), (12, "2", "9V", "colour sensor supply, 9 V made from 24 V"),
                (13, "9", "A4", "colour sensor output"), (14, NC, NC, "not used"),
                (15, "3,4", "GND", "light-barrier lamp"), (16, "2", "+24V", "light-barrier lamp"),
                (17, "3,4", "GND", "light-barrier lamp"), (18, "2", "+24V", "light-barrier lamp"),
                (19, NC, NC, "not used"), (20, NC, NC, "not used")],
        "st2": [(1, NC, NC, "not used"), (2, NC, NC, "not used"),
                (3, "10", "I5", "light barrier white"), (4, "2", "+24V", "sensor supply"),
                (5, "12", "I7", "light barrier blue"), (6, "2", "+24V", "sensor supply"),
                (7, "11", "I6", "light barrier red"), (8, "2", "+24V", "sensor supply"),
                (9, "3,4", "GND", "light-barrier lamp"), (10, "2", "+24V", "light-barrier lamp"),
                (11, "3,4", "GND", "light-barrier lamp"), (12, "2", "+24V", "light-barrier lamp"),
                (13, "3,4", "GND", "light-barrier lamp"), (14, "2", "+24V", "light-barrier lamp")],
        "relays": {"R1/R2": None, "R3/R4": None, "R5/R6": None, "R7/R8": None},
        "valves": {"V1": ("ejector white", "Q3", "20"), "V2": ("ejector red", "Q4", "21"),
                   "V3": ("ejector blue", "Q5", "22")},
        "encoders": {},
        "pages": [21, 22, 23, 24, 25, 26],
    },
}

FACTORY = {"page": 2, "supply": "24 V / 4.8 A", "digital_in": 26, "reference switches": 15,
           "light barriers": 9, "trail sensor inputs": 2, "counter_in": 10, "encoders": 5,
           "analog_in": 1, "outputs": 35, "unidirectional motors": 3, "bidirectional motors": 10,
           "lamps": 1, "compressors": 3, "solenoid valves": 8}

DISCREPANCIES = [
    {"what": "Colour sensor output range",
     "a": "0-10 V analogue (this document p.21, p.25, p.36)",
     "b": "0-2 V / 0-2000 mV (colour sensor datasheet 128599)",
     "impact": "scale the analogue input for the range the sensor really delivers; "
               "measure it on the machine"},
    {"what": "Warehouse vertical motor outputs",
     "a": "'Q6/Q7 (M3)' on the wiring page (p.10)",
     "b": "Q5/Q6 on the pin header (p.9), the Belegungsplan and terminals 21/22",
     "impact": "typo on p.10 - Q5/Q6 is used here"},
    {"what": "Processing station valve V2",
     "a": "'Vakuum / vacuum' in the board table (p.4)",
     "b": "Q12 'Ventil Senken / valve lowering' on terminal V2 (p.18, Belegungsplan)",
     "impact": "V2 = lowering is used here (it is wired to Q12)"},
    {"what": "Sorting line terminal 9",
     "a": "labelled 'I4' on the pin header (p.24)",
     "b": "A4, the analogue colour sensor, on the wiring page (p.25) and Belegungsplan",
     "impact": "an analogue signal on a pin the header calls digital - the RevPi DIO "
               "occupancy plan lists the colour sensor as 'not used'"},
    {"what": "Oven turntable Q1 direction",
     "a": "English 'counterclockwise' for BOTH Q1 and Q2 (Belegungsplan)",
     "b": "German 'im Uhrzeigersinn' (clockwise) for Q1",
     "impact": "Q1 = clockwise is used here"},
]


# ---------------------------------------------------------- reconciliation
def _model_signals():
    """Every I/O signal the factory MODEL carries, per module, from part tags."""
    import parts_table as PT
    out = {}
    for r in PT.build_all():
        for tok in re.split(r"[\s/+,]+", r["io_tag"] or ""):
            if re.fullmatch(r"(I|Q|A|B)\d+|AUX\d+", tok):
                out.setdefault(r["module"], {}).setdefault(tok, set()).add(r["part_name"])
    return out


def reconcile():
    ms = _model_signals()
    rows = []
    for mid, m in MODULES.items():
        plan = set(m["st3"].values())
        have = set(ms.get(mid, {}))
        rows.append({"module": mid,
                     "plan_signals": sorted(plan, key=_sig_key),
                     "missing_in_model": sorted(plan - have, key=_sig_key),
                     "extra_in_model": {s: sorted(ms[mid][s]) for s in sorted(have - plan, key=_sig_key)},
                     "ok": not (plan - have)})
    # factory totals from the per-module plan vs page 2
    tot = {"digital_in": 0, "counter_in": 0, "analog_in": 0, "outputs": 0}
    for m in MODULES.values():
        for k in tot:
            tot[k] += sum(len(v) for v in m["req"][k].values()) if k != "outputs" else \
                sum(len(v) for v in m["req"]["outputs"].values())
    totals = [{"what": k, "doc_p2": FACTORY[k], "sum_of_modules": v, "ok": FACTORY[k] == v}
              for k, v in tot.items()]
    return rows, totals


def _sig_key(s):
    m = re.fullmatch(r"([A-Z]+)(\d+)", s)
    return (m.group(1), int(m.group(2))) if m else (s, 0)


def main():
    rows, totals = reconcile()
    mods = {}
    for mid, m in MODULES.items():
        pins = lambda lst: [{"pin": p, "terminal": t, "signal": s, "function": f} for p, t, s, f in lst]
        mods[mid] = {**{k: m[k] for k in ("name", "ft", "short", "req", "pages")},
                     "st3": {str(k): v for k, v in m["st3"].items()},
                     "st1": pins(m["st1"]), "st2": pins(m["st2"]),
                     "relays": {k: (None if v is None else
                                    {"role": v[0], "a": v[1], "b": v[2], "motor": v[3]})
                                for k, v in m["relays"].items()},
                     "valves": {k: {"role": v[0], "q": v[1], "terminal": v[2]}
                                for k, v in m["valves"].items()},
                     "encoders": {k: list(v) for k, v in m["encoders"].items()}}
    doc = {"source": DOC, "board": BOARD, "plc": PLC, "factory": FACTORY, "modules": mods,
           "discrepancies": DISCREPANCIES,
           "reconciliation": {"modules": rows, "totals": totals}}
    json.dump(doc, open(OUT, "w"), indent=1)
    print(f"wrote {OUT}")
    for r in rows:
        extra = ", ".join(f"{s} ({'/'.join(p)})" for s, p in r["extra_in_model"].items()) or "none"
        print(f"  {r['module']:8s} plan {len(r['plan_signals']):2d} signals  missing in model: "
              f"{r['missing_in_model'] or 'none'}  extra in model: {extra}")
    for t in totals:
        print(f"  factory {t['what']:11s} p.2 says {t['doc_p2']:2d}, modules sum to {t['sum_of_modules']:2d}  "
              f"{'OK' if t['ok'] else 'MISMATCH'}")


if __name__ == "__main__":
    main()
