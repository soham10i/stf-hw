"""
The VGR's motion, planned and then PROVEN collision-free along the whole path.

factory_layout.check_cross() only ever tested the arm parked AT a station. The
path between stations was never checked, and the viewer's scripted tour swung
the arm through the oven's Sauger portal at plunge 210 on its way there. This
module closes that gap:

  plan()   builds the tour from the solved stations and the real cookie heights
  check()  walks every leg of it in <=1 deg / <=2 mm steps and tests every
           moving VGR part (and the cookie it carries) against every part of the
           warehouse, the oven and the sorting line with an oriented-box SAT test

Every station visit uses the same four-phase approach, which is what makes it
safe near structures that sit ABOVE a hand-over (the oven portal, the belt hood):

  1. swing at TRANSIT with the arm retracted - above everything on the table
  2. descend OUTSIDE the station, still retracted
  3. extend horizontally to the station at the approach height
  4. plunge vertically to CONTACT: the cup's underside meets the cookie's top
     face and never goes below it. The last few mm are taken up by the spring
     stem (the carriage over-travels, the cup does not), which is what builds
     the vacuum seal - then the cookie lifts.

The viewer plays exactly these waypoints (exported as factory.vgr_plan), so the
animation is the proven path, not a separately-typed one.
"""
import math

import factory_layout as FL
import hbw_model as HM
import oven_model as OM
import sorting_model as SM
import vgr_model as VG
from variant import UP1, UP10

V = VG.V
CUP_DROP = 28.0          # cup underside = plunge - 28
APPROACH = 45.0          # approach height above contact, before the last plunge
OVERTRAVEL = 4.0         # carriage travel absorbed by the spring stem at contact
assert OVERTRAVEL < V["SPRING"]


# ------------------------------------------------------------------ heights
def cookie_tops():
    """z of the cookie's TOP face at each station - the contact plane."""
    P = HM.P
    mould_base = 8.0                                    # moulds.size[2]
    wp = SM.S["WP_H"]
    tops = {
        "belt": P["CV_SURF"] + mould_base + wp,         # in its mould on the belt
        "oven": OM.CUP_TARGETS[OM.O["SAUGER"][0]],      # on the extended tray
    }
    for col, (_, _, z) in SM.handover_points().items():
        tops[f"bay_{col}"] = z                          # on the bay floor
    if UP1:
        import upgrade as U
        for nm in U.nests():
            tops[nm] = U.NEST_TOP + wp                  # on a buffer nest pad
    return tops


def contact_plunge(station):
    return cookie_tops()[station] + CUP_DROP


# ---------------------------------------------------------------- obstacles
def obstacles(serving=None):
    """Every static part of the other three modules, as factory-frame AABBs,
    with the machines parked the way they are while the VGR works. One process
    builds one variant, so the set per station is built once and reused."""
    if serving not in _OBST:
        _OBST[serving] = tuple(_obstacles(serving))
    return list(_OBST[serving])


_OBST = {}


