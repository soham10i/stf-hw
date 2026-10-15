"""
Upgrade 14, step 2 - proofs of the OPC UA server.

    python3 -m opcua.check            (from stf-cad/hbw; about a minute; or `make opcua-check`)

A real server is started on a test port with a random password, and real clients connect to it.
  (1) MAPPING      every signal of the compiled program's I/O image (plc.json) is exactly one node,
                   boolean signals TwoStateDiscreteType, encoders and the colour sensor AnalogUnitType
                   with a UNECE unit; every unit sequencer is an STFUnitType object.
  (2) TYPES        every node conforms to its type definition: each Mandatory child declared by the
                   type or any supertype is present (a walk independent of how the nodes were made).
  (3) MACHINERY    the cell is organised by the Machines folder; Identification and MachineryItemState
                   are AddIns; Manufacturer, SerialNumber and ProductInstanceUri are filled, and the
                   ProductInstanceUri is the cell's Asset Administration Shell asset id (step 1).
  (4) NODESET      the STF namespace exported as NodeSet2 XML loads into a fresh server next to DI, IA
                   and Machinery, and gives back the same nodes, browse names, classes and types.
  (5) SECURITY     the server offers only Basic256Sha256 Sign & Encrypt; it refuses a client without
                   security, an anonymous one, a wrong password and an untrusted certificate; it
                   accepts the trusted certificate with the right password, read-only.
  (6) LIVE         a client subscribes, calls StartOrder and watches the order run to "complete"; the
                   OrderTime and JobsCompleted it reads equal Upgrade 13's proof run.
  (7) MUTANTS      a missing signal node, a missing mandatory child, a wrong ProductInstanceUri and an
                   anonymous endpoint are each caught.
Output: web/public/opcua/stf.NodeSet2.xml and opcua.json (the address space and these results).
"""
import asyncio
import json
import logging
import os
import secrets
import shutil
import time

from asyncua import Client, Server, ua
from asyncua.common.xmlexporter import XmlExporter
from asyncua.crypto.cert_gen import setup_self_signed_certificate
from asyncua.server.user_managers import PermissiveUserManager
from cryptography.x509.oid import ExtendedKeyUsageOID

from opcua import model as M
from opcua import server as S

OUT = os.path.join(M.PUBLIC, "opcua")
PORT = 48401
SPEED = 40
log = logging.getLogger("stf.opcua.check")


# ------------------------------------------------------------- server-side proofs
async def mandatory_children(server, type_node):
    """Mandatory InstanceDeclarations of a type and all its supertypes, by browse name."""
    out, t = set(), type_node
    while t is not None:
        for r in await t.get_references(refs=ua.ObjectIds.HierarchicalReferences, direction=ua.BrowseDirection.Forward):
            if r.ReferenceTypeId.Identifier == ua.ObjectIds.HasSubtype:
                continue
            c = server.get_node(r.NodeId)
            rules = await c.get_references(refs=ua.ObjectIds.HasModellingRule)
            if rules and rules[0].NodeId == ua.NodeId(ua.ObjectIds.ModellingRule_Mandatory):
                out.add((await c.read_browse_name()).to_string())
        sup = await t.get_references(refs=ua.ObjectIds.HasSubtype, direction=ua.BrowseDirection.Inverse)
        t = server.get_node(sup[0].NodeId) if sup and sup[0].NodeId.Identifier != ua.ObjectIds.BaseObjectType else None
        if t is not None and t.nodeid in (ua.NodeId(ua.ObjectIds.BaseDataVariableType), ua.NodeId(ua.ObjectIds.BaseVariableType)):
            t = None
    return out


async def check_types(server, nodes):
    fails, cache = [], {}
    for n in nodes:
        td = await n.read_type_definition() if await n.read_node_class() in (ua.NodeClass.Object, ua.NodeClass.Variable) else None
        if td is None:
            continue
        if td not in cache:
            cache[td] = await mandatory_children(server, server.get_node(td))
        have = {(await c.read_browse_name()).to_string() for c in await n.get_children(refs=ua.ObjectIds.HierarchicalReferences)}
        for name in cache[td] - have:
            fails.append(f"TYPES {n.nodeid.to_string()}: mandatory {name} of its type is missing")
    return fails


