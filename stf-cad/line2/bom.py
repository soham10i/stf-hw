"""
STF-2 bill of materials - derived from line_model + joints + plc_io (never typed).

  bom/profile_cutlist.csv   every aluminium profile: section, cut length, end taps per end
  bom/bom.csv               everything to buy / make: profiles (by the metre), bought
                            mechanics, machined parts (with their hole count), fasteners
                            (modelled + bought kits), electrics, pneumatics, cables
  bom/index.html            the same, readable

Every quantity is counted from the model; every catalogue item carries its source tag
from hardware.py ([typ] = verify on the part bought).
"""
import csv
import html
import math
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hardware
import joints
import line_model
import plc_io

OUT = os.path.join(HERE, "bom")
KERF = 3.0                 # saw kerf + squaring allowance per cut (mm) [typ]
BAR = 6000.0               # profile stock length (mm) [cat: misumi / item][typ]


def _src(hw):
    for table in (hardware.STEPPER, hardware.GEARBOX, hardware.MGN, hardware.LEADSCREW, hardware.BEARING, hardware.FIELD, hardware.LOADS, hardware.BECKHOFF, hardware.PSU, hardware.SAFE):
        for k, v in table.items():
            if isinstance(k, str) and len(k) >= 3 and k in hw and isinstance(v, dict):
                return v.get("src", "[cat]")
    for k in ("CHAIN", "BEND", "DRIVE_UNIT", "TUBE", "GUIDE_BAR", "TABLE_PLATE", "VALVE_ISLAND", "AIR"):
        if k in hw:
            return getattr(hardware, k).get("src", "")
    if hw.startswith("ISO6432"):
        return "[ISO 6432][typ lengths]"
    if hw == "guard door kit":
        return hardware.SAFE["door"]["src"]
    return "[design]"


