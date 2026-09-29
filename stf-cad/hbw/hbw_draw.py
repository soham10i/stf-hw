"""Orthographic sketches + BOM, generated from hbw_model (single source of numbers)."""
import json, html
from hbw_model import build, P, fork_allowed

GC = {  # group -> (fill, stroke)
    "mould": ("#9aa3ac", "#5c646c"), "cover": ("#606770", "#333"),
    "frame": ("#e8e6e1", "#9a958c"), "rack": ("#2b2b2f", "#000"),
    "workpiece": ("#f7f7f4", "#b8b4ad"), "rail": ("#d0342c", "#7d1e19"),
    "crane": ("#3a3a40", "#111"), "fork": ("#d0342c", "#7d1e19"),
    "conveyor": ("#4a4a52", "#1c1c20"), "control": ("#2e7d4f", "#17402a"),
}
SENSOR = "#1e9e5a"; MOTOR = "#111"

def _f(p, view):
    a = p.aabb()
    if view == "plan":   return a[0], a[1], a[3] - a[0], a[4] - a[1], a[5]   # x,y  (depth = z)
    if view == "front":  return a[0], a[2], a[3] - a[0], a[5] - a[2], a[4]   # x,z  (depth = y)
    return a[1], a[2], a[4] - a[1], a[5] - a[2], a[3]                        # y,z  (depth = x)

def svg(view, pose, title, w_mm, h_mm, flipy=True):
    parts = sorted(build(*pose), key=lambda p: _f(p, view)[4])
    M = 46; S = 1.0
    W, H = w_mm * S + 2 * M, h_mm * S + 2 * M
    o = [f'<svg viewBox="0 0 {W:.0f} {H:.0f}" xmlns="http://www.w3.org/2000/svg" '
         f'role="img" aria-label="{html.escape(title)}">']
    o.append('<style>.dim{stroke:#c0392b;stroke-width:.7;fill:none}'
             '.dt{font:10px ui-monospace,monospace;fill:#c0392b}'
             '.lb{font:9px ui-monospace,monospace;fill:#555}'
             '.gr{stroke:#e4e2dd;stroke-width:.5}</style>')
    def X(v): return M + v * S
    def Y(v): return M + (h_mm - v) * S if flipy else M + v * S
    # grid 60 mm
    for gx in range(0, int(w_mm) + 1, 60): o.append(f'<line class="gr" x1="{X(gx):.1f}" y1="{Y(0):.1f}" x2="{X(gx):.1f}" y2="{Y(h_mm):.1f}"/>')
    for gy in range(0, int(h_mm) + 1, 60): o.append(f'<line class="gr" x1="{X(0):.1f}" y1="{Y(gy):.1f}" x2="{X(w_mm):.1f}" y2="{Y(gy):.1f}"/>')
    for p in parts:
        a, b, dw, dh, _ = _f(p, view)
        f, s = GC.get(p.group, ("#888", "#333"))
        if p.tag and p.tag.startswith("I") or p.tag in ("A1", "A2"): f = SENSOR
        elif p.tag and p.tag.startswith("Q"): f = MOTOR
        if p.colour in ("white", "alu", "steel"): f = "#eceae5"
        if p.colour == "red": f = "#d0342c"
        if p.colour == "colour": f = "#2f6fd0"
        y0 = Y(b + dh) if flipy else Y(b)
        o.append(f'<rect x="{X(a):.1f}" y="{y0:.1f}" width="{dw*S:.1f}" height="{dh*S:.1f}" '
                 f'fill="{f}" fill-opacity=".85" stroke="{s}" stroke-width=".6"><title>'
                 f'{html.escape(p.name)} {p.s}{" [" + p.tag + "]" if p.tag else ""}</title></rect>')
    o.append(f'<rect x="{X(0):.1f}" y="{Y(h_mm):.1f}" width="{w_mm*S:.1f}" height="{h_mm*S:.1f}" '
             f'fill="none" stroke="#9a958c" stroke-width="1"/>')
    return o, X, Y

