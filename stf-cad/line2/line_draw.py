"""
Blueprints for STF-2, generated from line_model (never drawn by hand).

  blueprints/00_layout.svg          A2, whole table 1:5: modules, loop, flow, stations, timing
  blueprints/<module>.svg           A3, third-angle projection (TOP / FRONT / RIGHT), scale
                                    chosen from the standard series, overall + key dimensions,
                                    I/O callouts, notes, BOM, title block
  blueprints/index.html             the blueprint book: sheets + design case + proofs + simulation

Run: python3 line_draw.py   (refuses to draw if line_model.check() fails)
"""
import html
import json
import math
import os
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import line_model as M

L = M.L
OUT = os.path.join(HERE, "blueprints")
SCALES = [1.0, 0.5, 0.4, 0.25, 0.2, 0.1, 0.05]
INK, THIN, ACCENT = "#1b2330", 0.18, "#1f4e8c"
DATE = time.strftime("%Y-%m-%d")


def lighten(h, a=0.55):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % tuple(int(c + (255 - c) * a) for c in (r, g, b))


def esc(t):
    return html.escape(str(t), quote=True)


# ------------------------------------------------------------ projection
VIEWS = {  # (horizontal model axis, vertical model axis, depth axis, depth sign: +1 = larger is nearer)
    "TOP": (0, 1, 2, +1),
    "FRONT": (0, 2, 1, -1),
    "RIGHT": (1, 2, 0, +1),
}


def extent(parts):
    bb = [min(p.aabb()[i] for p in parts) for i in range(3)] + [max(p.aabb()[i + 3] for p in parts) for i in range(3)]
    return bb


class View:
    def __init__(self, name, parts, sc, ox, oy):
        """ox, oy: sheet position (mm) of the view's model-min corner, bottom-left."""
        self.name, self.parts, self.sc = name, parts, sc
        self.h, self.v, self.d, self.ds = VIEWS[name]
        self.bb = extent(parts)
        self.ox, self.oy = ox, oy

    def size(self):
        return ((self.bb[self.h + 3] - self.bb[self.h]) * self.sc, (self.bb[self.v + 3] - self.bb[self.v]) * self.sc)

    def X(self, u):
        return self.ox + (u - self.bb[self.h]) * self.sc

    def Y(self, w):
        return self.oy - (w - self.bb[self.v]) * self.sc

    def pt(self, p3):
        return self.X(p3[self.h]), self.Y(p3[self.v])

    def svg(self, keep_order=False, section=()):
        """keep_order: draw in the given order (sections). section: names drawn as cut
        outlines (no fill), so what they contain shows."""
        o = []
        key = (lambda p: p.aabb()[self.d + 3]) if self.ds > 0 else (lambda p: -p.aabb()[self.d])
        for p in (self.parts if keep_order else sorted(self.parts, key=key)):
            fill, stroke = lighten(p.colour), INK
            b = p.aabb()
            if p.kind == "rod":
                a = p.p
                e = p.s[:3]
                x0, y0 = self.pt(a)
                x1, y1 = self.pt(e)
                w = max(p.s[3] * self.sc, 0.25)
                o.append(f'<line x1="{x0:.2f}" y1="{y0:.2f}" x2="{x1:.2f}" y2="{y1:.2f}" stroke="{INK}" '
                         f'stroke-width="{w + 0.25:.2f}" stroke-linecap="round"/>'
                         f'<line x1="{x0:.2f}" y1="{y0:.2f}" x2="{x1:.2f}" y2="{y1:.2f}" stroke="{fill}" '
                         f'stroke-width="{w:.2f}" stroke-linecap="round"/>')
                continue
            if p.kind == "arc" and self.name == "TOP":
                cx, cy, _ = p.p
                ri, ro, _, a0, a1 = p.s
                pts = []
                for k in range(0, 37):
                    t = math.radians(a0 + (a1 - a0) * k / 36)
                    pts.append((cx + ro * math.cos(t), cy + ro * math.sin(t)))
                for k in range(36, -1, -1):
                    t = math.radians(a0 + (a1 - a0) * k / 36)
                    pts.append((cx + ri * math.cos(t), cy + ri * math.sin(t)))
                d = "M" + " L".join(f"{self.X(x):.2f},{self.Y(y):.2f}" for x, y in pts) + " Z"
                o.append(f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{THIN}"/>')
                continue
            if p.kind == "cyl" and "xyz".index(p.s[0]) == self.d:
                cx, cy = self.pt(p.p)
                r = p.s[2] / 2 * self.sc
                o.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="{fill}" stroke="{stroke}" '
                         f'stroke-width="{THIN}"/>')
                if p.mech.startswith("tube:"):
                    o.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{float(p.mech.split(":")[1]) / 2 * self.sc:.2f}" '
                             f'fill="#ffffff" stroke="{stroke}" stroke-width="{THIN}"/>')
                if r > 1.5:
                    o.append(f'<path d="M{cx - r * 0.3:.2f},{cy:.2f}h{r * 0.6:.2f}M{cx:.2f},{cy - r * 0.3:.2f}v{r * 0.6:.2f}" '
                             f'stroke="{INK}" stroke-width="0.1"/>')
                continue
            x0, x1 = self.X(b[self.h]), self.X(b[self.h + 3])
            y0, y1 = self.Y(b[self.v + 3]), self.Y(b[self.v])
            cut = p.name in section
            o.append(f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{max(x1 - x0, 0.1):.2f}" height="{max(y1 - y0, 0.1):.2f}" '
                     f'fill="{"url(#hatch)" if cut else fill}" stroke="{stroke}" stroke-width="{THIN * (2 if cut else 1)}"/>')
            if p.mech.startswith("stack:") and self.name != "TOP":
                n_ = int(p.mech.split(":")[1])
                for k in range(1, n_):
                    yy = self.Y(b[2] + k * L["BOX"][2])
                    o.append(f'<line x1="{x0:.2f}" y1="{yy:.2f}" x2="{x1:.2f}" y2="{yy:.2f}" stroke="{INK}" stroke-width=".08"/>')
            if p.mech.startswith("tray:") and cut and self.name != "TOP":
                n = int(p.mech.split(":")[1])
                cx0 = (b[0] + b[3]) / 2
                for k in range(n):
                    px = cx0 + (k - (n - 1) / 2) * L["POCKET_PITCH"]
                    o.append(f'<rect x="{self.X(px - L["POCKET_D"] / 2):.2f}" y="{self.Y(b[5]):.2f}" '
                             f'width="{L["POCKET_D"] * self.sc:.2f}" height="{L["POCKET_DEPTH"] * self.sc:.2f}" '
                             f'fill="#ffffff" stroke="{INK}" stroke-width="{THIN}"/>')
                continue
            if p.mech.startswith("tray:"):
                n = int(p.mech.split(":")[1])
                cx0, cy0 = (b[0] + b[3]) / 2, (b[1] + b[4]) / 2
                for k in range(n):
                    px = cx0 + (k - (n - 1) / 2) * L["POCKET_PITCH"]
                    if self.name == "TOP":
                        o.append(f'<circle cx="{self.X(px):.2f}" cy="{self.Y(cy0):.2f}" r="{L["POCKET_D"] / 2 * self.sc:.2f}" '
                                 f'fill="none" stroke="{INK}" stroke-width="{THIN}" stroke-dasharray="0.8 0.4"/>')
                    else:
                        hx = self.X(px - L["POCKET_D"] / 2) if self.name == "FRONT" else None
                        if hx is not None:
                            o.append(f'<rect x="{hx:.2f}" y="{self.Y(b[5]):.2f}" width="{L["POCKET_D"] * self.sc:.2f}" '
                                     f'height="{L["POCKET_DEPTH"] * self.sc:.2f}" fill="none" stroke="{INK}" '
                                     f'stroke-width="{THIN}" stroke-dasharray="0.8 0.4"/>')
        w, h = self.size()
        o.append(f'<text x="{self.ox:.1f}" y="{self.oy - h - 3:.1f}" class="vt">{self.name} VIEW</text>')
        return "\n".join(o)

    def dim_h(self, u0, u1, w, off, text=None):
        """Horizontal dimension between model h-coords u0..u1 at model v-coord w, offset (mm on sheet, + down)."""
        x0, x1, y = self.X(u0), self.X(u1), self.Y(w) + off
        t = text or f"{u1 - u0:.1f}".rstrip("0").rstrip(".")
        return _dim(x0, y, x1, y, t, self.Y(w))

    def dim_v(self, w0, w1, u, off, text=None):
        y0, y1, x = self.Y(w0), self.Y(w1), self.X(u) + off
        t = text or f"{w1 - w0:.1f}".rstrip("0").rstrip(".")
        return _dim(x, y0, x, y1, t, self.X(u), vertical=True)


