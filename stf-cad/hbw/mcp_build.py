"""
Build the complete STF factory INSIDE a running FreeCAD GUI (via the FreeCAD MCP
run_script), one step at a time, from the same parameter tables as the headless
builder (stf_freecad.py). Also runs under freecadcmd, so every step can be proven
headless first.

    import sys; sys.path.insert(0, '/Users/sohampatel/workspace/stf-cad/hbw')
    import mcp_build as B
    B.step("proofs"); B.step("table"); B.step("hbw"); ...; B.step("wiring"); B.step("save")

Each step writes its result to REPORT (JSON), because the MCP run_script call
returns nothing but "success".

What is generated, and from where:
  solids        hbw_model / vgr_model / oven_model / sorting_model / plc_model,
                shaped by detail.precise() (asserts every shape stays inside the
                envelope the clearance proofs ran against)
  joints        nested App::Part containers, the same tree as stf_freecad.py
  components    every I/O part whose Belegungsplan kind is one of the nine ft
                components is REPLACED by that component's B-rep
                (components_cad.BUILDERS - the geometry exported to
                stf-factory/cad/components/<id>.step, cross-checked against the
                STEP file) placed by the `fit` block in hbw_parts.json:
                Placement(centre) * R(cols = sign_i * e_perm_i) * Placement(-origin)
  wiring        hbw_parts.json -> wiring: every conductor its own swept tube in its
                IEC role colour; hoses translucent PU tube
"""
import json
import math
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import FreeCAD as App
import Part

import hbw_model as HM, vgr_model as VG, oven_model as OM, sorting_model as SM
import plc_model as PM
import factory_layout as FL
import detail
from hbw_frames import by_frame as hbw_by_frame

V = App.Vector
OUT_DIR = os.path.expanduser("~/workspace/stf-factory/cad")
FCSTD = os.path.join(OUT_DIR, "STF_Factory_MCP.FCStd")
STEP = os.path.join(OUT_DIR, "STF_Factory_MCP.step")
PARTS_JSON = os.path.expanduser("~/workspace/stf-hw/web/public/hbw_parts.json")
COMP_DIR = os.path.join(OUT_DIR, "components")
REPORT = os.environ.get("STF_MCP_REPORT", os.path.join(HERE, "mcp_report.json"))
SHOTS = os.environ.get("STF_MCP_SHOTS", os.path.join(HERE, "mcp_shots"))
DOC = "STF_Factory_MCP"

# model colour names -> hex (stf_freecad.COLOURS, plus the table and plates)
COLOURS = {
    "black": "#2b2b2f", "red": "#cf3a2f", "ftred": "#e0492f", "alu": "#d6d9da",
    "steel": "#aeb4b8", "white": "#f2f0ea", "colour": "#2f6fd0", "green": "#1b8f52",
    "amber": "#e0a02a", "grey": "#8b9196", "darkgrey": "#474b52", "slate": "#3a3f44",
}
TABLE_WHITE = "#f4f3ef"
PLATE_BLACK = "#1c1d20"
GRID = 15.0                  # ft base plate grid (mm)
WIRE_D = 1.4                 # single conductor, outer diameter (assumed, measure)
BUNDLE_WIRE_D = 1.0          # conductor inside a PCB -> PLC bundle (assumed)
HOSE_D, HOSE_ID = 4.0, 2.5   # ft PU hose (assumed, measure)
BEND_R = 10.0                # wiring.py: Manhattan routes, bend radius 10

MODULE_KEYS = {"hbw": "HBW_Hochregallager", "vgr": "VGR_Sauggreifer", "oven": "OVEN_Brennofen",
               "sorting": "SORT_Sortierstrecke", "plc": "PLC_Schaltschrank"}

_state = {}


# ============================================================== utilities
def hexof(c):
    return c if isinstance(c, str) and c.startswith("#") else COLOURS.get(c, "#8b9196")


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def gui():
    return App.GuiUp and App.ActiveDocument is not None and App.ActiveDocument.Name == DOC


def doc():
    d = App.listDocuments().get(DOC)
    if d is None:
        raise RuntimeError(f"document {DOC} not open - run step('table') first")
    return d


def paint(o, hexcol, transparency=0):
    """Colour via the ViewObject (GUI). Headless keeps it in STF_Colour."""
    if "STF_Colour" not in o.PropertiesList:
        o.addProperty("App::PropertyString", "STF_Colour", "STF")
    o.STF_Colour = hexcol
    if App.GuiUp and getattr(o, "ViewObject", None) is not None:
        vo = o.ViewObject
        vo.ShapeColor = rgb(hexcol)
        vo.Transparency = int(transparency)
        if hasattr(vo, "LineColor"):
            r, g, b = rgb(hexcol)
            vo.LineColor = (r * 0.45, g * 0.45, b * 0.45)


def props(o, **kv):
    for k, v in kv.items():
        nm = "STF_" + k
        if nm not in o.PropertiesList:
            o.addProperty("App::PropertyString", nm, "STF")
        setattr(o, nm, str(v)[:240])


def safe(name):
    return "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in name)


def container(label, parent=None, t=(0, 0, 0), rot=0.0):
    d = doc()
    c = d.addObject("App::Part", safe(label))
    c.Label = label
    c.Placement = App.Placement(V(*t), App.Rotation(V(0, 0, 1), rot))
    if parent is not None:
        parent.addObject(c)
    _hide_origin(c)
    return c


def _hide_origin(c):
    if not App.GuiUp:
        return
    try:
        org = c.Origin
        org.ViewObject.Visibility = False
        for f in org.OriginFeatures:
            f.ViewObject.Visibility = False
    except Exception:
        pass


def feature(name, shape, parent, colour, transparency=0, label=None):
    o = doc().addObject("Part::Feature", safe(name))
    o.Label = label or name
    o.Shape = shape
    parent.addObject(o)
    paint(o, colour, transparency)
    return o


def report(step, data):
    try:
        allr = json.load(open(REPORT))
    except Exception:
        allr = {}
    data["t"] = time.strftime("%H:%M:%S")
    allr[step] = data
    allr["_last"] = step
    json.dump(allr, open(REPORT, "w"), indent=1, default=str)


