"""
STF-2 hardware catalogue - the ONLY place a bought-in part's numbers live.

The precise build phase replaces every generic box in line_model with a real,
orderable part. line_model, joints, plc_io and the CAD read the numbers from
here; nothing downstream may retype one.

Component family (user decision 2026-09-28): INDUSTRIAL TABLETOP
  B-type slot aluminium profiles 20/30/40 + T-nuts + ISO 4762 screws,
  HIWIN MGN miniature rails, NEMA 17 steppers (closed loop), ISO 15 608/625
  bearings, Tr8x4 lead screws, ISO 6432 mini cylinders.
Controls (user decision 2026-09-28): BECKHOFF EtherCAT - CX2020 + EK1100 +
  EL terminals, TwinCAT 3.

Source tags on every entry (`src`):
  [ISO nnnn]        the standard itself - dimensions are normative
  [cat: ...]        vendor catalogue / datasheet named in SOURCES
  [typ]             typical value across vendors of that class - VERIFY on the
                    part actually bought (the checks still run on it)
  [derived]         computed here from other catalogue numbers
A [typ] value is never silently promoted: verify() lists every one of them so
the purchase list and this table can be reconciled.
"""
import math

SOURCES = {
    "ISO 4762": "ISO 4762:2004 hexagon socket head cap screws (= DIN 912)",
    "ISO 7089": "ISO 7089:2000 plain washers, normal series, product grade A",
    "ISO 4032": "ISO 4032:2012 hexagon regular nuts (style 1)",
    "ISO 273": "ISO 273:1979 clearance holes for bolts and screws (fine / medium / coarse)",
    "ISO 261": "ISO 261/262 metric coarse threads; tap drill = d - P",
    "ISO 15": "ISO 15:2017 radial bearings - boundary dimensions (608 = 8x22x7, 625 = 5x16x5)",
    "ISO 2901": "ISO 2901/2903 metric trapezoidal screw threads (Tr8x4 = P2, 2-start)",
    "ISO 6432": "ISO 6432:2015 pneumatic cylinders 8..25 mm bore - mounting dimensions",
    "VDI 2230": "VDI 2230-1:2015 bolted joints (tightening torques for 8.8 at mu = 0.12)",
    "Bossard": "Bossard technical info T.023 - minimum engagement length in tapped holes",
    "misumi": "MISUMI HFS5 / HFS8 aluminium extrusion catalogue (B-type slot 6 / slot 8)",
    "hiwin": "HIWIN 'Miniature Linear Guideway MG series' catalogue (MGN-H blocks)",
    "nema": "NEMA ICS 16 frame 17 mounting + StepperOnline 17HS19-2004S1 / -2004D-E1000 datasheets",
    "pg17": "StepperOnline PG-series planetary gearbox for NEMA 17 datasheet",
    "beckhoff": "Beckhoff product pages / EL-terminal documentation (www.beckhoff.com)",
    "meanwell": "Mean Well SDR-120 / SDR-240 / SDR-480P datasheets",
    "tr8": "generic Tr8x4 lead screw + brass flange nut (catalogue common to many vendors)",
    "smc": "SMC SY3000 5-port solenoid valve manifold catalogue",
}

# ------------------------------------------------------------ metric threads
# d, pitch, tap drill [ISO 261]; ISO 273 clearance (fine, medium, coarse);
# ISO 4762 head (dk, k, s hex key, t key depth); ISO 7089 washer (d1, d2, h);
# ISO 4032 nut (s, m); ISO 4762 preferred stock lengths; tightening torque of an
# 8.8 screw at mu = 0.12 [VDI 2230], Nm.
THREAD = {
    "M3": dict(d=3.0, P=0.5, tap=2.5, clear=(3.2, 3.4, 3.6), head=(5.5, 3.0, 2.5, 1.3),
               washer=(3.2, 7.0, 0.5), nut=(5.5, 2.4), torque=1.3,
               lengths=(4, 5, 6, 8, 10, 12, 16, 20, 25, 30, 35, 40)),
    "M4": dict(d=4.0, P=0.7, tap=3.3, clear=(4.3, 4.5, 4.8), head=(7.0, 4.0, 3.0, 2.0),
               washer=(4.3, 9.0, 0.8), nut=(7.0, 3.2), torque=2.9,
               lengths=(6, 8, 10, 12, 16, 20, 25, 30, 35, 40, 45, 50)),
    "M5": dict(d=5.0, P=0.8, tap=4.2, clear=(5.3, 5.5, 5.8), head=(8.5, 5.0, 4.0, 2.5),
               washer=(5.3, 10.0, 1.0), nut=(8.0, 4.7), torque=5.7,
               lengths=(8, 10, 12, 16, 20, 25, 30, 35, 40, 45, 50)),
    "M6": dict(d=6.0, P=1.0, tap=5.0, clear=(6.4, 6.6, 7.0), head=(10.0, 6.0, 5.0, 3.0),
               washer=(6.4, 12.0, 1.6), nut=(10.0, 5.2), torque=9.9,
               lengths=(8, 10, 12, 16, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70)),
    "M8": dict(d=8.0, P=1.25, tap=6.8, clear=(8.4, 9.0, 10.0), head=(13.0, 8.0, 6.0, 4.0),
               washer=(8.4, 16.0, 1.6), nut=(13.0, 6.8), torque=24.0,
               lengths=(10, 12, 16, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 80)),
    "M10": dict(d=10.0, P=1.5, tap=8.5, clear=(10.5, 11.0, 12.0), head=(16.0, 10.0, 8.0, 5.0),
                washer=(10.5, 20.0, 2.0), nut=(16.0, 8.4), torque=48.0,
                lengths=(16, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80)),
}
# Head types: (dk, k, stock lengths). socket = ISO 4762 (THREAD[m]['head']), button = ISO 7380-1,
# csk = ISO 10642 (flush; k is the countersink depth, the length includes the head).
HEAD = {
    "button": {"M3": (5.7, 1.65, (6, 8, 10, 12, 16)), "M4": (7.6, 2.2, (6, 8, 10, 12, 16, 20)),
               "M5": (9.5, 2.75, (8, 10, 12, 16, 20, 25)), "M6": (10.5, 3.3, (10, 12, 16, 20, 25, 30)),
               "M8": (14.0, 4.4, (12, 16, 20, 25, 30))},
    "csk": {"M3": (6.72, 1.86, (6, 8, 10, 12, 16, 20)), "M4": (8.96, 2.48, (8, 10, 12, 16, 20, 25)),
            "M5": (11.2, 3.1, (10, 12, 16, 20, 25, 30)), "M6": (13.44, 3.72, (12, 16, 20, 25, 30, 35)),
            "M8": (17.92, 4.96, (16, 20, 25, 30, 35, 40))},
}
HEAD_SRC = "[ISO 7380-1][ISO 10642]"


