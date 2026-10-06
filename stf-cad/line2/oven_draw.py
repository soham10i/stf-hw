"""
The band oven made visible: temperature along the band, where the heat goes, how the power is distributed
over the 400 V phases, how long the oven takes to warm up - every number from oven.py through line_model.

  blueprints/M3_thermal.svg   A2 sheet: temperature profile + product colour along the band, element map with
                              phases, zone energy balance, phase loads, single-line diagram, warm-up curves
  oven/report.md              the same numbers as tables
  oven/profile.csv            the product history per second (t, x, segment, T top / core / bottom, water, colour)

Run: python3 oven_draw.py   (refuses to draw if the oven proofs fail)
"""
import csv
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hardware as H
import line_draw as D
import line_model as M
import oven as OV

L = M.L
OUT = os.path.join(HERE, "oven")
PH = M.PHASE_RGB
PHN = {"L1": "brown", "L2": "black", "L3": "grey"}
ITEM_C = dict(product="#c0562f", band="#8b9196", walls="#e0a02a", mouth="#1f63c4", exhaust="#6aa84f")


def esc(t):
    return D.esc(t)


def data():
    tb, tc = M.bake_t(), M.cool_t()
    st = M.stations()
    v = M.band_v()
    t_loop = (M.s_back(L["DELTA_X"][1]) - M.bend_s(L["TRANSFER_TH"][1])) / L["V"]
    tg, tn = M.band_gaps()
    tw = L["PICK_W"] / v
    trace, _ = OV.profile(L, tb, tc, [("pick window", tw, "loop"), ("loop", t_loop, "loop")], record=1.0, t_gap=tg, t_nose=tn)
    x_in = st["o0"] + L["CHAMBER"]["insul"]
    rows = []
    for r in trace:
        t = r[0]
        x = x_in + v * t if t <= tb + tg + tc + tn + tw + 1e-6 else None
        rows.append(dict(t=t, x=x, seg=r[1], top=r[2], core=r[3], bot=r[4], water=r[5], colour=r[6], q=r[7]))
    loads, els, plan, _ = M.oven_power()
    warm = OV.warmup(L, loads, els, M.band_w(), curves=True)
    return dict(tb=tb, tc=tc, st=st, v=v, rows=rows, loads=loads, els=els, plan=plan, warm=warm, t_loop=t_loop,
                bands=OV.band_temps(L, tb / len(L["OVEN_ZONES"])))


def axis_ticks(lo, hi, n=6):
    span = hi - lo
    step = 10 ** math.floor(math.log10(span / n))
    for m in (1, 2, 5, 10):
        if span / (step * m) <= n:
            step *= m
            break
    t = math.ceil(lo / step) * step
    out = []
    while t <= hi + 1e-9:
        out.append(t)
        t += step
    return out


class Plot:
    def __init__(self, x, y, w, h, xr, yr):
        self.x, self.y, self.w, self.h, self.xr, self.yr = x, y, w, h, xr, yr

    def px(self, v):
        return self.x + (v - self.xr[0]) / (self.xr[1] - self.xr[0]) * self.w

    def py(self, v):
        return self.y + self.h - (v - self.yr[0]) / (self.yr[1] - self.yr[0]) * self.h

    def frame(self, xlabel, ylabel, xt=None, yt=None):
        o = [f'<rect x="{self.x}" y="{self.y}" width="{self.w}" height="{self.h}" fill="none" stroke="{D.INK}" stroke-width=".25"/>']
        for t in (xt if xt is not None else axis_ticks(*self.xr)):
            X = self.px(t)
            o.append(f'<line x1="{X:.2f}" y1="{self.y + self.h}" x2="{X:.2f}" y2="{self.y + self.h + 1.2}" stroke="{D.INK}" stroke-width=".2"/>')
            o.append(f'<line x1="{X:.2f}" y1="{self.y}" x2="{X:.2f}" y2="{self.y + self.h}" stroke="#d9dde2" stroke-width=".12"/>')
            o.append(f'<text x="{X:.2f}" y="{self.y + self.h + 4}" class="dt" text-anchor="middle">{t:g}</text>')
        for t in (yt if yt is not None else axis_ticks(*self.yr)):
            Y = self.py(t)
            o.append(f'<line x1="{self.x - 1.2}" y1="{Y:.2f}" x2="{self.x}" y2="{Y:.2f}" stroke="{D.INK}" stroke-width=".2"/>')
            o.append(f'<line x1="{self.x}" y1="{Y:.2f}" x2="{self.x + self.w}" y2="{Y:.2f}" stroke="#d9dde2" stroke-width=".12"/>')
            o.append(f'<text x="{self.x - 2}" y="{Y + 0.8:.2f}" class="dt" text-anchor="end">{t:g}</text>')
        o.append(f'<text x="{self.x + self.w / 2}" y="{self.y + self.h + 8}" class="dt" text-anchor="middle">{esc(xlabel)}</text>')
        o.append(f'<text x="{self.x - 9}" y="{self.y + self.h / 2}" class="dt" text-anchor="middle" '
                 f'transform="rotate(-90 {self.x - 9} {self.y + self.h / 2})">{esc(ylabel)}</text>')
        return "\n".join(o)

    def line(self, pts, colour, w=.45, dash=""):
        d = " ".join(f"{'M' if i == 0 else 'L'}{self.px(a):.2f},{self.py(b):.2f}" for i, (a, b) in enumerate(pts))
        da = f' stroke-dasharray="{dash}"' if dash else ""
        return f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="{w}"{da}/>'


