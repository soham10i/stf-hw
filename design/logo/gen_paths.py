"""Generate precise path strings for the STF Digital Twin logo concepts."""
import math

P = lambda v: round(v, 2)


def pt(cx, cy, r, deg):
    a = math.radians(deg)
    return (cx + r * math.cos(a), cy + r * math.sin(a))


def gear_path(cx, cy, r_out, r_in, teeth=8, start_deg=-90):
    """Polygonal gear, one tooth per 360/teeth degrees."""
    step = 360.0 / teeth
    pts = []
    for t in range(teeth):
        a0 = start_deg + t * step
        for frac, r in ((0.0, r_in), (0.16, r_in), (0.34, r_out),
                        (0.66, r_out), (0.84, r_in), (1.0, r_in)):
            pts.append(pt(cx, cy, r, a0 + frac * step))
    d = "M" + " L".join(f"{P(x)},{P(y)}" for x, y in pts) + " Z"
    return d


def circle_path(cx, cy, r, clockwise=True, start_deg=-90, n=48):
    pts = [pt(cx, cy, r, start_deg + (360.0 / n) * i * (1 if clockwise else -1))
           for i in range(n + 1)]
    return "M" + " L".join(f"{P(x)},{P(y)}" for x, y in pts) + " Z"


def hex_path(cx, cy, r, pointy=True, start_deg=-90):
    pts = [pt(cx, cy, r, start_deg + 60 * i) for i in range(6)]
    return "M" + " L".join(f"{P(x)},{P(y)}" for x, y in pts) + " Z"


# ---- Concept A: twin gears ----
print("== GEAR solid (8t) ==")
print(gear_path(28, 36, 19, 13.8))
print("== GEAR wire (8t) ==")
print(gear_path(44.5, 22.5, 13, 9.4))
print("== GEAR hub hole solid (donut inner, CCW) ==")
print(circle_path(28, 36, 6.2, clockwise=False))
print("== GEAR hub hole wire (CCW) ==")
print(circle_path(44.5, 22.5, 4.2, clockwise=False))

# ---- Concept D: twin hexagon ----
print("== HEX outer (pointy) ==")
print(hex_path(32, 32, 29.5))
print("== HEX inner dashed ==")
print(hex_path(32, 32, 21.5))
print("== HEX left quad (solid half) ==")
q = [(32, 2.5 + 0.0), pt(32, 32, 29.5, -150)[0], pt(32, 32, 29.5, -150)[1],
     pt(32, 32, 29.5, 150)[0], pt(32, 32, 29.5, 150)[1], (32, 61.5)]
# recompute explicitly: pointy hex vertices: top(32,2.5), ur(57.6,17.25), lr(57.6,46.75), bottom(32,61.5), ll(6.4,46.75), ul(6.4,17.25)
quad = [(32, 2.5), (6.4, 17.25), (6.4, 46.75), (32, 61.5)]
print("M" + " L".join(f"{P(x)},{P(y)}" for x, y in quad) + " Z")

# ---- Concept B: cookie with bite (bite circle center on r=25 at -32 deg) ----
import math as m
ang = m.radians(-32)
bx, by = 32 + 25 * m.cos(ang), 32.5 + 25 * m.sin(ang)
print("== COOKIE body (circle CW + bite hole CCW) ==")
body = circle_path(32, 32.5, 25)
bite = circle_path(bx, by, 8.5, clockwise=False)
print(body + " " + bite)
print("bite center:", P(bx), P(by))
