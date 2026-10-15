"""
Upgrade 14, step 3 - proofs of the Sparkplug B edge node, the primary host and the Unified Namespace.

    python3 -m uns.check            (from stf-cad/hbw; about two minutes; or `make uns-check`)

A real Mosquitto broker is started on a test port with fresh passwords; the edge node runs as
its own process (so it can be killed), the primary host and a conformance monitor
(uns/audit.py) connect to it, and the order is run end to end.
  (1) MAPPING      every signal of the compiled program's I/O image is exactly one metric of one
                   device, every unit sequencer six; aliases unique; only Rebirth has none.
  (2) SPECIFICATION every message on the wire is judged against the Eclipse Sparkplug 3.0
                   requirements it touches (tck-id-...): topics, QoS and retain, seq 0..255, bdSeq,
                   births before data, aliases, report by exception, STATE, rebirth, walk.
  (3) HOST WAIT    the edge, started first, publishes nothing until the host's STATE is online.
  (4) LIVE         the host starts the order with an NCMD and watches it complete; the order time
                   and jobs it reads equal Upgrade 13's proof run.
  (5) REBIRTH      a Rebirth request gets a full birth with the same bdSeq.
  (6) UNS          a client that subscribes late gets every metric's current value from the
                   retained Unified Namespace alone, equal to the host's.
  (7) DEATH        the host goes offline: the edge ends its session with an NDEATH; the edge is
                   killed (SIGKILL): the broker publishes its will, the host marks it offline and
                   every metric stale, the UNS says so; both come back with bdSeq + 1.
  (8) SECURITY     TLS 1.3 only; no anonymous, wrong password, plain-text or untrusted-server
                   connection; each role reads and writes only what its access list grants.
  (9) MUTANTS      five edge nodes that each break one rule and two insecure brokers: each caught.
Output: web/public/uns/uns.json (the namespace, the verdicts, samples of the traffic).
"""
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time

import paho.mqtt.client as mqtt
from sil.stream import PUBLIC, bundle

from uns import namespace as N
from uns import sparkplug as SP
from uns.audit import Recorder, audit
from uns.broker import CACHE, ROLES, Broker, _pki
from uns.client import connect, make
from uns.host import Host
from uns.mutants import EDGES

PORT = 18883
SPEED = 40
OUT = PUBLIC / "uns"
HERE = os.path.dirname(os.path.abspath(__file__))
DT = {2: "Int16", 7: "UInt32", 8: "UInt64", 9: "Float", 10: "Double", 11: "Boolean", 12: "String"}


def wait(cond, timeout, step=0.1):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(step)
    return False


def online(h):
    return h.nodes.get(N.EDGE, {}).get("online", False)


# ------------------------------------------------------------------ (1) mapping
def check_mapping():
    fails = []
    ms = N.catalogue()
    io = json.load(open(PUBLIC / "sil" / "plc.json"))
    names = {(m.device, m.name) for m in ms}
    if len(names) != len(ms):
        fails.append("MAPPING two metrics share a device and name")
    want = sum(len(io["io"][a]) for a in ("ix", "qx", "iw", "id"))
    signal_metrics = [m for m in ms if m.props.get("address")]
    if len(signal_metrics) != want or len({m.props["address"] for m in signal_metrics}) != want:
        fails.append(f"MAPPING {len(signal_metrics)} signal metrics for {want} PLC signals")
    units = [m for m in ms if m.name.startswith("Units/")]
    if len(units) != 6 * len(io["units"]):
        fails.append(f"MAPPING {len(units)} unit metrics for {len(io['units'])} units")
    aliases = [m.alias for m in ms if m.alias is not None]
    if len(aliases) != len(set(aliases)) or [m.name for m in ms if m.alias is None] != [N.REBIRTH]:
        fails.append("MAPPING aliases not unique, or a metric other than Rebirth without one")
    uns = [m.uns for m in ms if m.uns]
    if len(uns) != len(set(uns)):
        fails.append("MAPPING two metrics share a UNS topic")
    return fails, ms


# ------------------------------------------------------------------ (8) security
def other_ca():
    d = CACHE / "other-ca"
    if d.exists():
        import shutil
        shutil.rmtree(d)
    ca, _, _ = _pki(d)
    return ca


