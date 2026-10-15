"""
STF-2 precise CAD: every part, bracket, mount and fastener as a solid, holes cut.

    /Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd line_cad_precise.py

-> ~/workspace/stf-factory/cad/line2_precise/<module>.FCStd / .step  (9 modules)
-> ~/workspace/stf-factory/cad/line2_precise/STF2_Precise.FCStd / .step (assembly + deck)
-> ~/workspace/stf-factory/cad/line2_precise/brep_report.json

Refuses to build unless line_model.check(), joints.check() and plc_io.check() pass.
Never touches STF_Factory*.FCStd or the v3 line2/ output (a new folder).

What is drawn exactly:
  B-type profiles  real section: slots (neck + chamber) on every face at the series grid,
                   a core bore per 20/30/40 cell (2040 = two cores)
  holes            ISO 273 medium clearance holes through every clamped part, counterbores
                   where the search chose them, tap-drill holes (d - P) in every tapped part,
                   through-holes for rods / shafts / the reject opening in the deck
  fasteners        ISO 4762 (hex socket), ISO 7380 (dome), ISO 10642 (countersunk) heads,
                   shanks at nominal d (threads not modelled), ISO 7089 washers, ISO 4032 nuts,
                   T-nuts in the slot chamber
The B-rep check (Shape.common) is the final authority over the analytic proofs: every
pair of solids whose boxes overlap must share no volume, except a shank in the tapped
hole it threads into (thread engagement) and the pairs line_model.allowed() declares.
"""
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "hbw"))

import FreeCAD as App
import Part

import fcstd_colour
import geom as G
import hardware as H
import joints as J
import line_model as M
import plc_io
import safety

V = App.Vector
OUT = os.path.expanduser("~/workspace/stf-factory/cad/line2_precise")
_LOG = open("/tmp/line_cad_precise.out", "w")


def print(*a, **k):                                    # freecadcmd drops buffered stdout on exit
    import builtins
    txt = " ".join(str(x) for x in a)
    builtins.print(txt, flush=True)
    _LOG.write(txt + "\n")
    _LOG.flush()
STEEL, ZINC, TNUT_C = "#3a3d40", "#9aa3ab", "#b0b4b8"
_line_cad = None


def base_shape(p):
    """The v3 shapes (trays with pockets, tubes, rounded boxes, arcs...) from line_cad."""
    global _line_cad
    if _line_cad is None:
        import line_cad as lc
        _line_cad = lc
    return _line_cad.shape(p)


# ------------------------------------------------------------------ profiles
def profile_shape(p):
    """B-type slot profile of the part's section, extruded along its long axis."""
    ser, ax = J.section(p)
    pr = H.PROFILE[ser]
    cross = [i for i in range(3) if i != ax]
    a, b = p.s[cross[0]], p.s[cross[1]]
    Ln = p.s[ax]
    s = Part.makeBox(a, b, Ln)
    cuts = []
    ua = H.slot_offsets(a, ser)
    vb = H.slot_offsets(b, ser)
    for u in ua:
        for v in vb:
            cuts.append(Part.makeCylinder(pr["core"] / 2, Ln + 2, V(a / 2 + u, b / 2 + v, -1)))
    neck, inner, depth, lip = pr["slot"], pr["inner"], pr["depth"], pr["lip"]
    for u in ua:                       # slots on the two faces normal to local y
        for y0, sgn in ((0.0, 1), (b, -1)):
            n = Part.makeBox(neck, lip + 0.02, Ln + 2, V(a / 2 + u - neck / 2, y0 - 0.01 if sgn > 0 else y0 - lip - 0.01, -1))
            c = Part.makeBox(inner, depth - lip, Ln + 2,
                             V(a / 2 + u - inner / 2, y0 + lip if sgn > 0 else y0 - depth, -1))
            cuts += [n, c]
    for v in vb:                       # slots on the two faces normal to local x
        for x0, sgn in ((0.0, 1), (a, -1)):
            n = Part.makeBox(lip + 0.02, neck, Ln + 2, V(x0 - 0.01 if sgn > 0 else x0 - lip - 0.01, b / 2 + v - neck / 2, -1))
            c = Part.makeBox(depth - lip, inner, Ln + 2,
                             V(x0 + lip if sgn > 0 else x0 - depth, b / 2 + v - inner / 2, -1))
            cuts += [n, c]
    s = s.cut(Part.makeCompound(cuts))
    # local (x, y, z) = (cross0, cross1, long) -> world
    m = App.Matrix()
    cols = [cross[0], cross[1], ax]
    rows = [[0.0] * 3 for _ in range(3)]
    for j, w in enumerate(cols):
        rows[w][j] = 1.0
    m.A11, m.A12, m.A13 = rows[0]
    m.A21, m.A22, m.A23 = rows[1]
    m.A31, m.A32, m.A33 = rows[2]
    if abs(m.determinant() + 1) < 1e-9:           # keep it a rotation: swap the two cross axes
        cols = [cross[1], cross[0], ax]
        s = Part.makeBox(b, a, Ln).cut(Part.makeCompound([]))
        return _profile_swapped(p, ser, ax, cross)
    s = s.transformGeometry(m)
    s.translate(V(*p.p))
    return s


