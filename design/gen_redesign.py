#!/usr/bin/env python3
"""Generate the STF Twin UI-redesign .kanva.pptd (kimi-design DSL).

Two pages: Operations Overview + Health & Maintenance.
Design direction: precision industrial operations console —
hairline rule panels, amber instrument accent, mono numerals, no glassmorphism.
"""
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "stf-redesign")
PAGES = os.path.join(OUT, "pages")
os.makedirs(PAGES, exist_ok=True)

W, H = 1600, 1000
RAIL_W = 220
CX = 252                 # content left edge
CW = 1572 - CX           # 1320 content width

# ---------------------------------------------------------------- helpers
def block(text, indent):
    pad = " " * indent
    return "\n".join(pad + line for line in text.split("\n"))

def text_el(eid, x, y, w, h, text, style=None, size=None, color=None,
            font=None, bold=None, align=None, wrap=None, ls=None, lh=None):
    lines = [f"  - elementId: {eid}", "    elementType: text",
             f"    bounds: [{x}, {y}, {w}, {h}]", "    content:"]
    if style: lines.append(f'      style: "{style}"')
    if size is not None: lines.append(f"      fontSize: {size}")
    if color: lines.append(f'      color: "{color}"')
    if font: lines.append(f'      fontFamily: "{font}"')
    if bold is not None: lines.append(f"      bold: {'true' if bold else 'false'}")
    if ls is not None: lines.append(f"      letterSpacing: {ls}")
    if lh is not None: lines.append(f"      lineHeight: {lh}")
    if align: lines.append(f"      align: [{align}]")
    if wrap is not None: lines.append(f"      wrap: {'true' if wrap else 'false'}")
    lines.append("      text: |")
    lines.append(block(text, 8))
    return "\n".join(lines)

def rect_el(eid, x, y, w, h, fill=None, border=None, radius=None):
    lines = [f"  - elementId: {eid}", "    elementType: shape",
             f"    bounds: [{x}, {y}, {w}, {h}]", f"    shapeName: {'roundRect' if radius else 'rect'}"]
    if radius: lines.append(f"    adjustments: [{radius}]")
    if fill: lines.append(f'    fill: {{type: solid, color: "{fill}"}}')
    if border: lines.append(f'    border: {{style: solid, width: 1, color: "{border}"}}')
    return "\n".join(lines)

def icon_el(eid, x, y, size, name, color):
    return "\n".join([
        f"  - elementId: {eid}", "    elementType: icon",
        f"    bounds: [{x}, {y}, {size}, {size}]",
        f'    iconName: "{name}"',
        f'    fill: {{type: solid, color: "{color}"}}'])

def panel(eid, x, y, w, h):
    return rect_el(eid, x, y, w, h, fill="$surface", border="$line", radius=6000)

def panel_head(eid, x, y, title, hint=None, pw=856):
    els = [text_el(f"{eid}-t", x + 20, y + 16, 340, 18, f"<p><strong>{title}</strong></p>",
                   size=13, color="$text", font="Liter", wrap=False)]
    if hint:
        els.append(text_el(f"{eid}-h", x + pw - 360, y + 18, 340, 14, f"<p>{hint}</p>",
                           size=11, color="$faint", font="JetBrains Mono",
                           align="right, top", wrap=False))
    return els

def line_el(eid, x, y, w, h, points, color, width=1, view=(100, 40), dash=False):
    style = "dash" if dash else "solid"
    return f"""  - elementId: {eid}
    elementType: line
    bounds: [{x}, {y}, {w}, {h}]
    viewBox: [{view[0]}, {view[1]}]
    points: "{points}"
    curve: smooth
    border: {{style: {style}, width: {width}, color: "{color}"}}"""

def sparkline(eid, x, y, w, h, values, color):
    lo, hi = min(values), max(values)
    rng = (hi - lo) or 1
    n = len(values)
    pts = " ".join(
        f"{round(i / (n - 1) * 100, 1)},{round(37 - (v - lo) / rng * 33, 1)}"
        for i, v in enumerate(values))
    return line_el(eid, x, y, w, h, pts, color, width=1.5)