def step(step_name, **kw):
    """Run one build step; the outcome (or the traceback) goes to REPORT."""
    t0 = time.time()
    try:
        data = STEPS[step_name](**kw) or {}
        data["ok"] = data.get("ok", True)
    except Exception as e:
        data = {"ok": False, "error": repr(e), "traceback": traceback.format_exc()[-3000:]}
    data["seconds"] = round(time.time() - t0, 1)
    report(step_name, data)
    return data


# ============================================================== proofs
def s_proofs():
    import vgr_path
    checks = (("HBW", HM.check(verbose=False)), ("VGR", VG.check(verbose=False)),
              ("OVEN", OM.check(verbose=False)), ("SORTING", SM.check(verbose=False)),
              ("PLC", PM.check(verbose=False) if hasattr(PM, "check") else []),
              ("CROSS", FL.check_cross() + FL.check_stations()),
              ("VGR PATH", vgr_path.check(verbose=False)))
    import mechanics, motion
    checks = checks + (("GUIDES", mechanics.check_guides("vgr")[0] + mechanics.check_guides("hbw")[0]),
                       ("OVEN MOTION", motion.check_oven()))
    fails = {n: f[:6] for n, f in checks if f}
    return {"ok": not fails, "fails": fails, "checked": [n for n, _ in checks]}


# ============================================================== parts table
def _json():
    if "json" not in _state:
        _state["json"] = json.load(open(PARTS_JSON))
    return _state["json"]


def _fits(module):
    d = _json()
    parts = {"hbw": d["parts"], "vgr": d["vgr"]["parts"], "oven": d["oven"]["parts"],
             "sorting": d["sorting"]["parts"], "plc": d["plc"]["parts"]}[module]
    return {q["n"]: q for q in parts if "fit" in q}, {q["n"]: q for q in parts}


# ============================================================== components
def _component(cid):
    """Sub-parts of one ft component, verified against its datasheet table and
    cross-checked against the exported STEP file."""
    cache = _state.setdefault("comp", {})
    if cid in cache:
        return cache[cid]
    import components_cad as CC
    parts = CC.BUILDERS[cid]()
    res, fails = CC.verify(cid, parts)
    if fails:
        raise AssertionError(f"component {cid} fails its datasheet check: {fails}")
    comp = Part.makeCompound([s for _, s, *_ in parts])
    step_path = os.path.join(COMP_DIR, f"{cid}.step")
    xs = {}
    if os.path.exists(step_path):
        ref = Part.read(step_path)
        v0, v1 = comp.Volume, ref.Volume
        b0, b1 = comp.BoundBox, ref.BoundBox
        dbb = max(abs(a - b) for a, b in zip(
            (b0.XMin, b0.YMin, b0.ZMin, b0.XMax, b0.YMax, b0.ZMax),
            (b1.XMin, b1.YMin, b1.ZMin, b1.XMax, b1.YMax, b1.ZMax)))
        xs = {"step_volume": round(v1, 3), "built_volume": round(v0, 3),
              "volume_rel_err": round(abs(v0 - v1) / max(v1, 1e-9), 6), "bbox_max_dev_mm": round(dbb, 4)}
        if xs["volume_rel_err"] > 1e-3 or dbb > 0.01:
            raise AssertionError(f"component {cid} differs from {step_path}: {xs}")
    cache[cid] = (parts, CC.COLOURS, res, xs)
    return cache[cid]


def _fit_placement(fit, sign=None, origin=None, perm=None):
    perm, sign = perm or fit["perm"], sign or fit["sign"]
    m = [[0.0] * 3 for _ in range(3)]
    for i in range(3):
        m[perm[i]][i] = float(sign[i])       # component axis i -> model axis perm[i]
    mat = App.Matrix(m[0][0], m[0][1], m[0][2], 0,
                     m[1][0], m[1][1], m[1][2], 0,
                     m[2][0], m[2][1], m[2][2], 0,
                     0, 0, 0, 1)
    o = origin or fit["origin"]
    return (App.Placement(V(*fit["centre"]), App.Rotation()).multiply(App.Placement(mat))
            .multiply(App.Placement(V(*[-v for v in o]), App.Rotation())))


def _housing_centre(parts):
    hb = next(s for n, s, *_ in parts if n == "housing").optimalBoundingBox(True, False)
    return [(hb.XMin + hb.XMax) / 2, (hb.YMin + hb.YMax) / 2, (hb.ZMin + hb.ZMax) / 2]


def place_component(p, q, parent, log):
    """Replace model part p (exported dict q, which carries the fit) by the
    precise ft component at real size. The fit's axis permutation is kept, but
    the component is seated by its HOUSING centre (the datasheet envelope the
    model part stands for), not by its overall box - protrusions (shaft, wire
    stub, nipples) stick out of the envelope instead of shoving the housing off
    it. seat() then picks the sign variant."""
    fit = q["fit"]
    cid = fit["comp"]
    parts, cols, res, xs = _component(cid)
    c = container(f"{p.name}", parent)
    hc = _housing_centre(parts)
    c.Placement = _fit_placement(fit, origin=hc)
    props(c, Component=cid, IO=p.tag, Group=p.group, Note=p.note, Envelope=str(detail.envelope(p)),
          Oversize=str(fit["oversize_mm"]))
    for n, s, col, mat, inside in parts:
        o = feature(f"{p.name}__{n}", s.copy(), c, cols[col], label=f"{p.name}.{n}")
        props(o, Material=mat, Component=cid, Sub=n)
    _state.setdefault("seat", []).append((c.Name, p, fit, hc))
    log.append({"part": p.name, "comp": cid, "oversize_mm": fit["oversize_mm"]})
    return c


# output sub-part of each component, and what it must point at
OUTPUT = {"encoder_motor": "output_shaft", "s_motor": "output_axle",
          "pneumatic_cylinder": "rod_end"}
