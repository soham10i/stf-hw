"""
Solid geometry for the STF-2 proofs - plain Python, no CAD kernel.

line_model describes every part as a box, an axis-aligned cylinder (solid or a
TUBE: mech 'tube:ID'), a rod (cylinder between two arbitrary points) or an arc
(annular sector extruded in z). The old static_clearance compared bounding
boxes between modules only; the precise phase needs the exact answer for EVERY
pair, including parts of the same module, and for every fastener.

interfere(a, b) returns the penetration depth estimate (mm, > tol means the two
solids share volume). Exact for box/box, box/axis-cylinder, coaxial-direction
cylinders; for the rest (rods, arcs, crossed cylinders) it samples the surface
of each solid at <= SAMPLE mm and tests the points against the other solid's
exact inside() - a sliver thinner than the sampling is caught by the B-rep
check in line_cad (Shape.common), which stays the authority.
"""
import math

SAMPLE = 1.0
TOL = 0.05


# ------------------------------------------------------------------ helpers
def aabb(p):
    return p.aabb()


def aabb_overlap(a, b, tol=TOL):
    d = [min(a[i + 3], b[i + 3]) - max(a[i], b[i]) for i in range(3)]
    return min(d) if min(d) > tol else 0.0


_AX = {"x": 0, "y": 1, "z": 2}


def _cyl(p):
    """(axis index, start along axis, length, centre (u, v) across, r, r_in)."""
    ax, Ln, d = p.s
    i = _AX[ax]
    c = [p.p[k] for k in range(3) if k != i]
    r_in = float(p.mech.split(":")[1]) / 2 if p.mech.startswith("tube:") else 0.0
    return i, p.p[i], Ln, c, d / 2.0, r_in


def _rect_circle_depth(rx0, ry0, rx1, ry1, cx, cy, r):
    """How deep a circle and a rectangle interpenetrate in 2D (<= 0: apart)."""
    dx = max(rx0 - cx, 0.0, cx - rx1)
    dy = max(ry0 - cy, 0.0, cy - ry1)
    if dx > 0 or dy > 0:
        return r - math.hypot(dx, dy)
    # centre inside the rectangle
    return r + min(cx - rx0, rx1 - cx, cy - ry0, ry1 - cy)


# ------------------------------------------------------------- inside tests
def inside(p, q, tol=TOL):
    """Depth of point q inside solid p (> tol = inside)."""
    x, y, z = q
    if p.kind == "box":
        b = p.aabb()
        return min(x - b[0], b[3] - x, y - b[1], b[4] - y, z - b[2], b[5] - z)
    if p.kind == "cyl":
        i, a0, Ln, c, r, r_in = _cyl(p)
        t = q[i] - a0
        u = [q[k] for k in range(3) if k != i]
        rr = math.hypot(u[0] - c[0], u[1] - c[1])
        d = min(t, Ln - t, r - rr)
        if r_in > 0:
            d = min(d, rr - r_in)
        return d
    if p.kind == "rod":
        x0, y0, z0 = p.p
        x1, y1, z1, dd = p.s
        v = (x1 - x0, y1 - y0, z1 - z0)
        L2 = sum(k * k for k in v)
        Ln = math.sqrt(L2)
        w = (x - x0, y - y0, z - z0)
        t = sum(w[k] * v[k] for k in range(3)) / Ln
        rr = math.sqrt(max(sum(k * k for k in w) - t * t, 0.0))
        return min(t, Ln - t, dd / 2 - rr)
    if p.kind == "arc":
        cx, cy, z0 = p.p
        ri, ro, h, a0, a1 = p.s
        rr = math.hypot(x - cx, y - cy)
        ang = math.degrees(math.atan2(y - cy, x - cx))
        while ang < a0:
            ang += 360
        while ang > a0 + 360:
            ang -= 360
        if ang > a1:
            return -1.0
        arcd = min((ang - a0), (a1 - ang)) * math.pi / 180 * rr
        return min(rr - ri, ro - rr, z - z0, z0 + h - z, arcd)
    raise ValueError(p.kind)