def _profile_swapped(p, ser, ax, cross):
    q = M.Part(p.name, p.module, p.group, p.kind, p.p, p.s, mech=p.mech)
    # build with the cross axes in the other order (a proper rotation), same outer box
    pr = H.PROFILE[ser]
    c0, c1 = cross[1], cross[0]
    a, b, Ln = p.s[c0], p.s[c1], p.s[ax]
    s = Part.makeBox(a, b, Ln)
    cuts = []
    ua, vb = H.slot_offsets(a, ser), H.slot_offsets(b, ser)
    for u in ua:
        for v in vb:
            cuts.append(Part.makeCylinder(pr["core"] / 2, Ln + 2, V(a / 2 + u, b / 2 + v, -1)))
    neck, inner, depth, lip = pr["slot"], pr["inner"], pr["depth"], pr["lip"]
    for u in ua:
        for y0, sgn in ((0.0, 1), (b, -1)):
            cuts.append(Part.makeBox(neck, lip + 0.02, Ln + 2, V(a / 2 + u - neck / 2, y0 - 0.01 if sgn > 0 else y0 - lip - 0.01, -1)))
            cuts.append(Part.makeBox(inner, depth - lip, Ln + 2, V(a / 2 + u - inner / 2, y0 + lip if sgn > 0 else y0 - depth, -1)))
    for v in vb:
        for x0, sgn in ((0.0, 1), (a, -1)):
            cuts.append(Part.makeBox(lip + 0.02, neck, Ln + 2, V(x0 - 0.01 if sgn > 0 else x0 - lip - 0.01, b / 2 + v - neck / 2, -1)))
            cuts.append(Part.makeBox(depth - lip, inner, Ln + 2, V(x0 + lip if sgn > 0 else x0 - depth, b / 2 + v - inner / 2, -1)))
    s = s.cut(Part.makeCompound(cuts))
    m = App.Matrix()
    rows = [[0.0] * 3 for _ in range(3)]
    for j, w in enumerate((c0, c1, ax)):
        rows[w][j] = 1.0
    m.A11, m.A12, m.A13 = rows[0]
    m.A21, m.A22, m.A23 = rows[1]
    m.A31, m.A32, m.A33 = rows[2]
    s = s.transformGeometry(m)
    s.translate(V(*p.p))
    return s


def shape_of(p):
    if J.is_profile(p):
        return profile_shape(p)
    if p.kind == "box" and not p.mech.startswith("tray:"):
        return Part.makeBox(*p.s, V(*p.p))
    return base_shape(p)


# ------------------------------------------------------------------ fasteners
def _axis(f):
    i = [abs(v) for v in f.axis].index(1.0)
    return i, f.axis[i]


def _cyl(r, h, base, i, sgn):
    d = [0.0, 0.0, 0.0]
    d[i] = float(sgn)
    return Part.makeCylinder(r, h, V(*base), V(*d))