def security(b, rec):
    """Connections that must be refused, and publishes and reads the access list must stop."""
    notes, fails = {}, []
    pw = b.passwords

    def try_conn(user, password, tls=True, ca=None):
        c = make(f"probe-{secrets.token_hex(3)}", user, password, ca or b.ca) if tls else \
            mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="probe-plain", protocol=mqtt.MQTTv311)
        if not tls and user:
            c.username_pw_set(user, password)
        rc = connect(c, b.port, timeout=3)
        if rc == "Success":
            c.disconnect()
            c.loop_stop()
        return rc
    for name, kw in (("anonymous", dict(user=None, password=None)),
                     ("wrong password", dict(user="stf-viewer", password=pw["stf-viewer"] + "x")),
                     ("plain text (no TLS)", dict(user="stf-viewer", password=pw["stf-viewer"], tls=False)),
                     ("server not signed by the cell's CA", dict(user="stf-viewer", password=pw["stf-viewer"], ca=other_ca()))):
        rc = try_conn(**kw)
        notes[name] = rc
        if rc == "Success":
            fails.append(f"SECURITY a connection with {name} was accepted")
    # writes the access list must stop: each carries a marker the auditor must never see
    probes = [("stf-viewer", N.topic("NCMD"), "the viewer commands the cell"),
              ("stf-edge", N.topic("NCMD"), "the edge forges a command to itself"),
              ("stf-edge", N.topic("NBIRTH", edge="Cell-X"), "the edge impersonates another edge node"),
              ("stf-edge", f"{N.UNS_ROOT}/hbw/inputs/i1", "the edge writes the Unified Namespace"),
              ("stf-scada", N.topic("NBIRTH"), "the host impersonates the edge node"),
              ("stf-viewer", f"{N.UNS_ROOT}/hbw/inputs/i1", "the viewer writes the Unified Namespace")]
    marks = {}
    for user, topic, what in probes:
        c = make(f"probe-{user}", user, pw[user], b.ca)
        if connect(c, b.port) != "Success":
            fails.append(f"SECURITY {user} could not connect for the write probe")
            continue
        mark = f"STF-ACL-PROBE-{secrets.token_hex(4)}".encode()
        marks[mark] = what
        c.publish(topic, mark, qos=1).wait_for_publish(3)
        c.disconnect()
        c.loop_stop()
    # reads: the viewer subscribes to the Sparkplug namespace and must get nothing
    got = []
    c = make("probe-viewer-read", "stf-viewer", pw["stf-viewer"], b.ca)
    c.on_message = lambda cl, ud, msg: got.append(msg.topic)
    connect(c, b.port, on_connect=lambda cl: cl.subscribe([(f"{N.NAMESPACE}/#", 0)]))
    time.sleep(1.5)
    c.disconnect()
    c.loop_stop()
    seen = {r["raw"] for r in rec.records}
    leaked = [marks[m] for m in marks if m in seen]
    notes["write probes"] = {what: ("DELIVERED" if what in leaked else "dropped by the access list") for what in marks.values()}
    notes["viewer reads Sparkplug"] = f"{len(got)} messages"
    for what in leaked:
        fails.append(f"SECURITY {what}: the broker delivered it")
    if got:
        fails.append(f"SECURITY the viewer read {len(got)} Sparkplug messages")
    return fails, notes


# ------------------------------------------------------------------ (6) the Unified Namespace
def uns_snapshot(b, user="stf-viewer"):
    got = {}
    c = make("uns-late-subscriber", user, b.passwords[user], b.ca)
    c.on_message = lambda cl, ud, msg: got.__setitem__(msg.topic, json.loads(msg.payload))
    connect(c, b.port, on_connect=lambda cl: cl.subscribe([(f"{N.UNS_ROOT}/#", 1)]))
    time.sleep(1.5)
    c.disconnect()
    c.loop_stop()
    return got


def check_uns(host, snap, ms):
    fails = []
    n = host.nodes[N.EDGE]
    want = [m for m in ms if m.uns]
    for m in want:
        rec = n["metrics"].get((m.device, m.name))
        got = snap.get(m.uns)
        if got is None:
            fails.append(f"UNS {m.uns}: no retained message")
        elif rec is not None and got["value"] != rec["value"]:
            fails.append(f"UNS {m.uns}: {got['value']!r}, the host has {rec['value']!r}")
    return fails, {"topics": len([t for t in snap if not t.endswith("_status")]), "metrics": len(want),
                   "status": snap.get(f"{N.UNS_ROOT}/_status"),
                   "example": {k: snap[k] for k in (f"{N.UNS_ROOT}/hbw/encoders/crane/travel",
                                                    f"{N.UNS_ROOT}/node/production/phase") if k in snap}}