def build():
    parts = line_model.build(with_product=False)
    fails, B = joints.check(verbose=False)
    if fails:
        raise SystemExit(f"REFUSING: joints fail ({fails[0]})")
    if plc_io.check(verbose=False):
        raise SystemExit("REFUSING: plc_io fails")
    if line_model.L.get("SAFE1"):
        import safety
        if safety.check(verbose=False)[0]:
            raise SystemExit("REFUSING: safety proofs fail")
    rows = []

    def add(cat, item, spec, qty, unit="pcs", src=""):
        rows.append(dict(category=cat, item=item, spec=spec, qty=qty, unit=unit, source=src))

    # --- profiles: cut list with end taps (from the fasteners that thread into a profile END)
    taps = defaultdict(lambda: [0, 0])
    for f in B.fasteners:
        p = next((q for q in parts if q.name == f.into), None)
        if p is None or not joints.is_profile(p):
            continue
        ser, ax = joints.section(p)
        i = [abs(v) for v in f.axis].index(1.0)
        if i != ax:
            continue
        end = 0 if f.axis[i] > 0 else 1              # screw pointing +axis enters the MIN end
        taps[p.name][end] += 1
    cut = Counter()
    metres = Counter()
    for p in parts + [b for b in B.brackets if joints.is_profile(b)]:
        if not joints.is_profile(p):
            continue
        ser, ax = joints.section(p)
        sec = p.mech.split(":")[1]
        Ln = round(p.s[ax], 1)
        t0, t1 = taps.get(p.name, [0, 0])
        core = hardware.PROFILE[ser]["core_tap"]
        mach = " + ".join(x for x in (f"end A {t0}x {core}" if t0 else "", f"end B {t1}x {core}" if t1 else "") if x)
        cut[(sec, Ln, mach or "plain")] += 1
        metres[sec] += Ln + KERF
    with open(os.path.join(OUT, "profile_cutlist.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["section", "series", "length_mm", "end machining", "qty"])
        for (sec, Ln, mach), q in sorted(cut.items()):
            w.writerow([sec, hardware.SECTION[sec][0], Ln, mach, q])
    for sec, mm in sorted(metres.items()):
        bars = math.ceil(mm / BAR * 1.1)                  # 10 % nesting loss
        add("profile", f"B-type profile {sec}", f"{hardware.PROFILE[hardware.SECTION[sec][0]]['series'].split('-')[0]}-{sec}, "
            f"{mm / 1000:.2f} m cut ({sum(q for (s, _, _), q in cut.items() if s == sec)} pieces) -> {bars} x 6 m",
            round(mm / 1000, 2), "m", hardware.PROFILE[hardware.SECTION[sec][0]]["src"])
    # --- bought mechanics (by catalogue key), machined parts (with holes)
    holes = Counter()
    for f in B.fasteners:
        for n in f.through:
            holes[n] += 1
        if not f.into.startswith("TNUT") and f.into != "NUT":
            holes[f.into] += 1
    bought, machined = Counter(), defaultdict(list)
    skip_groups = ("stock", "tray", "puck", "cookie", "port")
    seen_body = set()
    for p in parts:
        if joints.is_profile(p) or p.group in skip_groups or not p.hw or p.group == "chain":
            continue
        bn = joints.body_of(p)
        if bn != p.name:                       # a hollow body / bent bracket counts once
            if bn in seen_body:
                continue
            seen_body.add(bn)
        if joints.machined(p) or "sheet" in p.hw or "panel" in p.hw or p.hw.startswith(("PC ", "POM", "Al ")):
            b = p.aabb()
            dims = " x ".join(f"{b[i + 3] - b[i]:.1f}" for i in range(3))
            machined[(p.hw, dims)].append((p.name, holes.get(p.name, 0)))
            continue
        spec = p.hw
        if p.hw in hardware.SAFE:
            spec = f"{p.hw}: {hardware.SAFE[p.hw]['desc']}"
        if p.hw == "guard door kit":
            spec = f"{hardware.SAFE['door']['desc']}, leaf {p.s[0]:.0f} x {p.s[2]:.0f}"
        if "rail" in p.hw and "MGN" in p.hw:
            spec = f"{p.hw}, L = {max(p.s):.0f} mm"
        if p.hw in ("GUIDE_BAR",):
            spec = f"{hardware.GUIDE_BAR['desc']}, L = {max(p.aabb()[3] - p.aabb()[0], p.aabb()[4] - p.aabb()[1]):.0f} mm"
        src = _src(p.hw)
        if p.hw == "tubular":                    # band oven element: the catalogue item oven.py chose
            e = plc_io._oven_tables()[0][p.tag]
            spec, src = e["cat"]["model"], e["cat"]["src"]
        if p.hw in ("OVEN_FAN", "COOL_FAN", "BAND_MESH"):
            spec, src = getattr(hardware, p.hw)["desc"], getattr(hardware, p.hw)["src"]
            if p.hw == "BAND_MESH":
                if p.name != "band_carry":
                    continue
                spec += f", {line_model.band_w():.0f} wide, endless {2 * (line_model.stations()['e'] - line_model.stations()['x0']) / 1000 + math.pi * line_model.L['BAND']['drum'] / 1000:.2f} m"
        bought[(spec, src)] += 1
    add("bought", "side-flex chain", f"{hardware.CHAIN['desc']}, {line_model.loop_len() / 1000:.2f} m + take-up", 1, "loop",
        hardware.CHAIN["src"])
    for (spec, src), q in sorted(bought.items()):
        add("bought", spec.split(",")[0], spec, q, "pcs", src)
    for (hw, dims), lst in sorted(machined.items()):
        add("make", hw, f"{dims} mm, {sum(h for _, h in lst)} holes total ({', '.join(n for n, _ in lst[:4])}"
            f"{' ...' if len(lst) > 4 else ''})", len(lst), "pcs", "[design] machined / cut to the drawing")
    # --- fasteners: modelled + kits
    for (k, kind), q in joints.bom(B).items():
        add("fastener" if kind in ("screw", "washer", "nut") else "bracket", k, kind, q, "pcs",
            hardware.THREAD_SRC if kind in ("screw", "washer", "nut") else hardware.BRACKET.get(k, {}).get("src", "[typ]"))
    kit = Counter()
    for a, b, why, n in B.kits:
        kit[why] += 1
    for why, q in sorted(kit.items()):
        add("kit", why.split(" (")[0], f"{why} - fasteners NOT modelled", q, "joints", "[bought kit][typ]")
    # --- electrics: from the PLC layout
    ios = plc_io.IOS
    rails, _, _ = plc_io.terminals(ios)
    et = Counter(t for rail in rails for t, n, _ in rail)
    for t, q in sorted(et.items()):
        add("electric", f"Beckhoff {t}", hardware.BECKHOFF[t]["desc"], q, "pcs", hardware.BECKHOFF[t]["src"])
    lay, _, dims = plc_io.cabinet(rails)
    dev = Counter((d["type"], d["note"] if d["type"] in ("SSR DC", "MCB") else "")
                  for r in lay for d in r["devices"] if d["type"] not in hardware.BECKHOFF)
    for (t, note), q in sorted(dev.items()):
        spec = {"contactor": hardware.SAFE["contactor"]["desc"], "STL": hardware.SAFE["stl"]["desc"],
                "PTTB 2.5": hardware.TERMINAL_BLOCK2["model"], "zone contactor": hardware.ZONE_CONTACTOR["desc"],
                "SSR AC 25 A": hardware.SSR_AC25["model"], "relay 6.2": hardware.RELAY6["model"], "MCB 3-pole": hardware.MCB3["model"],
                "main switch": hardware.SUPPLY["desc"], "current transducer": hardware.CT_AC["model"]}.get(t, note or t)
        src = {"contactor": hardware.SAFE["contactor"]["src"], "STL": hardware.SAFE["stl"]["src"], "current transducer": hardware.CT_AC["src"]}.get(
            t, "[cat: meanwell]" if t.startswith("SDR") else "[typ]")
        add("electric", t, spec, q, "pcs", src)
    add("electric", "enclosure", f"sheet steel {line_model.L['CAB'][2]:g} x {line_model.L['CAB'][3]:g} x {line_model.L['CAB'][4]:g}, "
        f"filter fan {hardware.THERMAL['fan_m3h']:g} m3/h + grille", 1, "pcs", hardware.THERMAL["src"])
    sens = Counter(io.hw for io in ios if io.kind in ("DI", "AI", "TC", "IOL", "ENC") and io.hw in hardware.FIELD)
    for hw, q in sorted(sens.items()):
        add("sensor", hw, hardware.FIELD.get(hw, {}).get("desc", hw), q, "pcs", hardware.FIELD.get(hw, {}).get("src", "[typ]"))
    if line_model.L.get("SAFE1"):  # S-1 devices that are not solids of their own (implied in a part / the cabinet)
        dev_ = Counter()
        for io in ios:
            if io.hw in ("muting", "drawer_switch") and not io.tag.endswith(".B"):
                dev_[io.hw] += 1
        for hw, q in sorted(dev_.items()):
            add("safety", hw, hardware.SAFE[hw]["desc"], q, "pcs", hardware.SAFE[hw]["src"])
        nh = len(plc_io.heaters(ios))
        add("safety", "duplex thermocouple", hardware.SAFE["tc_duplex"]["desc"] + " (replaces the single TCs)", nh, "pcs",
            hardware.SAFE["tc_duplex"]["src"])
        add("safety", "zone exhaust valve", hardware.SAFE["zone_valve"]["desc"], line_model.n_zones(), "pcs",
            hardware.SAFE["zone_valve"]["src"])
        if not any(p.name == "reject_shutter" for p in parts):
            add("safety", "safety spring flap (reject funnel outlet)", "closed by pulling the drawer - NOT in the CAD",
                1, "pcs", "[open design item]")
    wires, _ = plc_io.wiring(ios)
    cab = defaultdict(float)
    for w in wires:
        cab[w["cable"]] += w["length_m"]
    for c, m in sorted(cab.items()):
        n, mm2, od = hardware.CABLE[c]
        add("cable", c, f"{n} x {mm2} mm2", round(m * 1.1, 1), "m", "[typ] +10 %")
    # --- pneumatics
    cyl = Counter(p.hw.split(" ")[0] for p in parts if p.hw.startswith("ISO6432"))
    for c, q in sorted(cyl.items()):
        add("pneumatic", c, "ISO 6432 cylinder, magnetic piston, cushioned", q, "pcs", "[ISO 6432]")
    ix, iy = line_model.L["ISLAND_XY"]
    tube = sum(2 * (abs(p.aabb()[0] - ix) + abs(p.aabb()[1] - iy) + p.aabb()[5]) / 1000 * 1.2
               for p in parts if p.hw.startswith("ISO6432"))
    add("pneumatic", "PU tube 4 x 2.5", "valve island -> every cylinder, 2 lines", round(tube, 1), "m", "[typ]")
    add("pneumatic", "push-in fittings M5 / G1/8", "2 per cylinder", 2 * sum(cyl.values()), "pcs", "[typ]")
    add("pneumatic", "vacuum ejector + switch", hardware.EJECTOR["desc"], len(line_model.L["DELTA_X"]) + 1, "pcs", hardware.EJECTOR["src"])
    return rows, cut


def write(rows, cut):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "bom.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["category", "item", "spec", "qty", "unit", "source"])
        w.writeheader()
        w.writerows(rows)
    cats = defaultdict(list)
    for r in rows:
        cats[r["category"]].append(r)
    e = html.escape
    body = [f"<h1>STF-2 bill of materials</h1><p class=sub>Derived from line_model + joints + plc_io. "
            f"{len(rows)} lines. <b>[typ]</b> = typical catalogue value, verify on the part bought. "
            f"Kits = bought connection kits whose screws are not modelled as solids.</p>"]
    for cat in ("profile", "bought", "make", "bracket", "fastener", "kit", "electric", "sensor", "safety", "cable",
                "pneumatic"):
        if cat not in cats:
            continue
        body.append(f"<h2>{e(cat)}</h2><table><tr><th>item</th><th>spec</th><th class=n>qty</th><th>unit</th>"
                    f"<th>source</th></tr>")
        for r in cats[cat]:
            body.append(f"<tr><td>{e(str(r['item']))}</td><td>{e(str(r['spec']))}</td><td class=n>{r['qty']}</td>"
                        f"<td>{e(r['unit'])}</td><td class=src>{e(r['source'])}</td></tr>")
        body.append("</table>")
    body.append("<h2>profile cut list</h2><table><tr><th>section</th><th class=n>length mm</th>"
                "<th>end machining</th><th class=n>qty</th></tr>")
    for (sec, Ln, mach), q in sorted(cut.items()):
        body.append(f"<tr><td>{sec}</td><td class=n>{Ln}</td><td>{e(mach)}</td><td class=n>{q}</td></tr>")
    body.append("</table>")
    css = ("body{font:14px/1.45 system-ui,sans-serif;margin:24px;color:#1b2330;background:#fff}"
           "table{border-collapse:collapse;width:100%;margin:8px 0 24px}td,th{border-bottom:1px solid #dde2e8;"
           "padding:4px 8px;text-align:left;vertical-align:top}th{background:#f3f5f8}.n{text-align:right}"
           ".src{color:#6b7480;font-size:12px}.sub{color:#4a5563}")
    with open(os.path.join(OUT, "index.html"), "w") as fh:
        fh.write(f"<!doctype html><meta charset=utf-8><title>STF-2 BOM</title><style>{css}</style>" + "".join(body))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    rows, cut = build()
    write(rows, cut)
    c = Counter(r["category"] for r in rows)
    print(f"BOM: {len(rows)} lines ({', '.join(f'{k} {v}' for k, v in sorted(c.items()))}); "
          f"{sum(cut.values())} profile pieces in {len(cut)} cut positions -> {OUT}")