def head(m, kind):
    """(dk, k, stock lengths) of a head type."""
    if kind == "socket":
        t = THREAD[m]
        return t["head"][0], t["head"][1], t["lengths"]
    return HEAD[kind][m]


# Thread depth of bought parts' own tapped holes (screws go INTO them) [cat][typ]
# rail_clamp = rail height under the counterbored bolt head [cat: hiwin][typ]
BOUGHT_THREAD = {
    "+PG": ("M4", 6.0, "AlMgSi_T6"),           # planetary output face, 4x M4 on 31 sq [typ]
    "+SWG": ("M4", 6.0, "AlMgSi_T6"), "+AB042": ("M4", 8.0, "steel"),
    "17HS": ("M3", 4.5, "AlMgSi_T6"),          # NEMA 17 front face, 4x M3 on 31 sq
    "MGN12H block": ("M3", 3.5, "steel"), "MGN9H block": ("M3", 3.0, "steel"), "MGN15H block": ("M3", 4.0, "steel"),
}

THREAD_SRC = "[ISO 261][ISO 273][ISO 4762][ISO 7089][ISO 4032][VDI 2230]"

# Minimum engaged thread length in a TAPPED hole as a multiple of d, so an 8.8
# screw breaks before the internal thread strips [Bossard T.023, typ].
MIN_ENGAGE = {
    "steel": 1.0,          # steel parts; steel T-nuts follow the nut rule m >= 0.8 d (see TNUT)
    "AlMgSi_T6": 1.5,      # 6082-T6 plate / 5083 cast tooling plate (Rm >= 270 MPa)
    "AlMgSi_T5": 2.0,      # 6063-T5 extrusion core bore (Rm ~ 185 MPa) - profile END tapping
    "POM": 2.5,            # plastic parts (prefer threaded inserts)
}
HOLE_CLASS = "medium"      # ISO 273 series used for every clearance hole
EDGE_MIN = 1.5             # hole centre >= EDGE_MIN x hole diameter from a free edge [typ]
GRID = 0.1                 # every fastener / hole coordinate lies on a 0.1 mm grid


def clearance(m, series=HOLE_CLASS):
    return THREAD[m]["clear"][("fine", "medium", "coarse").index(series)]


def screw_len(m, need, max_len=None):
    """Shortest ISO 4762 stock length >= need (and <= max_len), else None."""
    for L_ in THREAD[m]["lengths"]:
        if L_ >= need - 1e-9 and (max_len is None or L_ <= max_len + 1e-9):
            return float(L_)
    return None


# ------------------------------------------------------ B-type slot profiles
# slot opening, lip thickness (face -> underside of the lip), channel depth
# (face -> channel floor), channel inner width, core bore (end tap), mass kg/m,
# second moment of area mm^4 [cat: misumi HFS5/HFS8; typ for other B-type vendors].
PROFILE = {
    20: dict(series="HFS5-2020", slot=6.2, lip=1.8, depth=6.5, inner=11.0, core=4.2, core_tap="M5",
             mass=0.49, I=0.69e4, tnut="TN6-M5", bracket="BR20", src="[cat: misumi HFS5-2020][typ]"),
    30: dict(series="HFS8-3030", slot=8.2, lip=2.2, depth=9.0, inner=16.5, core=6.8, core_tap="M8",
             mass=0.87, I=2.8e4, tnut="TN8-M6", bracket="BR30", src="[cat: misumi HFS8-3030][typ]"),
    40: dict(series="HFS8-4040", slot=8.2, lip=4.3, depth=12.2, inner=20.0, core=6.8, core_tap="M8",
             mass=1.50, I=9.0e4, tnut="TN8-M6", bracket="BR40", src="[cat: misumi HFS8-4040][typ]"),
}
ALU_E = 70000.0            # N/mm2 [typ]
# Sections in use: name -> (series, width, height). The series (20/30/40) sets
# the slot geometry above; a 2040 has two slots on its 40 faces at +-10 from
# the centre, a 20 face has one slot on the centre line.
SECTION = {
    "2020": (20, 20.0, 20.0), "2040": (20, 20.0, 40.0), "2080": (20, 20.0, 80.0),
    "3030": (30, 30.0, 30.0), "3060": (30, 30.0, 60.0),
    "4040": (40, 40.0, 40.0), "4080": (40, 40.0, 80.0),
}
END_TAP_DEPTH = 25.0       # tapped depth of a profile end (core bore) [typ, vendor end-tapping service]


def section(name):
    """(series dict, width, height) of a profile section name like '3030'."""
    ser, w, h = SECTION[name]
    return PROFILE[ser], w, h


def slot_offsets(face_width, series):
    """Slot centre offsets from the middle of a profile face of this width."""
    n = int(round(face_width / series))
    return [(-(n - 1) / 2.0 + k) * series for k in range(n)]

# Drop-in T-nuts (steel). h = thread length; the nut rule m >= 0.8 d must hold on its own.
TNUT = {
    "TN6-M5": dict(slot=6, thread="M5", h=4.0, w=10.0, l=11.0, src="[cat: misumi HNTT5-5][typ]"),
    "TN8-M6": dict(slot=8, thread="M6", h=6.0, w=14.5, l=16.0, src="[cat: misumi HNTT8-6][typ]"),
    "TN8-M5": dict(slot=8, thread="M5", h=6.0, w=14.5, l=16.0, src="[cat: misumi HNTT8-5][typ]"),
    "TN8-M3": dict(slot=8, thread="M3", h=4.0, w=14.5, l=16.0, src="[cat: misumi HNTT8-3][typ]"),
    "TN6-M3": dict(slot=6, thread="M3", h=3.0, w=10.0, l=11.0, src="[cat: misumi HNTT5-3][typ]"),
    "TN8-M4": dict(slot=8, thread="M4", h=4.0, w=14.5, l=16.0, src="[cat: misumi HNTT8-4][typ]"),
    "TN6-M4": dict(slot=6, thread="M4", h=4.0, w=10.0, l=11.0, src="[cat: misumi HNTT5-4][typ]"),
}

