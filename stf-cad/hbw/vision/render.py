"""
Upgrade 15 - the camera over the sorting line, as a renderer of training images.

There is no camera and no real cookie to photograph, so the images are made
from the model: the cookie's size (sorting_model WP_D), its flavour colours and
the dough colour (pipeline), the way the twin bakes it (raw dough blended toward
the flavour colour), and the belt's rubber (detail_rich RUBBER). A camera looks
straight down just upstream of the colour sensor: 64 x 64 px over 80 mm.

  CONDITION  ok, underbaked, burnt, cracked, chipped - the faults a baking line
             rejects; each drawn the way it shows from above.
  RANDOM     everything the real images would vary in: position, rotation,
             size, light level and colour, the shading of the dome, the belt's
             texture, sensor noise, focus.  (Domain randomisation, Tobin et
             al. 2017: train on wide variation so the real world is one more
             variation.)
  NARROW/WIDE  two amounts of randomisation; the deployed network learns WIDE.
  REFERENCE  a grey target in the corner of every image, as inspection stations
             mount one: the network can divide out the light level and colour.
  SHIFT      the test images that measure generalisation are drawn OUTSIDE the
             training ranges: darker and brighter light, a warmer lamp, motion
             blur from the moving belt, more noise, a worn (lighter) belt.
Everything is ASSUMED: it shows the method, not the accuracy on a real camera.
"""
import math
import struct
import zlib

import numpy as np

import pipeline as PL
import sorting_model as SM

N = 64                                  # pixels
MM = 80.0                               # field of view, mm
PX = N / MM                             # px per mm
FLAVOURS = list(PL.FLAVOURS)            # chocolate, strawberry, vanilla
CONDITIONS = ["ok", "underbaked", "burnt", "cracked", "chipped"]
REF = 6                                 # the grey reference target: REF x REF px in the top-left corner
BELT = "#1f2023"                        # detail_rich.RUBBER


def rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32) / 255.0


DOUGH = rgb(PL.RAW_COLOUR)
COLOUR = {f: rgb(PL.FLAVOURS[f]["colour"]) for f in FLAVOURS}

# NARROW: what a first attempt randomises. WIDE: the deployed one - wider in every nuisance
# factor, but still short of SHIFT, the test of conditions never seen in training: darker and
# brighter light, a warmer lamp, more noise and blur, motion blur, a worn belt.
NARROW = dict(light=(0.75, 1.25), tint=0.06, noise=(0.005, 0.03), blur=(0.0, 0.8), motion=(0.0, 0.0),
              belt=(0.8, 1.3), jitter=6.0, warm=False)
WIDE = dict(light=(0.6, 1.4), tint=0.10, noise=(0.005, 0.035), blur=(0.0, 1.0), motion=(0.0, 1.0),
            belt=(0.8, 1.8), jitter=7.0, warm=False)
# A camera on a real line: exposure about 1 ms (the belt moves 0.05 mm), so motion blur stays
# under a pixel or two. SHIFT goes beyond WIDE, but not beyond what a real camera would see.
SHIFT = dict(light=(0.5, 0.6, 1.4, 1.55), tint=0.12, noise=(0.03, 0.045), blur=(0.8, 1.2), motion=(1.0, 2.0),
             belt=(1.9, 2.4), jitter=8.0, warm=True)
TRAIN = WIDE

_yy, _xx = np.mgrid[0:N, 0:N].astype(np.float32)


def _blur(img, s):
    """Separable Gaussian blur, sigma in px."""
    if s <= 0.05:
        return img
    r = max(1, int(3 * s))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / s) ** 2)
    k /= k.sum()
    pad = np.pad(img, ((r, r), (r, r), (0, 0)), mode="edge")
    tmp = sum(k[i] * pad[i:i + N, :, :] for i in range(2 * r + 1))
    return sum(k[i] * tmp[:, i:i + N, :] for i in range(2 * r + 1))


def _motion(img, px):
    """The belt moves along x during the exposure."""
    n = int(round(px))
    if n < 1:
        return img
    pad = np.pad(img, ((0, 0), (n, n), (0, 0)), mode="edge")
    return sum(pad[:, i:i + N, :] for i in range(2 * n + 1)) / (2 * n + 1)


