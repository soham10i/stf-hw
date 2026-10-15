"""
Plays motion/timeline.json (written by motion.py) on the STF2_Precise FreeCAD document.
Shared by the GUI macro (play_motion.FCMacro) and the headless check (validate_motion.py).

Every CAD solid was built in absolute coordinates, so a frame is applied as
    Placement = Placement(t, q) * original placement
for rigid parts, a re-built cylinder for the extending piston rods and the band cookies (they spread and
brown in the oven: colour from oven.py), and Visibility for the cookies. Screws and brackets of a moving body
take that body's placement. The oven elements glow while their SSR conducts (zone duty, 2 s PWM) and the
panel shows the oven power and the current on L1 / L2 / L3 at every frame.
"""
import json
import os

import FreeCAD as App
import Part


def find_timeline(doc, here=None):
    cands = []
    if doc is not None and doc.FileName:
        cands.append(os.path.join(os.path.dirname(doc.FileName), "motion", "timeline.json"))
    if here:
        cands.append(os.path.join(here, "timeline.json"))
    for c in cands:
        if os.path.exists(c):
            return c
    raise FileNotFoundError("timeline.json not found in " + ", ".join(cands))


class Player:
    def __init__(self, doc, timeline_path):
        self.doc = doc
        tl = json.load(open(timeline_path))
        self.dt, self.n, self.track, self.follow = tl["dt"], tl["frames"], tl["track"], tl["follow"]
        self.phases = tl.get("phases", {})
        self.glow, self.power, self.duty = tl.get("glow", {}), tl.get("power", []), tl.get("duty", {})
        self.temps, self.zones = tl.get("temps", []), tl.get("zones", [])
        objs = [o for o in doc.Objects if o.TypeId == "Part::Feature"]
        by_label = {}
        for o in objs:
            by_label.setdefault(o.Label, o)
        self.spawned = []
        for s in tl["spawn"]:                       # cookies on pucks that were empty when the CAD was built
            if s["name"] in by_label:
                continue
            ax = {"x": App.Vector(1, 0, 0), "y": App.Vector(0, 1, 0), "z": App.Vector(0, 0, 1)}[s["s"][0]]
            o = doc.addObject("Part::Feature", "motion_" + s["name"])
            o.Label = s["name"]
            o.Shape = Part.makeCylinder(s["s"][2] / 2, s["s"][1], App.Vector(*s["p"]), ax)
            if App.GuiUp:
                h = s["colour"].lstrip("#")
                o.ViewObject.ShapeColor = tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
            by_label[s["name"]] = o
            self.spawned.append(o)
        self.obj = {n: by_label[n] for n in self.track if n in by_label}
        self.missing = sorted(n for n in self.track if n not in by_label)
        self.base_pl = {n: App.Placement(o.Placement) for n, o in self.obj.items()}
        self.base_shape = {n: o.Shape.copy() for n, o in self.obj.items() if isinstance(self.track[n][0], dict)}
        # followers: screws by name prefix F####_, brackets by label
        self.fol = []
        for o in objs:
            key = o.Name[:6] if o.Name.startswith("F") and o.Name[1:5].isdigit() else o.Label
            body = self.follow.get(key)
            if body and body in self.obj:
                self.fol.append((o, body, App.Placement(o.Placement)))
        self.glow_obj = {n: by_label[n] for n in self.glow if n in by_label}
        self.base_col = {n: (o.ViewObject.ShapeColor if App.GuiUp else None) for n, o in self.glow_obj.items()}
        self.frame = 0

    def placement(self, name, k):
        v = self.track[name][k]
        return App.Placement(App.Vector(v[0], v[1], v[2]), App.Rotation(v[3], v[4], v[5], v[6])), v[7]

    def apply(self, k):
        k = max(0, min(self.n - 1, int(k)))
        self.frame = k
        moved = {}
        for n, o in self.obj.items():
            v = self.track[n][k]
            if isinstance(v, dict):                 # an extending rod / a band cookie: rebuild the cylinder
                ax = {"x": App.Vector(1, 0, 0), "y": App.Vector(0, 1, 0), "z": App.Vector(0, 0, 1)}[v["ax"]]
                o.Shape = Part.makeCylinder(v["dia"] / 2, max(v["len"], 0.01), App.Vector(*v["c"]), ax)
                if "vis" in v:
                    o.Visibility = bool(v["vis"])
                if App.GuiUp:
                    if "col" in v:
                        h = v["col"].lstrip("#")
                        o.ViewObject.ShapeColor = tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
                    if "vis" in v:
                        o.ViewObject.Visibility = bool(v["vis"])
                continue
            pl, vis = self.placement(n, k)
            o.Placement = pl.multiply(self.base_pl[n])
            moved[n] = pl
            if App.GuiUp:
                o.ViewObject.Visibility = bool(vis)
            o.Visibility = bool(vis)
        for o, body, base in self.fol:
            if body in moved:
                o.Placement = moved[body].multiply(base)
        if App.GuiUp:
            for n, o in self.glow_obj.items():
                g = self.glow[n]
                h = (g["on"] if g["bits"][k] == "1" else g["off"]).lstrip("#")
                o.ViewObject.ShapeColor = tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        return k

    def reset(self):
        for n, o in self.obj.items():
            o.Placement = self.base_pl[n]
            if n in self.base_shape:
                o.Shape = self.base_shape[n]
            o.Visibility = True
            if App.GuiUp:
                o.ViewObject.Visibility = True
        for o, body, base in self.fol:
            o.Placement = base
        if App.GuiUp:
            for n, o in self.glow_obj.items():
                if self.base_col.get(n) is not None:
                    o.ViewObject.ShapeColor = self.base_col[n]
        for o in self.spawned:
            self.doc.removeObject(o.Name)
        self.spawned = []

    def label(self, k):
        t = k * self.dt
        txt = f"t = {t:5.1f} s"
        for name, t0, d in self.phases.get("exchange", []):
            if t0 <= t < t0 + d:
                txt += f"  |  airlock: {name}"
        if self.power:
            W, a1, a2, a3 = self.power[min(k, len(self.power) - 1)]
            on = sum(1 for g in self.glow.values() if g["bits"][k] == "1")
            txt += (f"\noven {W / 1000:.2f} kW now ({on}/{len(self.glow)} elements on)   "
                    f"L1 {a1:.1f} A   L2 {a2:.1f} A   L3 {a3:.1f} A")
            txt += "\nduty " + "  ".join(f"{z} {d:.0%}" for z, d in sorted(self.duty.items()))
        if self.temps:
            y = self.temps[min(k, len(self.temps) - 1)]
            txt += "\nTC " + "  ".join(f"Z{i + 1} {v:.1f} C (set {self.zones[i]['T']:g})" for i, v in enumerate(y))
        return txt