C30, S30 = math.cos(math.radians(30)), math.sin(math.radians(30))


def _iso(x, y, z):
    """Pictorial from the front-left-top: +x right-up, +y left-up, +z up (math y up)."""
    return (x - y) * C30, (x + y) * S30 + z


def _shade(h, k):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c * k))) for c in (r, g, b))


def _solid_faces(p):
    """Visible faces (list of (poly3d, shade)) of a part, seen from (-x,-y,+z)."""
    x0, y0, z0, x1, y1, z1 = p.aabb()
    if p.kind == "box":
        return [([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], 1.0),
                ([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], 0.80),
                ([(x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1)], 0.65)]
    if p.kind == "cyl":
        ax, Ln, d = p.s
        r = d / 2
        n = 20
        cx, cy, cz = p.p
        faces = []
        if ax == "z":
            ring = lambda z: [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n), z)
                              for k in range(n)]
            bot, top = ring(cz), ring(cz + Ln)
            for k in range(n):
                a, b = k, (k + 1) % n
                mid = 2 * math.pi * (k + 0.5) / n
                if math.cos(mid) + math.sin(mid) < 0.3:            # faces toward the viewer
                    faces.append(([bot[a], bot[b], top[b], top[a]], 0.62 + 0.25 * max(0, -math.sin(mid))))
            faces.append((top, 1.0))
            return faces
        # horizontal cylinders: draw as their box (reads fine at drawing scale)
        return [([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], 1.0),
                ([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], 0.82),
                ([(x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1)], 0.68)]
    if p.kind == "arc":
        cx, cy, z0_ = p.p
        ri, ro, h, a0, a1 = p.s
        pts_o = [(cx + ro * math.cos(math.radians(a0 + (a1 - a0) * k / 24)),
                  cy + ro * math.sin(math.radians(a0 + (a1 - a0) * k / 24))) for k in range(25)]
        pts_i = [(cx + ri * math.cos(math.radians(a0 + (a1 - a0) * k / 24)),
                  cy + ri * math.sin(math.radians(a0 + (a1 - a0) * k / 24))) for k in range(25)]
        top = [(x, y, z0_ + h) for x, y in pts_o] + [(x, y, z0_ + h) for x, y in reversed(pts_i)]
        return [(top, 1.0)]
    return []


