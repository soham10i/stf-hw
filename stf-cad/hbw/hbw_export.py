"""
Export the HBW to the digital twin: web/public/hbw_parts.json.

Same source as the CAD and the drawings, so the browser scene cannot drift from
STF_HBW.FCStd. Parts are emitted in LOCAL joint-frame coordinates; the scene
nests four groups (world -> travel -> lift -> fork) and translates each by the
live joint value, exactly like the FreeCAD App::Part placements.
"""
import hashlib, json, os, sys
from hbw_model import (P, build, check, slot_ids, slot_pose,
                       MOULD_SLOTS, COOKIE_SLOTS, FREE_SLOT, COOKIE_FLAVOUR)
from hbw_frames import by_frame, PARENT, AXIS, FRAMES, HOME
import factory_layout
import vgr_model as VG
import oven_model as OM
import sorting_model as SM
import pipeline as PL
import hbw_model as HMOD

from variant import UP1, UP2, UP3, UP4, UP5, UP6, UP7, VARIANT
PUB = os.path.expanduser("~/workspace/stf-hw/web/public")
BASE_OUT = os.path.join(PUB, "hbw_parts.json")
OUT = os.path.join(PUB, f"hbw_parts_{VARIANT}.json" if UP1 else "hbw_parts.json")

COLOUR = {
    "black": "#2b2b2f", "red": "#cf3a2f", "alu": "#d6d9da", "steel": "#aeb4b8",
    "white": "#f2f0ea", "colour": "#2f6fd0", "green": "#1b8f52", "amber": "#e0a02a",
    "grey": "#8b9196", "darkgrey": "#474b52", "slate": "#3a3f44",
    "ftred": "#e0492f", "blue": "#1f63c4", "revpi": "#dcdedd",
    "yellow": "#f2c230", "polycarb": "#cfe6ff", "estop": "#d61f1f",
    "io": "#d9dcde", "iodi": "#f2d33d", "iodo": "#e0503a", "ioai": "#3ea55a", "iocnt": "#8b6ccf", "ioiol": "#06b6d4", "rfid": "#1f6f8b",
    "pe": "#9cc21a",
}


def col(name):
    """Flavour colours arrive as literal hex from pipeline.py; named ft colours
    go through the table."""
    return name if isinstance(name, str) and name.startswith("#") else COLOUR.get(name, "#8b9196")