def legend(x, y, items):
    o = []
    for k, (label, c, kind) in enumerate(items):
        yy = y + k * 3.6
        if kind == "line":
            o.append(f'<line x1="{x}" y1="{yy}" x2="{x + 6}" y2="{yy}" stroke="{c}" stroke-width=".6"/>')
        elif kind == "dash":
            o.append(f'<line x1="{x}" y1="{yy}" x2="{x + 6}" y2="{yy}" stroke="{c}" stroke-width=".5" stroke-dasharray="1.2,.8"/>')
        else:
            o.append(f'<rect x="{x}" y="{yy - 1.4}" width="6" height="2.8" fill="{c}"/>')
        o.append(f'<text x="{x + 8}" y="{yy + 0.8}" class="dt">{esc(label)}</text>')
    return "\n".join(o)


def profile_panel(d, x0, y0, w, h):
    """Temperature along the band (x = machine coordinate), zones shaded, element map above, cookies below."""
    st, v = d["st"], d["v"]
    xa, xb = st["dep"] - 20, st["pick"][1] + 10
    P = Plot(x0, y0 + 32, w, h - 74, (xa, xb), (0, 240))
    o = [f'<text x="{x0}" y="{y0 + 3}" class="vt">A  TEMPERATURE ALONG THE BAND - what the cookie sees, x = machine position (mm)</text>']
    ins = L["CHAMBER"]["insul"]
    zl = M.zone_len()
    shade = ["#fde3d6", "#fbd0bb", "#f8bea1"]
    for k, Z in enumerate(L["OVEN_ZONES"]):
        a = st["zones"][k]
        o.append(f'<rect x="{P.px(a):.2f}" y="{P.y}" width="{P.px(a + zl) - P.px(a):.2f}" height="{P.h}" fill="{shade[k]}"/>')
        o.append(f'<text x="{P.px(a + zl / 2):.2f}" y="{P.y + 4}" class="nt" text-anchor="middle" style="font-weight:700">'
                 f'Z{k + 1}  {Z["T"]:g} C</text>')
    o.append(f'<rect x="{P.px(st["o0"]):.2f}" y="{P.y}" width="{P.px(st["o0"] + ins) - P.px(st["o0"]):.2f}" height="{P.h}" fill="#e6e8ea"/>')
    o.append(f'<rect x="{P.px(st["o1"] - ins):.2f}" y="{P.y}" width="{P.px(st["o1"]) - P.px(st["o1"] - ins):.2f}" height="{P.h}" fill="#e6e8ea"/>')
    o.append(f'<rect x="{P.px(st["c0"]):.2f}" y="{P.y}" width="{P.px(st["c1"]) - P.px(st["c0"]):.2f}" height="{P.h}" fill="#dbe9f6"/>')
    o.append(f'<text x="{P.px((st["c0"] + st["c1"]) / 2):.2f}" y="{P.y + 4}" class="nt" text-anchor="middle" style="font-weight:700">'
             f'impingement cooling {L["COOLING"]["band"]["h_top"]:g}/{L["COOLING"]["band"]["h_bot"]:g} W/m2K</text>')
    o.append(f'<rect x="{P.px(st["pick"][0]):.2f}" y="{P.y}" width="{P.px(st["pick"][1]) - P.px(st["pick"][0]):.2f}" height="{P.h}" fill="#e3f1e0"/>')
    o.append(f'<text x="{P.px(sum(st["pick"]) / 2):.2f}" y="{P.y + 4}" class="nt" text-anchor="middle">delta C</text>')
    for nm, x in (("depositor", st["dep"]), ("topping", st["top"])):
        o.append(f'<line x1="{P.px(x):.2f}" y1="{P.y}" x2="{P.px(x):.2f}" y2="{P.y + P.h}" stroke="#7d8790" stroke-width=".25" stroke-dasharray="1,1"/>')
        o.append(f'<text x="{P.px(x) + 1:.2f}" y="{P.y + 8}" class="dt">{nm}</text>')
    o.append(P.frame("band position x (mm)  -  band speed %.3f mm/s, so 100 mm = %.0f s" % (v, 100 / v), "temperature (C)"))
    # zone air (step) + band
    air = [(xa, L["T_AMB"]), (st["o0"], L["T_AMB"])]
    for k, Z in enumerate(L["OVEN_ZONES"]):
        a = st["zones"][k]
        air += [(a, Z["T"]), (a + zl, Z["T"])]
    air += [(st["o1"], L["T_AMB"]), (xb, L["T_AMB"])]
    o.append(P.line(air, "#b03a2e", .35, "1.6,.9"))
    tau = L["BAND"]["m_area"] * H.BAND_MESH["cp"] / (2 * L["OVEN_H"]["bot"])      # oven.band_temps, sampled
    bpts, Tb = [(st["dep"], L["T_AMB"]), (st["zones"][0], L["T_AMB"])], L["T_AMB"]
    for k, Z in enumerate(L["OVEN_ZONES"]):
        T0 = Tb
        for j in range(1, 21):
            dx = zl * j / 20
            Tb = Z["T"] - (Z["T"] - T0) * math.exp(-dx / v / tau)
            bpts.append((st["zones"][k] + dx, Tb))
    o.append(P.line(bpts, "#8b9196", .3, ".8,.6"))
    pre = [(st["dep"], L["T_AMB"]), (st["o0"] + ins, L["T_AMB"])]
    for key, c in (("top", "#c0392b"), ("core", "#7a4a1d"), ("bot", "#e08e2b")):
        pts = list(pre) + [(r["x"], r[key]) for r in d["rows"] if r["x"] is not None and r["x"] <= xb]
        o.append(P.line(pts, c, .55))
    # water (right axis 0..20 %)
    W = Plot(P.x, P.y, P.w, P.h, P.xr, (0, 0.20))
    wpts = [(st["dep"], L["DOUGH"]["w0"]), (st["o0"] + ins, L["DOUGH"]["w0"])] + \
        [(r["x"], r["water"]) for r in d["rows"] if r["x"] is not None and r["x"] <= xb]
    o.append(W.line(wpts, "#1f63c4", .4, "2,1"))
    for t in (0, 5, 10, 15, 20):
        Y = W.py(t / 100)
        o.append(f'<text x="{P.x + P.w + 2}" y="{Y + 0.8:.2f}" class="dt" style="fill:#1f63c4">{t}%</text>')
    o.append(f'<text x="{P.x + P.w + 9}" y="{P.y + P.h / 2}" class="dt" text-anchor="middle" style="fill:#1f63c4" '
             f'transform="rotate(90 {P.x + P.w + 9} {P.y + P.h / 2})">water in the cookie (wet basis)</text>')
    # element map above the plot: top elements on one line, bottom on the next, phase-coloured
    for face, yy in (("top", y0 + 9), ("bot", y0 + 18)):
        o.append(f'<text x="{x0 - 1}" y="{yy + 1}" class="dt" text-anchor="end">{face} elements</text>')
        for k in range(len(L["OVEN_ZONES"])):
            for e, x in M.element_x(k, face):
                ph = next(p for p, items in d["plan"].items() if any(t == e["tag"] for t, _ in items))
                X = P.px(x)
                o.append(f'<rect x="{X - 2.2:.2f}" y="{yy - 2.4}" width="4.4" height="4.8" rx=".6" fill="{PH[ph]}"/>')
                o.append(f'<text x="{X:.2f}" y="{yy + 5.2}" class="dt" text-anchor="middle" style="font-size:1.7px">'
                         f'{e["tag"]} {e["P"]:.0f}W {ph}</text>')
    for k in range(len(L["OVEN_ZONES"])):
        X = P.px(st["zones"][k] + zl / 2)
        o.append(f'<circle cx="{X:.2f}" cy="{y0 + 26}" r="1.6" fill="none" stroke="#5b6168" stroke-width=".3"/>'
                 f'<text x="{X + 2.4:.2f}" y="{y0 + 26.8}" class="dt" style="font-size:1.7px">fan QF{k + 1} ({H.OVEN_FAN["P"]:g} W)</text>')
    # the cookies themselves, coloured by oven.py, one per row pitch
    yc = P.y + P.h + 22
    o.append(f'<text x="{x0 - 1}" y="{yc + 1}" class="dt" text-anchor="end">the cookie</text>')
    x = st["dep"]
    sp = L["BAND"]["spacing"]
    while x <= st["pick"][1]:
        dd, hh, col, topped = M.band_state((x - st["dep"]) / v)
        r = dd / 2 * P.w / (xb - xa)
        o.append(f'<circle cx="{P.px(x):.2f}" cy="{yc}" r="{r:.2f}" fill="{col}" stroke="#5b4a30" stroke-width=".12"/>')
        if topped:
            o.append(f'<circle cx="{P.px(x):.2f}" cy="{yc}" r="{r * L["TOPPING"]["d"] / dd:.2f}" fill="{L["BAKED"][1]}"/>')
        x += sp
    o.append(legend(x0 + w - 150, y0 + 40, [("zone air set point", "#b03a2e", "dash"), ("mesh band", "#8b9196", "dash"),
                                           ("cookie top surface", "#c0392b", "line"), ("cookie core", "#7a4a1d", "line"),
                                           ("cookie bottom", "#e08e2b", "line"), ("water (right axis)", "#1f63c4", "dash")]))
    o.append(legend(x0 + w - 115, y0 + 40, [(f"{p} {PHN[p]}", PH[p], "box") for p in ("L1", "L2", "L3")]))
    return "\n".join(o)