def iso_view(parts, ox, oy, max_w, max_h, label="ISOMETRIC (pictorial, not to scale)"):
    polys = []
    for p in parts:
        b = p.aabb()
        key = (b[0] + b[3] + b[1] + b[4]) / 2 - (b[2] + b[5]) * 0.9
        if p.kind == "rod":
            polys.append((key, "rod", p))
            continue
        for poly, k in _solid_faces(p):
            polys.append((key, "poly", (poly, k, p.colour)))
    pts = []
    for _, kind, item in polys:
        if kind == "rod":
            pts += [_iso(*item.p), _iso(*item.s[:3])]
        else:
            pts += [_iso(*q) for q in item[0]]
    xs, ys = [q[0] for q in pts], [q[1] for q in pts]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    sc = min(max_w / w, max_h / h)
    tx = lambda q: (ox + (q[0] - min(xs)) * sc, oy - (q[1] - min(ys)) * sc)
    o = [f'<text x="{ox:.1f}" y="{oy - h * sc - 3:.1f}" class="vt">{label}</text>']
    for _, kind, item in sorted(polys, key=lambda t: -t[0]):
        if kind == "rod":
            a, e = tx(_iso(*item.p)), tx(_iso(*item.s[:3]))
            wdt = max(item.s[3] * sc, 0.3)
            o.append(f'<line x1="{a[0]:.2f}" y1="{a[1]:.2f}" x2="{e[0]:.2f}" y2="{e[1]:.2f}" stroke="{_shade(item.colour, .7)}" '
                     f'stroke-width="{wdt:.2f}" stroke-linecap="round"/>')
            continue
        poly, k, col = item
        d = "M" + " L".join("%.2f,%.2f" % tx(_iso(*q)) for q in poly) + " Z"
        o.append(f'<path d="{d}" fill="{_shade(lighten(col, .15), k)}" stroke="{INK}" stroke-width=".06"/>')
    return "\n".join(o)


def _dim(x0, y0, x1, y1, text, base, vertical=False):
    o = []
    if vertical:
        o.append(f'<line x1="{base:.2f}" y1="{y0:.2f}" x2="{x0 + (1.5 if x0 > base else -1.5):.2f}" y2="{y0:.2f}" class="ext"/>')
        o.append(f'<line x1="{base:.2f}" y1="{y1:.2f}" x2="{x1 + (1.5 if x1 > base else -1.5):.2f}" y2="{y1:.2f}" class="ext"/>')
        o.append(f'<line x1="{x0:.2f}" y1="{y0:.2f}" x2="{x1:.2f}" y2="{y1:.2f}" class="dim" '
                 f'marker-start="url(#a)" marker-end="url(#a)"/>')
        ym = (y0 + y1) / 2
        o.append(f'<text x="{x0 - 1.2:.2f}" y="{ym:.2f}" class="dt" transform="rotate(-90 {x0 - 1.2:.2f} {ym:.2f})" '
                 f'text-anchor="middle">{esc(text)}</text>')
    else:
        o.append(f'<line x1="{x0:.2f}" y1="{base:.2f}" x2="{x0:.2f}" y2="{y0 + (1.5 if y0 > base else -1.5):.2f}" class="ext"/>')
        o.append(f'<line x1="{x1:.2f}" y1="{base:.2f}" x2="{x1:.2f}" y2="{y1 + (1.5 if y1 > base else -1.5):.2f}" class="ext"/>')
        o.append(f'<line x1="{x0:.2f}" y1="{y0:.2f}" x2="{x1:.2f}" y2="{y1:.2f}" class="dim" '
                 f'marker-start="url(#a)" marker-end="url(#a)"/>')
        o.append(f'<text x="{(x0 + x1) / 2:.2f}" y="{y0 - 0.8:.2f}" class="dt" text-anchor="middle">{esc(text)}</text>')
    return "\n".join(o)


STYLE = """<defs><marker id="a" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse">
<path d="M0,2 L10,5 L0,8 z" fill="#1b2330"/></marker>
<marker id="f" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="5" markerHeight="5" orient="auto">
<path d="M0,1 L10,5 L0,9 z" fill="#1f4e8c"/></marker>
<pattern id="hatch" width="1.6" height="1.6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
<rect width="1.6" height="1.6" fill="#eef1f5"/><line x1="0" y1="0" x2="0" y2="1.6" stroke="#1b2330" stroke-width=".18"/></pattern></defs>
<style>
text{font-family:'Helvetica Neue',Arial,sans-serif;fill:#1b2330}
.vt{font-size:3.2px;font-weight:700;letter-spacing:.3px}
.dt{font-size:2.3px}
.dim{stroke:#1b2330;stroke-width:.15;fill:none}
.ext{stroke:#1b2330;stroke-width:.1}
.tb{font-size:2.6px}.tbh{font-size:4.2px;font-weight:700}.tbs{font-size:2.1px;fill:#445}
.nt{font-size:2.3px}.nh{font-size:2.8px;font-weight:700;fill:#1f4e8c}
.co{font-size:2.1px}.col{stroke:#1f4e8c;stroke-width:.15}
</style>"""


