"""
STF-2 electrical sheets, generated from plc_io (never drawn by hand).

  electrical/E01_power.svg        power distribution: mains -> breakers -> PSUs / SSRs -> loads,
                                  the E-stop relay (concept open), every budget from plc_io.power()
  electrical/E02_cabinet.svg      mounting plate 1:2.5 - DIN rows, ducts, every device at its x
  electrical/E03_ethercat.svg     EtherCAT line (CX2020 -> rail 1 -> EK1100 -> rail 2) + Ethernet
  electrical/E1n_terminals_*.svg  terminal plan: every EL channel -> tag -> part -> cable
  electrical/index.html           the sheet book

Run: python3 elec_draw.py   (refuses if plc_io.check() fails)
"""
import html
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hardware as H
import line_draw as D
import line_model as M
import plc_io as P

OUT = os.path.join(HERE, "electrical")
INK, ACC = D.INK, D.ACCENT
esc = D.esc
W, Hh = 420, 297


def t(x, y, s, cls="nt", anchor="start", extra=""):
    return f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" text-anchor="{anchor}" {extra}>{esc(s)}</text>'


def box(x, y, w, h, fill="#fff", stroke=INK, sw=0.3):
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'


def line(x0, y0, x1, y1, sw=0.35, col=INK, dash=""):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" stroke="{col}" stroke-width="{sw}"{d}/>'


def power_sheet(ios, prows, no, n):
    b = []
    y0 = 30
    b.append(t(20, 22, "POWER DISTRIBUTION (single line)", "nh"))
    # mains bus
    b.append(line(30, y0, 30, 250, 0.6))
    b.append(t(22, y0 - 2, "L1 / L2 / L3 / N / PE  400 V 3N~ (CEE 16 A, RCD 30 mA)", "tbs"))
    safe = any(io.kind in P.SAFE_KINDS for io in ios)
    n_step = sum(1 for io in ios if io.kind == "STEP")
    if safe:
        zs = P.zones()
        _, els, plan, _ = M.oven_power()
        phase = {tg: p for p, items in plan.items() for tg, _ in items}
        oz = []
        for k in range(len(M.L["OVEN_ZONES"])):
            e_ = [e for e in els if e["zone"] == f"Z{k + 1}"]
            oz.append(f"-FC{10 + k} C16 3p -> -QKH{k + 1} (coil via STB Z{k + 1}) -> " +
                      ", ".join(f"{e['tag']} {e['P']:.0f} W {phase[e['tag']]}" for e in e_) + f", fan QF{k + 1}")
        feeds = [("-QB0", "main switch 4-pole + RCD", None),
                 ("-QK3/4", "oven feed (TwinSAFE, series)", oz + ["each element on its own -QA SSR 25 A; "
                                                                   "details: blueprints/M3_thermal.svg"]),
                 ("-FC3", "C6 supplies", [f"-TB1 {P.LOGIC_PSU[0]}: 24 V logic + safety (PC, EL, EL69xx/19xx/29xx, "
                                          "sensors, coils, locks, curtains)",
                                          "-TB2 SDR-480-24 (L1, fed via -QK3/-QK4): 24 V heat -> DC SSR + STL -> "
                                          "Q36-38 sealing heads",
                                          f"-TB3 SDR-480P-48 -> -QK1 + -QK2 (series) -> {n_step} EL7047;",
                                          f"   branch -QK5: {', '.join(zs['boxes']['motors'])} (boxes port zone)",
                                          f"   branch -QK6: {', '.join(zs['out']['motors'])} (out port zone)"])]
    else:
        feeds = [("-FC1", "main 2-pole C16", None),
                 ("-FC2", "C10 heaters", ["-QA1 SSR -> Q8 IR 300 W", "-QA2 SSR -> Q9 IR 300 W", "-QA3 SSR -> Q10 IR 300 W"]),
                 ("-FC3", "C6 supplies", ["-TB120 SDR-120-24: 24 V logic (PC, EL, sensors, coils, fans, light, cab fan)",
                                         "-TB480 SDR-480-24: 24 V heat -> -QA4..7 DC SSR -> Q36-38 sealing heads, Q15 die",
                                         "-TB480P SDR-480P-48: 48 V motors -> 22x EL7047 (17 used) - cut by -KF90"])]
    y = y0 + 12
    for tag, note, loads in feeds:
        b.append(line(30, y, 60, y))
        b.append(box(60, y - 5, 26, 10, "#f3f5f8"))
        b.append(t(73, y + 1.2, tag, "tb", "middle"))
        b.append(t(90, y + 1.2, note, "tbs"))
        if loads:
            for k, ld in enumerate(loads):
                yy = y + 12 + k * 11
                b.append(line(73, y + 5, 73, yy))
                b.append(line(73, yy, 110, yy))
                b.append(box(110, yy - 4, 180, 8, "#fff"))
                b.append(t(113, yy + 1.2, ld, "tbs"))
            y += 12 + len(loads) * 11 + 6
        else:
            y += 16
    b.append(box(300, 40, 100, 44, "#fff4f2", "#c0392b"))
    if safe:
        b.append(t(303, 47, "TWINSAFE (EL6910 + EL1904 / EL2904)", "tb"))
        msg = ["SF1 E-stop, SF2 guard locking, SF3 exhaust, SF6 ports", "K1+K2 (48 V), K3+K4 (400 V oven) in series, EDM",
               "K5/K6 + Y1/Y2: AMR port zones", "SF4: STB per oven zone -> KHn coil (hardwired)", "see E04 + safety/report.md"]
    else:
        b.append(t(303, 47, "-KF90 E-STOP RELAY (PNOZ class)", "tb"))
        msg = ["2-channel E-stop chain -> S0 / S1 (EL1809)", "cuts the 48 V motor supply",
               "de-energises the FRL dump valve Q19 (safe exhaust)", "SAFETY CONCEPT OPEN: PL / category",
               "and stop category not yet assessed"]
    for k, s in enumerate(msg):
        b.append(t(303, 54 + k * 6, s, "tbs"))
    b.append(t(300, 100, "BUDGETS (plc_io.power, <= 80 % of every rating)", "nh"))
    for k, (name, v, lim, ok, note) in enumerate(prows):
        b.append(t(300, 106 + k * 5.2, f"{'OK ' if ok else 'FAIL'} {name}: {v}  {lim}", "tbs"))
    return D.sheet(W, Hh, "\n".join(b), "Electrical E01 - power distribution", "single line, derived from plc_io",
                   no, n, "none")


