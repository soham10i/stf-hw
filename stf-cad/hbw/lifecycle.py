"""
Upgrade 7 - lifecycle: a cell someone can own for years (STF_VARIANT=up7).

  TOLERANCES  every critical clearance as a tolerance chain: the nominal gap
              from the models, minus each contributor's tolerance. Worst case
              (plain sum) must stay >= 0; the RSS figure is shown beside it.
              A chain that fails is a finding, and U7 carries its fix.
  ACCESS      every PCB, valve, motor, compressor and node coupler: is the
              column above it clear to the guard top, and is it within arm's
              reach (ISO 13857: 850 mm) of a guard door?
  SPARES      a spare-parts list generated from the parts of every module and
              upgrade, with wear parts and stock sized from Upgrade 6's lives.
  PLAN        the maintenance plan: Upgrade 6's intervals, the door to use,
              the detect-only checks.
  STRUCTURE   every load-carrying member under Upgrade 5's accelerations:
              peak deflection and first natural frequency (cantilever with a
              tip mass), against DEFL_DYN and F_MIN.
Assumed and flagged: every tolerance contributor, the densities, the profile
section area, and the reach.
"""
import math

import control as C
import vc as V
from variant import UP7

REACH = 850.0          # ISO 13857 upper-limb reach through an opening, mm
E_AL, E_PA = 70000.0, 2500.0
I_PROF = {15: 1900.0, 20: 6900.0}         # mm^4 (Misumi HFS3-1515 / HFS5-2020)
A_PROF = {15: 85.0, 20: 150.0}            # mm^2 section area (ASSUMED from catalogue class)
DEFL_DYN = 0.5         # mm peak dynamic deflection at the tool
F_MIN = 20.0           # Hz: the natural period must fit twice into the 0.1 s ramp
G = 9810.0             # mm/s^2


# ------------------------------------------------------------ tolerances
def chains():
    import hbw_model as HM
    import vgr_model as VG
    import sorting_model as SM
    q = HM.P
    acc = {a["axis"]: a["error_mm"] for a in V.ACC}
    cup = VG.V["CUP_D"]
    wp = q["WP_D"]
    pocket = min(q["MOULD"][0], q["MOULD"][1]) - 2 * q["RIM_T"]
    pocket_y = max(q["MOULD"][0], q["MOULD"][1]) - 2 * q["RIM_T"]
    seat = 0.2 if UP7 else (pocket_y - wp) / 2
    belt_w = SM.S["BELT"][3]
    bay_play = 0.5 if UP7 else (belt_w - SM.S["WP_D"]) / 2
    reach_y = max(p.aabb()[4] for p in HM.build(q["CV_X"], 80.0, q["FORK"][1]) if p.joint == "fork")
    rows = [
        ("T1", "fork table in the shelf gap (per side)", (q["SHELF_GAP"] - q["TABLE"][0]) / 2, [
            ("shelf bracket position (ft assembly)", 0.5), ("fork table width (moulded)", 0.2),
            ("lateral play of the Ausleger stages", 0.5), ("travel stop (U5 accuracy)", acc["travel"]),
            ("rack post spacing on the plate", 1.0)], None),
        ("T2", "RP1 read head vs the Ausleger's reach", HM.RFID_Y[0] - 20 - reach_y, [
            ("I5 switch actuation spread", 1.5), ("stage 2 length", 0.5), ("head bracket position", 1.0),
            ("belt frame on the plate", 1.0)], None),
        ("T3", "VGR cup seal on a cookie in its mould", (wp - cup) / 2, [
            ("swivel stop at the cup (U5)", acc["swivel"]), ("reach stop (U5)", acc["reach"]),
            ("hand-over station position", 1.0),
            ("cookie play in the mould pocket" + (" (U7 centring seat)" if UP7 else ""), seat)],
         "cup 40 -> 35 mm and a conical centring seat in each mould: the pocket let the cookie sit 4.5 mm off-centre"),
        ("T4", "VGR cup seal on a cookie in a Lagerstelle", (wp - cup) / 2, [
            ("swivel stop at the cup (U5)", acc["swivel"]), ("reach stop (U5)", acc["reach"]),
            ("bay position on the sorting plate", 1.0),
            ("cookie play across the bay" + (" (U7 V-guide)" if UP7 else ""), bay_play)],
         "a V-guide in each Lagerstelle: the ejector leaves the cookie wherever it sat across the belt"),
    ]
    out = []
    for cid, what, nom, contrib, fix in rows:
        worst = nom - sum(t for _, t in contrib)
        rss = nom - math.sqrt(sum(t * t for _, t in contrib))
        out.append({"id": cid, "what": what, "nominal": round(nom, 2), "worst": round(worst, 2), "rss": round(rss, 2),
                    "contrib": [{"what": w, "tol": round(t, 2)} for w, t in contrib], "fix": fix if UP7 else None,
                    "ok": worst >= 0})
    return out