def sheet(w, h, body, title, sub, sheet_no, n_sheets, scale):
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}">', STYLE,
         f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
         f'<rect x="10" y="10" width="{w - 20}" height="{h - 20}" fill="none" stroke="{INK}" stroke-width=".5"/>',
         body]
    tx, ty, tw, th = w - 10 - 180, h - 10 - 38, 180, 38
    s.append(f'<rect x="{tx}" y="{ty}" width="{tw}" height="{th}" fill="#fff" stroke="{INK}" stroke-width=".35"/>')
    s.append(f'<rect x="{tx}" y="{ty}" width="{tw}" height="9" fill="{ACCENT}"/>')
    s.append(f'<text x="{tx + 3}" y="{ty + 6.3}" class="tbh" style="fill:#fff">STF-2 CONTINUOUS COOKIE LINE</text>')
    s.append(f'<text x="{tx + 3}" y="{ty + 15}" class="tbh" style="font-size:3.6px">{esc(title)}</text>')
    s.append(f'<text x="{tx + 3}" y="{ty + 20}" class="tbs">{esc(sub)}</text>')
    rows = [("SCALE", scale), ("SHEET", f"{sheet_no} / {n_sheets}"), ("DATE", DATE), ("UNITS", "mm, deg"),
            ("PROJECTION", "third angle"), ("SOURCE", "line_model.py (generated - do not edit)")]
    for i, (k, v) in enumerate(rows):
        cx, cy = tx + 3 + (i % 3) * 60, ty + 26 + (i // 3) * 6
        s.append(f'<text x="{cx}" y="{cy}" class="tbs">{k}</text><text x="{cx}" y="{cy + 3}" class="tb">{esc(v)}</text>')
    s.append("</svg>")
    return "\n".join(s)


def notes_block(x, y, w, lines, title):
    o = [f'<text x="{x}" y="{y}" class="nh">{esc(title)}</text>']
    yy = y + 4.2
    for ln in lines:
        wrap = _wrap(ln, int(w / 1.15))
        for k, part in enumerate(wrap):
            o.append(f'<text x="{x + (2 if k else 0)}" y="{yy:.1f}" class="nt">{esc(part)}</text>')
            yy += 3.1
        yy += 0.6
    return "\n".join(o), yy


def _wrap(t, n):
    words, out, cur = t.split(), [], ""
    for wd in words:
        if len(cur) + len(wd) + 1 > n:
            out.append(cur)
            cur = wd
        else:
            cur = (cur + " " + wd).strip()
    if cur:
        out.append(cur)
    return out or [""]


# ------------------------------------------------------------ module content
def key_dims(mod, views):
    """Module-specific dimensions, from the parameters (never typed)."""
    T, F_, R = views["TOP"], views["FRONT"], views["RIGHT"]
    o = []
    yf, yb = M.y_front(), M.y_back()
    if mod == "M1_loop":
        (clx, cly), (crx, _) = M.centres()
        o.append(T.dim_h(clx, crx, yf, 6 + 8, f"S = {M.straight():.1f} (N*P = 2S + 2piR)"))
        o.append(T.dim_v(yf, yb, clx - L["R"] - 40, -6, f"2R = {2 * L['R']:.0f}"))
        o.append(F_.dim_v(0, L["BELT_Z"], clx, -10, f"chain top {L['BELT_Z']:.0f}"))
    elif mod == "M2_feeder":
        hx = L["HOPPER_X"][0]
        hw, hd, hh = L["HOPPER"]
        o.append(F_.dim_v(L["HOPPER_Z"], L["HOPPER_Z"] + hh, hx, -16, f"hopper {hh:.0f} ({M.hopper_cap()} cookies)"))
        xs = L["MAG_X"]
        o.append(T.dim_h(xs[0], xs[1], yf, 10, f"{xs[1] - xs[0]:.0f}"))
        o.append(T.dim_h(xs[1], xs[2], yf, 10, f"{xs[2] - xs[1]:.0f}"))
        o.append(F_.dim_v(M.z_cookie_top(), M.z_cookie_top() + L["DROP_H"], xs[0], -12, f"drop {L['DROP_H']:.0f}"))
    elif mod == "M3_tunnel":
        o0, o1 = M.oven_x()
        c0, c1 = M.cool_x()
        o.append(T.dim_h(o0, o1, yf - L["TUN_HALF"], 8, f"oven {M.oven_len():.0f} = v x {L['BAKE_S']:g} s"))
        o.append(T.dim_h(c0, c1, yf - L["TUN_HALF"], 8, f"cool {M.cool_len():.0f}"))
        o.append(F_.dim_v(M.z_cookie_top(), M.z_cookie_top() + L["TUN_CLEAR"], o0, -10, f"clear {L['TUN_CLEAR']:.0f}"))
    elif mod == "M4_stamp":
        x0 = L["STAMP_X0"]
        o.append(T.dim_h(x0, x0 + L["STAMP_STROKE"], yf, 8, f"stroke {L['STAMP_STROKE']:.0f}"))
        o.append(F_.dim_v(M.z_cookie_top(), M.z_cookie_top() + L["STAMP_CLEAR"], x0, -10, f"{L['STAMP_CLEAR']:.0f}"))
    elif mod == "M5_qc":
        x0, x1 = L["QC_X"]
        o.append(T.dim_h(L["KICK_X"], L["CAM_X"], yb, 12, f"cam -> kicker {L['CAM_X'] - L['KICK_X']:.0f}"))
        o.append(F_.dim_v(M.z_cookie_top(), M.z_cookie_top() + L["SENSOR_GAP"], L["CS_X"], 10, f"gap {L['SENSOR_GAP']:.0f}"))
    elif mod == "M6_pick":
        a, b = L["DELTA_X"]
        o.append(T.dim_h(b, a, L["DELTA_Y"], 14, f"delta pitch {a - b:.0f}"))
        o.append(R.dim_v(M.pick_z(), L["DELTA_Z"], L["DELTA_Y"], 14, f"base -> pick {L['DELTA_Z'] - M.pick_z():.0f}"))
    elif mod == "M7_pack":
        ys = L["LANE_Y"]
        o.append(T.dim_v(ys[0], ys[1], L["LANE_X"][0], -6, f"{ys[1] - ys[0]:.0f}"))
        xa, xs_ = L["CASS_X"]
        o.append(T.dim_h(xa, xs_, ys[-1] + 40, -8, f"shuttle {xs_ - xa:.0f}"))
        o.append(F_.dim_v(L["CASS_Z"], L["CASS_Z"] + L["CASS"][2], xs_ + L["CASS"][0], 8,
                          f"cassette {L['CASS'][2]:.0f} = {M.cass_cap()} packs"))
    return o


def module_notes(mod, parts, trows):
    rel = {"M1_loop": ["takt", "loop"], "M2_feeder": ["feeder", "singulator", "STOCK raw", "AMR deadline: raw"], "M3_tunnel": ["oven", "cooling"],
           "M4_stamp": ["stamp"], "M5_qc": ["QC", "kick", "STOCK rejects"], "M6_pick": ["pick", "tracking"],
           "M7_pack": ["cookie into", "pockets", "below the film", "sealer", "guided", "pawls", "film", "STOCK finished",
                       "STOCK empty", "AMR deadline: cassette"],
           "M8_control": [], "M9_ports": ["AMR"], "M10_safety": ["height"]}[mod]
    lines = [M.MODULES[mod]]
    for name, v, lim, ok, note in trows:
        if any(k.lower() in name.lower() for k in rel):
            lines.append(f"{'OK' if ok else 'FAIL'} - {name}: {v} {lim} {note}".strip())
    io = sorted({p.tag for p in parts if p.tag and p.group not in ("puck",)})
    if io:
        lines.append("I/O: " + ", ".join(io))
    bom = Counter(p.group for p in parts)
    lines.append("Parts: " + ", ".join(f"{g} x{n}" for g, n in sorted(bom.items())))
    assumed = "Sizes of bought ft parts from datasheets; everything tagged [assumed] in line_model.L - MEASURE."
    lines.append(assumed)
    return lines


def module_sheet(mod, parts, no, n, trows):
    W, H = 420, 297
    bb = extent(parts)
    dx, dy, dz = bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]
    area_w, area_h = 400 - 30 - 75, 297 - 20 - 45 - 30
    sc = next(s for s in SCALES if (dx + dy) * s + 40 <= area_w and (dy + dz) * s + 30 <= area_h)
    gap = 22
    fx, fy = 30, 20 + 12 + dy * sc + gap + dz * sc          # FRONT view bottom-left
    top = View("TOP", parts, sc, fx, 20 + 12 + dy * sc)
    front = View("FRONT", parts, sc, fx, fy)
    right = View("RIGHT", parts, sc, fx + dx * sc + gap, fy)
    views = {"TOP": top, "FRONT": front, "RIGHT": right}
    body = [top.svg(), front.svg(), right.svg()]
    body.append(front.dim_h(bb[0], bb[3], bb[2], 7))
    body.append(front.dim_v(bb[2], bb[5], bb[0], -7))
    body.append(top.dim_v(bb[1], bb[4], bb[0], -7))
    body.append(right.dim_h(bb[1], bb[4], bb[2], 7))
    body += key_dims(mod, views)
    # I/O callouts on the TOP view
    seen, tagged = set(), []
    for p in parts:
        if p.tag and p.group not in ("puck",) and p.tag.split(".")[0] not in seen:
            seen.add(p.tag.split(".")[0])
            tagged.append(p)
    tagged = tagged[:10]
    for i, p in enumerate(tagged):
        b = p.aabb()
        cx, cy = top.pt(((b[0] + b[3]) / 2, (b[1] + b[4]) / 2, 0))
        lx = top.ox + dx * sc + 6 + (i % 2) * 36
        ly = top.oy - dy * sc + 4 + (i // 2) * 5.2
        body.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{lx - 1:.1f}" y2="{ly - 0.8:.1f}" class="col"/>'
                    f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r=".5" fill="{ACCENT}"/>'
                    f'<text x="{lx:.1f}" y="{ly:.1f}" class="co">{esc(p.tag.split(".")[0])} {esc(p.name[:16])}</text>')
    ix = right.ox + dy * sc + 18
    if 410 - ix > 60:
        body.append(iso_view(parts, ix, 205, 410 - ix - 4, 150))
    # notes: the strip left of the title block, below the views
    nlines = module_notes(mod, parts, trows)
    nb, _ = notes_block(14, 297 - 10 - 38 + 3, 420 - 10 - 180 - 14 - 6, nlines[:7], "NOTES")
    body.append(nb)
    scl = f"1:{round(1 / sc, 2):g}"
    return sheet(W, H, "\n".join(body), f"{mod} - {M.MODULES[mod].split(' - ')[0]}", M.MODULES[mod], no, n, scl)


