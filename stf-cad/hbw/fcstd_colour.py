"""
Give a headless-built .FCStd real colours.

freecadcmd has no GUI, so `obj.ViewObject` does not exist and nothing can set a
colour the normal way. But colours do not live in the model document - they live
in GuiDocument.xml inside the .FCStd zip, alongside one small binary blob per
object. So we write those ourselves, in exactly the format FreeCAD 1.x wrote in
the user's own STF.FCStd:

    ShapeAppearance blob (40 bytes)
      uint32  count = 1
      uint32  ambient, diffuse, specular, emissive   (LE, packed 0xRRGGBBAA)
      float32 shininess
      float32 transparency
      12 bytes of zeros

Each object gets its own blob file and a <ViewProvider> entry naming it.
"""
import re
import shutil
import struct
import zipfile


def _packed(hexrgb):
    h = hexrgb.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return struct.pack("<I", (r << 24) | (g << 16) | (b << 8) | 0xFF)


def _blob(hexrgb, shininess=0.35, transparency=0.0):
    h = hexrgb.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    amb = f"#{r // 3:02x}{g // 3:02x}{b // 3:02x}"
    return (struct.pack("<I", 1) + _packed(amb) + _packed(hexrgb)
            + _packed("#888888") + _packed("#000000")
            + struct.pack("<f", shininess) + struct.pack("<f", transparency)
            + b"\x00" * 12)


VP_SOLID = """        <ViewProvider name="{name}" expanded="0" treeRank="{rank}">
            <Properties Count="4" TransientCount="0">
                <Property name="DisplayMode" type="App::PropertyEnumeration" status="1">
                    <Integer value="0"/>
                </Property>
                <Property name="ShapeAppearance" type="App::PropertyMaterialList" status="1">
                    <MaterialList file="{blob}" version="3"/>
                </Property>
                <Property name="ShapeColor" type="App::PropertyColor" status="1">
                    <PropertyColor value="{rgba}"/>
                </Property>
                <Property name="Visibility" type="App::PropertyBool" status="1">
                    <Bool value="true"/>
                </Property>
            </Properties>
        </ViewProvider>
"""

# Containers get a view provider of their own too. (An earlier comment here
# blamed missing container view providers for the file opening "empty"; testing
# in the real GUI showed the cause was the camera - see iso_camera().)
VP_GROUP = """        <ViewProvider name="{name}" expanded="1" treeRank="{rank}">
            <Properties Count="1" TransientCount="0">
                <Property name="Visibility" type="App::PropertyBool" status="1">
                    <Bool value="true"/>
                </Property>
            </Properties>
        </ViewProvider>
"""


# Each App::Part carries an App::Origin with 3 planes, 3 axes and a point.
# They are construction helpers: shown, 21 containers put 147 translucent
# squares and lines all over the model.
ORIGIN_TYPES = {"App::Origin", "App::Line", "App::Plane", "App::Point"}
VP_HIDDEN = VP_GROUP.replace('expanded="1"', 'expanded="0"').replace(
    '<Bool value="true"/>', '<Bool value="false"/>')


def _rotate(axis, angle, v):
    """Rotate vector v by `angle` rad about unit `axis` (Rodrigues)."""
    import math
    ax, ay, az = axis
    n = math.sqrt(ax * ax + ay * ay + az * az); ax, ay, az = ax / n, ay / n, az / n
    c, s_ = math.cos(angle), math.sin(angle)
    x, y, z = v
    dot = ax * x + ay * y + az * z
    cx, cy, cz = ay * z - az * y, az * x - ax * z, ax * y - ay * x
    return (x * c + cx * s_ + ax * dot * (1 - c), y * c + cy * s_ + ay * dot * (1 - c),
            z * c + cz * s_ + az * dot * (1 - c))


# FreeCAD's own isometric orientation, read back from its GUI (axis, angle)
ISO = ((0.74290597, 0.30772197, 0.59447265), 1.2140195)


