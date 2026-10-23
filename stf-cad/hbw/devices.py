"""
The control and power devices of the STF, as one parameter table: what the ft components
(components.py) hang on. Same format, same rule: every dimension carries its SOURCE.

  revpi_dio     KUNBUS RevPi DIO 100197          docs/Datenblatt_RevPi_DIO.pdf
  revpi_core    KUNBUS RevPi Core S 100359       docs/Datenblatt_RevPi_Cores.pdf
  psu_wdr120    Mean Well WDR-120-24             Mean Well's WDR-120 spec sheet (case 992B)
  adaptor_pcb   fischertechnik Adapterplatine 24V  536634 extended description p.4 (a drawing)
  io_coupler    remote I/O bus coupler, Modbus TCP  the upgrade design (io_nodes.py): no product chosen
  io_slice      remote I/O slice, 8 channels        the upgrade design (io_nodes.py)

Sources, beyond components.py's (datasheet, booklet, photo, ft-std, assumed):
  standard   fixed by a published standard: the TS35 top-hat rail (EN 60715: 35 x 7.5 mm), a
             1.6 mm FR-4 board, 2.54 mm pin headers and their shrouds (IEC 60603-13 style box
             headers: 2.54 x n/2 + 10.16 mm long)
  design     chosen in this project's upgrade design (io_nodes.py), not a product's datasheet

What the documents do NOT give, and is therefore 'assumed': where the RevPi's connectors and LEDs
sit on its front (KUNBUS publishes the envelope and the connector types, not their positions; its
own STEP files would settle it), the PSU's terminal pitch, the relays' height. The adaptor PCB's
outline is scaled off the drawing on p.4 (a 'photo' value), with two rulers that agree to 5 %:
its 34-pin ST3 box header (17 x 2.54 + 10.16 = 53.34 mm long) and its 20-pin ST1 (35.56 mm).

Frame for every device: origin at the envelope's min corner, mm. A DIN-rail device stands on its
rail: +X = its height (H), +Y = its width along the rail (B), +Z = its depth from the rail out to
the front (T); the front - connectors, LEDs, label - faces +Z. The PCB lies flat: +X its length,
+Y its depth (the terminal strip 1-30 at -Y, the PLC side), +Z up.
"""
from components import A, B, D, F, P, dim

S, DS = "standard", "design"

# the adaptor PCB drawing (536634 extended description p.4, 1021 x 681 px): its board outline
# and features in pixels, measured once off the image, and the ruler that turns them into mm
PCB_PX = {
    "board": (8, 12, 1011, 668),                      # x0, y0, x1, y1 (y down)
    "st1": (202, 29, 503, 94), "st2": (548, 29, 828, 94), "st3": (288, 461, 720, 527),
    "relays": [(157, 241), (249, 333), (400, 484), (492, 576), (584, 668), (676, 760), (827, 911), (919, 1003)],
    "relay_y": (220, 389),
    "valves": (10, 78, 219, 481),                     # V1-V4: x0, x1, y0, y1, four blocks
    "terminals": (18, 1000, 569, 643),                # 1-30: x0, x1, y0, y1, fifteen 2-pole blocks
    "holes": [(100, 146), (917, 146), (100, 537), (917, 537)], "hole_px": 24,
}
BOX_HEADER = lambda poles: poles / 2 * 2.54 + 10.16  # a 2-row 2.54 mm shrouded header's length
PCB_MM_PER_PX = BOX_HEADER(34) / (PCB_PX["st3"][2] - PCB_PX["st3"][0])   # ST3 is the ruler


def pcb_mm(px):
    return round(px * PCB_MM_PER_PX, 3)


_bx0, _by0, _bx1, _by1 = PCB_PX["board"]
PCB_L, PCB_W = pcb_mm(_bx1 - _bx0), pcb_mm(_by1 - _by0)

REVPI_FACTS = lambda extra: [
    ("Dimensions", "96 x 22.5 x 110.5 mm (H x B x T)", D),
    ("Housing", "DIN-rail housing for EN 50022 (TS35), plastic, IP20", D),
] + extra