def safety_sheet(ios, no, n):
    """E04: the TwinSAFE functions, every safe input / output with its device and function."""
    import safety as S
    b = [t(20, 22, "SAFETY FUNCTIONS (TwinSAFE EL6910) - Upgrade S-1", "nh")]
    y = 30
    for sf, fn, inp, resp, stop, pl, diag in S.SF:
        b.append(t(20, y, f"{sf}  {fn}  (PLr {pl}, stop {stop})", "tb"))
        for line_ in (f"in:  {inp}", f"out: {resp}", f"diag: {diag}"):
            y += 4.4
            b.append(t(26, y, line_[:150], "tbs"))
        y += 6.5
    y += 2
    b.append(t(20, y, "SAFE I/O", "nh"))
    y += 6
    y0, col = y, 0
    off = [0, 10, 30, 56, 98]
    for io in sorted((io for io in ios if io.kind in P.SAFE_KINDS), key=lambda i: (i.kind, i.slot)):
        if y == y0:
            for c_, h_ in zip(off, ["kind", "tag", "terminal", "device / part", "function"]):
                b.append(t(20 + col * 195 + c_, y, h_, "tb"))
            y += 4.5
        vals = [io.kind, io.tag, io.slot, (io.part or io.hw)[:18] + ("" if io.cad else " [impl.]"), io.desc[:44]]
        for c_, v in zip(off, vals):
            b.append(t(20 + col * 195 + c_, y, v, "tbs"))
        y += 2.75
        if y > 248:
            col, y = col + 1, y0
            if col > 1:
                break
    return D.sheet(W, Hh, "\n".join(b), "Electrical E04 - safety", "TwinSAFE functions + safe I/O, from safety.py",
                   no, n, "none")