# Die-cast corner brackets: leg length a, width b, wall t, T-nut screw, hole at
# `hole_at` from the heel on each leg.
BRACKET = {
    # hole_at = half the series, so the hole lands on the slot of a same-series crossing profile.
    # 20 series: two ISO 4762 M5 heads (k 5) meet at the heel -> button heads (ISO 7380), see joints.
    # 20 series: M4 + slot-6 M4 T-nuts. With M5 the 3 mm leg needs a washer to reach 0.8 d of the
    # nut, and the washer lifts its button head 0.5 mm into the other screw's head at the heel.
    "BR20": dict(a=20.0, b=20.0, t=3.0, screw="M4", hole_at=11.0, head="button", src="[cat: misumi HBLFSN5][typ]"),
    "BR30": dict(a=28.0, b=30.0, t=4.0, screw="M6", hole_at=15.0, head="socket", src="[cat: misumi HBLFSN8-3030][typ]"),
    "BR40": dict(a=38.0, b=40.0, t=5.0, screw="M6", hole_at=20.0, head="socket", src="[cat: misumi HBLFSN8-4040][typ]"),
}

# The deck: cast aluminium tooling plate, tapped THROUGH wherever the joints
# table anchors something (holes follow the joints, not a grid).
TABLE_PLATE = dict(material="EN AW-5083 cast tooling plate", t=12.0, engage="AlMgSi_T6",
                   anchor="M6", src="[typ] (ACP 5080 class)")

# -------------------------------------------------------- linear guides
# HIWIN MGN-H: rail W_R x H_R, block W x L, total height H (rail bottom -> block
# top), block holes B x C, rail bolts at pitch P, end distance E, C_dyn kN [cat: hiwin].
MGN = {
    "MGN9H": dict(rail=(9.0, 6.0), W=20.0, L=39.9, H=10.0, B=15.0, C=16.0, block_thread="M3",
                  rail_bolt="M3", P=20.0, E=7.5, C_dyn=1.86, rail_clamp=2.5, src="[cat: hiwin MGN9H]"),
    "MGN12H": dict(rail=(12.0, 8.0), W=27.0, L=45.4, H=13.0, B=20.0, C=20.0, block_thread="M3",
                   rail_bolt="M3", P=25.0, E=10.0, C_dyn=3.72, rail_clamp=3.5, src="[cat: hiwin MGN12H]"),
    "MGN15H": dict(rail=(15.0, 10.0), W=32.0, L=58.8, H=16.0, B=25.0, C=25.0, block_thread="M3",
                   rail_bolt="M3", P=40.0, E=15.0, C_dyn=6.37, rail_clamp=5.3, src="[cat: hiwin MGN15H]"),
}

# ------------------------------------------------------------- lead screws
LEADSCREW = {
    "Tr8x4": dict(d=8.0, lead=4.0, pitch=2.0, root=5.5, eff=0.35,
                  nut=dict(flange_d=22.0, flange_t=3.5, body_d=10.2, length=15.0, holes=4, hole_d=3.5, pcd=16.0),
                  src="[ISO 2901][cat: tr8][typ eff: brass nut, greased]"),
}
# critical speed n_c = f * d_root / L^2 * 1e7 rpm; designs stay below 80 % [typ, THK/NSK form]
WHIP_F = {"fixed-free": 3.4, "supported-supported": 9.7, "fixed-supported": 15.1, "fixed-fixed": 21.9}
WHIP_MARGIN = 0.8

# ---------------------------------------------------------------- bearings
BEARING = {
    "608-2RS": dict(d=8.0, D=22.0, B=7.0, C_dyn=3.45, src="[ISO 15][typ C]"),
    "625-2RS": dict(d=5.0, D=16.0, B=5.0, C_dyn=1.73, src="[ISO 15][typ C]"),
}

# --------------------------------------------------------------- motors
# NEMA 17: flange 42.3 square, bolt square 31.0 (M3), pilot 22 x 2, shaft 5 x 24 [nema].
NEMA17 = dict(flange=42.3, bolt_sq=31.0, bolt="M3", pilot=(22.0, 2.0), shaft=(5.0, 24.0), src="[cat: nema]")
STEPPER = {    # holding torque Nm, rated current A, body length (w/o shaft), encoder cap length
    "17HS13-0404S": dict(T_hold=0.26, I=0.4, R=30.0, body=34.0, enc_len=0.0, src="[cat: nema][typ]"),
    "17HS19-2004S1": dict(T_hold=0.59, I=2.0, R=1.4, body=48.0, enc_len=0.0, src="[cat: nema]"),
    "17HS19-2004D-E1000": dict(T_hold=0.59, I=2.0, R=1.4, body=48.0, enc_len=21.0, enc_ppr=1000,
                               src="[cat: nema] closed loop, 1000 ppr encoder"),
}
# Every sizing check allows only STEP_DERATE x T_hold up to STEP_KNEE_RPM and
# ~1/n above it (pull-out curve of a 2 A / 48 mm motor on 48 V) [typ, conservative].
STEP_DERATE, STEP_KNEE_RPM = 0.5, 300.0


def stepper_torque(model, rpm):
    T = STEP_DERATE * STEPPER[model]["T_hold"]
    return T if rpm <= STEP_KNEE_RPM else T * STEP_KNEE_RPM / rpm