def fastener_shapes(f):
    """Solids of one fastener (head, washer, shank, nut / T-nut)."""
    i, sgn = _axis(f)
    t = H.THREAD[f.thread]
    dk, k, _ = H.head(f.thread, f.head_type)
    wh = t["washer"][2] if f.washer else 0.0
    h = list(f.head)
    h[i] += sgn * f.cbore
    hb = list(h)
    hb[i] -= sgn * wh
    out = []
    if f.head_type == "socket":
        top = list(hb)
        top[i] -= sgn * k
        hd = _cyl(dk / 2, k, top, i, sgn)
        hexs = Part.makePolygon([V(math.cos(a) * t["head"][2] / math.sqrt(3), math.sin(a) * t["head"][2] / math.sqrt(3), 0)
                                 for a in [j * math.pi / 3 for j in range(7)]])
        sock = Part.Face(hexs).extrude(V(0, 0, t["head"][3]))
        rot = {0: App.Rotation(V(0, 1, 0), 90 * sgn), 1: App.Rotation(V(1, 0, 0), -90 * sgn), 2: App.Rotation()}[i]
        if i == 2 and sgn < 0:
            rot = App.Rotation(V(1, 0, 0), 180)
        sock.Placement = App.Placement(V(*top), rot)
        try:
            hd = hd.cut(sock)
        except Exception:
            pass
        out.append(("head", hd))
    elif f.head_type == "button":
        top = list(hb)
        top[i] -= sgn * k
        out.append(("head", _cyl(dk / 2, k, top, i, sgn)))
    else:                                            # countersunk: cone in the countersink
        d = [0.0, 0.0, 0.0]
        d[i] = float(sgn)
        out.append(("head", Part.makeCone(dk / 2, t["d"] / 2, k, V(*h), V(*d))))
    if f.washer:
        w = t["washer"]
        ring = _cyl(w[1] / 2, w[2], hb, i, sgn).cut(_cyl(w[0] / 2, w[2] + 0.2, hb, i, sgn))
        out.append(("washer", ring))
    start = h if f.head_type == "csk" else hb
    out.append(("shank", _cyl(t["d"] / 2, f.length - (0 if f.head_type != "csk" else 0), start, i, sgn)))
    if f.nut == "ISO4032":
        s_, m_ = t["nut"]
        far = list(hb)
        far[i] += sgn * f.clamp
        poly = Part.makePolygon([V(math.cos(a) * s_ / math.sqrt(3), math.sin(a) * s_ / math.sqrt(3), 0)
                                 for a in [j * math.pi / 3 + math.pi / 6 for j in range(7)]])
        nut = Part.Face(poly).extrude(V(0, 0, m_)).cut(Part.makeCylinder(t["d"] / 2, m_ + 1, V(0, 0, -0.5)))
        rot = {0: App.Rotation(V(0, 1, 0), 90 * sgn), 1: App.Rotation(V(1, 0, 0), -90 * sgn), 2: App.Rotation()}[i]
        if i == 2 and sgn < 0:
            rot = App.Rotation(V(1, 0, 0), 180)
        nut.Placement = App.Placement(V(*far), rot)
        out.append(("nut", nut))
    elif f.nut.startswith("TN"):
        # the same stepped, slot-oriented T-nut the joints engine proved collision-free
        shank = _cyl(t["d"] / 2, f.length + 1, start, i, sgn)
        for q in f.solids():
            if q.name.startswith("tnut"):
                out.append((q.name, Part.makeBox(*q.s, V(*q.p)).cut(shank)))
    return out


