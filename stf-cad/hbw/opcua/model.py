"""
Upgrade 14, step 2 - the cell's OPC UA information model (IEC 62541), generated from the model.

  COMPANION  OPC 40001-1 Machinery 1.04 (on DI 1.04 and IA 1.01, opcua/nodesets): the cell is a machine
             in the Machines folder, with the Machinery Identification (an AddIn) and the
             MachineryItemState state machine; its four modules are Machinery components, each with
             its own identification. The Identification's ProductInstanceUri is the cell's Asset
             Administration Shell asset id (Upgrade 14, step 1): the two standards point at one asset.
  SIGNALS    every PLC input and output of plc.json (Upgrade 13) is a TwoStateDiscreteType variable
             with the Belegungsplan's text; every encoder an AnalogUnitType with its UNECE unit and
             range; the RFID tag and the colour sensor are variables too. Node ids are readable:
             ns=STF;s=HBW.Inputs.I1.
  UNITS      the eight sequencers (STFUnitType): State, StateText, Job, Busy, Fault, Alarm.
  PRODUCTION the order: Phase, JobsCompleted, MachineTime, OrderTime, and the method StartOrder.
Every variable starts empty; opcua/server.py fills them from the software-in-the-loop PLC.
"""
import json
import os

from asyncua import ua
from asyncua.common.instantiate_util import instantiate as _instantiate

HERE = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.path.abspath(os.path.join(HERE, "..", "..", "..", "web", "public"))
NODESETS = [os.path.join(HERE, "nodesets", f) for f in
            ("Opc.Ua.Di.NodeSet2.xml", "Opc.Ua.IA.NodeSet2.xml", "Opc.Ua.Machinery.NodeSet2.xml")]
NS_URI = "https://soham10i.github.io/stf-hw/UA/"
DI_URI, MACH_URI = "http://opcfoundation.org/UA/DI/", "http://opcfoundation.org/UA/Machinery/"
CELL_ASSET = "https://soham10i.github.io/stf-hw/asset/stf-cell-u12"     # the AAS asset id (aas/build.py)

MODULES = {"hbw": "HBW", "vgr": "VGR", "oven": "Oven", "sorting": "Sorting"}
MODULE_NAME = {"hbw": "High-bay warehouse", "vgr": "Vacuum gripper robot", "oven": "Oven and turntable",
               "sorting": "Sorting line"}
UNIT_MODULE = {"crane": "hbw", "belt": "hbw", "arm": "vgr", "door": "oven", "sauger": "oven", "turntable": "oven",
               "ovenbelt": "oven", "line": "sorting"}
CEFACT = "http://www.opcfoundation.org/UA/units/un/cefact"


def unece(code):
    """EUInformation.UnitId from a UNECE Recommendation 20 common code (OPC 10000-8)."""
    v = 0
    for ch in code:
        v = (v << 8) | ord(ch)
    return v


EU = {"mm": ("MMT", "mm", "millimetre"), "deg": ("DD", "°", "degree"), "mV": ("2Z", "mV", "millivolt")}


def eu(kind):
    code, disp, desc = EU[kind]
    return ua.EUInformation(NamespaceUri=CEFACT, UnitId=unece(code), DisplayName=ua.LocalizedText(disp),
                            Description=ua.LocalizedText(desc))


async def load_companions(server):
    for f in NODESETS:
        await server.import_xml(f)


async def _find_type(server, name, base=None):
    stack = [base or server.nodes.base_object_type]
    while stack:
        n = stack.pop()
        if (await n.read_browse_name()).Name == name:
            return n
        stack += await n.get_children(refs=ua.ObjectIds.HasSubtype)
    raise LookupError(name)


async def _type_child(server, type_node, name):
    """A child declared by a type or one of its supertypes, by browse name."""
    t = type_node
    while t is not None:
        for c in await t.get_children():
            if (await c.read_browse_name()).Name == name:
                return c
        sup = await t.get_references(refs=ua.ObjectIds.HasSubtype, direction=ua.BrowseDirection.Inverse)
        t = server.get_node(sup[0].NodeId) if sup else None
    raise LookupError(name)