def energy_panel(d, x0, y0, w, h):
    o = [f'<text x="{x0}" y="{y0 + 3}" class="vt">B  WHERE THE HEAT GOES (steady, {3600 / M.takt():.0f} cookies/h)</text>']
    loads, els = d["loads"], d["els"]
    inst = {z["zone"]: sum(e["P"] for e in els if e["zone"] == z["zone"]) for z in loads}
    top = max(inst.values()) * 1.1
    P = Plot(x0 + 12, y0 + 10, w - 16, h - 24, (0, len(loads)), (0, top))
    o.append(P.frame("zone", "power (W)", xt=[], yt=axis_ticks(0, top)))
    bw = P.w / len(loads) * 0.5
    for k, z in enumerate(loads):
        xc = P.px(k + 0.5)
        y = 0.0
        for item in ("product", "band", "walls", "mouth", "exhaust"):
            val = max(0.0, z[item])
            if val <= 0:
                continue
            o.append(f'<rect x="{xc - bw / 2:.2f}" y="{P.py(y + val):.2f}" width="{bw:.2f}" height="{P.py(y) - P.py(y + val):.2f}" '
                     f'fill="{ITEM_C[item]}"/>')
            if P.py(y) - P.py(y + val) > 3:
                o.append(f'<text x="{xc:.2f}" y="{(P.py(y) + P.py(y + val)) / 2 + .8:.2f}" class="dt" text-anchor="middle" '
                         f'style="fill:#fff;font-size:1.9px">{val:.0f}</text>')
            y += val
        ins_ = inst[z["zone"]]
        o.append(f'<line x1="{xc - bw / 2 - 2:.2f}" y1="{P.py(ins_):.2f}" x2="{xc + bw / 2 + 2:.2f}" y2="{P.py(ins_):.2f}" stroke="{D.INK}" stroke-width=".4"/>')
        o.append(f'<line x1="{xc - bw / 2 - 2:.2f}" y1="{P.py(L["HEADROOM"] * ins_):.2f}" x2="{xc + bw / 2 + 2:.2f}" '
                 f'y2="{P.py(L["HEADROOM"] * ins_):.2f}" stroke="{D.INK}" stroke-width=".25" stroke-dasharray="1,.7"/>')
        o.append(f'<text x="{xc:.2f}" y="{P.py(ins_) - 1:.2f}" class="dt" text-anchor="middle">installed {ins_:.0f} W</text>')
        o.append(f'<text x="{xc:.2f}" y="{P.y + P.h + 4}" class="dt" text-anchor="middle" style="font-weight:700">'
                 f'{z["zone"]} {z["T"]:g} C  ({z["total"] / ins_:.0%})</text>')
    o.append(legend(x0 + 14, y0 + h - 4 + 3, []))
    items = [(k, ITEM_C[k], "box") for k in ("product", "band", "walls", "mouth", "exhaust")] + \
        [(f"installed / {L['HEADROOM']:.0%} limit", D.INK, "dash")]
    o.append(legend(P.x + P.w - 30, P.y + 4, items))
    return "\n".join(o)