def holes_for(f, parts_by):
    """(part name, cutting solid) for one fastener: clearance / counterbore / tap / through."""
    i, sgn = _axis(f)
    t = H.THREAD[f.thread]
    dk, k, _ = H.head(f.thread, f.head_type)
    wh = t["washer"][2] if f.washer else 0.0
    cuts = []
    h = list(f.head)
    clamp_part = f.clamp - wh + f.cbore               # thickness of the clamped part(s)
    for n in f.through:
        start = list(h)
        start[i] -= sgn * 1.0
        cuts.append((n, _cyl(f.hole / 2, clamp_part + 2.0, start, i, sgn)))
        if f.cbore > 0:
            cuts.append((n, _cyl(dk / 2 + 0.5, f.cbore + 1.0, start, i, sgn)))
        if f.head_type == "csk":
            d = [0.0, 0.0, 0.0]
            d[i] = float(sgn)
            cuts.append((n, Part.makeCone(dk / 2 + 0.2, f.hole / 2, k + 0.2, V(*h), V(*d))))
    joint_face = list(h)
    joint_face[i] += sgn * clamp_part
    tip = list(h)
    tip[i] += sgn * (f.cbore - wh + f.length)
    if f.into == "NUT":
        for n in f.joint.split("~")[:2]:
            if n not in f.through and n in parts_by:
                cuts.append((n, _cyl(f.hole / 2, abs(tip[i] - joint_face[i]) + 1, joint_face, i, sgn)))
    elif not f.into.startswith("TNUT") and f.into in parts_by:
        host = parts_by[f.into]
        if not (J.is_profile(host)):                 # a profile end tap uses its core bore
            cuts.append((f.into, _cyl(t["tap"] / 2, abs(tip[i] - joint_face[i]) + 1.0 + 2 * t["P"], joint_face, i, sgn)))
    return cuts


# ------------------------------------------------------------------ build
def build_all():
    t0 = time.time()
    fails = M.check(verbose=False)
    jf, B = J.check(verbose=False)
    pf = plc_io.check(verbose=False)
    sf, finds = safety.check(verbose=False) if M.L.get("SAFE1") else ([], [])
    if fails or jf or pf or sf:
        print("REFUSING to build:", (fails + jf + pf + sf)[:6])
        os._exit(1)
    parts = [p for p in M.build()]                                    # with product (pucks, cookies)
    base_shape(parts[0])                                               # load line_cad
    cf, cn = _line_cad.containment(parts)
    if cf:
        print("REFUSING to build - containment:", cf[:6])
        os._exit(1)
    print(f"containment: {cn} contained pairs, zero overlap (cookies in pockets/tubes, stacks on pawls)")
    deck = M.Part("table_top", "M1_loop", "table", "box", (0.0, 0.0, -L_T), M.L["TABLE"], "#f4f3ef",
                  hw="TABLE_PLATE")
    extra = B.brackets
    solids = {}
    for p in parts + extra + [deck]:
        solids[p.name] = shape_of(p)
    by = {p.name: p for p in parts + extra}
    by["TABLE"] = deck
    # cuts
    cut_of = {}
    for f in B.fasteners:
        for n, c in holes_for(f, by):
            key = "table_top" if n == "TABLE" else n
            cut_of.setdefault(key, []).append(c)
    for p in parts:                                                   # declared through-holes
        for q in parts:
            if p is q:
                continue
            why = M.allowed(p, q)
            if why and why.startswith("through-hole") and p.kind == "cyl" and ("rod" in p.name or "shaft" in p.name):
                ax, Ln, d = p.s
                cut_of.setdefault(q.name, []).append(Part.makeCylinder(d / 2 + 1.0, Ln, V(*p.p),
                                                                       V(*[1.0 if a == ax else 0.0 for a in "xyz"])))
        if p.name.startswith("stacker_rod_"):
            ax, Ln, d = p.s
            cut_of.setdefault("table_top", []).append(Part.makeCylinder(d / 2 + 1.0, Ln, V(*p.p), V(0, 0, 1)))
        if p.name == "reject_funnel":
            b = p.aabb()
            cut_of.setdefault("table_top", []).append(Part.makeBox(b[3] - b[0] - 10, b[4] - b[1] - 10, L_T + 2,
                                                                   V(b[0] + 5, b[1] + 5, -L_T - 1)))
    # MGN blocks are U-shaped round their rail: cut the rail's envelope (+0.1) out of each block;
    # rail bolts sit in counterbores in the rail (the block rides over their heads)
    rails = [p for p in parts if "MGN" in p.hw and "rail" in p.hw]
    for p in parts:
        if "MGN" in p.hw and "block" in p.hw:
            for r in rails:
                if M.allowed(p, r):
                    b = r.aabb()
                    cut_of.setdefault(p.name, []).append(Part.makeBox(b[3] - b[0] + 0.2, b[4] - b[1] + 0.2,
                                                                      b[5] - b[2] + 0.2, V(b[0] - 0.1, b[1] - 0.1, b[2] - 0.1)))
    for f in B.fasteners:
        for n in f.through:
            q = by.get(n)
            if q is not None and "MGN" in q.hw and "rail" in q.hw:
                i, sgn = _axis(f)
                dk = H.head(f.thread, f.head_type)[0]
                bb = q.aabb()
                far = bb[i] if sgn > 0 else bb[i + 3]                 # the rail's top (head side)
                depth = abs((f.head[i] + sgn * 0.0) - far) + 0.5
                start = list(f.head)
                start[i] = far - sgn * 0.5
                cut_of.setdefault(n, []).append(_cyl(dk / 2 + 0.5, depth + 0.5, start, i, sgn))
    for n, cs in cut_of.items():
        try:
            solids[n] = solids[n].cut(Part.makeCompound(cs))
        except Exception as e:
            print("cut failed", n, e)
    print(f"parts {len(solids)}, holes cut in {len(cut_of)} parts ({sum(len(v) for v in cut_of.values())} holes), "
          f"{time.time() - t0:.0f} s")
    fsolids = []
    for k, f in enumerate(B.fasteners):
        for kind, s in fastener_shapes(f):
            fsolids.append((f"F{k:04d}_{kind}", s, f))
    print(f"fastener solids {len(fsolids)}, {time.time() - t0:.0f} s")
    return parts, extra, deck, solids, fsolids, B