def packaging_sheet(parts, trows, no, n):
    """How a round cookie goes into a rectangular pack and how packs are stored."""
    W, H = 420, 297
    by = {p.name: p for p in parts}
    open_tray = [by["tray_weiss_A"]] + [p for p in parts if p.name.startswith("tray_weiss_A_cookie_")]
    sealed = [by["tray_weiss_sealed"]] + [p for p in parts if p.name.startswith("tray_weiss_sealed_cookie_")] + \
             [by["tray_weiss_sealed_film"]]
    cass = [p for p in parts if p.name.startswith("cassette_weiss_standby") and "_wall_front" not in p.name]
    if not cass:                     # airlock layout: no standby cassette in the machine - draw a full one
        tmp = []
        M._cassette(tmp.append, "cassette_weiss_standby", L["CASS_X"][1], L["LANE_Y"][0], M.cass_cap(), "",
                    L["BAKED"][0])
        cass = [p for p in tmp if "_wall_front" not in p.name]
    cass = sorted(cass, key=lambda p: (0 if "_wall_back" in p.name else 1 if "_stack" in p.name else 2))
    body = []
    t1 = View("TOP", open_tray, 1.0, 30, 34 + L["BOX"][1])
    body.append(t1.svg(keep_order=True).replace("TOP VIEW", "OPEN TRAY BEING FILLED - TOP (1:1)"))
    b = t1.bb
    cx = (b[0] + b[3]) / 2
    body.append(t1.dim_h(b[0], b[3], b[1], 6))
    body.append(t1.dim_h(cx - L["POCKET_PITCH"], cx, b[1], 14, f"pocket pitch {L['POCKET_PITCH']:g}"))
    body.append(t1.dim_v(b[1], b[4], b[3], 6))
    body.append(t1.dim_h(cx + L["POCKET_PITCH"] - L["POCKET_D"] / 2, cx + L["POCKET_PITCH"] + L["POCKET_D"] / 2,
                         (b[1] + b[4]) / 2, 50, f"pocket D{L['POCKET_D']:g} (cookie D{L['COOKIE'][0]:g})"))
    f1 = View("FRONT", sealed, 1.0, 30, 160)
    body.append(f1.svg(keep_order=True, section={"tray_weiss_sealed"}).replace("FRONT VIEW", "SEALED PACK - SECTION (1:1)"))
    fb = f1.bb
    body.append(f1.dim_v(fb[5] - L["POCKET_DEPTH"] - 0.6, fb[5] - 0.6, fb[0], -6, f"{L['POCKET_DEPTH']:g}"))
    body.append(f1.dim_v(fb[2], fb[5], fb[3], 6, f"{L['BOX'][2]:g}"))
    body.append(f'<text x="{f1.X(fb[3]) + 12:.1f}" y="{f1.Y(fb[5]) + 1:.1f}" class="co">film on the {L["FLANGE"]:g} mm flange, '
                f'1 mm above the cookie</text>')
    sc = 0.25
    cf = View("FRONT", cass, sc, 262, 226)
    body.append(cf.svg(keep_order=True).replace("FRONT VIEW", "FULL CASSETTE - FRONT WALL REMOVED (1:4)"))
    cb = cf.bb
    body.append(cf.dim_v(cb[2], cb[5], cb[0], -6))
    xm = cf.X((cb[0] + cb[3]) / 2)
    for y0, y1, t in ((cf.Y(cb[2]) + 14, cf.Y(cb[2]) + 1, "IN: the stacker pushes each"),
                      (cf.Y(cb[5]) - 1, cf.Y(cb[5]) - 14, "OUT: top opening, FIFO")):
        body.append(f'<line x1="{xm:.1f}" y1="{y0:.1f}" x2="{xm:.1f}" y2="{y1:.1f}" stroke="{ACCENT}" stroke-width=".6" '
                    f'marker-end="url(#f)"/><text x="{cf.X(cb[3]) + 4:.1f}" y="{(y0 + y1) / 2 + 1:.1f}" class="co" '
                    f'style="fill:#1f4e8c;font-weight:700">{esc(t)}</text>')
    body.append(f'<text x="{cf.X(cb[3]) + 4:.1f}" y="{cf.Y(cb[2]) + 11:.1f}" class="co" style="fill:#1f4e8c">'
                f'pack up through the spring pawls</text>')
    steps = ["1  An empty tray drops from the nested magazine (escapement forks) onto the lane.",
             f"2  A delta sets each round cookie straight down into a round pocket: D{L['POCKET_D']:g} vs D{L['COOKIE'][0]:g} "
             f"= {(L['POCKET_D'] - L['COOKIE'][0]) / 2:.2f} mm radial clearance > {L['INDEX_ERR'] + L['DELTA_REP'] + L['CUP_ECC']:.2f} mm "
             f"placement error (lane index + delta + cup).",
             f"3  The full tray indexes under the top sealer: a heated head seals a peelable film onto the "
             f"{L['FLANGE']:g} mm flange in {L['SEAL_T']:g} s, inside the {L['T_INDEX']:g} s index.",
             f"4  The stacker lifts the sealed pack through spring pawls into the cassette's open bottom; the pawls "
             f"catch the flange ({L['PAWL']:g} mm) and hold the whole stack.",
             f"5  A full cassette ({cass_cap_txt()}) shuttles to the AMR port. Packs leave through the open top: the first "
             f"pack in has risen to the top, so retrieval is first in, first out.",
             "Proven on the exact CAD (line_cad.containment): every cookie sits in its pocket / tube and every stack on "
             "its pawls with zero overlap."]
    nb, _ = notes_block(30, 185, 195, steps, "HOW A ROUND COOKIE IS PACKED AND STORED")
    body.append(nb)
    return sheet(W, H, "\n".join(body), "P1 - Pack and cassette detail", "tray pockets, film seal, cassette inlet/outlet",
                 no, n, "1:1 / 1:4")


