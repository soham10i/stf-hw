"""
DT-1 gate: the exported scene is the CAD, all of it, and nothing else.

    .venv-twin/bin/python twin/scene_check.py        (from stf-cad/line2; exit 1 on any failure)

Proofs
  S1 complete      every solid of STF2_Precise.FCStd (read from its Document.xml, independent of the export) is one
                   prim with stf:name, exactly once; no other part prims;
                   only the ten modules of line_model.MODULES (no M2_feeder / M3_tunnel / M4_stamp of the old design)
  S2 geometry      each prim's world bounding box (USD BBoxCache through its instance) equals the solid's exact B-rep box
                   within the tessellation deflection; each mesh encloses the B-rep volume within 2 %, every solid closed
  S3 identity      every signal of plc/io_list.csv drawn in the CAD names an existing part prim, and that part's stf:tag
                   is the signal's tag or its stem (AI1 -> AI1.R, delta_C.VAC -> delta_C.VAC.P)
  S4 motion        every part the timeline moves (track, spawn, followers) carries stf:moving and xformOp:transform:anim
                   as its first op, identity; no static part carries one
  S5 composition   the stage composes without errors; every prim's material binding resolves
  S6 validators    every OpenUSD validator (28 in 26.08) on the stage and on the USDZ package: 0 errors, 0 warnings
  S7 GLB           the Khronos glTF validator: 0 errors, 0 warnings; one node per part; each node's box (accessor
                   min/max + translation) equals the USD box
  S8 budget        triangles drawn <= 3,000,000 (the viewer budget, TECH_STACK.md section 5)
"""
import csv
import html
import json
import os
import re
import subprocess
import sys
import zipfile

import numpy as np
from pxr import Gf, Usd, UsdGeom, UsdShade, UsdValidation

HERE = os.path.dirname(os.path.abspath(__file__))
LINE2 = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
sys.path.insert(0, LINE2)
MODULES = ["M1_loop", "M2_depositor", "M3_oven", "M4_transfer", "M5_qc", "M6_pick", "M7_pack", "M8_control",
           "M9_ports", "M10_safety"]                       # = line_model.MODULES (asserted below without importing FreeCAD)
TRI_BUDGET = 3_000_000
VOL_TOL = 0.02


def fcstd_solids(path):
    """Labels of every Part::Feature in an FCStd, read from its Document.xml (no FreeCAD needed)."""
    x = zipfile.ZipFile(path).read("Document.xml").decode()
    feat = {n for t, n in re.findall(r'<Object type="([^"]+)" name="([^"]+)"', x) if t == "Part::Feature"}
    out = set()
    for name, body in re.findall(r'<Object name="([^"]+)"[^>]*>(.*?)</Object>', x, re.S):
        if name in feat:
            lab = re.search(r'<Property name="Label"[^>]*>\s*<String value="([^"]*)"', body)
            out.add(html.unescape(lab.group(1)) if lab else name)
    return out