def _upgrade_block(doc):
    """Upgrade 1: its parts (factory frame, translated only), its proofs, and
    before/after numbers measured from BOTH exports - never typed in."""
    import math, subprocess, upgrade as U, vgr_path
    fails = U.check(verbose=False) + vgr_path.check_buffer(verbose=False)
    if fails:
        print("REFUSING to export Upgrade 1 - it fails its proof:"); print("\n".join(fails[:30])); sys.exit(1)

    def pj(parts, at):
        return [{"n": p.name, "f": "world", "g": p.group, "k": p.kind,
                 "p": [round(p.p[0] + at[0], 3), round(p.p[1] + at[1], 3), round(p.p[2], 3)],
                 "s": list(p.s), "c": col(p.colour), "tag": p.tag, "mech": p.mech, "note": p.note}
                for p in parts]
    base_sag = json.loads(subprocess.run(
        [sys.executable, "-c", "import json, upgrade; print(json.dumps(upgrade.sag_report()))"],
        env={**os.environ, "STF_VARIANT": "base"}, capture_output=True, text=True, check=True,
        cwd=os.path.dirname(os.path.abspath(__file__))).stdout)

    def L(pts):
        return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))

    def metrics(d):
        w = d["wiring"]
        mods = [d["parts"], d["vgr"]["parts"], d["oven"]["parts"], d["sorting"]["parts"]]
        comp = sum(1 for ps in mods for p in ps if "compressor" in p["n"])
        comp += sum(1 for p in d.get("upgrade", {}).get("parts", []) if "compressor" in p["n"])
        return {"compressors": comp,
                "air_hose_m": round(sum(L(h["points"]) for h in w["hoses"]) / 1000, 2),
                "cable_m": round(sum(L(c["points"]) for c in w["cables"]) / 1000, 2),
                "cables": len(w["cables"]), "hoses": len(w["hoses"]),
                "vgr_stations": len(d["factory"]["stations"])}
    rep = U.report(doc)
    blk = {"name": "Upgrade 1 - central air, cookie buffer, stiff members",
           "parts": pj(U.buffer_parts(), U.BUF_AT) + pj(U.air_parts(), U.AIR_AT),
           "report": rep, "sag_before": base_sag,
           "buffer_tour": vgr_path.plan(vgr_path.buffer_tour()),
           "proofs": ["upgrade.check: plates on the table and clear of every module; nests "
                      "inside the VGR envelope; air station outside the arm's sweep; sag <= 0.2 mm",
                      "factory_layout.check_cross: every upgrade part against every module part, "
                      "and the VGR at every station (6 new) against the upgrade parts",
                      "vgr_path.check_buffer: 24 station visits (pick and place at every nest), "
                      "242 waypoints swept in 1 deg / 2 mm steps - nothing touches",
                      "all four module proofs and the original 42-waypoint tour, unchanged"]}
    import vgr_model as _VG
    blk["guides"] = [{"module": m, "host": h, "guest": g, "kind": k, "clearance_mm": c}
                     for m, gl in (("vgr", getattr(_VG, "GUIDES", [])), ("hbw", getattr(HMOD, "GUIDES", [])))
                     for h, g, k, c in gl]
    blk["precise"] = {
        "file": "precise_up1.glb",
        "generator": "stf-cad/hbw/web_precise.py (freecadcmd) - the same detail.precise / "
                     "detail_rich.rich / mechanics.guided that build STF_Factory_MCP.FCStd",
        "rich": sorted(__import__("detail_rich_names").RICH_NAMES),
        "rule": "every detailed solid is asserted to stay inside its part's proven envelope",
    }
    blk["components"] = [
        {"id": "encoder_motor", "ft": "144643", "size": "60x30x30 (+ shaft D4x7.5)", "source": "datasheet"},
        {"id": "mini_switch", "ft": "37783", "size": "30x15x7.5", "source": "datasheet"},
        {"id": "phototransistor", "ft": "36134", "size": "15x15x7.5", "source": "datasheet"},
        {"id": "colour_sensor", "ft": "128599", "size": "30x15x15", "source": "datasheet"},
        {"id": "s_motor", "ft": "S-24V", "size": "booklet part", "source": "assumed"},
        {"id": "compressor", "ft": "K-24V", "size": "booklet part", "source": "assumed"},
        {"id": "pneumatic_cylinder", "ft": "PZ", "size": "booklet part", "source": "assumed"},
        {"id": "ir_track_sensor", "ft": "128598", "size": "booklet part", "source": "assumed"},
        {"id": "solenoid_valve", "ft": "MV-3/2", "size": "booklet part", "source": "assumed"},
    ]
    blk["scale_note"] = ("2x structural scale; real VGR 140 mm reach / 120 mm vertical "
                         "(fischertechnik 536630: 270 deg, 140 mm, 120 mm)")
    doc["upgrade"] = blk
    after = metrics(doc)
    before = metrics(json.load(open(BASE_OUT))) if os.path.exists(BASE_OUT) else None
    blk["metrics"] = {"before": before, "after": after}
    return blk