def cass_cap_txt():
    return f"{M.cass_cap()} packs = {M.cass_cap() * L['PACK']} cookies"


def layout_sheet(parts, trows, sim, n):
    W, H = 594, 420
    sc = 0.2
    bb = (0, 0, -10, L["TABLE"][0], L["TABLE"][1], 600)
    ox, oy = 25, 20 + 12 + L["TABLE"][1] * sc

    class _V(View):
        def __init__(s):
            super().__init__("TOP", parts, sc, ox, oy)
            s.bb = list(bb)
    top = _V()
    body = [f'<rect x="{ox}" y="{oy - L["TABLE"][1] * sc}" width="{L["TABLE"][0] * sc}" height="{L["TABLE"][1] * sc}" '
            f'fill="#f7f6f2" stroke="{INK}" stroke-width=".3"/>', top.svg().replace("TOP VIEW", "PLAN - WHOLE TABLE")]
    # flow arrows along the loop
    s = 60.0
    while s < M.loop_len():
        (x0, y0), _ = M.pos(s)
        (x1, y1), _ = M.pos(s + 25)
        body.append(f'<line x1="{top.X(x0):.1f}" y1="{top.Y(y0):.1f}" x2="{top.X(x1):.1f}" y2="{top.Y(y1):.1f}" '
                    f'stroke="{ACCENT}" stroke-width=".6" marker-end="url(#f)"/>')
        s += 160.0
    st = [("FEED", M.s_front(sum(L["MAG_X"]) / 6)), ("OVEN in", M.s_front(M.oven_x()[0])),
          ("OVEN out", M.s_front(M.oven_x()[1])), ("COOL out", M.s_front(M.cool_x()[1])),
          ("STAMP", M.s_front(L["STAMP_X0"])), ("QC", M.s_back(L["CAM_X"])), ("KICK", M.s_back(L["KICK_X"])),
          ("DELTA A", M.s_back(L["DELTA_X"][0])), ("DELTA B", M.s_back(L["DELTA_X"][1]))]
    s0 = st[0][1]
    for i, (nm, s_) in enumerate(st):
        (x, y), _ = M.pos(s_)
        front_run = y < M.L["CL"][1]
        ly = top.Y(y) + (14 + (i % 2) * 5 if front_run else -14 - (i % 2) * 5)
        body.append(f'<line x1="{top.X(x):.1f}" y1="{top.Y(y):.1f}" x2="{top.X(x):.1f}" y2="{ly:.1f}" class="col"/>'
                    f'<text x="{top.X(x) + 1:.1f}" y="{ly + (2 if front_run else -0.5):.1f}" class="co" '
                    f'style="font-size:2.6px;font-weight:700">{nm}  s={s_:.0f}  t=+{(s_ - s0) / L["V"]:.0f}s</text>')
    body.append(top.dim_h(0, L["TABLE"][0], 0, 8))
    body.append(top.dim_v(0, L["TABLE"][1], 0, -8))
    # module legend + timing + simulation
    x0 = ox + L["TABLE"][0] * sc + 14
    lines = [f"{m}: {d}" for m, d in M.MODULES.items()]
    nb, yy = notes_block(x0, 36, W - 10 - x0 - 4, lines, "MODULES")
    body.append(nb)
    tl = [f"{'OK' if ok else 'FAIL'}  {name}: {v} {lim}" for name, v, lim, ok, _ in trows]
    nb, yy = notes_block(x0, yy + 4, W - 10 - x0 - 4, tl, "TIMING PROOF (line_model.check)")
    body.append(nb)
    sl = [f"{k} ({v['hours']:.0f} h): eff {v['line_efficiency']:.2f}, burnt {v['burnt']}, "
          f"AMR util {v['amr_util']}, STOPS {v['stops']}" for k, v in sim.items()]
    nb, yy = notes_block(x0, yy + 4, W - 10 - x0 - 4, sl, "FLOW SIMULATION (line_sim.py)")
    body.append(nb)
    # AMR docking faces (the robots stay on the floor)
    for nm, (x, y) in (("AMR: cassettes out/in", (L["TABLE"][0] + 6, L["LANE_Y"][0])),
                       ("AMR: box stacks", (-150, L["LANE_Y"][-1] + 90)),
                       ("AMR: raw totes + reject drawer", (L["HOPPER_X"][0], -40))):
        body.append(f'<text x="{top.X(x):.1f}" y="{top.Y(y):.1f}" class="co" style="fill:#1f4e8c;font-weight:700">{esc(nm)}</text>')
    return sheet(W, H, "\n".join(body), "00 - General arrangement", "whole table, flow, stations, timing, simulation",
                 1, n, "1:5")