# sub-parts whose job is to enter the part they drive or pass through their mount
ENGAGE = {"output_shaft", "bearing_collar", "output_axle", "piston_rod", "rod_end"}
DRIVEN = ("coupler", "pinion", "pulley", "shaft", "spindle", "rod", "pusher", "paddle", "door")


def _rotations():
    """The 24 proper rotations that map axes onto axes: (perm, sign), det +1."""
    import itertools
    out = []
    for perm in itertools.permutations(range(3)):
        par = 1 if sum(1 for i in range(3) for j in range(i + 1, 3) if perm[i] > perm[j]) % 2 == 0 else -1
        for a in (1, -1):
            for b in (1, -1):
                out.append((list(perm), [a, b, par * a * b]))
    return out


def _box_dist(b, pt):
    dx = max(b.XMin - pt.x, 0, pt.x - b.XMax)
    dy = max(b.YMin - pt.y, 0, pt.y - b.YMax)
    dz = max(b.ZMin - pt.z, 0, pt.z - b.ZMax)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def seat(root):
    """For every component placed in this module: of the four proper rotations
    that keep the fit's permutation, take the one whose output (shaft / axle /
    piston rod) points at the part it drives, then the least interference with
    the module's other solids. Verifies the housing sits on the envelope."""
    d = doc()
    pending = _state.pop("seat", [])
    done = _state.setdefault("seated", [])
    # earlier modules' components within 30 mm of this module are re-seated:
    # the oven's belt motor can only see the sorting rail once the sorting line exists
    rb = App.BoundBox(*_global_bbox(root))
    rb.enlarge(30)
    for rec in list(done):
        o = d.getObject(rec[0])
        if o is not None and o.getGlobalPlacement() is not None:
            gb = App.BoundBox(*_global_bbox(o))
            if gb.intersect(rb):
                pending.append(rec)
                done.remove(rec)
    done.extend(pending)
    root = d.getObject("STF_Table")
    others = []

    def walk(x):
        if x.Name == "Wiring":
            return
        for ch in getattr(x, "Group", []) or []:
            walk(ch)
        if (x.TypeId == "Part::Feature" and not x.Name.endswith("base_plate")
                and x.Name != "Table_Top" and not x.Label.startswith(("Cable_", "Bundle_", "Power_", "Hose_"))):
            sh = x.Shape.copy()
            sh.Placement = x.getGlobalPlacement()
            others.append((x, sh, sh.BoundBox))
    walk(root)
    out = []
    for cname, p, fit, hc in pending:
        c = d.getObject(cname)
        cid = fit["comp"]
        own = set(o.Name for o in c.Group)
        env = detail.envelope(p)
        envb = App.BoundBox(*env)
        envb_g = App.BoundBox(envb)
        pg = c.getParentGeoFeatureGroup() if hasattr(c, "getParentGeoFeatureGroup") else None
        parent_pl = c.getGlobalPlacement().multiply(c.Placement.inverse())
        g_env = App.BoundBox()
        for x in (env[0], env[3]):
            for y in (env[1], env[4]):
                for z in (env[2], env[5]):
                    g_env.add(parent_pl.multVec(V(x, y, z)))
        near = [(o, sh, bb) for o, sh, bb in others if o.Name not in own
                and bb.intersect(App.BoundBox(g_env.XMin - 25, g_env.YMin - 25, g_env.ZMin - 25,
                                              g_env.XMax + 25, g_env.YMax + 25, g_env.ZMax + 25))]
        drives = [(o, sh, bb) for o, sh, bb in near if any(k in o.Label.lower() for k in DRIVEN)
                  and "STF_Component" not in (o.InList[0].PropertiesList if o.InList else [])]
        hb0 = next(o for o in c.Group if o.STF_Sub == "housing").Shape.optimalBoundingBox(True, False)
        hext = (hb0.XLength, hb0.YLength, hb0.ZLength)
        eext = (env[3] - env[0], env[4] - env[1], env[5] - env[2])
        best = None
        for pm, sg in _rotations():
            # housing outside its proven envelope (mm, summed over axes)
            excess = sum(max(0.0, hext[i] - eext[pm[i]]) for i in range(3))
            if excess > 30:
                continue
            c.Placement = _fit_placement(fit, sign=sg, origin=hc, perm=pm)
            gpl = c.getGlobalPlacement()
            subs = []
            for o in c.Group:
                sh = o.Shape.copy()
                sh.Placement = gpl.multiply(o.Placement)
                subs.append((o, sh, sh.BoundBox))
            vol = 0.0
            drive_names = {x.Name for x, *_ in drives}
            for o, sh, bb in subs:
                for n2, sh2, bb2 in near:
                    if n2.Name in drive_names or not bb.intersect(bb2):
                        continue
                    try:
                        vol += sh.common(sh2).Volume
                    except Exception:
                        vol += 1e3
            dd = 0.0
            outn = OUTPUT.get(cid)
            if outn and drives:
                osub = next((sh for o, sh, bb in subs if o.STF_Sub == outn), None)
                if osub is not None:
                    tip = osub.BoundBox.Center
                    dd = min(_box_dist(bb, tip) for _, _, bb in drives)
            same = pm == fit["perm"]
            score = (vol + 100.0 * excess + 50.0 * dd + (0 if same else 2.0)
                     - (1e-3 if same and sg == fit["sign"] else 0))
            if best is None or score < best[0]:
                best = (score, sg, vol, dd, pm, excess)
        c.Placement = _fit_placement(fit, sign=best[1], origin=hc, perm=best[4])
        # the housing must now sit on the envelope: centre exact, and where the
        # datasheet size equals the model size, the faces too
        hsg = next(o for o in c.Group if o.STF_Sub == "housing")
        hs = hsg.Shape.copy()
        hs.Placement = c.Placement.multiply(hsg.Placement)
        hb = hs.optimalBoundingBox(True, False)
        cen_dev = max(abs(a - b) for a, b in zip(
            ((hb.XMin + hb.XMax) / 2, (hb.YMin + hb.YMax) / 2, (hb.ZMin + hb.ZMax) / 2),
            ((env[0] + env[3]) / 2, (env[1] + env[4]) / 2, (env[2] + env[5]) / 2)))
        face_dev = [round((hb.XLength, hb.YLength, hb.ZLength)[i] - (env[i + 3] - env[i]), 3) for i in range(3)]
        if cen_dev > 0.01:
            raise AssertionError(f"{p.name}: housing centre off its envelope by {cen_dev:.4f} mm")
        props(c, Sign=str(best[1]), Perm=str(best[4]))
        out.append({"part": p.name, "comp": cid, "perm": best[4], "fit_perm": fit["perm"],
                    "sign": best[1], "fit_sign": fit["sign"], "housing_excess_mm": round(best[5], 2),
                    "interference_mm3": round(best[2], 2), "output_to_drive_mm": round(best[3], 2),
                    "housing_centre_dev_mm": round(cen_dev, 4), "housing_minus_envelope_mm": face_dev})
    return out


