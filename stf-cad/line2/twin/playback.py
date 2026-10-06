"""
DT-2: the twin's player rules - motion/timeline.json applied to the DT-1 scene. The reference implementation (Python);
twin/web/player.js is the same rules in JavaScript (browser + Node), twin/blender_anim.py turns them into keyframes.
Every one is checked against the FreeCAD player (motion/motion_player.py) by twin/playback_check.py.

Rules (= motion_player.Player.apply):
  rigid track      v = [tx, ty, tz, qx, qy, qz, qw, vis]   world = M(t, q) * (part as in the CAD); in the scene a part is
                   its prototype translated by its offset, so the part's node matrix is M(t, q) * T(offset)
  follower         a screw F####_ (name prefix) or a bracket (label) in timeline["follow"] takes its body's M(t, q)
  reshaped track   v = {c, ax, dia, len, col?, vis?}   drawn as THE cylinder of the frame (base centre c, axis ax, diameter
                   dia, length max(len, 0.01)); the part's CAD mesh is hidden meanwhile (exactly what FreeCAD does when it
                   rebuilds the shape). Rows that only appear during the run (band_r101_*) exist only as such cylinders.
  spawned          timeline["spawn"]: cookies on pucks that were empty when the CAD was built - a cylinder from p, s
                   (axis, height, diameter), then moved by its rigid track
  glow             timeline["glow"][part]: colour "on" / "off" from bits[k] (the SSR state)
Units mm, the model frame (Z up). Matrices are 4x4 numpy, column vectors (p' = M @ [x, y, z, 1]).
"""
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LINE2 = os.path.dirname(HERE)
TIMELINE = os.path.join(LINE2, "motion", "timeline.json")
AXES = {"x": 0, "y": 1, "z": 2}


def quat_matrix(qx, qy, qz, qw):
    n = qx * qx + qy * qy + qz * qz + qw * qw
    s = 2.0 / n if n else 0.0
    return np.array([[1 - s * (qy * qy + qz * qz), s * (qx * qy - qz * qw), s * (qx * qz + qy * qw)],
                     [s * (qx * qy + qz * qw), 1 - s * (qx * qx + qz * qz), s * (qy * qz - qx * qw)],
                     [s * (qx * qz - qy * qw), s * (qy * qz + qx * qw), 1 - s * (qx * qx + qy * qy)]])


def rigid(v):
    m = np.eye(4)
    m[:3, :3] = quat_matrix(*v[3:7])
    m[:3, 3] = v[:3]
    return m


def cylinder_matrix(c, ax, dia, length):
    """Unit cylinder (base at the origin, axis +z, diameter 1, height 1) -> the frame's cylinder."""
    s = np.diag([dia, dia, max(length, 0.01), 1.0])
    r = np.eye(4)
    if ax == "x":                                   # +z -> +x: +90 deg about y
        r[:3, :3] = [[0, 0, 1], [0, 1, 0], [-1, 0, 0]]
    elif ax == "y":                                 # +z -> +y: -90 deg about x
        r[:3, :3] = [[1, 0, 0], [0, 0, 1], [0, -1, 0]]
    t = np.eye(4)
    t[:3, 3] = c
    return t @ r @ s


class Timeline:
    def __init__(self, path=TIMELINE):
        tl = json.load(open(path))
        self.raw = tl
        self.dt, self.n, self.track = tl["dt"], tl["frames"], tl["track"]
        self.follow = tl.get("follow", {})
        self.glow = tl.get("glow", {})
        self.spawn = {s["name"]: s for s in tl["spawn"]}
        self.reshaped = {n for n, v in self.track.items() if isinstance(v[0], dict)}

    def body_of(self, name):
        """The moving body a follower rides on (screws by their F####_ prefix, brackets by label), or None."""
        key = name[:6] if name.startswith("F") and name[1:5].isdigit() else name
        b = self.follow.get(key)
        return b if b in self.track else None

    def frame(self, k):
        """{name: (kind, 4x4 matrix, visible, colour or None)} for frame k.
        kind 'rigid' -> node matrix = M @ T(offset); 'cyl' -> unit cylinder matrix; 'hide' -> CAD mesh hidden."""
        k = max(0, min(self.n - 1, int(k)))
        out = {}
        for n, tr in self.track.items():
            v = tr[k]
            if isinstance(v, dict):
                out[n] = ("cyl", cylinder_matrix(v["c"], v["ax"], v["dia"], v["len"]), bool(v.get("vis", 1)), v.get("col"))
            else:
                out[n] = ("rigid", rigid(v), bool(v[7]), None)
        for n, g in self.glow.items():
            kind, m, vis, _ = out.get(n, ("rigid", np.eye(4), True, None))
            out[n] = (kind, m, vis, g["on"] if g["bits"][k] == "1" else g["off"])
        return out

    def follower_matrix(self, name, fr):
        b = self.body_of(name)
        if b is None or fr[b][0] != "rigid":
            return None
        return fr[b][1]
