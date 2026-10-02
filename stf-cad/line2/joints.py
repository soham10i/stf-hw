"""
STF-2 joints: every structural contact becomes a real, orderable fastening.

line_model says WHERE the solids are; this module says HOW they are held.

  1. contacts()    which solids touch (face contact, gap <= 0.5 mm, patch > 1 x 1 mm)
  2. classify()    every contact is one of
                     body       one bent / welded / bonded body (hollow() walls, a Z-bracket)
                     kinematic  declared moving joint (arm hub, ball joint, rail block, spindle, rod)
                     sliding    the chain on its track and between its guides
                     resting    located by gravity + pin (cassette lugs on the shuttle bar, tube in its block)
                     fastened   gets fasteners from a RULE below
                     incidental touching, carries nothing (never used as support)
  3. rules         profile on the deck       -> corner brackets, deck leg tapped into the tooling plate
                   profile end on a profile  -> corner brackets, T-nut screws in both legs
                   plate edge on a profile   -> corner brackets, plate leg tapped into the plate
                   plate / device on a profile face -> screws through it (or its flange) into T-nuts
                   plate / device on a tapped part / the deck -> screws into tapped holes,
                     through-bolt + nut where the part is too thin to tap
                   bought parts use their catalogue hole pattern (NEMA 17 31 sq, MGN block B x C)
  4. placement     every screw is SEARCHED: positions on the slot line / hole pattern / a 2 mm
                   grid over the contact patch (edge distance respected), head type ISO 4762 ->
                   ISO 7380 button -> ISO 10642 countersunk, with or without an ISO 7089 washer,
                   ISO 4762 stock length - the first combination that satisfies the thread rules
                   AND collides with nothing wins
  5. mounts        a device touching no structure gets a derived bracket (<= 60 mm) or 2020 stand
  6. proofs        (independent of the search) nothing floats; engagement >= MIN_ENGAGE x d
                   (T-nut: >= 0.8 d, ISO 898-2) and no bottoming; stock lengths; ISO 273 medium
                   holes; edge distance >= 1.5 x hole; fasteners + brackets collide with nothing
                   and each other; every fastener and bracket on the 0.1 mm grid.

Run: python3 joints.py      (exit 1 if any proof fails)
"""
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import geom as G
import hardware as H
import line_model as M

L = M.L
GAP = 0.5            # contact tolerance (mm): faces within GAP touch
AREA = 1.0           # a contact patch must be wider than this in both directions
DECK = M.Part("TABLE", "deck", "deck", "box", (0.0, 0.0, -L["TABLE"][2]), L["TABLE"], hw="TABLE_PLATE")
PRODUCT = ("stock", "tray", "puck", "cookie")


def g1(v):
    return round(v * 10) / 10


def gin(lo, hi):
    """First / last 0.1 mm grid values inside [lo, hi] (snapping never breaks an edge distance)."""
    return math.ceil(lo * 10 - 1e-6) / 10, math.floor(hi * 10 + 1e-6) / 10


def on_grid(v):
    return abs(v * 10 - round(v * 10)) < 1e-6


# ------------------------------------------------------------------ helpers
def is_profile(p):
    return p.kind == "box" and p.mech.startswith("profile:")


def section(p):
    """(series, long axis index) of a profile part."""
    sec = p.mech.split(":")[1]
    return H.SECTION[sec][0], max(range(3), key=lambda i: p.s[i])


def body_of(p):
    """Name of the rigid body a part belongs to (hollow walls, bent brackets, cassette)."""
    if p is None:
        return ""
    n = p.name
    if n.startswith("gb_"):
        for suf in ("_tab", "_floor", "_riser"):
            if n.endswith(suf):
                return n[: -len(suf)]
    for suf in ("_wall_front", "_wall_back", "_wall_left", "_wall_right", "_wall_top", "_floor", "_flange"):
        if n.endswith(suf):
            return n[: -len(suf)]
    if n.startswith("stacker_") and n[-2:] in ("_a", "_b") and n.count("_") == 2:
        return "stacker_" + n.split("_")[1]                       # twin belt strands of the bought conveyor
    if n.startswith("stacker_frame_"):
        return "stacker_" + n[len("stacker_frame_"):]            # bought transfer conveyor: belt + frame
    if n.startswith("cassette_") and ("_pawl_" in n or "_lug_" in n):
        return n.rsplit("_", 2)[0]
    if n.startswith("reject_bin_brush"):
        return "reject_bin"                                       # bristle strips bonded into the bin rim
    if n.startswith("abox_floor"):
        return "abox_floor"                                       # one machined plate with 3 cutouts
    if n.startswith("br_") and n.endswith(("_leg1", "_leg2")):
        return n[:-5]
    return n


MATERIAL = (           # hw / name keyword -> thread class
    ("TABLE_PLATE", "AlMgSi_T6"), ("GUIDE_BAR", "steel"), ("HFS", "AlMgSi_T5"), ("POM", "POM"),
    ("sheet-steel", "sheet"), ("mounting plate", "sheet"), ("sheet funnel", "sheet"), ("bracket 3 mm", "sheet"), ("L bracket", "AlMgSi_T6"),
    ("insulated", "insert"), ("PC ", "insert"), ("PP ", "insert"), ("silicone", "insert"), ("CFK", "insert"),
    ("plate", "AlMgSi_T6"), ("Al ", "AlMgSi_T6"), ("DRIVE_UNIT", "AlMgSi_T6"), ("block", "AlMgSi_T6"),
    ("ISO6432", "steel"), ("MGN", "steel"), ("17HS", "AlMgSi_T6"), ("slide", "steel"),
)
INSERT_LEN = 10.0    # threaded insert length in plastics / panels [typ]


def material(p):
    key = p.hw + " " + p.name
    for k, m in MATERIAL:
        if k in key:
            return m
    return "AlMgSi_T6"


def bought_thread(p):
    for k, v in H.BOUGHT_THREAD.items():
        if k in p.hw:
            return v
    return None


def thick(p, n):
    b = p.aabb()
    return b[n + 3] - b[n]


# ------------------------------------------------------------------ contact
@dataclass
class Contact:
    a: object
    b: object
    n: int                     # face normal axis (0/1/2); -1 curved/line; -2 volume overlap
    lo: tuple = ()
    hi: tuple = ()
    kind: str = ""
    why: str = ""


def _touch(a, b):
    A, B = a.aabb(), b.aabb()
    d = [min(A[i + 3], B[i + 3]) - max(A[i], B[i]) for i in range(3)]
    if min(d) < -GAP:
        return None
    lo = tuple(max(A[i], B[i]) for i in range(3))
    hi = tuple(min(A[i + 3], B[i + 3]) for i in range(3))
    if a.kind == "box" and b.kind == "box":
        wide = [i for i in range(3) if d[i] > AREA]
        if len(wide) < 2:
            return None
        if len(wide) == 3:
            return Contact(a, b, -2, lo, hi)
        n = next(i for i in range(3) if i not in wide)
        return Contact(a, b, n, lo, hi)
    s, o = (a, b) if len(G.surface(a, 2.0)) < len(G.surface(b, 2.0)) else (b, a)
    ob = o.aabb()
    for pt in G.surface(s, 1.0):
        if ob[0] - GAP < pt[0] < ob[3] + GAP and ob[1] - GAP < pt[1] < ob[4] + GAP and ob[2] - GAP < pt[2] < ob[5] + GAP:
            if G.inside(o, pt) > -GAP:
                n = min(range(3), key=lambda i: d[i])
                # an axis-aligned cylinder's END face on a box face is a planar contact
                flat = d[n] < AREA and all(d[i] > AREA for i in range(3) if i != n)
                for q in (a, b):
                    if q.kind == "cyl" and "xyz".index(q.s[0]) != n:
                        flat = False
                    if q.kind in ("rod", "arc"):
                        flat = False
                return Contact(a, b, n if flat else -1, lo, hi)
    return None


def contacts(parts):
    items = sorted(parts, key=lambda p: p.aabb()[0])
    out = []
    for i, a in enumerate(items):
        A = a.aabb()
        for b in items[i + 1:]:
            if b.aabb()[0] > A[3] + GAP:
                break
            c = _touch(a, b)
            if c:
                out.append(c)
    return out


