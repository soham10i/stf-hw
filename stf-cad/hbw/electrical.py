"""
The factory's electrics, pin by pin: every component's electrical definition and the wires
between them - power supply, RevPi Core, one RevPi DIO and one 24V adaptor PCB per module, and
every motor, switch, light barrier, encoder, sensor, valve, compressor and lamp on the ribbons.

Sources, read here and never retyped:
  controller.json        the adaptor PCB's terminals and ribbon pinouts per module
                         (controller.py, from 536634 extended description)
  components.json        the ft components' datasheet and booklet facts (components.py)
  occupancyPlan*.ods     which RevPi DIO terminal each signal lands on (docs/), parsed directly
  RevPi DIO / Core and WDR power supply datasheets (docs/) - transcribed below, page-tagged

Every rating carries its source: datasheet, booklet, plan (the occupancy plans), board (the
extended description), derived (computed from sourced values) or assumed (not documented:
measure it). check() gates the export: every board signal must reach a component pin and its
RevPi terminal, and the rating checks are computed from the sourced values.

    python3 electrical.py   ->  ~/workspace/stf-hw/web/public/electrical.json
"""
import html, json, math, os, re, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.expanduser("~/workspace/stf-hw/web/public")
DOCS = os.path.expanduser("~/workspace/stf-hw/docs")
OUT = os.path.join(WEB, "electrical.json")

D, B, P, BD, DV, A = "datasheet", "booklet", "plan", "board", "derived", "assumed"
DS = "design"   # the upgrade design in stf-cad (io_nodes.py, safety.py, upgrade.py): chosen, not a datasheet
V24 = [0.0, 28.8]          # a 24 V part: 24 V + 20 % (the RevPi's and EN 61131-2's supply tolerance)
V24_SRC = A                # the ft parts' own sheets give 24 V, not a tolerance

PLANS = {"hbw": "occupancyPlanHighbayWarehouse.ods", "vgr": "occupancyPlanSuctionGripper.ods",
         "oven": "occupancyPlanOven.ods", "sorting": "occupancyPlanSortingStation.ods"}


# ------------------------------------------------------------------ the occupancy plans
def read_plan(path):
    """{board terminal: (signal, revpi terminal or None, revpi channel or None)} from an .ods."""
    x = zipfile.ZipFile(path).read("content.xml").decode()
    out = {}
    for row in re.findall(r"<table:table-row[^>]*>(.*?)</table:table-row>", x, re.S):
        vals = []
        for attr, c in re.findall(r"<table:table-cell([^>]*)>(.*?)</table:table-cell>", row, re.S):
            t = html.unescape(re.sub(r"<[^>]+>", " ", c)).strip()
            m = re.search(r'number-columns-repeated="(\d+)"', attr)
            vals += [t] * min(int(m.group(1)) if m else 1, 3)
        if not vals or not vals[0].isdigit():
            continue
        term = int(vals[0])
        rest = [v for v in vals[2:] if v]
        if not rest:
            continue
        sig = re.match(r"([IQAB]\d+)", rest[0])
        if not sig:
            continue
        rp = next((int(v) for v in rest[1:] if v.isdigit()), None)
        ch = next((re.sub(r"\s+", " ", v) for v in rest[1:] if re.search(r"(IN|OUT)\s*\d+", v)), None)
        ch = re.search(r"(IN|OUT)\s*(\d+)", ch).groups() if ch else None
        out[term] = (sig.group(1), rp, f"{ch[0]}{ch[1]}" if ch else None)
    return out


# ------------------------------------------------------------------ part definitions
def pin(n, label, function, kind, volts, vsrc, *, colour=None, max_ma=None, isrc=None):
    p = {"pin_number": n, "label": label, "function": function, "electrical_type": kind,
         "voltage_limits": volts, "voltage_source": vsrc}
    if colour: p["colour"] = colour
    if max_ma is not None: p["max_mA"], p["current_source"] = max_ma, isrc
    return p


def rating(label, value, src): return {"label": label, "value": value, "source": src}


def comp_facts(c, key):
    return [rating(f["label"], f["value"], f["source"]) for f in c[key]["facts"]]