def dim(o, X, Y, x1, y1, x2, y2, text, off=0, vert=False):
    if vert:
        xx = X(x1) + off
        o.append(f'<path class="dim" d="M{X(x1)-4:.1f},{Y(y1):.1f}H{xx+4:.1f} M{X(x2)-4:.1f},{Y(y2):.1f}H{xx+4:.1f} M{xx:.1f},{Y(y1):.1f}V{Y(y2):.1f}"/>')
        o.append(f'<text class="dt" x="{xx+5:.1f}" y="{(Y(y1)+Y(y2))/2+3:.1f}">{text}</text>')
    else:
        yy = Y(y1) + off
        o.append(f'<path class="dim" d="M{X(x1):.1f},{Y(y1)-4:.1f}V{yy+4:.1f} M{X(x2):.1f},{Y(y2)-4:.1f}V{yy+4:.1f} M{X(x1):.1f},{yy:.1f}H{X(x2):.1f}"/>')
        o.append(f'<text class="dt" x="{(X(x1)+X(x2))/2:.1f}" y="{yy-4:.1f}" text-anchor="middle">{text}</text>')

def label(o, X, Y, x, y, t, anchor="start"):
    o.append(f'<text class="lb" x="{X(x):.1f}" y="{Y(y):.1f}" text-anchor="{anchor}">{html.escape(t)}</text>')

def plan(pose, title):
    o, X, Y = svg("plan", pose, title, 860, 640)
    dim(o, X, Y, 0, 0, 860, 0, "860", off=26)
    dim(o, X, Y, 45, 645, 555, 645, "510 rack", off=-14)
    dim(o, X, Y, 610, 645, 720, 645, "110 belt", off=-14)
    dim(o, X, Y, 0, 0, 0, 640, "640", off=-28, vert=True)
    label(o, X, Y, 8, 320, "rack  y 290..360")
    label(o, X, Y, 8, 216, "crane travel rail  y 210")
    label(o, X, Y, 440, 560, "conveyor + cover -> VGR")
    label(o, X, Y, 8, 30, "24V adapter PCB")
    return "".join(o) + "</svg>"

def front(pose, title):
    o, X, Y = svg("front", pose, title, 860, 580)
    for z, r in zip(P["ROW_Z"], "ABC"):
        dim(o, X, Y, 0, z, 0, z, "", off=0)
        label(o, X, Y, 8, z + 4, f"row {r}  z={z:.0f}")
    dim(o, X, Y, 860, 0, 860, 420, "420 rack", off=22, vert=True)
    dim(o, X, Y, 60, 560, 180, 560, "120 bay pitch", off=-14)
    dim(o, X, Y, 0, 120, 0, 240, "120", off=-30, vert=True)
    label(o, X, Y, 430, 570, "belt surface z=100", "middle")
    return "".join(o) + "</svg>"

def side(pose, title):
    o, X, Y = svg("side", pose, title, 640, 580)
    dim(o, X, Y, 290, 0, 360, 0, "70 bay depth", off=26)
    dim(o, X, Y, 0, 0, 640, 0, "640", off=44)
    dim(o, X, Y, 640, 0, 640, 420, "420", off=22, vert=True)
    label(o, X, Y, 300, 20, "conveyor + cover")
    label(o, X, Y, 295, 380, "rack")
    return "".join(o) + "</svg>"

def bom():
    rows = {}
    for p in build():
        key = (p.group, p.name.rstrip("0123456789_LR") or p.name)
        rows.setdefault(p.name, p)
    return [p for p in build()]

