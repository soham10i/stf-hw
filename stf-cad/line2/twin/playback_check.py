"""
DT-2 gate: the twin's players move every part exactly where the FreeCAD player moves it.

    .venv-twin/bin/python twin/playback_check.py      (from stf-cad/line2; needs twin/out from DT-1 and
                                                       twin/out/playback_ref.json from playback_ref.py)

For 41 frames (every second of the 40 s timeline) and every object the FreeCAD player moves (563: tracks, followers,
spawned cookies and toppings) the exact B-rep bounding box FreeCAD reports is compared with the box of what each
twin player draws:
  P1 Python   twin/playback.py on the DT-1 meshes (prototype vertices + offset, under the frame's matrix)
  P2 browser  twin/web/player.js (three.js math) on the GLB itself, run under Node - the code the web viewer runs
  P3 Blender  the keyframed scene of twin/blender_anim.py, evaluated at those frames (skipped if Blender is absent)
Tolerance: the tessellation deflection (0.2 mm) for CAD meshes; 0.05 mm for the cylinders the players rebuild (a
96-gon). Visibility must match at every sampled frame. A part the player hides (a reshaped track's CAD mesh) must not
be drawn.
"""
import json
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
sys.path.insert(0, HERE)
import playback as PB                                       # noqa: E402

TOL_MESH, TOL_CYL = 0.2 + 1e-3, 0.05
NGON = 96


def unit_cylinder_points(n=NGON):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ring = np.stack([0.5 * np.cos(a), 0.5 * np.sin(a)], 1)
    return np.vstack([np.c_[ring, np.zeros(n)], np.c_[ring, np.ones(n)]])


def box(m, pts):
    p = pts @ m[:3, :3].T + m[:3, 3]
    return np.r_[p.min(0), p.max(0)]


def python_boxes(tl, frames):
    """{frame: {name: (box, visible)}} from twin/playback.py on the DT-1 mesh cache."""
    idx = {s["name"]: s for s in json.load(open(os.path.join(OUT, "cache", "index.json")))["solids"]}
    npz = np.load(os.path.join(OUT, "cache", "meshes.npz"))
    verts = {}

    def v_of(n):
        if n not in verts:
            s = idx[n]
            verts[n] = npz[f"v{s['proto']}"].astype(np.float64) + np.array(s["offset"])
        return verts[n]

    cyl = unit_cylinder_points()
    out = {}
    for k in frames:
        fr = tl.frame(k)
        rows = {}
        for n, (kind, m, vis, _) in fr.items():
            if kind == "cyl":
                rows[n] = (box(m, cyl), vis, "cyl")
            elif n in tl.spawn:
                s = tl.spawn[n]
                base = PB.cylinder_matrix(s["p"], s["s"][0], s["s"][2], s["s"][1])
                rows[n] = (box(m @ base, cyl), vis, "cyl")
            elif n in idx:
                rows[n] = (box(m, v_of(n)), vis, "mesh")
        for n in idx:
            if idx[n]["moving"] and n not in fr:
                fm = tl.follower_matrix(n, fr)
                if fm is not None:
                    rows[n] = (box(fm, v_of(n)), True, "mesh")
        out[k] = rows
    return out


def compare(label, ref, got, row):
    worst, bad, vis_bad, missing = 0.0, [], [], []
    n_cmp = 0
    for k, objs in ref["ref"].items():
        k = int(k)
        for n, r in objs.items():
            g = got.get(k, {}).get(n)
            if g is None:
                missing.append(n)
                continue
            b, vis, kind = g
            if bool(r[6]) != bool(vis):
                vis_bad.append((k, n))
            if not r[6]:
                continue                                  # FreeCAD keeps the hidden shape where it was last; not drawn
            d = float(np.abs(np.array(r[:6]) - b).max())
            n_cmp += 1
            tol = TOL_CYL if kind == "cyl" else TOL_MESH
            worst = max(worst, d)
            if d > tol:
                bad.append((k, n, round(d, 3)))
    row(f"{label} boxes", f"{n_cmp} part-frames, worst {worst:.3f} mm", f"<= {TOL_MESH - 1e-3:g} mm mesh / {TOL_CYL:g} cyl",
        not bad and not missing, str((bad + [("missing", m) for m in sorted(set(missing))])[:4]))
    row(f"{label} visibility", f"{len(vis_bad)} mismatches", "0", not vis_bad, str(vis_bad[:4]))


def check(verbose=True):
    rows, fails = [], []

    def row(name, value, limit, ok, note=""):
        rows.append((name, value, limit, ok, note))
        if not ok:
            fails.append(f"PLAYBACK {name}: {value} vs {limit} {note}".strip())

    ref = json.load(open(os.path.join(OUT, "playback_ref.json")))
    frames = [int(k) for k in ref["frames"]]
    tl = PB.Timeline()
    row("reference", f"FreeCAD player: {ref['objects']} moved objects x {len(frames)} frames", "every mover", ref["objects"] > 0)
    compare("P1 Python", ref, python_boxes(tl, frames), row)

    js = os.path.join(HERE, "web", "check_player.mjs")
    if os.path.exists(js):
        r = subprocess.run(["node", js, ",".join(map(str, frames))], capture_output=True, text=True, cwd=HERE)
        try:
            data = json.loads(r.stdout)
            got = {int(k): {n: (np.array(v[:6]), bool(v[6]), v[7]) for n, v in objs.items()} for k, objs in data.items()}
            compare("P2 browser (player.js)", ref, got, row)
        except json.JSONDecodeError:
            row("P2 browser (player.js)", "did not run", "runs", False, (r.stderr or r.stdout)[:300])
    else:
        row("P2 browser (player.js)", "missing", "twin/web/check_player.mjs", False)

    bj = os.path.join(OUT, "blender_boxes.json")
    if os.path.exists(bj):
        data = json.load(open(bj))
        got = {int(k): {n: (np.array(v[:6]), bool(v[6]), v[7]) for n, v in objs.items()} for k, objs in data.items()}
        compare("P3 Blender", ref, got, row)
    else:
        row("P3 Blender", "no out/blender_boxes.json", "blender_anim.py --check", False)

    if verbose:
        for name, val, lim, ok, note in rows:
            print(f"  [{'ok' if ok else 'FAIL'}] {name:32s} {val:46s} {lim:30s} {note}")
        print("\n".join(fails) if fails else "ALL PLAYBACK PROOFS PASS (Python, browser and Blender players = FreeCAD player)")
    return rows, fails


if __name__ == "__main__":
    sys.exit(1 if check()[1] else 0)