GEARBOX = {    # NEMA 17 planetary: ratio, rated output torque Nm, efficiency, length, output shaft d x l
    "PG5": dict(ratio=5.18, T_rated=3.0, eff=0.90, length=34.0, shaft=(8.0, 20.0), src="[cat: pg17]"),
    "PG14": dict(ratio=13.73, T_rated=4.0, eff=0.81, length=45.0, shaft=(8.0, 20.0), src="[cat: pg17]"),
    "PG27": dict(ratio=26.85, T_rated=4.0, eff=0.81, length=45.0, shaft=(8.0, 20.0), src="[cat: pg17]"),
    # precision planetary, NEMA 17 input: the only gearbox whose backlash fits a 0.2 mm placement budget
    "AB042-5": dict(ratio=5.0, T_rated=9.0, eff=0.95, length=60.0, shaft=(10.0, 25.0), src="[cat: Apex AB042][typ]"),
    # strain-wave (harmonic) gear for NEMA 17: near-zero backlash, the placement budget needs it
    "SWG17-30": dict(ratio=30.0, T_rated=4.0, eff=0.70, length=32.0, shaft=(10.0, 20.0),
                     src="[typ] (NEMA 17 strain-wave reducer class, e.g. CSF-11-30 based)"),
}
BACKLASH_ARCMIN = {"PG5": 60.0, "PG14": 60.0, "PG27": 60.0, "AB042-5": 3.0, "SWG17-30": 0.33, "direct": 0.0}   # [cat: pg17 / Apex][typ]
STEP_ACC_DEG = 0.09        # stepper static position accuracy, +-5 % of a 1.8 deg step [typ]
ROTOR_J = {"17HS13-0404S": 3.4e-6, "17HS19-2004S1": 8.2e-6, "17HS19-2004D-E1000": 8.2e-6}   # kg m2 [cat: nema][typ]

# -------------------------------------------------------- pneumatics
# ISO 6432: rod d, rod thread, nose thread, port, barrel OD, body length at
# zero stroke (nose shoulder -> rear eye) [ISO 6432][typ lengths: Festo DSNU].
CYL = {
    8: dict(rod=4.0, rod_thread="M4", nose="M12x1.25", port="M5", od=10.0, body=64.0),
    10: dict(rod=4.0, rod_thread="M4", nose="M12x1.25", port="M5", od=12.0, body=64.0),
    12: dict(rod=6.0, rod_thread="M6", nose="M16x1.5", port="M5", od=14.0, body=75.0),
    16: dict(rod=6.0, rod_thread="M6", nose="M16x1.5", port="M5", od=18.0, body=82.0),
    20: dict(rod=8.0, rod_thread="M8", nose="M22x1.5", port="G1/8", od=22.0, body=95.0),
    25: dict(rod=10.0, rod_thread="M10x1.25", nose="M22x1.5", port="G1/8", od=27.0, body=104.0),
}
CYL_STROKES = (10, 15, 20, 25, 30, 40, 50, 80, 100, 125, 160)
P_SUPPLY = 0.6             # MPa at the valve island, regulated [assumed]
CYL_LOAD_RATIO = 0.7       # required force <= 70 % of theoretical thrust (dynamic) [typ]


def cyl_force(bore, retract=False):
    a = math.pi * bore ** 2 / 4
    if retract:
        a -= math.pi * CYL[bore]["rod"] ** 2 / 4
    return a * P_SUPPLY


def cyl_length(bore, stroke):
    """Retracted length, nose shoulder -> rear eye [derived]."""
    return CYL[bore]["body"] + stroke


AIR = dict(desc="silent oil-free compressor 24 l tank, under the table", fad=35.0, p_max=0.8,
           src="[typ] (Jun-Air 6-25 class)")          # free air delivery Nl/min at 6 bar
AIR_DUTY = 0.5             # compressor may run <= 50 % duty [typ]
EJECTOR = dict(desc="vacuum ejector, 0.5 mm nozzle", q=9.0, src="[typ] (Festo VN-05 class)")   # Nl/min while on
CYL_V_MAX = 1000.0         # mm/s max piston speed with cushioning [typ, ISO 6432 class]

VALVE_ISLAND = dict(model="SMC SY3000 manifold, 24 V DC coils", station_w=10.5, end_w=40.0, depth=60.0,
                    height=33.0, coil_A=0.015, zone_w=18.0, src="[cat: smc][typ]")   # zone_w: pressure-zone plate

# --------------------------------------------------------- electrics / PLC
# Beckhoff: width on the rail (mm), E-bus current (mA; negative = supplies),
# channels. Height 100 x depth 68 unless given [cat: beckhoff] - VERIFY widths
# and currents against the current documentation before ordering.
BECKHOFF = {
    "CX2020": dict(desc="Embedded PC, Celeron 1.4 GHz 2-core, TwinCAT 3 XAR", w=71.0, h=100.0, d=91.0,
                   ebus=0, ch=0, src="[cat: beckhoff][typ w - VERIFY]"),
    "CX2100-0004": dict(desc="CX2000 power supply unit 24 V, E-bus", w=40.0, h=100.0, d=91.0, ebus=-2000,
                        ch=0, src="[cat: beckhoff][typ w - VERIFY]"),
    "EK1100": dict(desc="EtherCAT coupler", w=44.0, ebus=-2000, ch=0, src="[cat: beckhoff]"),
    "EL1809": dict(desc="16 DI 24 V DC, 3 ms, 1-wire", w=12.0, ebus=100, ch=16, kind="DI", src="[cat: beckhoff]"),
    "EL2809": dict(desc="16 DO 24 V DC 0.5 A, 1-wire", w=12.0, ebus=110, ch=16, kind="DO", I_ch=0.5,
                   src="[cat: beckhoff]"),
    "EL2024": dict(desc="4 DO 24 V DC 2 A", w=12.0, ebus=100, ch=4, kind="DO2A", I_ch=2.0, src="[cat: beckhoff]"),
    "EL5101": dict(desc="1 ch incremental encoder RS422, 5 V supply", w=12.0, ebus=130, ch=1, kind="ENC",
                   src="[cat: beckhoff]"),
    "EL7047": dict(desc="1 ch stepper 48 V DC 5 A + incremental encoder input", w=24.0, ebus=140, ch=1,
                   kind="STEP", I_max=5.0, U=48.0, src="[cat: beckhoff][typ w - VERIFY]"),
    "EL3314": dict(desc="4 ch thermocouple (type K) + cold junction", w=12.0, ebus=200, ch=4, kind="TC",
                   src="[cat: beckhoff]"),
    "EL3064": dict(desc="4 ch AI 0..10 V, 12 bit", w=12.0, ebus=130, ch=4, kind="AI", src="[cat: beckhoff]"),
    "EL6224": dict(desc="4 port IO-Link master", w=12.0, ebus=180, ch=4, kind="IOL", src="[cat: beckhoff]"),
    "EL9410": dict(desc="E-bus power refresh 2 A + 24 V feed", w=12.0, ebus=-2000, ch=0, src="[cat: beckhoff]"),
    "EL9011": dict(desc="bus end cover", w=3.0, ebus=0, ch=0, src="[cat: beckhoff][typ w]"),
    "EL1252": dict(desc="2 DI 24 V with distributed-clock timestamps (latch)", w=12.0, ebus=110, ch=2, kind="DITS",
                   src="[cat: beckhoff][typ ebus]"),
    "EL2252": dict(desc="2 DO 24 V with distributed-clock timestamps (camera triggers)", w=12.0, ebus=110, ch=2,
                   kind="DOTS", I_ch=0.5, src="[cat: beckhoff][typ ebus]"),
    # TwinSAFE (Upgrade S-1): safety logic + FSoE safe I/O on the same EtherCAT rail
    "EL6910": dict(desc="TwinSAFE logic terminal (PLe / SIL 3), FSoE master", w=12.0, ebus=188, ch=0,
                   src="[cat: beckhoff][typ ebus - VERIFY]"),
    "EL1904": dict(desc="4 fail-safe DI 24 V (TwinSAFE, clocked test outputs)", w=12.0, ebus=200, ch=4, kind="SI",
                   src="[cat: beckhoff][typ ebus - VERIFY]"),
    "EL2904": dict(desc="4 fail-safe DO 24 V DC 0.5 A (TwinSAFE)", w=12.0, ebus=221, ch=4, kind="SO", I_ch=0.5,
                   src="[cat: beckhoff][typ ebus - VERIFY]"),
}
EL_H, EL_D = 100.0, 68.0