# ------------------------------------------------------------ classification
SLIDING = {("chain", "frame"), ("chain", "drive"), ("chain", "guide"),
           ("band", "chamber"), ("band", "frame"), ("band", "pan")}     # the mesh band on its skids / bed / pan

# Bought machines (2026-10-02): the band oven unit (band, drums, frame, chamber, elements, fans, hood) and the
# depositor + topping depositor come from an oven / depositor OEM as assembled units. Their INTERNAL joints
# are the OEM's (listed as a kit, screws not modelled); every joint between a unit and the rest of the
# machine - legs on the deck, the depositor on the band frame - is ours and proven like any other.
OEM_UNIT = {"M2_depositor": "wire-cut + topping depositor (OEM)", "M3_oven": "band oven unit (OEM)"}


def _oem(u, v):
    if u.module in OEM_UNIT and v.module in OEM_UNIT and not (J_PROFILE(u) and J_PROFILE(v)):
        return True
    return False


def J_PROFILE(p):
    return p.mech.startswith("profile:")

# Bought connection kits: contacts on curved faces or bought sub-assemblies, fastened by the
# vendor's kit. They carry load (support edges) and go into the BOM with their fastener count,
# but their screws are NOT modelled as solids - listed as such in every report.
KITS = (
    (lambda u, v: _oem(u, v) and u.module == v.module,
     "inside a bought unit: the OEM's own fastening (band oven unit / depositor)", "OEM", 0),
    (lambda u, v: _oem(u, v) and u.module != v.module,
     "depositor flange bolted to the band unit's side plates (OEM interface, 4 bolts)", "4x M6 (OEM)", 4),
    (lambda u, v: u.name.startswith("frame_") and u.kind == "box" and v.name.startswith("frame_") and v.kind == "arc",
     "bend-to-track connecting strip (bought), 2 per joint", "4x M5 T-nut", 4),
    (lambda u, v: u.name.startswith("leg_") and "curve" in u.name and v.name.startswith("frame_") and v.kind == "arc",
     "bend foot into the leg's end tap", "1x M8x30", 1),
    (lambda u, v: u.name.startswith("gb_") and "_curve_" in u.name and v.kind == "arc" and v.group == "frame",
     "guide bracket into a bend insert", "1x M5x10 button", 1),
    (lambda u, v: u.name.startswith("gb_") and "_curve_" in u.name and v.kind == "arc" and v.group == "guide",
     "guide bar onto its bracket", "1x M3x6", 1),
    (lambda u, v: "_heater_" in u.name and "_wall_" in v.name,
     "IR emitter end holder into the panel insert", "2x M4x10", 2),
    (lambda u, v: "_tc_" in u.name and v.name.endswith("_roof"),
     "thermocouple compression gland M8x1 in the roof", "1x gland", 1),
    (lambda u, v: "_curtain_" in u.name and v.name.endswith("_roof"),
     "curtain hem on a rod in 2 roof clips", "2x M4x10", 2),
    (lambda u, v: u.name.startswith("mag_empty_") and v.group == "magazine",
     "M12 sensor clamp on the tube", "1x clamp", 1),
    (lambda u, v: u.name == "M1_master_drive" and v.name == "M1_drive_unit",
     "gearbox on the drive unit's motor adapter flange (bought with the unit)", "4x M4x12", 4),
    # Upgrade S-1 guard
    (lambda u, v: u.group == "door" and v.name.startswith("guard_post"),
     "door leaf on 2 lift-off hinges into the hinge post (bought with the door kit)", "4x M5 T-nut", 4),
    (lambda u, v: u.group == "airlock_door" and v.group == "airlock_door",
     "door leaf in its guide track (bought kit)", "-", 0),
    (lambda u, v: u.group == "airlock_door" and (v.name.startswith(("guard_post", "guard_panel", "aout_post"))),
     "sliding airlock door kit: guide rails bolted through the panel into the frame (bought kit)", "6x M5 T-nut", 6),
    (lambda u, v: u.group == "operator" and u.kind == "cyl" and v.name.startswith("guard_panel"),
     "operator head in a 22.5 mm panel hole, ring nut (IEC 60947-5-5)", "1x ring nut", 1),
    (lambda u, v: u.group == "operator" and u.name.endswith("_block") and v.name.startswith("guard_panel"),
     "contact block clipped to the head's adapter through the panel", "1x clip adapter", 1),
)
INCIDENTAL = (
    (lambda u, v: u.name.startswith("gb_") and "_curve_" not in u.name and v.kind == "arc",
     "straight-run bracket beside the bend end"),
    (lambda u, v: "_curtain_" in u.name and "_wall_" in v.name, "curtain edge beside the wall"),
    (lambda u, v: u.name.startswith("collar_") and v.name.startswith("collar_"), "neighbouring collars touch"),
    (lambda u, v: u.name.startswith("stacker_rod") and v.name == "TABLE", "push rod in its deck hole"),
    (lambda u, v: u.name.startswith("reject_bin_brush") and (v.name == "TABLE" or v.group in ("sensor", "reject")),
     "brush strip wipes the deck underside / passes beside it"),
    (lambda u, v: u.group == "airlock_door" and u.joint and v.name == "TABLE",
     "sliding door leaf runs in its floor guide (never screwed down - found by the motion sweep)"),
    (lambda u, v: u.name.startswith("lc_") and v.name == "TABLE",
     "light-curtain bar stands on the deck, held by its brackets on the post"),
    (lambda u, v: u.name.startswith("guard_panel") and (v.group == "hopper"),
     "guard panel in front of the hopper / singulator plate (no screw into a food-contact part)"),
)


def CARRY(u, v, why):
    """True if u carries v in a one-way relation (v cannot carry u)."""
    un, vn = u.name, v.name
    if "chute starts in its outlet stub" in why:
        return un.startswith("chute_stub")
    if "chute end sits in its funnel collar" in why:
        return un.startswith("collar_")
    if "collar slid onto the tube top" in why:
        return u.group == "magazine"
    if "tube sits in its bore" in why:
        return u.group == "escapement"
    if "hangs on the bar by its lugs" in why:
        return un.startswith("shuttle_bar")
    if "reel on its spindle" in why:
        return "_spindle_" in un
    if "chain runs" in why:
        return u.group != "chain"
    if "disc / shaft / gearbox output" in why:
        return not un.startswith("singulator_") or un.startswith(("singulator_shaft", "singulator_plate"))
    return False


def classify(c):
    """(kind, reason) for a contact. Every rule here is a design statement."""
    a, b = c.a, c.b
    why = M.allowed(a, b)
    if a.group in PRODUCT or b.group in PRODUCT:
        return "incidental", "product"
    if c.n == -2:
        return ("kinematic", why) if why else ("incidental", "overlap without declaration (interference() owns it)")
    if body_of(a) == body_of(b):
        return "body", "one bent / welded / bonded body"
    if (a.group, b.group) in SLIDING or (b.group, a.group) in SLIDING:
        return "sliding", "chain runs on its track / between its guides"
    if why:
        return "kinematic", why
    for u, v in ((a, b), (b, a)):
        for pred, desc, spec, n in KITS:
            if pred(u, v):
                return "kit", f"{desc} ({spec})"
        for pred, desc in INCIDENTAL:
            if pred(u, v):
                return "incidental", desc
        un, vn = u.name, v.name
        if un.startswith("shuttle_block") and vn.startswith("shuttle_rail"):
            return "kinematic", "MGN block on its rail"
        if un == "stamp_block" and vn == "stamp_rail":
            return "kinematic", "MGN block on its rail"
        if un.startswith("shuttle_bar") and "_lug_" in vn:
            return "resting", "cassette hangs on the bar by its lugs (locating pins)"
        if un.startswith("mag_") and u.group == "magazine" and vn.startswith("esc_") and v.group == "escapement":
            return "resting", "tube sits in its bore in the escapement block (clamp screw)"
        if un.startswith("collar_") and v.group == "magazine":
            return "resting", "collar slid onto the tube top"
        if rod_bore(u) and (vn.endswith(("_cyl", "_cylinder")) or vn.startswith("stacker_lift")):
            return "kinematic", "piston rod in its cylinder"
        if rod_bore(u):
            return "rod", "piston rod thread in the driven part"
        if un.startswith("singulator_") and not un.startswith("singulator_plate") and u.kind == "cyl":
            if vn.startswith(("singulator_plate", "singulator_shaft", "M_singulator")):
                return "kinematic", "disc / shaft / gearbox output"
            if vn.startswith("hopper_"):
                return "incidental", "disc runs under the hopper floor"
        if u.group == "guide" and v.group == "guide":
            return "body", "arc guide butt-spliced to the straight guide (pinned splice plate)"
        if u.group == "cassette" and v.group in ("cassette", "stacker", "sensor", "gantry") and not vn.startswith("shuttle_bar"):
            return "incidental", "cassette passes / stands beside it"
        if u.group == "chain":
            return "incidental", "chain passes it"
        if un.startswith("kick_paddle") and vn.startswith("kick_cyl"):
            return "incidental", "paddle 1 mm off the cylinder nose"
        if un.startswith(("stamp_spindle", "stamp_coupling")) and \
                vn.startswith(("stamp_bearing", "stamp_coupling", "M_stamp", "stamp_nut", "stamp_motor_bracket")):
            return "kinematic", "spindle / coupling / motor shaft (passes through, bearings carry it)"
        if un.startswith("sealer_") and "_spindle_" in un and "_reel_" in vn:
            return "kinematic", "reel on its spindle"
    if c.n < 0:
        return "unresolved", "line / curved contact without a rule"
    return "fastened", "rule"