# ---------------------------------------------------------------- shared shell
NAV = [
    ("OPERATE", [("overview", "Overview", "fas:table-cells"),
                 ("production", "Production", "fas:industry"),
                 ("quality", "Quality & trace", "fas:circle-check"),
                 ("vision", "Vision QC", "fas:camera"),
                 ("alarms", "Alarms", "fas:bell"),
                 ("copilot", "Copilot", "fas:robot")]),
    ("MAINTAIN", [("health", "Health", "fas:heart-pulse"),
                  ("maintenance", "Maintenance", "fas:wrench")]),
    ("ANALYSE", [("month", "Month", "fas:calendar-days"),
                 ("throughput", "Throughput", "fas:gauge-high"),
                 ("process", "Oven process", "fas:temperature-high"),
                 ("scheduler", "Learned scheduler", "fas:shuffle"),
                 ("energy", "Energy & grid", "fas:bolt"),
                 ("carbon", "Carbon per cookie", "fas:leaf"),
                 ("security", "OT security", "fas:shield-halved")]),
    ("ENGINEER", [("engineering", "Engineering", "fas:gears"),
                  ("validation", "Validation", "fas:list-check"),
                  ("data", "Data", "fas:database")]),
    ("DOCS", [("docs", "Documentation", "fas:book-open"),
              ("degradation", "Degradation model", "fas:timeline")]),
]

def rail(selected):
    els = [rect_el("rail-bg", 0, 0, RAIL_W, H, fill="$rail"),
           rect_el("rail-edge", RAIL_W - 1, 0, 1, H, fill="$line")]
    # brand
    els += [rect_el("brand-mark", 20, 22, 36, 36, fill="$raised", border="#FFFFFF1F", radius=12000),
            text_el("brand-mark-t", 20, 22, 36, 36, "<p><strong>STF</strong></p>", size=12,
                    color="$accent", font="JetBrains Mono", align="center, middle", wrap=False),
            text_el("brand-name", 68, 25, 140, 18, "<p><strong>STF TWIN</strong></p>",
                    size=14, color="$text", font="Liter", wrap=False),
            text_el("brand-sub", 68, 45, 140, 13, "<p>Fabrik 24V · up12</p>", size=10,
                    color="$faint", font="JetBrains Mono", wrap=False)]
    y = 88
    for group, items in NAV:
        els.append(text_el(f"nav-g-{group}", 16, y, 180, 14,
                           f"<p>{group}</p>", size=10, color="$faint",
                           font="Liter", ls=1.5, wrap=False))
        y += 22
        for key, label, icon in items:
            on = (key == selected)
            if on:
                els.append(rect_el(f"nav-bg-{key}", 8, y, RAIL_W - 16, 30, fill="#FFFFFF0A", radius=8000))
                els.append(rect_el(f"nav-bar-{key}", 8, y, 2, 30, fill="$accent"))
            els.append(icon_el(f"nav-i-{key}", 18, y + 8, 14, icon,
                               "$accent" if on else "$faint"))
            els.append(text_el(f"nav-t-{key}", 42, y + 7, 160, 16,
                               f"<p>{label}</p>", size=13,
                               color="$text" if on else "$muted",
                               font="Liter", bold=on, wrap=False))
            y += 31
        y += 9
    # bottom status
    els += [rect_el("rail-div", 16, 892, RAIL_W - 32, 1, fill="$lineSoft"),
            rect_el("rail-dot", 17, 910, 7, 7, fill="$ok"),
            rect_el("rail-dot-ring", 14, 907, 13, 13, border="#45A87755", radius=50000),
            text_el("rail-src", 34, 906, 170, 14, "<p>SUPABASE · LIVE</p>", size=10,
                    color="$muted", font="JetBrains Mono", wrap=False),
            text_el("rail-ver", 34, 926, 170, 13, "<p>twin ws · v4.0.0</p>", size=10,
                    color="$faint", font="JetBrains Mono", wrap=False)]
    return els