PSU = {        # Mean Well DIN-rail (w x h x d) [cat: meanwell]
    "SDR-120-24": dict(U=24.0, I=5.0, w=40.0, h=125.2, d=113.5),
    "SDR-240-24": dict(U=24.0, I=10.0, w=63.0, h=125.2, d=113.5),
    "SDR-480-24": dict(U=24.0, I=20.0, w=85.5, h=125.2, d=128.5),
    "SDR-480P-48": dict(U=48.0, I=10.0, w=85.5, h=125.2, d=128.5),
}
PSU_LOAD_MAX = 0.8         # continuous load <= 80 % of rating [typ derating]
CX_POWER = dict(CX2020=15.0, EK1100=2.0, terminal=0.5, src="[cat: beckhoff][typ] W from 24 V Us")
SSR_DC = dict(model="Crydom D1D12 DC SSR 12 A on DIN adapter", w=22.5, h=100.0, d=80.0, ctl_A=0.012, src="[typ]")
SSR_AC = dict(model="Crydom D2410-10 AC SSR on DIN adapter", w=45.0, h=100.0, d=80.0, ctl_A=0.012, src="[typ]")
MCB_W = 17.5               # 1 module
SAFETY_RELAY = dict(model="Pilz PNOZ s4 (E-stop, 2 channels) [typ]", w=22.5, h=100.0, d=120.0)   # pre-S-1 only