# ------------------------------------------------------------------ fasteners
@dataclass
class Fastener:
    joint: str
    thread: str
    head_type: str
    length: float
    head: tuple                # centre of the head's bearing face (csk: the top surface)
    axis: tuple                # unit vector from the head into the joint
    clamp: float               # clamped length under the head (incl. washer)
    washer: bool
    into: str                  # part name, 'TNUT:<type>' or 'NUT'
    engage: float
    need: float
    tip_room: float            # >= 0: tip clear of the bottom / floor / far side
    hole: float                # ISO 273 clearance hole in the clamped part(s)
    edge: float                # smallest hole-centre-to-edge distance in the clamped part(s)
    through: tuple = ()        # names the shank passes (get holes)
    nut: str = ""
    cbore: float = 0.0         # counterbore depth: the head sits this far inside the clamped part
    slot_ax: int = -1          # T-nut: the axis its slot runs along (the nut's long side)
    series: int = 0            # T-nut: profile series (lip depth)

    def solids(self, tag=""):
        dk, k, _ = H.head(self.thread, self.head_type)
        i = [abs(v) for v in self.axis].index(1.0)
        ax = "xyz"[i]
        sgn = self.axis[i]
        out = []
        h = list(self.head)
        h[i] += sgn * self.cbore                          # the part's bearing surface (counterbore floor)
        wh = H.THREAD[self.thread]["washer"][2] if self.washer else 0.0
        hb = h[i] - sgn * wh                              # under the head (on the washer)
        if self.head_type != "csk":
            p = list(h)
            p[i] = hb - k if sgn > 0 else hb
            out.append(M.Part(f"{tag}head", "", "fastener", "cyl", tuple(p), (ax, k, dk)))
        if self.washer:
            w = H.THREAD[self.thread]["washer"]
            p = list(h)
            p[i] = hb if sgn > 0 else h[i]
            out.append(M.Part(f"{tag}washer", "", "fastener", "cyl", tuple(p), (ax, w[2], w[1])))
        p = list(h)
        p[i] = hb if sgn > 0 else hb - self.length
        out.append(M.Part(f"{tag}shank", "", "fastener", "cyl", tuple(p), (ax, self.length, H.THREAD[self.thread]["d"])))
        if self.nut == "ISO4032":
            s_, m_ = H.THREAD[self.thread]["nut"]
            p = list(h)
            far = hb + sgn * self.clamp
            p[i] = far if sgn > 0 else far - m_
            out.append(M.Part(f"{tag}nut", "", "fastener", "cyl", tuple(p), (ax, m_, s_ * 1.155)))
        if self.nut.startswith("TN") and self.slot_ax >= 0:
            tn = H.TNUT[self.nut]
            face = hb + sgn * self.clamp                        # the profile's outer face
            a0 = face + sgn * H.PROFILE[self.series]["lip"]
            # drop-in T-nut, stepped like its chamfered flanks: full width under the lip, half width below
            for k_, (d0, hh, wf) in enumerate(((0.0, tn["h"] / 2, 1.0), (tn["h"] / 2, tn["h"] / 2, 0.5))):
                lo, sz = [0.0] * 3, [0.0] * 3
                s0 = a0 + sgn * d0
                lo[i], sz[i] = (s0, hh) if sgn > 0 else (s0 - hh, hh)
                for j_ in range(3):
                    if j_ == i:
                        continue
                    ln = tn["l"] if j_ == self.slot_ax else tn["w"] * wf
                    lo[j_], sz[j_] = h[j_] - ln / 2, ln
                out.append(M.Part(f"{tag}tnut{k_}", "", "fastener", "box", tuple(lo), tuple(sz)))
        return out


def _vec(n, sgn):
    v = [0.0, 0.0, 0.0]
    v[n] = float(sgn)
    return tuple(v)


def _design(thread, head_type, clamp_t, into, cb_ok=False):
    """Every valid (length, washer, clamp, engage, need, tip_room, nut, cbore) for a screw through
    clamp_t into `into` = ('TNUT', series, tnut) | ('TAP', part, depth, through_ok) | ('NUT',).
    cb_ok: the clamped part is machined, so the head may sit in a counterbore (>= 3 mm left)."""
    # a counterbore at most recesses the head 2 mm below the surface; plain holes first, then the shortest screw
    kmax = H.head(thread, head_type)[1] + 2.0
    return sorted([r for r in _design1(thread, head_type, clamp_t, into, cb_ok) if r[7] <= kmax],
                  key=lambda r: (r[7] > 0, r[0], r[7]))


def _design1(thread, head_type, clamp_t, into, cb_ok):
    return [r + (0.0,) for r in _design0(thread, head_type, clamp_t, into)] + \
        ([r + (round(clamp_t - r[2] + (H.THREAD[thread]["washer"][2] if r[1] else 0.0), 1),)
          for cb in [x * 0.5 for x in range(1, int((clamp_t - 3.0) / 0.5) + 1)] if cb <= 40
          for r in _design0(thread, head_type, clamp_t - cb, into) if not r[1]]
         if cb_ok and head_type == "socket" and clamp_t >= 6.0 else [])


def _design0(thread, head_type, clamp_t, into):
    t = H.THREAD[thread]
    dk, k, lengths = H.head(thread, head_type)
    out = []
    for washer in ((False,) if head_type == "csk" else (False, True)):
        c = clamp_t + (t["washer"][2] if washer else 0.0)
        if head_type == "csk" and clamp_t < k + 0.5:
            continue                                     # countersink needs the material
        if into[0] == "TNUT":
            prof = H.PROFILE[into[1]]
            tn = H.TNUT[into[2]]
            need = 0.8 * t["d"]                          # ISO 898-2 engaged nut length
            for Ln in lengths:
                eng = min(tn["h"], Ln - c - prof["lip"])
                room = (c + prof["depth"] - 0.2) - Ln
                if eng >= need - 1e-6 and room >= 0:
                    out.append((float(Ln), washer, c, eng, need, room, into[2]))
        elif into[0] == "TAP":
            part, depth, through_ok = into[1], into[2], into[3]
            bt = bought_thread(part)
            mat = material(part)
            if bt:
                depth, mat = min(depth, bt[1]), bt[2]
            if mat == "insert":
                need = min(H.MIN_ENGAGE["steel"] * t["d"], INSERT_LEN)
                depth = min(depth, INSERT_LEN)
            elif mat == "sheet":
                continue
            else:
                need = H.MIN_ENGAGE[mat] * t["d"]
            for Ln in lengths:
                eng = min(Ln - c, depth)
                # a bought part's thread depth is usable to its end (the drill goes deeper);
                # a hole we tap ourselves keeps 0.5 mm; a through-tapped hole may let the tip out 2 mm
                room = (c + depth + (2.0 if through_ok else (0.0 if bt else -0.5))) - Ln
                if eng >= need - 1e-6 and room >= 0:
                    out.append((float(Ln), washer, c, eng, need, room, ""))
        elif into[0] == "NUT":
            s_, m_ = t["nut"]
            for Ln in lengths:
                room = Ln - (c + m_ + 2 * t["P"])        # at least 2 threads past the nut
                if room >= 0:
                    out.append((float(Ln), washer, c, m_, 0.8 * t["d"], room, "ISO4032"))
                    break
    return out