def topbar(eyebrow, title, sub, pm=False):
    els = [rect_el("top-edge", RAIL_W, 75, W - RAIL_W, 1, fill="$lineSoft"),
           text_el("tb-eyebrow", CX, 16, 420, 13, f"<p>{eyebrow}</p>", size=10,
                   color="$faint", font="Liter", ls=1.5, wrap=False),
           text_el("tb-title", CX, 31, 420, 26, f"<p><strong>{title}</strong></p>",
                   size=20, color="$text", font="Liter", wrap=False),
           text_el("tb-sub", CX, 58, 460, 14, f"<p>{sub}</p>", size=12,
                   color="$muted", font="Liter", wrap=False)]
    # search
    els += [rect_el("tb-search", 696, 20, 400, 36, fill="$raised", border="$line", radius=50000),
            icon_el("tb-search-i", 714, 31, 14, "fas:magnifying-glass", "$faint"),
            text_el("tb-search-t", 738, 30, 300, 16, "<p>Search units, orders, docs…</p>",
                    size=13, color="$faint", font="Liter", wrap=False),
            rect_el("tb-kbd", 1050, 28, 34, 20, border="$line", radius=50000),
            text_el("tb-kbd-t", 1050, 30, 34, 14, "<p>⌘K</p>", size=11, color="$muted",
                    font="JetBrains Mono", align="center, top", wrap=False)]
    # live clock
    els += [rect_el("tb-live", 1276, 33, 7, 7, fill="$ok", radius=50000),
            rect_el("tb-live-ring", 1273, 30, 13, 13, border="#45A87744", radius=50000),
            text_el("tb-clock", 1294, 24, 96, 20, "<p>14:32:07</p>", size=15,
                    color="$text", font="JetBrains Mono", wrap=False),
            text_el("tb-clock-l", 1294, 46, 96, 12, "<p>LIVE TWIN</p>", size=9,
                    color="$faint", font="JetBrains Mono", ls=2, wrap=False)]
    x = 1416
    if pm:
        els += [rect_el("tb-pm", x, 24, 58, 32, fill="$raised", border="$line", radius=8000),
                text_el("tb-pm-t", x, 24, 58, 32, '<p>PM <span style="color:$accent"><strong>ON</strong></span></p>',
                        size=11, color="$muted", font="JetBrains Mono", align="center, middle", wrap=False)]
        x += 74
    els += [icon_el("tb-bell", x, 31, 16, "fas:bell", "$muted"),
            rect_el("tb-bell-badge", x + 12, 26, 14, 14, fill="$fail", radius=50000),
            text_el("tb-bell-n", x + 12, 27, 14, 12, "<p>3</p>", size=9, color="#FFFFFF",
                    font="JetBrains Mono", align="center, top", wrap=False),
            rect_el("tb-avatar", x + 44, 24, 32, 32, fill="#1E242E", border="$line", radius=50000),
            text_el("tb-avatar-t", x + 44, 24, 32, 32, "<p>SP</p>", size=12, color="$muted",
                    font="JetBrains Mono", align="center, middle", wrap=False)]
    return els

def kpi_band(kpis):
    """kpis: list of (label, value, delta_html, delta_color, spark_values, spark_color)"""
    els = []
    cw = CW // len(kpis)
    for i, (label, value, delta, dcolor, svals, scolor) in enumerate(kpis):
        x = CX + i * cw
        els.append(text_el(f"kpi-{i}-l", x + 24, 104, 240, 14, f"<p>{label}</p>",
                           size=11, color="$muted", font="Liter", ls=1.2, wrap=False))
        els.append(text_el(f"kpi-{i}-v", x + 24, 124, 220, 42, f"<p><strong>{value}</strong></p>",
                           size=32, color="$text", font="JetBrains Mono", wrap=False))
        els.append(text_el(f"kpi-{i}-d", x + 24, 174, 250, 15, f"<p>{delta}</p>",
                           size=12, color=dcolor, font="Liter", wrap=False))
        els.append(sparkline(f"kpi-{i}-s", x + cw - 118, 124, 94, 46, svals, scolor))
        if i:
            els.append(rect_el(f"kpi-{i}-div", x, 108, 1, 84, fill="$lineSoft"))
    return els