def phase_panel(d, x0, y0, w, h):
    S = H.SUPPLY
    o = [f'<text x="{x0}" y="{y0 + 3}" class="vt">C  400 V 3N~ - LOAD PER PHASE (every element on)</text>']
    lim = S["load_max"] * S["I"]
    P = Plot(x0 + 12, y0 + 10, w - 16, h - 24, (0, 3), (0, S["I"]))
    o.append(P.frame("phase", "current (A)", xt=[], yt=[0, 4, 8, 12, 16]))
    bw = P.w / 3 * 0.5
    zc = {"E1": "#c0562f", "E2": "#d98a5a", "E3": "#ecb28c", "QF": "#5b6168"}
    for k, ph in enumerate(("L1", "L2", "L3")):
        xc = P.px(k + 0.5)
        y = 0.0
        for tag, W in sorted(d["plan"][ph]):
            a = W / S["U"]
            c = zc.get(tag[:2], "#999")
            o.append(f'<rect x="{xc - bw / 2:.2f}" y="{P.py(y + a):.2f}" width="{bw:.2f}" height="{P.py(y) - P.py(y + a):.2f}" '
                     f'fill="{c}" stroke="#fff" stroke-width=".2"/>')
            if P.py(y) - P.py(y + a) > 2.4:
                o.append(f'<text x="{xc:.2f}" y="{(P.py(y) + P.py(y + a)) / 2 + .7:.2f}" class="dt" text-anchor="middle" '
                         f'style="fill:#fff;font-size:1.7px">{tag} {W:.0f} W</text>')
            y += a
        o.append(f'<rect x="{xc - bw / 2 - 1.5:.2f}" y="{P.y + P.h + 1.2}" width="{bw + 3:.2f}" height="1.4" fill="{PH[ph]}"/>')
        o.append(f'<text x="{xc:.2f}" y="{P.y + P.h + 5.5}" class="dt" text-anchor="middle" style="font-weight:700">{ph}: {y:.1f} A</text>')
    o.append(f'<line x1="{P.x}" y1="{P.py(lim):.2f}" x2="{P.x + P.w}" y2="{P.py(lim):.2f}" stroke="#b03a2e" stroke-width=".35" stroke-dasharray="1.4,.8"/>')
    o.append(f'<text x="{P.x + P.w - 1}" y="{P.py(lim) - 1:.2f}" class="dt" text-anchor="end" style="fill:#b03a2e">'
             f'{S["load_max"]:.0%} of the {S["I"]:g} A CEE supply</text>')
    return "\n".join(o)


