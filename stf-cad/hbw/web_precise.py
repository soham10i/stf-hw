"""
Precise part meshes for the web twin's Upgrade 1 view - run INSIDE FreeCAD:

    STF_VARIANT=up1 freecadcmd web_precise.py

Every part is shaped by EXACTLY the functions that build STF_Factory_MCP.FCStd
(mcp_build._solid): detail_rich.rich() for the booklet-photo oven detail
(kiln bond seams, roof caps, door, lamp lens, Statik struts, 24-tooth saw,
geared Drehtisch, ribbed belt), otherwise mechanics.guided() - detail.precise()
(rounded ft blocks, chamfered pins, T-slot profiles, suction cup, cookies) with
every guide pocket of the model's GUIDES table cut in. All of these assert that
the detailed solid stays inside the part's proven envelope, so the clearance
proofs still hold for the geometry drawn.

Output: web/public/precise_up1.glb - one mesh node per part (per sub-solid for
rich parts) named "<module>:<part>[:<sub>]", vertices in MILLIMETRES in the
same frame the part has in hbw_parts_up1.json (joint-local for the HBW, module
frame at the authoring pose for the rest, factory frame for Upgrade 1's own
parts). No node transforms: the web places a mesh exactly where the part's box
was. Parts that animate by themselves in the web (spindles, belts, springs)
and parts drawn as a precise FreeCAD component (wiring.fit) are left out.
"""
import json, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import FreeCAD as App  # noqa: F401  (must run under freecadcmd)
import detail, detail_rich, mechanics
import stf_gltf as SG
import stf_web_glb as SW
from hbw_export import col
import hbw_model as HM
from hbw_frames import by_frame
import oven_model as OM
import sorting_model as SM
import vgr_model as VG
import upgrade as U
import wiring
from variant import UP1, UP2, VARIANT

OUT = os.path.expanduser(f"~/workspace/stf-hw/web/public/precise_{VARIANT}.glb")
SKIP_MECH = ("thread:", "spring", "belt", "chain:")     # animated by the web's own renderers
HEX_CLASS = {detail_rich.STEEL: "metal", detail_rich.ALU: "metal", detail_rich.RUBBER: "rubber"}


class MmGltf(SW.WebGltf):
    """WebGltf's PBR material classes, but millimetres and no root rotation."""

    def __init__(self):
        SG.Gltf.__init__(self, 1.0)
        self._cls = "plastic"

    def blob(self):
        doc = {"asset": {"version": "2.0", "generator": "stf-cad/hbw/web_precise.py"},
               "scene": 0, "scenes": [{"nodes": list(range(len(self.nodes)))}],
               "nodes": self.nodes, "meshes": self.meshes, "materials": self.mats,
               "accessors": self.acc, "bufferViews": self.views,
               "buffers": [{"byteLength": len(self.buf)}]}
        js = json.dumps(doc, separators=(",", ":")).encode()
        js += b" " * (-len(js) % 4)
        bn = bytes(self.buf) + b"\0" * (-len(self.buf) % 4)
        total = 12 + 8 + len(js) + 8 + len(bn)
        return (struct.pack("<III", 0x46546C67, 2, total)
                + struct.pack("<II", len(js), 0x4E4F534A) + js
                + struct.pack("<II", len(bn), 0x004E4942) + bn)


def _fitted(p):
    d = {"n": p.name, "tag": p.tag, "mech": p.mech, "k": p.kind, "p": list(p.p),
         "s": list(p.s)}
    return wiring.fit(d) is not None


def _shift(pos, at):
    return [(x + at[0], y + at[1], z) for x, y, z in pos]


def emit(g, module, p, siblings, at=None, stats=None):
    if p.group == "frame" or p.mech.startswith(SKIP_MECH) or p.mech == "panel" or _fitted(p):
        return
    if "pcb" in p.name.lower():
        return                                   # the web's PcbBoard is the richer model
    if module == "hbw" and (p.name.startswith("mould_") or p.name.startswith("wp_")):
        return                                   # the rack is drawn from the live rack state
    kind = "thread" if p.mech.startswith("thread:") else p.kind
    tol = g.TOLS[kind]
    subs = detail_rich.rich(p, module)
    if subs:
        for nm, shp, hexc in subs:
            g._cls = HEX_CLASS.get(hexc, SW.material_class(p))
            pos, nrm, idx = SW.face_mesh(shp, tol)
            if at:
                pos = _shift(pos, at)
            m = g.mesh(f"{p.name}.{nm}", pos, nrm, idx, hexc)
            g.node(f"{module}:{p.name}:{nm}", mesh=m,
                   extras={"module": module, "part": p.name, "sub": nm})
        stats["rich"] += 1
    else:
        g._cls = SW.material_class(p)
        shp = mechanics.guided(p, module, siblings) if module in ("hbw", "vgr", "oven", "sorting") \
            else detail.precise(p, siblings)
        pos, nrm, idx = SW.face_mesh(shp, tol)
        if at:
            pos = _shift(pos, at)
        m = g.mesh(p.name, pos, nrm, idx, col(p.colour))
        g.node(f"{module}:{p.name}", mesh=m, extras={"module": module, "part": p.name})
        stats["precise"] += 1
    g._cls = "plastic"


def main():
    assert UP1, "run with STF_VARIANT=up1 or up2 - this is the upgrade views' geometry"
    from detail_rich_names import RICH_NAMES
    assert set(detail_rich.RICH) == RICH_NAMES, \
        f"detail_rich.RICH changed - update detail_rich_names.py: {set(detail_rich.RICH) ^ RICH_NAMES}"
    g = MmGltf()
    st = {"rich": 0, "precise": 0}
    sib = {p.name: p for p in HM.build()}
    for fr in by_frame().values():
        for p in fr:
            emit(g, "hbw", p, sib, stats=st)
    for mod, parts in (("vgr", VG.build()), ("oven", OM.build()), ("sorting", SM.build())):
        s = {p.name: p for p in parts}
        for p in parts:
            emit(g, mod, p, s, stats=st)
    for at, parts in ((U.BUF_AT, U.buffer_parts()), (U.AIR_AT, U.air_parts())):
        for p in parts:
            emit(g, "upgrade", p, {}, at=at, stats=st)
    if UP2:
        import safety
        for p in safety.guard_parts():
            emit(g, "safety", p, {}, stats=st)
    from variant import UP3
    if UP3:
        import io_nodes
        for m in io_nodes.MODULES:
            for p in io_nodes.parts(m):
                emit(g, "io", p, {}, stats=st)
    blob = g.blob()
    with open(OUT, "wb") as fh:
        fh.write(blob)
    ntri = sum(a["count"] for a in g.acc if a["type"] == "SCALAR") // 3
    print(f"wrote {OUT}  ({len(blob) / 1024:.0f} kB)  {len(g.nodes)} meshes, {ntri} triangles, "
          f"{st['rich']} rich parts, {st['precise']} precise parts")


if __name__ == "__main__" or sys.argv[-1].endswith("web_precise.py"):
    main()