def copilot_bar(question="Ask the copilot — every answer checked against live twin data and 438 docs"):
    return [rect_el("ask-bar", CX, 928, CW, 44, fill="$surface", border="$line", radius=12000),
            icon_el("ask-i", CX + 22, 942, 16, "fas:robot", "$accent"),
            text_el("ask-t", CX + 50, 941, 900, 16, f"<p>{question}</p>", size=13,
                    color="$muted", font="Liter", wrap=False),
            rect_el("ask-kbd", 1504, 940, 48, 20, border="$line", radius=50000),
            text_el("ask-kbd-t", 1504, 942, 48, 14, "<p>⌘ ⏎</p>", size=11, color="$muted",
                    font="JetBrains Mono", align="center, top", wrap=False)]

def page_yaml(els, bg="$bg"):
    return ("background:\n"
            f'  type: solid\n  color: "{bg}"\n'
            "elements:\n" + "\n".join(els) + "\n")

# ================================================================ PAGE 1 — Overview
els = rail("overview")
els += topbar("OPERATE — OVERVIEW", "Operations overview",
              "Fabrik Simulation 24V · Line 1 · Shift 2 · 04:12 remaining")
els += kpi_band([
    ("OEE", "86.5 %", '<span style="color:$ok">▲ 2.1 pts</span> <span style="color:$faint">vs shift 1</span>', "$text",
     [78, 79, 81, 80, 82, 83, 84, 83.5, 85, 85.4, 86, 86.5], "$accent"),
    ("THROUGHPUT / H", "142.6", '<span style="color:$ok">▲ 6.2</span> <span style="color:$faint">vs shift 1</span>', "$text",
     [118, 121, 124, 122, 128, 131, 129, 134, 136, 138, 140, 142.6], "$ok"),
    ("RIGHT FIRST TIME", "99.1 %", '<span style="color:$ok">▲ 19.5 pts</span> <span style="color:$faint">vs timer baseline</span>', "$text",
     [79.6, 82, 86, 88, 91, 93, 95, 96.2, 97, 97.8, 98.4, 99.1], "$ok"),
    ("ENERGY / BATCH", "3.84 kWh", '<span style="color:$muted">▼ 4.0 %</span> <span style="color:$faint">vs last week</span>', "$text",
     [4.3, 4.25, 4.2, 4.15, 4.1, 4.05, 4.0, 3.96, 3.92, 3.9, 3.87, 3.84], "$muted"),
])

# ---- process line strip
els.append(text_el("line-tag", CX, 224, 60, 13, "<p>LINE 1</p>", size=10,
                   color="$faint", font="Liter", ls=1.5, wrap=False))
els.append(rect_el("line-track", 340, 248, 1192, 1, fill="$line"))
stations = [("Raw storage", "ready", "$faint"),
            ("HBW crane", "running", "$accent"),
            ("Oven line", "bake · 180 °C", "$accent"),
            ("Cooling", "running", "$accent"),
            ("Vision QC", "hold 1", "$warn"),
            ("Packing", "ready", "$faint")]
for i, (name, state, color) in enumerate(stations):
    x = 356 + i * 232
    els.append(text_el(f"st-{i}-n", x - 80, 224, 160, 14, f"<p>{name}</p>", size=12,
                       color="$text", font="Liter", align="center, top", wrap=False))
    els.append(rect_el(f"st-{i}-dot", x - 4, 244, 9, 9, fill=color, radius=50000))
    els.append(rect_el(f"st-{i}-ring", x - 7, 241, 15, 15, border="#FFFFFF22", radius=50000))
    els.append(text_el(f"st-{i}-s", x - 80, 262, 160, 12, f"<p>{state}</p>", size=10,
                       color="$faint", font="JetBrains Mono", align="center, top", wrap=False))

# ---- throughput panel
els.append(panel("p-tput", CX, 284, 856, 304))
els += panel_head("p-tput", CX, 284, "Throughput · live", "cookies / hour")
els.append(rect_el("lg-actual-dot", 1352, 302, 7, 7, fill="$accent", radius=50000))
els.append(text_el("lg-actual", 1364, 300, 44, 13, "<p>actual</p>", size=11, color="$muted",
                   font="Liter", wrap=False))