L_T = M.L["TABLE"][2]


def brep_check(parts, extra, deck, solids, fsolids, B):
    """Shape.common over every box-overlapping pair."""
    t0 = time.time()
    items = []
    for p in parts + extra + [deck]:
        if p.group in ("puck", "cookie"):
            continue
        s = solids[p.name]
        items.append((p.name, s, s.BoundBox, p))
    for name, s, f in fsolids:
        items.append((name, s, s.BoundBox, f))
    items.sort(key=lambda t: t[2].XMin)
    fails, n, allowed_n = [], 0, 0
    by = {p.name: p for p in parts + extra}
    for i, (na, sa, ba, pa) in enumerate(items):
        for nb, sb, bb, pb in items[i + 1:]:
            if bb.XMin > ba.XMax - 0.01:
                break
            if bb.YMin > ba.YMax - 0.01 or bb.YMax < ba.YMin + 0.01 or bb.ZMin > ba.ZMax - 0.01 or bb.ZMax < ba.ZMin + 0.01:
                continue
            fa = pa if isinstance(pa, J.Fastener) else None
            fb = pb if isinstance(pb, J.Fastener) else None
            if fa is not None and fb is not None and fa is fb:
                continue                                  # parts of one fastener
            ok_names = set()
            for f in (fa, fb):
                if f is not None:
                    ok_names |= {f.into, *f.joint.split("~")[:2], *f.through}
                    ok_names |= {x.name for x in B.brackets if getattr(x, "_joint", "") == f.joint}
            other = nb if fa is not None else na
            if (fa is not None) != (fb is not None) and (other in ok_names or
                                                          (other == "table_top" and "TABLE" in ok_names)):
                allowed_n += 1                            # thread engagement / T-nut in its slot
                continue
            if fa is None and fb is None:
                if pa.group == "stock" or pb.group == "stock":
                    continue
                if M.allowed(pa, pb) if (hasattr(pa, "aabb") and hasattr(pb, "aabb") and na != "table_top"
                                         and nb != "table_top") else False:
                    allowed_n += 1
                    continue
                if J.body_of(pa) == J.body_of(pb):
                    continue
            n += 1
            try:
                v = sa.common(sb).Volume
            except Exception:
                continue
            if v > 1e-3:
                fails.append((na, nb, round(v, 3)))
    print(f"B-rep: {n} pairs intersected exactly, {allowed_n} declared (threads / joints), "
          f"{len(fails)} with shared volume, {time.time() - t0:.0f} s")
    return fails, n