# ------------------------------------------------ safety (Upgrade S-1, SAFETY_CONCEPT.md)
# Every value here that enters a proof is a class value - VERIFY on the part bought.
SAFE = {
    "estop": dict(desc="E-stop pushbutton, panel mount 22.5 mm, 2 NC positive opening (IEC 60947-5-5, ISO 13850)",
                  head=(40.0, 35.0), block=(30.0, 45.0, 40.0), hole=22.5, src="[typ] (Eaton M22-PV class)"),
    "reset": dict(desc="reset pushbutton, blue, illuminated 22.5 mm, 1 NO", head=(30.0, 20.0),
                  block=(30.0, 45.0, 40.0), hole=22.5, I=0.02, src="[typ] (Eaton M22-DL class)"),
    "guard_lock": dict(desc="guard-locking switch, power-to-unlock, RFID coded (ISO 14119 type 4, high coding), "
                            "2 OSSD = closed AND locked, escape release inside", size=(40.0, 42.0, 148.0),
                       I=0.05, I_lock=0.35, F_hold=2000.0, src="[typ] (Schmersal AZM201 / Euchner CTM class)"),
    "light_curtain": dict(desc="safety light curtain type 4 (IEC 61496-1/-2), 14 mm resolution, 2 OSSD; "
                               "muting evaluated in the TwinSAFE logic", section=(20.0, 20.0), d=14.0,
                          t_resp=0.012, I=0.25, dead=20.0, src="[typ] (SICK deTec4 Core class)"),
    "contactor": dict(desc="contactor 24 V DC coil with mirror contact (IEC 60947-4-1 Annex F), 3 NO",
                      w=45.0, h=90.0, d=95.0, coil_A=0.17, DC1_48=20.0, AC1=22.0, t_off=0.030,
                      src="[typ] (Siemens 3RT2016-1BB42 class)"),
    "stl": dict(desc="safety temperature limiter STB (EN 14597), DIN 22.5 mm, own sensor element, manual reset, "
                     "relay contact in the heater load path", w=22.5, h=100.0, d=115.0, P=3.0, I_AC=3.0, I_DC24=3.0,
                src="[typ] (JUMO safetyM STB class)"),
    "tc_duplex": dict(desc="duplex type K thermocouple: element 1 -> PID (EL3314), element 2 -> STL",
                      src="[typ]"),
    "zone_valve": dict(desc="safe exhaust valve for a pneumatic pressure zone on the island, monitored "
                            "(cat. 2 with position switch)", w=18.0, I=0.05, t_exhaust=0.10,
                       src="[typ] (SMC VP-X / Festo VOFA class)"),
    "muting": dict(desc="muting sensor, M12 inductive in the docking plate (AMR docked)", I=0.02, src="[typ]"),
    "airlock_door": dict(desc="powered sliding guard door kit: 4 mm PC leaf in an Al frame, guides, rodless "
                              "pneumatic drive with force-limited closing, RFID guard-locking switch (2 OSSD = "
                              "closed AND locked)", F_close=50.0, I_lock=0.35, I=0.05,
                         src="[typ] (Festo / SMC rodless drive + Schmersal AZM201 class) - force limit VERIFY"),
    "trapdoor": dict(desc="trapdoor unit: bi-parting drop flaps 2 x 81 mm (PC 4 mm) on spring-return rotary vane "
                          "actuators 0.5 Nm (spring closes them when exhausted), SAFETY inductive sensor (2 OSSD, "
                          "PL d) for 'closed'", T=0.5,
                     arm=0.081, I=0.01, src="[typ] (Festo DSM-10 class)"),
    "dock": dict(desc="AMR dock sensor, M12 inductive in the docking plate", I=0.02, src="[typ]"),
    "reject_shutter": dict(desc="self-closing shutter unit under the reject hole: stainless blade in a guide "
                                "frame, spring-closed; a push pin on the drawer's back wall holds it open only "
                                "when the drawer is fully in (it closes within the first 20 mm of pulling)",
                           t=8.0, src="[design] (sheet-metal part + bought spring)"),
    "brush": dict(desc="brush strip on the reject-bin rim, PP bristles wiping the deck underside", residual=4.0,
                  src="[assumed] residual opening of a brush seal - VERIFY on the fitted strip"),
    "lift_guard": dict(desc="sheet-steel guard box 1.5 mm around the under-deck stacker lifts, flanged to the "
                            "deck, cable / hose grommets", src="[design]"),
    "drawer_switch": dict(desc="RFID safety switch, 2 OSSD, on the reject drawer", I=0.05, src="[typ]"),
    "pc_panel": dict(desc="polycarbonate guard panel 4 mm (EN ISO 14120), screwed to the frame", t=4.0,
                     E=2.3e9, nu=0.37, rho=1200.0, src="[typ] (Makrolon GP class)"),
    "door": dict(desc="guard door leaf: 2020 frame + 4 mm PC, 2 lift-off hinges, handle, actuator for the "
                      "guard-locking switch (bought kit)", depth=24.0, hinges=2, screws=8,
                 src="[typ] (Misumi / item guard door kit class)"),
}
# ISO 13849-1 reliability inputs [typ - VERIFY every value on the bought part's data sheet / SISTEMA library]
#   B10d  cycles until 10 % fail dangerously (electromechanical, pneumatic); MTTFd = B10d / (0.1 n_op)
#   PL    a certified device's own rating (electronic safety devices, TwinSAFE, STB)
RELIAB = {
    "estop": dict(B10d=100_000, src="[typ] E-stop contact blocks"),
    "contactor": dict(B10d=1_300_000, src="[typ] 3RT20 class at nominal DC-1 load"),
    "valve": dict(B10d=10_000_000, src="[typ] monitored exhaust / dump valve"),
    "guard_lock": dict(PL="e", PFHd=1.2e-9, src="[typ] RFID guard-locking switch, certified PL e"),
    "airlock_door": dict(PL="e", PFHd=1.2e-9, src="[typ] same switch class in the door kit"),
    "trapdoor": dict(PL="d", PFHd=2.0e-8, src="[typ] safety inductive sensor with OSSD (PL d)"),
    "drawer_switch": dict(PL="e", PFHd=1.2e-9, src="[typ] RFID safety switch"),
    "stl": dict(PL="d", src="[typ] STB to EN 14597, SIL 2 / PL d certified"),
    "twinsafe": dict(PL="e", PFHd=3.7e-9, src="[typ] EL6910 + EL1904 + EL2904, sum of the three PFHd"),
}
OP_YEAR = dict(days=220, hours=16.0, src="[assumed] two shifts")
# ISO 13849-1:2015 simplified method. Figure 5 read CONSERVATIVELY (where the bar straddles two PLs the
# lower one is taken) - VERIFY against the standard / SISTEMA; Table 11 for series subsystems.
PL_FIG5 = {   # (category, DC class) -> {MTTFd class: PL}
    ("B", "none"): {"low": "a", "medium": "b", "high": "b"},
    ("1", "none"): {"high": "c"},
    ("2", "low"): {"low": "a", "medium": "b", "high": "c"},
    ("2", "medium"): {"low": "b", "medium": "c", "high": "c"},
    ("3", "low"): {"low": "b", "medium": "c", "high": "c"},
    ("3", "medium"): {"low": "c", "medium": "c", "high": "d"},
    ("4", "high"): {"high": "e"},
}


def mttfd_class(y):
    return "high" if y >= 30 else "medium" if y >= 10 else "low" if y >= 3 else "none"


def dc_class(dc):
    return "high" if dc >= 0.99 else "medium" if dc >= 0.90 else "low" if dc >= 0.60 else "none"


def pl_series(pls):
    """ISO 13849-1 Table 11: the lowest PL, one lower if too many subsystems share it."""
    order = "abcde"
    if any(p not in order for p in pls):            # a subsystem reaches no PL at all
        return "-"
    low = min(pls, key=order.index)
    n = sum(1 for p in pls if p == low)
    limit = {"a": 3, "b": 2, "c": 2, "d": 3, "e": 3}[low]
    return low if n <= limit else (order[order.index(low) - 1] if low != "a" else "-")


# ISO 13855:2010 approach speeds, ISO 13857:2019 Table 4 (persons >= 14 years, upper limbs)
ISO13855 = dict(K_hand=2000.0, K_slow=1600.0, S_min=100.0, src="[ISO 13855] S = K T + 8 (d - 14)")
ISO13857_T4 = (   # (e_max mm, slot distance, square distance, round distance)
    (4.0, 2.0, 2.0, 2.0), (6.0, 10.0, 5.0, 5.0), (8.0, 20.0, 15.0, 5.0), (10.0, 80.0, 25.0, 20.0),
    (12.0, 100.0, 80.0, 80.0), (20.0, 120.0, 120.0, 120.0), (30.0, 850.0, 120.0, 120.0),
    (40.0, 850.0, 200.0, 120.0), (120.0, 850.0, 850.0, 850.0),
)
ISO13857_ARM = 850.0          # e > 120 mm: whole arm to the shoulder (and beyond: body access) - treat as 850
T_LOGIC = 0.030               # TwinSAFE reaction (input filter + FSoE watchdog share + logic) [typ - VERIFY with
                              # the Beckhoff TwinSAFE reaction-time calculation]
F_LOW = 50.0                  # N: a drive that can push no more than this is treated as low-energy (no crush /
                              # shear hazard) [assumed - the risk assessment must confirm; ISO/TS 15066 hand
                              # transient limit is 140 N, so 50 N leaves a margin]


def iso13857_distance(e, shape="slot"):
    """Minimum safety distance (mm) behind an opening of smallest width e (ISO 13857 Table 4)."""
    col = {"slot": 1, "square": 2, "round": 3}[shape]
    for row in ISO13857_T4:
        if e <= row[0] + 1e-9:
            return row[col]
    return ISO13857_ARM