els.append(rect_el("lg-target", 1418, 305, 24, 1, fill="$faint"))
els.append(text_el("lg-target-t", 1448, 300, 44, 13, "<p>target</p>", size=11, color="$muted",
                   font="Liter", wrap=False))
rows = "\n".join(f'          - ["{t}", {a}, 120]' for t, a in
                 [("06:00", 98), ("07:00", 112), ("08:00", 124), ("09:00", 131),
                  ("10:00", 128), ("11:00", 136), ("12:00", 141), ("13:00", 139), ("14:00", 142.6)])
els.append(f"""  - elementId: chart-tput
    elementType: chart
    bounds: [272, 326, 816, 240]
    fontFamily: Liter
    data:
      cols: [t, actual, target]
      rows:
{rows}
    series:
      - type: area
        encode: {{x: t, y: actual}}
        name: actual
        lineColor: "$accent"
        areaColor: "#E8A33D15"
        width: 2
        smooth: true
        marker: false
      - type: line
        encode: {{x: t, y: target}}
        name: target
        lineColor: "#4A515C"
        lineStyle: dash
        width: 1
        marker: false
    xAxis:
      label: {{fontSize: 10, color: "$faint"}}
      axisLine: false
      gridLine: false
    yAxis:
      min: 80
      max: 150
      label: {{fontSize: 10, color: "$faint", numberFormat: "0"}}
      axisLine: false
      gridLine: {{color: "#FFFFFF0A"}}
    legend: false""")

# ---- OEE waterfall panel
els.append(panel("p-oee", CX, 604, 856, 304))
els += panel_head("p-oee", CX, 604, "OEE waterfall · shift 2", "A × P × Q")
els.append("""  - elementId: chart-oee
    elementType: chart
    bounds: [272, 646, 816, 238]
    fontFamily: Liter
    data:
      cols: [step, v, total]
      rows:
        - [Availability, 92.0, true]
        - [Performance loss, -4.7, false]
        - [Quality loss, -0.8, false]
        - [OEE, 86.5, true]
    series:
      - type: waterfall
        encode: {x: step, y: v, isTotal: total}
        totalBars: {fill: "#3B4450"}
        decreaseBars: {fill: "$accent"}
        increaseBars: {fill: "$ok"}
    dataLabels: {show: true, fontSize: 9, color: "$muted", numberFormat: "0.0"}
    xAxis:
      label: {fontSize: 10, color: "$muted"}
      axisLine: false
      gridLine: false
    yAxis:
      min: 84
      max: 94
      label: {fontSize: 10, color: "$faint", numberFormat: "0.0"}
      axisLine: false
      gridLine: {color: "#FFFFFF0A"}
    legend: false""")

# ---- units panel
els.append(panel("p-units", 1128, 284, 444, 304))
els += panel_head("p-units", 1128, 284, "Units now", "2 / 8 RUNNING", pw=444)
units = [("crane", "running", "$accent"), ("belt", "belt back", "$accent"),
         ("arm", "ready", "$faint"), ("door", "to tt", "$accent"),
         ("sauger", "to tt", "$accent"), ("turntable", "ready", "$faint"),
         ("ovenbelt", "bake", "$accent"), ("line", "ready", "$faint")]
for i, (name, state, color) in enumerate(units):
    y = 348 + i * 28
    els.append(rect_el(f"u-{i}-dot", 1156, y + 6, 8, 8, fill=color, radius=50000))
    els.append(text_el(f"u-{i}-n", 1176, y, 150, 16, f"<p>{name}</p>", size=13,
                       color="$text", font="Liter", wrap=False))
    els.append(text_el(f"u-{i}-s", 1368, y + 2, 172, 14, f"<p>{state}</p>", size=11,
                       color="$faint", font="JetBrains Mono", align="right, top", wrap=False))
    if i < 7:
        els.append(rect_el(f"u-{i}-div", 1156, y + 26, 392, 1, fill="$lineSoft"))

