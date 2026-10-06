"""
Upgrade 15 - where the inspection camera is: placed from the model, checked against it.

    python3 -m vision.mount            (from stf-cad/hbw; or `make vision-mount`)

The camera hangs from the colour hood's roof on the sorting line, 40 mm before the colour
sensor A4. The hood already shields its stretch of belt from the room's light - the one
thing the CNN's test showed it cannot cope with (30 % false rejects under unseen light),
so the camera is put where its light is controlled: a ring light around the lens, strobed
while the cookie is under it, so A4's reading 40 mm later sees the hood dark as before.

Checks, against the Upgrade 12 export's own parts (every part's envelope, components at
their real size):
  FIT        no camera part overlaps any part of the line (the bracket may touch the roof)
  PATH       the camera clears the cookie's path along the belt (cookie + 5 mm)
  SENSOR     at least 5 mm from the colour sensor A4's envelope
  SIGHT      every ray from the lens to the inspected area - the cookie's footprint plus
             the renderer's jitter, on the belt and at the cookie's top - misses every part
  OPTICS     the lens angle that maps 80 mm onto the image at this working distance; the
             motion blur of a 1 ms exposure at the belt's speed
  TRIGGER    I2 (the inlet light barrier) fires; the cookie reaches the lens's axis after
             a fixed delay at the belt's speed
Writes web/public/vision/camera.json: the camera's parts in the sorting module's frame (the
twin draws them with the line) and these results.
"""
import json
import math
import os

from vision import render as R

HERE = os.path.dirname(os.path.abspath(__file__))
PUB = os.path.abspath(os.path.join(HERE, "..", "..", "..", "web", "public"))
EXPORT = os.path.join(PUB, "hbw_parts_up12.json")
OUT = os.path.join(PUB, "vision", "camera.json")
V_BELT = 50.0                    # mm/s, control.py V_BELT
EXPOSURE_S = 0.001
CLEAR_A4 = 5.0


def box_of(p):
    """Axis-aligned envelope of an exported part, components at their real (fitted) size."""
    x, y, z = p["p"]
    if p["k"] == "box":
        sx, sy, sz = p["s"]
        b = [x, y, z, x + sx, y + sy, z + sz]
    else:
        ax, L, d = p["s"]
        b = {"x": [x, y - d / 2, z - d / 2, x + L, y + d / 2, z + d / 2],
             "y": [x - d / 2, y, z - d / 2, x + d / 2, y + L, z + d / 2],
             "z": [x - d / 2, y - d / 2, z, x + d / 2, y + d / 2, z + L]}[ax]
    f = p.get("fit")
    if f:
        c, o = f["centre"], f["overall"]
        b = [min(b[0], c[0] - o[0] / 2), min(b[1], c[1] - o[1] / 2), min(b[2], c[2] - o[2] / 2),
             max(b[3], c[0] + o[0] / 2), max(b[4], c[1] + o[1] / 2), max(b[5], c[2] + o[2] / 2)]
    return b


def overlap(a, b, eps=1e-6):
    return all(a[i] < b[i + 3] - eps and b[i] < a[i + 3] - eps for i in range(3))


def gap(a, b):
    d = [max(b[i] - a[i + 3], a[i] - b[i + 3], 0.0) for i in range(3)]
    return math.sqrt(sum(v * v for v in d))


def ray_hits(p0, p1, b, n=60):
    for k in range(1, n + 1):
        t = k / n
        q = [p0[i] + (p1[i] - p0[i]) * t for i in range(3)]
        if all(b[i] < q[i] < b[i + 3] for i in range(3)):
            return True
    return False


def camera_parts(doc):
    s = doc["sorting"]["parts"]
    get = {p["n"]: p for p in s}
    roof, a4 = box_of(get["colour_hood_roof"]), box_of(get["A4_colour_sensor"])
    web = box_of(get["belt_web"])
    belt_top, yc = web[5], (web[1] + web[4]) / 2
    cx = (a4[0] + a4[3]) / 2 - 40.0                    # the lens axis, 40 mm before A4's centre
    body = 29.0
    lens_z = 92.0                                      # the lens's front face
    parts = [
        dict(n="cam_bracket", g="vision", f="world", k="box", p=[cx - 10, yc - 5, lens_z + 8 + 25], s=[20.0, 10.0, roof[2] - (lens_z + 33)],
             c="#9aa3ac", tag="", mech="", note="bracket screwed to the hood's roof"),
        dict(n="cam_body", g="vision", f="world", k="box", p=[cx - body / 2, yc - body / 2, lens_z + 8], s=[body, body, 25.0],
             c="#2b2d31", tag="CAM1", mech="", note="inspection camera (Upgrade 15): 29 mm board camera, GigE; ASSUMED part"),
        dict(n="cam_lens", g="vision", f="world", k="cyl", p=[cx, yc, lens_z], s=["z", 8.0, 14.0],
             c="#111316", tag="", mech="", note="M12 wide-angle lens"),
        dict(n="cam_ring_light", g="vision", f="world", k="cyl", p=[cx, yc, lens_z], s=["z", 6.0, 40.0],
             c="#e8eef7", tag="CAM1-L", mech="light", note="LED ring light, strobed with the exposure"),
    ]
    return parts, dict(cx=cx, yc=yc, belt_top=belt_top, lens_z=lens_z, a4=a4)


