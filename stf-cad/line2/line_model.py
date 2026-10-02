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
import oven as OV

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
    COOKIE=(45.0, 8.0), COOKIE_M=0.012,      # BAKED base cookie D [ft] x H, kg incl. topping (oven.simulate)
    FLAVOURS=("weiss", "rot", "blau"),       # vanilla / strawberry / chocolate (sorting-line bins)
    MIX=(1, 1, 1),                           # demand ratio -> heijunka sequence W R B W R B ...
    RAW="#ecddbe", BAKED=("#f7f1e1", "#c8233c", "#3b2112"),   # dough colour; TOPPING colour of each flavour
    # ---- M2 depositor + topping (2026-10-02, oven.py). ONE plain dough for every cookie; the flavour is a drop
    # of vanilla cream / strawberry jam / chocolate in a thumbprint well, put onto the raw slug BEFORE the oven
    # (industrial thumbprint-cookie practice). 6 band rows: row k carries flavour k mod 3 -> the transfer
    # delta picks a row in order and the heijunka sequence W R B W R B comes out by itself.
    DOUGH_SLUG=(38.0, 12.0), DOUGH_M=0.0112,  # wire-cut slug D x H, kg; spreads to COOKIE in the oven [assumed]
    DOUGH=dict(w0=0.18, cp_dry=1600.0, k_wet=0.40, k_dry=0.12,      # water (wet basis), J/kgK, W/mK      [typ]
               h_contact=150.0, contact_frac=0.3, eps=0.9,           # band contact W/m2K on 30 % of the base
               brown_Ea=1.2e5, brown_Tref=165.0, brown_t=150.0,      # Maillard: J/mol, C, s to golden at Tref
               rgb_raw=(236, 221, 190), rgb_baked=(205, 150, 80), rgb_dark=(110, 62, 28)),   # [assumed]
    TOPPING=dict(d=14.0, h=1.0, m=0.0015),   # drop D in its well, dome above the cookie top, kg     [assumed]
    DEP_DROP=5.0,                            # die underside above the slug top (the wire cuts there)
    DEP_ROLL=50.0, DEP_HOPPER=(190.0, 300.0),   # feed roll D; dough hopper length x height        [assumed]
    DEP_HOPPER_Y0=44.0,                      # hopper front wall: under the raw pour strip (AMR tips the tub)
    DEP_GRID=40.0,                           # safety grid in the hopper: square mesh e (ISO 13857 Table 4)
    DOUGH_KG=15.0, DOUGH_RHO=1150.0,         # kg dough when full (fill <= 80 %), kg/m3            [assumed]
    TOP_HOPPER=(80.0, 220.0), TOP_KG=0.8, TOP_RHO=1300.0,   # topping hopper D x H, kg full, kg/m3 [assumed]
    MAX_H=900.0,                             # user: "taller is fine" - nothing above this
    TOP_CYL=(16, 25), TOP_F=20.0,            # dosing piston (ISO 6432); N to push 2 drops through [assumed]
    DEP_T=2.0,                               # Nm at the feed rolls to extrude a row          [assumed, MEASURE]
    # ---- M3 band oven + band cooling (oven.py sizes it): a stainless mesh band, NOT the puck chain, goes
    # through the heat; plain steel, glass-fibre and mineral wool are the only materials in the chamber
    BAND=dict(rows=6, spacing=55.0, edge=20.0, m_area=2.5,         # rows across, mm pitch, kg/m2 mesh  [typ]
              z=240.0, yc=370.0, drum=100.0, x0=110.0),            # carry-run top, centre line, drum D, feed drum x
    T_AMB=25.0,                              # air inside the guard next to the oven              [assumed]
    OVEN_ZONES=[dict(T=210.0, dT_rad=40.0), dict(T=200.0, dT_rad=30.0), dict(T=185.0, dT_rad=20.0)],  # recipe
    OVEN_H=dict(top=70.0, bot=45.0),         # W/m2K: impingement fan per zone (top), through the mesh (bottom)
    BAKE_Q=dict(core_min=95.0, core_hold=60.0, w_end=0.05, colour=(0.8, 1.3), T_burn=200.0),   # baked =
    BAKE_MARGIN=2.0,                         # K: the bake must hold with every zone this far off its set point -
                                             # the browning roughly doubles per 8-10 K, so +-2 K is what the colour
                                             # window allows; oven_ctrl proves the zones hold it
    COOLING=dict(band=dict(h_top=90.0, h_bot=70.0),                  # impingement hood: down through the mesh
                 loop=dict(h_top=10.0, h_bot=2.0)),                  # still air on the puck
    T_TRANSFER=40.0, T_PACK=38.0,            # C: max anywhere in the cookie at the pick-up / at the sealer
    CHAMBER=dict(side_gap=20.0, h_inner=140.0, insul=50.0, insul_mat="mineral wool", h_out=9.0, mouth_h=45.0,
                 mouth_F=0.5, mouth_Cd=0.6, skin_t=0.8, m_fixed=1.5),   # mouth = band underside .. +45
    X_EXHAUST=0.05,                          # kg water per kg exhaust air                         [typ]
    HEADROOM=0.7, TOP_SHARE=0.6,             # steady load <= 70 % installed; top elements' share
    WARMUP_MAX=1800.0, SKIN_MAX=55.0,        # s cold start; outer skin C (EN ISO 13732-1, metal 10 s) [typ]
    OVEN_GAP=50.0, COOL_GAP=40.0, NOSE_GAP=150.0,   # topping -> inlet wall, outlet wall -> hood, hood -> drum
    DEP_DX=80.0, TOP_DX=100.0,               # feed drum -> depositor die, die -> topping nozzles
    # ---- M4 transfer: delta C picks every cookie off the band end and places it into a passing puck on the
    # right bend (the band cannot stop: a miss falls into the catch tray - counted, never a stop)
    DELTA_C=dict(x=1640.0, y=440.0, z=720.0, rot=60.0, l1=200.0, l2=440.0), PICK_W=70.0,   # base centre; band pick window (mm)
    CUP_OFF=14.0, CUP_D=12.0,                # twin cups off centre: they straddle the topping drop
    # ---- M5 vision QC + reject
    QC_X=(1360.0, 1500.0), CAM_X=1420.0, CS_X=1470.0, SENSOR_GAP=25.0,   # colour sensor at the hood entry (its mount clears the ring light)
    AI_LATENCY=0.50,                         # s, camera -> verdict budget            [assumed]
    KICK_X=1310.0, KICK_STROKE=100.0, KICK_T=0.20, KICK_W=40.0, KICK_CYL=(10, 100), KICK_Z=130.0,
    FUNNEL=(70.0, 70.0),
    # ---- M6 pick & place: two delta robots, each alone faster than the takt
    DELTA_X=(910.0, 590.0),                 # A (upstream on the back run), B
    DELTA_Y=905.0, DELTA_Z=498.0,            # base (shoulder plane): 12 lower for the 8 mm cookie
    DELTA_RB=70.0, DELTA_RE=30.0, DELTA_L1=130.0, DELTA_L2=300.0,
    DELTA_LIM=(-60.0, 90.0),                 # shoulder limits (deg, + = arm down)
    DELTA_ROT=(-15.0, 165.0),                # arm set rotation: the 90 deg arm/motor gap faces the other delta
    CUP_L=40.0, TRAVEL_Z=238.0,              # effector underside -> cup tip; home/travel height
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
    STACK_PLATE_W=30.0,                                   # lift plate width: it rises between the twin strands
    BOXMAG_X=(160.0, 330.0), BOXMAG_CAP=60, BOX_NEST=8.0, FORK_CYL=(8, 10),
    # rejects: chute through the table deck into a drawer bin under the table
    REJECT_BIN=(1255.0, 480.0, 240.0, 240.0, 290.0),     # x, y, w, d, h (below the deck); S-1c: 30 mm back
                                                          # so the bin covers the whole deck hole
    FUNNEL_OUT=50.0,                                      # square outlet of the funnel = the hole in the deck
    REJECT_GAP=10.0,                                      # bin top below the deck underside (the shutter's room)
    PACKING=0.50,                                         # bulk packing fraction of loose cookies  [assumed]
    # AMR service (the stock is finite; the AMR loop is what makes it unlimited)       [assumed]
    N_AMR=2, AMR_TRIP=60.0, AMR_HANDLE=30.0,
    REQ_HOPPER=0.35, REQ_BOXMAG=0.50, REQ_REJECT=0.70,
    # ---- M8 control: Beckhoff enclosure UNDER the deck; air from an off-table compressor
    CAB=(250.0, 300.0, 980.0, 850.0, 210.0),             # x, y, w, d, h of the enclosure under the deck
                                                          # (S-1: +TwinSAFE rail, contactors, STLs -> grown;
                                                          #  2026-10-02: + element SSRs, zone contactors -> 850)
                                                          # (sized by plc_io.cabinet(); clear of the reject bin)
    ISLAND_XY=(700.0, 480.0), FRL=(60.0, 60.0, 90.0),
    VALVE_SPARE=0.2,                                      # >= 20 % spare valve stations
    # ---- Upgrade PA-1 (physical AI): every actuator reports back, sensing where decisions happen
    PA1=True,
    LANE_MOTOR="17HS19-2004D-E1000", SHUTTLE_MOTOR="17HS19-2004D-E1000",
    TRANSFER_TH=(-36.0, -16.0, 14.0), PLACE_TH=(-30.0, -2.0),                    # bend angles: I1 full-puck check, place, I9 landing
    PACK_CAM=(1070.0, 960.0, 578.0),                      # CAM4 over the three lanes, before the sealer
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
    UNLOCK_STILL=2.5,                                     # s of standstill before a door unlocks (SF2): covers the
                                                          # oven fan rundown, the fans have no encoder
    FAN_RUNDOWN=2.0,                                      # s, oven impeller coast-down after KHn drops [assumed, MEASURE]
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


def dough_rate():
    """kg/s of dough at one cookie per takt."""
    return L["DOUGH_M"] / takt()


def dough_autonomy():
    """s of production in a full dough hopper."""
    return L["DOUGH_KG"] / dough_rate()


def topping_autonomy():
    """s of production in a full topping hopper (each flavour feeds a third of the cookies)."""
    return L["TOP_KG"] / (L["TOPPING"]["m"] * rate_flavour())


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


# ------------------------------------------------------------ band oven (oven.py does the physics)
def band_v():
    """Band speed: one row of BAND rows cookies per BAND rows takts."""
    B = L["BAND"]
    return B["spacing"] / (B["rows"] * takt())


def band_w():
    B = L["BAND"]
    return B["rows"] * B["spacing"] + 2 * B["edge"]


def band_y():
    yc = L["BAND"]["yc"]
    return yc - band_w() / 2, yc + band_w() / 2


def row_y(k):
    B = L["BAND"]
    return band_y()[0] + B["edge"] + B["spacing"] / 2 + k * B["spacing"]


def row_flavour(k):
    return k % len(FLAV)


