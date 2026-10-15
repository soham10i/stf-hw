# -*- coding: utf-8 -*-
import json, html
from hbw_model import build, P

V = json.load(open("views.json"))
parts = build()

GROUP_META = [
    ("frame",     "Module frame",            "The plate everything bolts to."),
    ("rack",      "Hochregal — the rack",    "Static storage structure, 4 bays x 3 rows = 12 slots."),
    ("mould",     "Werkstucktrager — moulds","A pocket per slot. The VGR drops a cookie in; the crane carries the whole mould."),
    ("workpiece", "Cookie",                  "White container + coloured lid, seated in a mould."),
    ("rail",      "Travel axis (X)",         "Fixed rail along the front; the whole crane rides it."),
    ("crane",     "Hochregalbediengerat",    "Mast, lift carriage and their drives."),
    ("fork",      "Ausleger — the fork",     "Telescoping cantilever that lifts from below."),
    ("conveyor",  "Fordertechnik",           "Twin-strip belt running out of the module, with two hand-over points."),
    ("cover",     "Identification tunnel",   "Four pillars, a roof, and a sensor at each inside corner."),
    ("tool",      "Fork table",              "Its own group so the checker can prove the mould touches ONLY its top face."),
    ("control",   "Electrics",               "24 V adapter PCB and terminals."),
]

def dims(p):
    if p.kind == "box":
        return "%g x %g x %g" % p.s
    ax, L, d = p.s
    return "Ø%g x %g (%s)" % (d, L, ax)

def pos(p):
    a = p.aabb()
    return "x %g..%g   y %g..%g   z %g..%g" % (a[0], a[3], a[1], a[4], a[2], a[5])

def collapse(g):
    """collapse repeated parts (9 workpieces, 18 shelf brackets ...) into one row + count"""
    seen = {}
    for p in [q for q in parts if q.group == g]:
        key = (dims(p), p.tag, p.note, p.kind, p.colour)
        seen.setdefault(key, []).append(p)
    rows = []
    for key, ps in seen.items():
        rows.append((ps[0], len(ps)))
    return rows

def rows_html(g):
    out = []
    for p, n in collapse(g):
        tag = ('<span class="tag %s">%s</span>' % (
            "io-in" if (p.tag.startswith("I") or p.tag.startswith("A") or p.tag.startswith("B"))
            else "io-out", html.escape(p.tag))) if p.tag else '<span class="tag none">—</span>'
        nm = html.escape(p.name.rstrip("0123456789_") if n > 1 else p.name)
        out.append(
            "<tr><td class='qty'>%d</td><td class='nm'>%s</td><td class='mono'>%s</td>"
            "<td>%s</td><td class='note'>%s</td></tr>"
            % (n, nm, html.escape(dims(p)), tag, html.escape(p.note or "")))
    return "\n".join(out)

SHEETS = [
    ("factory",   "STF-00", "Factory plan — top view", "1:2.4",
     "the whole table, matching your sketch",
     "Warehouse on the right: 2 rack, 3 conveyor running out toward the VGR, 4 picker rail, "
     "1 PCB. Dashed outlines are the reserved footprints for 5 VGR, 6 oven and 7 sorting."),
    ("plan_bay",  "HRL-01", "Plan / Draufsicht", "1:1", "crane at bay column 2, lift 140, Ausleger extended 60",
     "Top view. Rack across the back, travel rail through the middle, twin-strip conveyor at the right-hand edge."),
    ("front",     "HRL-02", "Front elevation / Vorderansicht", "1:1", "same pose, viewed from -Y",
     "Shelf levels A/B/C at z = 40 / 160 / 280, bay pitch 120. The mast is deliberately taller than the rack."),
    ("side",      "HRL-03", "Side elevation / Seitenansicht", "1:1", "same pose, viewed from +X",
     "Shows the fork reaching from the aisle into the 60 mm bay depth, and the arm riding clear above."),
    ("plan_belt", "HRL-04", "Plan — conveyor hand-over", "1:1", "travel 495, lift 92, Ausleger 95",
     "The 24 mm fork table sits inside the 30 mm gap between the two belt strips; the workpiece bridges them."),
]

sheets_html = []
for key, no, title, scale, pose, cap in SHEETS:
    sheets_html.append(f"""
<figure class="sheet">
  <div class="sheet-frame">{V[key]}</div>
  <figcaption class="titleblock">
    <div class="tb-main"><span class="tb-no">{no}</span><span class="tb-t">{html.escape(title)}</span></div>
    <dl class="tb-grid">
      <div><dt>Scale</dt><dd class="mono">{scale}</dd></div>
      <div><dt>Units</dt><dd class="mono">mm</dd></div>
      <div><dt>Projection</dt><dd class="mono">1st angle</dd></div>
      <div><dt>Pose</dt><dd class="mono">{html.escape(pose)}</dd></div>
    </dl>
    <p class="tb-cap">{html.escape(cap)}</p>
  </figcaption>
</figure>""")

groups_html = []
for g, title, sub in GROUP_META:
    n = len([p for p in parts if p.group == g])
    groups_html.append(f"""
<section class="grp">
  <header class="grp-h"><h3>{html.escape(title)}</h3>
    <span class="grp-n mono">{n} solids</span></header>
  <p class="grp-sub">{html.escape(sub)}</p>
  <div class="tw"><table>
    <thead><tr><th>Qty</th><th>Part</th><th>Size mm</th><th>I/O</th><th>Function / why this dimension</th></tr></thead>
    <tbody>{rows_html(g)}</tbody>
  </table></div>
</section>""")