def check(verbose=True):
    rows, fails = [], []

    def row(name, value, limit, ok, note=""):
        rows.append((name, value, limit, ok, note))
        if not ok:
            fails.append(f"SCENE {name}: {value} vs {limit} {note}".strip())

    import line_model as M
    assert list(M.MODULES) == MODULES
    idx = json.load(open(os.path.join(OUT, "cache", "index.json")))
    meta, solids = idx["meta"], idx["solids"]
    by = {s["name"]: s for s in solids}
    stage = Usd.Stage.Open(os.path.join(OUT, "stf2.usda"))

    # S5 composition first: nothing else means anything if the stage does not compose
    errs = stage.GetCompositionErrors()
    row("S5 stage composes", f"{len(errs)} composition errors", "0", not errs, "; ".join(str(e) for e in errs[:3]))

    prims = [p for p in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies())
             if p.HasAttribute("stf:name")]
    names = [p.GetAttribute("stf:name").Get() for p in prims]
    dup = len(names) - len(set(names))
    cad = fcstd_solids(meta["source"])                     # independent of the export: the FCStd's own object list
    missing, extra = sorted(cad - set(names)), sorted(set(names) - cad)
    mods = {p.GetAttribute("stf:module").Get() for p in prims}
    row("S1 complete", f"{len(prims)} part prims for the {len(cad)} solids of the FCStd; {len(missing)} missing, {len(extra)} extra, "
        f"{dup} duplicated", "all, once", not (missing or extra or dup) and len(prims) == len(cad),
        ", ".join((missing + extra)[:5]))
    row("S1 modules", ", ".join(sorted(mods)), "the 10 of line_model.MODULES", mods == set(MODULES))

    # S2 geometry
    bc = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_], useExtentsHint=False)
    worst, bad_bb = 0.0, []
    usd_box = {}
    for p, n in zip(prims, names):
        r = bc.ComputeWorldBound(p).ComputeAlignedRange()
        box = np.array([*r.GetMin(), *r.GetMax()])
        usd_box[n] = box
        d = float(np.abs(box - np.array(by[n]["bbox"])).max())
        worst = max(worst, d)
        if d > meta["deflection"] + 1e-3:
            bad_bb.append((n, round(d, 3)))
    row("S2 boxes = B-rep", f"worst {worst:.3f} mm over {len(prims)} parts", f"<= deflection {meta['deflection']} mm",
        not bad_bb, str(bad_bb[:4]) if bad_bb else "exact B-rep box (optimalBoundingBox)")
    vol_bad = [(s["name"], round(s["mesh_volume"] / s["volume"], 4)) for s in solids
               if s["volume"] > 0 and abs(s["mesh_volume"] / s["volume"] - 1) > VOL_TOL]
    wv = max(abs(s["mesh_volume"] / s["volume"] - 1) for s in solids if s["volume"] > 0)
    row("S2 volumes = B-rep", f"worst {wv:.2%}, {sum(not s['closed'] for s in solids)} not closed",
        f"<= {VOL_TOL:.0%}, all closed", not vol_bad and all(s["closed"] for s in solids),
        str(vol_bad[:4]) if vol_bad else "faces oriented outward (signed volume)")

    # S3 identity: a signal names its part (io_list column `part`); the part's tag is the signal's tag or its stem
    #    (delta_C.VAC on the cup carries delta_C.VAC and delta_C.VAC.P; AI1 carries AI1.R / .G / .B)
    io = list(csv.DictReader(open(os.path.join(LINE2, "plc", "io_list.csv"))))
    ptag = {n: p.GetAttribute("stf:tag").Get() for p, n in zip(prims, names)}
    need = [r for r in io if r["in_cad"] == "True"]
    lost = [r["tag"] for r in need if r["part"] not in ptag]
    clash = [r["tag"] for r in need if r["part"] in ptag and ptag[r["part"]]
             and not (r["tag"] == ptag[r["part"]] or r["tag"].startswith(ptag[r["part"]] + "."))]
    row("S3 signals on their part", f"{len(need) - len(lost) - len(clash)} of {len(need)} drawn signals "
        f"({len(io) - len(need)} implied: cabinet DIN devices, home switches)", "all", not lost and not clash,
        ", ".join((lost + clash)[:8]))

    # S4 motion
    tl = json.load(open(os.path.join(LINE2, "motion", "timeline.json")))
    movers = set(tl["track"]) | {s["name"] for s in tl["spawn"]}
    fol = tuple(tl.get("follow", {}))
    pm = {n: p for p, n in zip(prims, names)}
    wrong = []
    for n, p in pm.items():
        should = n in movers or n.startswith(fol)
        x = UsdGeom.Xformable(p)
        ops = x.GetOrderedXformOps()
        has = bool(ops) and ops[0].GetOpName() == "xformOp:transform:anim"
        ident = (ops[0].Get() == Gf.Matrix4d(1.0)) if has else True
        if p.GetAttribute("stf:moving").Get() != should or has != should or not ident:
            wrong.append(n)
    in_cad = [n for n in movers if n in pm]
    row("S4 moving parts", f"{sum(1 for n in pm if pm[n].GetAttribute('stf:moving').Get())} moving prims; "
        f"{len(in_cad)} of {len(movers)} timeline tracks are CAD parts", "every mover animatable, no static one",
        not wrong, ", ".join(wrong[:5]) or "the rest are cookies spawned by the timeline (not in the CAD)")

    # S5 materials
    unbound = [n for p, n in zip(prims, names) if not UsdShade.MaterialBindingAPI(p).ComputeBoundMaterial()[0]]
    row("S5 materials bound", f"{len(prims) - len(unbound)} of {len(prims)}", "all", not unbound, ", ".join(unbound[:5]))

    # S6 OpenUSD validators (all registered: composition, stage metadata, material binding, encapsulation, package)
    reg = UsdValidation.ValidationRegistry()
    ctx = UsdValidation.ValidationContext(reg.GetOrLoadAllValidators())
    for label, path in (("stage", "stf2.usda"), ("USDZ", "stf2.usdz")):
        st = Usd.Stage.Open(os.path.join(OUT, path))
        found = [e for e in ctx.Validate(st) if e.GetType() in (UsdValidation.ValidationErrorType.Error,
                                                                   UsdValidation.ValidationErrorType.Warn)]
        n = sum(1 for p in Usd.PrimRange(st.GetPseudoRoot(), Usd.TraverseInstanceProxies()) if p.HasAttribute("stf:name"))
        row(f"S6 USD validators, {label}", f"{n} parts; {len(found)} errors / warnings from "
            f"{len(reg.GetAllValidatorMetadata())} validators", f"{meta['solids']} parts, 0",
            not found and n == meta["solids"], "; ".join(e.GetMessage()[:90] for e in found[:2]))

    # S7 GLB
    r = subprocess.run(["node", os.path.join(HERE, "validate_glb.mjs"), os.path.join(OUT, "stf2.glb")],
                       capture_output=True, text=True, cwd=HERE)
    try:
        v = json.loads(r.stdout)
        row("S7 GLB Khronos validator", f"{v['errors']} errors, {v['warnings']} warnings", "0, 0",
            v["errors"] == 0 and v["warnings"] == 0, "; ".join(m["message"] for m in v["messages"][:2]))
    except (json.JSONDecodeError, KeyError):
        row("S7 GLB Khronos validator", "did not run", "0, 0", False, (r.stderr or r.stdout)[:200] +
            " (npm install in twin/)")
    raw = open(os.path.join(OUT, "stf2.glb"), "rb").read()
    jl = int.from_bytes(raw[12:16], "little")
    g = json.loads(raw[20:20 + jl])
    part_nodes = [nd for nd in g["nodes"] if "mesh" in nd]
    worst_g, bad_g = 0.0, []
    for nd in part_nodes:
        acc = g["accessors"][g["meshes"][nd["mesh"]]["primitives"][0]["attributes"]["POSITION"]]
        t = np.array(nd.get("translation", [0, 0, 0]))
        box = np.array([*(np.array(acc["min"]) + t), *(np.array(acc["max"]) + t)])
        d = float(np.abs(box - usd_box[nd["name"]]).max()) if nd["name"] in usd_box else 1e9
        worst_g = max(worst_g, d)
        if d > 1e-3:
            bad_g.append(nd["name"])
    row("S7 GLB = USD", f"{len(part_nodes)} part nodes, worst box difference {worst_g:.4f} mm", f"{meta['solids']}, <= 0.001 mm",
        len(part_nodes) == meta["solids"] and not bad_g, ", ".join(bad_g[:5]))

    # S8 budget
    row("S8 triangle budget", f"{meta['triangles_instanced']:,} drawn ({meta['triangles_stored']:,} stored in "
        f"{meta['prototypes']} prototypes)", f"<= {TRI_BUDGET:,}", meta["triangles_instanced"] <= TRI_BUDGET)

    if verbose:
        for name, val, lim, ok, note in rows:
            print(f"  [{'ok' if ok else 'FAIL'}] {name:26s} {val:70s} {lim:30s} {note}")
        print("\n".join(fails) if fails else "ALL SCENE PROOFS PASS (complete, geometry, identity, motion, composition, "
                                             "USDZ, GLB, budget)")
    return rows, fails


if __name__ == "__main__":
    sys.exit(1 if check()[1] else 0)