async def _optional(server, inst, type_node, name, value, vtype):
    """Add an optional property the type declares, with the type's own browse name and data type."""
    decl = await _type_child(server, type_node, name)
    bn = await decl.read_browse_name()
    dt = await decl.read_data_type()
    node = await inst.add_property(ua.NodeId(f"{inst.nodeid.Identifier}.{name}", inst.nodeid.NamespaceIndex), bn,
                                   ua.Variant(value, vtype), datatype=dt)
    return node


async def _relink(parent, child, ref_type):
    """Replace the reference asyncua made from parent to child (HasComponent or Organizes) by ref_type."""
    for r in await parent.get_references(direction=ua.BrowseDirection.Forward):
        if r.NodeId == child.nodeid and r.ReferenceTypeId.Identifier != ref_type:
            await parent.delete_reference(child, r.ReferenceTypeId)
    await parent.add_reference(child, ua.NodeId(ref_type))


async def _as_addin(parent, child):
    """Machinery adds Identification and the state machines as AddIns, not plain components."""
    await _relink(parent, child, ua.ObjectIds.HasAddIn)


async def _set(node, name, value, vtype):
    c = await node.get_child([name])
    await c.write_value(ua.Variant(value, vtype))
    return c


async def instantiate(parent, type_node, nodeid, bname):
    """A type's instance with its mandatory children only; optional ones are added where there is data."""
    return await _instantiate(parent, type_node, nodeid, bname=bname, instantiate_optional=False)


class Model:
    """The address space, and where each live value goes."""

    def __init__(self):
        self.signals = {}        # plc.json io name -> node
        self.units = {}          # unit -> {State, StateText, Job, Busy, Fault, Alarm}
        self.production = {}
        self.cell = None
        self.item_state = None
        self.states = {}         # Machinery item state name -> its state node id


