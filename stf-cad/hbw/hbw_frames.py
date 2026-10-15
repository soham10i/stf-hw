"""
Frame decomposition shared by every downstream consumer.

hbw_model.build(travel, lift, fork) bakes the pose into absolute coordinates.
Every joint here is a PURE TRANSLATION along one axis, so building at the zero
pose yields each part's coordinates *in its own joint frame* directly:

    world  ......... static parts, absolute
    travel ......... translate +X by `travel`
      lift ......... translate +Z by `lift`      (nested in travel)
        fork ....... translate +Y by `fork`      (nested in lift)

That nesting is the same hierarchy web/src/coords.ts already assumes
(base -> travel -> lift -> fork), and the same one the FreeCAD assembly uses,
so the CAD model and the browser scene articulate identically by construction.
"""
from hbw_model import build, P

FRAMES = ["world", "travel", "lift", "fork"]
PARENT = {"world": None, "travel": "world", "lift": "travel", "fork": "lift"}
AXIS = {"travel": "x", "lift": "z", "fork": "y"}      # factory frame


def local_parts():
    """All parts, positioned in their own joint frame."""
    return build(0.0, 0.0, 0.0)


def by_frame():
    out = {f: [] for f in FRAMES}
    for p in local_parts():
        out[p.joint or "world"].append(p)
    return out


def frame_offset(frame, travel, lift, fork):
    """Translation of `frame` relative to its parent, at the given pose."""
    return {"world": (0.0, 0.0, 0.0),
            "travel": (travel, 0.0, 0.0),
            "lift": (0.0, 0.0, lift),
            "fork": (0.0, fork, 0.0)}[frame]


HOME = dict(travel=P["CV_X"], lift=120.0, fork=0.0)  # parked at the conveyor


def verify(poses=((665, 120, 0), (120, 100, 115), (480, 340, 115), (665, 80, -115))):
    """Frames must reproduce build() exactly, or CAD and sim would articulate
    differently from the model the clearance proof ran against."""
    bad = []
    for tv, lz, fk in poses:
        want = {p.name: p.aabb() for p in build(tv, lz, fk)}
        for frame, parts in by_frame().items():
            dx, dy, dz = 0.0, 0.0, 0.0
            f = frame
            while f:
                ox, oy, oz = frame_offset(f, tv, lz, fk)
                dx, dy, dz = dx + ox, dy + oy, dz + oz
                f = PARENT[f]
            for p in parts:
                a = p.aabb()
                got = (a[0] + dx, a[1] + dy, a[2] + dz, a[3] + dx, a[4] + dy, a[5] + dz)
                if max(abs(g - w) for g, w in zip(got, want[p.name])) > 1e-9:
                    bad.append(f"{p.name} @ {(tv, lz, fk)}: {got} != {want[p.name]}")
    return bad


if __name__ == "__main__":
    b = verify()
    print("\n".join(b) if b else "frame decomposition EXACT for all test poses")
    import sys; sys.exit(1 if b else 0)
