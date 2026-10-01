"""
The four fischertechnik electrical components of the STF, as ONE parameter table.

Everything downstream reads this: the FreeCAD solids (components_cad.py), the
web component viewer (components.json) and the Gemini/FreeCAD prompt
(components_prompt.py). A dimension is changed here or nowhere.

Every dimension carries its SOURCE, because the datasheets only fix part of
the geometry and precision claims must not outrun the evidence:

  datasheet  printed in the ft datasheet (stf/docs/hw/*.pdf) - authoritative
  booklet    printed in 536634-Fabrik_Simulation_24V.pdf, Bauteilbeschreibung
             p.8-11 - authoritative for ratings, but it prints NO dimensions
  photo      read off the datasheet photo: position/shape certain, size estimated
  ft-std     fischertechnik system convention (15 mm grid, 2.5 mm plugs)
  assumed    not documented anywhere I have - MEASURE WITH CALIPERS

Frame for every component: origin at the housing's min corner, mm,
+X = length, +Y = depth (the -Y face is the FRONT), +Z = up.
"""

D, P, F, A, B = "datasheet", "photo", "ft-std", "assumed", "booklet"


def dim(key, label, value, source, note=""):
    return {"key": key, "label": label, "value": float(value), "source": source, "note": note}


# The fischertechnik dovetail groove ("Nut"). The ft datasheets do not print it;
# these are a nominal profile to be confirmed with calipers on a real block.
FT_GROOVE = [
    dim("g_mouth", "groove mouth width", 3.2, A, "opening at the surface"),
    dim("g_inner", "groove inner width", 4.4, A, "widest point, below the lips"),
    dim("g_depth", "groove depth", 3.6, A, ""),
]