# ---- orders panel
els.append(panel("p-orders", 1128, 604, 444, 304))
els += panel_head("p-orders", 1128, 604, "Active orders", "3 OPEN", pw=444)
els.append("""  - elementId: tbl-orders
    elementType: table
    bounds: [1152, 648, 400, 224]
    columnWidths: [0.30, 0.16, 0.18, 0.36]
    rowHeights: [0.16, 0.21, 0.21, 0.21, 0.21]
    style:
      cellStyle:
        fontSize: 12
        color: "$muted"
        fontFamily: Liter
        align: [left, middle]
        border: [null, null, {style: solid, width: 1, color: "#FFFFFF0A"}, null]
      firstRowStyle:
        fontSize: 10
        color: "$faint"
        letterSpacing: 1
        border: [null, null, {style: solid, width: 1, color: "#FFFFFF14"}, null]
    rows:
      - - text: "ORDER"
        - text: "QTY"
          align: [right, middle]
        - text: "DONE"
          align: [right, middle]
        - text: "STATUS"
      - - text: "#1042"
          fontFamily: JetBrains Mono
        - text: "9"
          align: [right, middle]
          fontFamily: JetBrains Mono
        - text: "3 / 9"
          align: [right, middle]
          fontFamily: JetBrains Mono
        - text: '<p><span style="color:$accent">● baking</span></p>'
      - - text: "#1041"
          fontFamily: JetBrains Mono
        - text: "9"
          align: [right, middle]
          fontFamily: JetBrains Mono
        - text: "9 / 9"
          align: [right, middle]
          fontFamily: JetBrains Mono
        - text: '<p><span style="color:$muted">● packing</span></p>'
      - - text: "#1040"
          fontFamily: JetBrains Mono
        - text: "12"
          align: [right, middle]
          fontFamily: JetBrains Mono
        - text: "12 / 12"
          align: [right, middle]
          fontFamily: JetBrains Mono
        - text: '<p><span style="color:$ok">● done</span></p>'
      - - text: "#1039"
          fontFamily: JetBrains Mono
        - text: "6"
          align: [right, middle]
          fontFamily: JetBrains Mono
        - text: "6 / 6"
          align: [right, middle]
          fontFamily: JetBrains Mono
        - text: '<p><span style="color:$ok">● done</span></p>'""")

els += copilot_bar()

with open(os.path.join(PAGES, "1_overview.page"), "w") as f:
    f.write(page_yaml(els))

# ================================================================ PAGE 2 — Health
els = rail("health")
els += topbar("MAINTAIN — HEALTH", "Health & maintenance",
              "Condition monitoring · U6 degradation model · machine age 12.4 shifts", pm=True)
els += kpi_band([
    ("FLEET HEALTH INDEX", "96", '<span style="color:$faint">mean HI · 100 = new</span>', "$text",
     [100, 100, 99.8, 99.6, 99.2, 98.8, 98.2, 97.6, 97, 96.6, 96.2, 96], "$accent"),
    ("PARTS", "10 · 0 · 0", '<span style="color:$faint">healthy / service due / failed</span>', "$text",
     [10]*12, "$ok"),
    ("NEXT WARNING", "19.5 sh", '<span style="color:$warn">air supply — leaks</span>', "$text",
     [30, 29, 27.5, 26, 25, 23.5, 22.5, 21.5, 20.5, 20, 19.8, 19.5], "$warn"),
    ("FIRST FAILURE", "29.9 sh", '<span style="color:$fail">air supply — leaks</span>', "$text",
     [42, 40, 38.5, 37, 35.5, 34.5, 33.5, 32.5, 31.8, 31, 30.4, 29.9], "$fail"),
])

# ---- remaining-life runway
els.append(panel("p-rul", CX, 284, 760, 356))
els += panel_head("p-rul", CX, 284, "Remaining-life runway", "shifts from now · 8 h each", pw=760)
els.append(text_el("rul-h1", 276, 326, 150, 12, "<p>PART</p>", size=9, color="$faint",
                   font="Liter", ls=1.5, wrap=False))
els.append(text_el("rul-h2", 440, 326, 36, 12, "<p>HI</p>", size=9, color="$faint",
                   font="Liter", ls=1.5, wrap=False))