def book(files, trows, sim):
    rows = "".join(f"<tr><td>{'✅' if ok else '❌'}</td><td>{esc(n)}</td><td>{esc(v)}</td><td>{esc(l)}</td>"
                   f"<td>{esc(nt)}</td></tr>" for n, v, l, ok, nt in trows)
    srows = "".join(f"<tr><td>{esc(k)}</td><td>{v['hours']:.0f} h</td><td>{v['steady_state_per_h']:.0f}</td>"
                    f"<td>{v['line_efficiency']:.2f}</td><td>{v['burnt']}</td><td>{v['empty_slots']}</td>"
                    f"<td>{v['blocked_cassette']}/{v['blocked_boxes']}</td><td>{v['amr_tasks']}</td>"
                    f"<td>{v['amr_util']}</td><td>{v['amr_max_late_min']}</td><td>{v['stops']}</td></tr>"
                    for k, v in sim.items())
    sheets = "".join(f'<section><h3>{esc(os.path.splitext(f)[0])}</h3><img src="{esc(f)}" alt="{esc(f)}"/></section>'
                     for f in files)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>STF-2 Blueprint Book</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{font-family:system-ui,sans-serif;max-width:1200px;margin:0 auto;padding:16px;color:#1b2330;background:#fff}}
h1{{color:#1f4e8c}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{border-bottom:1px solid #dde;padding:4px 6px;text-align:left}}
img{{width:100%;border:1px solid #ccd;background:#fff}}section{{margin:24px 0}}code{{background:#f2f4f8;padding:1px 4px}}</style></head><body>
<h1>STF-2 — continuous tabletop cookie line</h1>
<p>Generated {DATE} from <code>line_model.py</code>. A redesign of the fischertechnik 536634 factory
for continuous, per-flavour production: one chain loop that never stops, every process on the fly,
no single robot in the critical path.</p>
<h2>Why redesign</h2>
<table><tr><th></th><th>536634 factory (today)</th><th>STF-2 continuous line</th></tr>
<tr><td>Flow</td><td>stop-and-go; every machine starts/stops per workpiece</td><td>one chain loop that never stops; takt {M.takt():.1f} s</td></tr>
<tr><td>Transfers</td><td>one VGR serves belt, oven and 3 bays (single point of failure)</td><td>fixed stations on the loop; two delta pickers, either alone carries the line (N+1)</td></tr>
<tr><td>Oven</td><td>batch: door, slider, one part at a time</td><td>tunnel oven: bake = length / speed ({M.oven_len():.0f} mm = {L['BAKE_S']:g} s)</td></tr>
<tr><td>Processing</td><td>turntable indexes under the saw</td><td>flying stamp slaved to the master axis ({M.stamp_cycle()[2]:.2f} s cycle)</td></tr>
<tr><td>Sorting / storage</td><td>colour sensor + ejectors into bays; 12-slot AS/RS</td><td>product carries its recipe (NFC); vision QC; per-flavour box lanes into tall pack cassettes, exchanged by AMR through an airlock</td></tr>
<tr><td>Stock</td><td>12 workpieces in the rack</td><td>raw hopper {M.hopper_cap()} + finished cassettes 2 x {M.cass_cap() * L['PACK']} per flavour; the AMR loop makes it unlimited (proven below)</td></tr>
<tr><td>Failure behaviour</td><td>any machine down = factory down</td><td>losses, never stops: a missed cookie recirculates, a starved flavour leaves an empty puck</td></tr></table>
<h2>Physical AI architecture</h2>
<ul>
<li><b>One time base.</b> The loop drive's encoder is the master axis; every station latches it (puck-edge sensors) and runs as its own agent on its own I/O node.</li>
<li><b>The product carries its recipe.</b> NFC tag per puck: flavour + batch written at the feeder, QC verdict at the hood, read before the pickers.</li>
<li><b>Vision QC</b> (CAM1 + ft colour sensor in a light-tight hood): flavour, burn, crack, size. Trained on images rendered from this CAD twin (sim-to-real), fine-tuned on the real line; verdict budget {L['AI_LATENCY']:g} s vs {(L['CAM_X'] - L['KICK_X']) / L['V']:.1f} s of travel to the kicker.</li>
<li><b>Tracking pickers</b> (CAM2 upstream): cookie pose + puck phase; the delta IK is part of this model and every pick/place point is proven reachable.</li>
<li><b>Health</b>: current + encoder per motor, zone thermocouples; anomalies feed the scheduler.</li>
<li><b>Self-throttling</b>: when both pickers report down, the feeder stops loading (the chain keeps running). Simulated: burnt scrap in a 10-min double outage falls from 91 to 26.</li>
<li><b>AMR fleet</b> ({L['N_AMR']}, N+1): every buffer raises a task with a deadline = the autonomy it has left; earliest deadline first; one visit per port serves all its pending tasks. Proven: ONE robot's worst case (all 10 port tasks queued) beats every deadline; simulated: one robot carries an 8 h shift, the fleet may vanish for 15 min without loss.</li>
</ul>
<h2>Packaging and storage - how a round cookie ends up in a rectangular pack</h2>
<ol>
<li>An empty <b>pocket tray</b> ({L['BOX'][0]:g} x {L['BOX'][1]:g} x {L['TRAY_H']:g}, {L['PACK']} round pockets D{L['POCKET_D']:g} x {L['POCKET_DEPTH']:g})
drops from a nested magazine (corner guides, escapement forks) onto the lane.</li>
<li>A delta sets each round cookie straight down into a round pocket: {(L['POCKET_D'] - L['COOKIE'][0]) / 2:.2f} mm radial
clearance against a {L['INDEX_ERR'] + L['DELTA_REP'] + L['CUP_ECC']:.2f} mm placement error budget.</li>
<li>The top sealer seals a peelable film on the {L['FLANGE']:g} mm flange during the lane index; the cookie stays 1 mm under it.
Twin film reels with auto-splice last {L['REELS'] * L['FILM_M'] * 1000 / (L['BOX'][0] + 10) * L['PACK'] / (M.rate_flavour() * 3600):.1f} h per lane.</li>
<li>The stacker pushes each sealed pack up through spring pawls into the <b>open bottom</b> of a hollow cassette; the pawls hold
the stack by its flange. The cassette's <b>top is open</b>: the first pack in has risen to the top, so packs leave first in,
first out. The lugs sit on the end walls so the outlet stays clear (checked).</li>
<li>A full cassette ({M.cass_cap()} packs) is carried into the out airlock; with the inner door locked the AMR swaps it for an empty one ({M.cass_swap_t():.0f} s, covered by the pack waiting on the stacker).</li>
</ol>
<p>Proven on the exact CAD (<code>line_cad.containment</code>): every cookie sits in its pocket or tube, every stack on its
pawls, zero overlap, and nothing blocks a cassette outlet. Negative tests (pocket too small, stack off its pawls, a handle
across the outlet) are all caught.</p>
<img src="../renders/pack_trays.png" alt="pocket trays with cookies"/>
<img src="../renders/pack_cassettes.png" alt="cassettes, front wall removed"/>
<h2>CAD</h2><p>One FreeCAD document + STEP per module and the assembly in
<code>~/workspace/stf-factory/cad/line2/</code> (built by <code>line_cad.py</code>).</p>
<img src="../renders/STF2_iso.png" alt="STF-2 assembly, isometric"/>
<h2>Open items (honest)</h2>
<ul>
<li>Every parameter tagged [assumed] (chain, delta arm lengths, pick time, bake/cool times, puck) must be validated on hardware.</li>
<li>A fleet outage longer than the shortest buffer (~17 min) runs the box magazines dry first: taller box magazines or a second box port are the next lever.</li>
<li>Short double-picker outages still scrap the cookies already in flight (feed -> pick is {(M.s_back(L['DELTA_X'][0]) - M.s_front(sum(L['MAG_X']) / 6)) / L['V']:.0f} s): add an overflow buffer lane or an oven bypass (next design step).</li>
<li>The delta arms are checked for reach, not yet swept for collision with the portal over the whole workspace; lane indexing is simplified (independent box spots).</li>
<li>Isometric pictorials are schematic (painter's order); the three orthographic views are exact.</li>
</ul>
<h2>Timing proof</h2><table><tr><th></th><th>check</th><th>value</th><th>limit</th><th>note</th></tr>{rows}</table>
<h2>Flow simulation (seeded; 1 h picker scenarios, 8 h stock + AMR shifts)</h2><table><tr><th>scenario</th><th>span</th>
<th>steady /h</th><th>efficiency</th><th>burnt</th><th>empty slots</th><th>blocked cass/box</th><th>AMR tasks</th>
<th>AMR util</th><th>max late (min)</th><th>stops</th></tr>{srows}</table>
<h2>Sheets</h2>{sheets}</body></html>"""


def main():
    fails = M.check(verbose=False)
    if fails:
        sys.exit("REFUSING to draw: " + "; ".join(fails[:5]))
    os.makedirs(OUT, exist_ok=True)
    trows, _ = M.timing()
    sim = json.load(open(os.path.join(HERE, "sim_results.json")))
    # the PC roof would hide the whole plan: views show the guard's walls, doors and devices only
    parts = [p for p in M.build() if not p.name.startswith("guard_panel_roof")]
    mods = M.by_module(parts)
    n = 2 + len(mods)
    files = ["00_layout.svg", "P1_packaging.svg"]
    open(os.path.join(OUT, files[0]), "w").write(layout_sheet(parts, trows, sim, n))
    open(os.path.join(OUT, files[1]), "w").write(packaging_sheet(parts, trows, 2, n))
    for i, (mod, ps) in enumerate(mods.items(), 3):
        fn = f"{mod}.svg"
        open(os.path.join(OUT, fn), "w").write(module_sheet(mod, ps, i, n, trows))
        files.append(fn)
    open(os.path.join(OUT, "index.html"), "w").write(book(files, trows, sim))
    print(f"wrote {len(files)} sheets + index.html to {OUT}")


if __name__ == "__main__":
    main()