class World:
    """Everything a fastener or bracket may collide with, in a spatial hash."""

    def __init__(self, parts):
        self.cell = 100.0
        self.grid = defaultdict(list)
        for p in parts:
            self.add(p)

    def add(self, p):
        for key in self._keys(p.aabb()):
            self.grid[key].append(p)

    def remove(self, p):
        for key in self._keys(p.aabb()):
            self.grid[key] = [q for q in self.grid[key] if q is not p]

    def _keys(self, b):
        c = self.cell
        for i in range(int(b[0] // c), int(b[3] // c) + 1):
            for j in range(int(b[1] // c), int(b[4] // c) + 1):
                for k in range(int(b[2] // c), int(b[5] // c) + 1):
                    yield (i, j, k)

    def near(self, b):
        seen = set()
        for key in self._keys(b):
            for p in self.grid[key]:
                if id(p) not in seen:
                    seen.add(id(p))
                    yield p

    def hits(self, s, exempt):
        b = s.aabb()
        for p in self.near(b):
            if p.name in exempt or getattr(p, "_joint", None) in exempt or body_of(p) in exempt:
                continue
            if G.aabb_overlap(b, p.aabb()) and G.interfere(s, p):
                return p.name
        return None


HEAD_ORDER = ("socket", "button", "csk")


class Build:
    def __init__(self, parts):
        self.parts = parts
        self.by = {p.name: p for p in parts}
        self.fasteners = []
        self.brackets = []
        self.joints = []
        self.fails = []
        self.rodends = []
        self.partners = defaultdict(set)      # declared overlap partners (kinematic, allowed())
        self.kits = []
        self.world = World(list(parts))          # static product (stacks, tube cookies) is an obstacle too

    def parts_by(self, name):
        return self.by.get(name)

    def body_box(self, p):
        """AABB of the rigid body p belongs to (walls + floor of a hollow count together)."""
        bn = body_of(p)
        mem = [q.aabb() for q in self.parts if q is not DECK and body_of(q) == bn] or [p.aabb()]
        return tuple(min(b[i] for b in mem) for i in range(3)) + tuple(max(b[i + 3] for b in mem) for i in range(3))

    # --- one screw: try heads / washers / lengths until one fits and hits nothing
    def screw(self, jid, thread, clamp_t, head_pt, axis, into, edge, through, exempt, heads=HEAD_ORDER, cb_ok=False):
        for ht in heads:
            for (Ln, washer, c, eng, need, room, nut, cb) in _design(thread, ht, clamp_t, into, cb_ok):
                intoname = ("TNUT:" + into[2]) if into[0] == "TNUT" else (into[1].name if into[0] == "TAP" else "NUT")
                f = Fastener(jid, thread, ht, Ln, tuple(g1(v) for v in head_pt), axis, c, washer, intoname, eng, need,
                             room, H.clearance(thread), edge, tuple(through), nut, cb,
                             into[3] if into[0] == "TNUT" and len(into) > 3 else -1,
                             into[1] if into[0] == "TNUT" else 0)
                if all(self.world.hits(s, exempt) is None and _on_deck(s) for s in f.solids()):
                    return f
        return None

    def commit(self, fs):
        for f in fs:
            self.fasteners.append(f)
            f._solids = []
            for s in f.solids():
                s.name = f"F{len(self.fasteners)}:{f.joint}:{s.name}"
                s._joint = f.joint
                self.world.add(s)
                f._solids.append(s)

    def uncommit(self, f):
        """Take a fastener back out completely (list AND collision world)."""
        self.fasteners.remove(f)
        for s in f._solids:
            self.world.remove(s)

    # --- corner brackets
    def bracket_parts(self, name, module, series, heel, n, m, lat, lat_c):
        br = H.BRACKET[H.PROFILE[series]["bracket"]]
        a, b, t = br["a"], br["b"], br["t"]
        (ni, ns), (mi, ms) = n, m
        lo, sz = [0.0] * 3, [0.0] * 3
        lo[ni], sz[ni] = (heel[ni], t) if ns > 0 else (heel[ni] - t, t)
        lo[mi], sz[mi] = (heel[mi], a) if ms > 0 else (heel[mi] - a, a)
        lo[lat], sz[lat] = lat_c - b / 2, b
        p1 = M.Part(f"{name}_leg1", module, "bracket", "box", tuple(g1(v) for v in lo), tuple(sz), "#9aa3ab",
                    hw=H.PROFILE[series]["bracket"])
        lo, sz = [0.0] * 3, [0.0] * 3
        lo[mi], sz[mi] = (heel[mi], t) if ms > 0 else (heel[mi] - t, t)
        lo[ni], sz[ni] = (heel[ni] + t, a - t) if ns > 0 else (heel[ni] - a, a - t)
        lo[lat], sz[lat] = lat_c - b / 2, b
        p2 = M.Part(f"{name}_leg2", module, "bracket", "box", tuple(g1(v) for v in lo), tuple(sz), "#9aa3ab",
                    hw=H.PROFILE[series]["bracket"])
        return p1, p2, br

    def bracket_joint(self, jid, E, S, n, face_c, ser, m, lat, lat_c, s_into, e_into):
        """Bracket in the corner between S's face (normal n, coordinate face_c) and E's
        face (normal m). s_into / e_into: ('TNUT', series) or ('TAP', part, depth, through_ok)."""
        (ni, ns), (mi, ms) = n, m
        Eb = E.aabb()
        heel = [0.0] * 3
        heel[ni] = face_c
        heel[mi] = Eb[mi + 3] if ms > 0 else Eb[mi]
        heel[lat] = lat_c
        p1, p2, br = self.bracket_parts(f"br_{jid}", E.module, ser, heel, n, m, lat, lat_c)
        ex = {E.name, S.name, p1.name, p2.name, body_of(E), body_of(S)}
        for p in (p1, p2):
            if self.world.hits(p, ex):
                return False
        scr = br["screw"]
        edge = min(br["a"] - br["hole_at"], br["b"] / 2)
        heads = ("button",) if br["head"] == "button" else HEAD_ORDER
        into1 = ("TNUT", s_into[1], tnut_for(s_into[1], scr), section(S)[1]) if s_into[0] == "TNUT" else s_into
        into2 = ("TNUT", e_into[1], tnut_for(e_into[1], scr), section(E)[1]) if e_into[0] == "TNUT" else e_into
        for p in (p1, p2):                                # nothing leaves the deck
            if not _on_deck(p):
                return False
        h1 = list(heel)
        h1[mi] = heel[mi] + ms * br["hole_at"]
        h1[ni] = face_c + ns * br["t"]
        h2 = list(heel)
        h2[ni] = face_c + ns * br["hole_at"]
        h2[mi] = heel[mi] + ms * br["t"]
        for p in (p1, p2):
            p._joint = jid
            self.world.add(p)
        f1 = self.screw(jid, _fix(scr, into1), br["t"], h1, _vec(ni, -ns), into1, edge, (p1.name,), ex, heads)
        f2 = None
        if f1:
            self.commit([f1])
            f2 = self.screw(jid, _fix(scr, into2), br["t"], h2, _vec(mi, -ms), into2, edge, (p2.name,),
                            ex - {jid}, heads)
            if f2 and _pair_hit(f1, f2):
                f2 = None
            if not f2:
                self.uncommit(f1)
        if not (f1 and f2):
            self.world.remove(p1)
            self.world.remove(p2)
            return False
        self.brackets += [p1, p2]
        self.commit([f2])
        return True

    # --- rule: profile standing on the deck
    def profile_on_deck(self, c, E):
        ser, _ = section(E)
        Eb = E.aabb()
        cand = []
        for mi in (0, 1):
            lat = 1 - mi
            for ms in (-1, 1):
                for off in H.slot_offsets(E.s[lat], ser):
                    cand.append(((mi, ms), lat, (Eb[lat] + Eb[lat + 3]) / 2 + off))
        placed = 0
        want = 2 * len(H.slot_offsets(min(E.s[0], E.s[1]), ser))
        for m, lat, lc in cand:
            jid = f"{E.name}~TABLE~{'xy'[m[0]]}{'+' if m[1] > 0 else '-'}{placed}"
            if self.bracket_joint(jid, E, DECK, (2, 1), 0.0, ser, m, lat, lc,
                                  ("TAP", DECK, H.TABLE_PLATE["t"], True), ("TNUT", ser)):
                placed += 1
            if placed >= want:
                break
        return placed

    # --- rule: profile end / crossing on a profile face; plate edge on a profile face
    def corner(self, c, E, S, e_into):
        n = c.n
        Eb, Sb = E.aabb(), S.aabb()
        ns = 1 if Eb[n] >= Sb[n + 3] - GAP else -1
        face = Sb[n + 3] if ns > 0 else Sb[n]
        ser_s, ax_s = section(S)
        ser_e, ax_e = section(E) if is_profile(E) else (ser_s, n)
        placed = 0
        for ser in sorted({min(ser_e, ser_s), 20}, reverse=True):
            placed += self._corner(c, E, S, e_into, n, ns, face, ser, ser_e, ax_e, ser_s, ax_s, Eb, Sb)
            if placed:
                break
        return placed

    def _corner(self, c, E, S, e_into, n, ns, face, ser, ser_e, ax_e, ser_s, ax_s, Eb, Sb):
        br = H.BRACKET[H.PROFILE[ser]["bracket"]]
        placed = 0
        for mi in [i for i in range(3) if i != n]:
            lat = 3 - n - mi
            for ms in (-1, 1):
                edge_e = Eb[mi + 3] if ms > 0 else Eb[mi]
                room = (Sb[mi + 3] - edge_e) if ms > 0 else (edge_e - Sb[mi])
                if room < br["a"] - 1e-6:
                    continue
                if is_profile(E) and ax_e != n:          # crossing: E's slot must be at the E-leg hole
                    ez = face + ns * br["hole_at"]
                    if not any(abs(ez - ((Eb[n] + Eb[n + 3]) / 2 + o)) < 0.6 for o in H.slot_offsets(E.s[n], ser_e)):
                        continue
                if ax_s != mi:                           # S's slot must be at the S-leg hole
                    sm = edge_e + ms * br["hole_at"]
                    if not any(abs(sm - ((Sb[mi] + Sb[mi + 3]) / 2 + o)) < 0.6 for o in H.slot_offsets(S.s[mi], ser_s)):
                        continue
                s_lines = [(Sb[lat] + Sb[lat + 3]) / 2 + o for o in H.slot_offsets(S.s[lat], ser_s)] \
                    if ax_s != lat else None
                if is_profile(E) and ax_e != lat:
                    lines = [(Eb[lat] + Eb[lat + 3]) / 2 + o for o in H.slot_offsets(E.s[lat], ser_e)]
                    if s_lines is not None:
                        lines = [x for x in lines if any(abs(x - y) < 0.6 for y in s_lines)]
                elif s_lines is not None:
                    lines = [x for x in s_lines if c.lo[lat] + br["b"] / 2 - 1e-6 <= x <= c.hi[lat] - br["b"] / 2 + 1e-6]
                else:
                    lines = [g1((c.lo[lat] + c.hi[lat]) / 2)]
                for lc in lines:
                    jid = f"{E.name}~{S.name}~{'xyz'[mi]}{'+' if ms > 0 else '-'}{placed}"
                    if self.bracket_joint(jid, E, S, (n, ns), face, ser, (mi, ms), lat, lc, ("TNUT", ser_s),
                                          ("TNUT", ser_e) if is_profile(E) else e_into):
                        placed += 1
        return placed

    # --- rule: screws through D (or its flange) into T-nuts / an end tap / tapped holes / nuts of T
    def through(self, c, D, T, jid):
        n = c.n
        Db, Tb = D.aabb(), T.aabb()
        ns = 1 if Db[n] >= Tb[n + 3] - GAP else -1        # D sits on the +n side of T
        face = Tb[n + 3] if ns > 0 else Tb[n]
        t_d = thick(D, n)
        cb_ok = machined(D)
        # plates are clamped whole; a thick machined part gets a counterbore pocket; a thick bought
        # part is held through its 5 mm flange
        t = t_d if (t_d <= PLATE_T or cb_ok) and D.kind == "box" else 5.0
        others = [i for i in range(3) if i != n]
        span = [c.hi[i] - c.lo[i] for i in range(3)]
        exempt = {D.name, T.name, body_of(D), body_of(T)}
        if "MGN" in D.hw and "rail" in D.hw:
            exempt |= self.partners.get(D.name, set())      # the blocks ride over the rail's recessed heads
        cands, want, pat, into, thr = [], 1, False, None, None
        # ---- hole patterns of bought parts
        for q in (D, T):
            qb = q.aabb()
            cen = [(qb[i] + qb[i + 3]) / 2 for i in range(3)]
            if q.hw.startswith("17HS") and q.mech.startswith("motor:") and "xyz".index(q.mech[6]) == n:
                h_ = H.NEMA17["bolt_sq"] / 2
                thr = "M4" if "+" in q.hw else "M3"          # gearbox output face / bare motor face
                cands = [(g1(cen[others[0]] + a_ * h_), g1(cen[others[1]] + b_ * h_)) for a_ in (-1, 1) for b_ in (-1, 1)]
                pat = True
            elif "MGN" in q.hw and "block" in q.hw:
                mg = H.MGN[q.hw.split()[0]]
                along = max(others, key=lambda i: qb[i + 3] - qb[i])
                acr = [i for i in others if i != along][0]
                thr, pat = "M3", True
                for a_ in (-1, 1):
                    for b_ in (-1, 1):
                        p = {along: cen[along] + a_ * mg["C"] / 2, acr: cen[acr] + b_ * mg["B"] / 2}
                        cands.append((g1(p[others[0]]), g1(p[others[1]])))
            elif q is D and "MGN" in q.hw and "rail" in q.hw:
                mg = H.MGN[q.hw.split()[0]]
                along = max(others, key=lambda i: qb[i + 3] - qb[i])
                acr = [i for i in others if i != along][0]
                thr, pat, t = "M3", True, mg["rail_clamp"]
                x = qb[along] + mg["E"]
                while x <= qb[along + 3] - mg["E"] + 1e-6:
                    # a rail spanning several hosts (a split beam + the airlock header) is screwed into
                    # each host by the holes that lie over it
                    if c.lo[along] + 3.0 <= x <= c.hi[along] - 3.0:
                        p = {along: g1(x), acr: g1(cen[acr])}
                        cands.append((p[others[0]], p[others[1]]))
                    x += mg["P"]
                if not cands:
                    return 0, "no rail hole over this host"
            elif q is D and q.hw == "fan_80":
                h_ = H.LOADS["fan_80"]["holes"] / 2
                thr, pat, t = "M4", True, H.LOADS["fan_80"]["flange"]
                cands = [(g1(cen[others[0]] + a_ * h_), g1(cen[others[1]] + b_ * h_)) for a_ in (-1, 1) for b_ in (-1, 1)]
        if pat:
            want = len(cands)
            if bought_thread(D) and not bought_thread(T) and not ("MGN" in D.hw and "rail" in D.hw):
                return 0, "the bought part's threads face away (screw from its side)"
        # ---- into what
        if is_profile(T):
            ser, ax_t = section(T)
            if ax_t == n:                                  # the profile's END face: its core bore(s), tapped
                thr = H.PROFILE[ser]["core_tap"]
                into = ("TAP", T, H.END_TAP_DEPTH, False)
                u, v = others
                cands = [(g1((Tb[u] + Tb[u + 3]) / 2 + ou), g1((Tb[v] + Tb[v + 3]) / 2 + ov))
                         for ou in H.slot_offsets(T.s[u], ser) for ov in H.slot_offsets(T.s[v], ser)]
                want, pat = len(cands), True
            else:
                tn = H.PROFILE[ser]["tnut"]
                if thr:                                    # pattern thread in this slot
                    tn = next(k for k, v in H.TNUT.items() if v["slot"] == H.TNUT[tn]["slot"] and v["thread"] == thr)
                thr = H.TNUT[tn]["thread"]
                into = ("TNUT", ser, tn, ax_t)
                if not pat:
                    emin = H.EDGE_MIN * H.clearance(thr)
                    for lat in others:
                        run = 3 - n - lat
                        if run != ax_t:
                            continue
                        for off in H.slot_offsets(T.s[lat], ser):
                            lc = (Tb[lat] + Tb[lat + 3]) / 2 + off
                            if not (c.lo[lat] + emin - 1e-6 <= lc <= c.hi[lat] - emin + 1e-6):
                                continue
                            x, xe = gin(c.lo[run] + emin, c.hi[run] - emin)
                            step = max(2.0, g1((c.hi[run] - c.lo[run]) / 60))
                            while x <= xe + 1e-6:
                                pt = {lat: g1(lc), run: round(x, 1)}
                                cands.append((pt[others[0]], pt[others[1]]))
                                x += step
                    big = max(span[i] for i in others)
                    want = 1 if big <= 3 * emin else (2 if big <= 300 else int(big // 150) + 1)
        else:
            if not pat:
                small = min(span[i] for i in others)
                thr = "M6" if small >= 40 else ("M5" if small >= 25 else ("M4" if small >= 18 else "M3"))
                if T is DECK:
                    thr = H.TABLE_PLATE["anchor"] if small >= 30 else ("M5" if small >= 25 else "M4")
                emin = H.EDGE_MIN * H.clearance(thr)
                u, v = others
                su = max(2.0, g1((c.hi[u] - c.lo[u]) / 30))
                sv = max(2.0, g1((c.hi[v] - c.lo[v]) / 30))
                x, xe = gin(c.lo[u] + emin, c.hi[u] - emin)
                y0, ye = gin(c.lo[v] + emin, c.hi[v] - emin)
                while x <= xe + 1e-6:
                    y = y0
                    while y <= ye + 1e-6:
                        cands.append((round(x, 1), round(y, 1)))
                        y += sv
                    x += su
                want = 1 if small < 20 else (2 if max(span[u], span[v]) < 120 else 4)
            depth = thick(T, n) if T.kind != "arc" else T.s[1] - T.s[0]
            mat = material(T)
            if bought_thread(T):
                into = ("TAP", T, depth, False)
            elif T is DECK:
                into = ("TAP", T, depth, True)
            elif mat == "sheet" or (mat == "insert" and depth < INSERT_LEN + 0.5) or \
                    (mat != "insert" and depth < H.MIN_ENGAGE.get(mat, 1.5) * H.THREAD[thr]["d"] + 0.5):
                into = ("NUT",)
            else:
                into = ("TAP", T, depth, False)
        emin = H.EDGE_MIN * H.clearance(thr)
        order = cands if pat else _spread_pts(cands, max(want * 12, 24))
        chosen = []
        for (cu, cv) in order:
            if len(chosen) >= want:
                break
            h = [0.0] * 3
            h[n] = face + ns * t
            h[others[0]], h[others[1]] = cu, cv
            bodyb = self.body_box(D)
            ref = (bodyb[others[0]], bodyb[others[1]], bodyb[others[0] + 3], bodyb[others[1] + 3]) \
                if t_d <= PLATE_T or cb_ok else \
                (c.lo[others[0]], c.lo[others[1]], c.hi[others[0]], c.hi[others[1]])
            if D.kind != "box":
                ref = (c.lo[others[0]], c.lo[others[1]], c.hi[others[0]], c.hi[others[1]])
            edge = min(cu - ref[0], ref[2] - cu, cv - ref[1], ref[3] - cv)
            if "MGN" in D.hw and "rail" in D.hw:
                edge = min(edge, H.MGN[D.hw.split()[0]]["rail"][0] / 2)
            if edge < emin - 1e-6:
                if pat:
                    return 0, f"pattern hole at {tuple(round(q, 1) for q in h)} is {edge:.1f} mm from an edge"
                continue
            f = self.screw(jid, thr, t, h, _vec(n, -ns), into, edge, (D.name,), exempt, cb_ok=cb_ok)
            if f and all(not _pair_hit(f, g) for g in chosen):
                chosen.append(f)
            elif pat:
                return 0, f"pattern hole at {tuple(round(q, 1) for q in h)}: no valid screw / it hits something"
        if not chosen:
            return 0, f"no screw position on a {span[others[0]]:.1f} x {span[others[1]]:.1f} patch"
        self.commit(chosen)
        return len(chosen), ""

    # --- rule: a thin panel standing on the deck -> corner brackets along its length
    def panel_on_deck(self, c, P):
        pb = P.aabb()
        thin = 0 if P.s[0] < P.s[1] else 1
        long_ = 1 - thin
        L_ = P.s[long_]
        k = max(2, int(math.ceil((L_ - 60) / 250.0)) + 1)
        pos = [g1(pb[long_] + 30 + (L_ - 60) * j / (k - 1)) for j in range(k)]
        placed = 0
        for lc in pos:
            for ms in (-1, 1):
                jid = f"{P.name}~TABLE~{placed}"
                if self.bracket_joint(jid, P, DECK, (2, 1), 0.0, 20, (thin, ms), long_, lc,
                                      ("TAP", DECK, H.TABLE_PLATE["t"], True), ("TAP", P, P.s[thin], False)):
                    placed += 1
                    break
        return placed

    # --- rule: a piston rod's thread in the part it drives (tapped, or through + lock nut)
    def rod_end(self, c, rod, part):
        bore = rod_bore(rod)
        th = H.CYL[bore]["rod_thread"]
        d = float(th[1:].split("x")[0])
        mat = material(part)
        need = (H.MIN_ENGAGE.get(mat, 1.5) if mat not in ("insert", "sheet") else 2.5) * d
        depth = thick(part, c.n) - 0.5
        how = "tapped" if depth >= need else ("through + ISO 4035 lock nut" if thick(part, c.n) >= 2 else "")
        self.rodends.append((rod.name, part.name, th, round(min(depth, 1.5 * d), 1), round(need, 1), how))
        return 1 if how else 0


PLATE_T = 16.0       # a part this thin (along the screw) is clamped whole; thicker ones by a 5 mm flange


def machined(p):
    """A part we machine ourselves (a head may sit in a counterbore)."""
    return any(k in p.hw for k in ("plate", "block", "bar")) and material(p) not in ("sheet", "insert")


ROD_BORE = (("stamp_rod", "STAMP_CYL"), ("kick_rod", "KICK_CYL"), ("sealer_", "SEAL_CYL"), ("stacker_rod", "STACK_CYL"))


def rod_bore(p):
    for pre, key in ROD_BORE:
        if p.name.startswith(pre) and p.name.endswith("_rod") or (pre == "stacker_rod" and p.name.startswith(pre)):
            return L[key][0]
    return None


def _on_deck(p):
    b = p.aabb()
    return b[0] >= -1e-6 and b[1] >= -1e-6 and b[3] <= L["TABLE"][0] + 1e-6 and b[4] <= L["TABLE"][1] + 1e-6


def tnut_for(series, thread):
    """The T-nut of this profile series' slot for this thread."""
    slot = H.TNUT[H.PROFILE[series]["tnut"]]["slot"]
    return next(k for k, v in H.TNUT.items() if v["slot"] == slot and v["thread"] == thread)


def _fix(scr, into):
    """Bracket screw thread matched to the T-nut in that slot."""
    if into[0] == "TNUT":
        return H.TNUT[into[2]]["thread"]
    return scr


def _pair_hit(f, g):
    for s in f.solids():
        for t in g.solids():
            if G.aabb_overlap(s.aabb(), t.aabb()) and G.interfere(s, t):
                return True
    return False


def _spread_pts(pts, k):
    """Farthest-point ordering of candidate positions (first = a corner-most one)."""
    if len(pts) <= 2:
        return list(pts)
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    first = max(pts, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
    sel = [first]
    dmin = [math.dist(p, first) for p in pts]
    while len(sel) < min(k, len(pts)):
        i = max(range(len(pts)), key=lambda j: dmin[j])
        if dmin[i] <= 0:
            break
        sel.append(pts[i])
        for j, p in enumerate(pts):
            dmin[j] = min(dmin[j], math.dist(p, pts[i]))
    return sel


def _spread(fs, k):
    """Order fasteners by farthest-point sampling (spread the pattern)."""
    if len(fs) <= 2:
        return fs
    sel = [fs[0]]
    rest = fs[1:]
    while rest and len(sel) < k:
        best = max(rest, key=lambda f: min(math.dist(f.head, g.head) for g in sel))
        sel.append(best)
        rest.remove(best)
    return sel


# ------------------------------------------------------------------ mounts
STRUCT = ("frame", "portal", "gantry", "hood", "oven", "cool", "sealer", "traymag", "lane", "axis", "reject", "drive")


def derive_mounts(B, parts, supported):
    """A sensor / camera that touches no structure gets a mount: a 3 mm bracket
    (<= 60 mm) or a 2020 stand, the shortest one that collides with nothing."""
    out = []
    targets = [p for p in parts if (p.group in STRUCT or is_profile(p)) and p.kind == "box"] + [DECK]
    for d in parts:
        if d.name in supported or d.group not in ("sensor", "vision"):
            continue
        b = d.aabb()
        best = None
        for n in range(3):
            for s in (-1, 1):
                lat = [i for i in range(3) if i != n]
                start = b[n + 3] if s > 0 else b[n]
                for t in targets:
                    tb = t.aabb()
                    face = tb[n] if s > 0 else tb[n + 3]
                    dist = (face - start) * s
                    if dist < 1e-6 or dist > 400:
                        continue
                    for stand in ((False, True) if dist <= 60 else (True,)):
                        lo, sz = [0.0] * 3, [0.0] * 3
                        ok = True
                        for i in lat:
                            if stand:
                                c_ = (b[i] + b[i + 3]) / 2
                                lo[i], sz[i] = c_ - 10, 20.0
                            else:
                                lo[i], sz[i] = b[i], b[i + 3] - b[i]
                            if t is not DECK and not (tb[i] <= lo[i] + 1e-6 and tb[i + 3] >= lo[i] + sz[i] - 1e-6):
                                ok = False
                        if not ok:
                            continue
                        lo[n] = start if s > 0 else face
                        sz[n] = dist
                        arm = M.Part(f"mount_{d.name}", d.module, "mount", "box", tuple(g1(v) for v in lo),
                                     tuple(g1(v) for v in sz), "#9aa3ab",
                                     mech="profile:2020" if stand else "",
                                     hw="HFS5-2020 stand" if stand else "sensor bracket 3 mm S235")
                        if B.world.hits(arm, {d.name, t.name, arm.name}) or not _on_deck(arm):
                            continue
                        if best is None or dist < best[0]:
                            best = (dist, arm, t)
        if best:
            out.append((d, best[1], best[2]))
            best[1]._joint = f"mount_{d.name}"
            B.world.add(best[1])
    return out


# ------------------------------------------------------------------ solve
def solve():
    parts = [p for p in M.build(with_product=False)]
    B = Build([DECK] + parts)
    cs = contacts([DECK] + parts)
    kinds = defaultdict(list)
    for c in cs:
        c.kind, c.why = classify(c)
        kinds[c.kind].append(c)
    support = defaultdict(set)                  # support[a] = the parts a CARRIES (load path is directional)

    def link(a, b):
        support[a].add(b)
        support[b].add(a)

    def carries(c):
        """(carrier, carried) for a one-way relation, or None if it is rigid both ways."""
        for u, v in ((c.a, c.b), (c.b, c.a)):
            if CARRY(u, v, c.why):
                return u.name, v.name
        return None

    for k in ("body", "kinematic", "sliding", "resting"):
        for c in kinds[k]:
            one = carries(c)
            if one:
                support[one[0]].add(one[1])
            elif k == "sliding" or k == "resting":
                # a slide / a rest carries the part on top; never the other way
                lo, hi = (c.a, c.b) if c.a.aabb()[2] <= c.b.aabb()[2] else (c.b, c.a)
                support[lo.name].add(hi.name)
            else:
                link(c.a.name, c.b.name)
    for c in kinds["kinematic"]:
        B.partners[c.a.name].add(c.b.name)
        B.partners[c.b.name].add(c.a.name)
    for c in kinds["kit"]:
        link(c.a.name, c.b.name)
        n_ = next(n for pred, desc, spec, n in KITS if desc in c.why)
        B.kits.append((c.a.name, c.b.name, c.why, n_))
    for c in kinds["rod"]:
        rod, part = (c.a, c.b) if rod_bore(c.a) else (c.b, c.a)
        if B.rod_end(c, rod, part):
            link(c.a.name, c.b.name)
        else:
            B.fails.append(f"ROD END {rod.name} in {part.name}: thread cannot engage")
    for c in kinds["unresolved"]:
        B.fails.append(f"NO RULE line/curved contact {c.a.name} x {c.b.name}")
    # delta motors hang under their base by a bought NEMA 17 L-bracket (the round envelope
    # touches the plate on a line, so the contact search cannot see a face)
    for p in parts:
        if "_motor_" in p.name and p.group.startswith("delta_"):
            base = p.name.split("_motor_")[0] + "_base"
            link(p.name, base)
            B.kits.append((p.name, base, "NEMA 17 L-bracket under the base plate (4x M3 + 2x M5)", 6))
    rules = defaultdict(int)
    # deck + profile structure first, then plates / devices; big patches first
    def bought(p):
        return p.hw.startswith("17HS") or "MGN" in p.hw or p.hw == "fan_80"

    order = sorted(kinds["fastened"], key=lambda c: (
        0 if "TABLE" in (c.a.name, c.b.name) and (is_profile(c.a) or is_profile(c.b)) else
        1 if is_profile(c.a) and is_profile(c.b) else 2 if bought(c.a) or bought(c.b) else 3,
        -sum(sorted([c.hi[i] - c.lo[i] for i in range(3)])[1:])))
    joined = set()
    failed = []
    for c in order:
        a, b = c.a, c.b
        pair = frozenset((body_of(a), body_of(b)))
        if pair in joined:
            rules["covered: the two bodies are already fastened elsewhere"] += 1
            continue
        pa, pb = is_profile(a), is_profile(b)
        k, err = 0, ""
        if "TABLE" in (a.name, b.name) and (pa or pb) and c.n == 2:
            E = a if pa else b
            k = B.profile_on_deck(c, E)
            rule = "profile on the deck: corner brackets"
        elif pa and pb:
            _, ax_a = section(a)
            _, ax_b = section(b)
            if ax_a == c.n:
                E, S = a, b
            elif ax_b == c.n:
                E, S = b, a
            else:
                E, S = (a, b) if a.aabb()[c.n] >= b.aabb()[c.n] - GAP else (b, a)
            k = B.corner(c, E, S, None)
            rule = "profile on a profile: corner brackets"
        elif pa or pb:
            S, D = (a, b) if pa else (b, a)
            if thick(D, c.n) > PLATE_T and "plate" in D.hw and section(S)[1] != c.n:
                k = B.corner(c, D, S, ("TAP", D, min(D.s), False))
                rule = "plate edge on a profile: corner brackets"
            else:
                k, err = B.through(c, D, S, f"{D.name}~{S.name}")
                rule = "end tap / T-nuts in a profile"
        else:
            D, T = (b, a) if (a.name == "TABLE" or thick(a, c.n) > thick(b, c.n)) else (a, b)
            if T.name == "TABLE" and c.n == 2 and min(D.s[0], D.s[1]) < 2 * H.EDGE_MIN * H.clearance("M4") and \
                    D.aabb()[2] >= -1e-6:
                k = B.panel_on_deck(c, D)
                rule = "panel on the deck: corner brackets"
            else:
                k, err = B.through(c, D, T, f"{D.name}~{T.name}")
                if not k and T.name != "TABLE":
                    k, err2 = B.through(c, T, D, f"{T.name}~{D.name}")
                    err = "" if k else f"{err} | reversed: {err2}"
                rule = "into the tapped deck" if T.name == "TABLE" else "into a tapped part / a nut"
        rules[rule] += 1
        if k:
            link(a.name, b.name)
            joined.add(pair)
            B.joints.append((f"{a.name}~{b.name}", a.name, b.name, rule, k))
        else:
            failed.append((c, rule, err))
    for br in B.brackets:
        e, s_ = br._joint.split("~")[:2]
        link(br.name, e)
        link(br.name, s_)
    reach = _reach(support)
    mounts = derive_mounts(B, parts, reach)
    for d, arm, t in mounts:
        B.brackets.append(arm)
        link(d.name, arm.name)
        link(arm.name, t.name)
        B.joints.append((f"{d.name}~{arm.name}~{t.name}", d.name, t.name, "derived mount", 2))
    # a failed contact between two parts that both hold on elsewhere is only a touch
    reach = _reach(support)
    B.touching = []
    for c, rule, err in failed:
        must = ("TABLE" in (c.a.name, c.b.name) and (is_profile(c.a) or is_profile(c.b))) or \
            any("MGN" in q.hw and "block" in q.hw for q in (c.a, c.b))
        if must:          # a post must be anchored to the deck; a guideway block must be bolted to its carriage
            B.fails.append(f"MUST FASTEN {c.a.name} x {c.b.name} ({rule}{': ' + err if err else ''})")
        elif frozenset((body_of(c.a), body_of(c.b))) in joined or (c.a.name in reach and c.b.name in reach):
            B.touching.append((c.a.name, c.b.name))
        else:
            B.fails.append(f"NO FASTENERS {c.a.name} x {c.b.name} ({rule}{': ' + err if err else ''})")
    return B, parts, cs, kinds, support, rules, mounts


def _reach(support):
    seen = {"TABLE"}
    st = ["TABLE"]
    while st:
        n = st.pop()
        for m in support[n]:
            if m not in seen:
                seen.add(m)
                st.append(m)
    return seen


# ------------------------------------------------------------------ proofs
def proofs(B, parts, support):
    """Independent re-check of everything the search produced."""
    fails = list(B.fails)
    reach = _reach(support)
    for p in parts + B.brackets:
        if p.group in PRODUCT:
            continue
        if p.name not in reach:
            fails.append(f"FLOATS {p.name} ({p.module}) - no fastened / guided path to the deck")
    for f in B.fasteners:
        _, _, lengths = H.head(f.thread, f.head_type)
        if f.length not in [float(x) for x in lengths]:
            fails.append(f"LENGTH {f.joint}: {f.thread}x{f.length:g} is not a stock length")
        if f.engage < f.need - 1e-6:
            fails.append(f"ENGAGE {f.joint}: {f.thread}x{f.length:g} engages {f.engage:.1f} < {f.need:.1f} mm")
        if f.tip_room < -1e-6:
            fails.append(f"BOTTOMS {f.joint}: {f.thread}x{f.length:g} by {-f.tip_room:.1f} mm")
        if abs(f.hole - H.clearance(f.thread)) > 1e-9:
            fails.append(f"ISO 273 {f.joint}: hole {f.hole} != medium {H.clearance(f.thread)}")
        if f.edge < H.EDGE_MIN * f.hole - 1e-6:
            fails.append(f"EDGE {f.joint}: hole {f.edge:.1f} mm from an edge < {H.EDGE_MIN} x {f.hole}")
        if not all(on_grid(v) for v in f.head):
            fails.append(f"GRID {f.joint}: fastener at {f.head} off the 0.1 mm grid")
        if f.head_type == "csk" and f.clamp < H.head(f.thread, "csk")[1]:
            fails.append(f"CSK {f.joint}: countersink deeper than the part")
    for b in B.brackets:
        if not all(on_grid(v) for v in list(b.p) + list(b.s)):
            fails.append(f"GRID {b.name} off the 0.1 mm grid")
    for rod, part, th, eng, need, how in B.rodends:
        if how == "tapped" and eng < need - 1e-6:
            fails.append(f"ROD END {rod} ({th}) in {part}: engages {eng} < {need}")
    # collisions, re-checked from scratch
    solids = []
    for k, f in enumerate(B.fasteners):
        for s in f.solids():
            s.name = f"F{k}:{f.joint}:{s.name}"
            s._f = f
            solids.append(s)
    world = World(list(parts) + [DECK] + B.brackets)
    for s in solids:                                       # nothing leaves the deck's plan outline
        if not _on_deck(s):
            fails.append(f"OFF DECK {s.name.split(':', 1)[1]} reaches past the table edge")
    for b in B.brackets:
        if not _on_deck(b):
            fails.append(f"OFF DECK {b.name} reaches past the table edge")
    for s in solids:
        f = s._f
        ex = set(f.through) | {f.into} | set(f.joint.split("~")[:2])
        ex |= {body_of(B.parts_by(x)) for x in ex if B.parts_by(x)}
        ex |= {br.name for br in B.brackets if getattr(br, "_joint", "") == f.joint}
        for x in f.through:
            q = B.parts_by(x)
            if q and "MGN" in q.hw and "rail" in q.hw:
                ex |= B.partners.get(x, set())
        for p in world.near(s.aabb()):
            if p.name in ex or body_of(p) in ex:
                continue
            if G.aabb_overlap(s.aabb(), p.aabb()) and G.interfere(s, p):
                fails.append(f"FASTENER {s.name.split(':', 1)[1]} hits {p.name}")
    fw = World(solids)
    for s in solids:
        for t in fw.near(s.aabb()):
            if t._f is s._f or id(t) <= id(s):
                continue
            if G.aabb_overlap(s.aabb(), t.aabb()) and G.interfere(s, t):
                fails.append(f"FASTENER {s.name.split(':', 1)[1]} hits {t.name.split(':', 1)[1]}")
    for b in B.brackets:
        j = getattr(b, "_joint", "")
        ex = {b.name} | set(j.split("~")[:2]) | {x.name for x in B.brackets if getattr(x, "_joint", None) == j}
        if b.name.startswith("mount_"):
            ex |= {b.name[6:]} | {jj[2] for jj in B.joints if jj[0].startswith(b.name[6:] + "~mount_")}
        ex |= {body_of(B.parts_by(x)) for x in list(ex) if B.parts_by(x)}
        for p in world.near(b.aabb()):
            if p is b or p.name in ex or body_of(p) in ex:
                continue
            if G.aabb_overlap(b.aabb(), p.aabb()) and G.interfere(b, p):
                fails.append(f"BRACKET {b.name} hits {p.name}")
    return sorted(set(fails))


def bom(B):
    by = defaultdict(int)
    for f in B.fasteners:
        std = {"socket": "ISO 4762", "button": "ISO 7380-1", "csk": "ISO 10642"}[f.head_type]
        by[(f"{std} {f.thread}x{f.length:g}", "screw")] += 1
        if f.washer:
            by[(f"ISO 7089 {f.thread[1:]}", "washer")] += 1
        if f.nut and f.nut.startswith("TN"):
            by[(f"T-nut {f.nut}", "nut")] += 1
        if f.nut == "ISO4032":
            by[(f"ISO 4032 {f.thread}", "nut")] += 1
    for b in B.brackets:
        if b.name.endswith("_leg1"):
            by[(b.hw, "bracket")] += 1
        if b.name.startswith("mount_"):
            by[(b.hw, "mount")] += 1
    return dict(sorted(by.items()))


def check(verbose=True):
    B, parts, cs, kinds, support, rules, mounts = solve()
    fails = proofs(B, parts, support)
    if verbose:
        print(f"joints: {len(cs)} contacts -> " + ", ".join(f"{k} {len(v)}" for k, v in sorted(kinds.items())))
        print("  fastened by rule: " + ", ".join(f"{v} x {k}" for k, v in sorted(rules.items())))
        print(f"  {len(B.fasteners)} fasteners, {sum(1 for b in B.brackets if b.name.endswith('_leg1'))} corner "
              f"brackets, {len(mounts)} derived mounts")
        for (k, _), v in bom(B).items():
            print(f"    {v:4d} x {k}")
        print("\n".join(fails[:60]) if fails else
              "ALL JOINT PROOFS PASS (nothing floats, engagement, no bottoming, stock lengths, ISO 273 + edge, "
              "no collisions, grid)")
        if len(fails) > 60:
            print(f"... {len(fails) - 60} more")
    return fails, B


if __name__ == "__main__":
    f, _ = check()
    sys.exit(1 if f else 0)