def cabinet_sheet(lay, dims, no, n):
    cx, cy, cw, cd, ch = M.L["CAB"]
    sc = 1 / 3.0
    ox, oy = 25, 30
    b = [t(20, 22, f"MOUNTING PLATE {cw:g} x {cd:g} (enclosure under the deck, height {ch:g}) - scale 1:3", "nh")]
    b.append(box(ox, oy, cw * sc, cd * sc, "#fafbfc", INK, 0.5))
    colours = {"MCB": "#e8d9a8", "SDR": "#c9d6e3", "SSR": "#f0c8c0", "safety": "#f7b0a8", "PT": "#e6e6e6",
               "contactor": "#f7b0a8", "STL": "#f7c9a0", "EL19": "#f2e28c", "EL29": "#f2e28c", "EL69": "#f2c200",
               "EL": "#d4e8d4", "CX": "#b8d0f0", "EK": "#b8d0f0"}
    for r in lay:
        yy = oy + (r["y"] - cy) * sc
        b.append(box(ox + 15 * sc, yy - 1, (cw - 30) * sc, H.RAIL["w"] * sc, "#ffffff", "#9aa3ab", 0.2))
        if r["row"] < len(lay) - 1:
            b.append(box(ox + 15 * sc, yy + r["h"] * sc + 1, (cw - 30) * sc, H.DUCT["w"] * sc - 2, "#eef1f4",
                         "#b9bec4", 0.2))
        for d in r["devices"]:
            col = next((c for k, c in colours.items() if d["type"].startswith(k) or k in d["type"]), "#dddddd")
            x = ox + (d["x"] - cx) * sc
            b.append(box(x, yy, d["w"] * sc, d["h"] * sc, col, INK, 0.15))
            if d["w"] >= 12 and not d["type"].startswith("PT"):
                b.append(f'<text x="{x + d["w"] * sc / 2:.1f}" y="{yy + 2:.1f}" class="tbs" '
                         f'transform="rotate(90 {x + d["w"] * sc / 2:.1f} {yy + 2:.1f})">{esc(d["name"] + " " + d["type"])}</text>')
        b.append(t(ox + cw * sc + 4, yy + 4, f"row {r['row']}: {r['width']:.0f} / {r['rail']:.0f} mm, "
                                                f"{r['spare']:.0%} spare", "tbs"))
    th = dims["thermal"]
    notes = [f"Rows use {dims['used_d']:.0f} of {dims['inner_d']:.0f} mm plate depth; every rail keeps >= 20 % spare.",
             f"Deepest device + rail {max(d['d'] for r in lay for d in r['devices']) + H.RAIL['h']:.0f} mm <= "
             f"{dims['inner_h']:.0f} mm inside height.",
             f"Heat {th['loss_W']} W: natural dT {th['dT_natural']} K > {H.THERMAL['dT_max']:g} K -> filter fan "
             f"{H.THERMAL['fan_m3h']:g} m3/h, dT {th['dT']} K.",
             "Ducts 40 x 60 between rows; field cables enter through glands in the front wall."]
    nb, _ = D.notes_block(ox + cw * sc + 4, oy + 150, 95, notes, "NOTES")
    b.append(nb)
    return D.sheet(W, Hh, "\n".join(b), "Electrical E02 - cabinet layout", "DIN rows from plc_io.cabinet()",
                   no, n, "1:3")


def ethercat_sheet(rails, no, n):
    b = [t(20, 22, "ETHERCAT LINE + ETHERNET", "nh")]
    x, y = 25, 40
    for r, rail in enumerate(rails):
        b.append(t(x, y - 6, f"rail {r + 1}", "tb"))
        for k, (typ, name, note) in enumerate(rail):
            w_ = 11.5
            xx = x + k * (w_ + 1)
            if xx + w_ > W - 20:
                y += 30
                x = 25 - k * (w_ + 1)
                xx = x + k * (w_ + 1)
            col = "#b8d0f0" if typ.startswith(("CX", "EK")) else ("#f3f5f8" if typ in ("EL9410", "EL9011") else "#d4e8d4")
            b.append(box(xx, y, w_, 22, col, INK, 0.2))
            b.append(f'<text x="{xx + 3:.1f}" y="{y + 2:.1f}" class="tbs" '
                     f'transform="rotate(90 {xx + 3:.1f} {y + 2:.1f})">{esc(typ)}</text>')
            b.append(f'<text x="{xx + 7.5:.1f}" y="{y + 2:.1f}" class="tbs" '
                     f'transform="rotate(90 {xx + 7.5:.1f} {y + 2:.1f})">{esc(name)}</text>')
        y += 40
        x = 25
    b.append(t(25, y + 4, "EtherCAT: CX2020 X000 -> rail 1 E-bus -> (EtherCAT out) -> EK1100 -> rail 2 E-bus. "
                          "E-bus current summed per rail; EL9410 refreshes where the 2 A budget runs out.", "tbs"))
    y += 16
    net = [("CX2020 X001", "Ethernet switch (managed, 5 port)"), ("switch", "edge AI PC (vision QC, tracking, twin)"),
           ("switch", "CAM1 QC camera (GigE, PoE)"), ("switch", "CAM2 tracking camera (GigE, PoE)"),
           ("edge PC <-> CX2020", "ADS: QC verdicts, pick poses, twin state (TwinCAT ADS router)")]
    for k, (a, bb) in enumerate(net):
        b.append(t(25, y + k * 6, f"{a}  ->  {bb}", "tbs"))
    return D.sheet(W, Hh, "\n".join(b), "Electrical E03 - EtherCAT + network", "topology from plc_io.terminals()",
                   no, n, "none")


