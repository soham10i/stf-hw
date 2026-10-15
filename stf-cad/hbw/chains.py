"""
Upgrade 3 - drag chains (cable carriers) on every moving axis (STF_VARIANT=up3).

Until now every device that MOVES was unwired: a cable on a moving axis needs a
carrier or it is torn off / chafed within a few thousand cycles. Four chains
and a tower duct wire them all:

  hbw travel  horizontal, lower strand in a trough in front of the rail,
              fixed end at mid-stroke, moving end on the travel carriage
  hbw lift    vertical U hanging beside the mast (travel frame), moving end
              on the lift carriage's right leg
  vgr plunge  vertical U beside the tower (swivel frame), fixed under the
              tower top plate, moving end on the plunge carriage
  vgr reach   horizontal, fixed on the carriage top, upper strand over the
              arm, moving end on the arm's rear block
  vgr swivel  the tower cables come down a duct on the turntable and pass
              the swivel axis through the hollow Drehkranz (a twister loop)

Every chain is a set of real model parts: its brackets, and an ENVELOPE part
(mech "chain:<id>") that encloses the chain over its whole stroke - so the
module proofs, check_cross and the VGR's swept tours check it like any other
part. The web draws the animated chain inside that envelope.

check() proves per chain: length fits the stroke (loop never runs out or
bottoms out), bend radius >= 7.5 x the largest conductor, fill <= 60 % of the
inner section, unsupported span within the chain's self-supporting length,
and every moving I/O device is on a path of chains that ends in the world.
Link sizes are ASSUMED (a small plastic chain, 12 mm link height).
"""
import math

from variant import UP3

WIRE_D = 1.4                      # mm, one conductor as the wiring model draws it
BEND_FACTOR = 7.5                 # min bend radius = 7.5 x OD (chain-suitable cable)
FILL_MAX = 0.60
WALL = 1.5                        # link wall, mm (assumed)
SELF_SUPPORT = 500.0              # mm unsupported length for this chain size (assumed)

# ---------------------------------------------------------------- the chains
# All coordinates in the owning model's frame at its authoring pose.
HBW = {
    "travel": dict(axis="x", fixed="world", moving="travel", R=20.0, h=12.0, w=25.0,
                   F=(392.5, 142.5, 9.0), M=(0.0, 142.5, 49.0), stroke=(120.0, 665.0),
                   devices=["M3_lift_motor", "I4_ref_vertical", "M4_fork_motor",
                            "I5_ref_ausleger_front", "I6_ref_ausleger_back"]),
    # fixed end under the mast top plate: the carriage's legs wrap the mast
    # profiles, so anything fixed on a profile would be hit as the carriage passes
    "lift": dict(axis="z", fixed="travel", moving="lift", R=20.0, h=12.0, w=25.0,
                 F=(66.0, 207.5, 462.0), M=(106.0, 207.5, 30.0), stroke=(80.0, 360.0), Lc=440.0,
                 floor=60.0,
                 devices=["M4_fork_motor", "I5_ref_ausleger_front", "I6_ref_ausleger_back"]),
}
VGR = {
    "plunge": dict(axis="z", fixed="swivel", moving="plunge", R=20.0, h=12.0, w=25.0,
                   F=(267.5, 197.0, 598.0), M=(267.5, 237.0, 23.0), stroke=(84.0, 540.0), Lc=560.0,
                   floor=70.0,
                   devices=["M2_reach_motor", "suction_cup", "I2_ref_reach"]),
    "reach": dict(axis="-y", fixed="plunge", moving="reach", R=12.0, h=12.0, w=20.0,
                  # moving end on the rails 43 mm ahead of the rear block, not on it:
                  # a U chain's loop sits halfway between the arm's rear now and at
                  # full retraction, and at the rear block that loop reached into the
                  # HBW cover when serving bay_rot (check_cross found it)
                  F=(182.0, 231.0, 62.0), M=(182.0, 640.0, 38.0), stroke=(0.0, 400.0), Lc=447.0,
                  devices=["M2_reach_motor", "suction_cup"]),
}
# conductors per device (dual-lead motors + encoder, sensors 2, the cup's valve 2)
COND = {"M3_lift_motor": 6, "M4_fork_motor": 2, "I4_ref_vertical": 2, "I5_ref_ausleger_front": 2,
        "I6_ref_ausleger_back": 2, "M2_reach_motor": 6, "suction_cup": 2, "I2_ref_reach": 2,
        "M1_plunge_motor": 6, "I1_ref_plunge": 2}