DEVICES = {
    "revpi_dio": {
        "ft": "100197", "kind": "device", "maker": "KUNBUS GmbH", "family": "Revolution Pi",
        "name": "RevPi DIO", "name_de": "RevPi DIO (digitales I/O-Modul)",
        "datasheet": "Datenblatt_RevPi_DIO.pdf", "colour": "grey",
        "material": "plastic housing (datasheet), spring-clamp plugs",
        "facts": REVPI_FACTS([
            ("Weight", "approx. 100 g / 130 g with plugs", D),
            ("Supply", "12-24 V DC -5 % / +20 % (X2 and X4), 1.5 W", D),
            ("Inputs", "14, 2.4 mA, EN 61131-2 type I/III; counters or 6 encoders", D),
            ("Outputs", "14, 500 mA high-side or 100 mA push-pull, PWM 40-400 Hz", D),
            ("Connectors", "2 x 14-pole spring clamp, 3.5 mm pitch (Wieland 27.630.4453.0); 2 x 4-pole screw for supply", D),
            ("Indicators", "3 multicolour status LEDs", D),
            ("Bus", "PiBridge to the Core and further modules", D),
            ("Where the connectors sit", "not published - placed by assumption; KUNBUS's STEP file settles it", A),
        ]),
        "dims": [
            dim("L", "height H", 96.0, D), dim("W", "width B (along the rail)", 22.5, D), dim("H", "depth T (rail to front)", 110.5, D),
            dim("base_t", "depth of the full-height base", 70.0, A), dim("nose_h", "height of the front nose", 56.0, A),
            dim("rail_w", "TS35 rail width", 35.0, S, "EN 60715"), dim("rail_d", "TS35 rail depth", 7.5, S, "EN 60715"),
            dim("io_pitch", "I/O plug pitch", 3.5, D), dim("io_poles", "poles per I/O plug", 14, D),
            dim("pwr_poles", "poles per supply plug", 4, D), dim("pwr_pitch", "supply plug pitch", 3.5, A),
            dim("plug_w", "plug body width", 9.5, A), dim("plug_h", "plug body height", 12.0, A),
            dim("led_d", "LED diameter", 3.0, A), dim("edge", "housing edge round", 0.8, A),
        ],
    },
    "revpi_core": {
        "ft": "100359", "kind": "device", "maker": "KUNBUS GmbH", "family": "Revolution Pi",
        "name": "RevPi Core S", "name_de": "RevPi Core S (Steuerung)",
        "datasheet": "Datenblatt_RevPi_Cores.pdf", "colour": "grey",
        "material": "plastic housing (datasheet), passive heat sink",
        "facts": REVPI_FACTS([
            ("Weight", "approx. 115 g", D),
            ("Supply", "12-24 V DC -15 % / +20 %, reverse-polarity protected; 10 W max", D),
            ("CPU", "Broadcom BCM2711, 4 x Cortex-A72, 1.5 GHz; 1 GB LPDDR4; 8 GB eMMC", D),
            ("Interfaces", "2 x USB A, 1 x RJ45 10/100, 1 x micro-USB, 1 x micro-HDMI, 2 x PiBridge", D),
            ("Connectors", "1 x 4-pole screw connector for the supply", D),
            ("Indicators", "3 status LEDs, 2-colour (2 programmable)", D),
            ("Hold-up", "10 ms through supply dips at 20.4-28.8 V (EN 61131-2)", D),
            ("Where the connectors sit", "not published - placed by assumption; KUNBUS's STEP file settles it", A),
        ]),
        "dims": [
            dim("L", "height H", 96.0, D), dim("W", "width B (along the rail)", 22.5, D), dim("H", "depth T (rail to front)", 110.5, D),
            dim("base_t", "depth of the full-height base", 70.0, A), dim("nose_h", "height of the front nose", 56.0, A),
            dim("rail_w", "TS35 rail width", 35.0, S, "EN 60715"), dim("rail_d", "TS35 rail depth", 7.5, S, "EN 60715"),
            dim("pwr_poles", "poles of the supply plug", 4, D), dim("pwr_pitch", "supply plug pitch", 3.5, A),
            dim("rj45_w", "RJ45 jack width", 16.0, A), dim("rj45_h", "RJ45 jack height", 13.5, A),
            dim("usb_w", "USB A socket width", 14.5, A), dim("usb_h", "USB A socket height", 6.5, A),
            dim("led_d", "LED diameter", 3.0, A), dim("edge", "housing edge round", 0.8, A),
        ],
    },
    "psu_wdr120": {
        "ft": "WDR-120-24", "kind": "device", "maker": "MEAN WELL Enterprises Co., Ltd.", "family": "WDR",
        "name": "Power supply WDR-120-24", "name_de": "Netzteil WDR-120-24 (Hutschiene)",
        "datasheet": "Mean Well WDR-120 spec sheet (case 992B)",
        "document_url": "https://www.meanwell.com/Upload/PDF/WDR-120/WDR-120-SPEC.PDF",
        "install": "PowerSupply WDR DIN rail.pdf", "colour": "steel",
        "material": "metal case (datasheet: case 992B)",
        "facts": [
            ("Dimensions", "40 x 125.2 x 113.5 mm (W x H x D), tolerance +-1 mm", D),
            ("Output", "24 V, 5 A, 120 W; adjustable 24-29 V; efficiency 91 % (400 VAC)", D),
            ("Input", "180-550 VAC between any two phases (L1, L2: no neutral)", D),
            ("Terminals", "TB1: FG, AC/L2, AC/L1 - TB2: DC OK relay (1, 2), -V (3), +V (4)", D),
            ("DC OK", "relay contact, 30 V / 1 A, closed while the output is good", D),
            ("Weight", "0.65 kg (packing figure)", D),
            ("Mounting", "TS35/7.5 or TS35/15, vertical, input terminals down; 40 mm free above", D),
            ("Terminal pitch", "not given - assumed", A),
        ],
        "dims": [
            dim("L", "height H", 125.2, D, "+-1 mm"), dim("W", "width W (along the rail)", 40.0, D, "+-1 mm"),
            dim("H", "depth D (rail to front)", 113.5, D, "+-1 mm"),
            dim("rail_w", "TS35 rail width", 35.0, S, "EN 60715"), dim("rail_d", "TS35 rail depth", 7.5, S, "EN 60715"),
            dim("tb_pitch", "terminal pitch", 7.62, A), dim("tb_w", "terminal block depth", 12.0, A),
            dim("slot_w", "ventilation slot width", 2.0, A), dim("slot_l", "ventilation slot length", 30.0, A),
            dim("edge", "case edge round", 1.0, A),
        ],
    },
    "adaptor_pcb": {
        "ft": "536634-PCB", "kind": "device", "maker": "fischertechnik GmbH", "family": "fischertechnik Fabrik Simulation 24V (536634)",
        "name": "Adaptor PCB 24V", "name_de": "Adapterplatine 24V",
        "datasheet": "536634-Factory-simulation-24V-extended-description.pdf p.4", "colour": "green",
        "material": "FR-4 board (standard), relays, shrouded headers, pluggable terminals",
        "facts": [
            ("Dimensions", f"{PCB_L:.1f} x {PCB_W:.1f} x 1.6 mm (board), scaled off the p.4 drawing", P),
            ("Scale", f"{PCB_MM_PER_PX:.4f} mm/px: the 34-pin ST3 box header is 53.34 mm long", S),
            ("Headers", "ST1 and ST2 to the model (up to 20-pole), ST3 17 x 2 to the PLC", B),
            ("Relays", "R1-R8: changeover relays, 4 pairs, for the bidirectional motors", B),
            ("Terminals", "1-30 to the PLC (alternative to ST3); V1-V4 for the solenoid valves", B),
            ("Supply", "terminal 1: relays (+24 V Motor, diode); 2: sensors (diode, 0.2 A resettable fuse); 3, 4: GND", B),
            ("Not documented", "the board's outline and the relays' height - measure", A),
        ],
        "dims": [
            dim("L", "board length", PCB_L, P, "scaled off the p.4 drawing"), dim("W", "board depth", PCB_W, P, "scaled off the p.4 drawing"),
            dim("H", "board thickness", 1.6, S, "FR-4"),
            dim("hdr_h", "box header height", 9.1, S), dim("hdr_w", "box header width", 8.9, S),
            dim("relay_h", "relay height", 15.5, A), dim("term_h", "terminal block height", 10.0, A),
            dim("hole_d", "mounting hole", 3.2, S, "M3 clearance"), dim("standoff", "standoff height", 5.0, A),
        ],
    },
    "io_coupler": {
        "ft": "IO-COUPLER", "kind": "device", "maker": "not chosen (the upgrade design)", "family": "remote I/O, 750-series-like",
        "name": "Remote I/O bus coupler", "name_de": "Buskoppler Modbus TCP",
        "datasheet": "stf-cad io_nodes.py (Upgrade 3)", "colour": "grey",
        "material": "plastic housing (assumed)",
        "facts": [
            ("Dimensions", "51 x 100 x 72 mm (W x H x D) - the design's assumed product size", DS),
            ("Network", "2 x RJ45, Modbus TCP, from the cabinet switch", DS),
            ("Supply", "24 V system supply from the node's ECB channel", DS),
            ("Product", "none chosen yet: a 750-series-like coupler", DS),
        ],
        "dims": [
            dim("L", "height H", 100.0, DS), dim("W", "width W (along the rail)", 51.0, DS), dim("H", "depth D", 72.0, DS),
            dim("rail_w", "TS35 rail width", 35.0, S, "EN 60715"), dim("rail_d", "TS35 rail depth", 7.5, S, "EN 60715"),
            dim("rj45_w", "RJ45 jack width", 16.0, A), dim("rj45_h", "RJ45 jack height", 13.5, A),
        ],
    },
    "io_slice": {
        "ft": "IO-SLICE-8", "kind": "device", "maker": "not chosen (the upgrade design)", "family": "remote I/O, 750-series-like",
        "name": "Remote I/O slice, 8 channels", "name_de": "E/A-Klemme, 8 Kanaele",
        "datasheet": "stf-cad io_nodes.py (Upgrade 3)", "colour": "grey",
        "material": "plastic housing (assumed)",
        "facts": [
            ("Dimensions", "12 x 100 x 68 mm (W x H x D) - the design's assumed product size", DS),
            ("Channels", "8 (DI, DO); counter, analogue and IO-Link slices share the housing", DS),
            ("Connection", "push-in terminals, 4 rows of 2 [assumed]", A),
        ],
        "dims": [
            dim("L", "height H", 100.0, DS), dim("W", "width W (along the rail)", 12.0, DS), dim("H", "depth D", 68.0, DS),
            dim("rail_w", "TS35 rail width", 35.0, S, "EN 60715"), dim("rail_d", "TS35 rail depth", 7.5, S, "EN 60715"),
        ],
    },
}