CU_RHO = 0.0175            # Ohm mm2 / m
CABLE = {  # field cables [typ]: conductors x mm2, OD mm
    "M12-3": (3, 0.34, 5.0), "M12-4": (4, 0.34, 5.0), "motor-4": (4, 0.5, 6.5), "enc-8": (8, 0.14, 6.0),
    "tc-K": (2, 0.22, 3.5), "mains-3": (3, 1.0, 7.0), "dc-2": (2, 0.75, 5.5), "multipole-25": (25, 0.25, 11.0),
    "gige": (8, 0.14, 6.5), "iol-4": (4, 0.34, 5.0), "M12-5": (5, 0.34, 5.5), "M12-8": (8, 0.25, 6.0),
    "wire-0.75": (1, 0.75, 2.5),
}
PSU_EFF = 0.90             # Mean Well SDR efficiency [cat: meanwell][typ]
THERMAL = dict(k=5.5, dT_max=20.0, fan_m3h=60.0, src="[IEC 60890 simplified][typ] W/m2K, K, filter fan")
VDROP_MAX = 0.03           # <= 3 % voltage drop on a DC supply cable [typ, EN 60204-1 practice]

# conveyor & machine-specific bought parts
CHAIN = dict(desc="side-flexing flat-top chain, POM, 63 mm", w=63.0, pitch=12.7, mass=1.0, wl=1200.0, mu=0.25,
             src="[typ] (Regina/Rexnord 1873-class; mass kg/m, working load N at 20 C, mu on UHMW-PE)")
BEND = dict(desc="plain bend 180 deg, UHMW-PE track in an aluminium body", src="[typ]")
DRIVE_UNIT = dict(desc="intermediate (caterpillar) drive for side-flex chain, sprocket Z = 16", pd=65.0,
                  src="[typ]")        # effective pitch diameter on the chain
TUBE = dict(desc="extruded PMMA tube 53 x 3 (ID 47)", od=53.0, id=47.0, src="[typ]")
GUIDE_BAR = dict(desc="stainless flat bar 15 x 6 with UHMW facing", material="steel", src="[typ]")

TERMINAL_BLOCK = dict(model="Phoenix PT 2.5 push-in", pitch=5.2, src="[cat: Phoenix Contact PT 2,5][typ]")
TERMINAL_BLOCK2 = dict(model="Phoenix PTTB 2.5 double-level push-in (+24 V / 0 V)", pitch=5.2, h=75.0, d=60.0,
                       src="[cat: Phoenix Contact PTTB 2,5][typ]")
MCB = dict(model="1-pole MCB", w=17.5, src="[typ]")
SSR = dict(model="Crydom D2410-10 on DIN adapter", w=45.0, ctl_A=0.012, src="[typ]")
DUCT = dict(w=40.0, h=60.0, src="[typ] slotted wiring duct 40x60")
RAIL = dict(w=35.0, h=7.5, src="[EN 60715] TS35x7.5")

FIELD = {      # all 24 V PNP, M12 A-coded unless noted
    "diffuse_M12": dict(desc="diffuse photoelectric M12, PNP NO", size=(15.0, 7.5, 15.0), I=0.03,
                        src="[typ] (ifm OGH / Sick W4 class)"),
    "tof_level": dict(desc="ToF distance sensor, IO-Link", size=(20.0, 20.0, 12.0), I=0.05,
                      src="[typ] (ifm O1D class)"),
    "nfc_head": dict(desc="13.56 MHz RFID read/write head, IO-Link, ISO 15693", size=(40.0, 34.0, 25.0), I=0.08,
                     src="[typ] (ifm DTI410 / Balluff BIS M class)"),
    "encoder_wheel": dict(desc="measuring-wheel encoder 1024 ppr RS422, wheel C = 200 mm", ppr=1024, circ=200.0,
                          I=0.1, src="[typ] (Kuebler 3720 class)"),
    "tc_K": dict(desc="type K thermocouple, 3 mm sheath", I=0.0, src="[typ]"),
    "colour_sensor": dict(desc="true-colour sensor, 3 x 0..10 V (R, G, B)", I=0.05, src="[typ]"),
    "reed": dict(desc="cylinder reed switch, PNP, T-slot", I=0.01, src="[typ]"),
    "vac_switch": dict(desc="vacuum switch, PNP", I=0.02, src="[typ]"),
    "vac_iol": dict(desc="vacuum sensor -1..0 bar, IO-Link (analogue grip quality)", I=0.03, src="[typ] (ifm PV class)"),
    "pressure_iol": dict(desc="pressure sensor 0..10 bar, IO-Link (stamp force = p x A)", I=0.03,
                         src="[typ] (ifm PN class)"),
    "ir_pyrometer": dict(desc="IR pyrometer 0..300 C, 0..10 V, 15:1 optics", size=(15.0, 30.0, 15.0), I=0.05,
                         src="[typ] (Optris CS class)"),
}
LOADS = {      # powered loads that are not motors
    "heater_bar": dict(desc="IR quartz heater bar 230 V AC 300 W via SSR", P=300.0, I=0.012, src="[typ]"),
    "fan_80": dict(desc="80 mm 24 V DC fan, 4 holes 71.5 sq for M4", I=0.15, holes=71.5, flange=4.0, src="[typ]"),
    "ringlight": dict(desc="LED ring light 24 V", I=0.4, src="[typ]"),
    "valve_coil": dict(desc="SY3000 coil 24 V 0.35 W", I=0.015, src="[cat: smc][typ]"),
    "sealer_head": dict(desc="heated sealing bar 24 V 60 W", I=2.5, src="[typ]"),
    "singulator": dict(desc="rotary disc: NEMA 17 on EL7047", I=0.0, src="[derived]"),
    "exhaust_fan": dict(desc="24 V EC duct fan D60, oven vapour exhaust", I=0.4, src="[typ]"),
}