def main():
    fails = check(verbose=False)
    if fails:
        print("REFUSING to export - model fails its clearance proof:")
        print("\n".join(fails)); sys.exit(1)

    parts = []
    for frame, ps in by_frame().items():
        for p in ps:
            parts.append({
                "n": p.name, "f": frame, "g": p.group, "k": p.kind,
                "p": [round(v, 3) for v in p.p],
                "s": [p.s[0], p.s[1], p.s[2]] if p.kind == "box" else list(p.s),
                "c": col(p.colour),
                "tag": p.tag, "mech": p.mech, "note": p.note,
            })

    doc = {
        "schema": 1,
        "units": "mm",
        "frame": {"up": "z", "x": "along the rack face / travel",
                  "y": "into the module / fork extension"},
        "plate": list(P["PLATE"]),
        "factory": factory_layout.doc(),
        "frames": [{"name": f, "parent": PARENT[f], "axis": AXIS.get(f)} for f in FRAMES],
        "home": HOME,
        "joints": {
            "travel": {"limits": list(P["TRAVEL"]), "axis": "x",
                       "stops": {f"bay{i+1}": b for i, b in enumerate(P["BAY_X"])}
                                | {"conveyor": P["CV_X"]}},
            # the fork table top sits at lift + 10
            "lift": {"limits": list(P["LIFT"]), "axis": "z",
                     "stops": {f"row{r}_under": z - 20.0 for r, z in zip("ABC", P["ROW_Z"])}
                              | {f"row{r}_lift": float(z) for r, z in zip("ABC", P["ROW_Z"])}
                              | {"belt_under": P["CV_SURF"] - 20.0,
                                 "belt_lift": P["CV_SURF"],
                                 "transit": 260.0}},
            # one stroke, two end switches: the rack AND the belt are both
            # reached at +115, because the belt sits beyond the rack in the same
            # y band. I5 vorne / I6 hinten are the ends of that single stroke.
            "fork": {"limits": list(P["FORK"]), "axis": "y",
                     "stops": {"retracted": 0.0, "bay": 115.0, "conveyor": 115.0}},
        },
        "interlocks": [
            "The identification tunnel starts at y=580, past the far end of the "
            "extended telescope (y=555), so the crane can descend to the belt at "
            "any height without a forbidden lift band.",
            "The Ausleger telescopes +Y only. The rack and the belt are both on "
            "that side, so one stop (115) serves a bay and the hand-over alike.",
            "Extended only where a station exists at that height.",
        ],
        "moulds": {"slots": MOULD_SLOTS, "with_cookie": COOKIE_SLOTS,
                   "free_slot": FREE_SLOT,
                   "size": list(P["MOULD"]), "rim_h": P["RIM_H"],
                   # which flavour each raw cookie becomes once baked
                   "cookie_flavour": COOKIE_FLAVOUR},
        "stations": {"vgr_pick": [P["CV_X"], P["PICK_VGR"], P["CV_SURF"]],
                     "hbw_pick": [P["CV_X"], P["PICK_HBW"], P["CV_SURF"]]},
        "belt": {
            "x": P["CV_X"], "surface": P["CV_SURF"], "gap": P["CV_GAP"],
            "y0": P["CV_Y"][0], "y1": P["CV_Y"][1],
            "handover": 350.0,          # where the Ausleger sets the workpiece down
            "I2": 315.0, "I3": 370.0,   # light barriers, inner / outer
            "pulley_d": P["PULLEY_D"],
        },
        "pitch_mm": P["PITCH_MM"],
        "slots": {sid: list(slot_pose(sid)) for sid in slot_ids()},
        "parts": parts,
    }
    # ---- VGR module, in its own local frames ----
    import vgr_path
    vfail = VG.check(verbose=False) + factory_layout.check_stations() \
        + factory_layout.check_cross() + vgr_path.check(verbose=False)
    if vfail:
        print("REFUSING to export - the VGR fails its clearance proof:")
        print("\n".join(vfail)); sys.exit(1)
    vparts = []
    for p in VG.build():
        vparts.append({
            "n": p.name, "f": p.frame, "g": p.group, "k": p.kind,
            "p": [round(v, 3) for v in p.p],
            "s": [p.s[0], p.s[1], p.s[2]] if p.kind == "box" else list(p.s),
            "c": col(p.colour), "tag": p.tag,
            "mech": p.mech, "note": p.note,
        })
    doc["vgr"] = {
        "plate": list(VG.V["PLATE"]),
        "centre": [VG.V["CX"], VG.V["CY"]],
        "pitch_mm": VG.V["PITCH_MM"],
        "frames": [{"name": f, "parent": VG.PARENT[f]} for f in VG.FRAMES],
        # Station stops are SOLVED by factory_layout.solve_station() from the
        # belt's own coordinates, never typed in - so the VGR's idea of where
        # the hand-over is cannot drift from the conveyor's.
        "joints": {
            "swivel": {"kind": "revolute", "limits": list(VG.V["SWIVEL"]),
                       "stops": {"home": 0.0,
                                 "belt": factory_layout.stations()["belt"]["swivel"]}},
            "plunge": {"kind": "prismatic", "limits": list(VG.V["PLUNGE"]),
                       "stops": {"raised": VG.V["TRANSIT"], "transit": VG.V["TRANSIT"],
                                 "pick": vgr_path.contact_plunge("belt")}},
            "reach": {"kind": "prismatic", "limits": list(VG.V["REACH"]),
                      "stops": {"retracted": 0.0,
                                "belt": factory_layout.stations()["belt"]["reach"]}},
        },
        "cup_drop": 28.0,          # cup underside = plunge - 28
        # The pose VG.build() emits the parts at. Groups in the viewer carry only
        # the DELTA from this - it used to subtract the plunge LIMIT (320) from a
        # part set authored at 250, drawing the whole arm 70 mm too low.
        "authoring": {"swivel": 0.0, "plunge": 250.0, "reach": 0.0},
        "spring": VG.V["SPRING"],
        # The proven tour: every waypoint the viewer plays is one vgr_path.check()
        # swept against the warehouse, the oven and the sorting line.
        "plan": vgr_path.export(),
        "parts": vparts,
    }

    # ---- Oven module (536632) ----
    ofail = OM.check(verbose=False)
    if ofail:
        print("REFUSING to export - the oven fails its clearance proof:")
        print("\n".join(ofail)); sys.exit(1)
    oparts = []
    for p in OM.build():
        oparts.append({
            "n": p.name, "f": p.frame, "g": p.group, "k": p.kind,
            "p": [round(v, 3) for v in p.p],
            "s": [p.s[0], p.s[1], p.s[2]] if p.kind == "box" else list(p.s),
            "c": col(p.colour), "tag": p.tag,
            "mech": p.mech, "note": p.note,
        })
    doc["oven"] = {
        "plate": list(OM.O["PLATE"]),
        "turntable": list(OM.O["TT"]),
        "frames": [{"name": f, "parent": OM.PARENT[f], "axis": OM.AXES.get(f)}
                   for f in OM.FRAMES],
        "authoring": {"slider": OM.O["SLIDER"][1], "door": OM.O["DOOR_Z"][1],
                      "turn": 0.0, "sauger": OM.O["SAUGER"][1], "lower": 0.0, "push": 0.0},
        "joints": {
            "slider": {"kind": "prismatic", "axis": "+x", "limits": list(OM.O["SLIDER"]),
                       "stops": {"innen": OM.O["SLIDER"][0], "aussen": OM.O["SLIDER"][1]}},
            "door": {"kind": "prismatic", "axis": "+z", "limits": list(OM.O["DOOR_Z"]),
                     "stops": {"shut": OM.O["DOOR_Z"][0], "open": OM.O["DOOR_Z"][1]}},
            # three switch-defined stops (I1 / I4 / I2), each a real turn angle
            "turn": {"kind": "revolute", "axis": "rz", "limits": list(OM.O["TURN"]),
                     "stops": dict(OM.STATIONS)},
            "sauger": {"kind": "prismatic", "axis": "+y", "limits": list(OM.O["SAUGER"]),
                       "stops": {"oven": OM.O["SAUGER"][0], "turntable": OM.O["SAUGER"][1]}},
            # ONE pneumatic stroke: up, or down onto the workpiece top at either stop
            "lower": {"kind": "prismatic", "axis": "-z", "limits": list(OM.O["LOWER"]),
                      "stops": {"up": 0.0, "down": OM.O["LOWER"][1]}},
            "push": {"kind": "prismatic", "axis": "+y", "limits": list(OM.O["PUSH"]),
                     "stops": {"home": 0.0, "out": OM.O["PUSH"][1]}},
        },
        "handover": list(OM.handover_point()),
        "cup_up": OM.O["CUP_UP"], "tray_top": OM.Z_W, "disc_top": OM.Z_W,
        "wp_h": OM.O["WP_H"],
        "flow": OM.flow(),
        "parts": oparts,
    }

    # ---- Sorting line (536633) ----
    sfail = SM.check(verbose=False)
    if sfail:
        print("REFUSING to export - the sorting line fails its clearance proof:")
        print("\n".join(sfail)); sys.exit(1)
    sparts = []
    for p in SM.build():
        sparts.append({
            "n": p.name, "f": p.frame, "g": p.group, "k": p.kind,
            "p": [round(v, 3) for v in p.p],
            "s": [p.s[0], p.s[1], p.s[2]] if p.kind == "box" else list(p.s),
            "c": col(p.colour), "tag": p.tag,
            "mech": p.mech, "note": p.note,
        })
    doc["sorting"] = {
        "plate": list(SM.S["PLATE"]),
        "frames": [{"name": f, "parent": SM.PARENT[f]} for f in SM.FRAMES],
        "joints": {"push": {"kind": "prismatic", "axis": SM.EJECT_AXIS, "limits": list(SM.S["EJECT"]),
                            "stops": {"home": 0.0, "eject": SM.S["EJECT"][1]}}},
        "colours": list(SM.COLOURS),
        "sensor_gap": SM.S["SENSOR_GAP"],
        "handovers": {k: list(v) for k, v in SM.handover_points().items()},
        "parts": sparts,
    }

    # ---- the pipeline: inventory + schedule ----
    pfail = PL.check(verbose=False)
    if pfail:
        print("REFUSING to export - the pipeline is not safe:")
        print("\n".join(pfail)); sys.exit(1)
    log, final, baked = PL.simulate()
    doc["pipeline"] = {
        "flavours": PL.FLAVOURS,
        "raw_colour": PL.RAW_COLOUR,
        "baked_at_end": sorted(baked),
        "n_cookies": PL.N_COOKIES,
        "resources": PL.RESOURCES,
        "initial": {k: [v[0], list(v[1])] for k, v in PL.initial_inventory().items()},
        "final": {k: [v[0], list(v[1])] for k, v in final.items()},
        "transfers": log,
        "safety": [
            "Exactly 12 cookies exist; they are created in pipeline.py and nowhere else.",
            "Every transfer is atomic - all locks taken at once, released at the end - "
            "so hold-and-wait cannot occur and a deadlock cannot form.",
            "Locks are acquired in one fixed total order over resources.",
            "A move never starts unless its destination has room, so a gripper never "
            "lifts a cookie with nowhere to put it down.",
            "The oven is a single-part station: tray and chamber are excluded together, "
            "which is the deadlock the wait-for detector actually found.",
            "Every pose the schedule commands is checked against the module geometry.",
        ],
    }

    # ---- precise components, PLC cabinet, wiring (wiring.py) ----
    import wiring, plc_model as PM
    for lst in (doc["parts"], doc["vgr"]["parts"], doc["oven"]["parts"], doc["sorting"]["parts"]):
        for d in lst:
            f = wiring.fit(d)
            if f:
                d["fit"] = f
    pf = PM.check(verbose=False)
    if pf:
        print("REFUSING to export - the PLC cabinet fails its check:"); print("\n".join(pf)); sys.exit(1)
    doc["plc"] = {"at": list(factory_layout.PLC_AT), "plate": list(PM.C["PLATE"]),
                  "parts": [{"n": p.name, "f": "world", "g": p.group, "k": "box",
                             "p": [round(v, 3) for v in p.p], "s": list(p.s), "c": col(p.colour),
                             "tag": "", "mech": "", "note": p.note} for p in PM.build()]}
    if UP2:
        import safety
        sf = safety.check(verbose=False)
        if sf:
            print("REFUSING to export Upgrade 2 - it fails its safety proof:"); print("\n".join(sf[:30])); sys.exit(1)
        doc["safety"] = safety.export()
        for q in doc["safety"]["parts"]:
            q["c"] = col(q["c"])
    if UP3:
        import io_nodes
        nf = io_nodes.check(verbose=False)
        if nf:
            print("REFUSING to export Upgrade 3 - the I/O nodes fail:"); print("\n".join(nf)); sys.exit(1)
        used, rl, free = PM.rail_fill()
        doc["io3"] = {**io_nodes.export(),
                      "rail": {"used_mm": round(used, 1), "length_mm": rl, "free": round(free, 3)},
                      "parts": [{"n": p.name, "f": "world", "g": p.group, "k": p.kind,
                                 "p": [round(v, 3) for v in p.p], "s": list(p.s), "c": col(p.colour),
                                 "tag": p.tag, "mech": p.mech, "note": p.note}
                                for m in io_nodes.MODULES for p in io_nodes.parts(m)]}
        import chains
        cf, _ = chains.check(verbose=False)
        if cf:
            print("REFUSING to export Upgrade 3 - the drag chains fail:"); print("\n".join(cf)); sys.exit(1)
        doc["chains"] = chains.export()
    if UP4:
        import control
        kf = control.check(verbose=True)
        if kf:
            print("REFUSING to export Upgrade 4 - the control program fails:"); print("\n".join(kf[:30])); sys.exit(1)
        doc["control"] = control.export()
    if UP5:
        import vc
        vf = vc.check(verbose=True)
        if vf:
            print("REFUSING to export Upgrade 5 - virtual commissioning fails:"); print("\n".join(vf[:30])); sys.exit(1)
        doc["vc"] = vc.export()
    doc["wiring"] = wiring.wires(doc)
    if UP1:
        doc["upgrade"] = _upgrade_block(doc)
    if UP6:
        import health
        hf = health.check(verbose=True)
        if hf:
            print("REFUSING to export Upgrade 6 - condition monitoring fails:"); print("\n".join(hf[:30])); sys.exit(1)
        doc["health"] = health.export()
    if UP7:
        import lifecycle
        lf = lifecycle.check(doc, doc["health"], verbose=True)
        if lf:
            print("REFUSING to export Upgrade 7 - the lifecycle checks fail:"); print("\n".join(lf[:30])); sys.exit(1)
        doc["lifecycle"] = lifecycle.export(doc, doc["health"])

    blob = json.dumps(doc, sort_keys=True, separators=(",", ":"))
    doc["fingerprint"] = hashlib.sha256(blob.encode()).hexdigest()[:16]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(doc, fh, indent=1)
    print(f"wrote {OUT}")
    print(f"  {len(parts)} parts   fingerprint {doc['fingerprint']}   "
          f"{os.path.getsize(OUT)/1024:.0f} kB")
    for f in FRAMES:
        print(f"  frame {f:7s} {len([q for q in parts if q['f'] == f]):3d} parts")


if __name__ == "__main__":
    main()