def terminal_sheets(ios, wires, rails, start, n):
    by_term = defaultdict(list)
    wid = {w["tag"]: w for w in wires}
    for io in ios:
        if io.slot:
            name, ch = io.slot.split(" ch")
            by_term[name].append((int(ch), io))
    order = [(nm, typ) for rail in rails for typ, nm, _ in rail if nm in by_term or typ.startswith("EL") and nm]
    order = [(nm, typ) for nm, typ in order if typ in H.BECKHOFF and H.BECKHOFF[typ]["ch"] > 0]
    pages, cur, used = [], [], 0
    for nm, typ in order:
        rows = H.BECKHOFF[typ]["ch"] + 2
        if used + rows > 44:
            pages.append(cur)
            cur, used = [], 0
        cur.append((nm, typ))
        used += rows
    if cur:
        pages.append(cur)
    out = []
    for pi, pg in enumerate(pages):
        b = [t(20, 22, f"TERMINAL PLAN {pi + 1}/{len(pages)}", "nh")]
        y = 30
        cols = [20, 48, 70, 118, 185, 300, 330, 360]
        heads = ["terminal", "ch", "tag", "part", "description", "cable", "length", "cores"]
        for nm, typ in pg:
            b.append(box(18, y - 4, 384, 5.5, "#f3f5f8", INK, 0.15))
            b.append(t(20, y, f"{nm}  {typ}  {H.BECKHOFF[typ]['desc']}", "tb"))
            y += 5.5
            for c_, h_ in zip(cols, heads):
                b.append(t(c_, y, h_, "tbs"))
            y += 4.2
            chs = dict(by_term.get(nm, []))
            for ch in range(1, H.BECKHOFF[typ]["ch"] + 1):
                io = chs.get(ch)
                if io is None:
                    vals = [nm, str(ch), "spare", "", "", "", "", ""]
                else:
                    w = wid.get(io.tag, {})
                    vals = [nm, str(ch), io.tag, io.part, io.desc[:48] + ("  [implied]" if not io.cad else ""),
                            w.get("W", ""), f"{w.get('length_m', '')} m", w.get("cores", "")[:28]]
                for c_, v in zip(cols, vals):
                    b.append(t(c_, y, v, "tbs"))
                y += 3.6
            y += 3
        out.append(D.sheet(W, Hh, "\n".join(b), f"Electrical E1{pi} - terminal plan", "every channel -> tag -> cable",
                           start + pi, n, "none"))
    return out


def main():
    if P.check(verbose=False):
        raise SystemExit("REFUSING: plc_io proofs fail")
    ios = P.IOS
    rails, _, _ = P.terminals(ios)
    prows, _ = P.power(ios)
    lay, _, dims = P.cabinet(rails)
    wires, _ = P.wiring(ios)
    os.makedirs(OUT, exist_ok=True)
    safe = any(io.kind in P.SAFE_KINDS for io in ios)
    first = 5 if safe else 4
    term = terminal_sheets(ios, wires, rails, first, 0)
    n = first - 1 + len(term)
    term = terminal_sheets(ios, wires, rails, first, n)
    sheets = [("E01_power.svg", power_sheet(ios, prows, 1, n)), ("E02_cabinet.svg", cabinet_sheet(lay, dims, 2, n)),
              ("E03_ethercat.svg", ethercat_sheet(rails, 3, n))] + \
             ([("E04_safety.svg", safety_sheet(ios, 4, n))] if safe else []) + \
             [(f"E1{k}_terminals.svg", s) for k, s in enumerate(term)]
    for fn, svg in sheets:
        with open(os.path.join(OUT, fn), "w") as fh:
            fh.write(svg)
    links = "".join(f'<figure><img src="{fn}" alt="{fn}"><figcaption>{fn}</figcaption></figure>' for fn, _ in sheets)
    with open(os.path.join(OUT, "index.html"), "w") as fh:
        fh.write("<!doctype html><meta charset=utf-8><title>STF-2 electrical</title><style>body{font:14px system-ui;"
                 "margin:20px;background:#fff;color:#1b2330}img{width:100%;max-width:1400px;border:1px solid #ccd}"
                 "figure{margin:0 0 28px}</style><h1>STF-2 electrical sheets</h1>"
                 "<p>Generated from plc_io.py (I/O list, terminals, power, cabinet, wiring).</p>" + links)
    print(f"wrote {len(sheets)} electrical sheets -> {OUT}")


if __name__ == "__main__":
    main()