def _len_horizontal(c):
    s0, s1 = c["stroke"]
    return math.pi * c["R"] + (s1 - s0) / 2.0


def length(c):
    return c.get("Lc") or _len_horizontal(c)


def loop_centre(c, m_pos):
    """Horizontal chains: the loop's position along the axis for moving-end
    coordinate m_pos. Vertical chains: the loop centre height."""
    L, R = length(c), c["R"]
    if c["axis"] == "x":
        return (L - math.pi * R + c["F"][0] + m_pos) / 2.0
    if c["axis"] == "-y":
        return (L - math.pi * R + c["F"][1] + m_pos) / 2.0
    return (c["F"][2] + m_pos + math.pi * R - L) / 2.0


def _mpos(c, joint):
    """Moving-end coordinate along the chain's axis, in the FIXED frame."""
    if c["axis"] == "x":
        return joint                                   # travel carriage X
    if c["axis"] == "-y":
        return c["M"][1] - joint                       # arm rear moves -y with reach
    return joint + c["M"][2]                           # carriage z + attach offset


# ------------------------------------------------------------- model parts
def hbw_parts(Part, X, cb):
    """HBW chain parts at travel X, lift cb (module coordinates)."""
    if not UP3:
        return []
    t, l = HBW["travel"], HBW["lift"]
    out = []; A = out.append
    s0, s1 = t["stroke"]
    xL_max = loop_centre(t, s1)
    A(Part("chain_travel_trough", "chain", "box", (100.0, 127.5, 0.0), (xL_max + t["R"] + 12 - 100.0, 30.0, 3.0),
           "black", "plate", note="chain trough: the travel chain's lower strand lies in it"))
    # the chain at THIS travel: upper strand from the carriage to the loop,
    # lower strand from the loop back to the fixed point
    xL = loop_centre(t, X)
    xa = min(X, t["F"][0]) - 10.0
    A(Part("chain_travel_env", "chain", "box", (xa, 130.0, 3.0),
           (xL + t["R"] + t["h"] / 2 - xa, t["w"], 2 * t["R"] + t["h"]),
           "black", "chain_travel_trough", mech="chain:travel",
           note="the travel drag chain at this travel"))
    A(Part("chain_travel_bracket", "chain", "box", (X - 10.0, 140.0, 43.0), (20.0, 25.0, 12.0),
           "red", "travel_carriage", joint="travel", note="moving end of the travel chain"))
    # lift chain (travel frame): envelope from the loop's lowest to the top attach
    zc = loop_centre(l, _mpos(l, cb))                  # the loop at THIS lift
    z_top = max(l["F"][2], cb + l["M"][2]) + l["h"] / 2
    x0 = l["F"][0] - l["h"] / 2
    A(Part("chain_lift_env", "chain", "box", (X + x0, l["F"][1] - l["w"] / 2, zc - l["R"] - l["h"] / 2),
           (2 * l["R"] + l["h"], l["w"], z_top - (zc - l["R"] - l["h"] / 2)),
           "black", "chain_lift_fix", joint="travel", mech="chain:lift",
           note="the lift drag chain at this lift"))
    A(Part("chain_lift_fix", "chain", "box", (X + 57.0, 200.0, l["F"][2] - 6), (15.0, 15.0, 14.0),
           "red", "mast_top_plate", joint="travel",
           note="fixed end of the lift chain, hanging from the mast top plate - above the carriage's reach"))
    A(Part("chain_lift_bracket", "chain", "box", (X + 56.0, 200.0, cb + l["M"][2] - 6), (56.0, 15.0, 12.0),
           "red", "lift_carriage_R", joint="lift", note="moving end of the lift chain, on the carriage's right leg"))
    return out