def _obstacles(serving=None):
    out = []
    for p in HM.build(HM.P["CV_X"], 260.0, 0.0):        # crane parked at transit
        if p.group == "frame":
            continue
        a = p.aabb()
        c0, c1 = FL.to_factory(a[0], a[1]), FL.to_factory(a[3], a[4])
        out.append((f"HBW {p.name}", (min(c0[0], c1[0]), min(c0[1], c1[1]), a[2],
                                      max(c0[0], c1[0]), max(c0[1], c1[1]), a[5])))
    # the mould waiting at the VGR end of the belt - the cup must stay OUT of it
    mx, my = FL.belt_handovers()["vgr"][:2]
    z0 = HM.P["CV_SURF"]
    for nm, (x0, y0, x1, y1, za, zb) in {
            "base": (-30, -32, 30, 32, 0, 8),
            "rim_a": (-30, -32, -25, 32, 8, 20), "rim_b": (25, -32, 30, 32, 8, 20),
            "rim_c": (-25, -32, 25, -27, 8, 20), "rim_d": (-25, 27, 25, 32, 8, 20)}.items():
        out.append((f"MOULD {nm}", (mx + x0, my + y0, z0 + za, mx + x1, my + y1, z0 + zb)))
    for p in OM.build(sauger=OM.O["SAUGER"][1]):        # its own Sauger at the turntable
        if p.group == "frame":
            continue
        out.append((f"OVEN {p.name}", FL.oven_box(p.local_aabb())))
    for p in SM.build():
        if p.group == "frame":
            continue
        # the cookie the VGR is collecting is the target, not an obstacle
        if serving and serving.startswith("bay_") and p.name.startswith(f"wp_{serving[4:]}_"):
            continue
        a = p.local_aabb()
        c0, c1 = FL.to_factory_sort(a[0], a[1]), FL.to_factory_sort(a[3], a[4])
        out.append((f"SORT {p.name}", (min(c0[0], c1[0]), min(c0[1], c1[1]), a[2],
                                       max(c0[0], c1[0]), max(c0[1], c1[1]), a[5])))
    if UP1:
        import upgrade as U
        out += [(f"UP1 {p.name}", a) for _, p, a in U.factory_parts()]
    return out


# ---------------------------------------------------------------- VGR parts
def moving_parts(sw, pz, rr, compress=0.0, carrying=False):
    """Every part that moves with the arm, as (name, centre, half, angle, z0, z1)
    in the factory frame. The cup and the held cookie sit `compress` mm higher
    than the carriage alone would put them: that is the spring stem giving."""
    parts = [p for p in VG.build(sw, pz, rr) if p.frame != "world"]
    if carrying:
        parts += VG.held_cookie(sw, pz, rr)
    vx, vy = FL.VGR_AT
    t = math.radians(sw); ct, st = math.cos(t), math.sin(t)
    out = []
    for p in parts:
        a = p.local_aabb()
        lift = compress if (p.group in ("tool", "load")) else 0.0
        cx_, cy_ = (a[0] + a[3]) / 2 - V["CX"], (a[1] + a[4]) / 2 - V["CY"]
        c = (vx + V["CX"] + cx_ * ct - cy_ * st, vy + V["CY"] + cx_ * st + cy_ * ct)
        h = ((a[3] - a[0]) / 2, (a[4] - a[1]) / 2)
        # A vertical cylinder (cup, stem, cookie) is round: rotating it changes
        # nothing, so test it as an unrotated box of its diameter. Rotating its
        # square AABB instead inflates it by up to sqrt(2) - phantom hits.
        ang = 0.0 if (p.kind == "cyl" and p.s[0] == "z") else sw
        out.append((p.name, c, h, ang, a[2] + lift, a[5] + lift))
    return out


def pose_hits(k, obst, tol=0.05):
    hits = []
    for name, c, h, ang, z0, z1 in moving_parts(k["sw"], k["pz"], k["rr"], k["compress"],
                                                k["carry"] is not None):
        for on, oa in obst:
            dz = min(z1, oa[5]) - max(z0, oa[2])
            if dz <= tol:
                continue
            o = FL._obb_hit(c, h, ang, ((oa[0] + oa[3]) / 2, (oa[1] + oa[4]) / 2),
                            ((oa[3] - oa[0]) / 2, (oa[4] - oa[1]) / 2), tol)
            if o:
                hits.append((name, on, round(min(o, dz), 1)))
    return hits


# --------------------------------------------------------------------- plan
def _leg_clear(a, b, deg_step=2.0, mm_step=4.0):
    n = max(1, int(max(abs(b["sw"] - a["sw"]) / deg_step, abs(b["rr"] - a["rr"]) / mm_step,
                       abs(b["pz"] - a["pz"]) / mm_step)))
    obst = obstacles(serving=b.get("station"))
    for j in range(n + 1):
        u = j / n
        k = {x: a[x] + (b[x] - a[x]) * u for x in ("sw", "rr", "pz", "compress")}
        k["carry"] = a["carry"]
        if pose_hits(k, obst):
            return False
    return True