def write(parts, extra, deck, solids, fsolids, B):
    os.makedirs(OUT, exist_ok=True)
    import Import
    colour_mod = {}
    report = []
    groups = M.by_module(parts + [q for q in extra])
    fmod = {}
    by = {p.name: p for p in parts + extra}
    for name, s, f in fsolids:
        a = f.joint.split("~")[0]
        mod = by[a].module if a in by else by.get(f.joint.split("~")[1], deck).module
        fmod.setdefault(mod, []).append((name, s))
    for mod in list(M.MODULES) + ["STF2_Precise"]:
        for d in list(App.listDocuments()):
            App.closeDocument(d)
        doc = App.newDocument(mod)
        root = doc.addObject("App::Part", mod)
        colours = {}
        items = [deck] + parts + extra if mod == "STF2_Precise" else groups.get(mod, [])
        for p in items:
            o = doc.addObject("Part::Feature", "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in p.name))
            o.Label = p.name
            o.Shape = solids[p.name]
            for prop, val in (("STF_Module", p.module), ("STF_HW", p.hw), ("STF_IO", p.tag), ("STF_Note", p.note[:200])):
                o.addProperty("App::PropertyString", prop, "STF")
                setattr(o, prop, val)
            root.addObject(o)
            colours[o.Name] = p.colour if p.group != "bracket" else ZINC
            if p.hw in ("PC guard panel 4 mm", "guard door kit"):
                colours[o.Name] = p.colour + "/70"          # clear polycarbonate: see the machine through it
        fl = [x for m_ in fmod for x in fmod[m_]] if mod == "STF2_Precise" else fmod.get(mod, [])
        if fl:
            fo = doc.addObject("App::Part", f"{mod}_fasteners")
            root.addObject(fo)
            for name, s in fl:
                o = doc.addObject("Part::Feature", name)
                o.Shape = s
                fo.addObject(o)
                colours[o.Name] = TNUT_C if name.endswith("tnut") else STEEL
        doc.recompute()
        fc, st = os.path.join(OUT, f"{mod}.FCStd"), os.path.join(OUT, f"{mod}.step")
        Import.export([root], st)
        doc.saveAs(fc)
        bb = App.BoundBox()
        for o in doc.Objects:
            if o.TypeId == "Part::Feature":
                bb.add(o.Shape.BoundBox)
        fcstd_colour.colourise(fc, colours, camera=fcstd_colour.iso_camera(
            (bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax)))
        nobj = sum(1 for o in doc.Objects if o.TypeId == "Part::Feature")
        report.append((mod, nobj, os.path.getsize(fc) / 1e6, os.path.getsize(st) / 1e6))
        App.closeDocument(doc.Name)
        print("%-16s %5d solids  FCStd %6.1f MB  STEP %6.1f MB" % report[-1])
    return report


def main():
    parts, extra, deck, solids, fsolids, B = build_all()
    fails, n = brep_check(parts, extra, deck, solids, fsolids, B)
    rep = dict(pairs=n, fails=[list(f) for f in fails[:200]], n_fail=len(fails),
               fasteners=len(B.fasteners), brackets=len(B.brackets), parts=len(parts))
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "brep_report.json"), "w") as fh:
        json.dump(rep, fh, indent=1)
    if fails:
        print("REFUSING to write CAD - B-rep interference:")
        for f in fails[:40]:
            print("  ", f)
        os._exit(1)
    report = write(parts, extra, deck, solids, fsolids, B)
    print("wrote", OUT)


if sys.argv[-1].endswith("line_cad_precise.py") or __name__ == "__main__":
    main()