async def build(server, io=None):
    io = io or json.load(open(os.path.join(PUBLIC, "sil", "plc.json")))["io"]
    ns = await server.register_namespace(NS_URI)
    di = await server.get_namespace_index(DI_URI)
    mi = await server.get_namespace_index(MACH_URI)
    m = Model()
    N = lambda s: ua.NodeId(s, ns)                              # noqa: E731

    # ---- types
    unit_t = await server.nodes.base_object_type.add_object_type(N("STFUnitType"), f"{ns}:STFUnitType")
    await unit_t.write_attribute(ua.AttributeIds.Description, ua.DataValue(ua.Variant(
        ua.LocalizedText("A unit sequencer of the PLC program (Upgrade 13): its state machine, job and alarm"))))
    for name, vt, default in (("State", ua.VariantType.Int16, 0), ("StateText", ua.VariantType.String, ""),
                              ("Job", ua.VariantType.String, ""), ("Busy", ua.VariantType.Boolean, False),
                              ("Fault", ua.VariantType.Boolean, False), ("Alarm", ua.VariantType.Int16, 0)):
        v = await unit_t.add_variable(N(f"STFUnitType.{name}"), f"{ns}:{name}", ua.Variant(default, vt))
        await v.set_modelling_rule(True)
    ident_t = await _find_type(server, "MachineIdentificationType")
    item_ident_t = await _find_type(server, "MachineryComponentIdentificationType")
    comps_t = await _find_type(server, "MachineComponentsType")
    state_t = await _find_type(server, "MachineryItemState_StateMachineType")
    two_t = server.get_node(ua.ObjectIds.TwoStateDiscreteType)
    analog_t = server.get_node(ua.ObjectIds.AnalogUnitType)

    # ---- the cell, in Machinery's Machines folder
    machines = await server.nodes.objects.get_child([f"{mi}:Machines"])
    cell = await machines.add_object(N("Cell"), f"{ns}:STF_Cell")
    await _relink(machines, cell, ua.ObjectIds.Organizes)
    m.cell = cell
    ident = (await instantiate(cell, ident_t, N("Cell.Identification"), bname=ua.QualifiedName("Identification", di)))[0]
    ident = server.get_node(ident)
    await _as_addin(cell, ident)
    await _set(ident, f"{di}:Manufacturer", ua.LocalizedText("STF digital twin project"), ua.VariantType.LocalizedText)
    await _set(ident, f"{di}:SerialNumber", "VIRTUAL-0001", ua.VariantType.String)
    await _set(ident, f"{di}:ProductInstanceUri", CELL_ASSET, ua.VariantType.String)
    await _optional(server, ident, ident_t, "Model", ua.LocalizedText("Smart Tabletop Factory, Upgrade 12"), ua.VariantType.LocalizedText)
    await _optional(server, ident, ident_t, "YearOfConstruction", 2026, ua.VariantType.UInt16)
    sil = json.load(open(os.path.join(PUBLIC, "sil", "sil.json")))
    await _optional(server, ident, ident_t, "SoftwareRevision", f"PLC {sil['wasm_sha']}", ua.VariantType.String)
    await _optional(server, ident, ident_t, "ProductCode", "STF-U12", ua.VariantType.String)
    state = server.get_node((await instantiate(cell, state_t, N("Cell.MachineryItemState"),
                                               bname=ua.QualifiedName("MachineryItemState", mi)))[0])
    await _as_addin(cell, state)
    m.item_state = state
    for s in ("NotAvailable", "OutOfService", "Executing", "NotExecuting"):
        m.states[s] = (await _type_child(server, state_t, s)).nodeid

    # ---- the modules: Machinery components
    comps = server.get_node((await instantiate(cell, comps_t, N("Cell.Components"), bname=ua.QualifiedName("Components", mi)))[0])
    for mod, label in MODULES.items():
        mo = await comps.add_object(N(label), f"{ns}:{label}")
        await mo.write_attribute(ua.AttributeIds.Description, ua.DataValue(ua.Variant(ua.LocalizedText(MODULE_NAME[mod]))))
        mid = server.get_node((await instantiate(mo, item_ident_t, N(f"{label}.Identification"),
                                                 bname=ua.QualifiedName("Identification", di)))[0])
        await _as_addin(mo, mid)
        await _set(mid, f"{di}:Manufacturer", ua.LocalizedText("STF digital twin project"), ua.VariantType.LocalizedText)
        await _set(mid, f"{di}:SerialNumber", f"VIRTUAL-0001-{label}", ua.VariantType.String)
        folders = {k: await mo.add_folder(N(f"{label}.{k}"), f"{ns}:{k}") for k in ("Inputs", "Outputs", "Units")}
        for kind, area in (("Inputs", "ix"), ("Outputs", "qx")):
            for e in io[area]:
                if e["module"] != mod:
                    continue
                sig = e["signal"]
                nid = N(f"{label}.{kind}.{sig}")
                node = server.get_node((await instantiate(folders[kind], two_t, nid, bname=ua.QualifiedName(sig, ns)))[0])
                await node.write_value(ua.Variant(False, ua.VariantType.Boolean))
                desc = e.get("desc") or sig
                await node.write_attribute(ua.AttributeIds.Description, ua.DataValue(ua.Variant(ua.LocalizedText(desc))))
                await _set(node, "0:TrueState", ua.LocalizedText("on" if area == "qx" else "made"), ua.VariantType.LocalizedText)
                await _set(node, "0:FalseState", ua.LocalizedText("off" if area == "qx" else "open"), ua.VariantType.LocalizedText)
                m.signals[e["name"]] = node
        for e in io["id"]:
            if (e["unit"] == "crane" and mod == "hbw") or (e["unit"] == "arm" and mod == "vgr"):
                axis = e["axis"]
                node = server.get_node((await instantiate(mo, analog_t, N(f"{label}.Encoders.{axis}"),
                                                          bname=ua.QualifiedName(f"Position_{axis}", ns)))[0])
                await node.write_value(ua.Variant(0.0, ua.VariantType.Double))
                await node.write_attribute(ua.AttributeIds.Description, ua.DataValue(ua.Variant(
                    ua.LocalizedText(f"{e['unit']} {axis} position, from the encoder counter"))))
                kind = "deg" if axis == "swivel" else "mm"
                lo, hi = {"travel": (0, 665), "lift": (0, 400), "plunge": (84, 540), "reach": (0, 400), "swivel": (-180, 180)}[axis]
                await _optional(server, node, analog_t, "EURange", ua.Range(Low=lo, High=hi), ua.VariantType.ExtensionObject)
                await _set(node, "0:EngineeringUnits", eu(kind), ua.VariantType.ExtensionObject)
                m.signals[e["name"]] = node
        for e in io["iw"]:
            if e["name"].startswith(mod + "_"):
                tag = e["name"].split("_", 1)[1]
                if tag == "A4":
                    node = server.get_node((await instantiate(mo, analog_t, N(f"{label}.ColourSensor"),
                                                              bname=ua.QualifiedName("ColourSensor_A4", ns)))[0])
                    await node.write_value(ua.Variant(0.0, ua.VariantType.Double))
                    await _optional(server, node, analog_t, "EURange", ua.Range(Low=0, High=2000), ua.VariantType.ExtensionObject)
                    await _set(node, "0:EngineeringUnits", eu("mV"), ua.VariantType.ExtensionObject)
                else:
                    node = await mo.add_variable(N(f"{label}.{tag}"), f"{ns}:{tag}", ua.Variant(0, ua.VariantType.Int16))
                await node.write_attribute(ua.AttributeIds.Description, ua.DataValue(ua.Variant(ua.LocalizedText(e["desc"]))))
                m.signals[e["name"]] = node
        for u, um in UNIT_MODULE.items():
            if um == mod:
                un = await folders["Units"].add_object(N(f"{label}.Units.{u}"), f"{ns}:{u}", objecttype=unit_t)
                m.units[u] = {k: await un.get_child([f"{ns}:{k}"]) for k in ("State", "StateText", "Job", "Busy", "Fault", "Alarm")}

    # ---- the safety relay: a cell-wide input, in no module
    safety = await cell.add_folder(N("Safety"), f"{ns}:Safety")
    for e in io["ix"]:
        if e["module"] == "cell":
            node = server.get_node((await instantiate(safety, two_t, N(f"Safety.{e['signal']}"),
                                                      ua.QualifiedName(e["signal"], ns)))[0])
            await node.write_value(ua.Variant(False, ua.VariantType.Boolean))
            await node.write_attribute(ua.AttributeIds.Description, ua.DataValue(ua.Variant(ua.LocalizedText(e["desc"]))))
            await _set(node, "0:TrueState", ua.LocalizedText("OK"), ua.VariantType.LocalizedText)
            await _set(node, "0:FalseState", ua.LocalizedText("tripped"), ua.VariantType.LocalizedText)
            m.signals[e["name"]] = node

    # ---- the order
    prod = await cell.add_object(N("Production"), f"{ns}:Production")
    for name, vt, default in (("Phase", ua.VariantType.String, "homing"), ("JobsCompleted", ua.VariantType.UInt32, 0),
                              ("MachineTime", ua.VariantType.Double, 0.0), ("OrderTime", ua.VariantType.Double, 0.0),
                              ("Run", ua.VariantType.UInt32, 0)):
        m.production[name] = await prod.add_variable(N(f"Production.{name}"), f"{ns}:{name}", ua.Variant(default, vt))
    m.production["_object"] = prod
    m.ns = ns
    return m


async def our_nodes(server, m):
    """Every node of the STF namespace, for the NodeSet export: the types and the cell, depth first."""
    roots = [m.cell, server.get_node(ua.NodeId("STFUnitType", m.ns))]
    out, seen, stack = [], set(), list(roots)
    while stack:
        n = stack.pop()
        if n.nodeid in seen:
            continue
        seen.add(n.nodeid)
        if n.nodeid.NamespaceIndex == m.ns:
            out.append(n)
        stack += await n.get_children(refs=ua.ObjectIds.HierarchicalReferences)
    return out