def parts(components):
    C = components["components"]
    dims = lambda k: C[k]["overall_mm"]
    P_ = {}

    def define(pid, name, ft, src_doc, size, size_src, mass, pins, ratings, kind, glb=None):
        P_[pid] = {"part_id": pid, "name": name, "ft": ft, "document": src_doc, "kind": kind,
                   "dimensions_mm": {"x": size[0], "y": size[1], "z": size[2]}, "dimensions_source": size_src,
                   "mass_g": mass, "pins": pins, "ratings": ratings, "glb": glb}

    define("encoder_motor", "Encoder motor 24V", "144643", C["encoder_motor"]["datasheet"], dims("encoder_motor"), D, 70,
           [pin(1, "M+", "motor lead (socket)", "power_input", [0.0, 28.8], V24_SRC, max_ma=600, isrc=D),
            pin(2, "M-", "motor lead (socket)", "power_input", [0.0, 28.8], V24_SRC, max_ma=600, isrc=D),
            pin(3, "ENC+24V", "encoder supply", "power_input", V24, V24_SRC, colour="red"),
            pin(4, "ENC0V", "encoder ground", "power_input", V24, V24_SRC, colour="green"),
            pin(5, "PULS1", "encoder channel A, push-pull 0/24 V", "digital_io", V24, V24_SRC, colour="black", max_ma=10, isrc=D),
            pin(6, "PULS2", "encoder channel B, push-pull 0/24 V", "digital_io", V24, V24_SRC, colour="yellow", max_ma=10, isrc=D)],
           comp_facts(C, "encoder_motor"), "motor", "components/encoder_motor.glb")
    define("s_motor", "S-Motor 24V with U-gearbox", "S-24V", C["s_motor"]["datasheet"], dims("s_motor"), A, 40,
           [pin(1, "M+", "motor lead", "power_input", [0.0, 28.8], V24_SRC, max_ma=300, isrc=B),
            pin(2, "M-", "motor lead", "power_input", [0.0, 28.8], V24_SRC, max_ma=300, isrc=B)],
           comp_facts(C, "s_motor"), "motor", "components/s_motor.glb")
    define("mini_switch", "Mini switch", "37783", C["mini_switch"]["datasheet"], dims("mini_switch"), D, 3.4,
           [pin(1, "1", "common", "digital_io", [0.0, 50.0], D, max_ma=2000, isrc=D),
            pin(2, "2", "normally closed (1-2)", "digital_io", [0.0, 50.0], D, max_ma=2000, isrc=D),
            pin(3, "3", "normally open (1-3)", "digital_io", [0.0, 50.0], D, max_ma=2000, isrc=D)],
           comp_facts(C, "mini_switch"), "switch", "components/mini_switch.glb")
    define("phototransistor", "Photo-transistor", "36134", C["phototransistor"]["datasheet"], dims("phototransistor"), D, 1.7,
           [pin(1, "+", "collector (red marking)", "digital_io", [0.0, 35.0], D, colour="red", max_ma=15, isrc=D),
            pin(2, "-", "emitter, to the PLC input", "digital_io", [0.0, 35.0], D, max_ma=15, isrc=D)],
           comp_facts(C, "phototransistor"), "sensor", "components/phototransistor.glb")
    define("lb_lamp", "Light-barrier lamp (LED 162135)", "162135", "536634 extended description (wiring pages)", [15.0, 15.0, 7.5], A, 2.0,
           [pin(1, "+", "lamp supply", "power_input", V24, V24_SRC), pin(2, "-", "lamp return", "power_input", V24, V24_SRC)],
           [rating("Supply", "24 V from the board's '+24V' lamp pins", BD), rating("Current", "not documented - measure", A)],
           "lamp")
    define("colour_sensor", "Colour sensor", "128599", C["colour_sensor"]["datasheet"], dims("colour_sensor"), D, 6.8,
           [pin(1, "9V", "supply 6-10 V, ~15 mA", "power_input", [0.0, 10.0], D, colour="red", max_ma=15, isrc=D),
            pin(2, "GND", "ground", "power_input", [0.0, 10.0], D, colour="green"),
            pin(3, "OUT", "analogue output 0-2 V (datasheet)", "analog_in", [0.0, 10.0], D, colour="black")],
           comp_facts(C, "colour_sensor"), "sensor", "components/colour_sensor.glb")
    define("ir_track_sensor", "IR track sensor", "128598", C["ir_track_sensor"]["datasheet"], dims("ir_track_sensor"), A, 7,
           [pin(1, "9V", "supply 9 V", "power_input", [0.0, 10.0], A, colour="red"),
            pin(2, "GND", "ground", "power_input", [0.0, 10.0], A, colour="green"),
            pin(3, "S1", "channel 1, push-pull (level-shifted to 24 V on the board)", "digital_io", [0.0, 10.0], A, colour="black"),
            pin(4, "S2", "channel 2, push-pull", "digital_io", [0.0, 10.0], A, colour="yellow")],
           comp_facts(C, "ir_track_sensor"), "sensor", "components/ir_track_sensor.glb")
    define("compressor", "Compressor", "K-24V", C["compressor"]["datasheet"], dims("compressor"), A, 50,
           [pin(1, "+", "supply, from a PLC output", "power_input", V24, V24_SRC, max_ma=70, isrc=B),
            pin(2, "-", "return", "power_input", V24, V24_SRC, max_ma=70, isrc=B)],
           comp_facts(C, "compressor"), "pneumatic", "components/compressor.glb")
    define("solenoid_valve", "3/2-way solenoid valve", "MV-3/2", C["solenoid_valve"]["datasheet"], dims("solenoid_valve"), A, 20,
           [pin(1, "+", "coil, from a PLC output", "power_input", V24, V24_SRC),
            pin(2, "-", "coil return", "power_input", V24, V24_SRC)],
           comp_facts(C, "solenoid_valve"), "pneumatic", "components/solenoid_valve.glb")
    define("lamp", "Oven lamp", "", "536634 Belegungsplan (Leuchte Ofen, Q9)", [15.0, 15.0, 15.0], A, 3,
           [pin(1, "+", "from Q9", "power_input", V24, V24_SRC), pin(2, "-", "return", "power_input", V24, V24_SRC)],
           [rating("Current", "not documented - measure", A)], "lamp")

    # the adaptor PCB: terminals 1-30, both ribbons, the rails and the relays, the valve terminals
    pcb_pins = [pin(t, f"T{t}", "terminal to the PLC", "digital_io", V24, V24_SRC) for t in range(1, 31)]
    pcb_pins += [pin(100 + i, f"ST1.{i}", "ribbon ST1 to the model", "digital_io", V24, V24_SRC) for i in range(1, 21)]
    pcb_pins += [pin(200 + i, f"ST2.{i}", "ribbon ST2 to the model", "digital_io", V24, V24_SRC) for i in range(1, 21)]
    pcb_pins += [pin(300, "+24V_MOTOR", "terminal 1 through a diode: the relays' supply", "power_input", V24, V24_SRC),
                 pin(301, "+24V_SENSOR", "terminal 2 through a diode and a 0.2 A resettable fuse", "power_input", V24, V24_SRC, max_ma=200, isrc=BD),
                 pin(302, "GND", "terminals 3 and 4", "power_input", V24, V24_SRC),
                 pin(303, "9V", "9 V made from 24 V for the trail and colour sensors", "power_input", [0.0, 10.0], BD)]
    for r in range(1, 9):
        n = 400 + r * 10
        pcb_pins += [pin(n, f"R{r}.COM", "changeover relay: to the motor lead", "power_input", V24, V24_SRC),
                     pin(n + 1, f"R{r}.NO", "to +24V_MOTOR", "power_input", V24, V24_SRC),
                     pin(n + 2, f"R{r}.NC", "to GND (the motor brakes)", "power_input", V24, V24_SRC),
                     pin(n + 3, f"R{r}.A1", "coil, from its PLC output", "power_input", V24, V24_SRC)]
    for v in range(1, 5):
        pcb_pins += [pin(500 + v * 2, f"V{v}+", "valve terminal, from its PLC output", "power_input", V24, V24_SRC),
                     pin(501 + v * 2, f"V{v}-", "valve terminal, to GND", "power_input", V24, V24_SRC)]
    define("adaptor_pcb", "Adapterplatine 24V (adaptor PCB)", "", "536634 extended description p.3-4", [160.0, 100.0, 25.0], A, 120, pcb_pins,
           [rating("Inputs", "P-reading: the sensor switches +24 V onto the input", BD),
            rating("Outputs", "P-switching: the PLC switches +24 V to the load", BD),
            rating("Motors", "two changeover relays per bidirectional motor; both off = leads on GND", BD),
            rating("Sensor supply", "diode, then a 0.2 A resettable fuse", BD),
            rating("Speed", "a reduced voltage on terminal 1 slows ALL bidirectional motors at once", BD),
            rating("Freewheel diodes", "integrated for inductive loads", BD)], "board")

    dio_pins = [pin(1, "X4.24V", "main supply (12-24 V)", "power_input", [0.0, 28.8], D),
                pin(2, "X4.0V", "main supply ground", "power_input", [0.0, 28.8], D),
                pin(3, "X2.24V", "I/O supply [assumed pin name: the sheet gives 2 x 4-pole connectors]", "power_input", [0.0, 28.8], D),
                pin(4, "X2.0V", "I/O supply ground [assumed pin name]", "power_input", [0.0, 28.8], D)]
    dio_pins += [pin(10 + i, f"IN{i}", "digital input, 2.4 mA, EN 61131-2 type I/III; counter/encoder capable",
                     "digital_io", [-3.0, 36.0], D, max_ma=2.4, isrc=D) for i in range(1, 15)]
    dio_pins += [pin(30 + i, f"OUT{i}", "high-side output, 500 mA; PWM 40-400 Hz", "digital_io", [0.0, 28.8], D,
                     max_ma=500, isrc=D) for i in range(1, 15)]
    define("revpi_dio", "RevPi DIO", "100197", "Datenblatt_RevPi_DIO.pdf", [22.5, 110.5, 96.0], D, 100, dio_pins,
           [rating("Dimensions", "96 x 22.5 x 110.5 mm (H x B x T)", D),
            rating("Supply", "12-24 V DC -5 % / +20 %", D), rating("Power", "1.5 W max", D),
            rating("Inputs", "14, current limited to 2.4 mA at 24 V, EN 61131-2 type I and III", D),
            rating("Counters", "at most 6 counters, or 12 inputs as 6 encoders; 2 kHz (500 Hz encoder sequence)", D),
            rating("Debounce", "off, 25 us, 750 us or 3 ms - common to all inputs", D),
            rating("Outputs", "14, 500 mA high-side or 100 mA push-pull; PWM 40/80/160/200/400 Hz", D),
            rating("Watchdog", "outputs reset after 50 ms / 500 ms without the controller, 9 ms without the CPU", D),
            rating("Input protection", "-3 V to +36 V", D)], "plc")
    define("revpi_core", "RevPi Core", "100359", "Datenblatt_RevPi_Cores.pdf", [22.5, 110.5, 96.0], D, 200,
           [pin(1, "24V", "supply 12-24 V DC -15 % / +20 %", "power_input", [0.0, 28.8], D),
            pin(2, "0V", "supply ground", "power_input", [0.0, 28.8], D)],
           [rating("Dimensions", "96 x 22.5 x 110.5 mm (H x B x T)", D),
            rating("Supply", "12-24 V DC -15 % / +20 %, reverse-polarity protected", D),
            rating("Power", "10 W max (with 900 mA USB)", D),
            rating("Hold-up", "10 ms through supply dips only at 20.4-28.8 V", D),
            rating("CPU", "Broadcom BCM2711, quad Cortex-A72", D)], "plc")
    define("psu", "Mean Well WDR-120-24", "WDR-120-24", "PowerSupply WDR DIN rail.pdf", [40.0, 125.2, 113.5], A, 600,
           # Mean Well's WDR-120 spec sheet: TB1 FG / AC/L2 / AC/L1 (two phases, no neutral);
           # TB2 the DC OK relay contact (1, 2), -V (3), +V (4)
           [pin(1, "FG", "TB1.1: frame ground (to PE)", "power_input", [0.0, 550.0], D),
            pin(2, "AC/L2", "TB1.2: AC input, phase 2", "power_input", [0.0, 550.0], D),
            pin(3, "AC/L1", "TB1.3: AC input, phase 1", "power_input", [0.0, 550.0], D),
            pin(4, "DCOK.1", "TB2.1: DC OK relay contact (30 V / 1 A)", "digital_io", [0.0, 30.0], D, max_ma=1000, isrc=D),
            pin(5, "DCOK.2", "TB2.2: DC OK relay contact, closed while the output is good", "digital_io", [0.0, 30.0], D, max_ma=1000, isrc=D),
            pin(6, "-V", "TB2.3: 0 V", "power_input", [0.0, 28.8], D, max_ma=5000, isrc=D),
            pin(7, "+V", "TB2.4: 24 V DC output, 5 A", "power_input", [0.0, 28.8], D, max_ma=5000, isrc=D)],
           [rating("Dimensions", "40 x 125.2 x 113.5 mm (W x H x D, +-1 mm)", D),
            rating("Output", "24 V, 5 A, 120 W (WDR-120-24); adjustable 24-29 V; 91 % efficient", D),
            rating("Input", "180-550 VAC between any two phases (no neutral), 1.4 A", D),
            rating("DC OK", "relay contact, closed while the output is good, 30 V / 1 A", D),
            rating("Choice", "the factory needs 24 V / 4.8 A (536634 p.2): the WDR-120-24 is the 5 A model", DV),
            rating("Mounting", "vertical, input terminals at the bottom; 40 mm free above", D)], "power")

    # ---- the upgraded factory's parts (sizes and ratings from the upgrade design: ASSUMED parts)
    io_note = "750-series-like remote I/O, sized in io_nodes.py - an assumed product, not a datasheet"
    io = lambda pid, name, size, pins_, ratings_: define(pid, name, "", "stf-cad io_nodes.py", size, DS, 40, pins_, ratings_ + [rating("Product", io_note, DS)], "plc")
    io("io_coupler", "Modbus TCP bus coupler", [51.0, 100.0, 72.0],
       [pin(1, "24V", "system supply", "power_input", V24, DS), pin(2, "0V", "system ground", "power_input", V24, DS)],
       [rating("Network", "2 x RJ45, Modbus TCP, from the cabinet switch", DS)])
    io("io_supply_slice", "Field-supply slice", [12.0, 100.0, 68.0],
       [pin(1, "24V_ACT", "actuator 24 V from K1/K2: feeds every DO slice after it", "power_input", V24, DS),
        pin(2, "0V", "field ground", "power_input", V24, DS)], [])
    io("io_di8", "DI slice, 8 channels", [12.0, 100.0, 68.0],
       [pin(k, f"{k}", f"digital input {k}, 24 V type 1/3", "digital_io", [-3.0, 30.0], A) for k in range(1, 9)],
       [rating("Inputs", "8 x 24 V, EN 61131-2 type 1/3", A)])
    io("io_do8", "DO slice, 8 channels", [12.0, 100.0, 68.0],
       [pin(k, f"{k}", f"digital output {k}, from the field supply", "digital_io", V24, A, max_ma=500, isrc=A) for k in range(1, 9)],
       [rating("Outputs", "8 x 24 V, 0.5 A, short-circuit proof", A)])
    io("io_cnt", "Counter slice, 1 channel", [12.0, 100.0, 68.0],
       [pin(1, "A", "encoder channel A", "digital_io", [-3.0, 30.0], A), pin(2, "B", "encoder channel B", "digital_io", [-3.0, 30.0], A)],
       [rating("Counter", "A/B quadrature, up to 1 kHz", DS)])
    io("io_ai2", "AI slice, 2 channels", [12.0, 100.0, 68.0],
       [pin(k, f"{k}", f"analogue input {k}, 0-10 V", "analog_in", [0.0, 10.0], A) for k in (1, 2)],
       [rating("Inputs", "2 x 0-10 V (the colour sensor gives 0-2 V: 1/5 of the range)", A)])
    io("io_iol4", "IO-Link master slice, 4 ports", [12.0, 100.0, 68.0],
       [pin(k, f"{k}", f"IO-Link port {k} (C/Q)", "digital_io", V24, A) for k in range(1, 5)],
       [rating("Ports", "4 x IO-Link, for the RFID heads (Upgrade 4)", DS)])
    define("eth_switch", "Industrial Ethernet switch, 5 ports", "", "stf-cad cabinet (Upgrade 3)", [96.0, 30.0, 95.0], DS, 200,
           [pin(1, "24V", "supply", "power_input", V24, A), pin(2, "0V", "ground", "power_input", V24, A)],
           [rating("Ports", "5: the four nodes and the controller", DS), rating("Power", "not documented - measure", A)], "plc")
    define("ecb_4ch", "Electronic circuit breaker, 4 channels", "", "stf-cad cabinet (Upgrade 3)", [96.0, 45.0, 90.0], DS, 250,
           [pin(1, "IN+", "24 V in", "power_input", V24, A), pin(2, "IN-", "ground", "power_input", V24, A)]
           + [pin(2 + k, f"CH{k}", f"fused, monitored 24 V feed {k}", "power_input", V24, A, max_ma=2000, isrc=A) for k in range(1, 5)],
           [rating("Channels", "4: one fused, monitored 24 V feed per node", DS), rating("Trip current", "not chosen yet - [assumed] 2 A per channel", A)], "power")
    define("safety_relay", "Safety relay K0, 2-channel", "", "stf-cad cabinet (Upgrade 2)", [96.0, 22.5, 110.5], DS, 200,
           [pin(1, "A1", "supply", "power_input", V24, A), pin(2, "A2", "ground", "power_input", V24, A),
            pin(3, "S", "the guard and e-stop circuit (closed: safe)", "power_input", V24, A),
            pin(4, "13", "safety output 1: holds K1", "power_input", V24, A), pin(5, "23", "safety output 2: holds K2", "power_input", V24, A)],
           [rating("Function", "2-channel, monitored manual reset, EDM input", DS)], "safety")
    define("contactor", "Force-guided contactor", "", "stf-cad cabinet (Upgrade 2)", [90.0, 22.5, 100.0], DS, 250,
           [pin(1, "A1", "coil, from K0", "power_input", V24, A), pin(2, "A2", "coil ground", "power_input", V24, A),
            pin(3, "1", "main contact in", "power_input", V24, A), pin(4, "2", "main contact out", "power_input", V24, A)],
           [rating("Function", "force-guided: its NC aux reads back to K0 (EDM)", DS)], "safety")
    for pid, name, what in (("reed_switch", "Reed switch on a cylinder", "the piston's magnet closes it"),
                            ("vacuum_switch", "Vacuum switch", "closes at -0.3 bar: the cup is sealed on a part"),
                            ("pressure_switch", "Air pressure switch contact", "closes while the air station is at pressure")):
        define(pid, name, "", "stf-cad control.py U5_SENSORS (Upgrade 5)", [20.0, 10.0, 10.0], A, 5,
               [pin(1, "+", "from the +24 V sensor rail", "digital_io", V24, A), pin(2, "OUT", "to its DI channel", "digital_io", V24, A)]
               + ([pin(3, "P1", "pump contact in, from the actuator 24 V", "power_input", V24, A),
                   pin(4, "P2", "pump contact out, to the compressor", "power_input", V24, A)] if pid == "pressure_switch" else []),
               [rating("Function", what, DS)] + ([rating("Pump", "its other contact runs the compressor between 0.6 and 0.8 bar", DS)] if pid == "pressure_switch" else []),
               "switch")
    define("rfid_head", "RFID read/write head (IO-Link)", "", "stf-cad upgrade (Upgrade 4)", [40.0, 40.0, 20.0], A, 60,
           [pin(1, "L+", "IO-Link supply", "power_input", V24, A), pin(2, "L-", "ground", "power_input", V24, A),
            pin(3, "C/Q", "IO-Link data", "digital_io", V24, A)],
           [rating("Function", "reads the mould's tag at a belt read point", DS)], "sensor")
    return P_


