"""
The STF's mechanisms as precise FreeCAD solids, beside the nine ft components
(components_cad.py): the parts the upgrades added or that carry the lift, each a
3D view in the twin's component list.

    /Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd mechanisms_cad.py
                                                       (from stf-cad/hbw; or `make mechanisms`)

  drag_chain   the lift's drag chain (cable carrier), Upgrade 3 - chains.py
  lift_screw   the lift's spindle drive: 4 mm pitch spindle, nut, coupling - hbw_model.py
  rfid_head    an RFID read/write head under the belt, Upgrade 4 - hbw_model.py

Every number comes from the model that the proofs run on (chains.py, hbw_model.py,
the exported parts list); what the model only assumes is labelled "assumed". Each
solid is checked against those numbers to 0.01 mm before anything is written.
Writes web/public/components/<id>.glb, <id>.step and mechanisms.json (the twin
merges it with components.json); the .FCStd files go to .cache/mechanisms.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("STF_VARIANT", "up12")

import FreeCAD as App  # noqa: E402
import Part  # noqa: E402

import chains  # noqa: E402
from components_cad import COLOURS, bevelled_box  # noqa: E402

V = App.Vector
WEB_DIR = os.path.abspath(os.path.join(HERE, "..", "..", "web", "public", "components"))
CAD_DIR = os.path.join(HERE, ".cache", "mechanisms")
TOL_MM = 0.01
PARTS = json.load(open(os.path.join(HERE, "..", "..", "web", "public", "hbw_parts_up12.json")))["parts"]
PLC = json.load(open(os.path.join(HERE, "..", "..", "web", "public", "sil", "plc.json")))
COLOURS = {**COLOURS, "chain": "#2b2d31", "pom_white": "#ecebe4", "alu": "#c9ced4", "tag": "#f4f1e8"}


def part_note(name):
    return next((p.get("note", "") for p in PARTS if p["n"] == name), "")


# ================================================================ the drag chain
LIFT = chains.HBW["lift"]
CH_R, CH_H, CH_W, CH_L = LIFT["R"], LIFT["h"], LIFT["w"], chains.length(LIFT)
CH_N = 29                                                # links: the chain length in ~15 mm pitches
CH_P = CH_L / CH_N
CH_WALL = chains.WALL
CH_ZF = LIFT["F"][2]                                     # the fixed end, under the mast top plate
CH_ZM0 = LIFT["stroke"][0] + LIFT["M"][2]                # the moving end at the lowest lift
CH_TRAVEL = LIFT["stroke"][1] - LIFT["stroke"][0]
CH_U0 = 0.5                                              # the pose the solids are built in


def chain_path(s, u):
    """Point and tangent angle (about +Y) at arc length s from the fixed end, lift at u (0..1)."""
    zm = CH_ZM0 + CH_TRAVEL * u
    zc = (CH_ZF + zm + math.pi * CH_R - CH_L) / 2.0
    la = CH_ZF - zc
    if s <= la:
        p, t = (0.0, CH_ZF - s), (0.0, -1.0)
    elif s <= la + math.pi * CH_R:
        a = (s - la) / CH_R
        p, t = (CH_R - CH_R * math.cos(a), zc - CH_R * math.sin(a)), (math.sin(a), -math.cos(a))
    else:
        p, t = (2 * CH_R, zc + (s - la - math.pi * CH_R)), (0.0, 1.0)
    return p, math.degrees(math.atan2(-t[1], t[0]))


def chain_link():
    """One link at the origin: side plates with rounded ends, two crossbars; X along the chain."""
    def plate(y0):
        b = Part.makeBox(CH_P, CH_WALL, CH_H - 2.0, V(-CH_P / 2, y0, -(CH_H - 2.0) / 2))
        for x in (-CH_P / 2, CH_P / 2):
            b = b.fuse(Part.makeCylinder((CH_H - 2.0) / 2, CH_WALL, V(x, y0, 0), V(0, 1, 0)))
        pin = Part.makeCylinder(1.6, CH_WALL, V(CH_P / 2, y0, 0), V(0, 1, 0))
        return b.fuse(pin)
    side = plate(-CH_W / 2).fuse(plate(CH_W / 2 - CH_WALL))
    inner = CH_W - 2 * CH_WALL
    bars = [Part.makeBox(3.0, inner, 1.5, V(-1.5, -inner / 2, z)) for z in (CH_H / 2 - 1.5, -CH_H / 2)]
    return side.fuse(bars).removeSplitter()


def placed(shape, s, u):
    (x, z), ang = chain_path(s, u)
    sh = shape.copy()
    sh.rotate(V(0, 0, 0), V(0, 1, 0), ang)
    sh.translate(V(x, 0, z))
    return sh


def drag_chain():
    link = chain_link()
    parts = [(f"link_{i:02d}", placed(link, (i + 0.5) * CH_P, CH_U0), "chain", "pa", True) for i in range(CH_N)]
    fixed = Part.makeBox(15.0, CH_W + 6, 14.0, V(-7.5, -CH_W / 2 - 3, CH_ZF))
    zm = CH_ZM0 + CH_TRAVEL * CH_U0
    moving = Part.makeBox(15.0, CH_W + 6, 12.0, V(2 * CH_R - 7.5, -CH_W / 2 - 3, zm))
    parts += [("bracket_fixed", fixed, "red", "abs", True), ("bracket_moving", moving, "red", "abs", True)]
    return parts


# ================================================================ the lift's spindle drive
SP_D, SP_PITCH = 12.0, 4.0                               # hbw_model.py: LIFT_SPINDLE_D, PITCH_MM
SP_LEN, SP_DEPTH = 160.0, 0.9                            # a 160 mm stretch of it; thread depth assumed
NUT_AF, NUT_H = 22.0, 20.0                               # the nut's hex (assumed)
CPL_D, CPL_H = 16.0, 14.0                                # M3_coupler in hbw_model.py
NUT_Z0 = 40.0


def lift_screw():
    core = Part.makeCylinder(SP_D / 2 - SP_DEPTH, SP_LEN)
    helix = Part.makeHelix(SP_PITCH, SP_LEN - SP_PITCH, SP_D / 2 - SP_DEPTH)
    r0, r1 = SP_D / 2 - SP_DEPTH - 0.05, SP_D / 2
    prof = Part.makePolygon([V(r0, 0, -SP_PITCH * 0.3), V(r1, 0, -0.25), V(r1, 0, 0.25), V(r0, 0, SP_PITCH * 0.3),
                             V(r0, 0, -SP_PITCH * 0.3)])
    prof.translate(V(0, 0, SP_PITCH / 2))
    thread = Part.Wire(helix).makePipeShell([prof], True, True)
    spindle = core.fuse(thread)
    hexagon = [V(NUT_AF / math.sqrt(3) * math.cos(math.radians(60 * k + 30)),
                 NUT_AF / math.sqrt(3) * math.sin(math.radians(60 * k + 30)), 0) for k in range(7)]
    nut = Part.Face(Part.makePolygon(hexagon)).extrude(V(0, 0, NUT_H))
    nut = nut.cut(Part.makeCylinder(SP_D / 2 + 0.05, NUT_H + 1, V(0, 0, -0.5)))
    flange = Part.makeCylinder(NUT_AF / 2 + 4, 3.0).cut(Part.makeCylinder(SP_D / 2 + 0.05, 4, V(0, 0, -0.5)))
    nut = nut.fuse(flange).removeSplitter()
    nut.translate(V(0, 0, NUT_Z0))
    cpl = Part.makeCylinder(CPL_D / 2, CPL_H, V(0, 0, SP_LEN))
    for z in (SP_LEN + 3.5, SP_LEN + CPL_H - 3.5):
        cpl = cpl.cut(Part.makeCylinder(1.5, 4.0, V(CPL_D / 2 - 2.5, 0, z), V(1, 0, 0)))
    shaft = Part.makeCylinder(2.0, 7.5, V(0, 0, SP_LEN + CPL_H))
    shaft = shaft.cut(Part.makeBox(5, 5, 8, V(-2.5, 1.3, SP_LEN + CPL_H - 0.2)))    # the motor shaft's flat
    bearing = Part.makeCylinder(11.0, 8.0, V(0, 0, -8.0)).cut(Part.makeCylinder(SP_D / 2 + 0.1, 9, V(0, 0, -8.5)))
    return [("spindle", spindle, "steel", "steel", True), ("nut", nut, "pom", "pom", True),
            ("coupling", cpl, "steel", "steel", True), ("motor_shaft", shaft, "steel", "steel", False),
            ("bearing_block", bearing, "black", "abs", True)]


# ================================================================ the RFID read head
RF_L, RF_W, RF_H = 36.0, 40.0, 24.0                      # hbw_model.py: size ASSUMED
RF_GAP = 10.0                                            # head face to mould base


def rfid_head():
    body = bevelled_box(RF_L, RF_W, RF_H, 1.0)
    face = Part.makeBox(RF_L - 8, RF_W - 8, 0.6, V(4, 4, RF_H - 0.3))
    led = Part.makeCylinder(1.5, 1.2, V(RF_L - 5, RF_W - 5, RF_H))
    conn = Part.makeCylinder(4.0, 10.0, V(RF_L, RF_W / 2, 7.0), V(1, 0, 0))
    thread = Part.makeCylinder(4.6, 4.0, V(RF_L + 6.0, RF_W / 2, 7.0), V(1, 0, 0))
    cable = Part.makeCylinder(2.5, 30.0, V(RF_L + 10.0, RF_W / 2, 7.0), V(1, 0, 0))
    mould = Part.makeBox(60.0, 64.0, 8.0, V(RF_L / 2 - 30, RF_W / 2 - 32, RF_H + RF_GAP))
    tag = Part.makeCylinder(10.0, 1.0, V(RF_L / 2, RF_W / 2, RF_H + RF_GAP - 1.0))
    return [("housing", body, "black", "abs", True), ("sensing_face", face, "blue", "abs", True),
            ("status_led", led, "green", "abs", True), ("connector_m8", conn.fuse(thread), "steel", "brass", False),
            ("cable", cable, "rubber", "pvc", False), ("mould_base", mould, "grey", "abs", False),
            ("tag", tag, "tag", "pom", False)]


# ================================================================ the records
def mm(v):
    return round(v, 3)


def bbox(shape):
    return shape.optimalBoundingBox(True, False)


def chain_rows():
    _, rows = chains.check(verbose=False)
    return rows


def records():
    rows = {(r["module"], r["id"]): r for r in chain_rows()}
    lift = rows[("hbw", "lift")]
    io = {e["name"]: e for a in ("ix", "iw") for e in PLC["io"][a]}
    out = {}
    out["drag_chain"] = dict(
        kind="mechanism", ft="U3", upgrade="Upgrade 3", name="Drag chain (cable carrier)", name_de="Energiekette",
        datasheet="chains.py - the model's drag-chain proof", material="glass-fibre polyamide links (assumed)",
        facts=[("What it does", "carries the moving axes' cables so they bend on a fixed radius instead of chafing", "model"),
               ("Where", "HBW lift: hangs beside the mast, fixed under the top plate, moving end on the carriage's right leg", "model"),
               ("Length", f"{CH_L:.0f} mm, {CH_N} links of {CH_P:.2f} mm", "model"),
               ("Bend radius", f"{CH_R:.0f} mm; the cables need at least {lift['bend_min']} mm (7.5 x 1.4 mm conductor)", "model"),
               ("Link size", f"{CH_H:.0f} mm high, {CH_W:.0f} mm wide, {CH_WALL} mm wall", "assumed"),
               ("Stroke", f"lift {LIFT['stroke'][0]:.0f}-{LIFT['stroke'][1]:.0f} mm; the loop moves half as far as the carriage", "model"),
               ("Carries", f"{lift['conductors']} conductors ({', '.join(lift['devices'])}); fill {lift['fill']:.0%} of the inner section, limit 60 %", "model"),
               ("Proved", "chains.py: length fits the whole stroke, the loop never bottoms out, bend radius, fill, span; every moving device on a chain path", "model")],
        dims=[dict(key="L", label="chain length", value=CH_L, source="model", note="chains.HBW['lift']['Lc']"),
              dict(key="R", label="bend radius", value=CH_R, source="model", note=""),
              dict(key="h", label="link height", value=CH_H, source="assumed", note="a small plastic chain"),
              dict(key="w", label="link width", value=CH_W, source="assumed", note=""),
              dict(key="p", label="link pitch", value=mm(CH_P), source="model", note="length / links"),
              dict(key="wall", label="link wall", value=CH_WALL, source="assumed", note=""),
              dict(key="stroke", label="lift stroke", value=CH_TRAVEL, source="model", note="")],
        used_in=[{"module": m.upper(), "part": f"chain_{cid}_env", "io": f"{r['conductors']} conductors",
                  "terminal": f"{r['fixed']} -> {r['moving']}",
                  "function": f"{cid}: {r['length']:.0f} mm chain, R {r['R']:.0f}, stroke {r['stroke'][0]:.0f}-{r['stroke'][1]:.0f} mm"}
                 for (m, cid), r in rows.items()],
        motion=[{"part": "link", "type": "chain", "axis": [0, 1, 0], "links": CH_N, "pitch": mm(CH_P), "R": CH_R,
                 "length": CH_L, "zF": CH_ZF, "zM0": CH_ZM0, "travel": CH_TRAVEL, "u0": CH_U0, "dps": 30,
                 "moving": "bracket_moving"}],
        operate="lift up and down")
    out["lift_screw"] = dict(
        kind="mechanism", ft="HBW", upgrade="base machine", name="Lift spindle drive", name_de="Hubspindel mit Mutter",
        datasheet="hbw_model.py - lift_spindle, M3_coupler, lift carriage", material="steel spindle, POM nut (assumed)",
        facts=[("What it does", "turns the lift motor's rotation into the carriage's up-and-down travel", "model"),
               ("Spindle", f"D {SP_D:.0f} mm, {SP_PITCH:.0f} mm pitch: one turn lifts the carriage {SP_PITCH:.0f} mm", "model"),
               ("Encoder scale", f"75 pulses per output turn / {SP_PITCH:.0f} mm = {75 / SP_PITCH:.2f} pulses per mm", "model"),
               ("Speed", f"214 rpm at the motor's max-power point x {SP_PITCH:.0f} mm = {214 * SP_PITCH / 60:.2f} mm/s", "model"),
               ("Motor", "Encodermotor 144643 upright on the mast head, shaft down into the coupling", "model"),
               ("Nut", "rides in the lift carriage's left leg (fit checked as a thread, 0.05 mm)", "model"),
               ("Also used", "the travel axis (horizontal spindle) and the Ausleger use the same 4 mm pitch", "model"),
               ("Thread form, nut size", "not in the model - drawn as a trapezoid thread and a 22 mm hex", "assumed")],
        dims=[dict(key="d", label="spindle diameter", value=SP_D, source="model", note="LIFT_SPINDLE_D"),
              dict(key="P", label="pitch", value=SP_PITCH, source="model", note="PITCH_MM"),
              dict(key="cpl_d", label="coupling diameter", value=CPL_D, source="model", note="M3_coupler"),
              dict(key="cpl_h", label="coupling length", value=CPL_H, source="model", note=""),
              dict(key="len", label="length shown", value=SP_LEN, source="assumed", note="a stretch of the spindle"),
              dict(key="depth", label="thread depth", value=SP_DEPTH, source="assumed", note=""),
              dict(key="nut", label="nut across flats", value=NUT_AF, source="assumed", note="")],
        used_in=[{"module": "HBW", "part": p["n"], "io": p.get("tag", ""), "terminal": p.get("mech", ""),
                  "function": p.get("note", "")} for p in PARTS if str(p.get("mech", "")).startswith("thread:")],
        motion=[{"part": "nut", "type": "screw", "axis": [0, 0, 1], "pitch": SP_PITCH, "travel": 80.0, "dps": 45,
                 "turns": ["spindle", "coupling", "motor_shaft"]}],
        operate="drive the motor")
    out["rfid_head"] = dict(
        kind="mechanism", ft="U4", upgrade="Upgrade 4", name="RFID read/write head", name_de="RFID-Schreib-/Lesekopf",
        datasheet="hbw_model.py - rfid_rp1/rp2_head; control.py", material="ABS housing (assumed)",
        facts=[("What it does", "reads the tag in each mould's base, so the PLC knows which mould (and cookie) is on the belt", "model"),
               ("Standard", "13.56 MHz, ISO 15693 tags, IO-Link to the PLC", "model"),
               ("Where", "two read points under the conveyor belt, between its two strips", "model"),
               ("Read distance", f"{RF_GAP:.0f} mm from the head's face to the mould base", "model"),
               ("PLC signals", ", ".join(f"{k} {io[k]['addr']}" for k in ("hbw_RF1_Valid", "hbw_RF2_Valid", "hbw_RF2_Tag") if k in io), "model"),
               ("Size", f"{RF_L:.0f} x {RF_W:.0f} x {RF_H:.0f} mm", "assumed")],
        dims=[dict(key="L", label="housing length", value=RF_L, source="assumed", note="size ASSUMED in hbw_model.py"),
              dict(key="W", label="housing width", value=RF_W, source="assumed", note=""),
              dict(key="H", label="housing height", value=RF_H, source="assumed", note=""),
              dict(key="gap", label="face to mould base", value=RF_GAP, source="model", note="")],
        used_in=[{"module": "HBW", "part": p["n"], "io": p.get("tag", ""), "terminal": "IO-Link",
                  "function": p.get("note", "")[:120]} for p in PARTS if p["n"].startswith("rfid_") and p["n"].endswith("_head")],
        motion=[{"part": "mould_base", "type": "reciprocate", "axis": [1, 0, 0], "amp": 70.0, "dps": 60},
                {"part": "tag", "type": "reciprocate", "axis": [1, 0, 0], "amp": 70.0, "dps": 60}],
        operate="belt runs")
    return out


def verify(cid, parts):
    sh = {n: s for n, s, *_ in parts}
    checks = []

    def chk(label, want, have, source="model"):
        checks.append({"check": label, "datasheet_mm": mm(want), "model_mm": mm(have), "ok": abs(want - have) <= TOL_MM,
                       "source": source})
    if cid == "drag_chain":
        b = bbox(chain_link())
        chk("link height", CH_H, b.ZLength, "assumed")
        chk("link width", CH_W, b.YLength, "assumed")
        chk("links x pitch = chain length", CH_L, CH_N * CH_P)
        p_end, _ = chain_path(CH_L, CH_U0)
        chk("chain ends at the moving bracket (x)", 2 * CH_R, p_end[0])
        chk("chain ends at the moving bracket (z)", CH_ZM0 + CH_TRAVEL * CH_U0, p_end[1])
        low = min(chain_path(s, 0.0)[0][1] for s in [k * 0.5 for k in range(int(CH_L * 2) + 1)])
        checks.append({"check": "loop clears the floor at the lowest lift", "datasheet_mm": LIFT["floor"],
                       "model_mm": mm(low - CH_H / 2), "ok": low - CH_H / 2 >= LIFT["floor"], "source": "model"})
    elif cid == "lift_screw":
        b = bbox(sh["spindle"])
        chk("spindle diameter", SP_D, b.XLength)
        chk("coupling diameter", CPL_D, bbox(sh["coupling"]).XLength)
        chk("coupling length", CPL_H, bbox(sh["coupling"]).ZLength)
    elif cid == "rfid_head":
        b = bbox(sh["housing"])
        chk("housing length", RF_L, b.XLength, "assumed")
        chk("housing width", RF_W, b.YLength, "assumed")
        chk("housing height", RF_H, b.ZLength, "assumed")
        chk("face to mould base", RF_GAP, bbox(sh["mould_base"]).ZMin - b.ZMax)
    fails = [f"{cid}: {c['check']} {c['model_mm']} != {c['datasheet_mm']}" for c in checks if not c["ok"]]
    fails += [f"{cid}: {n} is not a valid solid" for n, s, *_ in parts if not s.Solids or not all(x.isValid() for x in s.Solids)]
    return checks, fails


def write_glb(cid, parts):
    """As components_cad.write_glb. The chain's links are meshed where they are built (u0); the
    viewer moves each from that pose along the chain's path (the motion record)."""
    import stf_web_glb as WG
    g = WG.WebGltf()
    kids = []
    for n, s, col, mat, inside in parts:
        swept = n in ("spindle",)
        pos, nrm, idx = WG.face_mesh(s, (0.05, 0.35) if swept else (0.01, 0.1))
        g._cls = "metal" if mat in ("steel", "brass") else "plastic"
        m = g.mesh(n, pos, nrm, idx, COLOURS[col])
        kids.append(g.node(n, mesh=m, extras={"part": n, "material": mat, "colour": COLOURS[col], "inside_envelope": inside}))
    open(os.path.join(WEB_DIR, f"{cid}.glb"), "wb").write(g.glb(kids))
    return sum(a["count"] for a in g.acc if a["type"] == "SCALAR") // 3