def vgr_parts(Part, pz, rr):
    """VGR chain parts at plunge pz, reach rr (module coordinates, swivel not applied)."""
    if not UP3:
        return []
    p, r = VGR["plunge"], VGR["reach"]
    out = []; A = out.append
    zc = loop_centre(p, _mpos(p, pz))                  # the loop at THIS plunge
    zb = zc - p["R"] - p["h"] / 2
    ya, yb = p["F"][1] - p["h"] / 2, p["M"][1] + p["h"] / 2
    A(Part("tower_cable_duct", "chain", "box", (252.0, 165.0, 38.0), (10.0, 20.0, 562.0),
           "grey", "turntable_disc", frame="swivel",
           note="cable duct down the tower to the turntable; the cables pass the swivel "
                "axis through the hollow Drehkranz (twister loop)"))
    A(Part("chain_plunge_env", "chain", "box", (p["F"][0] - p["w"] / 2, ya, zb),
           (p["w"], yb - ya, p["F"][2] + p["h"] / 2 - zb + 2), "black", "chain_plunge_fix",
           frame="swivel", mech="chain:plunge", note="envelope of the plunge drag chain over its stroke"))
    # bolted UNDER the top plate (12 mm of it), above the carriage's highest top (586)
    A(Part("chain_plunge_fix", "chain", "box", (238.0, ya, p["F"][2] - 6), (42.0, 12.0, 8.0),
           "red", "tower_top_plate", frame="swivel", note="fixed end of the plunge chain, under the tower top"))
    A(Part("chain_plunge_bracket", "chain", "box", (250.0, 215.0, pz + p["M"][2] - 6), (30.0, 28.0, 12.0),
           "red", "plunge_carriage", frame="plunge", note="moving end of the plunge chain, on the carriage side"))
    # the envelope at THIS reach: the loop sits where the chain's length puts it
    yL = loop_centre(r, _mpos(r, rr))
    A(Part("chain_reach_env", "chain", "box", (r["F"][0] - r["w"] / 2, 227.0, pz + r["M"][2] - r["h"] / 2),
           (r["w"], yL + r["R"] + r["h"] / 2 - 227.0, 2 * r["R"] + r["h"]),
           "black", "chain_reach_fix", frame="plunge", mech="chain:reach",
           note="the reach drag chain at this reach (upper strand spans the arm)"))
    # on the carriage's BACK face, above where the arm rails pass through it -
    # on its top face it would meet the tower top plate at full plunge
    A(Part("chain_reach_fix", "chain", "box", (r["F"][0] - r["w"] / 2, 227.0, pz + 30.0), (r["w"], 12.0, 38.0),
           "red", "plunge_carriage", frame="plunge", note="fixed end of the reach chain, on the carriage back face"))
    A(Part("chain_reach_bracket", "chain", "box", (r["F"][0] - r["w"] / 2, r["M"][1] - 7.0 - rr, pz + 25.0),
           (r["w"], 14.0, 7.0), "red", "arm_rail_L", frame="reach",
           note="moving end of the reach chain, clamped across both arm rails"))
    return out


# ------------------------------------------------------------------ checks
def _all():
    return [("hbw", k, v) for k, v in HBW.items()] + [("vgr", k, v) for k, v in VGR.items()]


def cables_in(c):
    return sum(COND.get(d, 2) for d in c["devices"])