# ------------------------------------------------------------------ the factory's wiring
VARIANTS = ("original", "upgraded")
# Upgrade 1's central air station replaced the module compressors (control.RETIRED)
RETIRED = {"vgr": ("Q7",), "oven": ("Q10",), "sorting": ("Q2",)}
# Upgrade 5's sensors (control.U5_SENSORS): module -> signal -> (the CAD part it sits on, kind)
U5 = {"oven": {"I10": ("Q13_door_cylinder", "reed_switch"), "I11": ("Q13_door_cylinder", "reed_switch"),
               "I12": ("Q12_lower_cylinder", "reed_switch"), "I13": ("Q12_lower_cylinder", "reed_switch"),
               "I14": ("Q14_pusher_cylinder", "reed_switch"), "I15": ("Q14_pusher_cylinder", "reed_switch")},
      "vgr": {"I4": ("vacuum_valve", "vacuum_switch"), "I5": ("air_pressure_switch", "pressure_switch")}}
NODE_ORDER = ("hbw", "vgr", "oven", "sorting")   # the ECB's channels, one per node [assumed order]


def build(controller, components, cad, variant):
    """The parts, wires, supplies and contacts of one variant:
         original  each module's board to its own RevPi DIO (the occupancy plans), the supply
                   straight to the boards - the factory as fischertechnik documents it
         upgraded  the board's terminals to a remote I/O node beside it (io_nodes.py), a fused
                   ECB channel per node, the actuator 24 V through the safety contactors K1/K2,
                   the central air station instead of the module compressors, and the sensors
                   Upgrades 4 and 5 added - the factory the 3D twin shows"""
    assert variant in VARIANTS
    up = variant == "upgraded"
    defs = parts(components)
    placed, nets, contacts, supplies, controls, findings = [], [], [], [], [], []
    net_of = {}  # (inst, pin) -> net id
    alias = {}   # a net's name -> the net it was merged into ("hbw.gnd" -> "0V")
    resolve = lambda nid: resolve(alias[nid]) if nid in alias and alias[nid] != nid else nid

    def place(inst, pid, module, cad_part=None):
        placed.append({"instance_id": inst, "part_id": pid, "module": module, "cad": cad_part})

    def join(net_id, *refs):
        """Puts pins on one net (merging into an existing net if a pin is on one already)."""
        refs = [r for r in refs if r]
        named = resolve(net_id)
        existing = next((net_of[r] for r in refs if r in net_of), None)
        nid = existing or named
        if existing and named != existing and any(n["net_id"] == named for n in nets):
            refs = refs + [(c["part_instance"], c["pin_label"]) for c in next(n for n in nets if n["net_id"] == named)["connections"][:1]]
        alias[net_id] = nid
        net = next((n for n in nets if n["net_id"] == nid), None)
        if not net:
            net = {"net_id": nid, "connections": []}
            nets.append(net)
        for r in refs:
            if r in net_of and net_of[r] != nid:  # merge the other net into this one
                other = next(n for n in nets if n["net_id"] == net_of[r])
                alias[other["net_id"]] = nid
                for q in other["connections"]:
                    net_of[(q["part_instance"], q["pin_label"])] = nid
                    net["connections"].append(q)
                nets.remove(other)
            if r not in net_of:
                net_of[r] = nid
                net["connections"].append({"part_instance": r[0], "pin_label": r[1]})
        return nid

    def contact(cid, inst, a, b, closed):
        contacts.append({"id": cid, "a": {"part_instance": inst, "pin_label": a},
                         "b": {"part_instance": inst, "pin_label": b}, "closed": closed})

    R = lambda inst, label: (inst, label)
    place("psu", "psu", "cabinet", "psu_wdr120")
    place("core", "revpi_core", "cabinet", "revpi_core_3")
    supplies.append({"id": "psu", "positive": {"part_instance": "psu", "pin_label": "+V"},
                     "negative": {"part_instance": "psu", "pin_label": "-V"}, "volts": 24})
    join("24V", ("psu", "+V"), ("core", "24V"))
    join("0V", ("psu", "-V"), ("core", "0V"))
    if up:
        place("switch", "eth_switch", "cabinet", "eth_switch")
        place("ecb", "ecb_4ch", "cabinet", "ecb_4ch")
        place("K0", "safety_relay", "cabinet", "safety_relay_K0")
        place("K1", "contactor", "cabinet", "contactor_K1")
        place("K2", "contactor", "cabinet", "contactor_K2")
        join("24V", R("switch", "24V"), R("ecb", "IN+"), R("K0", "A1"))
        join("0V", R("switch", "0V"), R("ecb", "IN-"), R("K0", "A2"), R("K1", "A2"), R("K2", "A2"))
        # the safety circuit: K0's two outputs hold K1 and K2; their NO contacts in series switch
        # the actuator 24 V for every node (Upgrade 2). Closed: the guards are shut, reset done.
        join("24V", R("K1", "1"))
        join("K0.out1", R("K0", "13"), R("K1", "A1"))
        join("K0.out2", R("K0", "23"), R("K2", "A1"))
        contact("safety.K0.13", "K0", "S", "13", True)
        contact("safety.K0.23", "K0", "S", "23", True)
        join("24V", R("K0", "S"))
        join("K1.out", R("K1", "2"), R("K2", "1"))
        join("24V_act", R("K2", "2"))
        contact("safety.K1", "K1", "1", "2", True)
        contact("safety.K2", "K2", "1", "2", True)
        for k in range(1, 5):
            contact(f"ecb.CH{k}", "ecb", "IN+", f"CH{k}", True)
        # Upgrade: the supply's DC OK contact to the PLC (the warehouse node's first spare input,
        # DI2.1). The PLC sees the 24 V sag or fail before the loads do, and logs it: the supply
        # is monitored, not assumed (it was wired to nothing).
        join("24V", R("psu", "DCOK.1"))
        contact("psu.dc_ok", "psu", "DCOK.1", "DCOK.2", True)

    io = {}
    alloc = cad["io3"]["allocation"] if up else None
    for m, mod in controller["modules"].items():
        pcb = f"{m}.pcb"
        place(pcb, "adaptor_pcb", m, {"hbw": "adapter_pcb_24V"}.get(m, f"{m}_pcb"))
        st3 = {int(k): v for k, v in mod["st3"].items()}
        term_of = {v: k for k, v in st3.items() if v}
        retired = RETIRED.get(m, ()) if up else ()

        # ---- power to the board, and the PLC side
        if not up:
            plan = read_plan(os.path.join(DOCS, PLANS[m]))
            dio = f"{m}.dio"
            place(dio, "revpi_dio", m)
            join("24V", R(pcb, "T1"), R(pcb, "T2"), R(dio, "X4.24V"), R(dio, "X2.24V"))
            join("0V", R(pcb, "T3"), R(pcb, "T4"), R(dio, "X4.0V"), R(dio, "X2.0V"))
            for term, (sig, rp, ch) in sorted(plan.items()):
                if term_of.get(sig) not in (None, term):
                    findings.append(f"{m}: the plan puts {sig} on terminal {term}, the board's header on {term_of[sig]}")
                if ch is None:
                    findings.append(f"{m}: {sig} (terminal {term}) has no RevPi channel in the plan - not wired to the PLC")
                    continue
                join(f"{m}.{sig}", R(pcb, f"T{term}"), R(dio, ch))
                io.setdefault(m, []).append({"signal": sig, "terminal": term, "revpi_terminal": rp, "channel": ch})
            for t, sig in st3.items():
                if sig and t not in plan and not sig.startswith(("+", "G")):
                    findings.append(f"{m}: the board's terminal {t} ({sig}) is not in the occupancy plan")
        else:
            node = f"{m}.node"
            place(node, "io_coupler", m, f"io_{m}_coupler")
            place(f"{m}.node.supply", "io_supply_slice", m, f"io_{m}_supply")
            ch = NODE_ORDER.index(m) + 1
            # the node's system and the board's sensor rail from the module's ECB channel; the
            # board's motor relays (terminal 1) and the DO slices from the switched actuator 24 V
            join(f"ecb.CH{ch}", R("ecb", f"CH{ch}"), R(node, "24V"), R(pcb, "T2"))
            join("24V_act", R(f"{m}.node.supply", "24V_ACT"), R(pcb, "T1"))
            join("0V", R(node, "0V"), R(f"{m}.node.supply", "0V"), R(pcb, "T3"), R(pcb, "T4"))
            slices = {}
            for a in (x for x in alloc if x["module"] == m):
                sid = f"{m}.node.{a['slice']}"
                if sid not in slices:
                    slices[sid] = a["type"]
                    place(sid, {"DI": "io_di8", "DO": "io_do8", "CNT": "io_cnt", "AI": "io_ai2", "IOL": "io_iol4"}[a["type"]], m, f"io_{m}_{a['slice']}")
                if not a["signal"]:
                    continue
                if a["type"] == "CNT":
                    s1, s2 = a["signal"].split("/")
                    join(f"{m}.{s1}", R(pcb, f"T{term_of[s1]}"), R(sid, "A"))
                    join(f"{m}.{s2}", R(pcb, f"T{term_of[s2]}"), R(sid, "B"))
                    for s in (s1, s2):
                        io.setdefault(m, []).append({"signal": s, "terminal": term_of[s], "revpi_terminal": None, "channel": f"{a['slice']}.{'A' if s == s1 else 'B'}"})
                    continue
                pin_ = f"{a['ch']}"
                on_board = a["signal"] in term_of
                join(f"{m}.{a['signal']}", R(sid, pin_), R(pcb, f"T{term_of[a['signal']]}") if on_board else None)
                kind = "OUT" if a["type"] == "DO" else "IN"
                io.setdefault(m, []).append({"signal": a["signal"], "terminal": term_of.get(a["signal"]), "revpi_terminal": None,
                                             "channel": f"{a['slice']}.{a['ch']}", "kind": kind})
            if m == "hbw":
                join("hbw.PS_OK", R("psu", "DCOK.2"), R("hbw.node.DI2", "1"))
                io.setdefault(m, []).append({"signal": "PS_OK", "terminal": None, "revpi_terminal": None,
                                             "channel": "DI2.1", "kind": "IN"})
            for sig in term_of:
                if sig[0] in "IQAB" and sig not in retired and not any(r["signal"] == sig for r in io.get(m, [])):
                    findings.append(f"{m}: the board's {sig} (terminal {term_of[sig]}) has no channel on the node")
        join(f"{m}.24V_motor", R(pcb, "T1"), R(pcb, "+24V_MOTOR"))
        join(f"{m}.24V_sensor", R(pcb, "T2"), R(pcb, "+24V_SENSOR"))
        join(f"{m}.gnd", R(pcb, "T3"), R(pcb, "GND"))
        supplies.append({"id": f"{m}.9V", "positive": {"part_instance": pcb, "pin_label": "9V"},
                         "negative": {"part_instance": pcb, "pin_label": "GND"}, "volts": 9})

        relays = {}
        for pair, r in mod["relays"].items():
            if r:
                ra, rb = (int(x) for x in pair.replace("R", "").split("/"))
                relays[r["a"]] = (ra, r["motor"])
                relays[r["b"]] = (rb, r["motor"])
        for q, (r, motor) in relays.items():
            # the coil from the PLC output (through its terminal); the contacts: COM-NC closed at rest
            join(f"{m}.{q}", R(pcb, f"T{term_of[q]}"), R(pcb, f"R{r}.A1"))
            join(f"{m}.24V_motor", R(pcb, f"R{r}.NO"))
            join(f"{m}.gnd", R(pcb, f"R{r}.NC"))
            for side, closed in (("NC", True), ("NO", False)):
                contact(f"{m}.R{r}.{side}", pcb, f"R{r}.COM", f"R{r}.{side}", closed)
            controls.append({"output": f"{m}.{q}", "closes": f"{m}.R{r}.NO", "opens": f"{m}.R{r}.NC", "motor": f"{m}.{motor}"})

        valves = {v["q"]: name for name, v in mod["valves"].items()}
        valve_cad = {"vgr": {"V1": "vacuum_valve"}, "sorting": {"V1": "valve_weiss", "V2": "valve_rot", "V3": "valve_blau"},
                     "oven": {"V1": "V1_valve_vakuum", "V2": "V2_valve_senken", "V3": "V3_valve_ofentuer", "V4": "V4_valve_schieber"}}
        for q, vname in valves.items():
            join(f"{m}.{q}", R(pcb, f"T{term_of[q]}"), R(pcb, f"{vname}+"))
            join(f"{m}.gnd", R(pcb, f"{vname}-"))
            inst = f"{m}.{vname}"
            place(inst, "solenoid_valve", m, valve_cad.get(m, {}).get(vname))
            join(f"{m}.{q}.valve", R(pcb, f"{vname}+"), R(inst, "+"))
            join(f"{m}.gnd", R(inst, "-"))

        # the model side: each ribbon pin, by its signal
        rows = [(f"ST1.{p['pin']}", p) for p in mod["st1"] or []] + [(f"ST2.{p['pin']}", p) for p in mod["st2"] or []]
        enc = {ch_: motor for motor, chs in mod["encoders"].items() for ch_ in chs}
        motors_seen, lamps, barriers = {}, [], []
        for i, (stp, p) in enumerate(rows):
            sig, fn = p["signal"], (p["function"] or "").lower()
            nxt = rows[i + 1][0] if i + 1 < len(rows) and rows[i + 1][1]["signal"] == "+24V" else None
            if sig is None:
                continue
            if sig == "+24V":
                join(f"{m}.24V_sensor", R(pcb, stp))
                if "lamp" in fn:
                    lamps.append(stp)
                continue
            if sig == "GND":
                join(f"{m}.gnd", R(pcb, stp))
                continue
            if sig == "9V":
                join(f"{m}.9V", R(pcb, stp), R(pcb, "9V"))
                continue
            if sig[0] in "IAB" and sig in term_of:
                join(f"{m}.{sig}", R(pcb, stp), R(pcb, f"T{term_of[sig]}"))
            if sig[0] == "I":
                inst = f"{m}.{sig}"
                if "barrier" in fn or "phototransistor" in fn:
                    place(inst, "phototransistor", m, ("tag", sig, "rx"))
                    join(f"{m}.24V_sensor", R(inst, "+"))
                    join(f"{m}.{sig}", R(inst, "-"))
                    barriers.append(sig)
                else:
                    place(inst, "mini_switch", m, ("tag", sig, None))
                    join(f"{m}.24V_sensor", R(inst, "1"))
                    join(f"{m}.{sig}", R(inst, "3"))
                    contact(f"{inst}.NO", inst, "1", "3", False)
                if not nxt:
                    findings.append(f"{m}: {sig} on {stp} has no +24V sensor pin beside it")
            elif sig in ("A1", "A2"):
                inst = f"{m}.trail"
                if not any(x["instance_id"] == inst for x in placed):
                    place(inst, "ir_track_sensor", m, ("tag", "A1", None))
                    join(f"{m}.9V", R(inst, "9V"))
                    join(f"{m}.gnd", R(inst, "GND"))
                join(f"{m}.{sig}", R(inst, "S1" if sig == "A1" else "S2"))
            elif sig == "A4":
                inst = f"{m}.A4"
                place(inst, "colour_sensor", m, ("tag", "A4", None))
                join(f"{m}.9V", R(inst, "9V"))
                join(f"{m}.gnd", R(inst, "GND"))
                join(f"{m}.{sig}", R(pcb, stp), R(inst, "OUT"), R(pcb, f"T{term_of[sig]}") if sig in term_of else None)
            elif sig[0] == "B":
                inst = f"{m}.{enc[sig]}"
                join(f"{m}.{sig}", R(inst, "PULS1" if int(sig[1:]) % 2 else "PULS2"))
            elif sig[0] == "Q":
                mm = re.search(r"\((M\d)", p["function"] or "")
                if sig in relays:
                    r, motor = relays[sig]
                    inst = f"{m}.{motor}"
                    if inst not in motors_seen:
                        motors_seen[inst] = 0
                        has_enc = motor in mod["encoders"]
                        place(inst, "encoder_motor" if has_enc else "s_motor", m, ("name", f"{motor}_", None))
                        if has_enc:
                            join(f"{m}.24V_sensor", R(inst, "ENC+24V"))
                            join(f"{m}.gnd", R(inst, "ENC0V"))
                    lead = "M+" if motors_seen[inst] == 0 else "M-"
                    motors_seen[inst] += 1
                    join(f"{m}.{motor}.{lead}", R(pcb, stp), R(pcb, f"R{r}.COM"), R(inst, lead))
                elif sig in valves or sig in retired:
                    pass  # on the valve terminals (done above), or retired by the central air station
                else:
                    # a load switched straight by the PLC: its return is the GND pin before it
                    if "compressor" in fn:
                        inst, pid, where = f"{m}.compressor", "compressor", ("tag", sig, None)
                    elif "lamp" in fn:
                        inst, pid, where = f"{m}.lamp", "lamp", ("tag", sig, None)
                    else:
                        inst, pid, where = f"{m}.{mm.group(1) if mm else sig}", "s_motor", ("tag", sig, None)
                    place(inst, pid, m, where)
                    join(f"{m}.{sig}", R(pcb, stp), R(pcb, f"T{term_of[sig]}"), R(inst, "+" if pid != "s_motor" else "M+"))
                    join(f"{m}.gnd", R(inst, "-" if pid != "s_motor" else "M-"))
        # the light-barrier lamps: one per barrier, on the module's lamp pins; the CAD draws each as
        # the barrier's transmitter
        for sig in barriers:
            if not lamps:
                findings.append(f"{m}: light barrier {sig} has no lamp pins")
                break
            inst = f"{m}.{sig}.lamp"
            place(inst, "lb_lamp", m, ("tag", sig, "tx"))
            join(f"{m}.24V_sensor", R(inst, "+"))
            join(f"{m}.gnd", R(inst, "-"))

        if up:
            # Upgrade 5's sensors, straight to the node (they are not on the board's ribbons)
            for sig, (host, kind) in U5.get(m, {}).items():
                inst = f"{m}.{sig}"
                place(inst, kind, m, ("name", host, None))
                join(f"{m}.24V_sensor", R(inst, "+"))
                join(f"{m}.{sig}", R(inst, "OUT"))
                contact(f"{inst}.NO", inst, "+", "OUT", False)
            if m == "hbw":
                # Upgrade 4's RFID heads on the node's IO-Link slice
                for k, rf in enumerate(("RF1", "RF2")):
                    inst = f"{m}.{rf}"
                    place(inst, "rfid_head", m, ("tag", rf, None))
                    join(f"{m}.24V_sensor", R(inst, "L+"))
                    join(f"{m}.gnd", R(inst, "L-"))
                    join(f"{m}.{rf}", R(inst, "C/Q"))
    if up:
        # the central air station's compressor (Upgrade 1)
        # its pressure switch runs it (0.6-0.8 bar) from the actuator 24 V - no PLC output; the
        # switch's second contact is the arm's I5, "air pressure OK"
        place("air.compressor", "compressor", "air", ("upgrade", "Q10_central_compressor", None))
        join("0V", R("air.compressor", "-"))
        join("24V_act", R("vgr.I5", "P1"))
        join("air.pump", R("vgr.I5", "P2"), R("air.compressor", "+"))
        contact("vgr.I5.pump", "vgr.I5", "P1", "P2", True)
    return defs, placed, nets, contacts, supplies, controls, io, findings