els.append(text_el("rul-h3", 478, 326, 420, 12, "<p>HEALTHY → WARNING → FAILURE</p>", size=9,
                   color="$faint", font="Liter", ls=1.5, align="center, top", wrap=False))
els.append(text_el("rul-h4", 908, 326, 88, 12, "<p>WARN·FAIL</p>", size=9, color="$faint",
                   font="JetBrains Mono", align="right, top", wrap=False))
BAR_X, BAR_W, SCALE = 478, 420, 430.0
rul = [("air supply", 100, 19.5, 29.9),
       ("colour sensor A4", 98, 32.9, 66.3),
       ("HBW belt", 95, 35.2, 49.7),
       ("VGR swivel gearbox", 96, 56.8, 62.2),
       ("HBW travel spindle + nut", 95, 112, 160),
       ("oven door cylinder", 98, 117, 166),
       ("Sauger lowering cyl.", 99, 117, 166),
       ("VGR suction cup seal", 99, 148, 187),
       ("Auswerfer cylinder", 99, 234, 332),
       ("RFID read heads", 99, 348, 415)]
for i, (name, hi, warn, fail) in enumerate(rul):
    y = 348 + i * 25
    w1 = round(warn / SCALE * BAR_W, 1)
    w2 = round(max((fail - warn) / SCALE * BAR_W, 3), 1)
    els.append(text_el(f"rul-{i}-n", 276, y + 2, 158, 14, f"<p>{name}</p>", size=11,
                       color="$muted", font="Liter", align="right, top", wrap=False))
    els.append(text_el(f"rul-{i}-hi", 442, y + 3, 30, 13, f"<p>{hi}</p>", size=10,
                       color="$ok", font="JetBrains Mono", wrap=False))
    els.append(rect_el(f"rul-{i}-bg", BAR_X, y + 5, BAR_W, 10, fill="#FFFFFF08", radius=50000))
    els.append(rect_el(f"rul-{i}-ok", BAR_X, y + 5, round(w1), 10, fill="$ok", radius=50000))
    els.append(rect_el(f"rul-{i}-wn", BAR_X + round(w1), y + 5, round(w2), 10, fill="$accent", radius=50000))
    els.append(rect_el(f"rul-{i}-fl", BAR_X + round(w1) + round(w2), y + 2, 2, 16, fill="$fail"))
    els.append(text_el(f"rul-{i}-v", 908, y + 3, 88, 13,
                       f"<p>{warn:g} · {fail:g}</p>", size=10, color="$faint",
                       font="JetBrains Mono", align="right, top", wrap=False))
for t in (0, 100, 200, 300, 400):
    x = round(BAR_X + t / SCALE * BAR_W)
    els.append(text_el(f"rul-tick-{t}", x - 16, 606, 32, 11, f"<p>{t}</p>", size=9,
                       color="$faint", font="JetBrains Mono", align="center, top", wrap=False))

# ---- not predictable panel
els.append(panel("p-np", 1032, 284, 540, 356))
els += panel_head("p-np", 1032, 284, "No gradual precursor", None)
np_items = [("Reed / reference switch breaks", "Preventive: switch test at every PM visit."),
            ("Light barrier gets dirty", "Preventive: clean lens at every PM visit."),
            ("Encoder cable in a drag chain", "Remote I/O bend counts give the life; replace the cable at end of chain life.")]
for i, (t1, t2) in enumerate(np_items):
    y = 330 + i * 86
    els.append(rect_el(f"np-{i}-bar", 1052, y + 2, 3, 30, fill="$warn"))
    els.append(text_el(f"np-{i}-t", 1068, y, 470, 18, f"<p><strong>{t1}</strong></p>", size=14,
                       color="$text", font="Liter", wrap=False))
    els.append(text_el(f"np-{i}-d", 1068, y + 24, 470, 32, f"<p>{t2}</p>", size=12,
                       color="$muted", font="Liter", lh=1.4))
    if i < 2:
        els.append(rect_el(f"np-{i}-div", 1052, y + 74, 500, 1, fill="$lineSoft"))
els.append(text_el("np-note", 1052, 596, 500, 28,
                   "<p>Watchdog catches these when they happen; the routine check covers the rest.</p>",
                   size=11, color="$faint", font="Liter", lh=1.4))

