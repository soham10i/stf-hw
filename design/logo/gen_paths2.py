"""Smooth geometry for STF logo v2 — rounded isometric cell, ribbon, orbit, rack."""
import math

def rounded_poly(pts, r):
    """Closed polygon path with cubic-bezier rounded corners (SVG path string)."""
    n = len(pts)
    d = []
    for i in range(n):
        p0 = pts[(i - 1) % n]; p1 = pts[i]; p2 = pts[(i + 1) % n]
        v1 = (p0[0] - p1[0], p0[1] - p1[1]); L1 = math.hypot(*v1)
        v2 = (p2[0] - p1[0], p2[1] - p1[1]); L2 = math.hypot(*v2)
        a = (p1[0] + v1[0] / L1 * r, p1[1] + v1[1] / L1 * r)
        b = (p1[0] + v2[0] / L2 * r, p1[1] + v2[1] / L2 * r)
        if i == 0:
            d.append(f"M{a[0]:.2f},{a[1]:.2f}")
        else:
            d.append(f"L{a[0]:.2f},{a[1]:.2f}")
        d.append(f"Q{p1[0]:.2f},{p1[1]:.2f} {b[0]:.2f},{b[1]:.2f}")
    return " ".join(d) + " Z"

def offset(pts, dx, dy):
    return [(x + dx, y + dy) for x, y in pts]

P = lambda v: round(v, 2)

# ---- Concept A: isometric enclosure cell ----
T = (32, 9); R = (53, 21); BR = (53, 45); B = (32, 57); BL = (11, 45); L = (11, 21); C = (32, 33)
sil = [T, R, BR, B, BL, L]
print("== A outer silhouette rounded ==")
print(rounded_poly(sil, 3.6))
print("== A ghost twin silhouette (offset +4.5,-3.5, r 3.6) ==")
print(rounded_poly(offset(sil, 4.5, -3.5), 3.6))
print("== A inner Y ==")
print(f"M{L[0]},{L[1]} L{C[0]},{C[1]} L{R[0]},{R[1]} M{C[0]},{C[1]} L{B[0]},{B[1]}")

# ---- Concept B: twin ribbon S (two subpaths, stroke w/ round caps) ----
print("== B ribbon upper (blue) ==")
print("M43,18.5 C43,11.5 38,7.5 32,7.5 C25.5,7.5 21,11.5 21,18.5 C21,25.5 26.5,28 32,30")
print("== B ribbon lower (amber) ==")
print("M21,45.5 C21,52.5 26,56.5 32,56.5 C38.5,56.5 43,52.5 43,45.5 C43,38.5 37.5,36 32,34")

# ---- Concept C: orbit ring ellipse rotated -18 deg about (32,32) ----
cx = cy = 32; rx, ry = 24.5, 9; rot = math.radians(-18)
pts = []
for i in range(61):
    t = 2 * math.pi * i / 60
    x, y = rx * math.cos(t), ry * math.sin(t)
    xr = x * math.cos(rot) - y * math.sin(rot)
    yr = x * math.sin(rot) + y * math.cos(rot)
    pts.append((P(cx + xr), P(cy + yr)))
d = "M" + " L".join(f"{x},{y}" for x, y in pts) + " Z"
print("== C orbit ring ==")
print(d)
# satellite at param t ~ -35 deg (upper right area), keep on ring
t = math.radians(-30)
x, y = rx * math.cos(t), ry * math.sin(t)
xr = x * math.cos(rot) - y * math.sin(rot); yr = x * math.sin(rot) + y * math.cos(rot)
print("satellite:", P(cx + xr), P(cy + yr))