HTML = """<title>Hochregallager Build Sheet</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
:root{
  --paper:#EDEFF1; --sheet:#FBFCFC; --panel:#F5F7F8;
  --ink:#15181B; --ink-2:#4E565E; --ink-3:#79838C;
  --rule:#D2D8DD; --rule-2:#E3E8EB;
  --ft:#D0342C; --dim:#C0392B; --sens:#1B8F52; --act:#1F1F24;
  --shadow:0 1px 0 rgba(21,24,27,.05), 0 8px 24px -18px rgba(21,24,27,.5);
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --paper:#101315; --sheet:#171B1E; --panel:#1B2024;
  --ink:#E6EAED; --ink-2:#A6B0B8; --ink-3:#7C868E;
  --rule:#2B3238; --rule-2:#232A2F;
  --ft:#F0564C; --dim:#F0564C; --sens:#3FD08A;--act:#C9D2D8;
  --shadow:0 1px 0 rgba(0,0,0,.4), 0 8px 28px -20px #000;
}}
:root[data-theme="dark"]{
  --paper:#101315; --sheet:#171B1E; --panel:#1B2024;
  --ink:#E6EAED; --ink-2:#A6B0B8; --ink-3:#7C868E;
  --rule:#2B3238; --rule-2:#232A2F;
  --ft:#F0564C; --dim:#F0564C; --sens:#3FD08A;--act:#C9D2D8;
  --shadow:0 1px 0 rgba(0,0,0,.4), 0 8px 28px -20px #000;
}
*{box-sizing:border-box}
body{background:var(--paper);color:var(--ink);
  font:400 15px/1.62 "IBM Plex Sans",system-ui,-apple-system,sans-serif;
  -webkit-font-smoothing:antialiased;padding:0 0 80px}
.mono{font-family:"IBM Plex Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}
.wrap{max-width:1180px;margin:0 auto;padding:0 26px}
.col{max-width:66ch}
h1,h2,h3{font-family:"Barlow Condensed","IBM Plex Sans",sans-serif;text-wrap:balance;
  letter-spacing:.005em;margin:0}
h1{font-weight:700;font-size:clamp(38px,6vw,62px);line-height:.98;text-transform:uppercase}
h2{font-weight:600;font-size:30px;text-transform:uppercase;letter-spacing:.02em}
h3{font-weight:600;font-size:21px}
.eyebrow{font-family:"IBM Plex Mono",monospace;font-size:11px;letter-spacing:.16em;
  text-transform:uppercase;color:var(--ink-3)}

/* header */
header.top{border-bottom:2px solid var(--ink);margin-bottom:34px;padding-top:44px}
.top .id{display:flex;flex-wrap:wrap;gap:10px 22px;align-items:baseline;margin-bottom:14px}
.top .id .art{color:var(--ft);font-weight:600}
.lede{margin:16px 0 26px;font-size:17px;color:var(--ink-2)}
.frame-key{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
  gap:0;border-top:1px solid var(--rule);margin-bottom:0}
.frame-key div{padding:12px 16px 14px;border-right:1px solid var(--rule-2)}
.frame-key div:last-child{border-right:0}
.frame-key dt{font-family:"IBM Plex Mono",monospace;font-size:11px;letter-spacing:.14em;
  text-transform:uppercase;color:var(--ink-3);margin-bottom:3px}
.frame-key dd{margin:0;font-size:14px}

/* provenance */
.prov{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1px;
  background:var(--rule);border:1px solid var(--rule);margin:34px 0 46px}
.prov > div{background:var(--sheet);padding:18px 20px 20px}
.prov h3{font-size:16px;margin-bottom:8px}
.prov .k{display:inline-block;width:9px;height:9px;margin-right:7px;vertical-align:1px}
.k.doc{background:var(--sens)} .k.ded{background:var(--ft)} .k.ass{background:var(--ink-3)}
.prov p{margin:0;font-size:14px;color:var(--ink-2)}
.prov ul{margin:8px 0 0;padding-left:18px;font-size:13.5px;color:var(--ink-2)}
.prov li{margin:3px 0}

/* drawing sheets */
.sheets{display:grid;gap:34px;margin:0 0 52px}
.sheet{margin:0;background:var(--sheet);border:1px solid var(--rule);box-shadow:var(--shadow)}
.sheet-frame{padding:14px;overflow-x:auto}
.sheet svg{display:block;min-width:520px;width:100%;height:auto}
.titleblock{border-top:1px solid var(--rule);padding:0}
.tb-main{display:flex;gap:14px;align-items:baseline;padding:11px 16px 9px;
  border-bottom:1px solid var(--rule-2)}
.tb-no{font-family:"IBM Plex Mono",monospace;font-size:12px;font-weight:600;
  letter-spacing:.1em;color:var(--ft)}
.tb-t{font-family:"Barlow Condensed",sans-serif;font-weight:600;font-size:19px;
  text-transform:uppercase;letter-spacing:.03em}
.tb-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  margin:0;border-bottom:1px solid var(--rule-2)}
.tb-grid > div{padding:8px 16px;border-right:1px solid var(--rule-2)}
.tb-grid > div:last-child{border-right:0}
.tb-grid dt{font-family:"IBM Plex Mono",monospace;font-size:10px;letter-spacing:.14em;
  text-transform:uppercase;color:var(--ink-3)}
.tb-grid dd{margin:2px 0 0;font-size:13px}
.tb-cap{margin:0;padding:10px 16px 13px;font-size:13.5px;color:var(--ink-2)}

/* component tables */
.grp{margin:0 0 30px}
.grp-h{display:flex;align-items:baseline;gap:14px;border-bottom:1.5px solid var(--ink);
  padding-bottom:6px;margin-bottom:6px}
.grp-n{font-size:12px;color:var(--ink-3);margin-left:auto}
.grp-sub{margin:0 0 12px;font-size:14px;color:var(--ink-2)}
.tw{overflow-x:auto}
table{border-collapse:collapse;width:100%;min-width:660px;font-size:13.5px}
th{font-family:"IBM Plex Mono",monospace;font-size:10.5px;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ink-3);text-align:left;font-weight:500;
  padding:0 12px 7px 0;border-bottom:1px solid var(--rule)}
td{padding:8px 12px 8px 0;border-bottom:1px solid var(--rule-2);vertical-align:top}
td.qty{font-family:"IBM Plex Mono",monospace;color:var(--ink-3);width:38px}
td.nm{font-family:"IBM Plex Mono",monospace;font-size:12.5px;white-space:nowrap}
td.mono{font-family:"IBM Plex Mono",monospace;white-space:nowrap;color:var(--ink-2)}
td.note{color:var(--ink-2);max-width:42ch}
.tag{font-family:"IBM Plex Mono",monospace;font-size:11px;font-weight:600;
  padding:2px 6px;white-space:nowrap;display:inline-block}
.tag.io-in{background:color-mix(in srgb,var(--sens) 16%,transparent);color:var(--sens)}
.tag.io-out{background:color-mix(in srgb,var(--ink) 10%,transparent);color:var(--ink)}
.tag.none{color:var(--ink-3);background:none;padding-left:0}

/* kinematics + checks */
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:34px;margin-bottom:46px}
.pass{border:1px solid var(--rule);background:var(--sheet);padding:20px 22px}
.pass h3{margin-bottom:10px}
.check{display:flex;gap:11px;padding:7px 0;border-bottom:1px solid var(--rule-2);font-size:13.5px}
.check:last-child{border-bottom:0}
.check b{font-family:"IBM Plex Mono",monospace;color:var(--sens);flex:none}
.q{border-left:3px solid var(--ft);padding:2px 0 2px 18px;margin:0 0 20px}
.q h3{font-size:17px;margin-bottom:4px}
.q p{margin:0;color:var(--ink-2);font-size:14.5px}
footer{border-top:1px solid var(--rule);margin-top:44px;padding-top:18px;
  font-size:13px;color:var(--ink-3)}
a{color:var(--ft)}
:focus-visible{outline:2px solid var(--ft);outline-offset:2px}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style>

<div class="wrap">
<header class="top">
  <div class="id">
    <span class="eyebrow art">ft 536631</span>
    <span class="eyebrow">Automatisiertes Hochregallager 24 V</span>
    <span class="eyebrow">module 1 of 4 &mdash; Fabrik-Simulation 536634</span>
  </div>
  <h1>Hochregallager<br>build sheet</h1>
  <p class="lede col">A from-scratch component breakdown and dimensioned layout for the high-bay
  warehouse: rack, stacker crane, telescoping fork, twin-strip conveyor and every sensor on the
  Belegungsplan. 170 solids, each with an explicit support and a proven clearance envelope.</p>
  <dl class="frame-key">
    <div><dt>Origin</dt><dd>front-left corner of the plate, on its top face</dd></div>
    <div><dt>+X</dt><dd>right &mdash; rack face &amp; crane travel</dd></div>
    <div><dt>+Y</dt><dd>back &mdash; fork extension, into the module</dd></div>
    <div><dt>+Z</dt><dd>up &mdash; shelf rows A, B, C</dd></div>
    <div><dt>Plate</dt><dd class="mono">600 &times; 400 &times; 10</dd></div>
  </dl>
</header>

<section class="prov">
  <div>
    <h3><span class="k doc"></span>Taken from the documents</h3>
    <p>Verbatim, no interpretation:</p>
    <ul>
      <li>All 24 terminal assignments &mdash; I1&hellip;I6, A1/A2, B1&hellip;B4, Q1&hellip;Q8.</li>
      <li>Encoder motor 144643: body <span class="mono">60&times;30&times;30</span>, shaft <span class="mono">&Oslash;4 &times; 7.5</span> out of a <span class="mono">30&times;30</span> end face, 2 flats 0.7&nbsp;mm.</li>
      <li>Its T&ndash;N&ndash;I curve: no-load <span class="mono">440 rpm</span>, stall <span class="mono">1800 g&middot;cm</span>, P<sub>max</sub> <span class="mono">2.03 W</span>, I<sub>max</sub> <span class="mono">0.6 A</span>, &eta;<sub>max</sub> 36&nbsp;%. Encoder: quadrature push-pull 0/24 V, <span class="mono">&le;1 kHz</span>.</li>
      <li>Mini switch <span class="mono">30&times;15&times;7.5</span>; phototransistor <span class="mono">15&times;15&times;7.5</span>.</li>
      <li>Q3 drives <em>towards the rack</em>, Q4 <em>towards the conveyor</em> &mdash; so rack and belt sit at opposite ends of the travel axis.</li>
      <li>I2 is the <em>inner</em> light barrier, I3 the <em>outer</em> one.</li>
    </ul>
  </div>
  <div>
    <h3><span class="k ded"></span>Deduced from the photos</h3>
    <p>From p.5 of the extended description and Abb. 7 / p.26 of the booklet:</p>
    <ul>
      <li>Four black posts &rarr; three bays; three shelf levels &rarr; nine slots.</li>
      <li>Workpieces sit <strong>directly on paired red shelf brackets</strong> &mdash; there is no pallet or tray in this module.</li>
      <li>The crane is a travelling mast on a front rail: spindle + guide rod, motor at the far end.</li>
      <li>The crane is visibly taller than the rack.</li>
    </ul>
  </div>
  <div>
    <h3><span class="k ass"></span>Assumed &mdash; needs your confirmation</h3>
    <p><strong>No supplied document contains a single dimension of the model.</strong> Every length below is
    my choice on the fischertechnik 15&nbsp;mm raster, anchored to the 600&times;400 module plate:</p>
    <ul>
      <li>Bay pitch and row pitch both <span class="mono">120</span>; row A at <span class="mono">z&nbsp;40</span>.</li>
      <li>Workpiece <span class="mono">&Oslash;45 &times; 20</span> (body 16 + lid 4).</li>
      <li>Belt surface at <span class="mono">z&nbsp;100</span>; belt runs along +Y.</li>
    </ul>
  </div>
</section>

<h2 style="margin-bottom:6px">Arrangement</h2>
<p class="col" style="margin:0 0 24px;color:var(--ink-2)">Your top view settles the one thing the manuals
never did: the rack and the conveyor sit on the <strong>same side</strong> of the picker rail, with the
conveyor beyond the rack along the travel axis. That is exactly what the Belegungsplan means by
Q3 <em>&ldquo;horizontal towards the rack&rdquo;</em> and Q4 <em>&ldquo;towards the conveyor&rdquo;</em> &mdash;
they are the two ends of the travel axis. It also means the Ausleger telescopes <strong>one way only</strong>,
and one stop (115&nbsp;mm) serves a rack bay and the belt hand-over alike. The warehouse is designed and proven
in its own module frame; putting it on the table is a rigid 90&deg; transform, which cannot introduce
interference, so the clearance proof carries over untouched.</p>

<h2 style="margin-bottom:6px">Drawings</h2>
<p class="col" style="margin:0 0 24px;color:var(--ink-2)">Every rectangle is a real solid from the model
&mdash; hover any of them for its name, size and I/O tag. Green = sensor, black = motor,
red = fischertechnik red parts, pale = aluminium/steel/white.</p>
<div class="sheets">__SHEETS__</div>

<h2 style="margin-bottom:6px">Component list</h2>
<p class="col" style="margin:0 0 26px;color:var(--ink-2)">170 solids in eleven assemblies. Repeated
parts are collapsed into one row with a quantity.</p>
__GROUPS__

<h2 style="margin:44px 0 6px">Axes &amp; stops</h2>
<div class="tw" style="margin-bottom:40px"><table>
<thead><tr><th>Axis</th><th>Motor</th><th>Encoder</th><th>Reference</th><th>Range mm</th><th>Named stops</th><th>Drive</th></tr></thead>
<tbody>
<tr><td class="nm">travel</td><td><span class="tag io-out">Q3/Q4</span></td><td><span class="tag io-in">B1/B2</span></td><td><span class="tag io-in">I1</span> at the conveyor end</td><td class="mono">120 &hellip; 665</td><td class="mono">bays 120 / 240 / 360 / 480 &middot; belt 665 (past the rack)</td><td class="mono">spindle, 4 mm lead</td></tr>
<tr><td class="nm">lift</td><td><span class="tag io-out">Q5/Q6</span></td><td><span class="tag io-in">B3/B4</span></td><td><span class="tag io-in">I4</span> at the mast top</td><td class="mono">80 &hellip; 360</td><td class="mono">rows under/lift 100&middot;120 / 220&middot;240 / 340&middot;360 &middot; belt 80&middot;100 &middot; transit 260</td><td class="mono">spindle, 4 mm lead</td></tr>
<tr><td class="nm">Ausleger</td><td><span class="tag io-out">Q7/Q8</span></td><td>&mdash;</td><td><span class="tag io-in">I5</span> vorne &middot; <span class="tag io-in">I6</span> hinten</td><td class="mono">0 &hellip; 115</td><td class="mono">retracted 0 &middot; <strong>115 serves a bay AND the belt</strong></td><td class="mono">spindle, 4 mm lead</td></tr>
<tr><td class="nm">belt</td><td><span class="tag io-out">Q1/Q2</span></td><td>&mdash;</td><td><span class="tag io-in">I2</span> inner &middot; <span class="tag io-in">I3</span> outer &middot; <span class="tag io-in">A1/A2</span> trail</td><td class="mono">320 long</td><td class="mono">crane hand-over y 325 &middot; tunnel &middot; VGR hand-over y 580</td><td class="mono">&Oslash;20 stub-axle drums</td></tr>
</tbody></table></div>

<h2 style="margin-bottom:6px">The mould cycle</h2>
<p class="col" style="margin:0 0 20px;color:var(--ink-2)">Twelve slots, twelve moulds &mdash; but one mould is
always the one in circulation, so at rest eleven are stowed and exactly one slot is free. That free slot is
what makes the rule work: a mould whose cookie the VGR has taken comes back and goes into whichever slot has
no mould. Without it the machine would have nowhere to put the empty mould.</p>
<div class="tw" style="margin-bottom:40px"><table>
<thead><tr><th>#</th><th>Who</th><th>What happens</th><th>Where</th></tr></thead>
<tbody>
<tr><td class="qty">1</td><td class="nm">crane</td><td>Fork enters the bay under the mould, lifts 10 mm, retracts</td><td class="mono">bay, row B</td></tr>
<tr><td class="qty">2</td><td class="nm">crane</td><td>Telescopes &minus;Y (I6) over the belt, lowers through the 40 mm gap &mdash; mould released</td><td class="mono">y 245</td></tr>
<tr><td class="qty">3</td><td class="nm">belt Q1</td><td>Carries the mould forward through the identification tunnel</td><td class="mono">y 245 &rarr; 75</td></tr>
<tr><td class="qty">4</td><td class="nm">VGR</td><td>Lifts the cookie out of the mould, bound for the oven / sorting station</td><td class="mono">y 75</td></tr>
<tr><td class="qty">5</td><td class="nm">belt Q2</td><td>Reverses, returning the EMPTY mould to the crane</td><td class="mono">y 75 &rarr; 245</td></tr>
<tr><td class="qty">6</td><td class="nm">crane</td><td>Picks the empty mould up and stows it in the slot that had none</td><td class="mono">C4</td></tr>
</tbody></table></div>

<div class="two">
  <div class="pass">
    <h3>What the model proves</h3>
    <div class="check"><b>PASS</b><span>96 poses across five travel columns &times; eight lift heights &times; five fork extensions &mdash; no two solids interpenetrate anywhere in the working envelope.</span></div>
    <div class="check"><b>PASS</b><span>Every one of the 183 solids either stands on something or is a declared, bolted cantilever &mdash; see the grounding section below.</span></div>
    <div class="check"><b>PASS</b><span>Nothing crosses the 600 &times; 400 plate boundary.</span></div>
    <div class="check"><b>RULE</b><span>Two interlocks fall out of the geometry rather than being imposed: at a rack column the fork may only telescope when the table is within &plusmn;12&nbsp;mm of a shelf, and over the belt it must cross the pulleys in the transit band (<span class="mono">lift &ge; 112</span>) before dropping into the gap.</span></div>
    <div class="check"><b>DRIVE</b><span>All three axes are spindle-driven at a 4&nbsp;mm lead: the travel screw along the front rail, the lift screw in the mast, and the Ausleger screw inside stage&nbsp;1 &mdash; 50&nbsp;mm of its thread stays exposed, and it stops at <span class="mono">y&nbsp;275</span> so it never enters a bay or the belt. The conveyor is two parallel strips on &Oslash;20 drums, driven through a right-angle crown gear off Q1/Q2, and runs both ways.</span></div>
  </div>
  <div class="pass">
    <h3>The three clearances that set every other number</h3>
    <div class="check"><b>30 / 24</b><span>The gap between a bay's two shelf brackets is 30&nbsp;mm; the fork table is 24&nbsp;mm. 3&nbsp;mm each side. This single pair is why the fork can lift from below at all.</span></div>
    <div class="check"><b>45 / 30</b><span>The workpiece is &Oslash;45 over a 30&nbsp;mm gap, so it rests on 7.5&nbsp;mm of each bracket &mdash; enough to seat, not enough to foul the fork.</span></div>
    <div class="check"><b>40 / 32</b><span>Shelf gap and belt gap are both 40&nbsp;mm; the fork table is 32. The arm (28) shares the table's z band rather than riding above it, so both pass the same gap and both stay under the mould.</span></div>
    <div class="check"><b>60 / 40</b><span>The mould is 60&nbsp;mm wide over that 40&nbsp;mm gap &mdash; 10&nbsp;mm of bearing on each bracket.</span></div>
    <div class="check"><b>y 580</b><span>The tunnel deliberately STARTS at y=580, past the far end of the extended telescope at y=555. Any nearer and the crane could not descend to the belt without a forbidden lift band.</span></div>
    <div class="check"><b>stub</b><span>Each belt strip has its own drum on a stub axle. A through shaft would have crossed the 40&nbsp;mm gap and blocked the fork.</span></div>
    <div class="check"><b>60 / 90</b><span>The mast STRADDLES the load &mdash; tubes at &plusmn;45 around a 60&nbsp;mm mould, carriage split into two legs with the yoke above the cookie. A mast as wide as the mould swallowed it whenever the fork retracted.</span></div>
    <div class="check"><b>ONLY</b><span><code>check_carry()</code> asserts the carried mould touches the fork table's top face and <em>nothing else</em>. The <code>(mould, fork)</code> pair is deliberately not whitelisted &mdash; that whitelist being too broad is how the mould sank into the arm unnoticed.</span></div>
  </div>
</div>


<h2 style="margin:44px 0 6px">The VGR, and the hand-over</h2>
<p class="col" style="margin:0 0 22px;color:var(--ink-2)">Cylindrical R&ndash;P&ndash;P, because the
Belegungsplan has an explicit <em>&ldquo;Motor drehen im/gegen Uhrzeigersinn&rdquo;</em>: swivel
<span class="tag io-out">Q5/Q6</span>, reach <span class="tag io-out">Q3/Q4</span>, plunge
<span class="tag io-out">Q1/Q2</span>, plus <span class="tag io-out">Q7</span> compressor and
<span class="tag io-out">Q8</span> vacuum valve. 24 solids, 54 poses, all clear. The cup&rsquo;s underside is
at <span class="mono">plunge &minus; 28</span> &mdash; that is the pick plane.</p>

<div class="two">
  <div class="pass">
    <h3>Stations are solved, not typed</h3>
    <p class="grp-sub">One function turns a point on the table into VGR joint values, and the export takes
    its stops from there &mdash; so the gripper&rsquo;s idea of where the hand-over is cannot drift from the
    conveyor&rsquo;s.</p>
    <div class="check"><b>PASS</b><span><b>belt</b> &rarr; target <span class="mono">(635, 695)</span>, swivel <span class="mono">91.33&deg;</span>, reach <span class="mono">90</span> (215&nbsp;mm away)</span></div>
<div class="check"><b>OPEN</b><span><b>sorting</b> &rarr; target <span class="mono">(125, 655)</span>, swivel <span class="mono">-83.23&deg;</span>, reach <span class="mono">172</span> (297&nbsp;mm away)</span></div>
<div class="check"><b>OPEN</b><span><b>oven</b> &rarr; target <span class="mono">(325, 225)</span>, swivel <span class="mono">-11.55&deg;</span>, reach <span class="mono">350</span> (475&nbsp;mm away)</span></div>
    <div class="check"><b>PASS</b><span>Every solved pose puts the cup on its target to better than
    0.01&nbsp;mm, and the arm at the belt hand-over does not touch the warehouse &mdash; the first
    cross-module check in the project.</span></div>
  </div>
  <div class="pass">
    <h3>What the arm cannot yet reach</h3>
    <p class="grp-sub">The cup sweeps an annulus 125&hellip;245&nbsp;mm about the tower. Footprint centres are
    placeholders, so what matters is whether <em>any</em> of a station falls inside it.</p>
    <div class="check"><b>PART</b><span><b>7 sorting</b> &mdash; nearest corner <span class="mono">190</span>, farthest <span class="mono">477</span> mm</span></div>
<div class="check"><b>NONE</b><span><b>6 oven</b> &mdash; nearest corner <span class="mono">300</span>, farthest <span class="mono">702</span> mm</span></div>
    <div class="check"><b>OPEN</b><span>The oven is out of reach entirely at this placement. Before it is
    designed, either its hand-over port comes to the near edge, the tower moves, or the arm gets a longer
    stroke. Flagged rather than guessed &mdash; and the check fails loudly if a port is ever put somewhere
    the arm cannot go.</span></div>
  </div>
</div>


<h2 style="margin:44px 0 6px">Brennofen &mdash; ft 536632</h2>
<p class="col" style="margin:0 0 22px;color:var(--ink-2)">45 solids, 72 poses, all clear. The whole
Belegungsplan is present: 9 inputs, 14 outputs. What stands out reading it is what this module
<em>lacks</em> &mdash; <strong>no encoders anywhere</strong>. Every axis runs to a reference switch, so unlike
the warehouse and the gripper you cannot ask it where it is, only whether it has arrived. That is a different
control problem, and it is worth knowing before any of it is programmed.</p>
<div class="two">
  <div class="pass">
    <h3>Two interlocks, both geometric</h3>
    <div class="check"><b>PROVEN</b><span>The Ofenschieber never travels with the Ofent&uuml;r shut. Remove the
    rule and the checker reports 18 tray-versus-door collisions &mdash; the shut door physically blocks the
    mouth the tray passes through, so this is geometry, not an assertion.</span></div>
    <div class="check"><b>PROVEN</b><span>Q12 only lowers <em>at</em> a station and only as far as that
    station's surface. Mid-travel the cup would be dragged through the turntable, its motor and the pusher.</span></div>
    <div class="check"><b>WHY</b><span>The Brennofen is <strong>elevated</strong> on a pedestal, as Abb. 9 shows.
    That is not decoration: it puts the hand-over at <span class="mono">z&nbsp;110</span>, near the belt's 100, so
    the VGR reaches it with its arm well under the oven's own Sauger portal. At the original z&nbsp;20 the arm
    fouled that portal, and the cross-module check caught it.</span></div>
  </div>
  <div class="pass">
    <h3>Where two modules had to agree</h3>
    <div class="check"><b>RULE</b><span>In the chained configuration (booklet p.15) the VGR serves the oven, so
    the station's <em>own</em> Sauger has to park at the turntable. Both grippers otherwise want the same spot
    over the extended tray. That rule is now enforced by the cross-module check rather than assumed.</span></div>
    <div class="check"><b>BAND</b><span>The VGR works in a plunge <em>band</em> at each station, not at a single
    stop: above the belt structure at the conveyor (<span class="mono">140&hellip;320</span>), under the oven's
    portal rail at the oven (<span class="mono">140&hellip;210</span>).</span></div>
    <div class="check"><b>PASS</b><span>Neither hand-over produces contact between any two modules, tested with
    proper oriented boxes &mdash; a long arm at 45&deg; has an enormous axis-aligned box and the conservative
    test reported hits that were not there.</span></div>
  </div>
</div>


<h2 style="margin:44px 0 6px">Swept-path check</h2>
<p class="col" style="margin:0 0 22px;color:var(--ink-2)">Checking named stops is not enough. A load can be
clear at both ends of a move and pass straight through a rack post in between &mdash; and a renderer can draw it
somewhere the model never put it. This walks the real cycle, <strong>exactly</strong> &mdash; no sampling
at all. Every joint is a pure translation, so each box moves in a straight line and the overlap condition on each
axis is a linear inequality in <em>t</em>; the time interval is solved for and the three axes intersected. A thin
part moving fast can no longer slip between samples, because there are none.</p>
<div class="two">
  <div class="pass">
    <h3>What was actually wrong</h3>
    <div class="check"><b>FOUND</b><span>The carried mould was drawn at fork-frame <span class="mono">y=360</span>
    while the fork table had moved to <span class="mono">y=210</span> &mdash; <strong>150&nbsp;mm deeper into the
    rack than the fork</strong>, straight through the stored moulds. A literal that did not follow
    <code>RAIL_Y</code>, the same shape of bug as the mast tubes earlier. It now reads the fork table part's own
    geometry, so it cannot drift again.</span></div>
    <div class="check"><b>WHY BLIND</b><span>The checks could not have caught it: the carried mould was in the
    same group as the <em>stored</em> moulds, so <code>(mould, rack)</code> and <code>(mould, mould)</code> were
    whitelisted for it too. A load in transit now has its own groups &mdash; it may rest on the fork table and
    carry its own cookie, nothing else.</span></div>
  </div>
  <div class="pass">
    <h3>Three more the sweep turned up</h3>
    <div class="check"><b>FIXED</b><span>Whether the fork is carrying is now <em>derived from the pose</em>
    &mdash; the load is on the fork exactly while the table top is above the surface it rests on. Flagged per
    leg, the transfer happened at the end of a move instead of at the instant of contact, and the load was
    modelled sinking through the belt.</span></div>
    <div class="check"><b>FIXED</b><span>A <strong>loaded</strong> VGR may not bottom out: the cookie hangs from
    <span class="mono">plunge&minus;48</span> and below the carry floor it is down at the level of M3, which lies
    flat across the base.</span></div>
    <div class="check"><b>FIXED</b><span>The oven's Sauger was stopping at the tray <em>surface</em>. With a
    workpiece on the tray that drives the cup straight through the part it is there to pick up &mdash; it stops
    at the workpiece top now.</span></div>
  </div>
</div>


<h2 style="margin:44px 0 6px">Sortierstrecke mit Farberkennung &mdash; ft 536633</h2>
<p class="col" style="margin:0 0 22px;color:var(--ink-2)">55 solids, all clear. Belt, colour sensor, three
pneumatic ejectors, three Lagerstellen. The booklet&rsquo;s <em>Erste Schritte</em> says the workpieces
<strong>start</strong> in these bays and the VGR collects them from here &mdash; that is what closes the factory
loop, so they are modelled sitting in place.</p>
<div class="two">
  <div class="pass">
    <h3>What the datasheet changes</h3>
    <div class="check"><b>128599</b><span>The Farbsensor is <strong>expressly not an RGB sensor</strong>. An LED
    shines and a phototransistor measures how much comes back, so &ldquo;similar colours can produce similar
    values&rdquo;, and the reading depends on ambient light <em>and on the distance to the object</em>. The
    sensor&rsquo;s standoff is therefore a real design parameter &mdash; <span class="mono">SENSOR_GAP =
    25&nbsp;mm</span> above the workpiece top &mdash; not a placement convenience.</span></div>
    <div class="check"><b>0&ndash;2 / 0&ndash;10</b><span>The sensor outputs <span class="mono">0&ndash;2 VDC</span>
    in millivolts, but terminal 9 is specified <span class="mono">0&ndash;10 VDC</span>: the 24&nbsp;V adapter PCB
    scales it. Anything reading the raw sensor must not assume the terminal&rsquo;s range.</span></div>
    <div class="check"><b>NO FEEDBACK</b><span>I1 is an <em>Impulstaster</em> &mdash; the only travel feedback on
    the module. No encoder, so the controller counts pulses from the inlet barrier to know which ejector to fire.
    Neither this module nor the oven has a single encoder between them.</span></div>
  </div>
  <div class="pass">
    <h3>Placement, solved</h3>
    <div class="check"><b>-125&deg;</b><span>The VGR&rsquo;s swivel range had to widen from &minus;95&deg; to
    &minus;125&deg;: the three Lagerstellen sit at &minus;94, &minus;104 and &minus;113&deg;. The station solver
    said so &mdash; nobody guessed it, and the old limit would have silently put two of the three bays out of
    reach.</span></div>
    <div class="check"><b>PASS</b><span>All five hand-overs now solve inside the envelope: belt, oven, and the
    three bays. Every solved pose lands on its target to better than 0.01&nbsp;mm, and none of them produces
    contact between modules.</span></div>
    <div class="check"><b>ONE AT A TIME</b><span>The three ejectors share one compressor and each sweeps the full
    belt width, so the model refuses any pose with two extended.</span></div>
  </div>
</div>


<h2 style="margin:44px 0 6px">Twelve cookies, one schedule</h2>
<p class="col" style="margin:0 0 22px;color:var(--ink-2)">The pipeline runs all twelve cookies through
warehouse &rarr; conveyor &rarr; VGR &rarr; oven &rarr; sorting line &rarr; Lagerstelle, and the three that
start in the bins back into the warehouse: <span class="mono">69 transfers, 31 scheduler rounds</span>, every
cookie ending in its own bin.</p>
<div class="two">
  <div class="pass">
    <h3>Why these three flavours</h3>
    <p class="grp-sub">The Farbsensor is not an RGB sensor &mdash; it measures how much light comes back. So the
    flavours are chosen to separate on <em>reflected brightness</em>, which is the only thing the hardware can
    actually see.</p>
    <div class="check"><b style="color:#4A2C17">&#9632;</b><span><b>chocolate</b> &mdash; 4 in the system, nominal Farbsensor reading <span class="mono">~340 mV</span>, sorted to the <span class="mono">blau</span> bin</span></div><div class="check"><b style="color:#D9536F">&#9632;</b><span><b>strawberry</b> &mdash; 4 in the system, nominal Farbsensor reading <span class="mono">~950 mV</span>, sorted to the <span class="mono">rot</span> bin</span></div><div class="check"><b style="color:#EFE0B0">&#9632;</b><span><b>vanilla</b> &mdash; 4 in the system, nominal Farbsensor reading <span class="mono">~1660 mV</span>, sorted to the <span class="mono">weiss</span> bin</span></div>
  </div>
  <div class="pass">
    <h3>Deadlock freedom, by construction</h3>
    <div class="check"><b>RULE</b><span>Exactly twelve cookies exist. They are created in <code>pipeline.py</code> and nowhere else &mdash; <code>hbw_model</code> and <code>sorting_model</code> take their placement from it, so a scene cannot quietly make it thirteen.</span></div><div class="check"><b>RULE</b><span>Every transfer is atomic: all locks taken at once, released at the end. Without hold-and-wait a deadlock cannot form at all &mdash; two of Coffman&rsquo;s four conditions are structurally impossible.</span></div><div class="check"><b>RULE</b><span>Locks are acquired in one fixed total order over resources, so no circular wait either.</span></div><div class="check"><b>RULE</b><span>A move never starts unless its destination has room &mdash; the rule that stops a gripper lifting a cookie with nowhere to put it down.</span></div><div class="check"><b>RULE</b><span>Every pose the schedule commands is checked against the module geometry, in the same run that proves the moulds do not sweep through the rack.</span></div>
  </div>
</div>
<div class="pass" style="margin-bottom:46px">
  <h3>The deadlock the detector actually found</h3>
  <div class="check"><b>FOUND</b><span>A first draft modelled &ldquo;on the fork&rdquo; as a schedulable state.
  The safety checker immediately caught <strong>two cookies being put on one fork</strong> &mdash; that is
  hold-and-wait, and removing it (transfers became atomic place-to-place moves) removed the whole class.</span></div>
  <div class="check"><b>FOUND</b><span>Then the wait-for graph closed a cycle between the oven tray and the oven
  chamber: <strong>the baked cookie could not leave the chamber because the tray was occupied, and the tray&rsquo;s
  cookie could not go in because the chamber was.</strong> That is a real deadlock in the <em>process</em>, not in
  the code. The oven is a single-part station, so tray and chamber are now excluded together.</span></div>
  <div class="check"><b>NOTE</b><span>Both were found by running the thing, not by reading it. A schedule that
  looks obviously fine on paper had two ways to wedge itself solid.</span></div>
</div>


<!-- GROUNDING_SECTION -->
<h2 style="margin:44px 0 6px">Why modules looked like they were floating</h2>
<p class="col" style="margin:0 0 22px;color:var(--ink-2)">The support test each model had only asked
<em>&ldquo;does this part touch the thing it names?&rdquo;</em> &mdash; and naming <code>plate</code> skipped even
that. A part could declare the base plate as its support while floating 90&nbsp;mm above it and pass every check.</p>
<div class="two">
  <div class="pass">
    <h3>The rule now</h3>
    <div class="check"><b>PLATE</b><span>If a part names the plate, its underside must actually <em>be</em> on the
    plate. No exceptions, no free pass.</span></div>
    <div class="check"><b>BELOW</b><span>Otherwise it must touch its support <em>and</em> have solid material
    directly beneath its footprint&hellip;</span></div>
    <div class="check"><b>OR BOLTED</b><span>&hellip;or be explicitly declared a <strong>cantilever</strong> &mdash;
    bolted to a vertical face, which is how ft shelf brackets, rods in bearing blocks and sensor mounts genuinely
    work. A cantilever needs at least 40&nbsp;mm&sup2; of real face contact, so a part touching along an edge cannot
    pass itself off as bolted.</span></div>
  </div>
  <div class="pass">
    <h3>What it found</h3>
    <div class="check"><b>13</b><span>Genuinely airborne while claiming the plate: the oven&rsquo;s whole conveyor
    frame and its motor, the Ofenschieber rail and its drive, the turntable pusher, the sorting line&rsquo;s belt
    motor and all three ejector cylinders, the VGR&rsquo;s swivel motor. Each now has a real leg, pedestal or
    bracket.</span></div>
    <div class="check"><b>2</b><span>Edge-supported: the oven&rsquo;s door guides hung off the lip of the chamber
    floor with zero face contact. They stand on it now.</span></div>
    <div class="check"><b>76</b><span>The rest are legitimate cantilevers, now declared as such rather than passing
    silently.</span></div>
  </div>
</div>

<h2 style="margin-bottom:16px">Before I cut the FreeCAD geometry</h2>
<div class="col">
  <div class="q"><h3>0 &nbsp;Files to open</h3>
  <p><code>STF_Factory.gltf</code> is the whole table, articulated: FreeCAD imports it as 278 named
  objects, and the joint nodes (<code>J1_Travel_X</code>, <code>J2_Lift_Z</code>, <code>J3_Ausleger_Y</code>,
  <code>J_Swivel</code>, <code>J_Plunge</code>, <code>J_Reach</code>) let you pose it. For <strong>exact</strong>
  geometry use <code>STF_HBW.step</code> instead &mdash; glTF is a mesh format and turns every cylinder into a
  32-gon, so it is the wrong file if you want true B-rep precision.</p></div>

  <div class="q"><h3>1 &nbsp;The four cover sensors have nowhere to plug in</h3>
  <p>The stock 536631 board has eight digital inputs and they are all spoken for &mdash; I1&hellip;I6 plus the
  A1/A2 trail sensor. The four sensors at the inside corners of the tunnel are therefore <strong>beyond the
  536631 I/O</strong>: they need the adapter PCB's spare terminals or a RevPi AIO module, and the colour
  sensor specifically needs an analogue input (0&ndash;2&nbsp;V), which this module does not have at all.
  Tell me which route you want and I will wire it into the I/O map.</p></div>

  <div class="q"><h3>2 &nbsp;Three measurements still pin the whole model</h3>
  <p>Bay pitch centre-to-centre, shelf pitch centre-to-centre, and the outside diameter and height of
  one workpiece. With those three I can rescale everything else off the raster in one pass.</p></div>

  <div class="q"><h3>3 &nbsp;Two numbers in the layout contradict the motor datasheet</h3>
  <p>The datasheet caps the motor at <span class="mono">0.6 A</span>, but
  <code>factory.layout.yaml</code> models <code>HBW_X</code> and <code>HBW_Y</code> at
  <span class="mono">1.5 A</span> running &mdash; two and a half times the motor's own maximum. And a
  <span class="mono">440 rpm</span> no-load motor behind the recorded <span class="mono">25:1</span> gearbox
  gives about <span class="mono">18 rpm</span> at the spindle, not the <span class="mono">214 rpm</span> the
  drive block assumes. The <span class="mono">14.27 mm/s</span> lab figure and the pulse rate are
  self-consistent, so the suspect value is the gear ratio. Worth checking against the real machine before
  Level&nbsp;3, because the current draw feeds the electrical model.</p></div>

  <div class="q"><h3>4 &nbsp;One deviation I made on purpose</h3>
  <p>The real lift motor drives the vertical spindle through a right-angle crown gear on the mast top
  plate. I have it mounted vertically, direct-drive &mdash; same envelope, far simpler geometry. Tell me if
  you want the crown gear modelled for shape fidelity.</p></div>
</div>

<footer>
  <p>Generated from <span class="mono">hbw_model.py</span> &mdash; the drawings, the component list and the
  clearance proof all read the same parameter table, so none of them can drift apart.
  Sources: 536634 Belegungsplan p.4 &middot; extended description p.5 &middot; Fabrik-Simulation booklet p.22/26 &middot;
  datasheets 144643, 37783, 36134, 128599.</p>
</footer>
</div>
"""
HTML = HTML.replace("__SHEETS__", "\n".join(sheets_html)).replace("__GROUPS__", "\n".join(groups_html))
open("hbw_sheet.html", "w").write(HTML)
print("wrote hbw_sheet.html", len(HTML))