def surface(p, step=SAMPLE):
    """Points on the boundary of p (and a coarse interior lattice so a solid
    completely swallowed by another is caught too)."""
    pts = []
    if p.kind == "box":
        x0, y0, z0, x1, y1, z1 = p.aabb()
        n = [max(2, int(math.ceil((hi - lo) / step)) + 1) for lo, hi in ((x0, x1), (y0, y1), (z0, z1))]
        xs = [x0 + (x1 - x0) * k / (n[0] - 1) for k in range(n[0])]
        ys = [y0 + (y1 - y0) * k / (n[1] - 1) for k in range(n[1])]
        zs = [z0 + (z1 - z0) * k / (n[2] - 1) for k in range(n[2])]
        for x in xs:
            for y in ys:
                pts += [(x, y, z0), (x, y, z1)]
        for x in xs:
            for z in zs:
                pts += [(x, y0, z), (x, y1, z)]
        for y in ys:
            for z in zs:
                pts += [(x0, y, z), (x1, y, z)]
        pts.append(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
        return pts
    if p.kind in ("cyl", "rod"):
        if p.kind == "cyl":
            i, a0, Ln, c, r, r_in = _cyl(p)
            e = [0.0, 0.0, 0.0]
            e[i] = 1.0
            o = [0.0, 0.0, 0.0]
            o[i] = a0
            j = [k for k in range(3) if k != i]
            o[j[0]], o[j[1]] = c
            u, w = [0.0] * 3, [0.0] * 3
            u[j[0]], w[j[1]] = 1.0, 1.0
        else:
            x1, y1, z1, dd = p.s
            v = (x1 - p.p[0], y1 - p.p[1], z1 - p.p[2])
            Ln = math.sqrt(sum(k * k for k in v))
            e = [k / Ln for k in v]
            o = list(p.p)
            r, r_in = dd / 2, 0.0
            a = (1.0, 0.0, 0.0) if abs(e[0]) < 0.9 else (0.0, 1.0, 0.0)
            u = [e[1] * a[2] - e[2] * a[1], e[2] * a[0] - e[0] * a[2], e[0] * a[1] - e[1] * a[0]]
            nu = math.sqrt(sum(k * k for k in u))
            u = [k / nu for k in u]
            w = [e[1] * u[2] - e[2] * u[1], e[2] * u[0] - e[0] * u[2], e[0] * u[1] - e[1] * u[0]]
        na = max(2, int(math.ceil(Ln / step)) + 1)
        nc = max(12, int(math.ceil(2 * math.pi * r / step)))

        def P(t, rad, th):
            return tuple(o[k] + e[k] * t + rad * (math.cos(th) * u[k] + math.sin(th) * w[k]) for k in range(3))

        for ia in range(na):
            t = Ln * ia / (na - 1)
            for ic in range(nc):
                th = 2 * math.pi * ic / nc
                pts.append(P(t, r, th))
                if r_in > 0:
                    pts.append(P(t, r_in, th))
        for t in (0.0, Ln):                      # end faces
            nr = max(1, int(math.ceil((r - r_in) / step)))
            for ir in range(nr + 1):
                rad = r_in + (r - r_in) * ir / nr
                for ic in range(nc):
                    pts.append(P(t, rad, 2 * math.pi * ic / nc))
        if r_in == 0:
            pts.append(P(Ln / 2, 0.0, 0.0))
        return pts
    if p.kind == "arc":
        cx, cy, z0 = p.p
        ri, ro, h, a0, a1 = p.s
        na = max(2, int(math.ceil(math.radians(a1 - a0) * ro / step)) + 1)
        nr = max(2, int(math.ceil((ro - ri) / step)) + 1)
        nz = max(2, int(math.ceil(h / step)) + 1)
        for ia in range(na):
            th = math.radians(a0 + (a1 - a0) * ia / (na - 1))
            c_, s_ = math.cos(th), math.sin(th)
            for ir in range(nr):
                rad = ri + (ro - ri) * ir / (nr - 1)
                pts += [(cx + rad * c_, cy + rad * s_, z0), (cx + rad * c_, cy + rad * s_, z0 + h)]
            for iz in range(nz):
                z = z0 + h * iz / (nz - 1)
                pts += [(cx + ri * c_, cy + ri * s_, z), (cx + ro * c_, cy + ro * s_, z)]
        return pts
    raise ValueError(p.kind)


# ------------------------------------------------------------ pair test
def interfere(a, b, tol=TOL):
    """Penetration depth of solids a and b (0.0 if they do not share volume
    deeper than tol)."""
    A, B = a.aabb(), b.aabb()
    ov = aabb_overlap(A, B, tol)
    if not ov:
        return 0.0
    ka, kb = a.kind, b.kind
    if ka == "box" and kb == "box":
        return ov
    if {ka, kb} == {"box", "cyl"}:
        bx, cy_ = (a, b) if ka == "box" else (b, a)
        i, a0, Ln, c, r, r_in = _cyl(cy_)
        bb = bx.aabb()
        ax_ov = min(bb[i + 3], a0 + Ln) - max(bb[i], a0)
        j = [k for k in range(3) if k != i]
        d2 = _rect_circle_depth(bb[j[0]], bb[j[1]], bb[j[0] + 3], bb[j[1] + 3], c[0], c[1], r)
        if r_in > 0 and d2 > tol:                   # tube: the box may sit in the bore
            corners = [(u, v) for u in (bb[j[0]], bb[j[0] + 3]) for v in (bb[j[1]], bb[j[1] + 3])]
            if all(math.hypot(u - c[0], v - c[1]) < r_in - tol for u, v in corners):
                return 0.0
            if r_in > 0:
                return _sampled(a, b, tol)
        d = min(ax_ov, d2)
        return d if d > tol else 0.0
    if ka == "cyl" and kb == "cyl" and a.s[0] == b.s[0]:
        ia, a0, La, ca, ra, rina = _cyl(a)
        ib, b0, Lb, cb, rb, rinb = _cyl(b)
        ax_ov = min(a0 + La, b0 + Lb) - max(a0, b0)
        dc = math.hypot(ca[0] - cb[0], ca[1] - cb[1])
        d2 = ra + rb - dc
        if (rina > 0 and dc + rb < rina - tol) or (rinb > 0 and dc + ra < rinb - tol):
            return 0.0                              # one sits in the other's bore
        d = min(ax_ov, d2)
        return d if d > tol else 0.0
    return _sampled(a, b, tol)


def _sampled(a, b, tol):
    best = 0.0
    for p, q in ((a, b), (b, a)):
        qb = q.aabb()
        for pt in surface(p):
            if not (qb[0] < pt[0] < qb[3] and qb[1] < pt[1] < qb[4] and qb[2] < pt[2] < qb[5]):
                continue
            d = inside(q, pt)
            if d > tol and d > best:
                best = d
    return best if best > tol else 0.0


def pairs(parts, tol=TOL):
    """All interfering pairs among parts, sweep-and-prune on x."""
    items = sorted(((p.aabb(), p) for p in parts), key=lambda t: t[0][0])
    out = []
    for i, (A, a) in enumerate(items):
        for B, b in items[i + 1:]:
            if B[0] >= A[3] - tol:
                break
            if aabb_overlap(A, B, tol):
                d = interfere(a, b, tol)
                if d:
                    out.append((a, b, d))
    return out