# ---- health map heatmap
els.append(panel("p-hm", CX, 660, 1320, 248))
els += panel_head("p-hm", CX, 660, "Health map · every part over machine life", "HI 55–100 · machine age, shifts", pw=1320)
parts = ["air supply", "colour sensor A4", "HBW belt", "VGR swivel gearbox",
         "HBW travel spindle + nut", "oven door cylinder", "Sauger lowering cyl.",
         "VGR suction cup seal", "Auswerfer cylinder", "RFID read heads"]
ages = ["0–50", "50–100", "100–150", "150–200", "200–250", "250–300", "300–350", "350–400"]
# end HI per part at age 400, start near 100
end_hi = {"air supply": 58, "colour sensor A4": 66, "HBW belt": 70, "VGR swivel gearbox": 74,
          "HBW travel spindle + nut": 78, "oven door cylinder": 84, "Sauger lowering cyl.": 85,
          "VGR suction cup seal": 87, "Auswerfer cylinder": 90, "RFID read heads": 96}
# renderer places the first data category at the bottom: feed reversed so the
# worst part (air supply) ends up on top, and draw the row labels ourselves
hm_rows = []
for p in reversed(parts):
    e = end_hi[p]
    for b, a in enumerate(ages):
        base = 100 - (100 - e) * (b / 7.0)
        jitter = ((hash((p, b)) % 7) - 3) * 1.1
        v = round(min(100, max(52, base + jitter)), 1)
        hm_rows.append(f'          - ["{a}", "{p}", {v}]')
HM_X, HM_Y, HM_W, HM_H = 436, 704, 1076, 184
els.append(f"""  - elementId: chart-hmap
    elementType: chart
    bounds: [{HM_X}, {HM_Y}, {HM_W}, {HM_H}]
    fontFamily: Liter
    data:
      cols: [age, part, hi]
      rows:
{chr(10).join(hm_rows)}
    series:
      - type: heatmap
        encode: {{x: age, y: part, value: hi}}
        colorScheme: ["#E8A33D", "#45A877"]
        colorScale:
          domain: [55, 100]
        colorbar:
          position: right
          label: {{fontSize: 9, color: "$faint"}}
    xAxis:
      label: {{fontSize: 9, color: "$faint"}}
      axisLine: false
      gridLine: false
    yAxis:
      label: false
      axisLine: false
      gridLine: false""")
for j, p in enumerate(parts):
    cy = HM_Y + (j + 0.5) * (HM_H / 10)
    els.append(text_el(f"hm-l-{j}", 276, round(cy - 7), 148, 14, f"<p>{p}</p>", size=10,
                       color="$muted", font="Liter", align="right, top", wrap=False))

els += copilot_bar(question="Ask the copilot — e.g. “which part fails first if PM stays off?”")

with open(os.path.join(PAGES, "2_health.page"), "w") as f:
    f.write(page_yaml(els))

# ================================================================ main entry
main = """version: v2
title: STF Twin — Operations Console Redesign
size: [1600, 1000]
customFonts:
  - family: Liter
    src: "https://statics.kimi.ai/neo-design-static/p-font/Liter.ttf"
  - family: JetBrains Mono
    src: "https://fonts.googleapis.com/css2?family=JetBrains+Mono"
theme:
  colors:
    bg: "#0A0C0F"
    rail: "#0C0F13"
    surface: "#0E1218"
    raised: "#131820"
    line: "#FFFFFF14"
    lineSoft: "#FFFFFF0A"
    text: "#E9EBEE"
    muted: "#8B929D"
    faint: "#5A616C"
    accent: "#E8A33D"
    ok: "#45A877"
    warn: "#E2622B"
    fail: "#D64550"
  textStyles:
    mono:
      fontSize: 12
      color: "$text"
      fontFamily: "JetBrains Mono"
pages:
  - pages/1_overview.page
  - pages/2_health.page
"""
with open(os.path.join(OUT, "stf-redesign.kanva.pptd"), "w") as f:
    f.write(main)

print("written:", OUT)