# ------------------------------------------------------------------ the run
def edge_process(b, bdseq):
    env = dict(os.environ, STF_UNS_EDGE_PASSWORD=b.passwords["stf-edge"], PYTHONPATH=os.path.dirname(HERE))
    return subprocess.Popen([sys.executable, "-m", "uns.edge", "--port", str(b.port), "--speed", str(SPEED),
                             "--bdseq-file", str(bdseq)], cwd=os.path.dirname(HERE), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def main_run():
    fails, out, timeline = [], {}, []
    t0 = time.time()

    def mark(what):
        timeline.append([round(time.time() - t0, 2), what])
    sil = json.load(open(PUBLIC / "sil" / "sil.json"))
    bdseq = CACHE / "check-bdseq"
    bdseq.unlink(missing_ok=True)
    with Broker(port=PORT, workdir=CACHE / "check") as b:
        rec = Recorder(b.port, b.ca, b.passwords["stf-auditor"])
        edge = edge_process(b, bdseq)
        mark("edge node started, before any host")
        time.sleep(2.0)
        early = [r for r in rec.records if "/NBIRTH/" in r["topic"]]
        out["host_wait"] = {"nbirth_before_host": len(early)}
        if early:
            fails.append("HOST WAIT the edge was born before the primary host was online")
        host = Host(b.port, b.ca, b.passwords["stf-scada"]).start()
        mark("primary host online (STATE)")
        if not wait(lambda: online(host) and len(host.nodes[N.EDGE]["devices"]) == 4, 10):
            fails.append("LIVE the edge node was not born after the host came online")
            raise SystemExit(fails)
        mark("edge born: NBIRTH + 4 DBIRTH")
        host.start_order()
        mark("host: NCMD 'Node Control/Restart Order'")
        sec_fails, out["security"] = security(b, rec)
        fails += sec_fails
        mark("security probes")
        done = wait(lambda: host.value(N.EDGE, None, "Production/Phase") == "complete"
                    and host.value(N.EDGE, None, "Production/OrderTime") > 0, 60, 0.25)
        order, jobs = host.value(N.EDGE, None, "Production/OrderTime"), host.value(N.EDGE, None, "Production/JobsCompleted")
        mark(f"order complete: {order:.2f} s, {jobs} jobs")
        want_t = round(sil["done_at"] - sil["homed_at"], 2)
        out["live"] = {"order_s": order, "jobs": jobs, "u13_order_s": want_t, "u13_jobs": sil["jobs"],
                       "state": host.value(N.EDGE, None, "Production/State")}
        if not done or abs(order - want_t) > 0.15 or jobs != sil["jobs"]:
            fails.append(f"LIVE order {order} s / {jobs} jobs, Upgrade 13 says {want_t} s / {sil['jobs']}")
        births = host.nodes[N.EDGE]["births"]
        host.rebirth(N.EDGE, "requested by the check")
        mark("host: NCMD 'Node Control/Rebirth'")
        ok = wait(lambda: host.nodes[N.EDGE]["births"] == births + 1 and online(host), 5)
        out["rebirth"] = {"born_again": ok, "bdSeq": host.nodes[N.EDGE]["bdseq"]}
        if not ok:
            fails.append("REBIRTH no new birth after the request")
        time.sleep(0.5)
        snap = uns_snapshot(b)
        uf, out["uns"] = check_uns(host, snap, N.catalogue())
        fails += uf
        mark(f"late subscriber: {out['uns']['topics']} retained UNS topics")
        # (7) the host goes offline, comes back
        bd0 = host.nodes[N.EDGE]["bdseq"]
        host.stop()
        mark("primary host offline (clean STATE death)")
        time.sleep(2.0)
        host = Host(b.port, b.ca, b.passwords["stf-scada"]).start()
        mark("primary host online again")
        ok = wait(lambda: online(host), 8)
        bd1 = host.nodes.get(N.EDGE, {}).get("bdseq")
        mark(f"edge born again, bdSeq {bd0} -> {bd1}")
        if not ok or bd1 != (bd0 + 1) % 256:
            fails.append(f"DEATH after the host returned: born {ok}, bdSeq {bd0} -> {bd1}")
        # the edge dies without a word
        edge.send_signal(signal.SIGKILL)
        edge.wait()
        mark("edge node killed (SIGKILL)")
        ok = wait(lambda: not online(host), 30)
        n = host.nodes[N.EDGE]
        stale = all(r["stale"] for r in n["metrics"].values())
        status = uns_snapshot(b).get(f"{N.UNS_ROOT}/_status", {})
        mark(f"broker published the will: host marks the node offline, {len(n['metrics'])} metrics stale")
        out["death"] = {"offline": ok, "stale": stale, "uns_status": status, "host_log": [x[:3] for x in host.log[-3:]]}
        if not ok or not stale or status.get("online") is not False:
            fails.append(f"DEATH after SIGKILL: offline {ok}, stale {stale}, UNS status {status}")
        edge = edge_process(b, bdseq)
        ok = wait(lambda: online(host), 10)
        bd2 = host.nodes[N.EDGE]["bdseq"]
        mark(f"edge restarted, born with bdSeq {bd2}")
        if not ok or bd2 != (bd1 + 1) % 256:
            fails.append(f"DEATH after restart: born {ok}, bdSeq {bd1} -> {bd2}")
        edge.send_signal(signal.SIGINT)                  # a clean shutdown: NDEATH, then DISCONNECT
        edge.wait(10)
        mark("edge stopped cleanly (NDEATH)")
        time.sleep(0.5)
        host.stop()
        records = rec.stop()
    verdicts, stats = audit(records)
    out["tck"] = verdicts.results()
    out["traffic"] = stats
    fails += [f"SPEC {k['id']}: {k['first_violation']}" for k in out["tck"] if not k["ok"]]
    out["samples"] = samples(records)
    out["timeline"] = timeline
    return fails, out


def samples(records):
    """One of each message, decoded, for the twin's panel."""
    out = {}
    for r in records:
        parts = r["topic"].split("/")
        kind = parts[2] if parts[0] == N.NAMESPACE and len(parts) > 2 else ("STATE" if "/STATE/" in r["topic"] else None)
        if parts[1:2] == ["STATE"]:
            kind = "STATE online" if json.loads(r["raw"]).get("online") else "STATE offline"
        if kind is None or kind in out or "PROBE" in str(r["raw"][:20]):
            continue
        if kind.startswith("STATE"):
            out[kind] = {"topic": r["topic"], "qos": r["qos"], "retain": r["retain"], "json": json.loads(r["raw"])}
            continue
        p = SP.decode(r["raw"])
        ms = [{k: v for k, v in (("name", m.name if m.HasField("name") else None), ("alias", m.alias if m.HasField("alias") else None),
                                 ("datatype", DT.get(m.datatype, m.datatype)), ("value", SP.get_value(m)),
                                 ("properties", SP.props(m) or None)) if v is not None} for m in p.metrics]
        out[kind] = {"topic": r["topic"], "qos": r["qos"], "retain": r["retain"], "bytes": len(r["raw"]),
                     "timestamp": p.timestamp, "seq": p.seq if p.HasField("seq") else None,
                     "metrics": ms[:8], "metric_count": len(ms)}
    return out


# ------------------------------------------------------------------ (9) mutants
def mutant_edge(mid):
    fails = []
    bdseq = CACHE / f"mutant-{mid}-bdseq"
    bdseq.unlink(missing_ok=True)
    with Broker(port=PORT + 1, workdir=CACHE / f"mutant-{mid}") as b:
        rec = Recorder(b.port, b.ca, b.passwords["stf-auditor"])
        e = EDGES[mid](b.port, b.ca, b.passwords["stf-edge"], speed=SPEED, bdseq_file=bdseq)
        threading.Thread(target=e.run, daemon=True).start()
        time.sleep(1.5)
        h = Host(b.port, b.ca, b.passwords["stf-scada"]).start()
        wait(lambda: online(h), 5)
        if online(h):
            h.start_order()
        time.sleep(4)
        e.shutdown()
        time.sleep(0.5)
        h.stop()
        records = rec.stop()
    v, _ = audit(records)
    fails += [f"SPEC {k['id']}: {k['first_violation']}" for k in v.results() if not k["ok"]]
    fails += [f"HOST {x[0]}: {x[2]}" for x in h.log if x[0] == "rebirth request"]
    return fails


def mutant_broker(mid):
    kw = {"SM1": dict(allow_anonymous=True),
          "SM2": dict(extra_acl=f"\nuser stf-edge\ntopic write {N.NAMESPACE}/{N.GROUP}/NCMD/#\n")}[mid]
    with Broker(port=PORT + 2, workdir=CACHE / f"mutant-{mid}", **kw) as b:
        rec = Recorder(b.port, b.ca, b.passwords["stf-auditor"])
        f, _ = security(b, rec)
        rec.stop()
    return f


MUTANTS = [("EM1", "DDATA carries the metric names", lambda: mutant_edge("EM1")),
           ("EM2", "a sequence number is skipped", lambda: mutant_edge("EM2")),
           ("EM3", "the NBIRTH's bdSeq is not the will's", lambda: mutant_edge("EM3")),
           ("EM4", "births without the primary host's STATE", lambda: mutant_edge("EM4")),
           ("EM5", "a DDATA repeats an unchanged value", lambda: mutant_edge("EM5")),
           ("SM1", "the broker accepts anonymous clients", lambda: mutant_broker("SM1")),
           ("SM2", "the access list lets the edge send commands", lambda: mutant_broker("SM2"))]


def namespace_json(ms):
    devices = {}
    for m in ms:
        devices.setdefault(m.device or "(node)", []).append(
            {"name": m.name, "alias": m.alias, "datatype": DT[m.dtype], "uns": m.uns,
             **({"properties": m.props} if m.props else {})})
    return {"group": N.GROUP, "edge": N.EDGE, "host": N.HOST_ID, "uns_root": N.UNS_ROOT,
            "topics": {"node": N.topic("{NBIRTH|NDATA|NDEATH|NCMD}"), "device": N.topic("{DBIRTH|DDATA|DDEATH|DCMD}", "{device}"),
                       "state": N.state_topic()}, "devices": devices}


def main():
    logging_quiet()
    bundle()
    t0 = time.time()
    fails, ms = check_mapping()
    f, out = main_run()
    fails += f
    muts = []
    for mid, what, fn in MUTANTS:
        mf = fn()
        muts.append({"id": mid, "what": what, "caught": bool(mf), "by": mf[0] if mf else None})
    fails += [f"mutant {m['id']} survived: {m['what']}" for m in muts if not m["caught"]]
    tck = json.load(open(os.path.join(HERE, "sparkplug", "tck.json")))
    for k in out["tck"]:
        k["text"] = tck.get(k["id"], "")
    out.update({"namespace": namespace_json(ms), "mutants": muts, "fails": fails, "seconds": round(time.time() - t0, 1),
                "broker": {"server": "Eclipse Mosquitto", "tls": "TLS 1.3, ECDSA P-256 certificate from the cell's CA",
                           "roles": list(ROLES)},
                "spec": "Eclipse Sparkplug 3.0.0 (ISO/IEC 20237:2023)"})
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "uns.json", "w") as fh:
        json.dump(out, fh, separators=(",", ":"), default=str)
    ok = sum(k["ok"] for k in out["tck"])
    print(f"{len(ms)} metrics; {ok}/{len(out['tck'])} Sparkplug requirements hold over "
          f"{out['traffic'].get('messages', 0)} messages ({out['traffic'].get('seq_wraps', 0)} seq wraps)")
    print(f"live: {out['live']}")
    print(f"uns: {out['uns']['topics']} retained topics; security: {out['security']}")
    for t, what in out["timeline"]:
        print(f"  {t:7.2f} s  {what}")
    for m in muts:
        print(f"  {m['id']} {m['what']}: {'caught - ' + m['by'][:110] if m['caught'] else 'SURVIVED'}")
    for f in fails:
        print("  FAIL", f)
    print("SPARKPLUG/UNS OK" if not fails else f"SPARKPLUG/UNS FAILED ({len(fails)})")
    return fails


def logging_quiet():
    import logging
    logging.getLogger("paho").setLevel(logging.CRITICAL)
    socket.setdefaulttimeout(None)


if __name__ == "__main__":
    raise SystemExit(1 if main() else 0)
