"""
STF-2 - a CONTINUOUS tabletop cookie line (redesign of the fischertechnik 536634 factory).

THE ONE PARAMETER TABLE for the redesign. Geometry, timing, drawings, CAD and the
flow simulation are all generated from `L` below; nothing downstream may retype
a number. `check()` must pass before anything is drawn or built.

Why a redesign: the 536634 factory is stop-and-go by construction - one VGR
serves every transfer, the oven is a batch station (door, slider, single part),
the warehouse crane and the sorting belt start and stop per workpiece. Its
throughput is set by the slowest serial chain and any one machine down stops the
factory.

STF-2 principles
  1. ONE conveyor that never stops: a side-flexing flat-top chain loop carrying
     N pucks at a fixed pitch P (an "electronic line shaft": every station
     synchronises to the loop's master encoder). takt = P / v.
  2. Every process happens ON THE FLY: gravity drop with lead compensation,
     tunnel oven + cooling tunnel (time = length / v), a flying stamp that tracks
     the belt, vision QC + on-the-fly reject, tracking delta pickers.
  3. No single bot: two delta pickers, each alone faster than the takt (N+1);
     the upstream one picks, the downstream one catches its misses.
  4. Nothing ever stops the loop: a missed / unplaceable cookie RECIRCULATES
     (the feeder sees a full puck and skips it), a starved flavour leaves an
     empty puck - both are losses the simulation counts, never a stop.
  5. The product carries its recipe: an NFC tag in every puck (flavour, state,
     QC result), written at the feeder and QC, read at the pickers.
  6. Physical AI hooks: vision QC (trained on images rendered from this twin),
     camera tracking for the pickers, per-motor current/encoder health, all
     stations as autonomous agents on one time base.

PRECISE BUILD PHASE (v4, 2026-09-28): every actuator, profile and bought part is
a real catalogue item from hardware.py (Part.hw = catalogue key), every drive is
SIZED (sizing()), and interference() proves that no two solids share volume -
ACROSS AND WITHIN modules, with every allowed overlap declared (ALLOW) - instead
of the old bounding-box check between modules only. joints.py then fastens every
contact; plc_io.py derives the Beckhoff I/O from the tags below.

Frame: TABLE frame, +X to the right (table length), +Y to the back, +Z up, mm.
Table (deck) top face at z = 0, deck underside at z = -TABLE[2].
Parts: box  p = min corner, s = size
       cyl  p = centre of the start face, s = (axis 'x'|'y'|'z', length, diameter)
       rod  p = (x0,y0,z0), s = (x1,y1,z1, diameter)   (any direction)
       arc  p = (cx,cy,z0), s = (r_in, r_out, height, a0_deg, a1_deg)
Source tags on parameters: [ft] fischertechnik datasheet/booklet, [hw] hardware.py
catalogue, [derived] computed here, [assumed] design choice - MEASURE.
"""
import math
from dataclasses import dataclass

import hardware as H

# --------------------------------------------------------------- parameters
L = dict(
    TABLE=(1870.0, 1510.0, 12.0),           # [ft] footprint of the 536634 twin; deck = hw TABLE_PLATE, 12 mm so an
                                             # M6 through a 4 mm bracket has a stock length that neither under-engages
                                             # nor pokes into the enclosure under the deck
    # ---- the loop (side-flexing flat-top chain, hw CHAIN)
    PITCH=80.0,                              # puck pitch on the chain                 [assumed]
    N=48,                                    # pucks on the loop
    R=200.0,                                 # curve radius (centreline)
    V=20.0,                                  # chain speed mm/s -> takt = PITCH / V
    CL=(280.0, 560.0),                       # centre of the LEFT curve
    BELT_W=64.0, CHAIN_T=10.0, BELT_Z=80.0,  # chain width (63 + side play), thickness, top face height
    GUIDE_T=6.0, GUIDE_H=15.0,               # puck side guides (hw GUIDE_BAR)
    FRAME="2040",                            # chain track: 2040 laid flat under the chain  [hw]
    TAKEUP=5.0,                              # chain take-up range of the drive unit   [assumed]
    DRIVE_X=(1120.0, 1250.0), DRIVE_Z=35.0,  # intermediate drive on the back run, sprocket axis height
    LEGS_FRONT=(320.0, 640.0, 960.0, 1280.0, 1530.0), LEGS_BACK=(320.0, 640.0, 960.0, 1290.0, 1530.0),
    GB_FRONT=(440.0, 700.0, 950.0, 1200.0, 1450.0), GB_BACK=(520.0, 760.0, 1000.0, 1260.0, 1356.0),
    CURVE_LEGS=(-60.0, 0.0, 60.0),           # leg angles on each bend (relative to its apex)
    CHAIN_MU_CURVE=0.25,                     # chain on the bend track (capstan)            [hw CHAIN mu]
    # ---- carrier / product
    PUCK=(60.0, 12.0), PUCK_M=0.06,          # puck D x H (NFC tag inside), mass kg         [assumed]
    NEST=(48.0, 2.0),                        # chamfered nest D x depth               [assumed]
    COOKIE=(45.0, 20.0), COOKIE_M=0.03,      # workpiece D x H [ft], mass kg [assumed]
    FLAVOURS=("weiss", "rot", "blau"),       # vanilla / strawberry / chocolate (sorting-line bins)
    MIX=(1, 1, 1),                           # demand ratio -> heijunka sequence W R B W R B ...
    RAW="#f2eee6", BAKED=("#efe0b0", "#d9536f", "#4a2c17"),
    # ---- M2 feeder: dual magazine per flavour (A/B swap = refill without stopping)
    MAG_X=(330.0, 390.0, 450.0, 510.0, 570.0, 630.0),   # tube axes over the front run (pitch 60)
    MAG_OD=H.TUBE["od"], MAG_ID=H.TUBE["id"], MAG_CAP=10,
    ESC_BLOCK=(56.0, 180.0, 25.0),           # POM escapement block per tube (holds the tube, guides the gate)
    GATE_Z=(5.0, 15.0),                      # gate slot in the block: bottom / top above the block underside
    ESC_CYL=(10, 50),                        # ISO 6432 bore x stroke                 [hw]
    ESC_F=5.0,                               # N to pull the gate under a full tube   [assumed, MEASURE]
    # bulk raw stock: one tall hopper per flavour + rotary singulating disc     [assumed]
    HOPPER=(200.0, 240.0, 310.0), HOPPER_Z=560.0, HOPPER_X=(150.0, 360.0, 570.0), HOPPER_Y=20.0,  # over their tubes
    CHUTE_SLOPE=30.0,                        # min chute angle for a cookie sliding on PMMA (mu ~0.3 = 17 deg)
    SING_T=0.5,                              # Nm on the singulator disc                [assumed, MEASURE]
    PACKING=0.50,                            # bulk packing fraction of loose cookies  [assumed, MEASURE]
    SINGULATE_S=1.5,                         # s per cookie from the disc (must beat the flavour rate)
    MAX_H=900.0,                             # user: "taller is fine" - nothing above this
    DROP_H=15.0,                             # escapement block underside above the seated cookie top
    VALVE_JITTER=0.005,                      # s, release-time jitter (valve + scan)  [assumed]
    NFC_WRITE_X=590.0,                       # writes the flavour the heijunka sequence assigned to the puck
    # ---- M3 tunnel oven + cooling tunnel
    BAKE_S=24.0, COOL_S=12.0,                # residence times (s)                    [assumed]
    OVEN_X0=660.0, TUN_GAP=20.0,
    TUN_HALF=80.0, TUN_WALL=12.0, TUN_ROOF=15.0, TUN_CLEAR=40.0,   # clear height above the cookie
    CURTAIN_GAP=5.0,                         # fabric curtain hem above the cookie top
    HEATERS=3, FANS=2,
    # ---- M4 flying stamp (decor / processing on the fly): MGN12H + Tr8x4 + NEMA 17
    STAMP_X0=1455.0, STAMP_STROKE=60.0, STAMP_CLEAR=30.0, STAMP_D=40.0,
    STAMP_T=dict(sync=0.30, down=0.25, dwell=0.50, up=0.25, settle=0.20), RETURN_V=4.0,
    STAMP_CYL=(16, 30), STAMP_F=40.0, ROD_OUT=20.0,    # ISO 6432 bore x stroke, stamp force N [assumed], rod out
    CARR_L=60.0, STAMP_M=1.5, T_ACC=0.05,               # carriage length, moving mass kg, accel time s [assumed]
    STAMP_RAIL="MGN12H", STAMP_RAIL_DY=-25.0, STAMP_SCREW="Tr8x4", STAMP_MOTOR="17HS19-2004D-E1000",
    # ---- M5 vision QC + reject
    QC_X=(1360.0, 1500.0), CAM_X=1420.0, CS_X=1470.0, SENSOR_GAP=25.0,   # colour sensor at the hood entry (its mount clears the ring light)
    AI_LATENCY=0.50,                         # s, camera -> verdict budget            [assumed]
    KICK_X=1310.0, KICK_STROKE=100.0, KICK_T=0.20, KICK_W=40.0, KICK_CYL=(10, 100), KICK_Z=130.0,
    FUNNEL=(70.0, 70.0),
    # ---- M6 pick & place: two delta robots, each alone faster than the takt
    DELTA_X=(910.0, 590.0),                 # A (upstream on the back run), B
    DELTA_Y=905.0, DELTA_Z=510.0,            # base (shoulder plane)
    DELTA_RB=70.0, DELTA_RE=30.0, DELTA_L1=130.0, DELTA_L2=300.0,
    DELTA_LIM=(-60.0, 90.0),                 # shoulder limits (deg, + = arm down)
    DELTA_ROT=(-15.0, 165.0),                # arm set rotation: the 90 deg arm/motor gap faces the other delta
    CUP_L=40.0, TRAVEL_Z=250.0,              # effector underside -> cup tip; home/travel height
    T_PICK=2.0, T_GRAB=0.8,                  # full pick-place cycle; reach+grip part  [assumed]
    PICK_OK=0.995,                           # grip success probability                [assumed]
    DELTA_MOTOR="17HS19-2004D-E1000", DELTA_GEAR="SWG17-30",
    DELTA_PAYLOAD=0.15, DELTA_ARM_M=0.06,    # effector+cup+cookie+half forearms kg, upper arm kg [assumed]
    DELTA_ACC=5.0, DELTA_VMAX=0.5,           # m/s2, m/s effector peaks for a 2 s cycle        [assumed]
    MOTOR_GAP=12.0,                          # gearbox face -> upper arm plane (clamp hub)
    # ---- M7 box lanes + gravity flow racks (no stacker crane)
    LANE_Y=(890.0, 960.0, 1030.0), LANE_X=(150.0, 1330.0), LANE_Z=80.0, LANE_W=60.0,
    BOX=(160.0, 55.0, 25.0), PACK=3, PACK_M=0.10,     # sealed pack envelope: tray + film; mass kg [assumed]
    # the pack: thermoformed tray with 3 round pockets, top-sealed with a peelable film  [assumed]
    TRAY_H=24.0, FLANGE=3.0, POCKET_D=46.5, POCKET_DEPTH=21.0, POCKET_PITCH=51.0, FILM_T=0.06,
    INDEX_ERR=0.3, DELTA_REP=0.2, CUP_ECC=0.1,           # placement error budget (mm)
    SEAL_X=1210.0, SEAL_T=1.0, FILM_M=100.0, REELS=2,     # per-lane top sealer, twin reel auto-splice
    SEAL_CYL=(25, 30), SEAL_P=0.15, SEAL_GAP=25.0,        # ISO 6432, seal pressure MPa [assumed], head lift
    REEL_DX=76.0, REEL_SIDE=(1, -1, 1), ARM_SIDE=(1, 1, -1),   # reels alternate down/upstream so the
                                                          # 15 mm reel arms have room between the lanes
    CASS_WALL=2.0, PAWL=2.0,                              # cassette wall, pawl engagement under the flange
    T_INDEX=2.0,
    # finished stock: bottom-up stacker at each lane end fills a tall pack cassette; an
    # overhead shuttle (MGN12H under a lane beam, GT2 belt) swaps it to the AMR port  [assumed]
    CASS=(170.0, 65.0, 705.0), CASS_X=(1345.0, 1545.0), CASS_Z=110.0, STACK_T=1.0, SWAP_T=3.0,
    STACK_CYL=(16, 30), PAWL_F=2.0, CASS_M=0.8,           # stacker cylinder, spring force per pawl N, empty kg
    BOXMAG_X=(160.0, 330.0), BOXMAG_CAP=60, BOX_NEST=8.0, FORK_CYL=(8, 10),
    # rejects: chute through the table deck into a drawer bin under the table
    REJECT_BIN=(1255.0, 480.0, 240.0, 240.0, 290.0),     # x, y, w, d, h (below the deck); S-1c: 30 mm back
                                                          # so the bin covers the whole deck hole
    FUNNEL_OUT=50.0,                                      # square outlet of the funnel = the hole in the deck
    REJECT_GAP=10.0,                                      # bin top below the deck underside (the shutter's room)
    # AMR service (the stock is finite; the AMR loop is what makes it unlimited)       [assumed]
    N_AMR=2, AMR_TRIP=60.0, AMR_HANDLE=30.0, RAW_TOTE=200,
    REQ_HOPPER=0.35, REQ_BOXMAG=0.50, REQ_REJECT=0.70,
    # ---- M8 control: Beckhoff enclosure UNDER the deck; air from an off-table compressor
    CAB=(250.0, 300.0, 980.0, 720.0, 210.0),             # x, y, w, d, h of the enclosure under the deck
                                                          # (S-1: +TwinSAFE rail, contactors, STLs -> grown)
                                                          # (sized by plc_io.cabinet(); clear of the reject bin)
    ISLAND_XY=(700.0, 480.0), FRL=(60.0, 60.0, 90.0),
    VALVE_SPARE=0.2,                                      # >= 20 % spare valve stations
    # ---- Upgrade PA-1 (physical AI): every actuator reports back, sensing where decisions happen
    PA1=True,
    SING_MOTOR="17HS19-2004D-E1000", LANE_MOTOR="17HS19-2004D-E1000", SHUTTLE_MOTOR="17HS19-2004D-E1000",
    DROP_CHECK_X=635.0,                                   # I9 landing check after the last tube
    PYRO_X=1142.5,                                        # IR1 product temperature in the oven/cooler gap
    PACK_CAM=(1070.0, 960.0, 590.0),                      # CAM4 over the three lanes, before the sealer
    # ---- Upgrade S-1 (safety, SAFETY_CONCEPT.md): a closed perimeter guard - the loop runs through every
    # module, so no partial guard can close around a hazard. 2020 frame, 4 mm PC outside it, PC roof.
    SAFE1=True,
    GUARD_PC=4.0, GUARD_TOP=896.0,                        # panel thickness; top of the top rails (roof above)
    GUARD_IN=dict(F1=16.0, F2=60.0, back=60.0, left=14.0, right=14.0),   # panel outer face from the deck edge:
                                                          # 14-16 behind the docking plates, 60 where an E-stop sits
    GUARD_STEP_X=800.0,                                   # front wall steps from F1 (feeder) to F2 here
    RAW_Y=150.0,                                          # raw port: roof rail centre; the hopper strip in front of
                                                          # it is the AMR pour opening, fixed lids behind it
    ROOF_X=(820.0, 1340.0), ROOF_Y=(510.0, 980.0),        # internal 2040 roof rails (centres)
    GUARD_POSTS=dict(F1=(120.0,), left=(400.0,), right=(450.0,)),
    DOORS=(("S20", "F2", 1000.0, 1700.0), ("S21", "back", 400.0, 1100.0), ("S22", "back", 1200.0, 1800.0)),
    # port openings: (wall, outer y of the two port posts, opening z0..z1, tag of its guard)
    PORT_OPEN=dict(boxes=("left", 798.0, 1120.0, 616.0, 876.0, "S30"), out=("right", 798.0, 1128.0, 40.0, 876.0, "S31")),
    # ---- AMR airlocks (S-1b): the side ports open only into closed chambers; the machine side is shut
    AIRLOCK=True,
    BOX_LOCK=dict(x1=380.0, y0=822.0, y1=1096.0, zf=610.0),    # chamber over the tray magazines: posts x ..x1,
                                                               # walls y0-4 / y1+4, floor zf..zf+6 with trapdoors
    OUT_LOCK=dict(x=1522.0, hx=1530.0, y0=822.0, y1=1104.0, park=1396.0, zdoor=834.0),   # inner door leaf x..hx,
                                                               # header hx..hx+30; chamber walls y0-4 / y1; the
                                                               # inner door parks behind the lanes up to y=park
    SHUTTLE_V=100.0, DOOR_T=1.5, AMR_EXCH=20.0,                # mm/s carrier, s per door stroke, s AMR swap [assumed]
    CASS_LEAD=75.0,                                            # s: the cassette task is raised this long before
                                                               # the lift counter says full (AMR trip + margin)
    CASS_STAGGER=True,                                         # policy: the 3 lanes' cassettes are a third of a
                                                               # fill apart, so exchanges never coincide
    ESTOPS=(("S10", "F2", 1765.0, 450.0), ("S11", "back", 1150.0, 450.0), ("S12", "back", 1816.0, 620.0)),
    RESET=("S13", "F2", 1805.0, 450.0),
    LOCK_Z=400.0,                                         # guard-locking switch underside
    PORT_ZONE=dict(boxes=("trapdoor",), out=("gantry",)),   # part groups a port's zone stops (S-1b airlocks:
                                                          # only what is IN the chamber; lanes + stackers run on)
    SS1_MARGIN=0.2,                                       # s added to the longest ramp-down before K1/K2 drop
    UNLOCK_STILL=1.0,                                     # s of encoder standstill before a door unlocks (SF2)
)

FLAV = L["FLAVOURS"]
G = 9.81


@dataclass
class Part:
    name: str
    module: str
    group: str
    kind: str
    p: tuple
    s: tuple
    colour: str = "#8b9196"
    joint: str = ""
    tag: str = ""
    mech: str = ""
    note: str = ""
    hw: str = ""

    def aabb(self):
        x, y, z = self.p
        if self.kind == "box":
            return (x, y, z, x + self.s[0], y + self.s[1], z + self.s[2])
        if self.kind == "cyl":
            ax, Ln, d = self.s
            r = d / 2
            if ax == "x":
                return (x, y - r, z - r, x + Ln, y + r, z + r)
            if ax == "y":
                return (x - r, y, z - r, x + r, y + Ln, z + r)
            return (x - r, y - r, z, x + r, y + r, z + Ln)
        if self.kind == "rod":
            x1, y1, z1, d = self.s
            r = d / 2
            return (min(x, x1) - r, min(y, y1) - r, min(z, z1) - r,
                    max(x, x1) + r, max(y, y1) + r, max(z, z1) + r)
        if self.kind == "arc":
            ri, ro, h, a0, a1 = self.s
            xs, ys = [], []
            angs = [a0, a1] + [a for a in (0, 90, 180, 270, 360, -90, -180) if a0 <= a <= a1]
            for a in angs:
                for r in (ri, ro):
                    xs.append(x + r * math.cos(math.radians(a)))
                    ys.append(y + r * math.sin(math.radians(a)))
            return (min(xs), min(ys), z, max(xs), max(ys), z + h)
        raise ValueError(self.kind)