def single_line(d, x0, y0, w, h):
    """Single-line diagram: CEE 16 A -> main switch + RCD -> K3/K4 (TwinSAFE) -> zone MCB -> KHn (STB in its
    coil) -> one SSR per element -> element on its phase; the zone fan on a coupling relay."""
    o = [f'<text x="{x0}" y="{y0 + 3}" class="vt">D  POWER DISTRIBUTION (single line)</text>']

    def box(x, y, bw, bh, t1, t2="", fill="#fff"):
        s = f'<rect x="{x:.2f}" y="{y:.2f}" width="{bw}" height="{bh}" fill="{fill}" stroke="{D.INK}" stroke-width=".25" rx=".6"/>'
        s += f'<text x="{x + bw / 2:.2f}" y="{y + bh / 2 - (0.4 if t2 else -0.8):.2f}" class="dt" text-anchor="middle" style="font-weight:700">{esc(t1)}</text>'
        if t2:
            s += f'<text x="{x + bw / 2:.2f}" y="{y + bh / 2 + 2.6:.2f}" class="dt" text-anchor="middle" style="font-size:1.8px">{esc(t2)}</text>'
        return s

    def ln(x1, y1, x2, y2, c=D.INK, wd=.35):
        return f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{c}" stroke-width="{wd}"/>'

    S = H.SUPPLY
    yy = y0 + 8
    bw, bh = 34, 8
    cx = x0 + 2
    o.append(box(cx, yy, bw, bh, "X0  CEE 16 A 5-pole", "400 V 3N~ 50 Hz"))
    o.append(ln(cx + bw, yy + bh / 2, cx + bw + 5, yy + bh / 2))
    o.append(box(cx + bw + 5, yy, bw, bh, "-QB0 main switch", "+ RCD 30 mA type A"))
    o.append(ln(cx + 2 * bw + 5, yy + bh / 2, cx + 2 * bw + 10, yy + bh / 2))
    o.append(box(cx + 2 * bw + 10, yy, bw + 6, bh, "-QK3 + -QK4 (TwinSAFE)", "SF1: E-stop drops the oven feed", "#fff4d6"))
    xbus = cx + 3 * bw + 16
    o.append(ln(xbus, yy + bh / 2, xbus + 4, yy + bh / 2))
    zs = list(enumerate(L["OVEN_ZONES"]))
    span = h - 26
    rowh = span / len(zs)
    o.append(ln(xbus + 4, yy + bh / 2, xbus + 4, yy + 10 + (len(zs) - 0.5) * rowh))
    phase_of = {t: p for p, items in d["plan"].items() for t, _ in items}
    for k, Z in zs:
        zy = yy + 12 + k * rowh
        o.append(ln(xbus + 4, zy + 4, xbus + 8, zy + 4))
        o.append(box(xbus + 8, zy, 22, 8, f"-FC{10 + k}", "3-pole C16"))
        o.append(ln(xbus + 30, zy + 4, xbus + 34, zy + 4))
        o.append(box(xbus + 34, zy, 24, 8, f"-QKH{k + 1}", f"coil via STB Z{k + 1}", "#fff4d6"))
        o.append(ln(xbus + 58, zy + 4, xbus + 62, zy + 4))
        els = [e for e in d["els"] if e["zone"] == f"Z{k + 1}"]
        n = len(els) + 1
        for j, e in enumerate(els + [None]):
            ey = zy - 1 + j * (rowh - 4) / n
            o.append(ln(xbus + 62, zy + 4, xbus + 62, ey + 2.5) + ln(xbus + 62, ey + 2.5, xbus + 66, ey + 2.5))
            if e is None:
                o.append(box(xbus + 66, ey, 26, 5, f"-KAQF{k + 1} relay", "", "#f3f4f5"))
                o.append(ln(xbus + 92, ey + 2.5, xbus + 96, ey + 2.5))
                o.append(box(xbus + 96, ey, 30, 5, f"fan QF{k + 1} {H.OVEN_FAN['P']:g} W"))
                ph = phase_of[f"QF{k + 1}"]
            else:
                o.append(box(xbus + 66, ey, 26, 5, f"-QA{e['tag']} SSR 25 A", "", "#f3f4f5"))
                o.append(ln(xbus + 92, ey + 2.5, xbus + 96, ey + 2.5))
                o.append(box(xbus + 96, ey, 30, 5, f"{e['tag']} {e['P']:.0f} W ({e['face']})"))
                ph = phase_of[e["tag"]]
            o.append(f'<rect x="{xbus + 127:.2f}" y="{ey + .6:.2f}" width="7" height="3.8" rx=".5" fill="{PH[ph]}"/>'
                     f'<text x="{xbus + 130.5:.2f}" y="{ey + 3.2:.2f}" class="dt" text-anchor="middle" style="fill:#fff;font-size:1.8px">{ph}</text>')
        o.append(f'<text x="{xbus + 8}" y="{zy + 11}" class="dt" style="font-size:1.8px">Z{k + 1} {Z["T"]:g} C: PID on TC{k + 1}, '
                 f'2 s time-proportioning PWM to the SSRs</text>')
    return "\n".join(o)


def warm_panel(d, x0, y0, w, h):
    o = [f'<text x="{x0}" y="{y0 + 3}" class="vt">E  WARM-UP FROM COLD (all elements on)</text>']
    tmax = max(t for _, t, _, _ in d["warm"]) / 60 * 1.15
    P = Plot(x0 + 12, y0 + 10, w - 16, h - 24, (0, tmax), (0, 240))
    o.append(P.frame("time (min)", "zone air (C)"))
    cols = ["#b03a2e", "#d98a5a", "#e0a02a"]
    for k, (z, t, Pw, cur) in enumerate(d["warm"]):
        o.append(P.line([(a / 60, b) for a, b in cur], cols[k], .5))
        o.append(f'<text x="{P.px(t / 60) + 1:.2f}" y="{P.py(cur[-1][1]) - 1:.2f}" class="dt" style="fill:{cols[k]}">'
                 f'{z} {t / 60:.0f} min ({Pw:.0f} W)</text>')
    o.append(f'<line x1="{P.px(L["WARMUP_MAX"] / 60):.2f}" y1="{P.y}" x2="{P.px(L["WARMUP_MAX"] / 60):.2f}" y2="{P.y + P.h}" '
             f'stroke="#b03a2e" stroke-width=".3" stroke-dasharray="1.2,.8"/>' if L["WARMUP_MAX"] / 60 <= tmax else "")
    return "\n".join(o)