def descent_reach(st, sw, rr, app, carry_in, carry_out):
    """The LONGEST reach at which the arm can come straight down from transit
    beside this station and then extend in at the approach height - both legs
    clear, carrying whatever it carries on the way in AND on the way out.

    Longer is better: a retracted arm sticks its reach motor 550 mm out behind
    the tower, which is what swept into the rack. Shorter is sometimes forced:
    at the oven the Sauger portal is directly over the tray, so the arm has to
    come down outside it and slide in underneath. The checker picks, not a rule.
    """
    T = V["TRANSIT"]
    for rd in [rr] + [r for r in range(int(rr // 10) * 10, -1, -10) if r < rr]:
        ok = True
        for carry in {carry_in, carry_out}:
            top = {"sw": sw, "rr": rd, "pz": T, "compress": 0.0, "carry": carry, "station": st}
            low = {**top, "pz": app}
            at = {**low, "rr": rr}
            if not (_leg_clear(top, low) and _leg_clear(low, at)):
                ok = False
                break
        if ok:
            return float(rd)
    raise RuntimeError(f"no clear descent to station {st}")


DEMO = [("belt", "pick", "raw", "warehouse belt"),
        ("oven", "place", None, "oven's Ofenschieber"),
        ("bay_rot", "pick", "baked", "rot Lagerstelle"),
        ("belt", "place", None, "warehouse belt")]


def plan(tour=None):
    """The demo tour: belt (raw) -> oven, then a baked cookie bay_rot -> belt.
    `tour` replaces it with any list of (station, pick|place, colour, label).
    Upgrade 10 blends the transit legs (blend()); the waypoint count and every
    key's role stay the same, so a job keeps one step structure."""
    keys = _plan(tour)
    return blend(keys) if BLEND["on"] else keys


def _plan(tour=None):
    S = FL.stations()
    T = V["TRANSIT"]
    home = {"sw": 0.0, "rr": 0.0, "pz": T}
    keys = []

    def k(sw, rr, pz, cup, carry, say, compress=0.0, station=None):
        keys.append({"sw": round(sw, 3), "rr": round(rr, 3), "pz": round(pz, 3),
                     "cup": cup, "carry": carry, "compress": compress,
                     "station": station, "say": say})

    def visit(st, action, carry_in, colour_out, label):
        s = S[st]; sw, rr = s["swivel"], s["reach"]
        con = contact_plunge(st); app = con + APPROACH
        cup_in = carry_in is not None
        rd = descent_reach(st, sw, rr, app, carry_in, colour_out)
        k(sw, rd, T, cup_in, carry_in, f"swing to the {label} at transit height", station=st)
        k(sw, rd, app, cup_in, carry_in, f"descend beside the {label}", station=st)
        k(sw, rr, app, cup_in, carry_in, f"extend over the {label}", station=st)
        k(sw, rr, con, cup_in, carry_in, "cup meets the cookie's top face", station=st)
        k(sw, rr, con - OVERTRAVEL, cup_in, carry_in,
          "press: the spring stem takes up the over-travel", OVERTRAVEL, st)
        if action == "pick":
            k(sw, rr, con - OVERTRAVEL, True, colour_out,
              "Q7/Q8 vacuum on - the cup sucks down onto the cookie", OVERTRAVEL, st)
            k(sw, rr, con, True, colour_out, "spring relaxes - seal holds", 0.0, st)
            carry_after = colour_out
        else:
            k(sw, rr, con - OVERTRAVEL, False, None,
              "vacuum off - the cookie is released", OVERTRAVEL, st)
            k(sw, rr, con, False, None, "spring relaxes", 0.0, st)
            carry_after = None
        k(sw, rr, app, carry_after is not None, carry_after,
          "lift the cookie clear" if carry_after else "lift clear", station=st)
        k(sw, rd, app, carry_after is not None, carry_after, "retract out from the station",
          station=st)
        k(sw, rd, T, carry_after is not None, carry_after, "rise to transit height", station=st)
        return carry_after

    k(home["sw"], home["rr"], home["pz"], False, None, "VGR at home, transit height")
    c = None
    for st, action, colour, label in (tour or DEMO):
        c = visit(st, action, c, colour, label)
    k(home["sw"], home["rr"], home["pz"], False, None, "VGR back home")
    return keys


# ------------------------------------------------ Upgrade 10: blended legs
# Every tour used to climb to TRANSIT (500 mm, above everything on the table),
# swing, and come straight down again - three moves one after another, with
# only one motor running at a time. Upgrade 10 keeps the waypoint count but
# moves the transit waypoints: each crossing flies at the LOWEST height at which
# the whole crossing is swept clear by the same SAT test, plus a margin, and may
# start swinging while it is still rising (several motors at once). What is
# searched is only proposed - check() still sweeps every leg of every tour.
BLEND = {"on": UP10}
MARGIN = 20.0            # mm the crossing is lifted above the lowest clear height
H_STEP = 20.0            # height grid of the search, mm
SPLITS = ((0.0, 1.0), (0.0, 0.5), (0.5, 1.0), (0.5, 0.5))   # where the swing starts / ends, 0..1
V_SW, V_LIN, T_LEG = 60.0, 120.0, 0.4    # deg/s, mm/s, s: as motion.py and control.py


def leg_time(a, b):
    d = max(abs(b["sw"] - a["sw"]) / V_SW, abs(b["rr"] - a["rr"]) / V_LIN, abs(b["pz"] - a["pz"]) / V_LIN)
    return max(d, T_LEG) if d > 1e-9 else 0.0


def _crossings(keys):
    """Runs of transit waypoints between two fixed poses: (fixed_before,
    movable indices, fixed_after). Home (the first and last key) stays put."""
    T = V["TRANSIT"]
    out, i, n = [], 1, len(keys)
    while i < n - 1:
        if abs(keys[i]["pz"] - T) < 1e-6:
            j = i
            while j + 1 < n - 1 and abs(keys[j + 1]["pz"] - T) < 1e-6:
                j += 1
            out.append((i - 1, list(range(i, j + 1)), j + 1))
            i = j + 1
        else:
            i += 1
    return out


def _place(keys, f0, mov, f1, a, b, h):
    A, B = keys[f0], keys[f1]
    lerp = lambda u: {x: A[x] + (B[x] - A[x]) * u for x in ("sw", "rr")}
    if len(mov) == 1:
        us = (b,) if f0 == 0 else (a,)      # from home: where the swing ends; to home: where it starts
    else:
        us = (a, b)
    return [{**keys[m], **{x: round(v, 3) for x, v in lerp(u).items()}, "pz": round(h, 3)} for m, u in zip(mov, us)]


def _legs_clear(chain, fine=False):
    return all(_leg_clear(p, q, *((1.0, 2.0) if fine else (2.0, 4.0))) for p, q in zip(chain, chain[1:]))


def _blend_one(keys, f0, mov, f1):
    T = V["TRANSIT"]
    A, B = keys[f0], keys[f1]
    lo = math.ceil(max(A["pz"], B["pz"]) / H_STEP) * H_STEP
    grid = [h for h in _frange(lo, T, H_STEP)] + [T]
    splits = SPLITS if len(mov) == 2 else ((0.0, 0.0), (0.5, 0.5), (1.0, 1.0))
    best = None
    for a, b in splits:
        def ok(h, fine=False, a=a, b=b):      # bind this split, not the loop's last
            return _legs_clear([A] + _place(keys, f0, mov, f1, a, b, h) + [B], fine)
        # the lowest clear height: clearance grows with height (everything is below TRANSIT)
        k_lo, k_hi = 0, len(grid) - 1
        if not ok(grid[k_hi]):
            continue
        while k_lo < k_hi:
            k = (k_lo + k_hi) // 2
            if ok(grid[k]):
                k_hi = k
            else:
                k_lo = k + 1
        h = min(T, grid[k_lo] + MARGIN)
        if not ok(h, fine=True):
            continue
        chain = [A] + _place(keys, f0, mov, f1, a, b, h) + [B]
        cost = sum(leg_time(p, q) for p, q in zip(chain, chain[1:]))
        if best is None or cost < best[0] - 1e-9:
            best = (cost, chain[1:-1])
    return best[1] if best else [keys[m] for m in mov]


def _frange(a, b, d):
    x = a
    while x < b - 1e-9:
        yield x
        x += d


def _blend_key(keys):
    import hashlib
    blob = repr(([(k["sw"], k["rr"], k["pz"], k["carry"], k["station"]) for k in keys],
                 [obstacles(k["station"]) for k in keys if k["station"]], MARGIN, H_STEP, SPLITS))
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def blend(keys):
    """The same waypoints with every transit crossing lowered and blended."""
    import json
    import os
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
    fp = os.path.join(d, f"blend_{_blend_key(keys)}.json")
    if os.path.exists(fp):
        return json.load(open(fp))
    out = [dict(k) for k in keys]
    for f0, mov, f1 in _crossings(keys):
        for m, k in zip(mov, _blend_one(keys, f0, mov, f1)):
            out[m] = k
    os.makedirs(d, exist_ok=True)
    json.dump(out, open(fp, "w"))
    return out


def buffer_tour():
    """Upgrade 1: every nest served both ways - a baked cookie from the rot
    Lagerstelle into the nest, then out of the nest onto the warehouse belt."""
    import upgrade as U
    t = []
    for i, nm in enumerate(U.nests(), 1):
        t += [("bay_rot", "pick", "baked", "rot Lagerstelle"),
              (nm, "place", None, f"buffer nest {i}"),
              (nm, "pick", "baked", f"buffer nest {i}"),
              ("belt", "place", None, "warehouse belt")]
    return t


# -------------------------------------------------------------------- check
def check(verbose=True, deg_step=1.0, mm_step=2.0, tour=None):
    keys = plan(tour)
    fails = []
    lo, hi = V["PLUNGE"]; r0, r1 = V["REACH"]; s0, s1 = V["SWIVEL"]
    for i, k in enumerate(keys):
        if not (lo <= k["pz"] <= hi and r0 <= k["rr"] <= r1 and s0 <= k["sw"] <= s1):
            fails.append(f"key {i} '{k['say']}' outside the joint limits")
    steps = 0
    for i in range(1, len(keys)):
        a, b = keys[i - 1], keys[i]
        n = max(1, int(max(abs(b["sw"] - a["sw"]) / deg_step,
                           abs(b["rr"] - a["rr"]) / mm_step,
                           abs(b["pz"] - a["pz"]) / mm_step,
                           abs(b["compress"] - a["compress"]) / 0.5)))
        obst = obstacles(serving=b["station"] or a["station"])
        seen = set()
        for j in range(n + 1):
            u = j / n
            k = {x: a[x] + (b[x] - a[x]) * u for x in ("sw", "rr", "pz", "compress")}
            k["carry"] = a["carry"] if u < 1 else b["carry"]
            steps += 1
            for h in pose_hits(k, obst):
                if (h[0], h[1]) in seen:
                    continue
                seen.add((h[0], h[1]))
                fails.append(f"leg {i} '{b['say']}': VGR {h[0]} x {h[1]} = {h[2]} mm "
                             f"@ sw={k['sw']:.1f} rr={k['rr']:.0f} pz={k['pz']:.0f}")
    if verbose:
        print(f"VGR path: {len(keys)} waypoints, {steps} swept poses checked")
        print("\n".join(fails[:40]) if fails else
              "PATH CLEAR (no VGR part or carried cookie touches any module on any leg; "
              "the cup never goes below a cookie's top face)")
    return fails


def check_buffer(verbose=True):
    return check(verbose, tour=buffer_tour()) if UP1 else []


def export():
    return {"keys": plan(), "cup_drop": CUP_DROP, "overtravel": OVERTRAVEL,
            "transit": V["TRANSIT"], "cookie_tops": cookie_tops()}


if __name__ == "__main__":
    import sys
    sys.exit(1 if check() else 0)