def g1(v):
    """Snap a derived coordinate to the 0.1 mm manufacturing grid."""
    return round(v * 10.0) / 10.0


# --------------------------------------------------------------- the loop path
def takt():
    return L["PITCH"] / L["V"]


def straight():
    """Straight length S, on the 0.1 mm grid: N * P = 2 S + 2 pi R within the take-up."""
    return g1((L["N"] * L["PITCH"] - 2 * math.pi * L["R"]) / 2)


def loop_len():
    return 2 * straight() + 2 * math.pi * L["R"]


def centres():
    cl = L["CL"]
    return cl, (g1(cl[0] + straight()), cl[1])


def y_front():
    return L["CL"][1] - L["R"]


def y_back():
    return L["CL"][1] + L["R"]


def pos(s):
    """Point and heading (deg) of the loop centreline at arc length s.
    s = 0 at the start of the FRONT run (flow +X), then the right curve, the
    back run (flow -X), the left curve."""
    S, R = straight(), L["R"]
    (clx, cly), (crx, cry) = centres()
    s %= loop_len()
    if s <= S:
        return (clx + s, cly - R), 0.0
    s -= S
    if s <= math.pi * R:
        th = -math.pi / 2 + s / R
        return (crx + R * math.cos(th), cry + R * math.sin(th)), math.degrees(th) + 90
    s -= math.pi * R
    if s <= S:
        return (crx - s, cry + R), 180.0
    s -= S
    th = math.pi / 2 + s / R
    return (clx + R * math.cos(th), cly + R * math.sin(th)), math.degrees(th) + 90


def s_front(x):
    return x - L["CL"][0]


def s_back(x):
    S, R = straight(), L["R"]
    crx = centres()[1][0]
    return S + math.pi * R + (crx - x)


def z_puck_top():
    return L["BELT_Z"] + L["PUCK"][1]


def z_seat():
    """Underside of a seated cookie (nest bottom)."""
    return z_puck_top() - L["NEST"][1]


def z_cookie_top():
    return z_seat() + L["COOKIE"][1]


def z_frame():
    """Underside / top of the chain track (the chain rides on its top face)."""
    top = L["BELT_Z"] - L["CHAIN_T"]
    return top - H.SECTION[L["FRAME"]][1], top


# ------------------------------------------------------------ stock (derived)
def cookie_vol():
    d, h = L["COOKIE"]
    return math.pi * (d / 2) ** 2 * h


def hopper_cap():
    w, d, h = L["HOPPER"]
    return int(w * d * h * L["PACKING"] / cookie_vol())