def iso_camera(bbox):
    """An Open Inventor camera that frames `bbox` (xmin,ymin,zmin,xmax,ymax,zmax)
    in FreeCAD's isometric view. Without one the file stores an empty camera and
    FreeCAD opens staring into the corner at the origin - the model is there,
    but you are looking at 5 cm of the base plate."""
    import math
    c = [(bbox[i] + bbox[i + 3]) / 2.0 for i in range(3)]
    diag = math.sqrt(sum((bbox[i + 3] - bbox[i]) ** 2 for i in range(3)))
    back = _rotate(ISO[0], ISO[1], (0.0, 0.0, 1.0))      # camera looks down -Z
    dist = diag * 1.5
    pos = [c[i] + back[i] * dist for i in range(3)]
    (ax, ay, az), ang = ISO
    return ("#Inventor V2.1 ascii\n\n\nOrthographicCamera {\n"
            "  viewportMapping ADJUST_CAMERA\n"
            f"  position {pos[0]:.3f} {pos[1]:.3f} {pos[2]:.3f}\n"
            f"  orientation {ax} {ay} {az}  {ang}\n"
            f"  nearDistance {max(1.0, dist - diag):.3f}\n"
            f"  farDistance {dist + diag:.3f}\n"
            "  aspectRatio 1\n"
            f"  focalDistance {dist:.3f}\n"
            f"  height {diag * 0.9:.3f}\n\n}}\n")


def _cam_attr(camera):
    from xml.sax.saxutils import quoteattr
    return quoteattr(camera or "", {"\n": "&#10;"})


def colourise(path, colour_of, camera=None):
    """colour_of: object name -> '#rrggbb'. Rewrites the .FCStd in place."""
    with zipfile.ZipFile(path) as z:
        items = {n: z.read(n) for n in z.namelist()}
    doc = items["Document.xml"].decode("utf8")
    kinds = dict(re.findall(r'<Object type="([^"]+)" name="([^"]+)"', doc)[::1] and
                 [(n, t) for t, n in re.findall(r'<Object type="([^"]+)" name="([^"]+)"', doc)])
    names = re.findall(r'<Object name="([^"]+)"', doc) or list(kinds)
    seen, order = set(), []
    for n in names:                       # Document.xml lists each object twice
        if n not in seen:
            seen.add(n); order.append(n)

    for n in kinds:
        if n not in seen:
            seen.add(n); order.append(n)
    vps, blobs, rank, nblob = [], {}, 0, 0
    for n in order:
        c = colour_of.get(n)
        if c:
            c, tr = (c.split("/")[0], int(c.split("/")[1])) if "/" in c else (c, 0)   # '#rrggbb/70' = 70 % clear
            blob = "ShapeAppearance" if nblob == 0 else f"ShapeAppearance{nblob}"
            blobs[blob] = _blob(c, transparency=tr / 100.0)
            h = c.lstrip("#")
            r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
            vp = VP_SOLID.format(name=n, rank=rank, blob=blob, rgba=(r << 24) | (g << 16) | (b << 8) | 0xFF)
            if tr:
                vp = vp.replace('<Properties Count="4"', '<Properties Count="5"').replace(
                    '                <Property name="Visibility"',
                    f'                <Property name="Transparency" type="App::PropertyPercent" status="1">\n'
                    f'                    <Integer value="{tr}"/>\n                </Property>\n'
                    '                <Property name="Visibility"')
            vps.append(vp)
            nblob += 1
        elif kinds.get(n) in ORIGIN_TYPES:
            vps.append(VP_HIDDEN.format(name=n, rank=rank))
        else:
            vps.append(VP_GROUP.format(name=n, rank=rank))
        rank += 1

    gui = ("<?xml version='1.0' encoding='utf-8'?>\n"
           "<!-- FreeCAD Document -->\n"
           '<Document SchemaVersion="1" HasExpansion="1">\n'
           "    <Expand />\n"
           f'    <ViewProviderData Count="{len(vps)}">\n'
           + "".join(vps) +
           "    </ViewProviderData>\n"
           f'    <Camera settings={_cam_attr(camera)} />\n'
           "</Document>\n")

    items["GuiDocument.xml"] = gui.encode("utf8")
    items.update({k: v for k, v in blobs.items()})
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in items.items():
            z.writestr(n, data)
    shutil.move(tmp, path)
    return len(vps)