def write_cad(cid, parts):
    import Import
    for d in list(App.listDocuments()):
        App.closeDocument(d)
    doc = App.newDocument(cid)
    cont = doc.addObject("App::Part", cid)
    for n, s, *_ in parts:
        o = doc.addObject("Part::Feature", n)
        o.Shape = s
        cont.addObject(o)
    doc.recompute()
    os.makedirs(CAD_DIR, exist_ok=True)
    Import.export([cont], os.path.join(WEB_DIR, f"{cid}.step"))
    doc.saveAs(os.path.join(CAD_DIR, f"{cid}.FCStd"))
    App.closeDocument(doc.Name)


BUILDERS = {"drag_chain": drag_chain, "lift_screw": lift_screw, "rfid_head": rfid_head}


def main():
    recs = records()
    built, all_fail = {}, []
    for cid, fn in BUILDERS.items():
        parts = fn()
        res, fails = verify(cid, parts)
        all_fail += fails
        built[cid] = (parts, res)
    if all_fail:
        print("REFUSING to write - mechanisms fail their checks:\n" + "\n".join(all_fail))
        sys.exit(1)
    os.makedirs(WEB_DIR, exist_ok=True)
    manifest = {}
    for cid, (parts, res) in built.items():
        write_cad(cid, parts)
        ntri = write_glb(cid, parts)
        bb = App.BoundBox()
        for _, s, *_ in parts:
            bb.add(bbox(s))
        r = recs[cid]
        manifest[cid] = {**{k: r[k] for k in ("kind", "ft", "upgrade", "name", "name_de", "datasheet", "material")},
                         "facts": [{"label": a, "value": b, "source": c} for a, b, c in r["facts"]],
                         "dims": r["dims"],
                         "parts": [{"name": n, "material": mat, "colour": COLOURS[col], "inside_envelope": inside}
                                   for n, s, col, mat, inside in parts],
                         "verification": res,
                         "overall_mm": [mm(bb.XLength), mm(bb.YLength), mm(bb.ZLength)],
                         "bbox_mm": [mm(v) for v in (bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax)],
                         "mesh": {"triangles": ntri, "chordal_tolerance_mm": 0.01},
                         "files": {"glb": f"{cid}.glb", "step": f"{cid}.step", "fcstd": f"stf-cad/hbw/.cache/mechanisms/{cid}.FCStd"},
                         "used_in": r["used_in"], "motion": r["motion"], "operate": r["operate"], "xray": False,
                         "generator": "mechanisms_cad.py"}
        print(f"{cid:12s} {r['upgrade']:14s} checks {sum(c['ok'] for c in res)}/{len(res)}  {ntri} tris  "
              f"used {len(r['used_in'])}x")
    json.dump({"components": manifest,
               "sources": {"model": "this project's model (stf-cad/hbw), held by its proofs",
                           "assumed": "not documented - an assumption of the model"}},
              open(os.path.join(WEB_DIR, "mechanisms.json"), "w"), indent=1)
    print(f"wrote {WEB_DIR}/<id>.glb, <id>.step and mechanisms.json")


if __name__ == "__main__" or sys.argv[-1].endswith("mechanisms_cad.py"):
    main()