# ------------------------------------------------------------------ placement from the CAD
def placement(placed, cad, findings):
    """Each part where the CAD export draws it: its tagged part's box in factory mm (the module's
    placement applied, a moving frame at its zero pose), and the module's turn as the part's."""
    import wiring as W
    srcs = {"hbw": cad["parts"], "vgr": cad["vgr"]["parts"], "oven": cad["oven"]["parts"], "sorting": cad["sorting"]["parts"]}
    turn = {"hbw": cad["factory"]["placement"]["rotate_deg"], "vgr": 0.0, "oven": cad["factory"]["oven_placement"]["rotate_deg"],
            "sorting": cad["factory"]["sort_placement"]["rotate_deg"]}
    io_parts = {p["n"]: p for p in cad["io3"]["parts"]}
    up_parts = {p["n"]: p for p in cad["upgrade"]["parts"]}
    ax, ay = cad["plc"]["at"]
    plc_parts = {p["n"]: p for p in cad["plc"]["parts"]}
    ident = lambda x, y: (x, y)

    def find(module, how):
        src = srcs.get(module, [])
        if isinstance(how, str):
            return next((p for p in src if p["n"] == how), None)
        kind, key, half = how
        if kind == "tag":
            hits = [p for p in src if (p.get("tag") or "").split(" ")[0].split("/")[0] == key or p.get("tag") == key]
            if half:
                hits = [p for p in hits if p["n"].endswith(f"_{half}")] or hits
            return hits[0] if hits else None
        if kind == "name":
            hits = [p for p in src if p["n"].startswith(key) or p["n"] == key]
            # a motor's name prefix also names its shaft and pulleys: the motor is the tagged one
            return next((p for p in hits if p.get("tag")), hits[0] if hits else None)
        return None

    for p in placed:
        how, m, box, frame, deg, src = p.pop("cad"), p["module"], None, "world", 0.0, None
        if p["module"] == "cabinet" and how in plc_parts:
            d = plc_parts[how]
            box = [d["p"][0] + ax, d["p"][1] + ay, d["p"][2], d["p"][0] + ax + d["s"][0], d["p"][1] + ay + d["s"][1], d["p"][2] + d["s"][2]]
            src = f"plc/{how}"
        elif isinstance(how, str) and how in io_parts:
            d = io_parts[how]
            box = W._box_f(d, ident)
            src = f"io3/{how}"
        elif isinstance(how, tuple) and how[0] == "upgrade":
            d = up_parts.get(how[1])
            box = d and W._box_f(d, ident)
            src = d and f"upgrade/{how[1]}"
        elif how is not None and m in srcs:
            d = find(m, how)
            if d is None and isinstance(how, tuple) and how[0] == "name" and m == "vgr":
                d = up_parts.get(how[1])  # the arm's air pressure switch sits on the air station
                if d:
                    box, src = W._box_f(d, ident), f"upgrade/{how[1]}"
            elif d is not None:
                box = W._box_f(d, W._tf(m))
                frame, deg, src = d.get("f", "world"), turn[m], f"{m}/{d['n']}"
        if box is None:
            p["world_position_mm"], p["world_quaternion"], p["placed"] = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0], None
            continue
        h = math.radians(deg) / 2
        p["world_position_mm"] = [round((box[i] + box[i + 3]) / 2, 3) for i in range(3)]
        p["world_quaternion"] = [0.0, 0.0, round(math.sin(h), 12), round(math.cos(h), 12)]
        p["placed"] = {"cad": src, "box_mm": [round(v, 3) for v in box], "frame": frame}
    unplaced = [p["instance_id"] for p in placed if not p["placed"]]
    if unplaced:
        findings.append(f"not in the CAD export, so not placed in 3D: {', '.join(unplaced)}")