async def check_mapping(server, m, io):
    fails = []
    want = [e["name"] for area in ("ix", "qx", "iw", "id") for e in io[area]]
    for name in want:
        if name not in m.signals:
            fails.append(f"MAPPING {name}: no node")
    ids = [n.nodeid for n in m.signals.values()]
    if len(ids) != len(set(ids)):
        fails.append("MAPPING two signals share a node")
    for e in io["ix"] + io["qx"]:
        n = m.signals.get(e["name"])
        if n is not None and await n.read_type_definition() != ua.NodeId(ua.ObjectIds.TwoStateDiscreteType):
            fails.append(f"MAPPING {e['name']}: not TwoStateDiscreteType")
    for e in io["id"]:
        n = m.signals.get(e["name"])
        if n is not None and await n.read_type_definition() != ua.NodeId(ua.ObjectIds.AnalogUnitType):
            fails.append(f"MAPPING {e['name']}: not AnalogUnitType")
    if sorted(m.units) != sorted(M.UNIT_MODULE):
        fails.append(f"MAPPING units {sorted(m.units)}")
    return fails


async def check_machinery(server, m):
    fails = []
    mi = await server.get_namespace_index(M.MACH_URI)
    di = await server.get_namespace_index(M.DI_URI)
    machines = await server.nodes.objects.get_child([f"{mi}:Machines"])
    refs = await machines.get_references(refs=ua.ObjectIds.Organizes, direction=ua.BrowseDirection.Forward)
    if m.cell.nodeid not in [r.NodeId for r in refs]:
        fails.append("MACHINERY the cell is not organised by the Machines folder")
    addins = {(await server.get_node(r.NodeId).read_browse_name()).Name: server.get_node(r.NodeId)
              for r in await m.cell.get_references(refs=ua.NodeId(ua.ObjectIds.HasAddIn), direction=ua.BrowseDirection.Forward)}
    for k in ("Identification", "MachineryItemState"):
        if k not in addins:
            fails.append(f"MACHINERY {k} is not an AddIn of the cell")
    ident = addins.get("Identification")
    if ident is not None:
        for name in (f"{di}:Manufacturer", f"{di}:SerialNumber", f"{di}:ProductInstanceUri"):
            try:
                v = await (await ident.get_child([name])).read_value()
            except ua.UaStatusCodeError:
                v = None
            if not v or (isinstance(v, ua.LocalizedText) and not v.Text):
                fails.append(f"MACHINERY Identification {name} is empty")
        aas = json.load(open(os.path.join(M.PUBLIC, "aas", "stf.aas.json")))
        cell_asset = next(s["assetInformation"]["globalAssetId"] for s in aas["assetAdministrationShells"]
                          if s["assetInformation"]["assetKind"] == "Instance")
        try:
            uri = await (await ident.get_child([f"{di}:ProductInstanceUri"])).read_value()
        except ua.UaStatusCodeError:
            uri = None
        if uri != cell_asset:
            fails.append(f"MACHINERY ProductInstanceUri {uri} is not the AAS asset id {cell_asset}")
    return fails


async def signature(server, nodes):
    out = {}
    for n in nodes:
        cls = await n.read_node_class()
        td = await n.read_type_definition() if cls in (ua.NodeClass.Object, ua.NodeClass.Variable) else None
        out[n.nodeid.to_string()] = ((await n.read_browse_name()).to_string(), cls.name, td.to_string() if td else None)
    return out