def base_chains():
    """The same chains on Upgrade 6's hardware (as found), for the before/after."""
    import subprocess, json, sys, os
    r = subprocess.run([sys.executable, "-c", "import json, lifecycle; print(json.dumps(lifecycle.chains()))"],
                       env={**os.environ, "STF_VARIANT": "up6"}, capture_output=True, text=True, check=True,
                       cwd=os.path.dirname(os.path.abspath(__file__)))
    return json.loads(r.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- access
SERVICE = ("pcb", "valve", "motor", "compressor", "coupler")


def access(doc):
    import safety as SF
    import wiring as W
    import upgrade as U
    import io_nodes as N
    boxes = []
    for m, parts in (("hbw", doc["parts"]), ("vgr", doc["vgr"]["parts"]), ("oven", doc["oven"]["parts"]),
                     ("sorting", doc["sorting"]["parts"])):
        for d in parts:
            if d["g"] == "frame" or d.get("f", "world") != "world" or d["n"].startswith("chain_"):
                continue
            boxes.append((m, d["n"], W._box_f(d, W._tf(m))))
    for mod, p, a in U.factory_parts(include_io=False):
        boxes.append((mod, p.name, list(a)))
    for m in N.MODULES:
        for p in N.parts(m):
            boxes.append(("io", p.name, list(p.local_aabb())))
    x0g, y0g, x1g, y1g = SF.outline()
    top = SF.H
    rows = []
    for m, n, b in boxes:
        if not any(k in n.lower() for k in SERVICE):
            continue
        sx, sy = (b[3] - b[0]) * 0.2, (b[4] - b[1]) * 0.2
        col = (b[0] + sx, b[1] + sy, b[5], b[3] - sx, b[4] - sy, top)
        over = [nn for mm, nn, o in boxes if nn != n and o[5] > col[2] + 0.5 and
                min(col[3], o[3]) - max(col[0], o[0]) > 0 and min(col[4], o[4]) - max(col[1], o[1]) > 0 and
                o[2] < col[5]]
        # from the side: a 300 mm corridor of the part's own section, any of the
        # four horizontal directions, ignoring its own drive train (same prefix)
        own = n.split("_")[0] + "_"
        side = None
        if over:
            for dname, (ax, sgn) in (("+x", (0, 1)), ("-x", (0, -1)), ("+y", (1, 1)), ("-y", (1, -1))):
                c = [b[0] + sx, b[1] + sy, b[2] + 1, b[3] - sx, b[4] - sy, b[5] - 1]
                if ax == 0:
                    c[0], c[3] = (b[3], b[3] + 300) if sgn > 0 else (b[0] - 300, b[0])
                else:
                    c[1], c[4] = (b[4], b[4] + 300) if sgn > 0 else (b[1] - 300, b[1])
                hit = [nn for mm, nn, o in boxes if nn != n and not nn.startswith(own) and
                       min(c[3], o[3]) - max(c[0], o[0]) > 0 and min(c[4], o[4]) - max(c[1], o[1]) > 0 and
                       min(c[5], o[5]) - max(c[2], o[2]) > 0]
                if not hit:
                    side = dname
                    break
        cx, cy = (b[0] + b[3]) / 2, (b[1] + b[4]) / 2
        best = None
        for did, (wall, (a0, a1), what) in SF.DOORS.items():
            wx = x0g if wall == "front" else x1g
            dy = 0.0 if a0 <= cy <= a1 else min(abs(cy - a0), abs(cy - a1))
            d = math.hypot(cx - wx, dy)
            if best is None or d < best[1]:
                best = (did, d)
        rows.append({"module": m, "part": n, "above_clear": not over, "blocked_by": over[:3], "side": side,
                     "from": "above" if not over else (f"side {side}" if side else "blocked"),
                     "door": best[0], "reach_mm": round(best[1]), "in_reach": best[1] <= REACH,
                     "ok": (not over or side is not None) and best[1] <= REACH})
    return rows


# ---------------------------------------------------------------- spares
CATS = [
    ("motor", lambda n, t: "motor" in n and not n.endswith(("_mount", "_shaft")), "ft encoder / S-motor 24 V"),
    ("reference switch", lambda n, t: n.startswith(("I1_", "I4_", "I5_", "I6_", "I2_ref", "I3_ref", "I7_", "I8_")) and "ref" in n,
     "ft mini switch 37783"),
    ("light barrier", lambda n, t: "lightbarrier" in n and n.endswith("_rx"), "phototransistor 36134 + LED 162135"),
    ("solenoid valve", lambda n, t: "valve" in n, "ft 3/2-way valve 24 V"),
    ("cylinder", lambda n, t: "cylinder" in n, "ft pneumatic cylinder"),
    ("compressor", lambda n, t: "compressor" in n, "ft compressor 24 V"),
    ("adapter PCB", lambda n, t: "pcb" in n, "24 V adapter board"),
    ("RFID head", lambda n, t: n.startswith("rfid_") and n.endswith("_head"), "RFID read/write head, IO-Link"),
    ("I/O coupler", lambda n, t: n.startswith("io_") and n.endswith("_coupler"), "Modbus TCP bus coupler"),
    ("I/O slice", lambda n, t: n.startswith("io_") and n.split("_")[-1][:2] in ("DI", "DO", "AI", "CN", "IO"), "I/O slice"),
    ("E-stop", lambda n, t: n.lower().startswith("es") and "estop" in n.lower(), "E-stop, 2 NC"),
]


def spares(doc, health):
    names = [d["n"] for d in doc["parts"] + doc["vgr"]["parts"] + doc["oven"]["parts"] + doc["sorting"]["parts"]]
    names += [d["n"] for d in doc.get("upgrade", {}).get("parts", [])]
    names += [d["n"] for d in doc.get("io3", {}).get("parts", [])]
    names += [d["n"] for d in doc.get("safety", {}).get("parts", [])]
    rows = []
    for cat, pred, what in CATS:
        q = sorted({n for n in names if pred(n, None)})
        if q:
            rows.append({"item": cat, "what": what, "qty": len(q), "wear": False, "per_year": None,
                         "stock": 1, "examples": q[:4]})
    n_reed = sum(len(v) for v in C.U5_SENSORS.values())
    rows.append({"item": "reed / vacuum / pressure switch", "what": "Upgrade 5 sensors", "qty": n_reed, "wear": False,
                 "per_year": None, "stock": 2, "examples": []})
    rows.append({"item": "drag chain", "what": "Upgrade 3 carriers", "qty": len(doc.get("chains", {}).get("chains", {})),
                 "wear": False, "per_year": None, "stock": 0, "examples": list(doc.get("chains", {}).get("chains", {}))})
    shifts_year = 2 * 250
    for h in health["components"]:
        if not h["wear_part"]:
            continue
        per_year = h["per_shift"] * shifts_year / h["life"]
        rows.append({"item": f"wear: {h['name']}", "what": f"life {h['life']:,} uses (ASSUMED)", "qty": 1, "wear": True,
                     "per_year": round(per_year, 2), "stock": max(1, math.ceil(per_year * 2 / 52) + 1),
                     "examples": [h["part"]]})
    return rows


def plan(health, acc):
    door_of = {r["part"]: r["door"] for r in acc}
    rows = []
    for h in health["components"]:
        rows.append({"task": f"service {h['name']}", "every_shifts": h["pm_shifts"], "trigger": "or a U6 warning",
                     "door": door_of.get(h["part"], "-"), "signal": h["metric"]})
    for d in health["detect_only"]:
        rows.append({"task": d["cover"], "every_shifts": 40.0, "trigger": "detect-only mode: " + d["mode"],
                     "door": "all", "signal": d["why"]})
    return rows


# ------------------------------------------------------------- structure
def _mass(parts, fill=None):
    g = 0.0
    for p in parts:
        if p.kind == "box":
            vol = p.s[0] * p.s[1] * p.s[2] / 1000.0
        else:
            vol = math.pi * (p.s[2] / 2) ** 2 * p.s[1] / 1000.0
        if "motor" in p.name:
            g += 60.0
        elif p.colour == "alu":
            g += vol * 2.7 * 0.45
        elif p.colour == "steel":
            g += vol * 7.85
        else:
            g += vol * 1.14 * 0.35              # hollow ft block (ASSUMED fill)
    return g / 1000.0                           # kg


def structure():
    import vgr_model as VG
    import hbw_model as HM
    import upgrade as U
    rows = []

    def member(name, what, L, E, I, m_tip, m_beam, a, section, note=""):
        F = (m_tip + 0.375 * m_beam) * a / 1000.0            # N (a in mm/s^2 -> m/s^2)
        d = F * L ** 3 / (3 * E * I)
        k = 3 * E * I / L ** 3                               # N/mm
        f = math.sqrt(k * 1000.0 / (m_tip + 0.24 * m_beam)) / (2 * math.pi)
        rows.append({"member": name, "load": what, "L_mm": round(L), "section": section, "E": E, "I": round(I),
                     "m_tip_g": round(m_tip * 1000), "a_ms2": round(a / 1000, 2), "defl_mm": round(d, 3),
                     "f1_hz": round(f, 1), "ok": d <= DEFL_DYN and f >= F_MIN, "note": note})

    vg = VG.build(0.0, 500.0, 400.0)
    reach = [p for p in vg if p.frame == "reach"]
    tool = [p for p in reach if p.group in ("tool",) or p.name.startswith(("suction", "arm_end_F"))]
    rails = [p for p in reach if p.name.startswith("arm_rail")]
    m_tip = _mass(tool) + 0.010
    m_rails = _mass(rails)
    L_arm = VG.V["ARM_FRONT"] + VG.V["REACH"][1]
    r = 0.57
    a_t = math.radians(V.PHYS["a_deg"]["swivel"]) * r * 1000
    Iz = 2 * (12 ** 4 / 12 + 144 * 9 ** 2)
    member("VGR arm, sideways", "swivel acceleration at full reach", L_arm, E_AL, Iz, m_tip, m_rails, a_t,
           "2 alu bars 12x12, 18 mm apart")
    member("VGR arm, vertical", "gravity + plunge acceleration", L_arm, E_AL, 2 * 12 ** 4 / 12, m_tip, m_rails,
           G + V.PHYS["a_mm"]["plunge"], "2 alu bars 12x12")
    moving = [p for p in vg if p.frame in ("plunge", "reach")]
    m_mov = _mass(moving) + 0.010
    cols = [p for p in vg if p.name.startswith("tower_column")]
    Ic = 4 * (I_PROF[15] + A_PROF[15] * (VG.V["COL_DX"] / 2) ** 2)
    member("VGR tower", "swivel acceleration of the carriage + arm at the top", VG.V["COL_Z"][1] - VG.V["COL_Z"][0],
           E_AL, Ic, m_mov, _mass(cols), math.radians(V.PHYS["a_deg"]["swivel"]) * 0.25 * 1000,
           "4 x 15x15 profile")
    hb = HM.build(HM.P["CV_X"], HM.P["LIFT"][1], 0.0, carrying=True)
    lift = [p for p in hb if p.joint in ("lift", "fork")] + [p for p in hb if p.group in ("load", "load_wp")]
    mast = [p for p in hb if p.name.startswith("mast_tube")]
    Im = 4 * (I_PROF[15] + A_PROF[15] * HM.P["TUBE_DX"] ** 2)
    member("HBW mast", "travel acceleration, carriage at the top", HM.P["TUBE_Z"][1] - HM.P["TUBE_Z"][0], E_AL, Im,
           _mass(lift), _mass(mast), V.PHYS["a_mm"]["travel"], "4 x 15x15 profile")
    load = [p for p in hb if p.group in ("load", "load_wp")]
    fork = [p for p in hb if p.joint == "fork"]
    st2 = next(p for p in hb if p.name == "ausleger_stage2")
    member("Ausleger stage 2", "mould + cookie, gravity + lift", HM.P["FORK"][1] + 40, E_AL,
           st2.s[0] * st2.s[2] ** 3 / 12, _mass(load) + _mass([p for p in fork if p.name == "fork_table"]),
           _mass([st2]), G + V.PHYS["a_mm"]["lift"], f"alu {st2.s[0]:.0f}x{st2.s[2]:.0f}")
    st1 = next(p for p in hb if p.name == "ausleger_stage1")
    if UP7:
        E1, I1, sec1 = E_AL, I_PROF[20], "20x20 profile (U7: replaces the ft block, same envelope)"
    else:
        E1, I1, sec1 = E_PA, st1.s[0] * st1.s[2] ** 3 / 12, f"PA6 ft block {st1.s[0]:.0f}x{st1.s[2]:.0f}"
    member("Ausleger stage 1", "stage 2 + mould + cookie, gravity + lift", st1.s[1], E1, I1,
           _mass(load) + _mass(fork), _mass([st1]), G + V.PHYS["a_mm"]["lift"], sec1)
    for s in U.sag_report():
        if s["case"] == "cantilever":
            m = s["F_N"] / 9.81
            member(f"oven {s['member']}", s["carries"], s["L_mm"], s["E_MPa"], s["I_mm4"], m, 0.0, G, s["section"],
                   note="U1 sag member; the load taken as its mass under gravity")
    return rows


# ------------------------------------------------------------------ check
def check(doc, health, verbose=True):
    fails = []
    ch = chains()
    fails += [f"TOLERANCE {c['id']} {c['what']}: worst case {c['worst']} mm" for c in ch if not c["ok"]]
    ac = access(doc)
    fails += [f"ACCESS {a['module']} {a['part']}: " + ("blocked above and at the sides by " + ", ".join(a["blocked_by"])
                                                       if a["from"] == "blocked" else f"{a['reach_mm']} mm from door {a['door']}")
              for a in ac if not a["ok"]]
    st = structure()
    fails += [f"STRUCTURE {s['member']}: {s['defl_mm']} mm, {s['f1_hz']} Hz" for s in st if not s["ok"]]
    if verbose:
        for c in ch:
            print(f"  {c['id']} {c['what']:45s} nominal {c['nominal']:6.2f}  worst {c['worst']:6.2f}  rss {c['rss']:6.2f}")
        print(f"  access: {sum(a['ok'] for a in ac)}/{len(ac)} serviceable parts clear from above and within reach")
        for a in ac:
            if not a["ok"]:
                print(f"    - {a['module']} {a['part']}: above {'clear' if a['above_clear'] else a['blocked_by']}, "
                      f"{a['reach_mm']} mm from door {a['door']}")
        for s in st:
            print(f"  {s['member']:22s} {s['defl_mm']:7.3f} mm  {s['f1_hz']:6.1f} Hz  {'ok' if s['ok'] else 'FAIL'}")
        print("\n".join(fails) if fails else "LIFECYCLE OK")
    return fails


def export(doc, health):
    ac = access(doc)
    return {"chains": chains(), "chains_before": base_chains() if UP7 else None, "access": ac,
            "spares": spares(doc, health), "plan": plan(health, ac), "structure": structure(),
            "rules": {"reach_mm": REACH, "defl_dyn_mm": DEFL_DYN, "f_min_hz": F_MIN},
            "assumed": "tolerance contributors, densities (ft blocks 35 % solid PA6, profiles 45 % alu), "
                       "the profile section area, the reach"}