# ------------------------------------------------------------------ rating checks
def checks(defs, placed, nets, io, controller, controls, cad, variant):
    out = []
    up = variant == "upgraded"

    def add(what, ok, detail, src, severity="fail"):
        """severity: what a failed check is - "fail" (it cannot work), "warn" (a limit, met in
        normal running)"""
        out.append({"check": what, "ok": ok, "severity": "ok" if ok else severity, "detail": detail, "source": src})

    count = lambda pid: sum(1 for p in placed if p["part_id"] == pid)
    if not up:
        for m, rows in io.items():
            ins = [r for r in rows if r["channel"].startswith("IN")]
            outs = [r for r in rows if r["channel"].startswith("OUT")]
            counters = [r for r in ins if r["signal"].startswith("B")]
            add(f"{m}: inputs on one DIO", len(ins) <= 14, f"{len(ins)} of 14", D)
            add(f"{m}: outputs on one DIO", len(outs) <= 14, f"{len(outs)} of 14", D)
            add(f"{m}: counter inputs", len(counters) <= 12 and len(counters) // 2 <= 6,
                f"{len(counters)} inputs = {len(counters) // 2} encoders of the DIO's 6", D)
        for label, rpm in (("at the axes' 214 rpm (lab)", 214), ("unloaded, 440 rpm (datasheet)", 440)):
            f = rpm * 75 / 60
            add(f"encoder rate {label}", f <= 500, f"{f:.0f} Hz per channel against the encoder's 1 kHz and the DIO's 500 Hz encoder sequence"
                + ("" if f <= 500 else " - an unloaded motor would lose counts; the axes run loaded"), DV, "warn")
        add("light-barrier input current", 2.4 <= 5, "the DIO input draws 2.4 mA; the board allows at most 5 mA through a phototransistor (15 mA rated)", D)
        add("compressor on a DIO output", 70 <= 500, "70 mA (booklet) of 500 mA", B)
    else:
        # every node keeps a fifth of each channel type free (io_nodes.SPARE_MIN)
        alloc = cad["io3"]["allocation"]
        for m in NODE_ORDER:
            for t in sorted({a["type"] for a in alloc if a["module"] == m}):
                chans = [a for a in alloc if a["module"] == m and a["type"] == t]
                used = sum(1 for a in chans if a["signal"])
                spare = 1 - used / len(chans)
                add(f"{m} node: {t} spare", spare >= 0.2, f"{used} of {len(chans)} channels used, {spare:.0%} spare (the design keeps 20 %)", DS)
        f = 440 * 75 / 60
        add("encoder rate, unloaded 440 rpm", f <= 1000, f"{f:.0f} Hz per channel against the counter slice's 1 kHz", DV)
        add("colour sensor on the AI slice", False, "0-2 V (datasheet) on a 0-10 V input: a fifth of the range, five times coarser than it could be", D, "warn")
    add("unidirectional S-motor on an output", 300 <= 500, "300 mA max (booklet) of 500 mA", B)

    # the inventory against the booklet's own totals for the whole factory (536634 p.2)
    F = controller["factory"]
    have = {"reference switches": count("mini_switch"), "light barriers": count("phototransistor"),
            "encoders": count("encoder_motor"), "compressors": count("compressor"), "solenoid valves": count("solenoid_valve"),
            "lamps": count("lamp")}
    for k, n in have.items():
        want = 1 if up and k == "compressors" else F[k]
        add(f"inventory: {k}", n == want, f"{n} wired, {want} " + ("(the central air station replaces the booklet's 3)" if up and k == "compressors" else "in the booklet"), BD)
    bi = len({c["motor"] for c in controls})
    uni = count("s_motor") + count("encoder_motor") - bi
    add("inventory: bidirectional motors", bi == F["bidirectional motors"], f"{bi} on relay pairs, {F['bidirectional motors']} in the booklet", BD)
    add("inventory: unidirectional motors", uni == F["unidirectional motors"], f"{uni} switched directly, {F['unidirectional motors']} in the booklet", BD)
    if up:
        added = {k: count(k) for k in ("reed_switch", "vacuum_switch", "pressure_switch", "rfid_head")}
        add("inventory: the upgrades' sensors", True, ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in added.items()), DS)

    # every PLC channel reaches a field part: its net holds a pin beyond the PLC and the board
    dead = []
    for n in nets:
        insts = {c["part_instance"] for c in n["connections"]}
        plc = {i for i in insts if ".dio" in i or ".node" in i}
        # a load on the board counts: a relay coil (R*.A1) or a valve terminal (V*+)
        board_load = any(c["part_instance"].endswith(".pcb") and re.match(r"(R\d\.A1|V\d\+)$", c["pin_label"]) for c in n["connections"])
        if plc and not board_load and not insts - plc - {i for i in insts if i.endswith(".pcb")}:
            dead.append(n["net_id"])
    add("every PLC channel reaches a field part", not dead, ", ".join(dead) or "all wired through", DV)

    # the supply budget
    motors = sum(600 if p["part_id"] == "encoder_motor" else 300 for p in placed if p["part_id"] in ("encoder_motor", "s_motor"))
    comps = 70 * count("compressor")
    if up:
        logic, what = 10000 / 24 + 3000 / 24 + 4 * 2000 / 24, "Core 10 W, switch 3 W [assumed], 4 couplers 2 W [assumed]"
    else:
        logic, what = 4 * (1500 / 24) + 10000 / 24, "4 DIOs 1.5 W, Core 10 W"
    total = motors + comps + logic
    add("supply budget, everything at its maximum at once", total <= 5000,
        f"motors {motors:.0f} mA + compressors {comps:.0f} mA + controls {logic:.0f} mA ({what}) = {total:.0f} mA of 5000 mA; "
        "the booklet sizes the factory at 4.8 A, so not every motor runs at its maximum at once", DV, "warn")
    run = sum(320 if p["part_id"] == "encoder_motor" else 225 for p in placed if p["part_id"] in ("encoder_motor", "s_motor")) + comps + logic
    add("supply budget, every motor running loaded at once", run <= 5000,
        f"{run:.0f} mA of 5000 mA (encoder motors at 320 mA - booklet; S-motors at 225 mA - the belt model)", DV)

    # placement: every part in the CAD, and the CAD's box the size of the part's datasheet envelope
    placed_n = sum(1 for p in placed if p.get("placed"))
    add("placed from the CAD export", placed_n == len(placed), f"{placed_n} of {len(placed)} parts", DV, "warn")
    for pid in sorted({p["part_id"] for p in placed}):
        d = defs[pid]
        housing = next((r["value"] for r in d["ratings"] if r["label"] == "Dimensions" and r["source"] == D), None)
        if not housing:
            continue
        want = sorted(float(v) for v in re.findall(r"[\d.]+", housing)[:3])
        off = []
        for p in placed:
            if p["part_id"] != pid or not p.get("placed"):
                continue
            b = p["placed"]["box_mm"]
            got = sorted(b[i + 3] - b[i] for i in range(3))
            err = max(abs(g - w) for g, w in zip(got, want))
            if err > 0.5:
                off.append(f"{p['instance_id']} {' x '.join(f'{g:.1f}' for g in got)} ({err:.1f} mm)")
        add(f"CAD size of every {d['name']}", not off, (f"the datasheet's housing is {' x '.join(f'{w:g}' for w in want)} mm: " + "; ".join(off)) if off
            else f"each within 0.5 mm of the datasheet's housing, {' x '.join(f'{w:g}' for w in want)} mm", D, "warn")
    return out