async def check_nodeset(server, m, path):
    nodes = await M.our_nodes(server, m)
    exp = XmlExporter(server)
    await exp.build_etree(nodes)
    await exp.write_xml(path)
    fresh = Server()
    await fresh.init()
    await M.load_companions(fresh)
    await fresh.import_xml(path)
    ns = await fresh.get_namespace_index(M.NS_URI)
    if ns != m.ns:
        return [f"NODESET namespace index {ns}, not {m.ns}"], len(nodes)
    again = [fresh.get_node(n.nodeid) for n in nodes]
    a, b = await signature(server, nodes), await signature(fresh, again)
    diff = [k for k in a if a[k] != b.get(k)]
    return [f"NODESET {k}: {a[k]} came back as {b.get(k)}" for k in diff[:5]], len(nodes)


# ------------------------------------------------------------- client-side proofs
async def client_cert(name, trusted):
    d = S.PKI / "clients" / name
    d.mkdir(parents=True, exist_ok=True)
    (S.PKI / "trusted").mkdir(parents=True, exist_ok=True)
    key, cert = d / "key.pem", d / "cert.der"
    uri = f"urn:stf-hw:opcua:client:{name}"
    await setup_self_signed_certificate(key, cert, uri, "localhost", [ExtendedKeyUsageOID.CLIENT_AUTH],
                                        {"countryName": "DE", "organizationName": "STF check", "commonName": name})
    if trusted:
        shutil.copy(cert, S.PKI / "trusted" / f"{name}.der")
    return uri, key, cert


async def try_connect(url, cert=None, user=None, password=None, secure=True):
    c = Client(url, timeout=4)
    if secure:
        uri, key, crt = cert
        c.application_uri = uri
        await c.set_security_string(f"Basic256Sha256,SignAndEncrypt,{crt},{key}")
    if user:
        c.set_user(user)
        c.set_password(password)
    try:
        await c.connect()
    except Exception as e:                       # noqa: BLE001 - any refusal counts
        return None, type(e).__name__
    return c, None


async def check_security(url, good, bad, user, password):
    fails, notes = [], {}
    c = Client(url, timeout=4)
    eps = await c.connect_and_get_server_endpoints()
    pol = sorted({(e.SecurityPolicyUri.rsplit("#", 1)[-1], e.SecurityMode.name) for e in eps})
    notes["endpoints"] = pol
    if pol != [("Basic256Sha256", "SignAndEncrypt")]:
        fails.append(f"SECURITY endpoints offered: {pol}")
    tests = [("no security", dict(secure=False, user=user, password=password)),
             ("anonymous", dict(cert=good)),
             ("wrong password", dict(cert=good, user=user, password=password + "x")),
             ("untrusted certificate", dict(cert=bad, user=user, password=password))]
    for name, kw in tests:
        cl, err = await try_connect(url, **kw)
        notes[name] = err or "ACCEPTED"
        if cl is not None:
            fails.append(f"SECURITY a client with {name} was accepted")
            await cl.disconnect()
    cl, err = await try_connect(url, cert=good, user=user, password=password)
    if cl is None:
        fails.append(f"SECURITY the trusted operator was refused ({err})")
        return fails, notes, None
    try:
        n = cl.get_node(ua.NodeId("Production.Phase", 0 + (await cl.get_namespace_index(M.NS_URI))))
        await n.write_value(ua.Variant("hacked", ua.VariantType.String))
        fails.append("SECURITY a variable could be written")
        notes["write"] = "ACCEPTED"
    except ua.UaStatusCodeError as e:
        notes["write"] = type(e).__name__
    return fails, notes, cl