def check(verbose=True):
    fails, rows = [], []
    for mod, cid, c in _all():
        R, h, w = c["R"], c["h"], c["w"]
        L = length(c)
        s0, s1 = c["stroke"]
        # bend radius
        rmin = BEND_FACTOR * WIRE_D
        if R < rmin:
            fails.append(f"BEND {mod} {cid}: R {R} < {rmin:.1f}")
        # fill: conductors vs the inner section
        inner = (w - 2 * WALL) * (h - 2 * WALL)
        n = cables_in(c)
        fill = n * math.pi * (WIRE_D / 2) ** 2 / inner
        if fill > FILL_MAX:
            fails.append(f"FILL {mod} {cid}: {fill:.0%} > {FILL_MAX:.0%}")
        # length: the loop must stay between (horizontal) or above the floor (vertical)
        span = 0.0
        if c["axis"] in ("x", "-y"):
            for j in (s0, s1):
                m = _mpos(c, j)
                lc = loop_centre(c, m)
                f = c["F"][0] if c["axis"] == "x" else c["F"][1]
                if lc < max(m, f) - 1e-6:
                    fails.append(f"LENGTH {mod} {cid}: loop at {lc:.0f} falls inside the stroke at {j}")
                span = max(span, lc - f)
            if span > SELF_SUPPORT:
                fails.append(f"SPAN {mod} {cid}: unsupported {span:.0f} mm > {SELF_SUPPORT:.0f}")
        else:
            for j in (s0, s1):
                zm = _mpos(c, j)
                zc = loop_centre(c, zm)
                if zc - R - h / 2 < c["floor"] - 1e-6:
                    fails.append(f"LENGTH {mod} {cid}: loop bottoms out ({zc - R - h / 2:.0f} < {c['floor']:.0f}) at {j}")
                if zc > min(c["F"][2], zm) - 1e-6:
                    fails.append(f"LENGTH {mod} {cid}: chain too short - loop above an attach point at {j}")
        rows.append({"module": mod, "id": cid, "axis": c["axis"], "fixed": c["fixed"], "moving": c["moving"],
                     "stroke": [s0, s1], "R": R, "h": h, "w": w, "length": round(L, 1),
                     "conductors": n, "fill": round(fill, 3), "bend_min": round(rmin, 1),
                     "span": round(span, 1), "devices": c["devices"]})
    # every moving I/O device rides a chain path to the world
    moving_io = {"hbw": ["M3_lift_motor", "I4_ref_vertical", "M4_fork_motor", "I5_ref_ausleger_front",
                         "I6_ref_ausleger_back"],
                 "vgr": ["M1_plunge_motor", "I1_ref_plunge", "I2_ref_reach", "M2_reach_motor", "suction_cup"]}
    path_to_world = {"hbw": set(HBW["travel"]["devices"]),
                     "vgr": set(VGR["plunge"]["devices"]) | {"M1_plunge_motor", "I1_ref_plunge"}}
    for mod, devs in moving_io.items():
        for d in devs:
            if d not in path_to_world[mod]:
                fails.append(f"UNWIRED {mod} {d}: no chain path to the world")
    if verbose:
        print(f"chains: {len(rows)} chains + tower duct, "
              f"{sum(len(v) for v in moving_io.values())} moving devices wired")
        print("\n".join(fails) if fails else "ALL CHECKS PASS (length, bend radius, fill, span, "
                                             "every moving device on a chain path)")
    return fails, rows


def export():
    _, rows = check(verbose=False)
    spec = {}
    for mod, cid, c in _all():
        spec[f"{mod}:{cid}"] = {**{k: v for k, v in c.items() if k != "devices"},
                                "length": round(length(c), 1), "devices": c["devices"]}
    return {"chains": spec, "rows": rows,
            "rules": {"bend": f"R >= {BEND_FACTOR} x {WIRE_D} mm conductor", "fill_max": FILL_MAX,
                      "self_support_mm": SELF_SUPPORT},
            "swivel": "tower cables run down a duct on the turntable and pass the swivel axis "
                      "through the hollow Drehkranz (twister loop, +/-130 deg)",
            "sizes": "chain links assumed: 12 mm high, 20-25 mm wide, 1.5 mm wall"}