def check(variant):
    controller = json.load(open(os.path.join(WEB, "controller.json")))
    components = json.load(open(os.path.join(WEB, "components", "components.json")))
    cad = json.load(open(os.path.join(WEB, "hbw_parts_up12.json")))
    defs, placed, nets, contacts, supplies, controls, io, findings = build(controller, components, cad, variant)
    placement(placed, cad, findings)
    ids = {p["instance_id"] for p in placed}
    labels = {pid: {x["label"] for x in d["pins"]} for pid, d in defs.items()}
    pid_of = {p["instance_id"]: p["part_id"] for p in placed}
    for n in nets:
        for c in n["connections"]:
            assert c["part_instance"] in ids, f"net {n['net_id']}: no part {c['part_instance']}"
            assert c["pin_label"] in labels[pid_of[c["part_instance"]]], f"net {n['net_id']}: {c}"
    for d in defs.values():
        for x in d["pins"]:
            assert x["voltage_source"] in (D, B, P, BD, DV, A, DS), x
        for r in d["ratings"]:
            assert r["source"] in (D, B, P, BD, DV, A, DS, "photo", "ft-std"), r
    assert len(ids) == len(placed), "an instance is placed twice"
    rated = checks(defs, placed, nets, io, controller, controls, cad, variant)
    return defs, {
        "project": {"placed_parts": [{k: p[k] for k in ("instance_id", "part_id", "world_position_mm", "world_quaternion")} for p in placed],
                    "wire_nets": nets},
        "modules": {p["instance_id"]: p["module"] for p in placed},
        "placement": {p["instance_id"]: p["placed"] for p in placed},
        "supplies": supplies, "contacts": contacts, "controls": controls, "io": io,
        "checks": rated, "findings": findings,
    }