async def check_live(cl, sil, state_id):
    ns = await cl.get_namespace_index(M.NS_URI)
    phase = cl.get_node(ua.NodeId("Production.Phase", ns))
    crane_job = cl.get_node(ua.NodeId("HBW.Units.crane.Job", ns))
    seen = {"phase": [], "crane": []}

    class H:
        def datachange_notification(self, node, val, data):
            key = "phase" if node == phase else "crane"
            if not seen[key] or seen[key][-1] != val:
                seen[key].append(val)
    sub = await cl.create_subscription(50, H())
    await sub.subscribe_data_change([phase, crane_job])
    prod = cl.get_node(ua.NodeId("Production", ns))
    ok = await prod.call_method(ua.NodeId("Production.StartOrder", ns))
    t0 = time.time()
    while time.time() - t0 < 90:
        await asyncio.sleep(0.25)
        if seen["phase"] and seen["phase"][-1] == "complete" and "running" in seen["phase"]:
            break
    order = await cl.get_node(ua.NodeId("Production.OrderTime", ns)).read_value()
    jobs = await cl.get_node(ua.NodeId("Production.JobsCompleted", ns)).read_value()
    state = (await cl.get_node(state_id).read_value()).Text
    await sub.delete()
    fails = []
    if not ok:
        fails.append("LIVE StartOrder returned false")
    if not seen["phase"] or seen["phase"][-1] != "complete":
        fails.append(f"LIVE the order did not complete over OPC UA (phases seen {seen['phase']})")
    want_t = round(sil["done_at"] - sil["homed_at"], 2)
    if abs(order - want_t) > 0.15:
        fails.append(f"LIVE OrderTime {order} s, Upgrade 13's run says {want_t} s")
    if jobs != sil["jobs"]:
        fails.append(f"LIVE JobsCompleted {jobs}, Upgrade 13's run completed {sil['jobs']}")
    crane = [x for x in seen["crane"] if x]
    return fails, {"phases": seen["phase"], "crane_jobs": crane[:6], "order_s": order, "jobs": jobs,
                   "wall_s": round(time.time() - t0, 1), "state": state}


# ------------------------------------------------------------- the address space for the twin
async def tree(server, m):
    """The address space below the cell as JSON: name, node id, class, type, description, unit, signal."""
    sig = {n.nodeid: k for k, n in m.signals.items()}
    unit = {node.nodeid: (u, k) for u, d in m.units.items() for k, node in d.items()}

    async def walk(n, depth=0, seen=None):
        seen = seen if seen is not None else set()
        if n.nodeid in seen or depth > 8:
            return None
        seen.add(n.nodeid)
        cls = await n.read_node_class()
        e = {"name": (await n.read_browse_name()).Name, "id": n.nodeid.to_string(), "cls": cls.name}
        if cls in (ua.NodeClass.Object, ua.NodeClass.Variable):
            td = await n.read_type_definition()
            if td is not None:
                e["type"] = (await server.get_node(td).read_browse_name()).Name
        d = await n.read_description()
        if d and d.Text:
            e["desc"] = d.Text
        if n.nodeid in sig:
            e["signal"] = sig[n.nodeid]
        if n.nodeid in unit:
            e["unit"], e["field"] = unit[n.nodeid]
        if cls == ua.NodeClass.Variable and "signal" not in e and "unit" not in e:
            try:
                v = await n.read_value()
                if isinstance(v, list) and v and isinstance(v[0], ua.Argument):
                    v = ", ".join(f"{a.Name}: {a.Description.Text}" for a in v)
                e["value"] = v.Text if isinstance(v, ua.LocalizedText) else (
                    f"{v.Low:g} .. {v.High:g}" if isinstance(v, ua.Range) else (
                        v.DisplayName.Text if isinstance(v, ua.EUInformation) else str(v)))
            except Exception:                    # noqa: BLE001
                pass
        kids = []
        for c in await n.get_children(refs=ua.ObjectIds.HierarchicalReferences):
            k = await walk(c, depth + 1, seen)
            if k:
                kids.append(k)
        if kids:
            e["children"] = kids
        return e
    return await walk(m.cell)