def notes(d):
    loads, els = d["loads"], d["els"]
    tot = sum(z["total"] for z in loads)
    inst = sum(e["P"] for e in els) + 3 * H.OVEN_FAN["P"]
    _, s = OV.simulate(L, OV.bake_segments(L, d["tb"]), record=1e9)
    return [
        f"Recipe: zones {' / '.join(f'{z['T']:g}' for z in L['OVEN_ZONES'])} C, impingement {L['OVEN_H']['top']:g} W/m2K "
        f"top / {L['OVEN_H']['bot']:g} through the mesh; bake {d['tb']:.0f} s = {M.zone_len():.0f} mm per zone at "
        f"{d['v']:.3f} mm/s.",
        f"Result (oven.py): core held at >= {L['BAKE_Q']['core_min']:g} C for {s['core_hold']:.0f} s, water "
        f"{L['DOUGH']['w0']:.0%} -> {s['moisture']:.1%}, top colour index {s['colour']:.2f} (1.0 = golden).",
        f"The core sits at 100 C while it still holds water: the heat goes into evaporation (the flat part of the "
        f"core curve) - that is why a thin cookie bakes in minutes and the old 20 mm puck never could.",
        f"Steady heat {tot:.0f} W ({tot * M.takt() / 3600:.2f} Wh per cookie); installed {inst:.0f} W in {len(els)} tubular "
        f"elements + 3 fans; zone 1 carries {loads[0]['total'] / tot:.0%} - it heats the cold dough and the cold band.",
        f"Each element has its own SSR; each zone has a 3-pole C16, a zone contactor KHn whose coil runs through the "
        f"zone's STB (SF4, own thermocouple element) and the line contactors K3/K4 (SF1) upstream.",
        f"Outer skin <= {max(z['skin'] for z in loads):.0f} C ({L['CHAMBER']['insul']:g} mm mineral wool); the puck chain "
        f"runs under the oven floor and never sees the heat.",
        "All food data are [assumed] - MEASURE on the first bake: dough water, conductivities, the Maillard constants, "
        "and the heat-transfer coefficients of the fans (oven.py header).",
    ]


def write_csv(d):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "profile.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["t_s", "x_mm", "segment", "T_top_C", "T_core_C", "T_bottom_C", "water_wb", "colour_index", "q_in_W"])
        for r in d["rows"]:
            wr.writerow([f"{r['t']:.0f}", "" if r["x"] is None else f"{r['x']:.1f}", r["seg"], f"{r['top']:.1f}",
                         f"{r['core']:.1f}", f"{r['bot']:.1f}", f"{r['water']:.4f}", f"{r['colour']:.3f}", f"{r['q']:.2f}"])


def write_report(d):
    S = H.SUPPLY
    lines = ["# STF-2 band oven - heat and power (generated by oven_draw.py from oven.py)", ""]
    lines += [f"- {n}" for n in notes(d)] + ["", "## Zones", "",
                                              "| zone | set C | length mm | product W | band W | walls W | mouths W | exhaust W | "
                                              "total W | installed W | load | skin C |", "|" + "---|" * 12]
    for z in d["loads"]:
        inst = sum(e["P"] for e in d["els"] if e["zone"] == z["zone"])
        lines.append(f"| {z['zone']} | {z['T']:g} | {z['len_mm']:.0f} | {z['product']:.0f} | {z['band']:.0f} | {z['walls']:.0f} | "
                     f"{z['mouth']:.0f} | {z['exhaust']:.0f} | {z['total']:.0f} | {inst:.0f} | {z['total'] / inst:.0%} | {z['skin']:.0f} |")
    lines += ["", "## Elements and phases", "", "| tag | zone | face | W | W/cm2 | phase | catalogue |", "|---|---|---|---|---|---|---|"]
    ph = {t: p for p, items in d["plan"].items() for t, _ in items}
    for e in d["els"]:
        lines.append(f"| {e['tag']} | {e['zone']} | {e['face']} | {e['P']:.0f} | {e['load_Wcm2']:.2f} | {ph[e['tag']]} | {e['cat']['model']} |")
    lines += ["", "## 400 V supply", "", "| phase | loads | W | A |", "|---|---|---|---|"]
    for p, items in d["plan"].items():
        W = sum(w for _, w in items)
        lines.append(f"| {p} | {', '.join(t for t, _ in items)} | {W:.0f} | {W / S['U']:.2f} |")
    lines += ["", "## Warm-up", ""] + [f"- {z}: {t / 60:.1f} min with {P:.0f} W" for z, t, P, _ in d["warm"]]
    open(os.path.join(OUT, "report.md"), "w").write("\n".join(lines) + "\n")


def main():
    rows, fails = M.oven_proofs()
    if fails:
        print("REFUSED - the oven proofs fail:\n" + "\n".join(fails))
        return 1
    d = data()
    W, Hh = 594, 420
    body = [profile_panel(d, 26, 16, 548, 190)]
    body.append(energy_panel(d, 20, 214, 140, 96))
    body.append(phase_panel(d, 170, 214, 110, 96))
    body.append(warm_panel(d, 20, 318, 140, 92))
    body.append(single_line(d, 292, 214, 290, 150))
    nb, _ = D.notes_block(170, 322, 118, notes(d), "WHAT THE SHEET SAYS")
    body.append(nb)
    svg = D.sheet(W, Hh, "\n".join(body), "M3 BAND OVEN - HEAT + POWER",
                  f"{len(d['els'])} elements, {sum(e['P'] for e in d['els']) / 1000:.1f} kW, 3 zones, 400 V 3N~ - oven.py",
                  "M3-T", "-", "charts (not to scale)")
    os.makedirs(D.OUT, exist_ok=True)
    open(os.path.join(D.OUT, "M3_thermal.svg"), "w").write(svg)
    write_csv(d)
    write_report(d)
    cf = control_sheet()
    print(f"wrote blueprints/M3_thermal.svg, blueprints/M3_control.svg, oven/report.md, oven/profile.csv "
          f"({len(d['rows'])} s of product history)")
    if cf:
        print("REFUSED - the control proofs fail:\n" + "\n".join(cf))
        return 1
    return 0