COMPONENTS = {
    "encoder_motor": {
        "ft": "144643",
        "name": "Encoder motor 24V",
        "name_de": "Encodermotor 24V",
        "datasheet": "144643-Encodermotor24V.pdf",
        "colour": "ftred",
        "material": "ABS housing (assumed), steel output shaft",
        "facts": [
            ("Dimensions", "60 x 30 x 30 mm", D),
            ("Output shaft", "D 4 mm, L 7.5 mm, 2 flats 0.7 mm each", D),
            ("Supply", "24 VDC via 2 ft sockets D 2.5 mm", D),
            ("No-load speed", "440 rpm", D),
            ("Stall torque", "1800 g.cm", D),
            ("Max current", "0.60 A", D),
            ("Max output power", "2.03 W", D),
            ("Encoder", "quadrature, push-pull 0/24 V, max 10 mA, max 1 kHz", D),
            ("Encoder connector", "4-pin header: red +24V, green 0V, black Puls1, yellow Puls2", D),
            ("Booklet: operating point", "2.03 W max output at 214 rpm, 320 mA", B),
            ("Booklet: gearbox", "25:1; 3 pulses per motor turn = 75 per output turn", B),
            ("Booklet vs datasheet", "consistent: 214 rpm at max power is ~half the 440 rpm "
                                     "no-load speed, as a DC motor's power peak must be", B),
        ],
        "dims": [
            dim("L", "housing length", 60, D),
            dim("W", "housing depth", 30, D),
            dim("H", "housing height", 30, D),
            dim("shaft_d", "shaft diameter", 4.0, D),
            dim("shaft_l", "shaft length (protruding)", 7.5, D),
            dim("flat", "flat depth, each side", 0.7, D, "across-flats = 4.0 - 2 x 0.7 = 2.6"),
            dim("collar_d", "bearing collar diameter", 7.0, P),
            dim("collar_h", "bearing collar height", 1.0, P),
            dim("edge", "housing edge bevel", 0.5, A),
            dim("groove_top_y", "top grooves at y", 7.5, P, "two grooves, y = 7.5 and 22.5"),
            dim("groove_side_z", "side groove at z", 15.0, P, "one groove per side face"),
            dim("sock_d", "power socket diameter", 2.5, D),
            dim("sock_depth", "power socket depth", 6.0, A),
            dim("sock_pitch", "power socket spacing", 10.0, P, "on the far end face, z = 15"),
            dim("slot_w", "socket recess width", 4.0, P),
            dim("slot_h", "socket recess height", 9.0, P),
            dim("slot_depth", "socket recess depth", 1.5, A),
            dim("hdr_w", "encoder header width", 10.4, A, "4 x 2.54 mm pitch"),
            dim("hdr_h", "encoder header height", 2.8, A),
        ] + FT_GROOVE,
    },
    "mini_switch": {
        "ft": "37783",
        "name": "Mini switch",
        "name_de": "Mini-Taster",
        "datasheet": "37783-Mini-switch.pdf",
        "colour": "black",
        "material": "ABS housing (assumed), red actuator",
        "facts": [
            ("Dimensions", "30 x 15 x 7.5 mm", D),
            ("Weight", "3.4 g", D),
            ("Switching power", "max 2 A, 50 V", D),
            ("Signal", "digital 0/1, usable as NO or NC", D),
            ("Contacts", "1-3 = normally open, 1-2 = normally closed", D),
            ("Controller input", "digital 5 kOhm, TXT I1-I8", D),
        ],
        "dims": [
            dim("L", "housing length", 30, D),
            dim("W", "housing thickness", 7.5, D),
            dim("H", "housing height", 15, D),
            dim("btn_l", "actuator length", 10.0, P),
            dim("btn_w", "actuator width", 5.5, P),
            dim("btn_h", "actuator travel above housing", 2.5, P),
            dim("btn_x", "actuator position from left end", 5.0, P),
            dim("contact_d", "contact socket diameter", 2.5, F, "ft plug standard"),
            dim("contact_depth", "contact socket depth", 5.0, A),
            dim("contact_x", "contact column at x", 24.0, P),
            dim("contact_z", "contacts at z", 3.5, P, "three sockets, z = 3.5 / 7.5 / 11.5"),
            dim("tab_l", "end tab length", 3.0, P, "outside the 30 mm datasheet body"),
            dim("tab_w", "end tab width", 4.0, P),
            dim("tab_h", "end tab height", 3.0, P),
            dim("edge", "housing edge bevel", 0.4, A),
        ],
    },
    "phototransistor": {
        "ft": "36134",
        "name": "Photo-transistor",
        "name_de": "Fototransistor",
        "datasheet": "36134-Photo-transistor.pdf",
        "colour": "ftyellow",
        "material": "ABS housing (assumed), NPN silicon phototransistor behind a clear window",
        "facts": [
            ("Dimensions", "15 x 15 x 7.5 mm", D),
            ("Weight", "1.7 g", D),
            ("Type", "NPN silicon phototransistor, pairs with light-barrier LED 162135", D),
            ("V_CE", "35 V", D),
            ("I_C", "15 mA (surge 75 mA)", D),
            ("Connections", "2 sockets for ft plugs D 2.5 mm, red marking = +", D),
            ("Controller input", "digital 5 kOhm, TXT I1-I8", D),
        ],
        "dims": [
            dim("L", "housing length", 15, D),
            dim("W", "housing depth", 15, D),
            dim("H", "housing height", 7.5, D),
            dim("win_l", "window slot length", 9.0, P),
            dim("win_w", "window slot width", 4.0, P),
            dim("win_depth", "window slot depth", 2.0, A),
            dim("lens_d", "lens diameter", 3.0, P),
            dim("sock_d", "socket diameter", 2.5, D),
            dim("sock_depth", "socket depth", 6.0, A),
            dim("sock_x", "sockets at x", 4.0, P, "two sockets, x = 4.0 and 11.0, front face"),
            dim("mark", "red + marking square", 3.0, P),
            dim("edge", "housing edge bevel", 0.4, A),
        ],
    },
    "colour_sensor": {
        "ft": "128599",
        "name": "Colour sensor",
        "name_de": "Farbsensor",
        "datasheet": "128599-Color-sensor.pdf",
        "colour": "black",
        "material": "ABS housing (assumed), LED + photodiode behind two windows",
        "facts": [
            ("Dimensions", "30 x 15 x 15 mm", D),
            ("Weight", "6.8 g", D),
            ("Supply", "6-10 VDC, approx. 15 mA", D),
            ("Signal", "analogue 0-2 VDC (0-2000 mV) - NOT an RGB sensor", D),
            ("Principle", "LED light reflected by the object is measured; value depends on "
                          "ambient light and distance", D),
            ("Wires", "red = 9 VDC, green = ground, black = signal", D),
            ("Booklet: principle", "emits RED light; the phototransistor measures how much "
                                   "comes back - it is a reflection sensor", B),
            ("Booklet: output", "0-9 V (booklet) vs 0-2 V (datasheet) vs 0-10 V at the PLC "
                                "terminal (extended description) - MEASURE", B),
            ("Booklet: supply", "9 VDC, converted from 24 VDC on the adapter PCB", B),
        ],
        "dims": [
            dim("L", "housing length", 30, D),
            dim("W", "housing depth", 15, D),
            dim("H", "housing height", 15, D),
            dim("hole_d", "optical window diameter", 3.4, P),
            dim("hole_depth", "optical window depth", 4.0, A),
            dim("hole_x", "windows at x", 12.0, P, "two windows, x = 12.0 and 16.5, z = 7.5"),
            dim("fin_w", "end-fin slot width", 1.2, P),
            dim("fin_depth", "end-fin slot depth", 1.5, P),
            dim("wire_d", "wire diameter", 1.2, A),
            dim("wire_l", "wire stub length", 12.0, A),
            dim("edge", "housing edge bevel", 0.4, A),
        ] + FT_GROOVE,
    },

    # ------------------------------------------------------------------
    # The five further components of the booklet's Bauteilbeschreibung
    # (536634 p.8-11). No ft datasheet for these is in stf/docs/hw, and the
    # booklet prints ratings and principles but NO dimensions - so every
    # size below is "assumed" (measure) or "photo" (read off the booklet
    # picture), and only the ratings are authoritative.
    # ------------------------------------------------------------------
    "s_motor": {
        "ft": "S-24V",
        "name": "S-Motor 24V",
        "name_de": "S-Motor 24V mit U-Getriebe",
        "datasheet": "536634-Fabrik_Simulation_24V.pdf p.9",
        "colour": "black",
        "material": "ABS housing (assumed), steel worm shaft, POM gears (assumed)",
        "facts": [
            ("Type", "permanent-magnet DC motor", B),
            ("Rated voltage", "24 VDC", B),
            ("Max current", "300 mA", B),
            ("Max torque", "5 mNm", B),
            ("No-load speed", "10 700 rpm", B),
            ("U-Getriebe", "64.8:1, output at the side", B),
            ("Output speed (derived)", "10 700 / 64.8 = 165 rpm no-load", B),
            ("Used for", "the conveyor belts (oven Q3, sorting Q1, HBW Q1/Q2) and M3/M4", B),
        ],
        "dims": [
            dim("L", "motor housing length", 45, A),
            dim("W", "motor housing depth", 30, A),
            dim("H", "motor housing height", 15, A),
            dim("worm_d", "worm diameter", 6.0, A),
            dim("worm_l", "worm length (protruding)", 12.0, A),
            dim("shaft_d", "motor shaft diameter", 2.0, A),
            dim("gb_l", "U-Getriebe length", 30, A),
            dim("gb_w", "U-Getriebe depth", 30, A),
            dim("gb_h", "U-Getriebe height", 30, A, "taller than the motor: the worm wheel sits above the worm"),
            dim("wheel_d", "worm wheel diameter", 14.0, A),
            dim("axle_d", "output axle diameter", 4.0, F, "ft axle standard"),
            dim("axle_l", "output axle length (protruding)", 10.0, A),
            dim("sock_d", "power socket diameter", 2.5, F),
            dim("edge", "housing edge bevel", 0.5, A),
        ] + FT_GROOVE,
        "motion": [
            {"part": "worm_shaft", "type": "spin", "axis": [1, 0, 0], "pivot": [45, 15, 7.5],
             "dps": 720},
            {"part": "worm_wheel", "type": "spin", "axis": [0, 1, 0], "pivot": [57, 15, 17.5],
             "dps": 720 / 64.8 * 8},
            {"part": "output_axle", "type": "spin", "axis": [0, 1, 0], "pivot": [57, 15, 17.5],
             "dps": 720 / 64.8 * 8},
        ],
        "operate": "24 V on",
        "xray": True,
    },
    "compressor": {
        "ft": "K-24V",
        "name": "Compressor",
        "name_de": "Kompressor (Membranpumpe)",
        "datasheet": "536634-Fabrik_Simulation_24V.pdf p.10, Abb. 4",
        "colour": "blue",
        "material": "ABS housing (assumed), EPDM membrane, steel crank",
        "facts": [
            ("Type", "diaphragm (membrane) pump - two chambers split by a membrane", B),
            ("Rated voltage", "24 VDC", B),
            ("Overpressure", "0.7 bar", B),
            ("Max current", "70 mA", B),
            ("Principle", "an eccentric crank moves a piston; piston right pulls the membrane "
                          "back and air is drawn in through the inlet valve; piston left "
                          "pushes it out through the outlet valve", B),
            ("Used in", "oven Q10, sorting Q2, VGR Q7 - one per pneumatic module", B),
        ],
        "dims": [
            dim("L", "housing length", 60, A),
            dim("W", "housing depth", 30, A),
            dim("H", "housing height", 30, A),
            dim("nip_d", "air outlet nipple diameter", 4.0, A),
            dim("nip_l", "air outlet nipple length", 6.0, A),
            dim("crank_r", "crank throw (eccentric radius)", 2.5, A, "stroke = 2 x throw = 5 mm"),
            dim("piston_d", "piston diameter", 8.0, A),
            dim("mem_d", "membrane diameter", 20.0, A),
            dim("edge", "housing edge bevel", 0.5, A),
        ] + FT_GROOVE,
        "motion": [
            {"part": "crank", "type": "spin", "axis": [0, 1, 0], "pivot": [30, 15, 15], "dps": 360},
            {"part": "crank_pin", "type": "orbit", "axis": [0, 1, 0], "pivot": [30, 15, 15], "dps": 360},
            {"part": "conrod", "type": "reciprocate", "axis": [-1, 0, 0], "amp": 5.0, "dps": 360},
            {"part": "piston", "type": "reciprocate", "axis": [-1, 0, 0], "amp": 5.0, "dps": 360},
            {"part": "membrane", "type": "reciprocate", "axis": [-1, 0, 0], "amp": 1.5, "dps": 360},
        ],
        "operate": "24 V on",
        "xray": True,
    },
    "pneumatic_cylinder": {
        "ft": "PZ",
        "name": "Pneumatic cylinder",
        "name_de": "Pneumatikzylinder",
        "datasheet": "536634-Fabrik_Simulation_24V.pdf p.10",
        "colour": "black",
        "material": "ABS end caps, clear PC barrel, steel tie rods and piston rod, red spring",
        "facts": [
            ("Principle", "a piston splits the cylinder into two chambers; a pressure "
                          "difference moves it", B),
            ("Return", "spring (single-acting): vent the valve and it springs back", B),
            ("Vacuum trick", "two cylinders mechanically coupled: pressurise one, both rods "
                             "extend, the chamber sealed by the suction cup grows - and its "
                             "pressure falls below ambient", B),
            ("Driven by", "a 3/2-way solenoid valve", B),
            ("Used in", "oven door Q13, oven lowering Q12, Auswerfer Q14, the three "
                        "sorting ejectors, and the vacuum generators", B),
        ],
        "dims": [
            dim("L", "overall length, retracted", 60, A),
            dim("W", "end cap depth", 15, F),
            dim("H", "end cap height", 15, F),
            dim("cap_rear", "rear cap length", 15, F),
            dim("cap_front", "front cap length", 8, A),
            dim("barrel_d", "barrel diameter", 11.0, A),
            dim("rod_d", "piston rod diameter", 4.0, A),
            dim("rod_out", "rod protrusion, retracted", 5.0, A),
            dim("stroke", "stroke", 15.0, A),
            dim("tie_d", "tie rod diameter", 2.0, A),
            dim("nip_d", "air nipple diameter", 3.0, A),
        ],
        "motion": [
            {"part": "piston_rod", "type": "slide", "axis": [-1, 0, 0], "travel": 15},
            {"part": "rod_end", "type": "slide", "axis": [-1, 0, 0], "travel": 15},
            {"part": "piston", "type": "slide", "axis": [-1, 0, 0], "travel": 15},
            {"part": "spring", "type": "squash", "axis": [1, 0, 0], "travel": 15,
             "anchor": [8, 7.5, 7.5], "length": 32},
        ],
        "operate": "valve energised",
    },
    "ir_track_sensor": {
        "ft": "128598",
        "name": "IR track sensor",
        "name_de": "IR-Spursensor",
        "datasheet": "536634-Fabrik_Simulation_24V.pdf p.9",
        "colour": "grey",
        "material": "ABS housing (assumed), IR LEDs + IR phototransistors",
        "facts": [
            ("Type", "digital infrared sensor for a black track on a white ground", B),
            ("Range", "5 - 30 mm to the surface", B),
            ("Elements", "2 emitters + 2 receivers = two channels", B),
            ("Outputs", "push-pull, one per channel", B),
            ("Wires", "red = 9 VDC, green = ground, black and yellow = the two signals", B),
            ("Supply", "9 VDC; the adapter PCB converts 24 V and shifts the levels", B),
            ("Used in", "HBW A1/A2 (Spursensor Signal 1 unten / Signal 2 oben)", B),
        ],
        "dims": [
            dim("L", "housing length", 30, A),
            dim("W", "housing depth", 15, A),
            dim("H", "housing height", 15, A),
            dim("win_d", "optical window diameter", 4.0, P),
            dim("win_x", "windows at x", 9.0, P, "two windows, x = 9 and 21"),
            dim("fin_w", "end-fin slot width", 1.2, P),
            dim("wire_d", "wire diameter", 1.2, A),
            dim("wire_l", "wire stub length", 12.0, A),
            dim("edge", "housing edge bevel", 0.4, A),
        ] + FT_GROOVE,
        "operate": "move the track",
    },
    "solenoid_valve": {
        "ft": "MV-3/2",
        "name": "3/2-way solenoid valve",
        "name_de": "3/2-Wege-Magnetventil",
        "datasheet": "536634-Fabrik_Simulation_24V.pdf p.11, Abb. 5",
        "colour": "blue",
        "material": "steel bracket and plunger, copper coil in a blue ABS bobbin, PA nipples",
        "facts": [
            ("Ports", "1 (P) supply, 2 (A) to the cylinder, 3 (R) vent", B),
            ("States", "2: energised 1->2 (P->A); de-energised 2->3 (A->R)", B),
            ("Actuation", "coil (a) pulls the sliding plunger (b) against the spring (c)", B),
            ("Default", "the spring closes P and vents the cylinder - normally closed", B),
            ("Wiring", "2 wires: a PLC output and ground", B),
            ("Used in", "oven V1-V4 (Q11-Q14), sorting Q3-Q5, VGR Q8", B),
        ],
        "dims": [
            dim("L", "body length", 20, A),
            dim("W", "body depth", 15, A),
            dim("H", "body height", 25, A),
            dim("coil_w", "coil width", 16.0, A),
            dim("core_d", "plunger diameter", 4.0, A),
            dim("core_travel", "plunger travel", 1.5, A),
            dim("nip_d", "nipple diameter", 4.0, A),
            dim("nip_l", "nipple length", 8.0, A),
            dim("plate_t", "bracket sheet thickness", 1.5, A),
        ],
        "motion": [
            {"part": "plunger", "type": "slide", "axis": [0, 0, 1], "travel": 1.5},
            {"part": "spring", "type": "squash", "axis": [0, 0, -1], "travel": 1.5,
             "anchor": [10, 7.5, 23.5], "length": 5.5},
        ],
        "operate": "coil energised",
        "xray": True,
    },
}


def get(cid, key):
    for d_ in COMPONENTS[cid]["dims"]:
        if d_["key"] == key:
            return d_["value"]
    raise KeyError(f"{cid}.{key}")


def used_in():
    """Where each component sits in the factory model - joined from the same
    parts table the CAD tab and the spreadsheet use."""
    import parts_table as PT
    out = {cid: [] for cid in COMPONENTS}
    ft_to = {c["ft"]: cid for cid, c in COMPONENTS.items()}
    for r in PT.build_all():
        cid = ft_to.get(r["ft_part_no"])
        if cid:
            out[cid].append({"module": r["module"], "part": r["part_name"],
                             "io": r["io_tag"], "terminal": r["revpi_klemme"],
                             "function": r["function_en"]})
    return out