def check(doc, parts, g):
    s = doc["sorting"]["parts"]
    others = [(p["n"], box_of(p)) for p in s]
    cam = [(p["n"], box_of(p)) for p in parts]
    res, fails = [], []

    def add(name, ok, detail):
        res.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            fails.append(f"{name}: {detail}")
    hits = [(c, o) for c, cb in cam for o, ob in others if overlap(cb, ob)]
    add("FIT", not hits, "no overlap with any of the line's parts" if not hits else f"{hits[:3]}")
    wp_d, wp_h = 45.0, 20.0
    lane = [16.0, g["yc"] - wp_d / 2 - 5, g["belt_top"], 840.0, g["yc"] + wp_d / 2 + 5, g["belt_top"] + wp_h + 5]
    low = min(cb[2] for _, cb in cam)
    add("PATH", all(not overlap(cb, lane) for _, cb in cam),
        f"lowest camera part {low:.0f} mm, cookie top {g['belt_top'] + wp_h:.0f} mm: {low - g['belt_top'] - wp_h:.0f} mm clear")
    da = min(gap(cb, g["a4"]) for _, cb in cam)
    add("SENSOR", da >= CLEAR_A4, f"{da:.1f} mm from A4's envelope (at least {CLEAR_A4:.0f})")
    lens = [g["cx"], g["yc"], g["lens_z"]]
    half = wp_d / 2 + R.WIDE["jitter"]
    targets = [[g["cx"] + dx, g["yc"] + dy, z] for z in (g["belt_top"], g["belt_top"] + wp_h)
               for dx in (-half, -half / 2, 0, half / 2, half) for dy in (-half, -half / 2, 0, half / 2, half)]
    blocked = [(o, t) for t in targets for o, ob in others if ray_hits(lens, t, ob)]
    add("SIGHT", not blocked, f"{len(targets)} rays to the inspected area ({2 * half:.0f} mm square), none blocked"
        if not blocked else f"blocked by {sorted({o for o, _ in blocked})}")
    wd = g["lens_z"] - g["belt_top"]
    angle = 2 * math.degrees(math.atan(R.MM / 2 / wd))
    blur_px = V_BELT * EXPOSURE_S * R.PX
    add("OPTICS", angle < 100 and blur_px < 1, f"{R.MM:.0f} mm field at {wd:.0f} mm needs a {angle:.0f}° lens; "
        f"1 ms exposure at {V_BELT:.0f} mm/s blurs {blur_px:.2f} px")
    i2 = next(box_of(p) for p in s if p["n"] == "I2_inlet_rx")
    trig = (g["cx"] - (i2[0] + i2[3]) / 2) / V_BELT
    add("TRIGGER", trig > 0, f"I2 breaks, the cookie is under the lens {trig:.2f} s later; A4 reads it "
        f"{40.0 / V_BELT:.2f} s after that, with the ring light off")
    return res, fails, dict(working_distance_mm=wd, lens_angle_deg=round(angle, 1), blur_px=round(blur_px, 3),
                            trigger_delay_s=round(trig, 3), roi_mm=2 * half)


def mutants(doc):
    """The checks can fail: three wrong mounts, each must be caught."""
    out = []
    for mid, what, dx, dz in (("CM1", "camera moved onto the colour sensor", 40.0, 0.0),
                              ("CM2", "camera lowered into the cookie's path", 0.0, -35.0),
                              ("CM3", "camera moved back over the inlet barrier, outside the hood", -60.0, -20.0)):
        parts, g = camera_parts(doc)
        for p in parts:
            p["p"] = [p["p"][0] + dx, p["p"][1], p["p"][2] + dz]
        g = {**g, "cx": g["cx"] + dx, "lens_z": g["lens_z"] + dz}
        _, f, _ = check(doc, parts, g)
        out.append({"id": mid, "what": what, "caught": bool(f), "by": f[0] if f else None})
    return out


def main():
    doc = json.load(open(EXPORT))
    parts, g = camera_parts(doc)
    res, fails, optics = check(doc, parts, g)
    muts = mutants(doc)
    fails += [f"mutant {m['id']} survived: {m['what']}" for m in muts if not m["caught"]]
    out = {"parts": parts, "frame": "sorting", "lens": [g["cx"], g["yc"], g["lens_z"]], "fov_mm": R.MM,
           "image_px": R.N, "optics": optics, "checks": res, "mutants": muts, "fails": fails, "export": doc["fingerprint"],
           "why_here": "inside the colour hood: its light is controlled, the CNN's weak point"}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1)
    for r in res:
        print(f"  {r['check']:8s} {'ok ' if r['ok'] else 'FAIL'} {r['detail']}")
    for m in muts:
        print(f"  {m['id']} {m['what']}: {'caught - ' + m['by'] if m['caught'] else 'SURVIVED'}")
    print("camera mount OK" if not fails else f"camera mount FAILED ({len(fails)})")
    return fails


if __name__ == "__main__":
    raise SystemExit(1 if main() else 0)