def cass_cap():
    """packs per cassette: the stack height inside the cassette over the pack height"""
    return int((L["CASS"][2] - 30.0) // L["BOX"][2])


def lift_guard_box():
    """(x0, y0, z0, x1, y1, z1) of the sheet box around the under-deck stacker lifts and their reeds."""
    xa, cw = L["CASS_X"][0], L["CASS"][0]
    xc = xa + cw / 2
    bore = L["STACK_CYL"][0]
    zt = -L["TABLE"][2]
    return (xc - 40.0, L["LANE_Y"][0] - 25.0, zt - 128.0, xc + 40.0, L["LANE_Y"][-1] + 25.0, zt)


def _lift_guard(A):
    x0, y0, z0, x1, y1, z1 = lift_guard_box()
    t = 1.5
    hollow(A, "lift_guard", "pack", "stacker", x0, y0, z0, x1 - x0, y1 - y0, z1 - z0, t, "#6b7078",
           hw="sheet-steel lift guard 1.5 mm", note="closed box under the deck around the three stacker lifts "
           "(fixed guard, tool to remove); rods leave it only through the deck")
    for suf, fx in (("_flange", x0 - 20.0), ("_wall_top", x1)):        # screw flanges on the deck underside
        A(Part(f"lift_guard{suf}", "pack", "stacker", "box", (fx, y0, z1 - t), (20.0, y1 - y0, t), "#6b7078",
               hw="sheet-steel lift guard 1.5 mm"))


def reject_hole():
    """(x0, y0, side) of the square hole in the deck under the reject funnel (the funnel's outlet)."""
    kx, yb, fw_, fd_ = L["KICK_X"], y_back(), *L["FUNNEL"]
    cx, cy = kx, yb - 32 - 6 - 1 - fd_ / 2
    o = L["FUNNEL_OUT"]
    return cx - o / 2, cy - o / 2, o


def reject_cap():
    x, y, w, d, h = L["REJECT_BIN"]
    return int(w * d * h * L["PACKING"] / cookie_vol())


def rate_flavour():
    return 1 / takt() * L["MIX"][0] / sum(L["MIX"])


# ------------------------------------------------------------ station timing
def oven_len():
    return L["V"] * L["BAKE_S"]


def cool_len():
    return L["V"] * L["COOL_S"]


def oven_x():
    x0 = L["OVEN_X0"]
    return x0, x0 + oven_len()


def cool_x():
    o1 = oven_x()[1] + L["TUN_GAP"]
    return o1, o1 + cool_len()


def z_esc():
    """Underside of the escapement blocks."""
    return z_cookie_top() + L["DROP_H"]


def drop_time():
    """Free fall of the cookie bottom from the gate top to the nest (from the
    geometry - v3 used DROP_H + H and forgot the gate thickness)."""
    h = z_esc() + L["GATE_Z"][1] - z_seat()
    return math.sqrt(2 * h / 1000.0 / G)


def stamp_cycle():
    t = L["STAMP_T"]
    track = t["sync"] + t["down"] + t["dwell"] + t["up"]
    dist = L["V"] * track
    ret = dist / (L["RETURN_V"] * L["V"]) + t["settle"]
    return track, dist, track + ret


def delta_window(xd):
    """Belt length under a delta's reach circle at pick height, and its time."""
    r = delta_reach_radius()
    dy = abs(L["DELTA_Y"] - y_back())
    if dy >= r:
        return 0.0, 0.0
    c = 2 * math.sqrt(r * r - dy * dy)
    return c, c / L["V"]


# ------------------------------------------------------------ delta kinematics
def arm_angles(xd):
    """The three arm plane angles of the delta at xd (rotated by DELTA_ROT so the
    wide gap between arms and motor bodies faces the neighbouring delta)."""
    rot = L["DELTA_ROT"][L["DELTA_X"].index(xd)] if xd in L["DELTA_X"] else 0.0
    return tuple(rot + k * 120.0 for k in range(3))


def delta_ik(x, y, z, xd):
    """Shoulder angles (deg, + = down) for effector centre (x,y,z) of delta
    whose base centre is (xd, DELTA_Y, DELTA_Z). None if unreachable/limited."""
    rb, re, l1, l2 = L["DELTA_RB"], L["DELTA_RE"], L["DELTA_L1"], L["DELTA_L2"]
    X, Y, Z = x - xd, y - L["DELTA_Y"], z - L["DELTA_Z"]
    out = []
    for phi in arm_angles(xd):
        c, s = math.cos(math.radians(phi)), math.sin(math.radians(phi))
        xp, yp = c * X + s * Y, -s * X + c * Y          # into the arm's plane
        a = xp + re - rb
        A_, B_ = -2 * a * l1, 2 * Z * l1
        K = l2 * l2 - a * a - yp * yp - Z * Z - l1 * l1
        m = math.hypot(A_, B_)
        if m < 1e-9 or abs(K) > m:
            return None
        base = math.atan2(B_, A_)
        d_ = math.acos(K / m)
        best = None
        for th in (base + d_, base - d_):
            ex = rb + l1 * math.cos(th)               # elbow radius: take the OUTER solution
            if best is None or ex > best[0]:
                best = (ex, th)
        deg = math.degrees(best[1])
        deg = (deg + 180) % 360 - 180
        if not (L["DELTA_LIM"][0] <= deg <= L["DELTA_LIM"][1]):
            return None
        out.append(deg)
    return out


def delta_points(x, y, z, xd):
    """Shoulder, elbow, wrist points of the three arms at an effector pose."""
    ang = delta_ik(x, y, z, xd)
    if ang is None:
        raise ValueError("unreachable")
    rb, re, l1 = L["DELTA_RB"], L["DELTA_RE"], L["DELTA_L1"]
    pts = []
    for phi, th in zip(arm_angles(xd), ang):
        c, s = math.cos(math.radians(phi)), math.sin(math.radians(phi))
        sh = (xd + rb * c, L["DELTA_Y"] + rb * s, L["DELTA_Z"])
        r_el = rb + l1 * math.cos(math.radians(th))
        el = (xd + r_el * c, L["DELTA_Y"] + r_el * s, L["DELTA_Z"] - l1 * math.sin(math.radians(th)))
        wr = (x + re * c, y + re * s, z)
        pts.append((phi, sh, el, wr))
    return pts


def delta_reach_radius():
    """Largest radius (from the delta axis) reachable in every direction at the
    pick height - found numerically from the IK, not assumed."""
    zp = pick_z()
    xd = L["DELTA_X"][0]
    lo, hi = 0.0, 400.0
    for _ in range(40):
        mid = (lo + hi) / 2
        ok = all(delta_ik(xd + mid * math.cos(math.radians(a)), L["DELTA_Y"] + mid * math.sin(math.radians(a)),
                          zp, xd) for a in range(0, 360, 5))
        lo, hi = (mid, hi) if ok else (lo, mid)
    return lo


def delta_jacobian(x, y, z, xd, h=0.01):
    """d(effector)/d(shoulder angles) in mm/rad (3x3, columns = arms), from the
    IK by central differences and a 3x3 inverse."""
    Jt = []
    for k in range(3):
        d = [0.0, 0.0, 0.0]
        d[k] = h
        a = delta_ik(x + d[0], y + d[1], z + d[2], xd)
        b = delta_ik(x - d[0], y - d[1], z - d[2], xd)
        if a is None or b is None:
            return None
        Jt.append([math.radians(a[i] - b[i]) / (2 * h) for i in range(3)])   # row k: dtheta/dp_k
    # Jt[k][i] = dtheta_i / dp_k  ->  M = dtheta/dp with M[i][k]
    M_ = [[Jt[k][i] for k in range(3)] for i in range(3)]
    a, b, c = M_[0]
    d, e, f = M_[1]
    g, hh, i = M_[2]
    det = a * (e * i - f * hh) - b * (d * i - f * g) + c * (d * hh - e * g)
    if abs(det) < 1e-12:
        return None
    inv = [[(e * i - f * hh) / det, (c * hh - b * i) / det, (b * f - c * e) / det],
           [(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det],
           [(d * hh - e * g) / det, (b * g - a * hh) / det, (a * e - b * d) / det]]
    return inv                                            # inv[k][i] = dp_k / dtheta_i


def pick_z():
    """Effector underside height when the cup tip touches a seated cookie."""
    return z_cookie_top() + L["CUP_L"]


def place_z():
    return L["LANE_Z"] + 3.0 + L["COOKIE"][1] + L["CUP_L"]


def delta_poses():
    """Every pose the pickers are commanded to: the pick window at pick and
    travel height, the three pockets of every lane at place and travel height."""
    out = []
    for i, xd in enumerate(L["DELTA_X"]):
        c, _ = delta_window(xd)
        for dx in [(-c / 2 + 2) + k * (c - 4) / 10 for k in range(11)]:
            for z in (pick_z(), L["TRAVEL_Z"]):
                out.append((i, xd, (xd + dx, y_back(), z), "pick"))
        for y in L["LANE_Y"]:
            for dx in (-L["POCKET_PITCH"], 0.0, L["POCKET_PITCH"]):
                for z in (place_z(), L["TRAVEL_Z"]):
                    out.append((i, xd, (xd + dx, y, z), "place"))
    return out


# --------------------------------------------------------------- geometry
def hollow(A, name, module, group, x0, y0, z0, w, d, h, t, colour, bottom=True, note="", joint="", hw=""):
    """An open-top box made of real walls (and a floor): something can go IN."""
    A(Part(f"{name}_wall_front", module, group, "box", (x0, y0, z0), (w, t, h), colour, joint=joint, note=note, hw=hw))
    A(Part(f"{name}_wall_back", module, group, "box", (x0, y0 + d - t, z0), (w, t, h), colour, joint=joint, hw=hw))
    A(Part(f"{name}_wall_left", module, group, "box", (x0, y0 + t, z0), (t, d - 2 * t, h), colour, joint=joint, hw=hw))
    A(Part(f"{name}_wall_right", module, group, "box", (x0 + w - t, y0 + t, z0), (t, d - 2 * t, h), colour,
           joint=joint, hw=hw))
    if bottom:
        A(Part(f"{name}_floor", module, group, "box", (x0 + t, y0 + t, z0), (w - 2 * t, d - 2 * t, t), colour,
               joint=joint, hw=hw))


def nema(A, name, module, group, axis, face, centre, gear, motor, tag="", note="", sign=1):
    """A NEMA 17 motor (+ gearbox) as ONE box envelope: `face` = coordinate of
    the gearbox (or motor) mounting face along `axis`, body extends in `sign`
    direction; centre = the shaft axis position in the other two coordinates."""
    ln = H.STEPPER[motor]["body"] + H.STEPPER[motor]["enc_len"] + (H.GEARBOX[gear]["length"] if gear else 0.0)
    f = H.NEMA17["flange"]
    i = "xyz".index(axis)
    lo = [0.0, 0.0, 0.0]
    sz = [0.0, 0.0, 0.0]
    lo[i] = face if sign > 0 else face - ln
    sz[i] = ln
    k = 0
    for j in range(3):
        if j != i:
            lo[j] = centre[k] - f / 2
            sz[j] = f
            k += 1
    A(Part(name, module, group, "box", tuple(lo), tuple(sz), "#e0492f", tag=tag,
           hw=f"{motor}" + (f"+{gear}" if gear else ""), mech=f"motor:{axis}{'+' if sign > 0 else '-'}", note=note))
    return ln


def cyl6432(A, name, module, group, bore, stroke, axis, face, centre, sign, tag="", joint="", note=""):
    """ISO 6432 cylinder as a box envelope (barrel OD + nose/eye -> square of
    OD + 3): nose face at `face`, body extends in `sign` direction."""
    ln = H.cyl_length(bore, stroke)
    w = H.CYL[bore]["od"] + 3.0
    i = "xyz".index(axis)
    lo, sz = [0.0] * 3, [0.0] * 3
    lo[i] = face if sign > 0 else face - ln
    sz[i] = ln
    k = 0
    for j in range(3):
        if j != i:
            lo[j] = centre[k] - w / 2
            sz[j] = w
            k += 1
    A(Part(name, module, group, "box", tuple(lo), tuple(sz), "#d9eef7", tag=tag, joint=joint,
           hw=f"ISO6432-{bore}x{stroke}", mech=f"cyl:{axis}{'+' if sign > 0 else '-'}", note=note))
    return ln


def _guide_bracket(A, name, axis, c, n, at, off=0.0):
    """Z-bracket (3 mm bent sheet) holding a puck guide 10 mm above the chain
    track: tab on the track's side face, floor under the chain, riser behind
    the guide. axis 'y' = straight along x (n = +-1 in y, at = x position);
    axis 'x' = bend apex (n = +-1 in x, at = y position). c = track centre line."""
    zf0, zf1 = z_frame()
    hw_ = H.SECTION[L["FRAME"]][2] / 2          # half width of the track
    g0 = L["BELT_W"] / 2                          # guide inner face
    g1_ = g0 + L["GUIDE_T"]
    boxes = (("tab", hw_, hw_ + 3, zf0, zf1 - 1),           # 19 mm: edge distance for the M5 at the slot
             ("floor", hw_ + 3, g1_ + 3, zf0, zf0 + 3),
             ("riser", g1_, g1_ + 3, zf0 + 3, L["BELT_Z"] + L["GUIDE_H"]))
    for k, (nm, r0, r1, z0, z1) in enumerate(boxes):
        a, b = (c + r0, c + r1) if n > 0 else (c - r1, c - r0)
        a, b = a + n * off, b + n * off
        if axis == "y":
            A(Part(f"{name}_{nm}", "loop", "guide_bracket", "box", (at - 10, a, z0), (20, b - a, z1 - z0), "#9aa3ab",
                   hw="guide bracket 3 mm S235, zinc", note="holds the puck guide over the chain"))
        else:
            A(Part(f"{name}_{nm}", "loop", "guide_bracket", "box", (a, at - 10, z0), (b - a, 20, z1 - z0), "#9aa3ab",
                   hw="guide bracket 3 mm S235, zinc", note="holds the puck guide over the chain"))


def _loop_parts(A):
    S, R = straight(), L["R"]
    (clx, cly), (crx, cry) = centres()
    bw, ct, bz = L["BELT_W"], L["CHAIN_T"], L["BELT_Z"]
    gt, gh = L["GUIDE_T"], L["GUIDE_H"]
    yf, yb = y_front(), y_back()
    zf0, zf1 = z_frame()
    fw = H.SECTION[L["FRAME"]][2]
    kx = L["KICK_X"]
    d0, d1 = L["DRIVE_X"]
    for nm, y in (("front", yf), ("back", yb)):
        A(Part(f"chain_{nm}", "loop", "chain", "box", (clx, y - bw / 2, bz - ct), (S, bw, ct), "#3b3e44",
               mech="belt:loop", hw="CHAIN", note="side-flexing flat-top chain, runs continuously"))
        spans = [(clx, crx)] if nm == "front" else [(clx, d0), (d1, crx)]
        for k, (a, b) in enumerate(spans):
            A(Part(f"frame_{nm}_{k}", "loop", "frame", "box", (a, y - fw / 2, zf0), (b - a, fw, zf1 - zf0), "#d6d9da",
                   mech=f"profile:{L['FRAME']}", hw=f"HFS5-{L['FRAME']}",
                   note="chain track: 2040 laid flat + UHMW-PE wear strips"))
        for side, off in (("in", -1), ("out", 1)):
            gy = y + off * (bw / 2 + gt / 2) - gt / 2
            segs = [(clx, crx)]
            if nm == "back":                                   # gap for the reject kicker
                g0, g1_ = kx - L["KICK_W"] / 2 - 10, kx + L["KICK_W"] / 2 + 10
                segs = [(clx, g0), (g1_, crx)]
            for k, (a, b) in enumerate(segs):
                A(Part(f"guide_{nm}_{side}_{k}", "loop", "guide", "box", (a, gy, bz), (b - a, gt, gh), "#b9bec4",
                       hw="GUIDE_BAR"))
        legs = L["LEGS_FRONT"] if nm == "front" else L["LEGS_BACK"]
        for i, lx in enumerate(legs):
            A(Part(f"leg_{nm}_{i}", "loop", "frame", "box", (lx - 10, y - 20, 0), (20.0, 40.0, zf0), "#d6d9da",
                   mech="profile:2040", hw="HFS5-2040"))
        # the end brackets sit fully on the straight: a flat bracket across the joint would cut
        # 0.3 mm into the curved bend (found by interference()); the arc guide butts onto the straight one
        gbs = (clx + 10,) + (L["GB_FRONT"] if nm == "front" else L["GB_BACK"]) + (crx - 10,)
        for i, gx in enumerate(gbs):
            for side in ("in", "out"):                         # 'in' = towards the loop centre
                _guide_bracket(A, f"gb_{nm}_{side}_{i}", "y", y, 1 if (nm == "front") == (side == "in") else -1, gx)
    for nm, (cx, cy), a0, a1, apex in (("right", (crx, cry), -90.0, 90.0, 0.0), ("left", (clx, cly), 90.0, 270.0, 180.0)):
        A(Part(f"chain_{nm}_curve", "loop", "chain", "arc", (cx, cy, bz - ct),
               (R - bw / 2, R + bw / 2, ct, a0, a1), "#3b3e44", mech="belt:loop", hw="CHAIN"))
        A(Part(f"frame_{nm}_curve", "loop", "frame", "arc", (cx, cy, zf0),
               (R - fw / 2, R + fw / 2, zf1 - zf0, a0, a1), "#d6d9da", hw="BEND",
               note="plain bend 180 deg (UHMW-PE track)"))
        A(Part(f"guide_{nm}_curve_in", "loop", "guide", "arc", (cx, cy, bz),
               (R - bw / 2 - gt, R - bw / 2, gh, a0, a1), "#b9bec4", hw="GUIDE_BAR"))
        A(Part(f"guide_{nm}_curve_out", "loop", "guide", "arc", (cx, cy, bz),
               (R + bw / 2, R + bw / 2 + gt, gh, a0, a1), "#b9bec4", hw="GUIDE_BAR"))
        for i, da in enumerate(L["CURVE_LEGS"]):
            th = math.radians(apex + da)
            lx, ly = g1(cx + R * math.cos(th)), g1(cy + R * math.sin(th))
            A(Part(f"leg_{nm}_curve_{i}", "loop", "frame", "box", (lx - 20, ly - 20, 0), (40.0, 40.0, zf0), "#d6d9da",
                   mech="profile:4040", hw="HFS8-4040"))
        s = 1 if apex == 0.0 else -1                      # apex direction in x
        for side, n in (("in", -s), ("out", s)):
            # on the CONCAVE (inner) side a flat 20 mm bracket would cut 0.28 mm into the bend and
            # 0.31 into the guide at its ends: set it 0.4 mm off the apex (the screw pulls it on)
            _guide_bracket(A, f"gb_{nm}_curve_{side}", "x", cx + s * R, n, cy, off=0.4 if side == "in" else 0.0)
    # intermediate (caterpillar) drive: replaces the back track between DRIVE_X
    A(Part("M1_drive_unit", "loop", "drive", "box", (d0, yb - fw / 2, 0), (d1 - d0, fw, zf1), "#5b6168",
           hw="DRIVE_UNIT", mech="drive:loop",
           note="intermediate drive: sprocket under the chain; carries the chain track over its length"))
    motor_face = yb - fw / 2
    nema(A, "M1_master_drive", "loop", "drive", "y", motor_face, ((d0 + d1) / 2, L["DRIVE_Z"]), "PG27",
         "17HS19-2004D-E1000", tag="Q1", sign=-1,
         note="chain drive (EL7047, closed loop); flange on the drive unit's inner face")
    A(Part("B1_master_encoder", "loop", "drive", "box", (1150.0, yb + fw / 2, 20.0), (40.0, 40.0, zf1 - 22.0),
           "#1b8f52", tag="B1", hw="encoder_wheel",
           note="measuring wheel on the chain underside: THE MASTER AXIS every station synchronises to "
                "(electronic line shaft); sprocket slip shows as drive-encoder vs B1 drift"))


def _pucks(A, t=0.0):
    """Carriers on the loop at time t with the nominal steady-state content."""
    Lp = loop_len()
    feed_s = s_front(L["MAG_X"][0])
    pick_s = s_back(L["DELTA_X"][1]) + 80
    oven_s1 = s_front(oven_x()[1])
    d, h = L["PUCK"]
    for k in range(L["N"]):
        s = (k * L["PITCH"] + L["V"] * t) % Lp
        (x, y), _ = pos(s)
        A(Part(f"puck_{k:02d}", "loop", "puck", "cyl", (x, y, L["BELT_Z"]), ("z", h, d), "#1f63c4",
               joint="loop", tag="NFC", note="carrier with NFC tag (recipe + state)"))
        loaded = (s > feed_s + 30) and (s < pick_s)
        if loaded:
            f = k % 3
            col = L["BAKED"][f] if s > oven_s1 else L["RAW"]
            A(Part(f"cookie_{k:02d}", "loop", "cookie", "cyl", (x, y, z_seat()),
                   ("z", L["COOKIE"][1], L["COOKIE"][0]), col, joint="loop", note=FLAV[f]))


def mag_top():
    return z_esc() + L["ESC_BLOCK"][2] + L["MAG_CAP"] * L["COOKIE"][1] + 20


def chute(i):
    """(start, end) of flavour i's chutes: disc outlet (between the back legs) ->
    30 mm above the tube tops (the chute end clears the tube; the cookie drops in). Returns [(p0, p1_A), (p0, p1_B)]."""
    hw, hd, hh = L["HOPPER"]
    hx, hy, hz = L["HOPPER_X"][i], L["HOPPER_Y"], L["HOPPER_Z"]
    p0 = (hx + hw / 2, hy + hd + 10, hz - 30)             # outlet stub 10 mm behind the hopper
    return [(p0, (L["MAG_X"][2 * i + k], y_front(), mag_top() + 30)) for k in (0, 1)]


def _feeder(A):
    yf = y_front()
    z0 = z_esc()
    bw_, bd_, bh_ = L["ESC_BLOCK"]
    top = mag_top()
    bore, stroke = L["ESC_CYL"]
    for i, mx in enumerate(L["MAG_X"]):
        f, ab = FLAV[i // 2], "AB"[i % 2]
        A(Part(f"esc_{f}_{ab}", "feeder", "escapement", "box", (mx - bw_ / 2, yf - bd_ / 2, z0), (bw_, bd_, bh_),
               "#e0492f", hw="escapement block POM", mech=f"gate:{L['GATE_Z'][0]}:{L['GATE_Z'][1]}",
               note="POM block: holds the tube, the slide gate runs in a slot (z GATE_Z), D47 drop hole; "
                    "released LEAD mm early - see check()"))
        cyl6432(A, f"esc_cyl_{f}_{ab}", "feeder", "escapement", bore, stroke, "y", yf + bd_ / 2,
                (mx, z0 + sum(L["GATE_Z"]) / 2), +1, tag=f"Q{2 + i}",
                note="gate cylinder, nose-mounted on the block's back face")
        A(Part(f"mag_{f}_{ab}", "feeder", "magazine", "cyl", (mx, yf, z0 + bh_), ("z", top - z0 - bh_, L["MAG_OD"]),
               "#d9eef7", mech=f"tube:{L['MAG_ID']}", hw="TUBE",
               note=f"clear TUBE (ID {L['MAG_ID']:g}): chute in at the top, gate out at the bottom; "
                    f"{L['MAG_CAP']} {f} cookies"))
        for c_ in range(6):
            A(Part(f"mag_{f}_{ab}_cookie_{c_}", "feeder", "stock", "cyl",
                   (mx, yf, z0 + bh_ + c_ * L["COOKIE"][1] + 0.5), ("z", L["COOKIE"][1] - 1, L["COOKIE"][0]), L["RAW"]))
        A(Part(f"mag_empty_{f}_{ab}", "feeder", "sensor", "box", (mx - 7.5, yf - L["MAG_OD"] / 2 - 7.5, z0 + bh_ + 5),
               (15.0, 7.5, 15.0), "#1b8f52", tag=f"I{2 + i}", hw="diffuse_M12",
               note="tube-low sensor, clipped to the tube -> AMR refill request"))
    x0, x1 = L["MAG_X"][0] - 45, L["MAG_X"][-1] + bw_ / 2 + 1       # 1 mm clear of the oven wall
    for nm, y in (("front", yf - 90), ("back", yf + 60)):
        A(Part(f"feeder_beam_{nm}", "feeder", "frame", "box", (x0, y, z0 - 30), (x1 - x0, 30.0, 30.0), "#d6d9da",
               mech="profile:3030", hw="HFS8-3030"))
        for px in (x0, x1 - 30):
            A(Part(f"feeder_post_{nm}_{int(px)}", "feeder", "frame", "box", (px, y, 0), (30.0, 30.0, z0 - 30),
                   "#d6d9da", mech="profile:3030", hw="HFS8-3030"))
    hw, hd, hh = L["HOPPER"]
    for i, (f, hx) in enumerate(zip(FLAV, L["HOPPER_X"])):
        hy, hz = L["HOPPER_Y"], L["HOPPER_Z"]
        hollow(A, f"hopper_{f}", "feeder", "hopper", hx, hy, hz, hw, hd, hh, 3.0, "#d9eef7", hw="PC sheet 3 mm",
               note=f"bulk raw {f} cookies, ~{hopper_cap()} at {L['PACKING']:g} packing; OPEN TOP (hinged lid) "
                    f"for the AMR tote; floor has the outlet onto the singulator disc")
        A(Part(f"hopper_{f}_level", "feeder", "sensor", "box", (hx + hw / 2 - 20, hy + hd, hz + hh - 24),
               (40.0, 20.0, 24.0), "#1b8f52", tag=f"IOL{1 + i}", hw="tof_level",
               note=f"ToF level sensor on an angle bracket outside the back wall, looking over the rim "
                    f"-> AMR refill request at {L['REQ_HOPPER']:.0%}"))
        cx, cy = hx + hw / 2, hy + hd / 2
        A(Part(f"singulator_{f}", "feeder", "hopper", "cyl", (cx, cy, hz - 20), ("z", 20.0, 180.0),
               "#e0492f", mech="spin:singulator", hw="POM disc 180 x 20, 6 pockets",
               note="rotary singulating disc: one cookie per pocket into the chute; camera jam check"))
        A(Part(f"singulator_shaft_{f}", "feeder", "hopper", "cyl", (cx, cy, hz - 36), ("z", 16.0, 8.0), "#9aa3ab",
               hw="PG14 output shaft D8", note="through the plate into the disc hub"))
        A(Part(f"singulator_plate_{f}", "feeder", "hopper", "box", (hx + 30, hy, hz - 36), (hw - 60, 150.0, 15.0),
               "#b9bec4", hw="Al plate 15 mm", note="motor plate between the front legs; disc runs 1 mm above it"))
        nema(A, f"M_singulator_{f}", "feeder", "hopper", "z", hz - 36, (cx, cy), "PG14", L["SING_MOTOR"],
             tag=f"Q{30 + i}", sign=-1, note="singulator drive (EL7047)")
        for leg in ((hx, hy), (hx + hw - 30, hy), (hx, hy + hd - 30), (hx + hw - 30, hy + hd - 30)):
            A(Part(f"hopper_leg_{f}_{int(leg[0])}_{int(leg[1])}", "feeder", "frame", "box", (*leg, 0),
                   (30.0, 30.0, hz), "#d6d9da", mech="profile:3030", hw="HFS8-3030"))
        for k, (p0, p1) in enumerate(chute(i)):
            A(Part(f"chute_{f}_{'AB'[k]}", "feeder", "hopper", "rod", p0, (*p1, 50.0), "#d9eef7", hw="PC chute D50",
                   note="clear chute, disc outlet -> tube top (Y diverter A/B)"))
            A(Part(f"collar_{f}_{'AB'[k]}", "feeder", "hopper", "cyl", (p1[0], p1[1], mag_top()), ("z", 15.0, 60.0),
                   "#d9eef7", hw="PC funnel collar on the tube top", note="the chute end sits in it"))
        p0 = chute(i)[0][0]
        A(Part(f"chute_stub_{f}", "feeder", "hopper", "box", (p0[0] - 30, hy + hd - 20, p0[2]), (60.0, 30.0, hz - p0[2]),
               "#d9eef7", hw="PC outlet stub", note="disc outlet under the hopper floor; the Y chute hangs in it"))
    # upstream of the first tube, where a 2020 stand clears the feeder post's deck bracket and the guide
    A(Part("feeder_empty_check", "feeder", "sensor", "box", (236.0, yf - 58, L["BELT_Z"] + 5),
           (15.0, 7.5, 15.0), "#1b8f52", tag="I1", hw="diffuse_M12",
           note="light barrier: puck already full (recirculating) -> do NOT load it"))
    A(Part("nfc_writer", "feeder", "sensor", "box", (L["NFC_WRITE_X"] - 20, yf - 32 - 6 - 40, L["BELT_Z"] - 30),
           (40.0, 34.0, 25.0), "#2f6fd0", tag="NFC-W", hw="nfc_head",
           note="writes the flavour the sequence assigned + batch into the puck tag (I1 confirms the load)"))


def _pa1(A):
    """Upgrade PA-1 sensors that need a place in the machine (the rest - reeds on every cylinder,
    analogue vacuum, stamp pressure - live inside an existing part's envelope; see plc_io)."""
    if not L["PA1"]:
        return
    yf = y_front()
    A(Part("I9_drop_check", "feeder", "sensor", "box", (L["DROP_CHECK_X"], yf - 58, L["BELT_Z"]),
           (15.0, 7.5, 15.0), "#1b8f52", tag="I9", hw="diffuse_M12",
           note="landing check after the last tube: did the cookie land in the nest? (timestamped, EL1252) - "
                "the label that lets the drop lead be learned"))
    zr = z_cookie_top() + L["TUN_CLEAR"]
    A(Part("IR1_pyrometer", "tunnel", "sensor", "box", (L["PYRO_X"], yf - 15, zr), (15.0, 30.0, 15.0), "#1b8f52",
           tag="IR1", hw="ir_pyrometer",
           note="product surface temperature leaving the oven: closes the bake loop on the cookie, not the air"))
    x, y, z = L["PACK_CAM"]
    A(Part("CAM4_pack", "pick", "vision", "cyl", (x, y, z), ("z", 40.0, 30.0), "#2b2b2f", tag="CAM4",
           hw="GigE global-shutter camera",
           note="pack camera over the three lanes before the sealer: cookie seated in its pocket, flavour, damage"))


def guard():
    """Post bands of the perimeter guard (min corners of the 2020 lines, mm)."""
    W, D, _ = L["TABLE"]
    t, w, gi = L["GUARD_PC"], 20.0, L["GUARD_IN"]
    return dict(t=t, w=w, yF1=gi["F1"] + t, yF2=gi["F2"] + t, yB=D - gi["back"] - t - w, xL=gi["left"] + t,
                xR=W - gi["right"] - t - w, xS=L["GUARD_STEP_X"], zt=L["GUARD_TOP"] - w,
                yF1o=gi["F1"], yF2o=gi["F2"], yBo=D - gi["back"], xLo=gi["left"], xRo=W - gi["right"])


def _guard(A):
    """Upgrade S-1 perimeter guard: posts, top rails, roof rails, PC panels, doors with guard locking,
    light curtains at the AMR ports, E-stops, reset; fixed hopper lids behind the raw pour strip."""
    if not L["SAFE1"]:
        return
    g = guard()
    t, w, zt = g["t"], g["w"], g["zt"]
    yF1, yF2, yB, xL, xR, xS = g["yF1"], g["yF2"], g["yB"], g["xL"], g["xR"], g["xS"]
    PC, AL, SAFE_C = "#cfe6f2", "#d6d9da", "#f2c200"

    def post(x, y):
        A(Part(f"guard_post_{int(x)}_{int(y)}", "safety", "guard", "box", (x, y, 0.0), (w, w, zt), AL,
               mech="profile:2020", hw="HFS5-2020"))

    def rail(name, x0, y0, sx, sy, sec="2020"):
        A(Part(f"guard_rail_{name}", "safety", "guard", "box", (x0, y0, zt), (sx, sy, 20.0), AL,
               mech=f"profile:{sec}", hw="HFS5-2020" if sec == "2020" else "HFS5-2040"))

    def panel(name, p, s, note=""):
        A(Part(f"guard_panel_{name}", "safety", "guard", "box", p, s, PC, hw="PC guard panel 4 mm", note=note))

    # ---- posts
    doors = {d[0]: d for d in L["DOORS"]}
    pts = [(xL, yF1), (xS, yF1), (xS, yF2), (xR, yF2), (xL, yB), (xR, yB)]
    pts += [(x, yF1) for x in L["GUARD_POSTS"]["F1"]] + [(xL, y) for y in L["GUARD_POSTS"]["left"]] + \
        [(xR, y) for y in L["GUARD_POSTS"]["right"]]
    for tag, wall, x0, x1 in L["DOORS"]:
        yy = yF2 if wall == "F2" else yB
        pts += [(x0, yy), (x1 - w, yy)]
    for side, y0, y1, z0_, z1_, tag in L["PORT_OPEN"].values():
        xx = xL if side == "left" else xR
        pts += [(xx, y0), (xx, y1 - w)]
    for x, y in sorted(set(pts)):
        post(x, y)
    # ---- top rails (on the posts) + internal roof rails
    rx0, rx1, ry = L["HOPPER_X"][0], L["HOPPER_X"][-1] + L["HOPPER"][0], L["RAW_Y"]
    X1, X2 = L["ROOF_X"]
    rail("F1a", xL, yF1, rx0 - xL, w)
    rail("F1b", rx1, yF1, xS + w - rx1, w)
    rail("step", xS, yF1 + w, w, yF2 - yF1 - w)
    rail("raw_l", rx0 - w, yF1 + w, w, ry + 20 - yF1 - w)
    rail("raw_r", rx1, yF1 + w, w, ry + 20 - yF1 - w)
    rail("raw", rx0, ry - 20, rx1 - rx0, 40.0, "2040")
    rail("roofX1", X1 - 20, yF2, 40.0, yB - yF2, "2040")
    rail("F2", X1 + 20, yF2, xR + w - X1 - 20, w)
    rail("roofX2", X2 - 20, yF2 + w, 40.0, yB - yF2 - w, "2040")
    rail("left", xL, yF1 + w, w, yB - yF1 - w)
    rail("right", xR, yF2 + w, w, yB - yF2 - w)
    rail("back", xL, yB, xR + w - xL, w)
    for k, yc in enumerate(L["ROOF_Y"]):
        segs = [(xL + w, X1 - 20), (X1 + 20, X2 - 20), (X2 + 20, xR)]
        o_ = L["OUT_LOCK"]
        if L.get("AIRLOCK") and o_["y0"] < yc < o_["y1"]:       # ends on the out-airlock header cap
            segs = segs[:2] + [(X2 + 20, o_["hx"]), (o_["hx"] + 20, xR)]
        for j, (a, b) in enumerate(segs):
            rail(f"roofY{k + 1}_{j}", a, yc - 20, b - a, 40.0, "2040")
    # ---- wall panels (outside the frame, 2 mm above the deck, up to the rail tops)
    zp, hp = 2.0, L["GUARD_TOP"] - 2.0
    yo1, yo2, ybo, xlo, xro = g["yF1o"], g["yF2o"], g["yBo"], g["xLo"], g["xRo"]
    hz_top = L["HOPPER_Z"] + L["HOPPER"][2]
    panel("F1a", (xlo, yo1, zp), (rx0 - xlo, t, hp))
    panel("F1b", (rx0, yo1, zp), (rx1 - rx0, t, hz_top - zp),
          note="in front of the hoppers, up to their rim: above it the raw pour strip is open")
    panel("F1c", (rx1, yo1, zp), (xS + w - rx1, t, hp))
    panel("step", (xS + w, yo1, zp), (t, yo2 + t - yo1, hp))
    edges = [xS + w + t]
    for tag, wall, x0, x1 in L["DOORS"]:
        if wall == "F2":
            edges += [x0 + w / 2, x1 - w / 2]
    edges.append(xro)
    for k in range(0, len(edges), 2):
        panel(f"F2_{k // 2}", (edges[k], yo2, zp), (edges[k + 1] - edges[k], t, hp))
    edges = [xlo]
    for tag, wall, x0, x1 in L["DOORS"]:
        if wall == "back":
            edges += [x0 + w / 2, x1 - w / 2]
    edges.append(xro)
    for k in range(0, len(edges), 2):
        panel(f"B_{k // 2}", (edges[k], ybo - t, zp), (edges[k + 1] - edges[k], t, hp))
    for side, (x_, y_a) in (("left", (xlo, yF1)), ("right", (xro - t, yF2))):
        op = next(v for v in L["PORT_OPEN"].values() if v[0] == side)
        _, y0, y1, zo0, zo, tag = op
        panel(f"{side}_0", (x_, y_a, zp), (t, y0 + w / 2 - y_a, hp))
        panel(f"{side}_1", (x_, y1 - w / 2, zp), (t, yB + w - (y1 - w / 2), hp))
        if zo < zt - 1e-6:
            panel(f"{side}_port_top", (x_, y0 + w / 2, zo), (t, y1 - y0 - w, L["GUARD_TOP"] - zo),
                  note="above the AMR port opening")
        if zo0 > zp + 1e-6:
            panel(f"{side}_port_bot", (x_, y0 + w / 2, zp), (t, y1 - y0 - w, zo0 - zp),
                  note="below the AMR port opening")
    # ---- roof (4 mm PC on the rails)
    zr = L["GUARD_TOP"]
    ys = [None, L["ROOF_Y"][0], L["ROOF_Y"][1], ybo]
    cols = ((xlo, X1), (X1, X2), (X2, xro))
    for r in range(3):
        for c, (a, b) in enumerate(cols):
            y0 = ys[r] if r else (yo1 if c == 0 else yo2)
            if r == 0 and c == 0:
                panel("roof_0_0a", (a, y0, zr), (rx0 - a, ys[1] - y0, t))
                panel("roof_0_0b", (rx0, ry, zr), (rx1 - rx0, ys[1] - ry, t),
                      note="behind the raw pour strip")
                panel("roof_0_0c", (rx1, y0, zr), (b - rx1, ys[1] - y0, t))
            else:
                panel(f"roof_{r}_{c}", (a, y0, zr), (b - a, ys[r + 1] - y0, t))
    # ---- hopper lids: the pour strip in front of the raw rail is the only way into a hopper
    hw_, hd_, hh_ = L["HOPPER"]
    for f, hx in zip(FLAV, L["HOPPER_X"]):
        hy = L["HOPPER_Y"]
        A(Part(f"hopper_{f}_wall_top", "feeder", "hopper", "box", (hx, ry, L["HOPPER_Z"] + hh_),
               (hw_, hy + hd_ - ry, 3.0), "#d9eef7", hw="PC sheet 3 mm",
               note="fixed lid (bonded): the AMR pours through the strip in front of the raw rail; the ToF "
                    "level sensor looks through a window in it"))
    # ---- doors: bought leaf on 2 hinges at the hinge post, guard-locking switch on the lock post
    gs = H.SAFE["guard_lock"]["size"]
    for tag, wall, x0, x1 in L["DOORS"]:
        if wall == "F2":
            yl, ysw = yo2, yF2 + w
        else:
            yl, ysw = yB, yB - gs[1]
        A(Part(f"door_{tag}", "safety", "door", "box", (x0 + w, yl, 2.0), (x1 - w - 2.0 - (x0 + w), H.SAFE["door"]["depth"],
                                                                         zt - 2.0 - 2.0), "#b7d3e6",
               hw="guard door kit", note="hinged at the hinge post, locked by the switch at the lock post"))
        A(Part(f"lock_{tag}", "safety", "sensor", "box", (x1 - w, ysw, L["LOCK_Z"]), gs, SAFE_C, tag=tag,
               hw="guard_lock", note="guard locking: opens only after TwinSAFE standstill (SF2)"))
    # ---- AMR ports: airlocks (S-1b) - or, without them, type 4 light curtains in the post line
    if L.get("AIRLOCK"):
        _airlocks(A)
    else:
        sec = H.SAFE["light_curtain"]["section"]
        for name, (side, y0, y1, zo0, zo, tag) in L["PORT_OPEN"].items():
            xx = xL if side == "left" else xR
            z1 = zo if zo < zt - 1e-6 else zt - 6.0
            for k, yy in enumerate((y0 + w, y1 - w - sec[1])):
                A(Part(f"lc_{name}_{'tr'[k]}", "safety", "sensor", "box", (xx, yy, 0.0), (sec[0], sec[1], z1),
                       SAFE_C, tag=tag if k == 0 else "", hw="light_curtain",
                       note=f"type 4 light curtain across the {name} port; muted only while the AMR is docked "
                            f"and the port zone is at safe standstill (SF6)"))
    # ---- E-stops + reset (head outside the panel, contact block inside)
    es, rs = H.SAFE["estop"], H.SAFE["reset"]
    for tag, wall, x, z in list(L["ESTOPS"]) + [L["RESET"]]:
        d = es if tag != L["RESET"][0] else rs
        hd, hl = d["head"]
        bw, bd, bh = d["block"]
        if wall == "F2":
            y_out, y_in, sgn = yo2, yo2 + t, -1
        else:
            y_out, y_in, sgn = ybo, ybo - t, 1
        A(Part(f"{'estop' if d is es else 'reset'}_{tag}_head", "safety", "operator", "cyl",
               (x, y_out if sgn > 0 else y_out - hl, z), ("y", hl, hd), "#d8262c" if d is es else "#2f6fd0",
               tag=tag, hw="estop" if d is es else "reset",
               note="E-stop (SF1): 2 NC to the TwinSAFE inputs" if d is es else "reset after a safety stop"))
        A(Part(f"{'estop' if d is es else 'reset'}_{tag}_block", "safety", "operator", "box",
               (x - bw / 2, y_in if sgn < 0 else y_in - bd, z - bh / 2), (bw, bd, bh), "#3a3f44",
               hw="contact element (bought with the head)", note="contact block on the operator head, behind the panel"))


def _airlocks(A):
    """S-1b: each side AMR port opens only into a closed chamber.
    boxes: a chamber OVER the three tray magazines (floor with a trapdoor unit per lane). The outer door
           opens only with every trapdoor closed; the trapdoors drop a stack only with the outer door locked.
    out:   the cassette standby bay IS the chamber: an inner sliding door + a fixed header (the lane beams
           end on it, the rails pass under it) separate it from the stackers. The carrier moves the full
           cassette into the chamber, the inner door closes, the outer opens for the AMR swap, and back."""
    g = guard()
    t, w, zt = g["t"], g["w"], g["zt"]
    PC, AL, SAFE_C = "#cfe6f2", "#d6d9da", "#f2c200"
    gt = L["GUARD_TOP"]

    def prof(name, p, s_, sec="2020", group="airlock"):
        hw = {"2020": "HFS5-2020", "2040": "HFS5-2040", "3030": "HFS8-3030"}[sec]
        A(Part(name, "safety", group, "box", p, s_, AL, mech=f"profile:{sec}", hw=hw))

    def pc(name, p, s_, note=""):
        A(Part(name, "safety", "airlock", "box", p, s_, PC, hw="PC guard panel 4 mm", note=note))

    def split_roof(y0, y1):
        """y intervals of [y0, y1] not under an internal roof rail (a wall must stop below it)."""
        cuts = sorted((yc - 20, yc + 20) for yc in L["ROOF_Y"])
        out, a = [], y0
        for c0, c1 in cuts:
            if c1 <= a or c0 >= y1:
                continue
            if c0 > a:
                out.append((a, c0, gt))
            out.append((max(a, c0), min(c1, y1), zt))
            a = min(c1, y1)
        if a < y1:
            out.append((a, y1, gt))
        return out

    # ---------------------------------------------------------------- boxes airlock (left)
    b = L["BOX_LOCK"]
    x0, x1, y0, y1, zf = g["xL"] + w, b["x1"], b["y0"], b["y1"], b["zf"]
    corners = [(x0, y0), (x1 - w, y0), (x0, y1 - w), (x1 - w, y1 - w)]
    for k, (px, py) in enumerate(corners):
        prof(f"abox_post_{k}", (px, py, 0.0), (w, w, zt))
    for k, px in enumerate((x0, x1 - w)):          # floor beams between the posts
        prof(f"abox_beam_{k}", (px, y0 + w, zf - 20.0), (w, y1 - y0 - 2 * w, 20.0))
    # floor: one machined plate with a cutout over each magazine (modelled as its strips = one body)
    bl, bw, _ = L["BOX"]
    mxc = sum(L["BOXMAG_X"]) / 2
    ox0, ox1 = mxc - bl / 2 + 4, mxc + bl / 2 - 4                   # inside the magazine's end guides
    oys = [(y - bw / 2 - 2.5, y + bw / 2 + 2.5) for y in L["LANE_Y"]]
    fl = dict(hw="Al plate 6 mm (chamber floor, 3 cutouts)", note="chamber floor over the tray magazines")
    ya, yb = y0 + w, y1 - w
    strips = [("l", (x0, ya), (ox0, yb)), ("r", (ox1, ya), (x1, yb)), ("f", (x0 + w, y0), (x1 - w, ya)),
              ("b", (x0 + w, yb), (x1 - w, y1)), ("f2", (ox0, ya), (ox1, oys[0][0])),
              ("b2", (ox0, oys[-1][1]), (ox1, yb)), ("m1", (ox0, oys[0][1]), (ox1, oys[1][0])),
              ("m2", (ox0, oys[1][1]), (ox1, oys[2][0]))]
    for suf, (a0, b0), (a1, b1) in strips:
        A(Part(f"abox_floor_{suf}", "safety", "airlock", "box", (g1(a0), g1(b0), zf), (g1(a1 - a0), g1(b1 - b0), 6.0),
               "#b9bec4", **fl))
    td = H.SAFE["trapdoor"]
    for i, (f, y) in enumerate(zip(FLAV, L["LANE_Y"])):
        A(Part(f"trapdoor_{f}", "safety", "trapdoor", "box", (ox0 - 14, y - 34, zf - 10), (ox1 - ox0 + 28, 68.0, 10.0),
               "#e0492f", tag=f"Q{42 + i}", hw="trapdoor unit",
               note="bi-parting drop flaps under the floor cutout: open only with the outer door locked"))
    for wall, p_, s_ in (("front", (x0, y0 - t, zf + 6), (x1 - x0, t, gt - zf - 6)),
                         ("back", (x0, y1, zf + 6), (x1 - x0, t, gt - zf - 6))):
        pc(f"abox_wall_{wall}", p_, s_)
    for k, (a_, b_, ztop) in enumerate(split_roof(y0 - t, y1 + t)):
        pc(f"abox_wall_right_{k}", (x1, a_, zf + 6), (t, b_ - a_, ztop - zf - 6))
        if ztop < gt:                                  # under an internal roof rail: a post on the floor holds it
            prof(f"abox_post_mid_{k}", (x1 - w, (a_ + b_) / 2 - w / 2, zf + 6), (w, w, zt - zf - 6))
    side, py0, py1, oz0, oz1, tag = L["PORT_OPEN"]["boxes"]
    A(Part("aldoor_boxes", "safety", "airlock_door", "box", (g["xLo"] - 10, py0 + 12, oz0 - 10),
           (10.0, 580.0, gt - oz0 + 10), "#b7d3e6", tag=tag, hw="airlock_door",
           note="outer airlock door (kit, drawn closed; parks towards the back): opens only with every trapdoor "
                "closed and exhausted"))
    # ---------------------------------------------------------------- out airlock (right)
    o = L["OUT_LOCK"]
    hx, ox, oy0, oy1, zd = o["hx"], o["x"], o["y0"], o["y1"], o["zdoor"]
    sz = shuttle_z()
    for k, py in enumerate((oy0, oy1 - 30)):
        prof(f"aout_post_{k}", (hx, py, 0.0), (30.0, 30.0, sz["beam"]), "3030")
    prof("aout_header", (hx, oy0, sz["beam"]), (30.0, oy1 - oy0, 30.0), "3030")
    # header cap up to the roof: the internal roof rail ends on its sides (guard roof, split there)
    prof("aout_header_top", (hx, oy0, sz["beam_top"]), (20.0, oy1 - oy0, 20.0))
    A(Part("aldoor_inner", "safety", "airlock_door", "box", (ox, oy0 - t, 0.0), (hx - ox, o["park"] - oy0 + t, zd),
           "#b7d3e6", tag="S32", hw="airlock_door",
           note="inner airlock door (kit, drawn closed): slides behind the lanes to open; closes the standby bay "
                "off from the stackers. Its top stays under the MGN rails; the header closes the rest"))
    xr = g["xR"]
    pc("aout_wall_front", (hx, oy0 - t, 2.0), (xr - hx, t, gt - 2.0))
    pc("aout_wall_back", (hx, oy1, 2.0), (xr - hx, t, gt - 2.0))
    side, py0, py1, oz0, oz1, tag = L["PORT_OPEN"]["out"]
    A(Part("aldoor_out", "safety", "airlock_door", "box", (g["xRo"], py0 + 12, oz0 + 2), (10.0, 590.0, gt - oz0 - 2),
           "#b7d3e6", tag=tag, hw="airlock_door",
           note="outer airlock door (kit, drawn closed; parks towards the back): opens only with the inner door "
                "locked and the shuttles at safe standstill"))


def airlock_chambers():
    """Closed chamber volumes (x0, y0, z0, x1, y1, z1) of the airlocks - the only space an open outer door
    exposes."""
    g = guard()
    b, o = L["BOX_LOCK"], L["OUT_LOCK"]
    return dict(boxes=(g["xL"] + g["w"], b["y0"], b["zf"] + 6, b["x1"], b["y1"], L["GUARD_TOP"]),
                out=(o["hx"], o["y0"], 0.0, g["xR"], o["y1"], L["GUARD_TOP"]))


def cass_swap_t():
    """Lane blocked per cassette exchange through the airlock: carrier out, inner door shut, outer door
    open, AMR swap, outer door shut, inner door open, carrier back (the AMR waits at the port)."""
    move = (L["CASS_X"][1] - L["CASS_X"][0]) / L["SHUTTLE_V"]
    return 2 * move + 4 * L["DOOR_T"] + L["AMR_EXCH"] if L.get("AIRLOCK") else L["SWAP_T"]


def transfer_buffer():
    """Sealed packs that can wait at the lane end while no cassette is over the stacker: the transfer
    belt from the lane end to the far end of the stacker platform holds this many whole packs."""
    belt = L["CASS_X"][0] + L["CASS"][0] + 5 - L["LANE_X"][1]
    return int(belt // L["BOX"][0])


def _tunnel(A, name, x0, x1, n_zone, zone_kind):
    yf = y_front()
    h2, wt, rt = L["TUN_HALF"], L["TUN_WALL"], L["TUN_ROOF"]
    zr = z_cookie_top() + L["TUN_CLEAR"]
    for side, y0 in (("in", yf - h2), ("out", yf + h2 - wt)):
        A(Part(f"{name}_wall_{side}", "tunnel", name, "box", (x0, y0, 0), (x1 - x0, wt, zr), "#cf3a2f",
               hw="insulated panel 12 mm (threaded inserts)", note="insulated wall"))
    A(Part(f"{name}_roof", "tunnel", name, "box", (x0, yf - h2, zr), (x1 - x0, 2 * h2, rt), "#2b2b2f",
           hw="insulated panel 15 mm (threaded inserts)"))
    for end, xe in (("in", x0), ("out", x1 - 3)):
        hem = z_cookie_top() + L["CURTAIN_GAP"]
        A(Part(f"{name}_curtain_{end}", "tunnel", name, "box", (xe, yf - h2 + wt, hem), (3.0, 2 * h2 - 2 * wt, zr - hem),
               "#6b6f76", hw="silicone-glass curtain", note="fabric curtain; hem CURTAIN_GAP above the cookie"))
    for k in range(n_zone):
        xz = x0 + (k + 0.5) * (x1 - x0) / n_zone
        if zone_kind == "heater":
            A(Part(f"{name}_heater_{k}", "tunnel", name, "cyl", (xz, yf - h2 + wt, zr - 12), ("y", 2 * h2 - 2 * wt, 8.0),
                   "#ffd27a", tag=f"Q{8 + k}", hw="heater_bar",
                   note="heater zone (IR bar via SSR), closed-loop with its thermocouple"))
            A(Part(f"{name}_tc_{k}", "tunnel", name, "cyl", (xz + 30, yf + 40, zr - 20), ("z", 20.0, 4.0), "#b9bec4",
                   tag=f"TC{1 + k}", hw="tc_K", note="thermocouple (zone temperature -> PID / learned bake model)"))
        else:
            A(Part(f"{name}_fan_{k}", "tunnel", name, "cyl", (xz, yf, zr + rt), ("z", 25.0, 80.0), "#474b52",
                   tag=f"Q{11 + k}", mech="spin:fan", hw="fan_80", note="cooling fan"))


def stamp_frame():
    """z levels of the flying stamp, bottom up, all derived from the catalogue."""
    bore, stroke = L["STAMP_CYL"]
    zs = z_cookie_top() + L["STAMP_CLEAR"]            # die underside, retracted
    z_rod = zs + 10
    z_cyl = z_rod + L["ROD_OUT"]
    z_car = z_cyl + H.cyl_length(bore, stroke)
    rail = H.MGN[L["STAMP_RAIL"]]
    z_blk = z_car + 10
    z_plate = z_blk + rail["H"]                        # rail mounting face = cross plate underside
    return dict(zs=zs, rod=z_rod, cyl=z_cyl, car=z_car, blk=z_blk, plate=z_plate)


def _stamp(A):
    yf = y_front()
    x0 = L["STAMP_X0"]
    z = stamp_frame()
    rail = H.MGN[L["STAMP_RAIL"]]
    xa, xb = x0 - 20, x0 + L["STAMP_STROKE"] + L["CARR_L"] + 45
    zp = z["plate"]
    for px in (xa - 30, xb):
        for py in (yf - 90, yf + 60):
            A(Part(f"stamp_post_{int(px)}_{int(py)}", "stamp", "frame", "box", (px, py, 0), (30.0, 30.0, zp - 30),
                   "#d6d9da", mech="profile:3030", hw="HFS8-3030"))
    for py in (yf - 90, yf + 60):
        A(Part(f"stamp_beam_{int(py)}", "stamp", "frame", "box", (xa - 30, py, zp - 30), (xb - xa + 60, 30.0, 30.0),
               "#d6d9da", mech="profile:3030", hw="HFS8-3030"))
    A(Part("stamp_plate", "stamp", "axis", "box", (xa - 30, yf - 90, zp), (xb - xa + 60, 180.0, 8.0),
           "#b9bec4", hw="Al plate 8 mm", note="cross plate: the rail hangs under it"))
    yr = yf + L["STAMP_RAIL_DY"]                            # rail line: its block screws clear the cylinder
    A(Part("stamp_rail", "stamp", "axis", "box", (xa, yr - rail["rail"][0] / 2, zp - rail["rail"][1]),
           (xb - 40 - xa, rail["rail"][0], rail["rail"][1]), "#9aa3ab", hw=L["STAMP_RAIL"] + " rail",
           note="miniature guideway, mounted upside down under the plate"))
    A(Part("stamp_block", "stamp", "carriage", "box", (x0 + L["CARR_L"] / 2 - rail["L"] / 2, yr - rail["W"] / 2, z["blk"]),
           (rail["L"], rail["W"], rail["H"] - 3.0), "#3b3e44", joint="stamp_x", hw=L["STAMP_RAIL"] + " block"))
    ys = yf + 30                                           # spindle line beside the rail
    zsp = z["car"] - 8
    for k, bx in enumerate((xa, xb - 40)):
        A(Part(f"stamp_bearing_{k}", "stamp", "axis", "box", (bx, ys - 12, zsp - 12), (15.0, 24.0, zp - zsp + 12),
               "#8b9196", hw="608-2RS in pillow block" if k else "2x 608-2RS fixed block",
               note="spindle support hung from the plate (fixed at the motor end, supported at the other)"))
    A(Part("stamp_spindle", "stamp", "axis", "cyl", (xa, ys, zsp), ("x", xb - 25 - xa, H.LEADSCREW["Tr8x4"]["d"]),
           "#cf3a2f", mech="thread:stamp_x", hw=L["STAMP_SCREW"], note="Tr8x4 lead screw"))
    A(Part("stamp_coupling", "stamp", "axis", "cyl", (xb - 25, ys, zsp), ("x", 25.0, 20.0), "#9aa3ab",
           hw="flexible coupling 5/8 D20"))
    A(Part("stamp_motor_bracket", "stamp", "axis", "box", (xb, ys - 25, zsp - 24), (5.0, 50.0, zp - 5 - zsp + 24),
           "#9aa3ab", hw="NEMA17 L bracket 5 mm"))
    A(Part("stamp_motor_bracket_flange", "stamp", "axis", "box", (xb, ys - 25, zp - 5), (40.0, 50.0, 5.0),
           "#9aa3ab", hw="NEMA17 L bracket 5 mm", note="flange of the L bracket, screwed to the plate"))
    nema(A, "M_stamp_axis", "stamp", "axis", "x", xb + 5, (ys, zsp), None, L["STAMP_MOTOR"], tag="Q14", sign=1,
         note="carriage slaved to the master axis while stamping (EL7047, closed loop)")
    A(Part("stamp_carriage", "stamp", "carriage", "box", (x0, yf - 45, z["car"]), (L["CARR_L"], 95.0, 10.0),
           "#2b2b2f", joint="stamp_x", hw="Al plate 10 mm"))
    nut = H.LEADSCREW["Tr8x4"]["nut"]
    A(Part("stamp_nut", "stamp", "carriage", "box", (x0 + 15, ys - 16, zsp - 12), (30.0, 32.0, z["car"] - zsp + 12),
           "#e0a02a", joint="stamp_x", hw="Tr8x4 brass flange nut in a block",
           note=f"flange D{nut['flange_d']:g} on the carriage underside"))
    bore, stroke = L["STAMP_CYL"]
    cyl6432(A, "stamp_cylinder", "stamp", "carriage", bore, stroke, "z", z["car"], (x0 + L["CARR_L"] / 2, yf), -1,
            tag="Q16", joint="stamp_x", note="stamp cylinder, rear flange on the carriage")
    A(Part("stamp_rod", "stamp", "tool", "cyl", (x0 + L["CARR_L"] / 2, yf, z["rod"]), ("z", L["ROD_OUT"], H.CYL[bore]["rod"]),
           "#b9bec4", joint="stamp_z"))
    A(Part("stamp_die", "stamp", "tool", "cyl", (x0 + L["CARR_L"] / 2, yf, z["zs"]), ("z", 10.0, L["STAMP_D"]), "#e0a02a",
           joint="stamp_z", hw="heated flavour die", note="flavour die, heated"))
    A(Part("stamp_sync_sensor", "stamp", "sensor", "box", (x0 - 75, yf - 55, L["BELT_Z"] + 5), (15.0, 7.5, 15.0),
           "#1b8f52", tag="I8", hw="diffuse_M12",
           note="puck-edge sensor: latches the master-axis position to phase the carriage"))


def _qc(A):
    yb = y_back()
    x0, x1 = L["QC_X"]
    zr = 200.0
    yo = yb + 84.0                                         # outer wall: room for the NFC head outside the guide
    for side, y0 in (("in", yb - 62), ("out", yo)):          # 12 mm panels: an M3 needs 2 x 5.1 mm edge room
        A(Part(f"qc_wall_{side}", "qc", "hood", "box", (x0, y0, 0), (x1 - x0, 12.0, zr), "#cf3a2f",
               hw="Al composite panel 10 mm (threaded inserts)", note="light-tight hood (the colour sensor reads ambient light too)"))
    A(Part("qc_roof", "qc", "hood", "box", (x0, yb - 62, zr), (x1 - x0, yo + 12 - (yb - 62), 12.0), "#2b2b2f",
           hw="Al composite panel 12 mm (threaded inserts)"))
    lip = z_cookie_top() + 10
    for end, xe in (("in", x1 - 12), ("out", x0)):
        A(Part(f"qc_lip_{end}", "qc", "hood", "box", (xe, yb - 50, lip), (12.0, yo - (yb - 50), zr - lip), "#2b2b2f",
               hw="Al composite panel 10 mm (threaded inserts)", note="entry/exit lip: product opening below it"))
    A(Part("qc_camera", "qc", "vision", "cyl", (L["CAM_X"], yb, zr - 40), ("z", 40.0, 30.0), "#2b2b2f", tag="CAM1",
           hw="GigE global-shutter camera",
           note="top view; AI: flavour, burn, crack, size (trained on renders of this twin)"))
    A(Part("qc_ringlight", "qc", "vision", "cyl", (L["CAM_X"], yb, zr - 45), ("z", 5.0, 70.0), "#f2f0ea", tag="Q17",
           hw="ringlight"))
    A(Part("A1_colour_sensor", "qc", "sensor", "box", (L["CS_X"] - 15, yb - 7.5, z_cookie_top() + L["SENSOR_GAP"]),
           (30.0, 15.0, 15.0), "#2b2b2f", tag="AI1", hw="colour_sensor",
           note="true-colour sensor, SENSOR_GAP above the cookie"))
    A(Part("nfc_qc", "qc", "sensor", "box", (x0 + 10, yb + 46, L["BELT_Z"] - 30), (40.0, 34.0, 25.0), "#2f6fd0",
           tag="NFC-W2", hw="nfc_head", note="writes the QC verdict into the puck tag"))
    kx = L["KICK_X"]
    bore, stroke = L["KICK_CYL"]
    w = H.CYL[bore]["od"] + 3
    zk = L["KICK_Z"]
    A(Part("kick_paddle", "qc", "reject", "box", (kx - L["KICK_W"] / 2, yb + 38, z_seat() + 2),
           (L["KICK_W"], 6.0, zk + w / 2 - z_seat() - 2), "#e0492f", joint="kick_y", hw="Al paddle 6 mm",
           note="hangs from the rod end; sweeps -Y across the chain (guide gap here)"))
    A(Part("kick_rod", "qc", "reject", "cyl", (kx, yb + 44, zk), ("y", 1.0, H.CYL[bore]["rod"]), "#b9bec4",
           joint="kick_y", hw="rod end M4 into the paddle"))
    cyl6432(A, "kick_cylinder", "qc", "reject", bore, stroke, "y", yb + 45, (kx, zk), +1, tag="Q18",
            note="reject kicker, nose-mounted on its post, ABOVE the tray lanes")
    A(Part("kick_mount", "qc", "reject", "box", (kx - 15, yb + 45, zk - w / 2 - 6), (29.0, 30.0, 6.0), "#9aa3ab",
           hw="Al plate 6 mm", note="adapter: end-tapped to the post, the cylinder's foot screwed into it"))
    A(Part("kick_post", "qc", "reject", "box", (kx - 10, yb + 45, 0), (20.0, 20.0, zk - w / 2 - 6), "#d6d9da",
           mech="profile:2020", hw="HFS5-2020"))
    fw_, fd_ = L["FUNNEL"]
    A(Part("reject_funnel", "qc", "reject", "box", (kx - fw_ / 2, yb - 32 - 6 - 1 - fd_, 0), (fw_, fd_, z_seat() - 8),
           "#474b52", hw="Al sheet funnel",
           note="funnel over a hole in the table deck (cookie falls ~80 mm into it)"))
    bx, by, bw_, bd, bh = L["REJECT_BIN"]
    zt = -L["TABLE"][2]
    gap = L["REJECT_GAP"] if L.get("SAFE1") else 2.0
    if L.get("SAFE1"):              # S-1c: the hole under the funnel is shut whenever the drawer is not fully in
        hx0, hy0, ho = reject_hole()
        sh = H.SAFE["reject_shutter"]["t"]
        A(Part("reject_shutter", "qc", "reject", "box", (hx0 - 10, hy0 - 10, zt - sh), (ho + 20, 2 * ho + 40, sh),
               "#9aa3ab", hw="reject shutter unit",
               note="spring-closed blade under the deck hole, held open by the drawer only when it is fully in"))
    hollow(A, "reject_bin", "qc", "reject", bx, by, zt - bh - gap, bw_, bd, bh, 3.0, "#474b52", hw="PP bin",
           note=f"open drawer bin UNDER the table, ~{reject_cap()} cookies; pulled from the front edge "
                f"on two slides; level sensor -> AMR at {L['REQ_REJECT']:.0%}")
    for k, sx in enumerate((bx - 14, bx + bw_)):          # 14 wide: an M4 into the deck needs 2 x 6.75 edge room
        A(Part(f"reject_slide_{k}", "qc", "reject", "box", (sx, 0.0, zt - 35), (14.0, by + bd, 35.0), "#b9bec4",
               hw="telescopic slide 35 x 12", note="drawer slide under the deck"))
    A(Part("reject_level", "qc", "sensor", "box", (bx + bw_ / 2 - 10, by + bd, zt - 16), (20.0, 20.0, 14.0),
           "#1b8f52", tag="IOL4", hw="tof_level", note="drawer fill level"))


def _delta(A, name, xd, pose=None, static=True, moving=True):
    yd, zd = L["DELTA_Y"], L["DELTA_Z"]
    ex, ey, ez = pose or (xd, yd, L["TRAVEL_Z"])
    motor, gear = L["DELTA_MOTOR"], L["DELTA_GEAR"]
    ln = H.STEPPER[motor]["body"] + H.STEPPER[motor]["enc_len"] + H.GEARBOX[gear]["length"]
    rr = H.NEMA17["flange"] / 2 * math.sqrt(2) + 0.1                     # square body -> round envelope
    zb = zd + math.ceil(rr)
    if static:
        A(Part(f"{name}_base", "pick", name, "cyl", (xd, yd, zb), ("z", 12.0, 2 * (L["DELTA_RB"] + 60)), "#2b2b2f",
               hw="Al base plate 12 mm"))
    for phi, sh, el, wr in delta_points(ex, ey, ez, xd):
        c, s = math.cos(math.radians(phi)), math.sin(math.radians(phi))
        tx, ty = -s, c                                                    # motor axis = tangent
        g = L["MOTOR_GAP"]
        if static:
            A(Part(f"{name}_motor_{int(phi)}", "pick", name, "rod",
                   (sh[0] - g * tx, sh[1] - g * ty, zd), (sh[0] - (g + ln) * tx, sh[1] - (g + ln) * ty, zd, 2 * rr),
                   "#e0492f", tag=f"{name}.M{int(phi)}", hw=f"{motor}+{gear}",
                   note="closed-loop NEMA 17 + precision planetary (backlash budget), hung under the base"))
            A(Part(f"{name}_shaft_{int(phi)}", "pick", name, "rod",
                   (sh[0] - g * tx, sh[1] - g * ty, zd), (sh[0] + 8 * tx, sh[1] + 8 * ty, zd,
                                                          H.GEARBOX[gear]["shaft"][0]), "#9aa3ab"))
        if moving:
            A(Part(f"{name}_upper_{int(phi)}", "pick", name, "rod", sh, (*el, 12.0), "#d6d9da", joint=name,
                   hw="CFK tube 12 + clamp hub"))
            A(Part(f"{name}_pin_{int(phi)}", "pick", name, "rod", (el[0] - 18 * tx, el[1] - 18 * ty, el[2]),
                   (el[0] + 18 * tx, el[1] + 18 * ty, el[2], 8.0), "#9aa3ab", joint=name,
                   hw="elbow cross pin D8, ball studs"))
            for k in (-1, 1):
                o = 18 * k
                A(Part(f"{name}_fore_{int(phi)}_{'ab'[k > 0]}", "pick", name, "rod",
                       (el[0] + o * tx, el[1] + o * ty, el[2]), (wr[0] + o * tx, wr[1] + o * ty, wr[2], 5.0),
                       "#2b2b2f", joint=name, hw="CFK rod 5 + ball joints", note="parallelogram"))
    if moving:
        A(Part(f"{name}_effector", "pick", name, "cyl", (ex, ey, ez), ("z", 10.0, 2 * L["DELTA_RE"] + 16), "#e0492f",
               joint=name, hw="Al effector"))
        A(Part(f"{name}_cup", "pick", name, "cyl", (ex, ey, ez - L["CUP_L"]), ("z", L["CUP_L"], 24.0), "#26282b",
               joint=name, tag=f"{name}.VAC", hw="bellows cup D24 on spring stem",
               note="vacuum cup: ejector valve (DO) + vacuum switch (DI)"))


def portal():
    y0, y1 = y_back() - 32 - 6 - 50, L["LANE_Y"][-1] + 110
    # portal beams 80 above the shoulders: at the pick poses delta B's 285 deg elbow rises to z ~590
    return L["DELTA_X"][1] - 210, L["DELTA_X"][0] + 190, y0, y1, L["DELTA_Z"] + 80


def _pick(A):
    x0, x1, y0, y1, zt = portal()
    for px in (x0, x1 - 40):
        for py in (y0, y1 - 40):
            A(Part(f"portal_post_{int(px)}_{int(py)}", "pick", "portal", "box", (px, py, 0), (40.0, 40.0, zt),
                   "#d6d9da", mech="profile:4040", hw="HFS8-4040"))
    for py in (y0, y1 - 40):
        A(Part(f"portal_beam_{int(py)}", "pick", "portal", "box", (x0, py, zt), (x1 - x0, 40.0, 40.0), "#d6d9da",
               mech="profile:4040", hw="HFS8-4040"))
    rr = H.NEMA17["flange"] / 2 * math.sqrt(2) + 0.1
    zb_top = L["DELTA_Z"] + math.ceil(rr) + 12
    for i, xd in enumerate(L["DELTA_X"]):
        A(Part(f"delta_mount_{'AB'[i]}", "pick", "portal", "box", (xd - 20, y0, zt + 40), (40.0, y1 - y0, 40.0),
               "#d6d9da", mech="profile:4040", hw="HFS8-4040"))
        A(Part(f"delta_hanger_{'AB'[i]}", "pick", "portal", "box", (xd - 20, L["DELTA_Y"] - 20, zb_top),
               (40.0, 40.0, zt + 40 - zb_top), "#d6d9da", mech="profile:4040", hw="HFS8-4040",
               note="hanger: corner brackets to the mount, base plate screwed into its end tap"))
        _delta(A, f"delta_{'AB'[i]}", xd)
    A(Part("track_camera", "pick", "vision", "cyl", (1080.0, y_back(), 300.0), ("z", 40.0, 30.0), "#2b2b2f",
           tag="CAM2", hw="GigE global-shutter camera",
           note="tracking camera upstream of the deltas: cookie pose + puck phase for the pickers"))
    A(Part("nfc_pick", "pick", "sensor", "box", (L["DELTA_X"][0] + 130, y_back() + 40, L["BELT_Z"] - 30),
           (40.0, 34.0, 25.0), "#2f6fd0", tag="NFC-R", hw="nfc_head",
           note="reads flavour + QC verdict before the pick zone"))


def _tray(A, name, x_c, y_c, z0, cookies, sealed, colour_of):
    """Pocket tray (mech tray:3 -> CAD cuts the pockets) + the cookies in its pockets."""
    bl, bw, _ = L["BOX"]
    A(Part(name, "pack", "tray", "box", (x_c - bl / 2, y_c - bw / 2, z0), (bl, bw, L["TRAY_H"]), "#f4f2ec",
           mech=f"tray:{L['PACK']}", note=f"thermoformed tray, {L['PACK']} round pockets D{L['POCKET_D']:g} x "
                                          f"{L['POCKET_DEPTH']:g}, {L['FLANGE']:g} mm flange"))
    floor = z0 + L["TRAY_H"] - L["POCKET_DEPTH"]
    for k in range(cookies):
        cx = x_c + (k - (L["PACK"] - 1) / 2) * L["POCKET_PITCH"]
        A(Part(f"{name}_cookie_{k}", "pack", "stock", "cyl", (cx, y_c, floor), ("z", L["COOKIE"][1], L["COOKIE"][0]),
               colour_of))
    if sealed:
        A(Part(f"{name}_film", "pack", "tray", "box", (x_c - bl / 2, y_c - bw / 2, z0 + L["TRAY_H"]),
               (bl, bw, 0.6), "#cfe3f2", note="peelable lidding film (drawn 0.6 thick)"))


def _cassette(A, name, x0, y_c, packs, joint, colour_of):
    """Hollow guided magazine: open bottom (spring pawls = inlet), open top (FIFO outlet)."""
    cw, cd, ch = L["CASS"]
    t = L["CASS_WALL"]
    z0 = L["CASS_Z"]
    y0 = y_c - cd / 2
    hollow(A, name, "pack", "cassette", x0, y0, z0, cw, cd, ch, t, "#cfd8df", bottom=False, joint=joint,
           hw="cassette, Al sheet 2 mm",
           note=f"pack cassette: OPEN BOTTOM with spring pawls (the stacker pushes packs in), OPEN TOP "
                f"(retrieval, FIFO: the first pack in rises to the top); {cass_cap()} packs")
    for k, (px, py) in enumerate(((x0 + t, y0 + t), (x0 + cw - t - 12, y0 + t), (x0 + t, y0 + cd - t - 6),
                                  (x0 + cw - t - 12, y0 + cd - t - 6))):
        A(Part(f"{name}_pawl_{k}", "pack", "cassette", "box", (px, py, z0), (12.0, 6.0, 8.0), "#e0492f", joint=joint,
               note="spring pawl: swings up as a pack passes, snaps under its flange"))
    for k, lx in enumerate((x0 - 6, x0 + cw - t)):      # lugs on the END walls: the top opening stays clear
        A(Part(f"{name}_lug_{k}", "pack", "cassette", "box", (lx, y_c - 15, z0 + ch), (6 + t, 30.0, 8.0), "#2b2b2f",
               joint=joint, note="hanger lug: the shuttle bar rests on it (outside the outlet)"))
    bl, bw, bh = L["BOX"]
    if packs:
        A(Part(f"{name}_stack", "pack", "stock", "box", (x0 + cw / 2 - bl / 2, y_c - bw / 2, z0 + 8),   # ON the pawls
               (bl, bw, packs * bh), colour_of, joint=joint, mech=f"stack:{packs}",
               note=f"{packs} sealed packs on the pawls"))


def shuttle_z():
    """z levels of the cassette shuttle, bottom up (rail under a lane beam)."""
    z_ct = L["CASS_Z"] + L["CASS"][2]
    rail = H.MGN["MGN12H"]
    z_bar = z_ct + 8
    z_blk = z_bar + 8
    z_beam = z_blk + rail["H"]
    return dict(top=z_ct, bar=z_bar, blk=z_blk, beam=z_beam, beam_top=z_beam + 30)


def _lanes(A):
    x0, x1 = L["LANE_X"]
    bl, bw, bh = L["BOX"]
    mx0, mx1 = L["BOXMAG_X"]
    mxc = (mx0 + mx1) / 2
    zb = L["LANE_Z"] + L["TRAY_H"] + 7                    # forks run 0.4 mm above a passing pack
    hgt = L["BOXMAG_CAP"] * L["BOX_NEST"]
    for i, (f, y) in enumerate(zip(FLAV, L["LANE_Y"])):
        col = L["BAKED"][i]
        A(Part(f"lane_{f}_belt", "pack", "lane", "box", (x0, y - L["LANE_W"] / 2, L["LANE_Z"] - 10),
               (x1 - x0, L["LANE_W"], 10.0), "#3b3e44", mech="belt:lane", hw="mini belt conveyor belt 60",
               note="tray lane, indexes one tray pitch when a tray is full"))
        A(Part(f"lane_{f}_frame", "pack", "lane", "box", (x0, y - L["LANE_W"] / 2 - 3, 0),
               (x1 - x0, L["LANE_W"] + 6, L["LANE_Z"] - 10), "#d6d9da", tag=f"Q{20 + i}",
               hw=f"mini belt conveyor 60, end drive {L['LANE_MOTOR']}+PG5 inside the frame",
               note="lane conveyor frame (bought); the drive sits inside its envelope"))
        # trays: filling under B, filling under A, sealed after the sealer
        _tray(A, f"tray_{f}_B", L["DELTA_X"][1], y, L["LANE_Z"], 1, False, col)
        _tray(A, f"tray_{f}_A", L["DELTA_X"][0], y, L["LANE_Z"], 2, False, col)
        _tray(A, f"tray_{f}_sealed", L["SEAL_X"], y, L["LANE_Z"], 3, True, col)
        # empty-tray magazine: END guides (the tray's x ends) + nested stack + fork escapement
        for k, (gx, gy) in enumerate(((mxc - bl / 2 - 5, y - 32), (mxc - bl / 2 - 5, y + 15),
                                      (mxc + bl / 2 + 1, y - 32), (mxc + bl / 2 + 1, y + 15))):
            A(Part(f"boxmag_{f}_guide_{k}", "pack", "boxmag", "box", (gx, gy, zb), (4.0, 17.0, hgt), "#d6d9da",
                   hw="Al angle 4 mm", note="end guide of the empty-tray magazine (open top: the AMR drops a stack in)"))
        A(Part(f"boxmag_{f}_stack", "pack", "stock", "box", (mxc - bl / 2, y - bw / 2, zb),
               (bl, bw, hgt * 0.8), "#f4f2ec", mech=f"stack:{int(L['BOXMAG_CAP'] * 0.8)}",
               note="nested empty trays (8 mm nest pitch)"))
        # escapement forks at the tray's x ENDS, hung under the magazine bars (there is no room
        # between the lanes: the conveyors stand 4 mm apart)
        for k, fx in enumerate((mxc - bl / 2 - 25, mxc + bl / 2 - 3)):
            A(Part(f"boxmag_{f}_fork_{'lr'[k]}", "pack", "boxmag", "box", (fx, y - 10, zb - 6), (28.0, 20.0, 6.0),
                   "#e0492f", tag=f"Q{33 + i}", hw=f"ISO6432-{L['FORK_CYL'][0]}x{L['FORK_CYL'][1]} + POM fork",
                   note="escapement fork under the bottom tray's end flange: release one, hold the rest"))
        # top sealer: heated head on a cylinder hanging from the crossbeam, twin film reels
        sx = L["SEAL_X"]
        zh = L["LANE_Z"] + bh + L["SEAL_GAP"]
        A(Part(f"sealer_{f}_head", "pack", "sealer", "box", (sx - bl / 2 - 5, y - bw / 2 - 1, zh),
               (bl + 10, bw + 2, 18.0), "#e0a02a", joint=f"seal_{f}", tag=f"Q{36 + i}", hw="sealer_head",
               note=f"heated sealing head, {L['SEAL_T']:g} s dwell during the lane index pause"))
    # tray-magazine frame: two 2020 bars across the lanes at the guides' outer faces, on 2020 posts
    yy0, yy1 = L["LANE_Y"][0] - L["LANE_W"] / 2 - 3 - 21, L["LANE_Y"][-1] + L["LANE_W"] / 2 + 3 + 21
    for k, bx in enumerate((mxc - bl / 2 - 5 - 20, mxc + bl / 2 + 5)):
        A(Part(f"traymag_bar_{k}", "pack", "traymag", "box", (bx, yy0, zb), (20.0, yy1 - yy0, 20.0), "#d6d9da",
               mech="profile:2020", hw="HFS5-2020", note="carries the end guides of all three tray magazines"))
        for py in (yy0, yy1 - 20):
            A(Part(f"traymag_post_{k}_{int(py)}", "pack", "traymag", "box", (bx, py, 0), (20.0, 20.0, zb), "#d6d9da",
                   mech="profile:2020", hw="HFS5-2020"))
    sx = L["SEAL_X"]
    yb0, yb1 = y_back() + 62, L["LANE_Y"][-1] + L["LANE_W"] / 2 + 12
    zbeam = L["LANE_Z"] + 230
    for px in (sx - 95, sx + 30):                      # front posts clear of the reject kicker
        for py in (yb0, yb1):
            A(Part(f"seal_post_{int(px)}_{int(py)}", "pack", "sealer", "box", (px, py, 0), (30.0, 30.0, zbeam),
                   "#d6d9da", mech="profile:3030", hw="HFS8-3030"))
    for py in (yb0, yb1):
        A(Part(f"seal_beam_{int(py)}", "pack", "sealer", "box", (sx - 95, py, zbeam), (155.0, 30.0, 30.0),
               "#d6d9da", mech="profile:3030", hw="HFS8-3030"))
    A(Part("seal_crossbeam", "pack", "sealer", "box", (sx - 15, yb0, zbeam + 30), (30.0, yb1 + 30 - yb0, 30.0),
           "#d6d9da", mech="profile:3030", hw="HFS8-3030", note="carries the three sealing cylinders and reel arms"))
    bore, stroke = L["SEAL_CYL"]
    rd = 2 * math.sqrt(L["FILM_M"] * 0.00006 * 1e6 / math.pi + 38.0 ** 2)      # reel OD from film length
    for i, (f, y) in enumerate(zip(FLAV, L["LANE_Y"])):
        zh = L["LANE_Z"] + bh + L["SEAL_GAP"]
        cl = cyl6432(A, f"sealer_{f}_cyl", "pack", "sealer", bore, stroke, "z", zbeam + 30, (sx, y), -1,
                     note="sealing cylinder, rear flange under the crossbeam")
        A(Part(f"sealer_{f}_rod", "pack", "sealer", "cyl", (sx, y, zh + 18), ("z", zbeam + 30 - cl - zh - 18,
                                                                              H.CYL[bore]["rod"]),
               "#b9bec4", joint=f"seal_{f}", hw="rod extension"))
        rs, ys_ = L["REEL_SIDE"][i], L["ARM_SIDE"][i]
        rx = sx + rs * L["REEL_DX"]
        ax0, ax1 = (sx + 15, rx + 14) if rs > 0 else (rx - 14, sx - 15)
        ay0 = y + 31 if ys_ > 0 else y - 46
        A(Part(f"sealer_{f}_reelarm", "pack", "sealer", "box", (ax0, ay0, zbeam - 60),
               (ax1 - ax0, 15.0, g1(2 * rd + 70)), "#9aa3ab", hw="Al plate 15 mm",
               note="reel arm, bracketed to the crossbeam; carries both reel spindles"))
        for k in range(L["REELS"]):
            zc = g1(zbeam - 60 + 10 + rd / 2 + k * (rd + 6))
            A(Part(f"sealer_{f}_reel_{k}", "pack", "sealer", "cyl", (rx, y - 30, zc), ("y", 60.0, rd),
                   "#cfe3f2", mech="tube:76",
                   note=f"film reel {L['FILM_M']:g} m ({'unwind' if k == 0 else 'spare, auto-splice'})"))
            A(Part(f"sealer_{f}_spindle_{k}", "pack", "sealer", "cyl", (rx, y - 31 if ys_ < 0 else y - 30, zc),
                   ("y", 61.0, 75.8), "#9aa3ab", hw="reel chuck D76 (expanding core) on a D20 Al spindle"))
    cw, cd, ch = L["CASS"]
    sz = shuttle_z()
    bore, stroke = L["STACK_CYL"]
    zt = -L["TABLE"][2]
    for i, (f, y) in enumerate(zip(FLAV, L["LANE_Y"])):
        col = L["BAKED"][i]
        xa, xs_ = L["CASS_X"]
        A(Part(f"stacker_{f}", "pack", "stacker", "box", (L["LANE_X"][1], y - L["LANE_W"] / 2, L["LANE_Z"] - 10),
               (xa + cw - L["LANE_X"][1] + 5, L["LANE_W"], 10.0), "#3b3e44", mech="belt:lane",
               hw="transfer belt (driven with the lane)", note="transfer onto the stacker platform under the active cassette"))
        A(Part(f"stacker_frame_{f}", "pack", "stacker", "box", (L["LANE_X"][1], y - L["LANE_W"] / 2 - 3, 0),
               (xa + cw - L["LANE_X"][1] + 5, L["LANE_W"] + 6, L["LANE_Z"] - 10 - 10 - 1), "#d6d9da",
               hw="transfer conveyor frame", note="the lift plate rises through it"))
        A(Part(f"stacker_plate_{f}", "pack", "stacker", "box", (xa + cw / 2 - 60, y - 20, L["LANE_Z"] - 20),
               (120.0, 40.0, 10.0), "#e0492f", joint=f"lift_{f}", hw="Al plate 10 mm",
               note="lift plate, rises through a slot in the transfer belt"))
        A(Part(f"stacker_rod_{f}", "pack", "stacker", "cyl", (xa + cw / 2, y, zt), ("z", L["LANE_Z"] - 20 - zt,
                                                                                    H.CYL[bore]["rod"]),
               "#b9bec4", joint=f"lift_{f}", hw="push rod (extended piston rod)"))
        cyl6432(A, f"stacker_lift_{f}", "pack", "stacker", bore, stroke, "z", zt, (xa + cw / 2, y), -1,
                tag=f"Q{24 + i}", note=f"bottom-up stacker UNDER the deck: lifts each sealed pack "
                                       f"{L['PAWL'] + bh:g} mm through the spring pawls")
        _cassette(A, f"cassette_{f}_active", xa, y, 11, f"shuttle_{f}", col)
        if not L.get("AIRLOCK"):                          # S-1b: the standby bay is the airlock chamber, empty
            _cassette(A, f"cassette_{f}_standby", xs_, y, cass_cap(), f"shuttle_{f}", col)
        A(Part(f"stack_count_{f}", "pack", "sensor", "box", (xa + cw / 2 - 30, y - 10, -L["TABLE"][2] - 40),
               (10.0, 20.0, 20.0), "#1b8f52", tag=f"I{12 + i}", hw="reed",
               note="reed switch on the lift cylinder: lifts are counted, the cassette is full at cass_cap() "
                    "(a sensor above the cassette would sit in the shuttle's path)"))
    if L.get("SAFE1"):              # S-1c: the lifts move under the deck - a closed sheet box around them
        _lift_guard(A)
    gx0, gx1 = L["CASS_X"][0] - 20, L["CASS_X"][1] + cw + 20
    gy0, gy1 = y_back() + 62, L["LANE_Y"][-1] + cd / 2 + 10
    rail = H.MGN["MGN12H"]
    for px in (gx0, gx1 - 30):
        for py in (gy0, gy1):
            A(Part(f"cass_post_{int(px)}_{int(py)}", "pack", "gantry", "box", (px, py, 0), (30.0, 30.0, sz["beam"]),
                   "#d6d9da", mech="profile:3030", hw="HFS8-3030"))
        A(Part(f"cass_ybeam_{int(px)}", "pack", "gantry", "box", (px, gy0, sz["beam"]), (30.0, gy1 + 30 - gy0, 30.0),
               "#d6d9da", mech="profile:3030", hw="HFS8-3030"))
    lock = L.get("AIRLOCK")
    hx = L["OUT_LOCK"]["hx"]
    for i, (f, y) in enumerate(zip(FLAV, L["LANE_Y"])):
        spans = [(gx0 + 30, hx), (hx + 30, gx1 - 30)] if lock else [(gx0 + 30, gx1 - 30)]
        for k, (b0, b1) in enumerate(spans):
            A(Part(f"shuttle_beam_{f}" + (f"_{k}" if lock else ""), "pack", "gantry", "box", (b0, y - 15, sz["beam"]),
                   (b1 - b0, 30.0, 30.0), "#d6d9da", mech="profile:3030", hw="HFS8-3030",
                   note="lane beam: the shuttle rail hangs under it" + (" (ends on the airlock header)" if lock else "")))
        A(Part(f"shuttle_rail_{f}", "pack", "gantry", "box", (gx0 + 30, y - rail["rail"][0] / 2,
                                                             sz["beam"] - rail["rail"][1]),
               (gx1 - gx0 - 60, rail["rail"][0], rail["rail"][1]), "#9aa3ab", hw="MGN12H rail"))
        xa, xs_ = L["CASS_X"]
        if lock:     # one-cassette carrier: stroke CASS_X[1] - CASS_X[0] into the airlock chamber and back
            A(Part(f"shuttle_bar_{f}", "pack", "gantry", "box", (xa - 6, y - 16, sz["bar"]), (cw + 12, 32.0, 8.0),
                   "#3b3e44", joint=f"shuttle_{f}", hw="Al bar 30x8",
                   note="carrier bar: the cassette hangs on it by its lugs; drawn at the stacker"))
            xcs = (xa + cw / 2 - 50, xa + cw / 2 + 50)
        else:
            A(Part(f"shuttle_bar_{f}", "pack", "gantry", "box", (xa - 6, y - 16, sz["bar"]),
                   (xs_ + cw + 6 - xa + 6, 32.0, 8.0), "#3b3e44", joint=f"shuttle_{f}", hw="Al bar 30x8",
                   note="shuttle bar: rests on the lugs of both cassettes, carried by two MGN12H blocks"))
            xcs = (xa + cw / 2, xs_ + cw / 2)
        for k, xc in enumerate(xcs):
            A(Part(f"shuttle_block_{f}_{k}", "pack", "gantry", "box", (xc - rail["L"] / 2, y - rail["W"] / 2, sz["blk"]),
                   (rail["L"], rail["W"], rail["H"] - 3.0), "#3b3e44", joint=f"shuttle_{f}", hw="MGN12H block"))
        md = 21
        # 8 mm machined plate: the NEMA screw heads sit in counterbores (the gantry's corner bracket
        # is 0.7 mm from the last lane's upper heads otherwise)
        A(Part(f"shuttle_plate_{f}", "pack", "gantry", "box", (gx1, y - 5, sz["beam"] - 49),
               (8.0, 52.0, 79.0), "#9aa3ab", hw="Al motor plate 8 mm"))
        # motor axis below the y-beam: its upper M3 heads clear the beam
        nema(A, f"M_shuttle_{f}", "pack", "gantry", "x", gx1 + 8, (y + md, sz["bar"] - 3), None, L["SHUTTLE_MOTOR"],
             tag=f"Q{27 + i}", sign=1, note="shuttle drive, GT2 20T belt along the lane beam (EL7047)")


def _control(A):
    cx, cy, cw, cd, ch = L["CAB"]
    zt = -L["TABLE"][2]
    A(Part("cabinet_wall_top", "control", "cab", "box", (cx, cy, zt - 1.5), (cw, cd, 1.5), "#3a3f44",
           hw="sheet-steel enclosure back wall", note="the enclosure's back wall, screwed to the deck underside"))
    hollow(A, "cabinet", "control", "cab", cx, cy, zt - ch, cw, cd, ch - 1.5, 1.5, "#3a3f44",
           hw="sheet-steel enclosure, hung under the deck",
           note="Beckhoff CX2020 + EL terminals, PSUs, SSRs, terminal blocks (layout: plc_io.py)")
    # plc_io.cabinet(): ~170 W of losses give 27 K by natural convection -> filter fan in, grille out
    A(Part("cabinet_fan", "control", "cab", "box", (cx - 20, cy + cd / 2 - 60, zt - ch / 2 - 60), (20.0, 120.0, 120.0),
           "#2b2b2f", hw="filter fan 24 V 60 m3/h, 120 mm", note="always on with the 24 V logic supply"))
    A(Part("cabinet_grille", "control", "cab", "box", (cx + cw, cy + cd - 190, zt - ch / 2 - 60), (12.0, 120.0, 120.0),
           "#2b2b2f", hw="exhaust filter grille 120 mm"))
    A(Part("cab_mount_plate", "control", "cab", "box", (cx + 1.5, cy + 1.5, zt - ch + 1.5), (cw - 3, cd - 3, 2.0),
           "#c9ced2", hw="galvanised mounting plate 2 mm"))
    ix, iy = L["ISLAND_XY"]
    n = n_valves()
    st = n + math.ceil(n * L["VALVE_SPARE"])
    vi = H.VALVE_ISLAND
    zw = n_zones() * vi["zone_w"]
    A(Part("valve_island", "control", "pneu", "box", (ix, iy, 0), (g1(st * vi["station_w"] + vi["end_w"] + zw), vi["depth"],
                                                                   vi["height"]), "#1f63c4",
           hw=f"{vi['model']}, {st} stations", note=f"{n} valves used + {st - n} spare"
                                                     + (f"; {n_zones()} safe pressure-zone plates" if zw else "")))
    fx, fy, fz = L["FRL"]
    A(Part("frl", "control", "pneu", "box", (ix + st * vi["station_w"] + vi["end_w"] + zw + 20, iy, 0), (fx, fy, fz),
           "#1f63c4", tag="Q19", hw="FRL + soft-start / dump valve 24 V",
           note="air from the off-table compressor (hw AIR); dump valve = safe exhaust"))


def _ports(A):
    """Docking faces for the AMR fleet (the robots themselves stay on the floor)."""
    A(Part("port_raw", "ports", "port", "box", (L["HOPPER_X"][0], 0.0, 0.0),
           (L["HOPPER_X"][-1] + L["HOPPER"][0] - L["HOPPER_X"][0], 14.0, 40.0), "#1f4e8c", hw="docking plate Al 14 mm",
           note="front edge: raw-tote docking face (tipping tote refills a hopper from the front)"))
    A(Part("port_out", "ports", "port", "box", (L["TABLE"][0] - 14, L["LANE_Y"][0] - 60, 0.0),
           (14.0, L["LANE_Y"][-1] - L["LANE_Y"][0] + 120, 40.0), "#1f4e8c", hw="docking plate Al 14 mm",
           note="right edge: full cassette out, empty cassette in"))
    A(Part("port_boxes", "ports", "port", "box", (0.0, L["LANE_Y"][0] - 60, 0.0),
           (14.0, L["LANE_Y"][-1] - L["LANE_Y"][0] + 120, 40.0), "#1f4e8c", hw="docking plate Al 14 mm",
           note="left edge: empty-box stack refill"))
    A(Part("port_reject", "ports", "port", "box", (L["REJECT_BIN"][0] + 60, 0.0, 0.0), (120.0, 14.0, 40.0), "#1f4e8c",
           hw="docking plate Al 14 mm",
           note="front edge: reject drawer pull"))


MODULES = {
    "M1_loop": "Main loop - side-flexing flat-top chain, 48 NFC pucks, intermediate drive, master encoder",
    "M2_feeder": "Feeder - dual magazines per flavour, lead-compensated gravity drop, NFC write",
    "M3_tunnel": "Tunnel oven (3 heater zones) + cooling tunnel (2 fans)",
    "M4_stamp": "Flying stamp - MGN12H carriage on a Tr8x4 screw slaved to the master axis",
    "M5_qc": "Vision QC hood + colour sensor + on-the-fly reject",
    "M6_pick": "Pick cell - two tracking delta robots (N+1) on a portal",
    "M7_pack": "Box lanes (3 flavours) + bottom-up stackers into pack cassettes (AMR exchange through the airlock)",
    "M8_control": "Beckhoff enclosure under the deck, valve island, FRL",
    "M9_ports": "AMR docking faces - raw in + rejects (front), cassettes (right), boxes (left)",
    "M10_safety": "Safety - perimeter guard + roof, 3 doors with guard locking, AMR airlocks (boxes: trapdoor "
                  "chamber, cassettes: inner + outer door), E-stops (TwinSAFE, SAFETY_CONCEPT.md)",
}
_MOD_OF = {"loop": "M1_loop", "feeder": "M2_feeder", "tunnel": "M3_tunnel", "stamp": "M4_stamp",
           "qc": "M5_qc", "pick": "M6_pick", "pack": "M7_pack", "control": "M8_control", "ports": "M9_ports",
           "safety": "M10_safety"}


def _actuator_parts():
    out = []
    A = out.append
    _feeder(A)
    _stamp(A)
    _qc(A)
    _lanes(A)
    return out


def n_zones():
    """Safe pneumatic pressure zones on the island (S-1): the AMR ports whose zone has pneumatics."""
    if not L.get("SAFE1"):
        return 0
    parts = _zone_parts()
    return sum(1 for gs in L["PORT_ZONE"].values()
               if any(p.group in gs and (p.hw.startswith("ISO6432") or p.hw == "trapdoor unit") for p in parts))


def _zone_parts():
    out = []
    A = out.append
    _lanes(A)
    if L.get("SAFE1") and L.get("AIRLOCK"):
        _airlocks(A)
    return out


def n_valves():
    """Solenoid valves = pneumatic actuators (one valve per cylinder group) + vacuum ejectors."""
    cyl = {p.tag for p in _actuator_parts() if p.hw.startswith("ISO6432") and p.tag}
    n = len(cyl) + len(L["DELTA_X"])
    if L.get("SAFE1") and L.get("AIRLOCK"):            # airlock door drives + trapdoor actuators
        n += sum(1 for p in _zone_parts() if p.hw in ("airlock_door", "trapdoor unit"))
    return n


def build(t=0.0, with_product=True):
    out = []
    A = out.append
    _loop_parts(A)
    if with_product:
        _pucks(A, t)
    _feeder(A)
    o0, o1 = oven_x()
    _tunnel(A, "oven", o0, o1, L["HEATERS"], "heater")
    c0, c1 = cool_x()
    _tunnel(A, "cool", c0, c1, L["FANS"], "fan")
    _stamp(A)
    _qc(A)
    _pick(A)
    _lanes(A)
    _control(A)
    _ports(A)
    _pa1(A)
    _guard(A)
    for p in out:
        p.module = _MOD_OF[p.module]
    return out


def by_module(parts=None):
    parts = parts if parts is not None else build()
    d = {m: [] for m in MODULES}
    for p in parts:
        d[p.module].append(p)
    return d


# ---------------------------------------------------------------- proofs
def _ovl(a, b, tol=0.05):
    d = [min(a[i + 3], b[i + 3]) - max(a[i], b[i]) for i in range(3)]
    return min(d) if min(d) > tol else 0.0


def _circle_box(cx, cy, r, b):
    dx = max(b[0] - cx, 0, cx - b[3])
    dy = max(b[1] - cy, 0, cy - b[4])
    return dx * dx + dy * dy < r * r - 1e-9


def timing():
    """The line's timing budget, every number derived. Returns (rows, fails)."""
    T = takt()
    rows, fails = [], []

    def row(name, value, limit, ok, note):
        rows.append((name, value, limit, ok, note))
        if not ok:
            fails.append(f"TIMING {name}: {value} vs {limit} - {note}")

    rows.append(("takt (P / v)", f"{T:.2f} s", "", True,
                 f"{3600 / T:.0f} cookies/h, {3600 / T / 3:.0f} per flavour at 1:1:1"))
    err = L["N"] * L["PITCH"] - loop_len()
    row("loop closes", f"N*P - (2S + 2piR) = {err:+.2f} mm", f"|..| <= take-up {L['TAKEUP']:g}",
        abs(err) <= L["TAKEUP"], "S on the 0.1 mm grid; the drive unit's take-up absorbs the rest")
    tf = drop_time()
    lead = L["V"] * tf
    resid = L["V"] * L["VALVE_JITTER"]
    clr = (L["NEST"][0] - L["COOKIE"][0]) / 2
    row("feeder drop", f"fall {tf * 1000:.0f} ms -> belt moves {lead:.2f} mm, released {lead:.2f} mm early; "
        f"residual {resid:.2f} mm", f"nest radial clearance {clr:.2f} mm", resid <= clr,
        "without the lead the cookie would land %.2f mm off (> clearance)" % lead)
    row("tunnel oven", f"{oven_len():.0f} mm at {L['V']:g} mm/s", f"bake {L['BAKE_S']:g} s", True,
        "no door, no slider: bake time = length / speed")
    row("cooling tunnel", f"{cool_len():.0f} mm", f"cool {L['COOL_S']:g} s", True, "")
    track, dist, cyc = stamp_cycle()
    row("flying stamp cycle", f"{cyc:.2f} s", f"<= takt {T:.2f} s", cyc <= T,
        f"tracks {track:.2f} s = {dist:.0f} mm, returns at {L['RETURN_V']:g}x")
    row("flying stamp stroke", f"needs {dist + 20:.0f} mm", f"has {L['STAMP_STROKE']:g} mm",
        dist + 20 <= L["STAMP_STROKE"], "tracking distance + 20 mm accel/decel margin")
    d_ai = L["CAM_X"] - L["KICK_X"]
    row("QC verdict before the kicker", f"{d_ai / L['V']:.1f} s of travel", f">= AI latency {L['AI_LATENCY']:g} s",
        d_ai / L["V"] >= L["AI_LATENCY"] + L["KICK_T"], "camera -> kicker distance / v")
    win = (L["KICK_W"] - 0) / L["V"]
    row("reject kick", f"stroke {L['KICK_T']:g} s", f"cookie under paddle {win:.1f} s", L["KICK_T"] <= win, "")
    need = (y_back() + 38) - (y_back() - 38 - L["FUNNEL"][1] / 2 + L["COOKIE"][0] / 2)
    row("kick reaches the funnel", f"needs {need:.1f} mm", f"stroke {L['KICK_STROKE']:g} = cylinder {L['KICK_CYL'][1]}",
        need <= L["KICK_STROKE"] <= L["KICK_CYL"][1], "paddle pushes the cookie centre over the funnel centre")
    cap1 = 1 / L["T_PICK"]
    row("pick capacity, ONE delta", f"{cap1:.2f} /s", f">= demand {1 / T:.2f} /s", cap1 >= 1 / T,
        "N+1: either delta alone carries the line")
    c, tw = delta_window(L["DELTA_X"][0])
    row("tracking window per delta", f"{c:.0f} mm = {tw:.1f} s", f">= reach+grip {L['T_GRAB']:g} s",
        tw >= L["T_GRAB"], "chord of the reach circle over the back run")
    clr = (L["POCKET_D"] - L["COOKIE"][0]) / 2
    err = L["INDEX_ERR"] + L["DELTA_REP"] + L["CUP_ECC"]
    row("cookie into its pocket", f"radial clearance {clr:.2f} mm", f">= placement error {err:.2f} mm", clr >= err,
        "lane index + delta repeatability + cup eccentricity: the round cookie drops into the round pocket")
    span = (L["PACK"] - 1) * L["POCKET_PITCH"] + L["POCKET_D"]
    row("pockets fit the tray", f"{span:.1f} mm of pockets", f"<= {L['BOX'][0] - 2 * L['FLANGE']:.1f} inside the flange",
        span <= L["BOX"][0] - 2 * L["FLANGE"], "3 round cookies in a rectangular tray")
    head = L["POCKET_DEPTH"] - L["COOKIE"][1]
    row("cookie below the film", f"{head:.1f} mm headroom", "> 0", head > 0, "the film never touches the cookie")
    row("sealer in the index pause", f"{L['SEAL_T']:g} s", f"<= lane index {L['T_INDEX']:g} s",
        L["SEAL_T"] <= L["T_INDEX"], "seals while the lane indexes the next tray in")
    inner = (L["CASS"][0] - 2 * L["CASS_WALL"], L["CASS"][1] - 2 * L["CASS_WALL"])
    gap = min(inner[0] - L["BOX"][0], inner[1] - L["BOX"][1]) / 2
    row("pack guided in the cassette", f"{gap:.1f} mm per side", "0.5 .. 4 mm", 0.5 <= gap <= 4.0,
        "open bottom inlet / open top outlet, walls guide the stack")
    row("pawls hold the stack", f"engage {L['PAWL']:g} mm", f"<= flange {L['FLANGE']:g} mm", L["PAWL"] <= L["FLANGE"],
        "pawls catch the tray flange; FIFO: first pack in rises to the top outlet")
    packs_per_reel = L["FILM_M"] * 1000 / (L["BOX"][0] + 10)
    t_film = L["REELS"] * packs_per_reel * L["PACK"] / (rate_flavour() * 3600)
    row("film autonomy", f"{t_film:.1f} h per lane", ">= 8 h shift", t_film >= 8.0,
        f"{L['REELS']} reels x {packs_per_reel:.0f} packs, auto-splice; reload at shift change")
    rf = rate_flavour()
    row("singulator keeps up", f"{1 / L['SINGULATE_S']:.2f} cookies/s", f">= flavour rate {rf:.3f}/s",
        1 / L["SINGULATE_S"] >= rf, "hopper disc refills the tube buffer faster than the belt drains it")
    worst_ang = 90.0
    for i in range(3):
        for p0, p1 in chute(i):
            run = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            worst_ang = min(worst_ang, math.degrees(math.atan2(p0[2] - p1[2], run)))
    row("chutes run downhill", f"steepest-worst {worst_ang:.1f} deg", f">= {L['CHUTE_SLOPE']:g} deg",
        worst_ang >= L["CHUTE_SLOPE"], "v3 chutes rose 5 mm from the disc to the tube - found in the precise phase")
    a_hop = hopper_cap() / rf
    a_cas = cass_cap() * L["PACK"] / rf
    a_box = L["BOXMAG_CAP"] * L["PACK"] / rf
    a_rej = reject_cap() / (1 / T * 0.05)
    rows.append(("STOCK raw hopper", f"{hopper_cap()} cookies", f"{a_hop / 60:.0f} min per flavour", True,
                 f"+ {2 * L['MAG_CAP']} in the A/B tubes"))
    if L.get("AIRLOCK"):
        sw = cass_swap_t()
        rows.append(("STOCK finished cassette", f"{cass_cap()} packs = {cass_cap() * L['PACK']} cookies",
                     f"{a_cas / 60:.0f} min each", True,
                     f"airlock exchange {sw:.0f} s; a LATE robot blocks that lane (loss counted by line_sim)"))
    else:
        rows.append(("STOCK finished cassette", f"{cass_cap()} packs = {cass_cap() * L['PACK']} cookies",
                     f"{a_cas / 60:.0f} min each, A/B = {2 * a_cas / 60:.0f} min", True, "per flavour"))
    rows.append(("STOCK empty boxes", f"{L['BOXMAG_CAP']} boxes", f"{a_box / 60:.0f} min", True, "per lane"))
    rows.append(("STOCK rejects", f"{reject_cap()} cookies", f"{a_rej / 3600:.1f} h at 5 % rejects", True,
                 "drawer under the deck"))
    zmax = max(p.aabb()[5] for p in build(with_product=False))
    row("height limit", f"max z {zmax:.0f}", f"<= {L['MAX_H']:g}", zmax <= L["MAX_H"], "user: taller is fine")
    # AMR: a task's DEADLINE is the autonomy left when it is requested; the worst
    # case response of ONE robot is every other port task queued ahead of it.
    dl = {"cassette swap": a_cas,                          # other cassette fills meanwhile
          "raw refill": L["REQ_HOPPER"] * a_hop,
          "box refill": L["REQ_BOXMAG"] * a_box,
          "reject drawer": (1 - L["REQ_REJECT"]) * a_rej}
    n_tasks = 3 + 3 + 3 + 1
    worst = n_tasks * (L["AMR_TRIP"] + L["AMR_HANDLE"])
    if L.get("AIRLOCK"):
        # no standby cassette any more: the exchange is timed by the lift counter, a late AMR blocks
        # that one lane (a counted loss in line_sim), never the loop - so it is not a worst-case deadline
        del dl["cassette swap"]
        cover = transfer_buffer() * L["PACK"] / rf
        row("airlock exchange covered by the lane-end buffer", f"{transfer_buffer()} pack = {cover:.0f} s",
            f">= exchange {cass_swap_t():.0f} s", cover >= cass_swap_t(),
            "a robot on time costs no production: the waiting pack is lifted into the new cassette")
        rows.append(("AMR call: cassette exchange", f"{L['CASS_LEAD']:.0f} s before full",
                     f">= trip {L['AMR_TRIP']:g} s", L["CASS_LEAD"] >= L["AMR_TRIP"],
                     "airlock: no standby buffer - a late robot blocks that lane only (line_sim counts it)"))
        if L["CASS_LEAD"] < L["AMR_TRIP"]:
            fails.append("AMR call for the cassette exchange shorter than the trip")
    for k, d_ in dl.items():
        row(f"AMR deadline: {k}", f"{d_ / 60:.1f} min", f">= worst case ONE robot {worst / 60:.1f} min",
            d_ >= worst, "all 10 port tasks queued ahead - so one AMR suffices and the 2nd is N+1")
    per_h = (3 * 3600 / a_cas) + 3 * rf * 3600 / L["RAW_TOTE"] + 3 * 3600 / ((1 - L["REQ_BOXMAG"]) * a_box) + 0.2
    util = per_h * (L["AMR_TRIP"] + L["AMR_HANDLE"]) / 3600
    if L.get("AIRLOCK"):                               # the robot waits at the port through the exchange
        # the robot's handling time IS the exchange; extra = waiting for full + exchange beyond handling
        util += 3 * 3600 / a_cas * (L["CASS_LEAD"] - L["AMR_TRIP"] + cass_swap_t() - L["AMR_HANDLE"]) / 3600
        row("cassette exchanges never coincide", "staggered by a third" if L["CASS_STAGGER"] else "in phase",
            f"gap {a_cas / 3:.0f} s >= exchange {cass_swap_t() + L['CASS_LEAD']:.0f} s",
            L["CASS_STAGGER"] and a_cas / 3 >= cass_swap_t() + L["CASS_LEAD"],
            "equal flavour rates would fill all three at once; one robot then serves them in turn")
    row("AMR utilisation, one robot", f"{util:.0%}", "< 70 %", util < 0.7, f"{per_h:.1f} tasks/h")
    return rows, fails


# ------------------------------------------------------------- drive sizing
def sizing():
    """Every drive against its catalogue rating: torque at speed, gearbox
    rating, cylinder thrust and stroke, lead-screw whip, placement error from
    backlash, air consumption. Returns (rows, fails)."""
    rows, fails = [], []

    def row(name, value, limit, ok, note):
        rows.append((name, value, limit, ok, note))
        if not ok:
            fails.append(f"SIZING {name}: {value} vs {limit} - {note}")

    # --- Q1 loop drive: capstan pull of a side-flex chain round two 180 deg bends
    ch = H.CHAIN
    m = ch["mass"] * loop_len() / 1000 + L["N"] * L["PUCK_M"] + L["N"] * 0.75 * L["COOKIE_M"]
    f0 = ch["mu"] * m * G
    pull = f0 * math.exp(L["CHAIN_MU_CURVE"] * 2 * math.pi)
    row("chain pull (2 bends, capstan)", f"{pull:.0f} N", f"<= working load {ch['wl']:.0f} N", pull <= ch["wl"],
        f"{m:.1f} kg moving, mu {ch['mu']:g}, e^(mu*2pi) = {math.exp(L['CHAIN_MU_CURVE'] * 2 * math.pi):.2f}")
    gb = H.GEARBOX["PG27"]
    t_out = pull * H.DRIVE_UNIT["pd"] / 2 / 1000
    n_out = L["V"] / (math.pi * H.DRIVE_UNIT["pd"]) * 60
    n_mot = n_out * gb["ratio"]
    t_mot = t_out / gb["ratio"] / gb["eff"]
    row("Q1 gearbox PG27 output", f"{t_out:.2f} Nm", f"<= rated {gb['T_rated']:g} Nm", t_out <= gb["T_rated"],
        f"sprocket PD {H.DRIVE_UNIT['pd']:g} at {n_out:.1f} rpm")
    avail = H.stepper_torque("17HS19-2004D-E1000", n_mot)
    row("Q1 motor torque at speed", f"{t_mot:.3f} Nm @ {n_mot:.0f} rpm", f"<= {avail:.3f} Nm (50 % derate)",
        t_mot <= avail, "17HS19 closed loop on EL7047")
    # --- stamp axis: Tr8x4 on MGN12H
    ls = H.LEADSCREW[L["STAMP_SCREW"]]
    v_ret = L["RETURN_V"] * L["V"]
    n_s = v_ret / ls["lead"] * 60
    span = (L["STAMP_X0"] + L["STAMP_STROKE"] + L["CARR_L"] + 45 - 40) - (L["STAMP_X0"] - 20 + 15)
    n_c = H.WHIP_F["fixed-supported"] * ls["root"] / span ** 2 * 1e7
    row("stamp screw critical speed", f"{n_s:.0f} rpm", f"<= {H.WHIP_MARGIN:.0%} of {n_c:.0f} rpm (L {span:.0f})",
        n_s <= H.WHIP_MARGIN * n_c, "Tr8x4 fixed-supported")
    a = v_ret / 1000 / L["T_ACC"]
    F = L["STAMP_M"] * a
    t_load = F * ls["lead"] / 1000 / (2 * math.pi * ls["eff"])
    t_rot = H.ROTOR_J[L["STAMP_MOTOR"]] * (n_s * 2 * math.pi / 60) / L["T_ACC"]
    avail = H.stepper_torque(L["STAMP_MOTOR"], n_s)
    row("Q14 stamp motor torque", f"{t_load + t_rot:.3f} Nm @ {n_s:.0f} rpm", f"<= {avail:.3f} Nm",
        t_load + t_rot <= avail, f"carriage {L['STAMP_M']:g} kg to {v_ret:.0f} mm/s in {L['T_ACC']:g} s + rotor inertia")
    # --- delta pickers: torque and placement error from the Jacobian at every pose
    gear = H.GEARBOX[L["DELTA_GEAR"]]
    worst_t, worst_err, worst_rpm = 0.0, 0.0, 0.0
    e = math.radians(H.BACKLASH_ARCMIN[L["DELTA_GEAR"]] / 60 + H.STEP_ACC_DEG / gear["ratio"])
    Fm = L["DELTA_PAYLOAD"] * (G + L["DELTA_ACC"])
    for i, xd, pose, kind in delta_poses():
        J = delta_jacobian(*pose, xd)
        if J is None:
            fails.append(f"SIZING delta Jacobian singular at {pose}")
            continue
        ang = delta_ik(*pose, xd)
        for k in range(3):                                   # arm k
            col = [J[r][k] / 1000 for r in range(3)]          # m/rad
            tq = Fm * math.sqrt(sum(c * c for c in col)) + \
                L["DELTA_ARM_M"] * G * L["DELTA_L1"] / 2000 * abs(math.cos(math.radians(ang[k])))
            worst_t = max(worst_t, tq)
            w = L["DELTA_VMAX"] / math.sqrt(sum(c * c for c in col))       # rad/s if all speed on this arm
            worst_rpm = max(worst_rpm, w * 60 / (2 * math.pi) * gear["ratio"])
        err = math.sqrt(sum((sum(abs(J[r][k]) for k in range(3)) * e) ** 2 for r in range(3)))
        worst_err = max(worst_err, err)
    t_mot = worst_t / gear["ratio"] / gear["eff"]
    avail = H.stepper_torque(L["DELTA_MOTOR"], worst_rpm)
    row("delta joint torque (worst pose)", f"{worst_t:.2f} Nm", f"<= gearbox {gear['T_rated']:g} Nm",
        worst_t <= gear["T_rated"], f"payload {L['DELTA_PAYLOAD']:g} kg at g + {L['DELTA_ACC']:g} m/s2 via J^T F")
    row("delta motor torque at speed", f"{t_mot:.3f} Nm @ {worst_rpm:.0f} rpm", f"<= {avail:.3f} Nm",
        t_mot <= avail, f"{L['DELTA_MOTOR']} + {L['DELTA_GEAR']}")
    row("delta placement error (backlash + steps)", f"{worst_err:.3f} mm", f"<= DELTA_REP {L['DELTA_REP']:g} mm",
        worst_err <= L["DELTA_REP"], f"{H.BACKLASH_ARCMIN[L['DELTA_GEAR']]:g}' backlash: a PG5 (60') would give "
                                     f"{worst_err * math.radians(1.0 + H.STEP_ACC_DEG / 5.18) / e:.1f} mm")
    # --- singulator and shuttle
    gb = H.GEARBOX["PG14"]
    n_d = 60 / (6 * L["SINGULATE_S"])
    t_m = L["SING_T"] / gb["ratio"] / gb["eff"]
    avail = H.stepper_torque(L["SING_MOTOR"], n_d * gb["ratio"])
    row("singulator motor", f"{t_m:.3f} Nm @ {n_d * gb['ratio']:.0f} rpm", f"<= {avail:.3f} Nm", t_m <= avail,
        f"disc {L['SING_T']:g} Nm [assumed] via PG14")
    lock = L.get("AIRLOCK")
    ms = (1 if lock else 2) * (L["CASS_M"] + cass_cap() * L["PACK_M"])
    d = L["CASS_X"][1] - L["CASS_X"][0]
    tm = d / L["SHUTTLE_V"] if lock else L["SWAP_T"]
    acc = 4.5 * d / 1000 / tm ** 2
    Fsh = ms * acc + 0.005 * ms * G
    pd = 12.73
    vpk = 1.5 * d / tm
    n_sh = vpk / (math.pi * pd) * 60
    t_sh = Fsh * pd / 2000 + H.ROTOR_J[L["SHUTTLE_MOTOR"]] * (n_sh * 2 * math.pi / 60) / (tm / 3)
    avail = H.stepper_torque(L["SHUTTLE_MOTOR"], n_sh)
    row("shuttle motor (full cassette)" if lock else "shuttle motor (both cassettes full)",
        f"{t_sh:.4f} Nm @ {n_sh:.0f} rpm", f"<= {avail:.3f} Nm", t_sh <= avail,
        f"{ms:.1f} kg, {d:.0f} mm in {tm:g} s, GT2 20T")
    # --- pneumatics: thrust >= need / 0.7, stroke >= need, piston speed
    bh = L["BOX"][2]
    flange_area = L["BOX"][0] * L["BOX"][1] - (L["BOX"][0] - 2 * L["FLANGE"]) * (L["BOX"][1] - 2 * L["FLANGE"])
    cyls = [
        ("escapement gate", L["ESC_CYL"], L["ESC_F"], L["MAG_ID"] + 3, "retract", None),
        ("stamp", L["STAMP_CYL"], L["STAMP_F"], L["STAMP_CLEAR"], "extend", None),
        ("kicker", L["KICK_CYL"], 5.0, L["KICK_STROKE"], "extend", L["KICK_STROKE"] / L["KICK_T"]),
        ("stacker lift", L["STACK_CYL"], cass_cap() * L["PACK_M"] * G + 4 * L["PAWL_F"], L["PAWL"] + bh, "extend", None),
        ("sealer", L["SEAL_CYL"], L["SEAL_P"] * flange_area, L["SEAL_GAP"], "extend", None),
        ("tray forks", L["FORK_CYL"], 2.0, 6.0, "extend", None),
    ]
    air = 0.0
    per_h = {"escapement gate": 3600 / takt(), "stamp": 3600 / takt(), "kicker": 0.05 * 3600 / takt(),
             "stacker lift": 3600 / takt() / L["PACK"], "sealer": 3600 / takt() / L["PACK"],
             "tray forks": 2 * 3600 / takt() / L["PACK"]}
    for name, (bore, stroke), need, s_need, way, v in cyls:
        f = H.cyl_force(bore, retract=(way == "retract"))
        ok = need <= H.CYL_LOAD_RATIO * f and s_need <= stroke and (v is None or v <= H.CYL_V_MAX)
        row(f"cylinder {name} D{bore}x{stroke}", f"needs {need:.0f} N, {s_need:.0f} mm"
            + (f", {v:.0f} mm/s" if v else ""), f"<= {H.CYL_LOAD_RATIO:.0%} of {f:.0f} N, stroke {stroke}",
            ok, f"ISO 6432 at {H.P_SUPPLY * 10:g} bar ({way})")
        vol = math.pi * bore ** 2 / 4 * stroke * 2 / 1e6          # litres per double stroke
        air += vol * (H.P_SUPPLY * 10 + 1) * per_h[name] / 60     # Nl/min
    air += len(L["DELTA_X"]) * H.EJECTOR["q"] * L["T_GRAB"] / L["T_PICK"]
    air *= 1.1
    row("air consumption", f"{air:.1f} Nl/min (+10 % leakage)", f"<= {H.AIR_DUTY:.0%} of FAD {H.AIR['fad']:g}",
        air <= H.AIR_DUTY * H.AIR["fad"], "the v3 on-table 66 mm toy compressor is gone; ejectors dominate")
    return rows, fails


def reach():
    """Delta IK must solve every pick point in its window and every place point."""
    fails, n = [], 0
    for i, xd, (x, y, z), kind in delta_poses():
        n += 1
        if delta_ik(x, y, z, xd) is None:
            fails.append(f"REACH delta_{'AB'[i]}: {kind} ({x:.0f},{y:.0f},{z:.0f})")
    return fails, n


PASS_THROUGH = {"chain", "frame", "guide", "puck", "cookie", "drive"}


def product_clearance(step=5.0):
    """Sweep the puck + cookie envelope along the whole loop against every
    static part: tunnels, curtains, hood lips, stamp at home, kicker at home,
    deltas at their travel height, sensors, guide brackets."""
    parts = [p for p in build(with_product=False) if p.group not in PASS_THROUGH and p.kind != "arc"]
    boxes = [(p, p.aabb()) for p in parts]
    fails, n = [], 0
    r_p, z_p = L["PUCK"][0] / 2, (L["BELT_Z"], z_puck_top())
    r_c, z_c = L["COOKIE"][0] / 2, (z_seat(), z_cookie_top())
    s = 0.0
    while s < loop_len():
        (x, y), _ = pos(s)
        for p, b in boxes:
            for r, (z0, z1) in ((r_p, z_p), (r_c, z_c)):
                if b[2] < z1 - 0.05 and b[5] > z0 + 0.05 and _circle_box(x, y, r, b):
                    if p.kind == "rod":
                        continue          # rods are checked in 3D by interference()
                    fails.append(f"PRODUCT hits {p.name} at s={s:.0f} ({x:.0f},{y:.0f})")
        n += 1
        s += step
    return sorted(set(fails)), n


def lane_clearance(step=5.0):
    """Sweep a sealed pack (tray + film) along every lane from the magazine to the
    stacker against every static part except the lane itself - the v3 kicker
    cylinder reached 5 mm into lane 1 and no check could see it."""
    parts = [p for p in build(with_product=False)
             if p.group not in ("lane", "tray", "stock", "stacker", "cassette") and "boxmag" not in p.name]
    import geom
    bl, bw, bh = L["BOX"]
    fails, n = [], 0
    for y in L["LANE_Y"]:
        x = L["LANE_X"][0] + 15
        while x + bl <= L["CASS_X"][0] + L["CASS"][0]:
            env = Part("pack", "", "", "box", (x, y - bw / 2, L["LANE_Z"]), (bl, bw, L["TRAY_H"] + 0.6))
            for p in parts:
                if _ovl(env.aabb(), p.aabb()) and geom.interfere(env, p):
                    fails.append(f"LANE pack at y={y:.0f} hits {p.name}")
            n += 1
            x += step
    return sorted(set(fails)), n


# ------------------------------------------------------------ interference
JOINT_PAIRS = (("motor", "shaft"), ("shaft", "upper"), ("upper", "fore"), ("fore", "effector"),
               ("upper", "pin"), ("pin", "fore"))


def allowed(a, b):
    """Declared overlaps: the reason two solids may share volume, or None."""
    A_, B_ = sorted((a.name, b.name))
    for x, y in ((A_, B_), (B_, A_)):
        if y.startswith(x + "_cookie_") and a.group in ("tray", "stock") and b.group in ("tray", "stock"):
            return "contained: cookie in its tray pocket (B-rep proven in line_cad.containment)"
    if A_.startswith("chute_") and B_.startswith("chute_") and A_[:-2] == B_[:-2]:
        return "one Y-diverter chute"
    if a.group == b.group and a.group.startswith("delta_"):
        ka = a.name.split("_")[2]
        kb = b.name.split("_")[2]
        pa = a.name.split("_")[3] if len(a.name.split("_")) > 3 else ""
        pb = b.name.split("_")[3] if len(b.name.split("_")) > 3 else ""
        for u, v in JOINT_PAIRS:
            if {ka, kb} == {u, v} and (pa == pb or "effector" in (ka, kb)):
                return "kinematic joint (clamp hub / ball joint)"
    pair = {a.name.rsplit("_", 1)[0] if a.name[-1].isdigit() else a.name,
            b.name.rsplit("_", 1)[0] if b.name[-1].isdigit() else b.name}
    for u, v, why in (("stamp_spindle", "stamp_bearing", "spindle in its bearing"),
                      ("stamp_spindle", "stamp_nut", "spindle in its nut"),
                      ("stamp_spindle", "stamp_coupling", "spindle in the coupling"),
                      ("stamp_rail", "stamp_block", "MGN block on its rail")):
        if {a.name, b.name} & {u} and any(n.startswith(v) for n in (a.name, b.name)) and u != v:
            return why
    if ("shuttle_rail" in a.name and "shuttle_block" in b.name) or ("shuttle_rail" in b.name and "shuttle_block" in a.name):
        if a.name.split("_")[2] == b.name.split("_")[2]:
            return "MGN block on its rail"
    for u, v in ((a, b), (b, a)):
        if u.name.startswith("stacker_rod_") and v.name == "stacker_frame_" + u.name[12:]:
            return "through-hole: push rod in a clearance hole of the transfer frame (cut in CAD)"
    for u, v in ((a, b), (b, a)):
        if u.name.startswith("singulator_shaft_") and v.name.startswith("singulator_plate_"):
            return "through-hole: gearbox shaft through the motor plate"
        if u.name.startswith("chute_") and not u.name.startswith("chute_stub"):
            f = u.name.split("_")[1]
            if v.name == f"chute_stub_{f}":
                return "chute starts in its outlet stub"
            if v.name == "collar_" + u.name[6:]:
                return "chute end sits in its funnel collar"
    if ("_reel_" in a.name and "_spindle_" in b.name) or ("_reel_" in b.name and "_spindle_" in a.name):
        if a.name.split("_")[1] == b.name.split("_")[1] and a.name[-1] == b.name[-1]:
            return "reel on its spindle"
    return None


def interference(parts=None):
    """Every pair of solids, across AND within modules: share no volume unless
    declared in allowed(). Returns (fails, n_pairs_tested, allowed_used)."""
    import geom
    parts = parts if parts is not None else build(with_product=False)
    fails, used = [], {}
    hits = geom.pairs(parts)
    for a, b, d in hits:
        why = allowed(a, b)
        if why:
            used[why] = used.get(why, 0) + 1
            continue
        fails.append(f"INTERFERE {a.name} x {b.name} ({d:.2f} mm)")
    return sorted(fails), len(hits), used


def moving_clearance():
    """Moving envelopes vs everything: kicker paddle over its stroke, stamp
    carriage + tool over the stroke and down to contact, escapement gates
    (inside their blocks by construction), deltas at every commanded pose."""
    import geom
    allp = build(with_product=False)
    fails = []
    stat = [p for p in allp]
    pad = next(p for p in allp if p.name == "kick_paddle")
    sw = Part("kick_sweep", pad.module, pad.group, "box", (pad.p[0], pad.p[1] - L["KICK_STROKE"], pad.p[2]),
              (pad.s[0], pad.s[1] + L["KICK_STROKE"], pad.s[2]))
    for b in stat:
        if b.name != "kick_paddle" and b.group not in ("chain", "frame") and geom.interfere(sw, b):
            if b.name == "kick_cylinder":
                continue
            fails.append(f"KICK sweep hits {b.name}")
    mov = [p for p in allp if p.joint in ("stamp_x", "stamp_z")]
    for q in mov:
        a = q.aabb()
        down = L["STAMP_CLEAR"] if q.joint == "stamp_z" else 0.0
        sw = Part(q.name + "_sweep", q.module, q.group, "box", (a[0], a[1], a[2] - down),
                  (a[3] - a[0] + L["STAMP_STROKE"], a[4] - a[1], a[5] - a[2] + down))
        for b in stat:
            if b.joint in ("stamp_x", "stamp_z") or b.group in ("chain", "frame", "guide"):
                continue
            if b.name in ("stamp_rail", "stamp_spindle") and q.name in ("stamp_block", "stamp_nut"):
                continue
            if geom.interfere(sw, b):
                fails.append(f"STAMP sweep {q.name} hits {b.name}")
    # deltas at every commanded pose: arms vs every static solid except their own base/motors' joints
    static = [p for p in allp if not (p.group.startswith("delta_") and p.joint)]
    n = 0
    for i, xd, pose, kind in delta_poses():
        arms = []
        _delta(arms.append, f"delta_{'AB'[i]}", xd, pose, static=False)
        for p in arms:
            p.module = "M6_pick"
        for p in arms:
            for b in static:
                if not _ovl(p.aabb(), b.aabb()):
                    continue
                if allowed(p, b):
                    continue
                if kind == "pick" and b.group == "chain":
                    continue
                if p.name.endswith("_cup") and b.group in ("tray", "stock"):
                    continue                 # the cup is IN the pocket when placing (it carries the cookie)
                n += 1
                if geom.interfere(p, b):
                    fails.append(f"DELTA {p.name} at {kind} {tuple(round(v) for v in pose)} hits {b.name}")
    return sorted(set(fails)), n


def grid():
    """Every static part's placement on the 0.1 mm grid (min corner, or centre
    for a bought envelope centred on an axis). Moving poses (IK) are exempt."""
    fails = []
    for p in build(with_product=False):
        if p.joint and p.group.startswith("delta_"):
            continue
        if p.kind == "arc":
            vals = list(p.p) + list(p.s[:3])
            ok = all(abs(v * 10 - round(v * 10)) < 1e-6 for v in vals)
        elif p.kind == "rod":
            vals = list(p.p) + list(p.s[:3])
            ok = all(abs(v * 10 - round(v * 10)) < 1e-6 for v in vals) or p.group.startswith("delta_")
        else:
            b = p.aabb()
            ok = True
            for i in range(3):
                lo_ok = abs(b[i] * 10 - round(b[i] * 10)) < 1e-6
                c = (b[i] + b[i + 3]) / 2
                c_ok = abs(c * 10 - round(c * 10)) < 1e-6
                ok = ok and (lo_ok or c_ok)
        if not ok:
            fails.append(f"GRID {p.name} off the 0.1 mm grid: p={tuple(round(v, 4) for v in p.p)}")
    return fails


def contact():
    """The die lands exactly on the cookie top; the cup on the cookie top."""
    fails = []
    die = next(p for p in build(with_product=False) if p.name == "stamp_die")
    if abs(die.p[2] - L["STAMP_CLEAR"] - z_cookie_top()) > 1e-6:
        fails.append("CONTACT stamp die does not land on the cookie top")
    if abs(pick_z() - L["CUP_L"] - z_cookie_top()) > 1e-6:
        fails.append("CONTACT delta cup tip != cookie top at the pick height")
    return fails


def check(verbose=True):
    rows, fails = timing()
    srows, sfails = sizing()
    rf, n_reach = reach()
    pf, n_sweep = product_clearance()
    lf, n_lane = lane_clearance()
    inf, n_int, used = interference()
    mf, n_mov = moving_clearance()
    gf = grid()
    fails = fails + sfails + rf + pf + lf + inf + mf + gf + contact()
    if verbose:
        print(f"STF-2 continuous line: {len(build())} parts, loop {loop_len():.1f} mm, "
              f"S = {straight():.1f} mm, takt {takt():.2f} s")
        for name, v, lim, ok, note in rows + srows:
            print(f"  [{'ok' if ok else 'FAIL'}] {name:36s} {v:45s} {lim:38s} {note}")
        print(f"  delta reach radius at pick height: {delta_reach_radius():.1f} mm; "
              f"{n_reach} pick/place points solved by IK")
        print(f"  product envelope swept along the loop: {n_sweep} stations of 5 mm; "
              f"packs swept along the lanes: {n_lane} stations")
        print(f"  interference: {n_int} touching/overlapping candidate pairs, allowed by declaration: "
              + ", ".join(f"{v} x {k}" for k, v in used.items()))
        print(f"  moving envelopes: kicker, stamp, deltas at {len(delta_poses())} poses ({n_mov} exact pair tests)")
        print("\n".join(fails) if fails else
              "ALL CHECKS PASS (timing, sizing, reach, product + lane sweep, interference, motion, grid, contact)")
    return fails


if __name__ == "__main__":
    import sys
    sys.exit(1 if check() else 0)