def render(flavour, condition, rnd, R=TRAIN):
    """One camera image (N x N x 3, 0..1) of a cookie of a flavour in a condition, under ranges R."""
    u = rnd.uniform
    # the belt: dark rubber, a fine texture and the lateral ribs
    belt = rgb(BELT) * u(*R["belt"])
    img = np.ones((N, N, 3), np.float32) * belt
    img += (rnd.standard_normal((N, N, 1)) * 0.015).astype(np.float32)
    rib = 0.02 * (np.sin((_xx + u(0, 8)) * 2 * math.pi / 8) > 0.6)
    img += rib[..., None]
    # the cookie: a shallow dome, its colour from the bake
    cx, cy = N / 2 + u(-R["jitter"], R["jitter"]), N / 2 + u(-R["jitter"], R["jitter"])
    rad = SM.S["WP_D"] / 2 * PX * u(0.92, 1.08)
    rot = u(0, 2 * math.pi)
    dx, dy = _xx - cx, _yy - cy
    d = np.sqrt(dx ** 2 + dy ** 2) / rad
    inside = d <= 1.0
    bake = {"ok": u(0.9, 1.0), "underbaked": u(0.15, 0.55), "burnt": 1.0}.get(condition, u(0.9, 1.0))
    base = DOUGH + (COLOUR[flavour] - DOUGH) * bake
    if condition == "burnt":
        base = base * u(0.35, 0.55)
    shade = 1.0 - 0.35 * d ** 2                                 # the dome darkens toward the rim
    col = base[None, None, :] * shade[..., None]
    col *= (1 + rnd.standard_normal((N, N, 1)).astype(np.float32) * 0.04)   # crumb texture
    if condition == "burnt":                                   # a charred rim
        rim = np.clip((d - u(0.6, 0.75)) / 0.3, 0, 1)
        col *= (1 - 0.7 * rim)[..., None]
    if condition == "underbaked":                              # a pale, glossy centre
        col += (0.12 * np.clip(1 - d / 0.5, 0, 1))[..., None]
    if condition == "cracked":                                 # a dark, jagged line through the top
        ax, ay = math.cos(rot), math.sin(rot)
        along = dx * ax + dy * ay
        across = -dx * ay + dy * ax
        wiggle = 1.6 * np.sin(along * u(0.4, 0.8) + u(0, 6))
        w = u(0.8, 1.6)
        crack = (np.abs(across - wiggle) < w) & (np.abs(along) < rad * u(0.6, 0.95))
        col[crack] *= u(0.25, 0.45)
    if condition == "chipped":                                 # a bite out of the edge
        bx, by = cx + math.cos(rot) * rad, cy + math.sin(rot) * rad
        bite = np.sqrt((_xx - bx) ** 2 + (_yy - by) ** 2) < rad * u(0.3, 0.5)
        inside = inside & ~bite
    # the grey reference target on the rail, in a corner the cookie never reaches (jitter + radius
    # stay > 4 px away): 50 % reflectance, so it sees the same light and lamp colour as the cookie
    img[:REF, :REF] = 0.5
    # a soft shadow on the belt (light from above-left), then the cookie
    sh = np.sqrt((_xx - cx - 2) ** 2 + (_yy - cy - 2) ** 2) / rad <= 1.05
    img[sh & ~inside] *= 0.7
    img[inside] = col[inside]
    # the light: level and colour; a highlight on the dome
    light = u(*R["light"][:2]) if len(R["light"]) == 2 else (
        u(*R["light"][:2]) if rnd.random() < 0.5 else u(*R["light"][2:]))
    tint = 1 + rnd.uniform(-R["tint"], R["tint"], 3).astype(np.float32)
    if R["warm"]:
        tint = tint * np.array([1.08, 1.0, 0.9], np.float32)    # a warmer lamp than in training
    img = img * light * tint
    hx, hy = cx - rad * 0.35, cy - rad * 0.35
    img[inside] += (0.08 * np.exp(-((_xx - hx) ** 2 + (_yy - hy) ** 2) / (rad * 0.3) ** 2))[inside][..., None]
    # the optics and the sensor
    img = _motion(_blur(img, u(*R["blur"])), u(*R["motion"]))
    img = img + rnd.standard_normal(img.shape).astype(np.float32) * u(*R["noise"])
    return np.clip(img, 0, 1)


def dataset(n, seed, R=TRAIN):
    """n images with balanced labels: X (n, 3, N, N) float32, flavour and condition indices."""
    rnd = np.random.default_rng(seed)
    X = np.empty((n, 3, N, N), np.float32)
    yf = np.empty(n, np.int64)
    yc = np.empty(n, np.int64)
    for i in range(n):
        f = i % len(FLAVOURS)
        c = (i // len(FLAVOURS)) % len(CONDITIONS)
        X[i] = render(FLAVOURS[f], CONDITIONS[c], rnd, R).transpose(2, 0, 1)
        yf[i], yc[i] = f, c
    return X, yf, yc


def png(img):
    """An RGB image (H x W x 3, 0..1) as PNG bytes (no imaging library needed)."""
    a = (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)
    h, w, _ = a.shape
    raw = b"".join(b"\x00" + a[y].tobytes() for y in range(h))

    def chunk(t, data):
        return struct.pack(">I", len(data)) + t + data + struct.pack(">I", zlib.crc32(t + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