# ------------------------------------------------------------------ control sheet (upgrade O-2, oven_ctrl.py)
def control_sheet():
    import oven_ctrl as OC
    pl = OC.Plant()
    gains = OC.tune(pl)
    n = pl.n
    cols = ["#b03a2e", "#d98a5a", "#e0a02a"]
    full = lambda t: [1.0] * n
    sc = {
        "S1": OC.run(pl, gains, 2400.0, lambda t: [0.0] * n, T0=[L["T_AMB"]] * n, ramp=True, record=5.0),
        "S2": OC.run(pl, gains, 1500.0, OC.content_fn(), record=5.0),
        "S2pi": OC.run(pl, gains, 1500.0, OC.content_fn(), ff=False, record=5.0),
        "S3": OC.run(pl, gains, 2400.0, OC.content_fn((0.0, 600.0)), record=5.0),
        "S3pi": OC.run(pl, gains, 2400.0, OC.content_fn((0.0, 600.0)), ff=False, record=5.0),
        "S4": OC.run(pl, gains, 1500.0, full, fail=(0, max(e["P"] for e in pl.els if e["zone"] == "Z1"), 600.0), record=2.0),
        "S5": OC.run(pl, gains, 900.0, full, stuck=(0, 300.0), record=2.0),
    }
    # S6: the worst corner of the mismatch sweep - the PLC's model is 20 % off, the feed-forward learns
    mm = OC.CTRL["MM"]
    tp = OC.Mismatch(pl, 1 - mm["cf"], 1 + mm["lb"], 1 + mm["lp"], 1 - mm["pf"], 1 + mm["tf"])
    ad = OC.adapt0(n)
    h1 = OC.run(pl, gains, 3600.0, lambda t: [0.0] * n, T0=[L["T_AMB"]] * n, ramp=True, true=tp, adapt=ad)
    h2 = OC.run(pl, gains, 3600.0, OC.content_fn(), T0=h1["T"][-1], true=tp, adapt=ad)
    sc["S6"] = OC.run(pl, gains, 2400.0, OC.content_fn((0.0, 600.0)), T0=h2["T"][-1], true=tp, adapt=ad, I0=h2["I"],
                      record=5.0)
    r1 = OC.run(pl, gains, 3600.0, lambda t: [0.0] * n, T0=[L["T_AMB"]] * n, ramp=True, true=tp, learn=False)
    r2 = OC.run(pl, gains, 3600.0, OC.content_fn(), T0=r1["T"][-1], true=tp, learn=False, I0=r1["I"])
    sc["S6raw"] = OC.run(pl, gains, 2400.0, OC.content_fn((0.0, 600.0)), T0=r2["T"][-1], true=tp, learn=False,
                         I0=r2["I"], record=5.0)
    win = L["BAKE_MARGIN"]
    body = []

    def panel(x0, y0, w, h, title, h_, key, yr, yl, extra=None, dev=False, pi=None, pi_label="PI alone (no feed-forward)"):
        o = [f'<text x="{x0}" y="{y0 + 3}" class="vt">{esc(title)}</text>']
        tmax = h_["t"][-1] / 60
        P = Plot(x0 + 12, y0 + 9, w - 16, h - 22, (0, tmax), yr)
        o.append(P.frame("time (min)", yl))
        if dev:
            o.append(f'<rect x="{P.x}" y="{P.py(win):.2f}" width="{P.w}" height="{P.py(-win) - P.py(win):.2f}" fill="#e3f1e0"/>')
            o.append(f'<text x="{P.x + 1}" y="{P.py(win) - 0.8:.2f}" class="dt" style="fill:#3a7d32">bake window +-{win:g} K</text>')
        for k in range(n):
            if dev:
                pts = [(t / 60, r[k] - pl.Ts[k]) for t, r in zip(h_["t"], h_["T"])]
                if pi is not None:
                    o.append(P.line([(t / 60, min(max(r[k] - pl.Ts[k], yr[0]), yr[1])) for t, r in zip(pi["t"], pi["T"])],
                                    cols[k], .3, "1.2,.8"))
            else:
                pts = [(t / 60, r[k]) for t, r in zip(h_["t"], h_[key])]
            pts = [(a, min(max(b, yr[0]), yr[1])) for a, b in pts]
            o.append(P.line(pts, cols[k], .5))
        if extra:
            o.append(extra(P))
        o.append(legend(P.x + P.w - 30, P.y + 4, [(f"Z{k + 1} {pl.Ts[k]:g} C", cols[k], "line") for k in range(n)]
                        + ([(pi_label, "#888", "dash")] if pi else [])))
        return "\n".join(o)

    def s1_extra(P):
        return "".join(P.line([(t / 60, min(pl.Ts[k], L["T_AMB"] + OC.CTRL["RAMP"] * t / 60)) for t in sc["S1"]["t"]],
                              "#1f63c4", .25, ".8,.6") for k in range(n))

    big = max(pl.zel[0], key=lambda e: e["P"])

    def s4_extra(P):
        o = [f'<line x1="{P.px(10):.2f}" y1="{P.y}" x2="{P.px(10):.2f}" y2="{P.y + P.h}" stroke="#1b2330" stroke-width=".3"/>'
             f'<text x="{P.px(10) + 1:.2f}" y="{P.y + 4}" class="dt">{big["tag"]} opens</text>']
        at = min((a for a in sc["S4"]["alarm_t"] if a is not None), default=None)
        nt = sc["S4"]["ident"].get(big["tag"])
        if at and nt:
            o.append(f'<text x="{P.px(10) + 1:.2f}" y="{P.y + 8}" class="dt" style="fill:#b03a2e">phase current short: '
                     f'+{at - 600:.1f} s; named {big["tag"]}: +{nt - 600:.1f} s</text>'
                     f'<text x="{P.px(10) + 1:.2f}" y="{P.y + 12}" class="dt">then out of the zone model (power, gain)</text>')
        return "".join(o)

    def s5_extra(P):
        tt = sc["S5"]["trip_t"][0]
        o = [f'<line x1="{P.x}" y1="{P.py(OC.CTRL["STB_T"]):.2f}" x2="{P.x + P.w}" y2="{P.py(OC.CTRL["STB_T"]):.2f}" stroke="#b03a2e" stroke-width=".3" stroke-dasharray="1.2,.8"/>'
             f'<text x="{P.x + 1}" y="{P.py(OC.CTRL["STB_T"]) - 1:.2f}" class="dt" style="fill:#b03a2e">STB {OC.CTRL["STB_T"]:g} C (SF4)</text>',
             f'<line x1="{P.x}" y1="{P.py(OC.CTRL["T_LIMIT"]):.2f}" x2="{P.x + P.w}" y2="{P.py(OC.CTRL["T_LIMIT"]):.2f}" stroke="#1b2330" stroke-width=".3"/>'
             f'<text x="{P.x + 1}" y="{P.py(OC.CTRL["T_LIMIT"]) - 1:.2f}" class="dt">limit {OC.CTRL["T_LIMIT"]:g} C</text>',
             f'<line x1="{P.px(5):.2f}" y1="{P.y}" x2="{P.px(5):.2f}" y2="{P.y + P.h}" stroke="#1b2330" stroke-width=".3"/>'
             f'<text x="{P.px(5) + 1:.2f}" y="{P.y + P.h - 3}" class="dt">Z1 SSRs fail ON</text>']
        if tt:
            o.append(f'<line x1="{P.px(tt / 60):.2f}" y1="{P.y}" x2="{P.px(tt / 60):.2f}" y2="{P.y + P.h}" stroke="#b03a2e" stroke-width=".3"/>'
                     f'<text x="{P.px(tt / 60) + 1:.2f}" y="{P.y + P.h - 8}" class="dt" style="fill:#b03a2e">STB drops KH1</text>')
        return "".join(o)

    body.append(panel(20, 16, 180, 120, "S1 COLD START (empty band, ramp + ramp feed-forward)", sc["S1"], "y", (0, 240),
                      "TC (C)", s1_extra))
    body.append(panel(208, 16, 180, 120, "S2 PRODUCTION START (cold dough fills the zones)", sc["S2"], "T", (-25, 10),
                      "zone - set point (K)", dev=True, pi=sc["S2pi"]))
    body.append(panel(396, 16, 180, 120, "S3 DEPOSITOR STOPS 10 min, RESTARTS", sc["S3"], "T", (-25, 10),
                      "zone - set point (K)", dev=True, pi=sc["S3pi"]))
    body.append(panel(20, 146, 180, 120, f"S4 HEATER BREAK {big['tag']} (Z1 RIDES THROUGH ON N-1)", sc["S4"], "T", (-4, 3),
                      "zone - set point (K)", s4_extra, dev=True))
    body.append(panel(208, 146, 180, 120, "S5 Z1 SSRs STUCK ON -> STB", sc["S5"], "T", (150, 320), "zone air (C)", s5_extra))
    body.append(panel(20, 276, 180, 120, "S6 REAL OVEN 20 % OFF THE MODEL: S3 AFTER LEARNING", sc["S6"], "T", (-6, 6),
                      "zone - set point (K)", dev=True, pi=sc["S6raw"], pi_label="same oven, learning off"))
    body.append(f'<text x="208" y="282" class="vt">S6 CORNER</text>' + "".join(
        f'<text x="208" y="{290 + 5 * i}" class="dt">{esc(t_)}</text>' for i, t_ in enumerate([
            f"heat capacity x{1 - mm['cf']:g}, base losses x{1 + mm['lb']:g}, product load x{1 + mm['lp']:g},",
            f"element power x{1 - mm['pf']:g} (supply -5 %), TC lag x{1 + mm['tf']:g}; gains fixed (tuned on the model).",
            "Warm-up (empty band) learns W0, the first production hour learns a1:",
            "  " + ", ".join(f"Z{k + 1} W0 {ad['W0'][k]:+.0f} W a1 {ad['a1'][k]:.2f}" for k in range(n)),
            "FB_Oven keeps both PERSISTENT: the next start begins learned.",
            "The commissioning hour (before learning) is flagged by its bake log."])))
    rows, fails, _ = OC.check(verbose=False, write=False)
    lines = [f"{'OK' if ok else 'FAIL'} - {nm}: {v} ({lim})" for nm, v, lim, ok, _ in rows]
    lines += ["Model: one lumped node per zone (oven.capacity, oven.wall_loss / mouth_loss, the band and product loads "
              "of oven.zone_loads), zone-to-zone air exchange, TC lag. Assumed: ZONE_G, TC_TAU, the STB / limit "
              "temperatures - MEASURE (oven_ctrl.py header).",
              "FB_Oven runs exactly this: feed-forward of the band content (learned W0 / a1) + PI + anti-windup + "
              "set-point ramp + heater-break check on the phase currents (BC1-3); plc/FB_Oven.st carries the gains."]
    nb, _ = D.notes_block(400, 150, 172, lines, "PROOFS (oven_ctrl.py)")
    body.append(nb)
    svg = D.sheet(594, 420, "\n".join(body), "M3 OVEN CONTROL - ZONES IN TIME",
                  "learning feed-forward + PI per zone, heater break, 6 scenarios, STB - oven_ctrl.py", "M3-C", "-", "charts (not to scale)")
    open(os.path.join(D.OUT, "M3_control.svg"), "w").write(svg)
    return fails


if __name__ == "__main__":
    sys.exit(main())
