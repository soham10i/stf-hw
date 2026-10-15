"""
Guides: what slides through / turns in what - made real in the B-rep and proven.

The models allow a carriage and its columns to overlap as envelopes (their
checkers whitelist the pair). That hides the question that matters: is the
carriage GUIDED by the columns, or just drawn through them? Each model now owns
a GUIDES table, (host, guest, kind, clearance):

  slide   linear guide: the host gets a pocket = guest cross-section + clearance
  thread  spindle nut:  the host gets a bore = spindle major diameter + clearance
  bore    clearance hole only (the guest passes through, is not guided by it)

guided(p, module) cuts those pockets into the precise shape (detail only ever
REMOVES material, so every envelope proof still holds). check_guides(module)
proves, on the exact B-rep, for every pair:
  - zero overlap (common volume < 1e-3 mm3): nothing is drawn through anything;
  - slide/thread: the gap is within the clearance (the guest really bears on
    the host - it is guided, not floating in an oversize hole);
  - slide: the guest runs clean THROUGH the host along its travel axis, so the
    pocket is a through-pocket valid at every pose.
Runs inside FreeCAD.
"""
import FreeCAD as App
import Part

import detail

V = App.Vector
_cache = {}


def _model(module):
    if module in _cache:
        return _cache[module]
    if module == "hbw":
        import hbw_model as HM
        from hbw_frames import by_frame, HOME
        mod = {p.name: p for p in HM.build(**HOME)}
        loc = {p.name: p for fr in by_frame().values() for p in fr}
        guides = getattr(HM, "GUIDES", [])
    elif module == "vgr":
        import vgr_model as VG
        mod = loc = {p.name: p for p in VG.build()}
        guides = getattr(VG, "GUIDES", [])
    elif module == "oven":
        import oven_model as OM
        mod = loc = {p.name: p for p in OM.build()}
        guides = getattr(OM, "GUIDES", [])
    elif module == "sorting":
        import sorting_model as SM
        mod = loc = {p.name: p for p in SM.build()}
        guides = getattr(SM, "GUIDES", [])
    else:
        mod = loc = {}
        guides = []
    _cache[module] = (mod, loc, guides)
    return _cache[module]


def _long_axis(p):
    if p.kind == "cyl":
        return "xyz".index(p.s[0])
    return max(range(3), key=lambda i: p.s[i])


def pocket(g, c):
    """The guest's envelope grown by c across its travel axis (not along it)."""
    x0, y0, z0, x1, y1, z1 = detail.envelope(g)
    if g.kind == "cyl":
        ax, L, d = g.s
        dirv = {"x": V(1, 0, 0), "y": V(0, 1, 0), "z": V(0, 0, 1)}[ax]
        return Part.makeCylinder(d / 2.0 + c, L, V(*g.p), dirv)
    ax = _long_axis(g)
    lo, hi = [x0, y0, z0], [x1, y1, z1]
    for i in range(3):
        if i != ax:
            lo[i] -= c
            hi[i] += c
    return Part.makeBox(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2], V(*lo))


def guided(p, module, siblings=None):
    """Precise shape of local part p with its guide pockets cut in."""
    s = detail.precise(p, siblings)
    mod, loc, guides = _model(module)
    tools = []
    for host, guest, kind, c in guides:
        if host != p.name or guest not in mod or host not in mod:
            continue
        hm = mod[host]
        d = V(*p.p) - V(*hm.p)                   # module -> this part's local frame
        t = pocket(mod[guest], c)
        t.translate(d)
        tools.append(t)
    if tools:
        s = s.cut(Part.makeCompound(tools)).removeSplitter()
    return s


def check_guides(module, tol_gap=0.02):
    """Exact-B-rep proof of every guide pair (see module docstring)."""
    mod, loc, guides = _model(module)
    fails, rows = [], []
    for host, guest, kind, c in guides:
        if host not in mod or guest not in mod:
            fails.append(f"{module}: guide names unknown part {host if host not in mod else guest}")
            continue
        hm, gm = mod[host], mod[guest]
        hs = guided(hm, module) if host in loc and loc[host] is hm else _guided_module(hm, module)
        gs = detail.precise(gm)
        vol = hs.common(gs).Volume
        gap = hs.distToShape(gs)[0]
        through = True
        if kind == "slide":
            ax = _long_axis(gm)
            he, ge = detail.envelope(hm), detail.envelope(gm)
            through = ge[ax] <= he[ax] + 1e-6 and ge[ax + 3] >= he[ax + 3] - 1e-6
        ok = vol < 1e-3 and (kind == "bore" or gap <= c + tol_gap) and through
        rows.append({"host": host, "guest": guest, "kind": kind, "clearance": c,
                     "overlap_mm3": round(vol, 5), "gap_mm": round(gap, 4), "through": through, "ok": ok})
        if not ok:
            why = ("overlap %.3f mm3" % vol if vol >= 1e-3 else
                   "not through along the travel axis" if not through else
                   "gap %.3f > clearance %.2f (not guided)" % (gap, c))
            fails.append(f"{module}: {host} / {guest} ({kind}): {why}")
    return fails, rows


def _guided_module(hm, module):
    """guided() for a part given in MODULE coordinates (HBW frames differ)."""
    mod, loc, guides = _model(module)
    s = detail.precise(hm)
    tools = [pocket(mod[g], c) for h, g, k, c in guides if h == hm.name and g in mod]
    if tools:
        s = s.cut(Part.makeCompound(tools)).removeSplitter()
    return s