# ------------------------------------------------------------- band oven (2026-10-02, oven.py)
STEEL_RHO = 7900.0         # kg/m3 stainless
# straight tubular heating elements, Incoloy 800 sheath, 230 V, cold ends through the side walls with an
# M14 gland; heated length spans the chamber, the cold ends cross the insulation      [typ] (Backer/Watlow)
TUBULAR = [dict(model=f"tubular element D8.5 {lh} mm heated, {P} W 230 V", d=8.5, L_heated=float(lh),
                L=float(lh) + 2 * 75.0, P=float(P), gland="M14x1.5", src="[typ]")
           for lh in (300, 350, 380, 400, 450, 500) for P in (250, 350, 500, 650, 800)]
TUBULAR_WCM2 = 5.0         # sheath surface load limit in forced air (Incoloy, 200 C air)        [typ]
BAND_MESH = dict(desc="balanced-weave stainless mesh band, 1.2 mm wire, flat edges", cp=500.0, t=5.0,
                 mu_skid=0.25, src="[typ] (Wire Belt / Cambridge class)")
INSULATION = {
    "mineral wool": dict(rho=100.0, cp=840.0, k=lambda T: 0.035 + 1.0e-4 * T, T_max=650.0,
                         src="[typ] (Rockwool board 100 kg/m3: k 0.045 at 100 C, 0.055 at 200 C)"),
}
OVEN_FAN = dict(desc="oven circulation fan: 230 V shaded-pole motor outside the roof, long shaft, "
                     "D90 radial impeller inside", P=35.0, I=0.25, d_imp=90.0, motor=(60.0, 60.0, 70.0),
                src="[typ] (EBM-papst RRL class)")
RELAY6 = dict(model="Phoenix PLC-RSC 24DC/21 coupling relay 6.2 mm (230 V fan)", w=6.2, h=80.0, d=94.0, ctl_A=0.009,
              I=6.0, src="[cat: Phoenix Contact PLC-RSC][typ]")
ZONE_CONTACTOR = dict(desc="oven zone contactor 3-pole AC-1 25 A, 24 V DC coil; the zone STB contact is in its coil",
                      w=45.0, h=90.0, d=95.0, coil_A=0.17, AC1=25.0, src="[typ] (3RT2015 class)")
MCB3 = dict(model="3-pole MCB C16 (oven zone feed)", w=52.5, src="[typ]")
COOL_FAN = dict(desc="120 mm 24 V DC axial fan, band cooling", I=0.25, size=120.0, holes=105.0, src="[typ]")
SSR_AC25 = dict(model="Crydom D2425 25 A AC SSR on a DIN heatsink", w=45.0, h=100.0, d=110.0, ctl_A=0.012,
                I=25.0, U_drop=1.6, R_th=1.1, src="[typ] (heatsink K/W for the derating check)")
CT_AC = dict(model="AC current transducer, split core, 0..20 A true RMS -> 0..10 V, 24 V DC fed", w=22.5, h=90.0,
             d=60.0, range=20.0, acc=0.01, t_resp=0.3, I=0.02,
             src="[typ] (acc of range, t_resp to 95 %; heater-break detection on the element feed)")
SUPPLY = dict(desc="400 V 3N~ 50 Hz, CEE 16 A 5-pole plug, main switch, RCD type A 30 mA", U=230.0, U_LL=400.0,
              I=16.0, load_max=0.8, rcd_mA=30.0, src="[typ] IEC 60309 / IEC 60204-1")
TEMP_LIMIT = {"POM chain": 80.0, "UHMW-PE track": 80.0, "NFC tag": 85.0}   # C, continuous [typ]
LEAK_mA = dict(tubular=0.5, psu=0.5, src="[typ] protective-conductor current per item, hot and dry")
CABLE_AC = {1.5: dict(I=16.0, T=180.0, model="SiF 1.5 mm2 (silicone, 180 C)"),       # free air, in the oven
            2.5: dict(I=21.0, T=90.0, model="H07V-K 2.5 mm2 in the cabinet")}         # [typ] IEC 60364-5-52


# ------------------------------------------------------------- self-check
def verify():
    """Consistency of the catalogue itself (not of the machine). Returns
    (fails, typ): typ lists every entry still to verify on the bought part."""
    fails, typ = [], []
    for k, t in THREAD.items():
        c = t["clear"]
        if not (t["d"] < c[0] < c[1] < c[2]):
            fails.append(f"ISO 273 series not ordered for {k}")
        if list(t["lengths"]) != sorted(t["lengths"]):
            fails.append(f"stock lengths of {k} not sorted")
        if abs(t["tap"] - (t["d"] - t["P"])) > 0.05:
            fails.append(f"tap drill of {k} != d - P")
        if t["head"][0] <= t["washer"][0]:
            fails.append(f"head of {k} falls through its washer")
    for k, n in TNUT.items():
        d = THREAD[n["thread"]]["d"]
        if n["h"] < 0.8 * d - 1e-9:
            fails.append(f"T-nut {k}: thread length {n['h']} < 0.8 d = {0.8 * d}")
    for s, p in PROFILE.items():
        tn = TNUT[p["tnut"]]
        if not (p["slot"] < tn["w"] <= p["inner"]):
            fails.append(f"T-nut {p['tnut']} does not fit / hold in profile {s}")
        if p["depth"] <= p["lip"] + tn["h"]:
            fails.append(f"profile {s}: channel too shallow for {p['tnut']}")
    for table in (PROFILE, TNUT, BRACKET, MGN, LEADSCREW, BEARING, STEPPER, GEARBOX, BECKHOFF, FIELD, LOADS, SAFE,
                  RELIAB):
        for k, v in table.items():
            s = v.get("src", "")
            if "typ" in s or "VERIFY" in s:
                typ.append(str(k))
    typ += ["CYL body lengths", "VALVE_ISLAND", "TABLE_PLATE", "STEP_DERATE", "MIN_ENGAGE", "T_LOGIC", "F_LOW"]
    prev = 0.0
    for row in ISO13857_T4:
        if row[0] <= prev:
            fails.append("ISO 13857 table not ordered")
        prev = row[0]
    return fails, typ


if __name__ == "__main__":
    f, t = verify()
    print(f"hardware catalogue: {len(THREAD)} threads, {len(PROFILE)} profiles, {len(MGN)} rails, "
          f"{len(STEPPER)} steppers, {len(CYL)} cylinder bores, {len(BECKHOFF)} Beckhoff items")
    print("\n".join(f) if f else "catalogue self-check PASS")
    print(f"{len(t)} entries are [typ]/VERIFY - reconcile with the purchase list:\n  " + ", ".join(t))