# ------------------------------------------------------------- run
async def run(mutant=None):
    # asyncua logs every refused certificate with a traceback; refusals are what (5) tests
    for name in ("asyncua", "asyncuagds.validate"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    io_all = json.load(open(os.path.join(M.PUBLIC, "sil", "plc.json")))
    sil = json.load(open(os.path.join(M.PUBLIC, "sil", "sil.json")))
    user, password = "operator", secrets.token_urlsafe(18)
    url = f"opc.tcp://127.0.0.1:{PORT}/stf/"
    # the client certificates first: the server reads its trust list when it is made
    good = await client_cert("operator-pc", trusted=True)
    bad = await client_cert("unknown-pc", trusted=False)
    server, m = await S.make_server(user, password, url)
    if mutant:
        await mutant(server, m)
    feed = S.Feed(server, m, io_all["io"], io_all["units"])
    await S.add_method(server, m, feed)
    fails, out = [], {}
    nodes = await M.our_nodes(server, m)
    fails += await check_mapping(server, m, io_all["io"])
    fails += await check_types(server, nodes)
    fails += await check_machinery(server, m)
    os.makedirs(OUT, exist_ok=True)
    nf, n_nodes = await check_nodeset(server, m, os.path.join(OUT, "stf.NodeSet2.xml"))
    fails += nf
    out["nodes"] = n_nodes
    if mutant is None:
        out["tree"] = await tree(server, m)
    async with server:
        task = asyncio.create_task(feed.run(SPEED, 100))
        await asyncio.sleep(1.0)
        sf, notes, cl = await check_security(url, good, bad, user, password)
        fails += sf
        out["security"] = notes
        if cl is not None and mutant is None:
            cs = await m.item_state.get_child(["0:CurrentState"])
            lf, live = await check_live(cl, sil, cs.nodeid)
            fails += lf
            out["live"] = live
        if cl is not None:
            await cl.disconnect()
        feed.proc.kill()
        task.cancel()
    return fails, out


# mutants: each breaks the server one way; the checks must catch every one
async def _m_signal(server, m):
    n = m.signals.pop("hbw_I1")
    await n.delete()


async def _m_mandatory(server, m):
    n = await m.signals["oven_I10"].get_child(["0:TrueState"])
    await n.delete()


async def _m_uri(server, m):
    di = await server.get_namespace_index(M.DI_URI)
    ident = None
    for r in await m.cell.get_references(refs=ua.NodeId(ua.ObjectIds.HasAddIn)):
        node = server.get_node(r.NodeId)
        if (await node.read_browse_name()).Name == "Identification":
            ident = node
    await (await ident.get_child([f"{di}:ProductInstanceUri"])).write_value(ua.Variant("urn:somewhere-else", ua.VariantType.String))


async def _m_anonymous(server, m):
    server.set_identity_tokens([ua.AnonymousIdentityToken, ua.UserNameIdentityToken])
    server.iserver.user_manager = PermissiveUserManager()


MUTANTS = [("OM1", "a PLC signal without a node", _m_signal),
           ("OM2", "a mandatory child (TrueState) removed", _m_mandatory),
           ("OM3", "ProductInstanceUri not the AAS asset id", _m_uri),
           ("OM4", "anonymous access allowed", _m_anonymous)]


async def main():
    S.bundle_stream()
    io = json.load(open(os.path.join(M.PUBLIC, "sil", "plc.json")))
    t0 = time.time()
    fails, out = await run()
    muts = []
    for mid, what, fn in MUTANTS:
        f, _ = await run(fn)
        muts.append({"id": mid, "what": what, "caught": bool(f), "by": f[0] if f else None})
    fails += [f"mutant {x['id']} survived: {x['what']}" for x in muts if not x["caught"]]
    out.update({"mutants": muts, "fails": fails, "endpoint": "opc.tcp://127.0.0.1:4840/stf/", "namespace": M.NS_URI,
                "companions": ["DI 1.04.0", "IA 1.01.4", "Machinery 1.04.0"], "seconds": round(time.time() - t0, 1),
                "signals": sum(len(v) for k, v in io["io"].items() if k in ("ix", "qx", "iw", "id"))})
    with open(os.path.join(OUT, "opcua.json"), "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"{out['nodes']} nodes; security {out['security']}")
    if "live" in out:
        print(f"live: {out['live']}")
    for x in muts:
        print(f"  {x['id']} {x['what']}: {'caught - ' + x['by'][:100] if x['caught'] else 'SURVIVED'}")
    for f in fails:
        print("  FAIL", f)
    print("OPC UA OK" if not fails else f"OPC UA FAILED ({len(fails)})")
    return fails


if __name__ == "__main__":
    raise SystemExit(1 if asyncio.run(main()) else 0)