def bake_t():
    t = OV.bake_time(L)
    if t is None:
        raise ValueError("oven.bake_time: the recipe burns before it bakes - no band length exists")
    return t


def band_gaps():
    """(s of still air from the last zone to the hood, s from the hood end to the pick window start)."""
    v = band_v()
    return (L["CHAMBER"]["insul"] + L["COOL_GAP"]) / v, (L["NOSE_GAP"] - L["PICK_W"]) / v


def cool_t():
    t = OV.cool_time(L, bake_t(), *band_gaps())
    if t is None:
        raise ValueError("oven.cool_time: the band cooling never reaches T_TRANSFER")
    return t


def zone_len():
    """Length of one heated zone (whole mm): the band speed x the bake time / zones."""
    return float(math.ceil(band_v() * bake_t() / len(L["OVEN_ZONES"])))


def cool_len():
    return float(math.ceil(band_v() * cool_t()))


def stations():
    """x of every station along the band (flow +X): feed drum, depositor die, topping nozzles, chamber outer
    faces, zone starts, cooling hood, pick window, discharge drum."""
    ins = L["CHAMBER"]["insul"]
    x0 = L["BAND"]["x0"]
    dep = x0 + L["DEP_DX"]
    top = dep + L["TOP_DX"]
    o0 = top + L["OVEN_GAP"]
    zl = zone_len()
    zs = [o0 + ins + k * zl for k in range(len(L["OVEN_ZONES"]))]
    o1 = zs[-1] + zl + ins
    c0 = o1 + L["COOL_GAP"]
    c1 = c0 + cool_len()
    e = c1 + L["NOSE_GAP"]
    return dict(x0=x0, dep=dep, top=top, o0=o0, zones=zs, o1=o1, c0=c0, c1=c1, pick=(e - L["PICK_W"], e), e=e)


def chamber_z():
    """z levels of the band unit (bottom up)."""
    zb = L["BAND"]["z"]
    t = H.BAND_MESH["t"]
    ins = L["CHAMBER"]["insul"]
    r = L["BAND"]["drum"] / 2
    zc = zb - t - r                                       # drum axis: the carry run lies on its top
    f1 = zb - 45.0                                        # floor inner face
    return dict(band=zb, under=zb - t, drum=zc, ret=(zc - r - t, zc - r), pan=(zc - r - t - 7.0, zc - r - t),
                floor=(f1 - ins, f1), roof=(f1 + L["CHAMBER"]["h_inner"], f1 + L["CHAMBER"]["h_inner"] + ins),
                el_bot=zb - 30.0, el_top=zb + 60.0, mouth=(zb - t - 5.0, zb - t - 5.0 + L["CHAMBER"]["mouth_h"]),
                skid=(zb - t - 6.0, zb - t))


def chamber_y():
    yb0, yb1 = band_y()
    g, ins = L["CHAMBER"]["side_gap"], L["CHAMBER"]["insul"]
    return dict(i0=yb0 - g, i1=yb1 + g, o0=yb0 - g - ins, o1=yb1 + g + ins)


def oven_power():
    """(zone loads, elements, phase plan, warm-up) from oven.py at the production rate."""
    st = stations()
    loads = OV.zone_loads(L, bake_t(), band_w(), band_v(), 1 / takt())
    cy = chamber_y()
    els = OV.elements(L, loads, cy["i1"] - cy["i0"])
    fans = [(f"QF{k + 1}", H.OVEN_FAN["P"]) for k in range(len(L["OVEN_ZONES"]))]
    plan = OV.phase_plan(L, els, fans)
    warm = OV.warmup(L, loads, els, band_w())
    return loads, els, plan, warm


def element_x(zone_k, face):
    """x of every element of a zone face, evenly spaced; top elements leave the zone centre to the fan."""
    els = [e for e in oven_power()[1] if e["zone"] == f"Z{zone_k + 1}" and e["face"] == face]
    zl = zone_len()
    x0 = stations()["zones"][zone_k]
    n = len(els)
    xs = [g1(x0 + (i + 0.5) * zl / n) for i in range(n)]
    return list(zip(els, xs))


def bend_s(theta):
    """Loop arc length of the right bend at angle theta (deg, -90 = start of the bend)."""
    return straight() + L["R"] * math.radians(theta + 90.0)


def bend_xy(theta, r=None):
    (crx, cry) = centres()[1]
    r = L["R"] if r is None else r
    return crx + r * math.cos(math.radians(theta)), cry + r * math.sin(math.radians(theta))


def delta_window(xd):
    """Belt length under a delta's reach circle at pick height, and its time."""
    r = delta_reach_radius()
    dy = abs(L["DELTA_Y"] - y_back())
    if dy >= r:
        return 0.0, 0.0
    c = 2 * math.sqrt(r * r - dy * dy)
    return c, c / L["V"]


# ------------------------------------------------------------ delta kinematics
def _dbase(xd):
    """(y, z, rot) of the delta whose base centre is at x = xd: A/B on the portal, C over the band end."""
    c = L["DELTA_C"]
    if xd == c["x"]:
        return c["y"], c["z"], c["rot"]
    return L["DELTA_Y"], L["DELTA_Z"], (L["DELTA_ROT"][L["DELTA_X"].index(xd)] if xd in L["DELTA_X"] else 0.0)


def _darms(xd):
    """(rb, re, l1, l2) of the delta at xd: C has longer arms (the band row + the drop to the pucks)."""
    c = L["DELTA_C"]
    if xd == c["x"]:
        return L["DELTA_RB"], L["DELTA_RE"], c["l1"], c["l2"]
    return L["DELTA_RB"], L["DELTA_RE"], L["DELTA_L1"], L["DELTA_L2"]


def arm_angles(xd):
    """The three arm plane angles of the delta at xd (rotated by DELTA_ROT so the
    wide gap between arms and motor bodies faces the neighbouring delta)."""
    rot = _dbase(xd)[2]
    return tuple(rot + k * 120.0 for k in range(3))


def delta_ik(x, y, z, xd):
    """Shoulder angles (deg, + = down) for effector centre (x,y,z) of delta
    whose base centre is (xd, _dbase). None if unreachable/limited."""
    rb, re, l1, l2 = _darms(xd)
    yd, zd, _ = _dbase(xd)
    X, Y, Z = x - xd, y - yd, z - zd
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
    rb, re, l1, _ = _darms(xd)
    yd, zd, _ = _dbase(xd)
    pts = []
    for phi, th in zip(arm_angles(xd), ang):
        c, s = math.cos(math.radians(phi)), math.sin(math.radians(phi))
        sh = (xd + rb * c, yd + rb * s, zd)
        r_el = rb + l1 * math.cos(math.radians(th))
        el = (xd + r_el * c, yd + r_el * s, zd - l1 * math.sin(math.radians(th)))
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


def band_pick_z():
    """Delta C effector underside when the cups touch a cookie on the band."""
    return L["BAND"]["z"] + L["COOKIE"][1] + L["CUP_L"]


def travel_z(xd):
    """Home / travel height of the delta at xd: A/B over the lanes, C between the band and the bend."""
    return L["TRAVEL_Z"] if xd != L["DELTA_C"]["x"] else band_pick_z() + 20.0


def delta_c_poses():
    """Delta C: every row position in the band pick window (pick + travel) and the place window on the bend."""
    out = []
    xc = L["DELTA_C"]["x"]
    p0, p1 = stations()["pick"]
    for x in (p0 + 2, (p0 + p1) / 2, p1 - 2):
        for k in range(L["BAND"]["rows"]):
            for z in (band_pick_z(), travel_z(xc)):
                out.append((2, xc, (x, row_y(k), z), "pick"))
    a, b = L["PLACE_TH"]
    for i in range(7):
        th = a + (b - a) * i / 6
        x, y = bend_xy(th)
        for z in (pick_z(), travel_z(xc)):
            out.append((2, xc, (x, y, z), "place"))
    return out


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
    return out + delta_c_poses()


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


PHASE_RGB = {"L1": "#7a4a1d", "L2": "#1c1c1c", "L3": "#8d9399"}     # IEC 60445: brown / black / grey


def transfer_times():
    """(t_enter, s_place): a row enters the pick window t_enter s after its deposit; delta C picks cookie k of
    a row at t_dep + t_enter + (k+1) takt and places it 1 s later into the puck that is then at s_place
    (inside PLACE_TH) - the same phase every takt, because the band is geared to the chain."""
    st = stations()
    t_enter = (st["pick"][0] - st["dep"]) / band_v()
    s0 = bend_s(L["PLACE_TH"][0] + 2.0)
    t_pl = t_enter + 1.0
    return t_enter, s0 + ((L["V"] * t_pl - s0) % L["PITCH"])


def _pucks(A, t=0.0):
    """Carriers on the loop at time t with the nominal steady-state content: a baked base + its topping drop
    from the transfer place point to the picker."""
    Lp = loop_len()
    load_s = transfer_times()[1]
    pick_s = s_back(L["DELTA_X"][1]) + 80
    d, h = L["PUCK"]
    T = L["TOPPING"]
    for k in range(L["N"]):
        s = (k * L["PITCH"] + L["V"] * t) % Lp
        (x, y), _ = pos(s)
        A(Part(f"puck_{k:02d}", "loop", "puck", "cyl", (x, y, L["BELT_Z"]), ("z", h, d), "#1f63c4",
               joint="loop", tag="NFC", note="carrier with NFC tag (recipe + state)"))
        if load_s <= s < pick_s:
            f = k % 3
            A(Part(f"cookie_{k:02d}", "loop", "cookie", "cyl", (x, y, z_seat()),
                   ("z", L["COOKIE"][1], L["COOKIE"][0]), cookie_hex(), joint="loop", note=FLAV[f]))
            A(Part(f"cookie_{k:02d}_top", "loop", "cookie", "cyl", (x, y, z_cookie_top()), ("z", T["h"], T["d"]),
                   L["BAKED"][f], joint="loop", note=f"{FLAV[f]} topping"))


def cookie_hex():
    """Colour of a fully baked base (oven.py colour index at the oven exit)."""
    _, s = OV.simulate(L, OV.bake_segments(L, bake_t()), record=1e9)
    return OV.colour_hex(L, s["colour"], s["moisture"])


def band_state(t_in):
    """(D, H, colour hex, topped) of the product t_in s after it was deposited (oven.py profile + spread)."""
    st = stations()
    v = band_v()
    t_top = (st["top"] - st["dep"]) / v
    t_oven = (st["o0"] + L["CHAMBER"]["insul"] - st["dep"]) / v
    (d0, h0), (d1, h1) = L["DOUGH_SLUG"], L["COOKIE"]
    if t_in <= t_oven:
        return d0, h0, L["RAW"], t_in >= t_top
    tb = t_in - t_oven
    tr = band_trace()
    i = min(int(tb), len(tr) - 1)
    row = tr[i]
    f = min(1.0, tb / (bake_t() / len(L["OVEN_ZONES"])))        # the slug spreads in the first zone
    return d0 + (d1 - d0) * f, h0 + (h1 - h0) * f, OV.colour_hex(L, row[6], row[5]), True