# ============================================================== geometry
def _solid(p, parent, fits, jparts, log, made):
    if p.group == "frame":
        return None
    if p.name in fits:
        made["components"] += 1
        return place_component(p, fits[p.name], parent, log)
    import detail_rich, mechanics
    module = jparts or ""
    subs = detail_rich.rich(p, module)
    if subs:
        # multi-colour detail (booklet photos), each sub-shape inside the envelope
        c = container(p.name, parent)
        props(c, Group=p.group, IO=p.tag, Mech=p.mech, Note=p.note, Envelope=str(detail.envelope(p)),
              Rich="1")
        for nm, sh, col in subs:
            o = feature(f"{p.name}__{nm}", sh, c, col, label=f"{p.name}.{nm}")
            props(o, Sub=nm)
        made["solids"] += 1
        return c
    shape = mechanics.guided(p, module, _state.get("siblings")) if module else \
        detail.precise(p, _state.get("siblings"))
    o = feature(p.name, shape, parent, hexof(p.colour))
    props(o, Group=p.group, IO=p.tag, Mech=p.mech, Note=p.note, Envelope=str(detail.envelope(p)))
    made["solids"] += 1
    return o


def base_plate(p, parent, name):
    """Black ft base plate: the model's plate envelope, with the 15 mm grid of
    grooves cut into its top (decoration only removes material)."""
    x0, y0, z0 = p.p
    dx, dy, dz = p.s
    w, dep = 1.2, 0.8
    # slab + the raised islands between the grooves, built directly (no boolean:
    # a grid cut on a 1 m plate costs ~20 s): identical to cutting the grooves
    xs = [x0] + [x0 + k * GRID for k in range(1, int((dx - 1) // GRID) + 1) if x0 + k * GRID < x0 + dx - 1] + [x0 + dx]
    ys = [y0] + [y0 + k * GRID for k in range(1, int((dy - 1) // GRID) + 1) if y0 + k * GRID < y0 + dy - 1] + [y0 + dy]
    zt = z0 + dz - dep
    solids = [Part.makeBox(dx, dy, dz - dep, V(x0, y0, z0))]
    for i in range(len(xs) - 1):
        xa = xs[i] + (w / 2 if i > 0 else 0)
        xb = xs[i + 1] - (w / 2 if i + 1 < len(xs) - 1 else 0)
        for j in range(len(ys) - 1):
            ya = ys[j] + (w / 2 if j > 0 else 0)
            yb = ys[j + 1] - (w / 2 if j + 1 < len(ys) - 1 else 0)
            solids.append(Part.makeBox(xb - xa, yb - ya, dep, V(xa, ya, zt)))
    plate = Part.makeCompound(solids)
    o = feature(name, plate, parent, PLATE_BLACK)
    props(o, Group="frame", Note=f"ft base plate {dx:.0f} x {dy:.0f} (model size, not yet measured), "
                                 f"{GRID:.0f} mm grid")
    return o


def _module(key, t=(0, 0, 0), rot=0.0):
    d = doc()
    old = d.getObject(safe(MODULE_KEYS[key]))
    if old is not None:
        _remove_tree(old)
    return container(MODULE_KEYS[key], d.getObject("STF_Table"), t, rot)


def _remove_tree(o):
    d = doc()
    names = []

    def walk(x):
        for c in getattr(x, "Group", []) or []:
            walk(c)
        names.append(x.Name)
        if x.TypeId == "App::Part":
            try:
                names.append(x.Origin.Name)
                names.extend(f.Name for f in x.Origin.OriginFeatures)
            except Exception:
                pass
    walk(o)
    for n in names:
        if d.getObject(n) is not None:
            try:
                d.removeObject(n)
            except Exception:
                pass


def _summary(key, made, log, model_parts, seated=()):
    d = doc()
    root = d.getObject(safe(MODULE_KEYS[key]))
    bb = _global_bbox(root)
    n_model = sum(1 for p in model_parts if p.group != "frame")
    over = [c for c in log if any(abs(v) > 0.05 for v in c["oversize_mm"])]
    return {"model_parts": n_model, "precise_solids": made["solids"], "components": made["components"],
            "all_parts_built": made["solids"] + made["components"] == n_model,
            "component_seating": list(seated), "components_bigger_than_envelope": [(c["part"], c["comp"], c["oversize_mm"])
                                                                      for c in over],
            "bbox_factory": [round(v, 1) for v in bb]}


def _global_bbox(root):
    bb = App.BoundBox()

    def walk(x):
        for c in getattr(x, "Group", []) or []:
            walk(c)
        if x.TypeId == "Part::Feature":
            sh = x.Shape.copy()
            sh.Placement = x.getGlobalPlacement()
            bb.add(sh.BoundBox)
    walk(root)
    return (bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax)


# ============================================================== steps
def s_table():
    for name in list(App.listDocuments()):
        if name == DOC:
            App.closeDocument(name)
    d = App.newDocument(DOC)
    if App.GuiUp:
        import FreeCADGui as Gui
        Gui.ActiveDocument = Gui.getDocument(DOC)
    table = container("STF_Table")
    fx, fy, ft = FL.PLATE
    # the table top sits 10 mm BELOW the module plates' underside (z = -10):
    # coplanar faces flicker
    top = feature("Table_Top", detail.rounded_box(fx, fy, ft, (0, 0, -10 - ft)), table, TABLE_WHITE)
    props(top, Note=f"table {fx:.0f} x {fy:.0f} (factory_layout.PLATE)")
    _state["siblings"] = {p.name: p for p in HM.build()}
    d.recompute()
    return {"doc": DOC, "table": [fx, fy, ft]}


def s_hbw():
    made, log = {"solids": 0, "components": 0}, []
    fits, _ = _fits("hbw")
    _state["siblings"] = {p.name: p for p in HM.build()}
    hbw = _module("hbw", (FL.TX, FL.TY, 0), FL.ROTATE_DEG)
    base_plate(next(p for p in HM.build() if p.group == "frame"), hbw, "HBW_base_plate")
    hf = hbw_by_frame()
    j1 = container("J1_Travel_X", hbw, (HM.P["CV_X"], 0, 0))
    j2 = container("J2_Lift_Z", j1, (0, 0, 120.0))
    j3 = container("J3_Ausleger_Y", j2, (0, 0, 0))
    for fr, c in (("world", hbw), ("travel", j1), ("lift", j2), ("fork", j3)):
        for p in hf[fr]:
            _solid(p, c, fits, "hbw", log, made)
    doc().recompute()
    return _summary("hbw", made, log, HM.build(), seat(hbw))


def s_vgr():
    made, log = {"solids": 0, "components": 0}, []
    fits, _ = _fits("vgr")
    vx, vy = FL.VGR_AT
    vgr = _module("vgr", (vx, vy, 0))
    base_plate(next(p for p in VG.build() if p.group == "frame"), vgr, "VGR_base_plate")
    sw = container("J_Swivel", vgr, (VG.V["CX"], VG.V["CY"], 0))
    piv = container("_pivot", sw, (-VG.V["CX"], -VG.V["CY"], 0))
    pl = container("J_Plunge", piv)
    rc = container("J_Reach", pl)
    for p in VG.build():
        _solid(p, {"world": vgr, "swivel": piv, "plunge": pl, "reach": rc}.get(p.frame, vgr),
               fits, "vgr", log, made)
    # the cookie on the cup (vgr_model.held_cookie), shown while the plan carries
    hc = VG.held_cookie(0.0, 250.0, 0.0)
    ck = Part.makeCompound([detail.precise(q) for q in hc])
    o = feature("VGR_held_cookie", ck, rc, "#efe0b0")
    props(o, Note="held cookie - visible only while vgr_path.plan() carries")
    if App.GuiUp:
        o.ViewObject.Visibility = False
    doc().recompute()
    return _summary("vgr", made, log, VG.build(), seat(vgr))


def s_oven():
    made, log = {"solids": 0, "components": 0}, []
    fits, _ = _fits("oven")
    oven = _module("oven", (FL.OVEN_TX, FL.OVEN_TY, 0), FL.OVEN_ROT)
    base_plate(next(p for p in OM.build() if p.group == "frame"), oven, "OVEN_base_plate")
    jsl = container("J_Ofenschieber", oven)
    jdr = container("J_Ofentuer", oven)
    tcx, tcy = OM.O["TT"]
    jtu = container("J_Drehkranz", oven, (tcx, tcy, 0))
    jtp = container("_tt_pivot", jtu, (-tcx, -tcy, 0))
    jsa = container("J_Sauger", oven)
    jlo = container("J_Senken", jsa)
    jpu = container("J_Auswerfer", oven)
    cmap = {"world": oven, "slider": jsl, "door": jdr, "turn": jtp, "sauger": jsa, "lower": jlo, "push": jpu}
    for p in OM.build():
        _solid(p, cmap[p.frame], fits, "oven", log, made)
    doc().recompute()
    return _summary("oven", made, log, OM.build(), seat(oven))


def s_sorting():
    made, log = {"solids": 0, "components": 0}, []
    fits, _ = _fits("sorting")
    sort = _module("sorting", (FL.SORT_TX, FL.SORT_TY, 0), FL.SORT_ROT)
    base_plate(next(p for p in SM.build() if p.group == "frame"), sort, "SORT_base_plate")
    cmap = {"world": sort}
    for i, col in enumerate(SM.COLOURS):
        cmap[f"push{i}"] = container(f"J_Auswurf_{col}", sort)
    for p in SM.build():
        _solid(p, cmap[p.frame], fits, "sorting", log, made)
    doc().recompute()
    return _summary("sorting", made, log, SM.build(), seat(sort))


def s_plc():
    made, log = {"solids": 0, "components": 0}, []
    plc = _module("plc", (FL.PLC_AT[0], FL.PLC_AT[1], 0))
    base_plate(next(p for p in PM.build() if p.group == "frame"), plc, "PLC_base_plate")
    for p in PM.build():
        _solid(p, plc, {}, "plc", log, made)
    doc().recompute()
    return _summary("plc", made, log, PM.build())


# -------------------------------------------------------------- wiring
def _fillet_wire(pts, r):
    """Polyline -> Part.Wire with a radius-r arc at each corner (r shrinks
    where the legs are short)."""
    q = [V(*pts[0])]
    for p in pts[1:]:
        v = V(*p)
        if (v - q[-1]).Length > 1e-6:
            q.append(v)
    # drop collinear interior points
    k = [q[0]]
    for i in range(1, len(q) - 1):
        a, b = (q[i] - k[-1]), (q[i + 1] - q[i])
        if a.cross(b).Length > 1e-6 * a.Length * b.Length:
            k.append(q[i])
    k.append(q[-1])
    if len(k) < 2:
        return None
    edges, start = [], k[0]
    for i in range(1, len(k) - 1):
        a, b, c = k[i - 1], k[i], k[i + 1]
        din, dout = (b - a), (c - b)
        lin, lout = din.Length, dout.Length
        din.normalize(); dout.normalize()
        phi = math.acos(max(-1.0, min(1.0, din.dot(dout))))       # turn angle
        t = r * math.tan(phi / 2)
        tmax = 0.45 * min(lin if i == 1 else lin / 2, lout if i == len(k) - 2 else lout / 2)
        if t > tmax:
            t = tmax
        rr = t / math.tan(phi / 2) if phi > 1e-6 else 0
        p1, p2 = b - din * t, b + dout * t
        if (p1 - start).Length > 1e-6:
            edges.append(Part.LineSegment(start, p1).toShape())
        if rr > 0.05:
            bis = (dout - din)
            bis.normalize()
            centre = b + bis * (rr / math.cos(phi / 2))
            mid = centre + (b - centre).normalize() * rr
            edges.append(Part.Arc(p1, mid, p2).toShape())
        else:
            edges.append(Part.LineSegment(p1, p2).toShape())
        start = p2
    if (k[-1] - start).Length > 1e-6:
        edges.append(Part.LineSegment(start, k[-1]).toShape())
    return Part.Wire(edges)


def _tube(wire, d, d_in=0.0):
    e0 = wire.OrderedEdges[0]
    p0 = e0.valueAt(e0.FirstParameter)
    t0 = e0.tangentAt(e0.FirstParameter)
    circ = Part.Wire(Part.Circle(p0, t0, d / 2).toShape())
    try:
        s = wire.makePipeShell([circ], True, True)
        if d_in > 0:
            ci = Part.Wire(Part.Circle(p0, t0, d_in / 2).toShape())
            s = s.cut(wire.makePipeShell([ci], True, True))
        if s.isValid() and s.Volume > 0:
            return s
    except Exception:
        pass
    # fallback: cylinders along the discretised path + spheres at the joints
    pts = wire.discretize(Distance=2.0)
    segs = [Part.makeCylinder(d / 2, (b - a).Length, a, b - a) for a, b in zip(pts, pts[1:])
            if (b - a).Length > 1e-6]
    segs += [Part.makeSphere(d / 2, p) for p in pts[1:-1]]
    return Part.makeCompound(segs)


def _offset(points, k, n, pitch):
    """Conductor k of n: the whole route shifted along the XY diagonal, so the
    conductors lie side by side on both X and Y runs."""
    s = (k - (n - 1) / 2) * pitch
    return [(x + s * 0.7071, y + s * 0.7071, z) for x, y, z in points]


def _striped(wire, d, colours, pitch=8.0):
    """Protective earth: alternating green / yellow sleeves along the conductor."""
    pts = wire.discretize(Distance=pitch)
    groups = [[], []]
    for i, (a, b) in enumerate(zip(pts, pts[1:])):
        if (b - a).Length > 1e-6:
            groups[i % 2].append(Part.makeCylinder(d / 2, (b - a).Length, a, b - a))
            groups[i % 2].append(Part.makeSphere(d / 2, b))
    return [(Part.makeCompound(g), colours[i]) for i, g in enumerate(groups) if g]


def s_wiring():
    d = doc()
    old = d.getObject("Wiring")
    if old is not None:
        _remove_tree(old)
    w = _json()["wiring"]
    roles = {k: v["colour"] for k, v in w["roles"].items()}
    root = container("Wiring", d.getObject("STF_Table"))
    counts = {}
    runs = []
    for grp, key, dia in (("Cables", "cables", WIRE_D), ("Bundles", "bundles", BUNDLE_WIRE_D),
                          ("Power", "power", WIRE_D)):
        g = container(grp, root)
        for i, run in enumerate(w[key]):
            label = run.get("part") or run.get("name") or f"{run['module']}_bundle"
            if key == "bundles":
                label = f"{run['module']}_PCB_to_PLC"
            label = f"{grp[:-1]}_{i:02d}_{label}"
            c = container(label, g)
            props(c, Module=run.get("module", "plc"), IO=run.get("tag", ""),
                  Conductors=",".join(run["conductors"]))
            n = len(run["conductors"])
            by_role = {}
            for k, role in enumerate(run["conductors"]):
                wire = _fillet_wire(_offset(run["points"], k, n, dia * 1.15), BEND_R)
                if wire is None:
                    continue
                if roles[role] == "PE":
                    for sh, col in _striped(wire, dia, ("#2e9e44", "#f2d21b")):
                        feature(f"{label}_PE", sh, c, col, label=f"{label}.PE")
                else:
                    by_role.setdefault(role, []).append(_tube(wire, dia))
                counts[role] = counts.get(role, 0) + 1
            for role, shapes in by_role.items():
                o = feature(f"{label}_{role}", Part.makeCompound(shapes), c, roles[role],
                            label=f"{label}.{role}")
                props(o, Role=role, Conductors=len(shapes))
            runs.append(label)
    g = container("Hoses", root)
    for i, h in enumerate(w["hoses"]):
        wire = _fillet_wire(h["points"], BEND_R)
        if wire is None:
            continue
        o = feature(f"Hose_{i:02d}_{h['from']}_to_{h['to']}", _tube(wire, HOSE_D, HOSE_ID), g,
                    roles["AIR"], transparency=45)
        props(o, Role="AIR", Module=h["module"], From=h["from"], To=h["to"])
        counts["AIR"] = counts.get("AIR", 0) + 1
    d.recompute()
    return {"conductors_by_role": counts, "runs": len(runs), "hoses": len(w["hoses"]),
            "note": "conductor/hose diameters are assumed (WIRE_D, HOSE_D) - measure"}


# -------------------------------------------------------------- checks
def s_interference(module="all", tol=0.05):
    """Brute force, whitelist OFF: every placed component and wire against every
    other solid, in factory coordinates. Reports, does not fix."""
    d = doc()
    solids = []
    for o in d.Objects:
        if o.TypeId != "Part::Feature" or o.Name == "Table_Top" or o.Name.endswith("base_plate"):
            continue
        sh = o.Shape.copy()
        sh.Placement = o.getGlobalPlacement()
        chain = [x.Label for x in o.InListRecursive if x.TypeId == "App::Part"]
        solids.append((o, sh, sh.BoundBox, chain))
    comp = [s for s in solids if "STF_Component" in s[0].PropertiesList]
    wires = [s for s in solids if any(ch in ("Wiring",) for ch in s[3])]
    rest = [s for s in solids if s not in comp and s not in wires]
    hits = []

    def inter(a, b):
        if not a[2].intersect(b[2]):
            return 0.0
        try:
            return a[1].common(b[1]).Volume
        except Exception:
            return -1.0
    parent = lambda s: s[0].InList[0].Label if s[0].InList else ""

    def env_box(s):
        """the proven envelope of the model part this component replaced (global)"""
        c = s[0].InList[0]
        e = eval(c.STF_Envelope)
        pl = c.getGlobalPlacement().multiply(c.Placement.inverse())
        return Part.makeBox(e[3] - e[0], e[4] - e[1], e[5] - e[2], V(e[0], e[1], e[2])).transformGeometry(pl.toMatrix())
    inherited, engaged = [], []
    for a in comp:
        for b in rest + comp:
            if b is a or parent(a) == parent(b):
                continue
            v = inter(a, b)
            if v > tol or v < 0:
                eb = env_box(a)
                other = env_box(b) if b in comp else b[1]
                try:
                    was = eb.common(other).Volume > tol
                except Exception:
                    was = False
                sub = getattr(a[0], "STF_Sub", "")
                if was:
                    inherited.append((a[0].Label, b[0].Label, round(v, 2)))
                elif sub in ENGAGE:
                    engaged.append((a[0].Label, b[0].Label, round(v, 2)))
                else:
                    hits.append((a[0].Label, b[0].Label, round(v, 2)))
    route, ends = [], []
    for a in wires:
        run = a[0].InList[0] if a[0].InList else None
        rl = run.Label if run is not None else ""
        for b in rest + comp:
            v = inter(a, b)
            if not (v > tol or v < 0):
                continue
            bl = b[0].Label
            own = rl.split("_", 2)[-1] if rl.startswith("Cable_") else None
            endpoint = ((own and bl.split(".")[0] == own) or "pcb" in bl.lower()
                        or bl.startswith(("cable_duct", "terminal_", "revpi", "psu", "din_rail")))
            (ends if endpoint else route).append((rl or a[0].Label, bl, round(v, 2)))
    comp_hits = sorted(set((min(x, y), max(x, y), v) for x, y, v in hits))
    route = sorted(set(route))
    inh = sorted(set((min(x, y), max(x, y), v) for x, y, v in inherited))
    return {"component_hits_new": len(comp_hits), "component_hit_list": comp_hits[:60],
            "component_hits_inherited_from_model": len(inh), "inherited_list": inh[:60],
            "output_engagements": sorted(set(engaged)),
            "wire_route_hits": len(route), "wire_route_list": route[:80],
            "wire_endpoint_contacts": len(ends)}


# -------------------------------------------------------------- view + save
def shot(name, only=None, view="iso", w=1600, h=1000):
    """Screenshot from the GUI. only: module keys to show (others hidden)."""
    if not App.GuiUp:
        return None
    import FreeCADGui as Gui
    d = doc()
    gd = Gui.getDocument(DOC)
    Gui.ActiveDocument = gd
    vis = {}
    if only:
        keep = {safe(MODULE_KEYS[k]) for k in only if k in MODULE_KEYS} | ({"Wiring"} if "wiring" in only else set())
        for o in d.getObject("STF_Table").Group:
            vis[o.Name] = o.ViewObject.Visibility
            o.ViewObject.Visibility = o.Name in keep
    v = gd.ActiveView
    {"iso": v.viewIsometric, "top": v.viewTop, "front": v.viewFront, "right": v.viewRight,
     "rear": v.viewRear, "left": v.viewLeft}[view]()
    v.fitAll()
    os.makedirs(SHOTS, exist_ok=True)
    path = os.path.join(SHOTS, f"{name}.png")
    Gui.updateGui()
    v.saveImage(path, w, h, "White")
    for n, val in vis.items():
        d.getObject(n).ViewObject.Visibility = val
    return path


def s_closeup(label, name, margin=60.0, view="iso", w=1400, h=1000):
    """Close-up of one object: hide every solid outside its (enlarged) global
    box, fitAll, save, restore. (ViewSelection clips at the near plane.)"""
    import FreeCADGui as Gui
    d = doc()
    tgt = [x for x in d.Objects if x.Label == label][0]
    region = App.BoundBox(*_global_bbox(tgt)) if tgt.TypeId == "App::Part" else None
    if region is None:
        sh = tgt.Shape.copy(); sh.Placement = tgt.getGlobalPlacement(); region = sh.BoundBox
    region.enlarge(margin)
    hidden = []
    for o in d.Objects:
        if o.TypeId != "Part::Feature" or not o.ViewObject.Visibility:
            continue
        sh = o.Shape.copy(); sh.Placement = o.getGlobalPlacement()
        bb = sh.BoundBox
        inside = (bb.XMin >= region.XMin - 1 and bb.XMax <= region.XMax + 1 and
                  bb.YMin >= region.YMin - 1 and bb.YMax <= region.YMax + 1 and
                  bb.ZMin >= region.ZMin - 1 and bb.ZMax <= region.ZMax + 1)
        if not inside and not bb.intersect(region):
            o.ViewObject.Visibility = False
            hidden.append(o)
        elif not inside:
            # long members (columns, plates) crossing the region: keep, but they
            # would blow the fit up - clip them out of the fit by hiding plates only
            if (o.Name == "Table_Top" or o.Name.endswith("base_plate")
                    or o.Label.startswith(("Cable_", "Bundle_", "Power_", "Hose_"))):
                o.ViewObject.Visibility = False
                hidden.append(o)
    v = Gui.getDocument(DOC).ActiveView
    {"iso": v.viewIsometric, "front": v.viewFront, "top": v.viewTop, "right": v.viewRight}[view]()
    v.fitAll()
    Gui.updateGui()
    path = os.path.join(SHOTS, f"{name}.png")
    v.saveImage(path, w, h, "White")
    for o in hidden:
        o.ViewObject.Visibility = True
    return {"path": path, "hidden": len(hidden)}


def s_shot(name="view", only=None, view="iso"):
    return {"path": shot(name, only, view)}


def s_save():
    d = doc()
    os.makedirs(OUT_DIR, exist_ok=True)
    if os.path.abspath(FCSTD) == os.path.abspath(os.path.join(OUT_DIR, "STF_Factory.FCStd")):
        raise RuntimeError("refusing to overwrite the headless build")
    d.saveAs(FCSTD)
    import Import
    Import.export([d.getObject("STF_Table")], STEP)
    n = sum(1 for o in d.Objects if o.TypeId == "Part::Feature")
    j = sum(1 for o in d.Objects if o.TypeId == "App::Part")
    return {"fcstd": FCSTD, "fcstd_mb": round(os.path.getsize(FCSTD) / 1e6, 1), "step": STEP,
            "step_mb": round(os.path.getsize(STEP) / 1e6, 1), "features": n, "containers": j}


# ------------------------------------------------------------------- motion
def s_pose(t=0.0):
    import motion
    tl = _state.setdefault("timeline", motion.timeline())
    poses = {m: motion.pose_at(k, t) for m, k in tl.items()}
    motion.apply(doc(), poses)
    doc().recompute()
    return {"t": t, "poses": {m: {j: round(v, 2) for j, v in p.items()} for m, p in poses.items()}}


def s_play(fps=20, speed=1.0, seconds=0):
    """Animate in the GUI on a QTimer (non-blocking). seconds=0 plays forever."""
    if not App.GuiUp:
        return {"ok": False, "error": "needs the GUI"}
    from PySide import QtCore
    import motion
    tl = _state.setdefault("timeline", motion.timeline())
    old = _state.get("timer")
    if old is not None:
        old.stop()
    clock = {"t": 0.0}
    timer = QtCore.QTimer()

    def tick():
        clock["t"] += speed / fps
        if seconds and clock["t"] > seconds:
            timer.stop()
            return
        motion.apply(doc(), {m: motion.pose_at(k, clock["t"]) for m, k in tl.items()})

    timer.timeout.connect(tick)
    timer.start(int(1000 / fps))
    _state["timer"] = timer
    return {"playing": True, "fps": fps, "speed": speed,
            "cycles_s": {m: k[-1][0] for m, k in tl.items()}}


def s_stop():
    t = _state.pop("timer", None)
    if t is not None:
        t.stop()
    return {"stopped": t is not None}


def s_film(name="factory", seconds=45.0, fps=10, w=960, h=600, only=None, view="iso", zoom_out=1):
    """Render frames through the GUI and assemble a GIF + MP4 (ffmpeg)."""
    if not App.GuiUp:
        return {"ok": False, "error": "needs the GUI"}
    import FreeCADGui as Gui, motion, subprocess, shutil
    s_stop()
    tl = _state.setdefault("timeline", motion.timeline())
    d = doc()
    gd = Gui.getDocument(DOC)
    v = gd.ActiveView
    vis = {}
    if only:
        keep = {safe(MODULE_KEYS[k]) for k in only if k in MODULE_KEYS}
        for o in d.getObject("STF_Table").Group:
            vis[o.Name] = o.ViewObject.Visibility
            o.ViewObject.Visibility = o.Name in keep
    try:
        v.setAnimationEnabled(False)       # view changes animate: frames would catch it turning
    except Exception:
        pass
    # fit at the pose where the machines are tallest / widest (VGR at transit,
    # arm out), then leave a margin, so nothing leaves the frame mid-cycle
    motion.apply(d, {m: dict(motion.pose_at(k, 0.0)) for m, k in tl.items()})
    {"iso": v.viewIsometric, "top": v.viewTop}[view]()
    v.fitAll()
    for _ in range(zoom_out):
        v.zoomOut()
    for _ in range(3):
        Gui.updateGui()
    fdir = os.path.join(SHOTS, f"film_{name}")
    shutil.rmtree(fdir, ignore_errors=True)
    os.makedirs(fdir)
    n = int(seconds * fps)
    for i in range(n):
        motion.apply(d, {m: motion.pose_at(k, i / fps) for m, k in tl.items()})
        Gui.updateGui()
        v.saveImage(os.path.join(fdir, f"f{i:04d}.png"), w, h, "White")
    for k, val in vis.items():
        d.getObject(k).ViewObject.Visibility = val
    mp4 = os.path.join(SHOTS, f"{name}.mp4")
    gif = os.path.join(SHOTS, f"{name}.gif")
    ff = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    subprocess.run([ff, "-y", "-loglevel", "error", "-framerate", str(fps), "-i",
                    os.path.join(fdir, "f%04d.png"), "-pix_fmt", "yuv420p", "-vf",
                    "pad=ceil(iw/2)*2:ceil(ih/2)*2", mp4], check=False)
    subprocess.run([ff, "-y", "-loglevel", "error", "-framerate", str(fps), "-i",
                    os.path.join(fdir, "f%04d.png"), "-vf",
                    "scale=720:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse", gif],
                   check=False)
    return {"frames": n, "mp4": mp4 if os.path.exists(mp4) else None,
            "gif": gif if os.path.exists(gif) else None}


STEPS = {"proofs": s_proofs, "table": s_table, "hbw": s_hbw, "vgr": s_vgr, "oven": s_oven,
         "sorting": s_sorting, "plc": s_plc, "wiring": s_wiring, "interference": s_interference,
         "shot": s_shot, "save": s_save, "pose": s_pose, "play": s_play, "stop": s_stop,
         "film": s_film}


if sys.argv[-1].endswith("mcp_build.py"):          # freecadcmd: headless dry run of every step
    FCSTD = os.path.join(os.environ.get("STF_MCP_OUT", "/tmp"), "STF_Factory_MCP_headless.FCStd")
    STEP = FCSTD.replace(".FCStd", ".step")
    for s in os.environ.get("STF_MCP_STEPS", "proofs,table,hbw,vgr,oven,sorting,plc,wiring,interference,save").split(","):
        r = step(s)
        print(s, "OK" if r.get("ok") else "FAILED", r.get("seconds"), "s",
              "" if r.get("ok") else r.get("error"))