def main():
    variants = {}
    for v in VARIANTS:
        defs, variants[v] = check(v)
    doc = {
        "schema": "stf.electrical/2",
        "sources": {"board": "controller.json", "components": "components/components.json", "cad": "hbw_parts_up12.json",
                    "plans": list(PLANS.values()),
                    "datasheets": ["Datenblatt_RevPi_DIO.pdf", "Datenblatt_RevPi_Cores.pdf", "PowerSupply WDR DIN rail.pdf"]},
        "source_tags": {D: "a manufacturer's datasheet", B: "the 536634 booklet", P: "the occupancy plans",
                        BD: "the extended description of the adaptor PCB", DV: "computed from sourced values",
                        DS: "the upgrade design in stf-cad: chosen, not measured", A: "not documented: measure"},
        "parts": defs,
        "variants": variants,
    }
    json.dump(doc, open(OUT, "w"), indent=1)
    for v, x in variants.items():
        placed = x["project"]["placed_parts"]
        n_pins = sum(len(defs[p["part_id"]]["pins"]) for p in placed)
        print(f"== {v}: {len(placed)} parts, {n_pins} pins, {len(x['project']['wire_nets'])} nets, {len(x['contacts'])} contacts")
        for c in x["checks"]:
            if c["severity"] != "ok" or "inventory" in c["check"] or "placed" in c["check"]:
                print({"ok": "  ok   ", "warn": "  WARN ", "fail": "  FAIL "}[c["severity"]] + c["check"] + ": " + c["detail"])
        for f in x["findings"]:
            print("  finding: " + f)
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