_TRACE = {}


def band_trace():
    """Per-second product history from the oven inlet to the band end (oven.profile)."""
    k = OV._key(L)
    if k not in _TRACE:
        _TRACE[k] = OV.profile(L, bake_t(), cool_t(), record=1.0, t_gap=band_gaps()[0], t_nose=band_gaps()[1])[0]
    return _TRACE[k]


def _band_product(A, t=0.0):
    """Every row on the band at time t: slugs, topped slugs, baking / cooling cookies up to the pick window
    (delta C empties a row in 6 takts inside it)."""
    st = stations()
    v, sp = band_v(), L["BAND"]["spacing"]
    zb = L["BAND"]["z"]
    T = L["TOPPING"]
    period = sp / v
    n_rows = int((st["pick"][1] - st["dep"]) // sp) + 1
    for j in range(n_rows):
        t_in = (t % period) + j * period                     # row j was deposited t_in s ago
        r = int(round((t - t_in) / period))                  # deposit index: the row's name for its whole life
        x = st["dep"] + v * t_in
        if x > st["pick"][1]:
            continue
        d, h, col, topped = band_state(t_in)
        picked = 0
        if x >= st["pick"][0]:                               # delta C takes one cookie per takt, row order
            picked = min(L["BAND"]["rows"], int((x - st["pick"][0]) / (v * takt())))
        for k in range(picked, L["BAND"]["rows"]):
            y = row_y(k)
            nm = f"band_r{r + 100:03d}_{k}"
            A(Part(nm, "oven", "cookie", "cyl", (g1(x), y, zb), ("z", round(h, 2), round(d, 2)), col, joint="band",
                   note=f"{FLAV[row_flavour(k)]}, {t_in:.0f} s on the band"))
            if topped:
                A(Part(nm + "_top", "oven", "cookie", "cyl", (g1(x), y, zb + round(h, 2)), ("z", T["h"], T["d"]),
                       L["BAKED"][row_flavour(k)], joint="band", note="topping drop"))


def raw_strip():
    """(x0, x1, rim z) of the AMR pour strip: over the dough hopper and the three topping hoppers."""
    hl, hh = L["DEP_HOPPER"]
    xs = top_hopper_x()
    td, th = L["TOP_HOPPER"]
    return dep_hopper_x0(), xs[-1] + td / 2 + 10, min(dep_z()["hopper"] + hh, top_z() + th)


def dep_hopper_x0():
    """The dough hopper reaches 60 mm past the die downstream, the rest upstream (clear of the topping pistons)."""
    return stations()["dep"] + 60.0 - L["DEP_HOPPER"][0]


def dep_z():
    zb = L["BAND"]["z"]
    die = zb + L["DOUGH_SLUG"][1] + L["DEP_DROP"]
    roll = L["DEP_ROLL"]
    return dict(die=die, housing=(die + 15.0, die + 15.0 + roll + 70.0), roll=die + 15.0 + roll / 2 + 2.0,
                hopper=die + 15.0 + roll + 70.0)


def top_hopper_x():
    o0 = stations()["o0"]
    td = L["TOP_HOPPER"][0]
    return [o0 + 40 + td / 2 + k * (td + 10) for k in range(len(FLAV))]


def top_z():
    """Underside of the topping hoppers (on their rack plate)."""
    return dep_z()["hopper"] + 50.0


def _depositor(A):
    """M2: plain-dough wire-cut depositor (6 dies across the band) + thumbprint topping depositor (3 flavours,
    each feeding 2 rows). Both hang on brackets on the band's in-feed side plates."""
    st = stations()
    cy = chamber_y()
    dz = dep_z()
    dep, top = st["dep"], st["top"]
    zb = L["BAND"]["z"]
    roll = L["DEP_ROLL"]
    hw_ = roll + 2.0 + 10.0                                    # housing half length in x (rolls + wall)
    yi0, yi1 = cy["i0"], cy["i1"]
    SS = "#c9ced2"
    A(Part("dep_die", "depositor", "depositor", "box", (dep - hw_, yi0, dz["die"]), (2 * hw_, yi1 - yi0, 15.0), SS,
           hw="die plate, 6 orifices D38 (stainless)",
           note="the dough is pressed through 6 orifices; the wire cuts a slug per row at the die face"))
    A(Part("dep_wire", "depositor", "depositor", "box", (dep - 40.0, band_y()[0], dz["die"] - 2.0),
           (80.0, band_w(), 2.0), "#5b6168", joint="wire_x", hw="wire-cut frame (cam-driven by the roll drive)",
           note=f"cuts a {L['DOUGH_SLUG'][1]:g} mm slug per row; the slug falls {L['DEP_DROP']:g} mm onto the band"))
    z0, z1 = dz["housing"]
    hollow(A, "dep_housing", "depositor", "depositor", dep - hw_, yi0, z0, 2 * hw_, yi1 - yi0, z1 - z0, 10.0, SS,
           bottom=False, hw="roll housing (stainless)", note="two counter-rotating feed rolls over the die")
    for k, sx in enumerate((-1, 1)):
        A(Part(f"dep_roll_{k}", "depositor", "depositor", "cyl", (dep + sx * (roll / 2 + 1.0), yi0 + 10.0, dz["roll"]),
               ("y", yi1 - yi0 - 20.0, roll), "#9aa3ab", mech="spin:roll", hw="fluted feed roll D60 (stainless)"))
    nema(A, "M_dep_rolls", "depositor", "depositor", "y", yi1, (dep, dz["roll"]), "PG27", "17HS19-2004D-E1000",
         tag="Q41", sign=1, note="feed rolls + wire cam: one slug per row, geared to the band (EL7047)")
    hl, hh = L["DEP_HOPPER"]
    y0 = L["DEP_HOPPER_Y0"]
    hx0 = dep_hopper_x0()
    hollow(A, "dep_hopper", "depositor", "hopper", hx0, y0, dz["hopper"], hl, yi1 - y0, hh, 3.0, SS,
           hw="dough hopper 3 mm stainless",
           note=f"plain dough, {L['DOUGH_KG']:g} kg = {dough_autonomy() / 60:.0f} min; the AMR tips a tub "
                f"through the pour strip; throat into the roll housing")
    gz = dz["roll"] + roll / 2 + H.iso13857_distance(L["DEP_GRID"], "square") + 10.0
    A(Part("dep_hopper_grid", "depositor", "hopper", "box", (hx0 + 3.0, y0 + 3.0, g1(gz)), (hl - 6.0, yi1 - y0 - 6.0, 5.0),
           "#9aa3ab", hw=f"safety grid {L['DEP_GRID']:g} mm square mesh (stainless, welded in)",
           note="the dough passes, a hand does not reach the feed rolls (ISO 13857 Table 4)"))
    A(Part("dep_hopper_level", "depositor", "sensor", "box", (hx0 + hl / 2 - 20.0, yi1, dz["hopper"] + hh - 24.0),
           (40.0, 20.0, 24.0), "#1b8f52", tag="IOL1", hw="tof_level",
           note=f"dough level -> AMR refill at {L['REQ_HOPPER']:.0%}"))
    for nm, xc, zt_ in (("dep", dep, dz["die"]), ):
        for side, yy in (("f", yi0 - 8.0), ("b", yi1)):
            for k, dx in enumerate((-hw_, hw_ - 30.0)):
                A(Part(f"dep_bracket_{side}{k}", "depositor", "depositor", "box", (xc + dx, yy, zb - 5.0),
                       (30.0, 8.0, zt_ - zb + 5.0 + 15.0), "#9aa3ab", hw="Al bracket 8 mm",
                       note="carries the die / housing on the band side plate"))
    # topping: one manifold across the band, a dosing piston per flavour, 6 nozzles (rows k, k+3 = flavour k)
    zm = zb + L["DOUGH_SLUG"][1] + 10.0
    A(Part("top_manifold", "depositor", "topping", "box", (top - 20.0, yi0, zm), (40.0, yi1 - yi0, 30.0), SS,
           hw="topping manifold, 6 nozzles (stainless)",
           note="each nozzle presses the thumbprint well and leaves one drop; rows k and k+3 get flavour k"))
    for side, yy in (("f", yi0 - 8.0), ("b", yi1)):
        A(Part(f"top_bracket_{side}", "depositor", "topping", "box", (top - 20.0, yy, zb - 5.0), (40.0, 8.0, zm - zb + 5.0 + 30.0),
               "#9aa3ab", hw="Al bracket 8 mm", note="carries the manifold on the band side plate"))
    bore, stroke = L["TOP_CYL"]
    for f in range(len(FLAV)):
        y = (row_y(f) + row_y(f + 3)) / 2
        cyl6432(A, f"top_cyl_{FLAV[f]}", "depositor", "topping", bore, stroke, "z", zm + 30.0, (top, y), +1,
                tag=f"Q{2 + f}", note=f"{FLAV[f]} dosing piston: one stroke = 2 drops of {L['TOPPING']['m'] * 1000:g} g")
    # topping hoppers on a rack in front of the oven inlet, under the pour strip
    td, th = L["TOP_HOPPER"]
    xs = top_hopper_x()
    zr = top_z()
    yh = L["DEP_HOPPER_Y0"] + 6.0 + td / 2
    xr0, xr1 = xs[0] - td / 2 - 10, xs[-1] + td / 2 + 10
    A(Part("top_rack", "depositor", "topping", "box", (xr0, yh - td / 2 - 6, zr - 10), (xr1 - xr0, td + 12, 10.0),
           "#9aa3ab", hw="Al plate 10 mm", note="topping hopper rack"))
    for k, px in enumerate((xr0, xr1 - 30.0)):
        A(Part(f"top_rack_post_{k}", "depositor", "topping", "box", (px, yh - 48.0, 0.0), (30.0, 30.0, zr - 10),
               "#d6d9da", mech="profile:3030", hw="HFS8-3030"))
    for f, xh in enumerate(xs):
        A(Part(f"top_hopper_{FLAV[f]}", "depositor", "topping", "cyl", (xh, yh, zr), ("z", th, td), L["BAKED"][f],
               hw="topping hopper (heated jacket for chocolate)",
               note=f"{FLAV[f]} topping, {L['TOP_KG']:g} kg = {topping_autonomy() / 60:.0f} min; AMR refill"))
        A(Part(f"top_level_{FLAV[f]}", "depositor", "sensor", "box", (xh - 10.0, yh + td / 2, zr + th - 24.0),
               (20.0, 20.0, 24.0), "#1b8f52", tag=f"IOL{5 + f}", hw="tof_level", note="topping level"))
        xm = top - 14.0 + 14.0 * f
        yf_ = yh - 10.0 + 12.0 * f                             # staggered so the runs never cross
        zl_ = chamber_z()["roof"][1] + 20.0                     # over the oven roof, under the rack
        pts = [(xh, yf_, zr - 10.0), (xh, yf_, zl_), (xm, yf_, zl_), (xm, yi0 + 12.0, zm + 30.0)]
        for j in range(3):
            A(Part(f"top_hose_{FLAV[f]}_{'abc'[j]}", "depositor", "topping", "rod", pts[j], (*pts[j + 1], 10.0),
                   "#d9eef7", hw="food hose D10", note="hopper outlet -> over the oven roof -> manifold top" if j == 0 else ""))


def _oven(A):
    """M3: the band unit - mesh band on two drums, insulated 3-zone chamber (tubular elements top + bottom,
    impingement fan, duplex thermocouple per zone), impingement cooling hood, crumb pan; oven.py sizes it."""
    st = stations()
    cz, cy = chamber_z(), chamber_y()
    ins = L["CHAMBER"]["insul"]
    B = L["BAND"]
    yb0, yb1 = band_y()
    o0, o1 = st["o0"], st["o1"]
    x0, xe = st["x0"], st["e"]
    r = B["drum"] / 2
    t = H.BAND_MESH["t"]
    SKIN, SS = "#c2c7cc", "#c9ced2"
    pan = (x0, xe + r + 10.0)                                    # the pan reaches past the nose: misses land in it
    # ---- band, drums, shafts, bearings, drive
    A(Part("band_carry", "oven", "band", "box", (x0, yb0, cz["under"]), (xe - x0, band_w(), t), "#8b9196",
           mech="belt:band", hw="BAND_MESH", note=f"{band_v():.2f} mm/s = one row of {B['rows']} per {B['rows']} takts"))
    A(Part("band_return", "oven", "band", "box", (x0, yb0, cz["ret"][0]), (xe - x0, band_w(), t), "#8b9196",
           mech="belt:band", hw="BAND_MESH", note="returns outside the chamber, on the crumb pan"))
    for nm, xd in (("feed", x0), ("drive", xe)):
        A(Part(f"drum_{nm}", "oven", "band", "cyl", (xd, yb0 - 10.0, cz["drum"]), ("y", band_w() + 20.0, B["drum"]),
               "#9aa3ab", mech="spin:band", hw=f"band drum D{B['drum']:g} (stainless, crowned)",
               note="tension drum (screw take-up)" if nm == "feed" else "drive drum"))
        ys0, ys1 = cy["i0"] - 8.0 - 25.0, cy["i1"] + 8.0 + 25.0
        A(Part(f"drum_{nm}_shaft", "oven", "band", "cyl", (xd, ys0, cz["drum"]), ("y", ys1 - ys0, 20.0), "#9aa3ab",
               hw="shaft D20"))
        for side, yy in (("f", ys0), ("b", cy["i1"] + 8.0)):
            A(Part(f"drum_{nm}_bearing_{side}", "oven", "band", "box", (xd - 25.0, yy, cz["drum"] - 25.0), (50.0, 25.0, 50.0),
                   "#5b6168", hw="flanged bearing unit UCF204 class", note="on the side plate"))
    nema(A, "M_band", "oven", "band", "z", cz["drum"] - 25.0, (xe, cy["i1"] + 8.0 + 14.5), "PG27", "17HS19-2004D-E1000",
         tag="Q40", sign=-1, note="band drive under the back bearing, GT3 belt to the drum shaft; geared to the master "
                                  "axis (EL7047, closed loop)")
    # ---- side plates (in-feed / out-feed), slider beds, legs
    pz0 = cz["drum"] - 25.0
    for sec, a, b in (("in", x0 - r - 10.0, o0), ("out", o1, xe + r + 10.0)):
        for side, yy in (("f", cy["i0"] - 8.0), ("b", cy["i1"])):
            A(Part(f"band_plate_{sec}_{side}", "oven", "frame", "box", (a, yy, pz0), (b - a, 8.0, cz["under"] - pz0),
                   "#b9bec4", hw="Al plate 8 mm", note="band side plate: bearings outside, slider bed inside"))
    A(Part("band_bed_in", "oven", "frame", "box", (x0 + r + 2.0, cy["i0"], cz["skid"][0]),
           (o0 - x0 - r - 2.0, cy["i1"] - cy["i0"], 6.0), SS, hw="slider bed 6 mm (stainless)"))
    A(Part("band_bed_out", "oven", "frame", "box", (o1, cy["i0"], cz["skid"][0]),
           (xe - r - 2.0 - o1, cy["i1"] - cy["i0"], 6.0), SS, hw="perforated slider bed 6 mm (stainless)",
           note="the cooling air passes through it"))
    legs = [("in", x0 + r + 10.0), ("in", o0 - 50.0), ("out", o1 + 10.0), ("out", xe - r - 50.0)]
    for k, (sec, lx) in enumerate(legs):
        for side, yy in (("f", cy["i0"] - 40.0), ("b", cy["i1"])):
            A(Part(f"band_leg_{k}{side}", "oven", "frame", "box", (lx, yy, 0.0), (40.0, 40.0, pz0), "#d6d9da",
                   mech="profile:4040", hw="HFS8-4040"))
    # ---- crumb / return pan + hangers, end lip (a missed cookie falls off the nose into it)
    A(Part("band_pan", "oven", "pan", "box", (pan[0], cy["i0"], cz["pan"][0]), (pan[1] - pan[0], cy["i1"] - cy["i0"], 7.0),
           SS, hw="crumb pan 7 mm (stainless, U-folded)",
           note="carries the return run; collects crumbs and any cookie delta C missed (emptied each shift)"))
    A(Part("band_pan_lip", "oven", "pan", "box", (pan[1] - 3.0, cy["i0"], cz["pan"][1]), (3.0, cy["i1"] - cy["i0"], 25.0),
           SS, hw="crumb pan 7 mm (stainless, U-folded)"))
    hx = [x0 + r + 70.0, (x0 + o0) / 2 + 40.0, o0 + 120.0, (o0 + o1) / 2, o1 - 120.0, o1 + 80.0, xe - r - 120.0]
    for k, x in enumerate(hx):
        top_ = cz["floor"][0] if o0 < x < o1 else pz0
        for side, (ya, yb_) in (("f", (cy["i0"] - 8.0, cy["i0"])), ("b", (cy["i1"], cy["i1"] + 8.0))):
            A(Part(f"pan_hanger_{k}{side}", "oven", "pan", "box", (g1(x), ya, cz["pan"][0]), (20.0, yb_ - ya, top_ - cz["pan"][0]),
                   "#9aa3ab", hw="hanger 8 mm (stainless)"))
    # ---- chamber: one welded box of 50 mm panels (stainless skins, mineral wool), band mouths in the ends
    PN = "insulated oven panel 50 mm (stainless skins, mineral wool)"
    A(Part("oven_panel_floor", "oven", "chamber", "box", (o0, cy["o0"], cz["floor"][0]), (o1 - o0, cy["o1"] - cy["o0"], ins),
           SKIN, hw=PN))
    A(Part("oven_panel_roof", "oven", "chamber", "box", (o0, cy["o0"], cz["roof"][0]), (o1 - o0, cy["o1"] - cy["o0"], ins),
           SKIN, hw=PN))
    hgt = cz["roof"][0] - cz["floor"][1]
    for side, yy in (("front", cy["o0"]), ("back", cy["i1"])):
        A(Part(f"oven_panel_{side}", "oven", "chamber", "box", (o0, yy, cz["floor"][1]), (o1 - o0, ins, hgt), SKIN, hw=PN))
    for end, xx in (("in", o0), ("out", o1 - ins)):
        A(Part(f"oven_panel_{end}_lo", "oven", "chamber", "box", (xx, cy["i0"], cz["floor"][1]),
               (ins, cy["i1"] - cy["i0"], cz["mouth"][0] - cz["floor"][1]), SKIN, hw=PN))
        A(Part(f"oven_panel_{end}_hi", "oven", "chamber", "box", (xx, cy["i0"], cz["mouth"][1]),
               (ins, cy["i1"] - cy["i0"], cz["roof"][0] - cz["mouth"][1]), SKIN, hw=PN,
               note=f"band mouth {L['CHAMBER']['mouth_h']:g} mm high below it"))
    for k, lx in enumerate((o0 + 30.0, (o0 + o1) / 2 - 20.0, o1 - 70.0)):
        for side, yy in (("f", cy["o0"]), ("b", cy["o1"] - 40.0)):
            A(Part(f"oven_leg_{k}{side}", "oven", "chamber", "box", (g1(lx), yy, 0.0), (40.0, 40.0, cz["floor"][0]),
                   "#d6d9da", mech="profile:4040", hw="HFS8-4040"))
    # skids: the carry run slides on 2 stainless bars on posts between the bottom elements
    xi0, xi1 = o0 + ins, o1 - ins
    sy = (yb0 + 40.0, yb1 - 46.0)
    for k, yy in enumerate(sy):
        A(Part(f"oven_skid_{k}", "oven", "chamber", "box", (xi0, yy, cz["skid"][0]), (xi1 - xi0, 6.0, 6.0), SS,
               hw="skid bar 6 x 6 (stainless)"))
    bot = [x for k in range(len(L["OVEN_ZONES"])) for _, x in element_x(k, "bot")]
    zl = zone_len()
    posts = [xi0 + 10.0] + [st["zones"][k] for k in range(1, len(L["OVEN_ZONES"]))] + [xi1 - 16.0]
    for i, px in enumerate(posts):
        if min(abs(px + 3 - b) for b in bot) < 12.0:
            raise ValueError(f"skid post at {px} meets a bottom element")
        for k, yy in enumerate(sy):
            A(Part(f"oven_skidpost_{i}{k}", "oven", "chamber", "box", (g1(px), yy, cz["floor"][1]),
                   (6.0, 6.0, cz["skid"][0] - cz["floor"][1]), SS, hw="skid post 6 x 6 (stainless)"))
    # ---- per zone: elements (phase-coloured terminal covers), impingement fan, duplex thermocouple
    plan = oven_power()[2]
    phase_of = {tag: ph for ph, items in plan.items() for tag, _ in items}
    for k, Z in enumerate(L["OVEN_ZONES"]):
        zx0 = st["zones"][k]
        for face, zz in (("top", cz["el_top"]), ("bot", cz["el_bot"])):
            for e, x in element_x(k, face):
                ph = phase_of[e["tag"]]
                A(Part(f"oven_heater_{e['tag']}", "oven", f"zone{k + 1}", "cyl", (x, cy["i0"], zz), ("y", cy["i1"] - cy["i0"], 8.5),
                       "#c0562f", tag=e["tag"], hw="tubular",
                       note=f"{e['P']:.0f} W 230 V on {ph}, {e['load_Wcm2']:.1f} W/cm2 - {e['cat']['model']}"))
                for side, yy in (("f", cy["o0"] - 14.0), ("b", cy["o1"])):
                    A(Part(f"oven_term_{e['tag']}_{side}", "oven", f"zone{k + 1}", "box", (x - 10.0, yy, zz - 10.0),
                           (20.0, 14.0, 20.0), PHASE_RGB[ph], hw="element terminal cover",
                           note=f"{ph} ({'brown' if ph == 'L1' else 'black' if ph == 'L2' else 'grey'}) / N"))
        xm = g1(zx0 + zl / 2)
        yc = B["yc"]
        A(Part(f"oven_fan_{k + 1}_imp", "oven", f"zone{k + 1}", "cyl", (xm, yc, cz["roof"][0] - 25.0), ("z", 20.0, 90.0),
               "#5b6168", mech="spin:fan", hw="D90 radial impeller", note="impingement: pushes zone air down onto the band"))
        A(Part(f"oven_fan_{k + 1}_shaft", "oven", f"zone{k + 1}", "cyl", (xm, yc, cz["roof"][0] - 5.0), ("z", 5.0, 8.0),
               "#9aa3ab", hw="fan shaft D8 (through the roof)"))
        A(Part(f"oven_fan_{k + 1}_motor", "oven", f"zone{k + 1}", "box", (xm - 30.0, yc - 30.0, cz["roof"][1]),
               (60.0, 60.0, 70.0), "#2b2b2f", tag=f"QF{k + 1}", hw="OVEN_FAN", note="230 V on the zone feed"))
        tops = [x for _, x in element_x(k, "top")]
        xt = g1((tops[0] + tops[1]) / 2) if len(tops) > 1 else g1(zx0 + zl / 4)
        yt = cy["i0"] + 25.0
        A(Part(f"oven_tc_{k + 1}", "oven", f"zone{k + 1}", "cyl", (xt, yt, cz["band"] + 30.0),
               ("z", cz["roof"][0] - cz["band"] - 30.0, 6.0), "#b9bec4", tag=f"TC{k + 1}", hw="tc_K",
               note="duplex type K: element 1 -> PID (EL3314), element 2 -> the zone's STB (SF4)"))
        A(Part(f"oven_tc_{k + 1}_head", "oven", f"zone{k + 1}", "box", (xt - 10.0, yt - 10.0, cz["roof"][1]), (20.0, 20.0, 25.0),
               "#b9bec4", hw="thermocouple head + gland"))
    # vapour exhaust over zone 1 (most of the water leaves there) - hose to the hall extraction
    xs = g1(st["zones"][0] + zl * 0.75)
    ys = cy["o1"] - 45.0
    A(Part("oven_exhaust", "oven", "chamber", "cyl", (xs, ys, cz["roof"][1]), ("z", 180.0, 60.0), SS,
           hw="exhaust stack D60 + damper", note="vapour out; damper sets the extraction (oven.py X_EXHAUST)"))
    A(Part("oven_exhaust_fan", "oven", "chamber", "box", (xs - 40.0, ys - 40.0, cz["roof"][1] + 180.0), (80.0, 80.0, 60.0),
           "#2b2b2f", tag="QX1", hw="exhaust_fan", note="24 V EC duct fan; hose to the hall extraction through the roof"))
    A(Part("IR1_pyrometer", "oven", "sensor", "box", (o1, B["yc"] - 15.0, cz["mouth"][1] + 5.0), (15.0, 30.0, 15.0),
           "#1b8f52", tag="IR1", hw="ir_pyrometer",
           note="product surface temperature at the oven exit: closes the bake loop on the cookie, not the air"))
    # ---- impingement cooling: hood with fans over the band, plenum with fans under it
    c0, c1 = st["c0"], st["c1"]
    for side, yy in (("front", cy["i0"] - 8.0), ("back", cy["i1"])):
        A(Part(f"cool_hood_wall_{side}", "oven", "cooler", "box", (c0, yy, cz["under"]), (c1 - c0, 8.0, 95.0), "#3a3f44",
               hw="sheet-steel hood 8 mm frame"))
    zh = cz["under"] + 95.0
    A(Part("cool_hood_wall_top", "oven", "cooler", "box", (c0, cy["i0"] - 8.0, zh), (c1 - c0, cy["i1"] - cy["i0"] + 16.0, 3.0),
           "#3a3f44", hw="sheet-steel hood 3 mm"))
    nf = max(1, int((c1 - c0) // 130))
    for i in range(nf):
        x = g1(c0 + (i + 0.5) * (c1 - c0) / nf)
        A(Part(f"cool_fan_{i + 1}", "oven", "cooler", "box", (x - 60.0, B["yc"] - 60.0, zh + 3.0), (120.0, 120.0, 25.0),
               "#2b2b2f", tag=f"QC{i + 1}", hw="COOL_FAN", note="blows room air down through the mesh"))
    zp0 = cz["skid"][0] - 59.0
    hollow(A, "cool_plenum", "oven", "cooler", c0, cy["i0"], zp0, c1 - c0, cy["i1"] - cy["i0"], 59.0, 3.0, "#3a3f44",
           hw="sheet-steel plenum 3 mm", note="takes the air through the mesh; fans in its floor blow it down")
    for i in range(nf):
        x = g1(c0 + (i + 0.5) * (c1 - c0) / nf)
        A(Part(f"cool_exfan_{i + 1}", "oven", "cooler", "box", (x - 60.0, B["yc"] - 60.0, zp0 - 25.0), (120.0, 120.0, 25.0),
               "#2b2b2f", tag=f"QC{nf + i + 1}", hw="COOL_FAN"))


def _transfer(A):
    """M4: delta C on its own portal over the band end + the right bend: picks every cookie of a row off the
    band inside the pick window and places it into a passing puck (tracking both); NFC write, I1, I9."""
    c = L["DELTA_C"]
    xc, yc, zc = c["x"], c["y"], c["z"]
    rr = H.NEMA17["flange"] / 2 * math.sqrt(2) + 0.1
    zb_top = zc + math.ceil(rr) + 12
    zt = L["GUARD_TOP"] - 20.0 - 40.0              # beam under the roof rails: the hanger is long enough for brackets
    yf, yb_ = guard()["yF2"] + 25.0, yc + 240.0
    for k, py in enumerate((yf, yb_ - 40.0)):
        A(Part(f"tportal_post_{k}", "transfer", "portal", "box", (xc - 20.0, py, 0.0), (40.0, 40.0, zt), "#d6d9da",
               mech="profile:4040", hw="HFS8-4040"))
    A(Part("tportal_beam", "transfer", "portal", "box", (xc - 20.0, yf, zt), (40.0, yb_ - yf, 40.0), "#d6d9da",
           mech="profile:4040", hw="HFS8-4040"))
    A(Part("delta_hanger_C", "transfer", "portal", "box", (xc - 20.0, yc - 20.0, zb_top), (40.0, 40.0, zt - zb_top),
           "#d6d9da", mech="profile:4040", hw="HFS8-4040",
           note="hanger: corner brackets to the beam, base plate screwed into its end tap"))
    _delta(A, "delta_C", xc, module="transfer")
    for nm, th, tag, hw, note in (("I1_full_check", L["TRANSFER_TH"][0], "I1", "diffuse_M12",
                                   "puck already full (recirculating) -> delta C does NOT place into it"),
                                  ("nfc_writer", L["TRANSFER_TH"][1], "NFC-W", "nfc_head",
                                   "writes flavour (band row), batch, bake log (IR1, zone temperatures) into the tag"),
                                  ("I9_landing_check", L["TRANSFER_TH"][2], "I9", "diffuse_M12",
                                   "landing check after the place: is the cookie seated in the nest? (EL1252)")):
        x, y = bend_xy(th, L["R"] + 55.0)
        sz = (40.0, 34.0, 25.0) if hw == "nfc_head" else (15.0, 15.0, 15.0)
        z = L["BELT_Z"] - 40.0 if hw == "nfc_head" else L["BELT_Z"] + 5.0
        A(Part(nm, "transfer", "sensor", "box", (g1(x - sz[0] / 2), g1(y - sz[1] / 2), z), sz, "#1b8f52" if hw != "nfc_head"
               else "#2f6fd0", tag=tag, hw=hw, note=note))


def _pa1(A):
    """Upgrade PA-1 sensors that need a place of their own (IR1, I9 and the NFC writer live in _oven/_transfer)."""
    if not L["PA1"]:
        return
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
    rx0, rx1, hz_top = raw_strip()
    ry = L["RAW_Y"]
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
    panel("F1a", (xlo, yo1, zp), (rx0 - xlo, t, hp))
    panel("F1b", (rx0, yo1, zp), (rx1 - rx0, t, hz_top - zp),
          note="in front of the dough + topping hoppers, up to the lowest rim: above it the pour strip is open")
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
    # ---- dough hopper lid: the pour strip in front of the raw rail is the only way into it (the topping
    # hoppers lie wholly under the strip; their own lids are hinged, interlocked by nothing - food-contact)
    hl, hh = L["DEP_HOPPER"]
    zh = dep_z()["hopper"] + hh
    A(Part("dep_hopper_wall_top", "depositor", "hopper", "box", (dep_hopper_x0(), ry, zh), (hl, chamber_y()["i1"] - ry, 3.0),
           "#c9ced2", hw="dough hopper 3 mm stainless",
           note="fixed lid (welded): the AMR tips the tub through the strip in front of the raw rail; the ToF "
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
    _door(A, "aldoor_boxes", g["xLo"] - 10, g["xLo"], py0 + 14, py1 - 14, oz0 - 10, gt, tag,
          "outer airlock door: opens only with every trapdoor closed and exhausted")
    # ---------------------------------------------------------------- out airlock (right)
    o = L["OUT_LOCK"]
    hx, ox, oy0, oy1, zd = o["hx"], o["x"], o["y0"], o["y1"], o["zdoor"]
    sz = shuttle_z()
    for k, py in enumerate((oy0, oy1 - 30)):
        prof(f"aout_post_{k}", (hx, py, 0.0), (30.0, 30.0, sz["beam"]), "3030")
    prof("aout_header", (hx, oy0, sz["beam"]), (30.0, oy1 - oy0, 30.0), "3030")
    # header cap up to the roof: the internal roof rail ends on its sides (guard roof, split there)
    prof("aout_header_top", (hx, oy0, sz["beam_top"]), (20.0, oy1 - oy0, 20.0))
    _door(A, "aldoor_inner", ox, hx, oy0 - t, oy1 + t, 0.0, zd, "S32",
          "inner airlock door: slides behind the lanes to open; closes the standby bay off from the stackers. "
          "Its top stays under the MGN rails; the header closes the rest")
    xr = g["xR"]
    pc("aout_wall_front", (hx, oy0 - t, 2.0), (xr - hx, t, gt - 2.0))
    pc("aout_wall_back", (hx, oy1, 2.0), (xr - hx, t, gt - 2.0))
    side, py0, py1, oz0, oz1, tag = L["PORT_OPEN"]["out"]
    _door(A, "aldoor_out", g["xRo"], g["xRo"] + 10, py0 + 14, py1 - 14, oz0 + 2, gt, tag,
          "outer airlock door: opens only with the inner door locked and the shuttles at safe standstill")


def _door(A, name, x0, x1, y0, y1, z0, z1, tag, note):
    """A sliding airlock door kit: the LEAF (drawn closed, joint door_<tag>) and its parking guide behind it,
    one leaf length long in +y (the leaf slides into it to open)."""
    A(Part(name, "safety", "airlock_door", "box", (x0, y0, z0), (x1 - x0, y1 - y0, z1 - z0), "#b7d3e6", tag=tag,
           hw="airlock_door", joint=f"door_{tag}", note=note + " (leaf, drawn closed)"))
    A(Part(f"{name}_park", "safety", "airlock_door", "box", (x0, y1, z0), (x1 - x0, y1 - y0, z1 - z0), "#9aa3ab",
           hw="airlock door guide + drive (kit)", note="the leaf parks in here when open"))


def door_stroke(tag):
    """Opening stroke (+y) of the airlock door leaf with this tag."""
    return {p.tag: p.s[1] for p in _zone_parts() if p.hw == "airlock_door" and p.tag}[tag]


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
    if L.get("SAFE1"):              # brush strip on the rim closes the bin-top slot (split where the shutter is)
        hx0, hy0, ho = reject_hole()
        zb, t = zt - gap, 3.0
        segs = [("front", (bx, by), (bx + bw_, by + t)), ("left", (bx, by + t), (bx + t, by + bd - t)),
                ("right", (bx + bw_ - t, by + t), (bx + bw_, by + bd - t)),
                ("back_l", (bx, by + bd - t), (hx0 - 10, by + bd)), ("back_r", (hx0 + ho + 10, by + bd - t), (bx + bw_, by + bd))]
        for nm, (a0, b0), (a1, b1) in segs:
            A(Part(f"reject_bin_brush_{nm}", "qc", "reject", "box", (a0, b0, zb), (a1 - a0, b1 - b0, gap), "#2b2b2f",
                   hw="brush strip 3 mm (PP bristles)", note="rides with the drawer, wipes the deck underside"))
    for k, sx in enumerate((bx - 14, bx + bw_)):          # 14 wide: an M4 into the deck needs 2 x 6.75 edge room
        A(Part(f"reject_slide_{k}", "qc", "reject", "box", (sx, 0.0, zt - 35), (14.0, by + bd, 35.0), "#b9bec4",
               hw="telescopic slide 35 x 12", note="drawer slide under the deck"))
    A(Part("reject_level", "qc", "sensor", "box", (bx + bw_ / 2 - 10, by + bd, zt - 16), (20.0, 20.0, 14.0),
           "#1b8f52", tag="IOL4", hw="tof_level", note="drawer fill level"))


def _delta(A, name, xd, pose=None, static=True, moving=True, module="pick"):
    yd, zd, _ = _dbase(xd)
    ex, ey, ez = pose or (xd, yd, travel_z(xd))
    motor, gear = L["DELTA_MOTOR"], L["DELTA_GEAR"]
    ln = H.STEPPER[motor]["body"] + H.STEPPER[motor]["enc_len"] + H.GEARBOX[gear]["length"]
    rr = H.NEMA17["flange"] / 2 * math.sqrt(2) + 0.1                     # square body -> round envelope
    zb = zd + math.ceil(rr)
    if static:
        A(Part(f"{name}_base", module, name, "cyl", (xd, yd, zb), ("z", 12.0, 2 * (L["DELTA_RB"] + 60)), "#2b2b2f",
               hw="Al base plate 12 mm"))
    for phi, sh, el, wr in delta_points(ex, ey, ez, xd):
        c, s = math.cos(math.radians(phi)), math.sin(math.radians(phi))
        tx, ty = -s, c                                                    # motor axis = tangent
        g = L["MOTOR_GAP"]
        if static:
            A(Part(f"{name}_motor_{int(phi)}", module, name, "rod",
                   (sh[0] - g * tx, sh[1] - g * ty, zd), (sh[0] - (g + ln) * tx, sh[1] - (g + ln) * ty, zd, 2 * rr),
                   "#e0492f", tag=f"{name}.M{int(phi)}", hw=f"{motor}+{gear}",
                   note="closed-loop NEMA 17 + precision planetary (backlash budget), hung under the base"))
            A(Part(f"{name}_shaft_{int(phi)}", module, name, "rod",
                   (sh[0] - g * tx, sh[1] - g * ty, zd), (sh[0] + 8 * tx, sh[1] + 8 * ty, zd,
                                                          H.GEARBOX[gear]["shaft"][0]), "#9aa3ab"))
        if moving:
            A(Part(f"{name}_upper_{int(phi)}", module, name, "rod", sh, (*el, 12.0), "#d6d9da", joint=name,
                   hw="CFK tube 12 + clamp hub"))
            A(Part(f"{name}_pin_{int(phi)}", module, name, "rod", (el[0] - 18 * tx, el[1] - 18 * ty, el[2]),
                   (el[0] + 18 * tx, el[1] + 18 * ty, el[2], 8.0), "#9aa3ab", joint=name,
                   hw="elbow cross pin D8, ball studs"))
            for k in (-1, 1):
                o = 18 * k
                A(Part(f"{name}_fore_{int(phi)}_{'ab'[k > 0]}", module, name, "rod",
                       (el[0] + o * tx, el[1] + o * ty, el[2]), (wr[0] + o * tx, wr[1] + o * ty, wr[2], 5.0),
                       "#2b2b2f", joint=name, hw="CFK rod 5 + ball joints", note="parallelogram"))
    if moving:
        A(Part(f"{name}_effector", module, name, "cyl", (ex, ey, ez), ("z", 10.0, 2 * L["DELTA_RE"] + 16), "#e0492f",
               joint=name, hw="Al effector"))
        for k, sx in enumerate((-1, 1)):                  # twin cups straddle the topping drop in the centre
            A(Part(f"{name}_cup_{'ab'[k]}", module, name, "cyl", (ex + sx * L["CUP_OFF"], ey, ez - L["CUP_L"]),
                   ("z", L["CUP_L"], L["CUP_D"]), "#26282b", joint=name, tag=f"{name}.VAC" if k == 0 else "",
                   hw=f"bellows cup D{L['CUP_D']:g} on spring stem",
                   note="twin vacuum cups on one ejector: ejector valve (DO) + vacuum sensor"))


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
        # TWIN-strand transfer conveyor: the lift plate rises BETWEEN the strands (a belt cannot have a slot -
        # found by the motion sweep, motion.py); the pack rests on both strands
        ps = L["STACK_PLATE_W"] / 2 + 2.0
        for k, (a_, b_) in enumerate(((y - L["LANE_W"] / 2, y - ps), (y + ps, y + L["LANE_W"] / 2))):
            zf_ = L["LANE_Z"] - 10 - 10 - 1                   # frame top: the strand + its side rail stand on it
            A(Part(f"stacker_{f}_{'ab'[k]}", "pack", "stacker", "box", (L["LANE_X"][1], a_, zf_),
                   (xa + cw - L["LANE_X"][1] + 5, b_ - a_, L["LANE_Z"] - zf_), "#3b3e44", mech="belt:lane",
                   hw="transfer belt strand on its side rail (twin-strand conveyor, driven with the lane)",
                   note="transfer onto the stacker platform under the active cassette"))
        A(Part(f"stacker_frame_{f}", "pack", "stacker", "box", (L["LANE_X"][1], y - L["LANE_W"] / 2 - 3, 0),
               (xa + cw - L["LANE_X"][1] + 5, L["LANE_W"] + 6, L["LANE_Z"] - 10 - 10 - 1), "#d6d9da",
               hw="transfer conveyor frame", note="the lift plate rises through it"))
        A(Part(f"stacker_plate_{f}", "pack", "stacker", "box",
               (xa + cw / 2 - 60, y - L["STACK_PLATE_W"] / 2, L["LANE_Z"] - 20),
               (120.0, L["STACK_PLATE_W"], 10.0), "#e0492f", joint=f"lift_{f}", hw="Al plate 10 mm",
               note="lift plate, rises between the two transfer strands"))
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
    rx0, rx1, _ = raw_strip()
    A(Part("port_raw", "ports", "port", "box", (rx0, 0.0, 0.0), (rx1 - rx0, 14.0, 40.0), "#1f4e8c",
           hw="docking plate Al 14 mm",
           note="front edge: dough tub / topping refill docking face (the AMR tips through the pour strip)"))
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
    "M2_depositor": "Depositor - plain-dough wire-cut (6 rows) + thumbprint topping (3 flavours, 2 rows each)",
    "M3_oven": "Band oven - stainless mesh band, 3 zones (tubular elements top + bottom, impingement fans, duplex "
               "TC + STB), impingement cooling, 400 V 3-phase (oven.py)",
    "M4_transfer": "Transfer - delta C picks each cookie off the band end into a passing puck on the right bend",
    "M5_qc": "Vision QC hood + colour sensor + on-the-fly reject",
    "M6_pick": "Pick cell - two tracking delta robots (N+1) on a portal",
    "M7_pack": "Box lanes (3 flavours) + bottom-up stackers into pack cassettes (AMR exchange through the airlock)",
    "M8_control": "Beckhoff enclosure under the deck, valve island, FRL",
    "M9_ports": "AMR docking faces - raw in + rejects (front), cassettes (right), boxes (left)",
    "M10_safety": "Safety - perimeter guard + roof, 3 doors with guard locking, AMR airlocks (boxes: trapdoor "
                  "chamber, cassettes: inner + outer door), E-stops (TwinSAFE, SAFETY_CONCEPT.md)",
}
_MOD_OF = {"loop": "M1_loop", "depositor": "M2_depositor", "oven": "M3_oven", "transfer": "M4_transfer",
           "qc": "M5_qc", "pick": "M6_pick", "pack": "M7_pack", "control": "M8_control", "ports": "M9_ports",
           "safety": "M10_safety"}


def _actuator_parts():
    out = []
    A = out.append
    _depositor(A)
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
    n = len(cyl) + len(L["DELTA_X"]) + 1                 # + delta C's ejector
    if L.get("SAFE1") and L.get("AIRLOCK"):            # airlock door drives + trapdoor actuators
        n += sum(1 for p in _zone_parts() if p.hw in ("airlock_door", "trapdoor unit"))
    return n


def build(t=0.0, with_product=True):
    out = []
    A = out.append
    _loop_parts(A)
    if with_product:
        _pucks(A, t)
        _band_product(A, t)
    _depositor(A)
    _oven(A)
    _transfer(A)
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
    B = L["BAND"]
    row("flavour rows on the band", f"{B['rows']} rows, {len(FLAV)} flavours", "rows % flavours == 0, MIX 1:1:1",
        B["rows"] % len(FLAV) == 0 and len(set(L["MIX"])) == 1,
        "row k carries flavour k mod 3: delta C picks a row in order -> W R B W R B on the loop")
    v = band_v()
    rows.append(("band speed", f"{v:.3f} mm/s", f"one row of {B['rows']} per {B['rows'] * T:.0f} s", True,
                 f"{B['spacing']:g} mm row pitch; electronically geared to the master axis"))
    tb, tc = bake_t(), cool_t()
    _, sb = OV.simulate(L, OV.bake_segments(L, tb), record=1e9)
    Q = L["BAKE_Q"]
    row("bake (oven.py, 1-D + evaporation)", f"{tb:.0f} s: core >= {Q['core_min']:g} C for {sb['core_hold']:.0f} s, "
        f"water {sb['moisture']:.1%}, colour {sb['colour']:.2f}",
        f"hold >= {Q['core_hold']:g} s, water <= {Q['w_end']:.0%}, colour {Q['colour'][0]:g}..{Q['colour'][1]:g}",
        OV.baked_ok(L, sb), "the shortest residence that bakes it; the band length follows from it")
    st = stations()
    rows.append(("oven length", f"{len(L['OVEN_ZONES'])} zones x {zone_len():.0f} mm",
                 f"= {v:.3f} mm/s x {tb:.0f} s", True, "zones " + " / ".join(f"{z['T']:g}" for z in L["OVEN_ZONES"]) + " C"))
    _, sc = OV.profile(L, tb, tc, record=1e9, t_gap=band_gaps()[0], t_nose=band_gaps()[1])
    row("band cooling", f"hood {cool_len():.0f} mm = {tc:.0f} s -> max {sc['T_max']:.1f} C at the pick window",
        f"<= T_TRANSFER {L['T_TRANSFER']:g} C", sc["T_max"] <= L["T_TRANSFER"],
        f"impingement hood {L['COOLING']['band']['h_top']:g}/{L['COOLING']['band']['h_bot']:g} W/m2K")
    win = L["PICK_W"] / v
    row("row emptied in the pick window", f"{win:.1f} s", f">= {B['rows']} takts = {B['rows'] * T:.0f} s",
        win >= B["rows"] * T, "delta C takes one cookie per takt; a row never reaches the nose")
    cap_c = 1 / L["T_PICK"]
    row("transfer capacity, delta C", f"{cap_c:.2f} /s", f">= demand {1 / T:.2f} /s", cap_c >= 1 / T,
        "single transfer: a miss falls into the crumb pan (counted loss) - the band cannot stop with the oven hot")
    a0, a1 = L["PLACE_TH"]
    arc = L["R"] * math.radians(a1 - a0)
    row("place window on the bend", f"{arc:.0f} mm = {arc / L['V']:.1f} s", f">= reach+grip {L['T_GRAB']:g} s",
        arc / L["V"] >= L["T_GRAB"], "delta C tracks the puck along the arc (IK at 7 points)")
    t_loop = (s_back(L["DELTA_X"][1]) - bend_s(L["TRANSFER_TH"][1])) / L["V"]
    _, sp = OV.profile(L, tb, tc, [("pick window", L["PICK_W"] / v, "loop"), ("loop", t_loop, "loop")], record=1e9,
                       t_gap=band_gaps()[0], t_nose=band_gaps()[1])
    row("cookie at the picker", f"max {sp['T_max']:.1f} C after {t_loop:.0f} s on the loop", f"<= T_PACK {L['T_PACK']:g} C",
        sp["T_max"] <= L["T_PACK"], "a warm cookie sealed in film sweats (condensate in the pack)")
    cyy = chamber_y()
    g = guard()
    x0p, x1p, y0p, _, _ = portal()
    row("band unit fits", f"y {cyy['o0']:.0f}..{cyy['o1']:.0f}, x {st['x0'] - L['BAND']['drum'] / 2:.0f}.."
        f"{st['e'] + L['BAND']['drum'] / 2 + 24:.0f}", f"guard y >= {g['yF2'] + 20:.0f}, portal y0 {y0p:.0f}, x <= curve",
        cyy["o0"] >= g["yF2"] + 20 and cyy["o1"] < y0p and st["x0"] - L["BAND"]["drum"] / 2 > g["xL"] + 20,
        "raised over the loop's front run: the chain stays out of the heat")
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
    a_dough, a_top = dough_autonomy(), topping_autonomy()
    vol = L["DEP_HOPPER"][0] * (chamber_y()["i1"] - L["DEP_HOPPER_Y0"]) * L["DEP_HOPPER"][1] * 1e-9
    row("dough fits its hopper", f"{L['DOUGH_KG']:g} kg = {L['DOUGH_KG'] / L['DOUGH_RHO'] * 1000:.1f} l",
        f"<= 80 % of {vol * 1000:.1f} l", L["DOUGH_KG"] / L["DOUGH_RHO"] <= 0.8 * vol, "")
    td, th = L["TOP_HOPPER"]
    tv = math.pi * (td / 2) ** 2 * th * 1e-9
    row("topping fits its hopper", f"{L['TOP_KG']:g} kg = {L['TOP_KG'] / L['TOP_RHO'] * 1000:.2f} l",
        f"<= 80 % of {tv * 1000:.2f} l", L["TOP_KG"] / L["TOP_RHO"] <= 0.8 * tv, "")
    a_cas = cass_cap() * L["PACK"] / rf
    a_box = L["BOXMAG_CAP"] * L["PACK"] / rf
    a_rej = reject_cap() / (1 / T * 0.05)
    rows.append(("STOCK dough hopper", f"{L['DOUGH_KG']:g} kg", f"{a_dough / 60:.0f} min", True,
                 f"{L['DOUGH_M'] * 1000:g} g per cookie, one plain dough"))
    rows.append(("STOCK topping hoppers", f"3 x {L['TOP_KG']:g} kg", f"{a_top / 60:.0f} min each", True,
                 f"{L['TOPPING']['m'] * 1000:g} g per drop"))
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
          "dough refill": L["REQ_HOPPER"] * a_dough,
          "topping refill": L["REQ_HOPPER"] * a_top,
          "box refill": L["REQ_BOXMAG"] * a_box,
          "reject drawer": (1 - L["REQ_REJECT"]) * a_rej}
    n_tasks = 1 + 3 + 3 + 3 + 1                       # dough, 3 toppings, 3 cassettes, 3 box mags, reject
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
            d_ >= worst, f"all {n_tasks} port tasks queued ahead - so one AMR suffices and the 2nd is N+1")
    per_h = (3 * 3600 / a_cas) + 3600 / ((1 - L["REQ_HOPPER"]) * a_dough) + 3 * 3600 / ((1 - L["REQ_HOPPER"]) * a_top) \
        + 3 * 3600 / ((1 - L["REQ_BOXMAG"]) * a_box) + 0.2
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
    # --- Q40 band drive: slider-bed / skid friction of the carry run + product, pan friction of the return,
    # pulled by the drive drum through a PG27 (0.5 rpm at the drum)
    B = L["BAND"]
    run = (stations()["e"] - stations()["x0"]) / 1000
    m_carry = B["m_area"] * band_w() / 1000 * run + run * 1000 / B["spacing"] * B["rows"] * L["DOUGH_M"]
    m_ret = B["m_area"] * band_w() / 1000 * run
    F = H.BAND_MESH["mu_skid"] * (m_carry + m_ret) * G
    r_d = B["drum"] / 2000
    gb = H.GEARBOX["PG27"]
    n_drum = band_v() / (math.pi * B["drum"]) * 60
    t_out = F * r_d * 1.5                                  # x1.5: take-up tension difference + bearings
    row("Q40 band drive gearbox PG27", f"{t_out:.2f} Nm", f"<= rated {gb['T_rated']:g} Nm", t_out <= gb["T_rated"],
        f"{m_carry + m_ret:.1f} kg of mesh + dough, mu {H.BAND_MESH['mu_skid']:g}; drum {n_drum:.2f} rpm")
    t_mot = t_out / gb["ratio"] / gb["eff"]
    avail = H.stepper_torque("17HS19-2004D-E1000", n_drum * gb["ratio"])
    row("Q40 band motor", f"{t_mot:.3f} Nm @ {n_drum * gb['ratio']:.1f} rpm", f"<= {avail:.3f} Nm", t_mot <= avail,
        "closed loop, geared to the master axis")
    t_mot = L["DEP_T"] / gb["ratio"] / gb["eff"]
    n_r = 60 / (B["rows"] * takt()) * 2                    # ~2 roll turns per row [assumed]
    avail = H.stepper_torque("17HS19-2004D-E1000", n_r * gb["ratio"])
    row("Q41 depositor roll motor", f"{t_mot:.3f} Nm @ {n_r * gb['ratio']:.0f} rpm", f"<= {avail:.3f} Nm", t_mot <= avail,
        f"rolls {L['DEP_T']:g} Nm [assumed] via PG27")
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
                L["DELTA_ARM_M"] * G * _darms(xd)[2] / 2000 * abs(math.cos(math.radians(ang[k])))
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
    # --- shuttle
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
        ("topping dosing", L["TOP_CYL"], L["TOP_F"], 2 * L["TOPPING"]["m"] / L["TOP_RHO"] * 1e9 /
         (math.pi * L["TOP_CYL"][0] ** 2 / 4), "extend", None),
        ("kicker", L["KICK_CYL"], 5.0, L["KICK_STROKE"], "extend", L["KICK_STROKE"] / L["KICK_T"]),
        ("stacker lift", L["STACK_CYL"], cass_cap() * L["PACK_M"] * G + 4 * L["PAWL_F"], L["PAWL"] + bh, "extend", None),
        ("sealer", L["SEAL_CYL"], L["SEAL_P"] * flange_area, L["SEAL_GAP"], "extend", None),
        ("tray forks", L["FORK_CYL"], 2.0, 6.0, "extend", None),
    ]
    air = 0.0
    per_h = {"topping dosing": 3 * rate_flavour() * 3600 / 2, "kicker": 0.05 * 3600 / takt(),
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
    air += (len(L["DELTA_X"]) + 1) * H.EJECTOR["q"] * L["T_GRAB"] / L["T_PICK"]
    air *= 1.1
    row("air consumption", f"{air:.1f} Nl/min (+10 % leakage)", f"<= {H.AIR_DUTY:.0%} of FAD {H.AIR['fad']:g}",
        air <= H.AIR_DUTY * H.AIR["fad"], "the v3 on-table 66 mm toy compressor is gone; ejectors dominate")
    return rows, fails


def oven_proofs():
    """The band oven's heat and power, every number from oven.py: zone loads vs installed elements, sheath
    load, warm-up, outer skin, the loop under the oven, the 400 V 3N~ supply per phase, RCD leakage, SSRs."""
    rows, fails = [], []

    def row(name, value, limit, ok, note):
        rows.append((name, value, limit, ok, note))
        if not ok:
            fails.append(f"OVEN {name}: {value} vs {limit} - {note}")

    loads, els, plan, warm = oven_power()
    cz, cy = chamber_z(), chamber_y()
    for z in loads:
        inst = sum(e["P"] for e in els if e["zone"] == z["zone"])
        n_t = sum(1 for e in els if e["zone"] == z["zone"] and e["face"] == "top")
        n_b = sum(1 for e in els if e["zone"] == z["zone"] and e["face"] == "bot")
        row(f"{z['zone']} {z['T']:g} C load / installed", f"{z['total']:.0f} W / {inst:.0f} W ({z['total'] / inst:.0%})",
            f"<= {L['HEADROOM']:.0%}", z["total"] <= L["HEADROOM"] * inst,
            f"product {z['product']:.0f}, band {z['band']:.0f}, walls {z['walls']:.0f}, mouth {z['mouth']:.0f}, "
            f"exhaust {z['exhaust']:.0f} W; {n_t} top + {n_b} bottom elements")
    worst = max(els, key=lambda e: e["load_Wcm2"])
    row("element sheath load (worst)", f"{worst['load_Wcm2']:.2f} W/cm2 ({worst['tag']})", f"<= {H.TUBULAR_WCM2:g} W/cm2",
        worst["load_Wcm2"] <= H.TUBULAR_WCM2, "Incoloy sheath in forced air")
    tw = max(t for _, t, _ in warm)
    row("warm-up from cold (all elements on)", f"{tw / 60:.1f} min (" + ", ".join(f"{z} {t / 60:.0f}" for z, t, _ in warm) + ")",
        f"<= {L['WARMUP_MAX'] / 60:.0f} min", tw <= L["WARMUP_MAX"], "lumped chamber: skins, band, elements, half the wool")
    skin = max(z["skin"] for z in loads)
    row("outer skin (hottest zone)", f"{skin:.1f} C", f"<= {L['SKIN_MAX']:g} C", skin <= L["SKIN_MAX"],
        f"{L['CHAMBER']['insul']:g} mm mineral wool; burn threshold for 10 s on bare metal (EN ISO 13732-1) [typ]")
    lim = min(H.TEMP_LIMIT["POM chain"], H.TEMP_LIMIT["UHMW-PE track"], H.TEMP_LIMIT["NFC tag"])
    row("loop under the oven", f"floor skin {skin:.1f} C, return band on the pan", f"<= {lim:g} C (POM / UHMW / NFC)",
        skin <= lim, "the chain, its track and the tags never enter the heat")
    S = H.SUPPLY
    amps = {ph: sum(w for _, w in items) / S["U"] for ph, items in plan.items()}
    imax = max(amps.values())
    row("400 V 3N~ supply, worst phase", "  ".join(f"{p} {a:.1f} A" for p, a in amps.items()),
        f"<= {S['load_max']:.0%} of {S['I']:g} A", imax <= S["load_max"] * S["I"],
        f"{sum(e['P'] for e in els) / 1000:.2f} kW elements + fans; CEE 16 A, 30 mA RCD type A")
    unb = (imax - min(amps.values())) / imax
    row("phase balance", f"{unb:.0%} spread", "<= 25 %", unb <= 0.25, "largest-first onto the least loaded phase")
    leak = len(els) * H.LEAK_mA["tubular"] + 4 * H.LEAK_mA["psu"]
    row("protective-conductor current", f"{leak:.1f} mA", f"<= 30 % of {S['rcd_mA']:g} mA RCD",
        leak <= 0.3 * S["rcd_mA"], f"{len(els)} elements + 4 PSUs, hot and dry [typ]")
    ssr = H.SSR_AC25
    ie = max(e["P"] for e in els) / S["U"]
    tc = 40.0 + ssr["R_th"] * ssr["U_drop"] * ie
    row("element SSR (worst)", f"{ie:.2f} A, case {tc:.0f} C", f"<= {ssr['I']:g} A, case <= 80 C", ie <= ssr["I"] and tc <= 80,
        "one SSR per element on its DIN heatsink, cabinet air 40 C")
    tot = sum(z["total"] for z in loads)
    rows.append(("energy per cookie", f"{tot * takt() / 3600:.2f} Wh", f"steady {tot / 1000:.2f} kW at {3600 / takt():.0f}/h",
                 True, "product " + f"{sum(z['product'] for z in loads) / tot:.0%}" + " of it; the rest heats band, walls, air"))
    return rows, fails


def reach():
    """Delta IK must solve every pick point in its window and every place point."""
    fails, n = [], 0
    for i, xd, (x, y, z), kind in delta_poses():
        n += 1
        if delta_ik(x, y, z, xd) is None:
            fails.append(f"REACH delta_{'ABC'[i]}: {kind} ({x:.0f},{y:.0f},{z:.0f})")
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
    if a.name.startswith("top_hose_") and b.name.startswith("top_hose_") and a.name[:-2] == b.name[:-2]:
        return "one hose (straight runs joined by a bend)"
    for u, v in ((a, b), (b, a)):
        if u.name.startswith("top_hose_") and v.name == "top_rack":
            return "through-hole: hose through the rack plate into the hopper outlet"
        if u.name.startswith("top_hose_") and v.name == "top_manifold":
            return "hose in its manifold port (barb)"
        if u.name.startswith("top_hose_") and v.name.startswith("top_hopper_") and u.name.split("_")[2] == v.name.split("_")[2]:
            return "hose on its hopper outlet"
    for u, v in ((a, b), (b, a)):
        if u.name.startswith("drum_") and u.name.endswith("_shaft"):
            d = u.name.split("_")[1]
            if v.name == f"drum_{d}":
                return "drum keyed on its shaft"
            if v.name.startswith(f"drum_{d}_bearing"):
                return "shaft in its bearing unit"
            if v.name.startswith("band_plate_"):
                return "through-hole: drum shaft through the side plate (cut in CAD)"
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
    if a.group == b.group == "airlock_door" and {a.name, b.name} in ({n, n + "_park"} for n in
                                                                    ("aldoor_boxes", "aldoor_inner", "aldoor_out")):
        return "door leaf slides into its parking guide (kit)"
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
    """Moving envelopes vs everything: kicker paddle over its stroke, the depositor's cutting wire over its
    stroke, all three deltas at every commanded pose."""
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
    wire = next(p for p in allp if p.name == "dep_wire")
    a_ = wire.aabb()
    stroke = L["DOUGH_SLUG"][0] + 10.0
    sw = Part("wire_sweep", wire.module, wire.group, "box", (a_[0] - stroke / 2, a_[1], a_[2]),
              (a_[3] - a_[0] + stroke, a_[4] - a_[1], a_[5] - a_[2]))
    for b in stat:
        if b.name in ("dep_wire", "dep_die") or b.group in ("chain", "frame", "guide", "band", "pan"):
            continue
        if geom.interfere(sw, b):
            fails.append(f"WIRE sweep hits {b.name}")
    # deltas at every commanded pose: arms vs every static solid except their own base/motors' joints
    static = [p for p in allp if not (p.group.startswith("delta_") and p.joint)]
    n = 0
    for i, xd, pose, kind in delta_poses():
        arms = []
        if delta_ik(*pose, xd) is None:
            continue                                     # reach() reports it
        _delta(arms.append, f"delta_{'ABC'[i]}", xd, pose, static=False)
        for p in arms:
            p.module = "M6_pick" if i < 2 else "M4_transfer"
        for p in arms:
            for b in static:
                if not _ovl(p.aabb(), b.aabb()):
                    continue
                if allowed(p, b):
                    continue
                if kind == "pick" and b.group == "chain":
                    continue
                if "_cup_" in p.name and b.group in ("tray", "stock"):
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
    """The slug is cut at the die and lands on the band; the cups touch the cookie top on the loop and on the
    band; the topping nozzles clear the slug."""
    fails = []
    dz = dep_z()
    if abs(dz["die"] - L["DEP_DROP"] - L["DOUGH_SLUG"][1] - L["BAND"]["z"]) > 1e-6:
        fails.append("CONTACT the die is not DEP_DROP above the slug on the band")
    if abs(pick_z() - L["CUP_L"] - z_cookie_top()) > 1e-6:
        fails.append("CONTACT delta cup tip != cookie top at the pick height")
    if abs(band_pick_z() - L["CUP_L"] - L["BAND"]["z"] - L["COOKIE"][1]) > 1e-6:
        fails.append("CONTACT delta C cup tip != cookie top on the band")
    if L["CUP_OFF"] - L["CUP_D"] / 2 < L["TOPPING"]["d"] / 2 or L["CUP_OFF"] + L["CUP_D"] / 2 > L["COOKIE"][0] / 2:
        fails.append("CONTACT twin cups do not land between the topping drop and the cookie rim")
    return fails


def band_clearance(step=5.0):
    """Sweep every row's product (slug -> baked cookie + drop) along the band from the die to the pick window
    against every static part: die, wire, topping manifold, mouths, thermocouples, hood, pyrometer."""
    parts = [p for p in build(with_product=False) if p.group not in ("band", "pan") and p.kind != "arc"]
    boxes = [(p, p.aabb()) for p in parts]
    st = stations()
    v = band_v()
    zb = L["BAND"]["z"]
    fails, n = [], 0
    x = st["dep"]
    while x <= st["pick"][1]:
        d, h, _, topped = band_state((x - st["dep"]) / v)
        z1 = zb + h + (L["TOPPING"]["h"] if topped else 0.0)
        for k in range(L["BAND"]["rows"]):
            y = row_y(k)
            for p, b in boxes:
                if b[2] < z1 - 0.05 and b[5] > zb + 0.05 and _circle_box(x, y, d / 2, b):
                    if p.name == "dep_wire" and x <= st["dep"] + 1:
                        continue                          # the slug is cut free at the wire
                    fails.append(f"BAND product hits {p.name} at x={x:.0f} row {k}")
            n += 1
        x += step
    return sorted(set(fails)), n


def check(verbose=True):
    rows, fails = timing()
    srows, sfails = sizing()
    rf, n_reach = reach()
    pf, n_sweep = product_clearance()
    lf, n_lane = lane_clearance()
    bf, n_band = band_clearance()
    inf, n_int, used = interference()
    mf, n_mov = moving_clearance()
    gf = grid()
    orows, ofails = oven_proofs()
    fails = fails + sfails + ofails + rf + pf + lf + bf + inf + mf + gf + contact()
    if verbose:
        print(f"STF-2 continuous line: {len(build())} parts, loop {loop_len():.1f} mm, "
              f"S = {straight():.1f} mm, takt {takt():.2f} s")
        for name, v, lim, ok, note in rows + srows + orows:
            print(f"  [{'ok' if ok else 'FAIL'}] {name:36s} {v:45s} {lim:38s} {note}")
        print(f"  delta reach radius at pick height: {delta_reach_radius():.1f} mm; "
              f"{n_reach} pick/place points solved by IK")
        print(f"  product envelope swept along the loop: {n_sweep} stations of 5 mm; "
              f"packs swept along the lanes: {n_lane} stations; band product: {n_band} row stations")
        print(f"  interference: {n_int} touching/overlapping candidate pairs, allowed by declaration: "
              + ", ".join(f"{v} x {k}" for k, v in used.items()))
        print(f"  moving envelopes: kicker, cutting wire, deltas A/B/C at {len(delta_poses())} poses ({n_mov} exact pair tests)")
        print("\n".join(fails) if fails else
              "ALL CHECKS PASS (timing, sizing, oven heat + power, reach, product + lane + band sweep, interference, "
              "motion, grid, contact)")
    return fails


if __name__ == "__main__":
    import sys
    sys.exit(1 if check() else 0)