def factory_plan():
    """Top view of the whole table, matching the user's sketch."""
    import factory_layout as FL
    d = FL.doc(); fw, fh = d["plate"][0], d["plate"][1]
    M, S = 46, 0.42
    W, H = fw * S + 2 * M, fh * S + 2 * M
    X = lambda v: M + v * S
    Y = lambda v: M + (fh - v) * S
    o = [f'<svg viewBox="0 0 {W:.0f} {H:.0f}" xmlns="http://www.w3.org/2000/svg">',
         '<style>.dt{font:11px ui-monospace,monospace;fill:#c0392b}'
         '.lb{font:11px ui-monospace,monospace;fill:#444}'
         '.nn{font:600 15px ui-monospace,monospace;fill:#c0392b}</style>']
    o.append(f'<rect x="{X(0):.1f}" y="{Y(fh):.1f}" width="{fw*S:.1f}" height="{fh*S:.1f}" '
             'fill="#f2f3f4" stroke="#5a6169" stroke-width="1.4"/>')
    for n in d["neighbours"]:
        x, y, w, h = n["rect"]
        o.append(f'<rect x="{X(x):.1f}" y="{Y(y+h):.1f}" width="{w*S:.1f}" height="{h*S:.1f}" '
                 'fill="none" stroke="#9a958c" stroke-width="1.1" stroke-dasharray="6 4"/>')
        o.append(f'<text class="nn" x="{X(x)+8:.1f}" y="{Y(y+h)+20:.1f}">{n["n"]}</text>')
        o.append(f'<text class="lb" x="{X(x)+8:.1f}" y="{Y(y+h)+36:.1f}">{n["label"]}</text>')
    hx, hy, hw, hh = d["hbw_rect"]
    o.append(f'<rect x="{X(hx):.1f}" y="{Y(hy+hh):.1f}" width="{hw*S:.1f}" height="{hh*S:.1f}" '
             'fill="#e7e9ea" stroke="#5a6169" stroke-width="1.2"/>')
    # the built parts, in factory coordinates
    for p in build():
        if p.group in ("frame",):
            continue
        a = p.aabb()
        c0 = FL.to_factory(a[0], a[1]); c1 = FL.to_factory(a[3], a[4])
        x0, x1 = sorted((c0[0], c1[0])); y0, y1 = sorted((c0[1], c1[1]))
        f, st = GC.get(p.group, ("#888", "#333"))
        if p.tag: f = SENSOR
        if p.colour in ("red", "ftred"): f = "#d0342c"
        o.append(f'<rect x="{X(x0):.1f}" y="{Y(y1):.1f}" width="{(x1-x0)*S:.1f}" '
                 f'height="{(y1-y0)*S:.1f}" fill="{f}" fill-opacity=".8" stroke="{st}" '
                 f'stroke-width=".5"><title>{p.name}</title></rect>')
    for nn, lab, xx, yy in ((1, "PCB", 1130, 110), (2, "High-bay storage", 700, 330),
                            (3, "Conveyor", 620, 780), (4, "Picker rail", 1045, 460),
                            (5, "VGR", 300, 830)):
        o.append(f'<text class="nn" x="{X(xx):.1f}" y="{Y(yy):.1f}">{nn}</text>')
        o.append(f'<text class="lb" x="{X(xx)+14:.1f}" y="{Y(yy):.1f}">{lab}</text>')
    o.append(f'<text class="dt" x="{X(fw/2):.1f}" y="{Y(0)+26:.1f}" text-anchor="middle">'
             f'{fw:.0f} x {fh:.0f} mm</text>')
    return "".join(o) + "</svg>"


if __name__ == "__main__":
    out = {
        "plan_bay":  plan((240, 240, 115), "Plan - crane serving bay B2"),
        "plan_belt": plan((665, 100, 115), "Plan - crane at the conveyor hand-over"),
        "front":     front((240, 240, 115), "Front elevation"),
        "side":      side((240, 240, 115), "Side elevation"),
        "factory":   factory_plan(),
    }
    open("views.json", "w").write(json.dumps(out))
    parts = build()
    print(f"{len(parts)} solids, {len(set(p.group for p in parts))} groups")
    for g in ("frame","rack","workpiece","rail","crane","fork","conveyor","control"):
        gp=[p for p in parts if p.group==g]
        print(f"  {g:10s} {len(gp):3d}")
