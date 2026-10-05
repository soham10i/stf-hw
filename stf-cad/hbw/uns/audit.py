"""
Upgrade 14, step 3 - the conformance monitor: what went over the wire, judged against the
Eclipse Sparkplug 3.0 specification's testable requirements (the `tck-id-...` IDs).

It is a passive MQTT 5 client subscribed to everything with QoS 2 and Retain-As-Published, so
it sees each message's QoS and retain flag as published. It shares no code with uns/edge.py or
uns/host.py: it reads the raw topics and payloads only (the payload schema aside).
"""
import json
import threading
import time
from collections import defaultdict

from paho.mqtt.subscribeoptions import SubscribeOptions

from uns import sparkplug as SP
from uns.client import connect, make

NODE_KINDS = {"NBIRTH", "NDATA", "NDEATH", "NCMD"}
DEVICE_KINDS = {"DBIRTH", "DDATA", "DDEATH", "DCMD"}
REBIRTH = "Node Control/Rebirth"


class Recorder:
    def __init__(self, port, ca, password, user="stf-auditor"):
        self.records, self.lock = [], threading.Lock()
        self.c = make("stf-auditor", user, password, ca, v5=True)
        self.c.on_message = self._on
        rc = connect(self.c, port, on_connect=lambda cl: cl.subscribe("#", options=SubscribeOptions(qos=2, retainAsPublished=True)))
        if rc != "Success":
            raise RuntimeError(f"auditor: connect refused ({rc})")
        time.sleep(0.3)

    def _on(self, client, userdata, msg):
        with self.lock:
            self.records.append({"t": time.time(), "topic": msg.topic, "qos": msg.qos, "retain": bool(msg.retain),
                                 "raw": bytes(msg.payload)})

    def stop(self):
        self.c.disconnect()
        self.c.loop_stop()
        return self.records


class Verdicts:
    """Requirement id -> how often it was checked and its first violation."""

    def __init__(self):
        self.n, self.fail = defaultdict(int), {}

    def check(self, tck, ok, detail=""):
        self.n[tck] += 1
        if not ok and tck not in self.fail:
            self.fail[tck] = detail

    def results(self):
        return [{"id": k, "checked": self.n[k], "ok": k not in self.fail, "first_violation": self.fail.get(k)}
                for k in sorted(self.n)]


def audit(records, namespace="spBv1.0"):
    v = Verdicts()
    stats = defaultdict(int)
    host_online = {}                                     # host id -> last STATE online flag
    state_ts = {}
    nodes = {}                                           # (group, edge) -> what the wire said so far
    pending_rebirth = {}

    def node(key):
        return nodes.setdefault(key, {"born": False, "seq": None, "bd": None, "dead_since_birth": True, "aliases": {},
                                      "names": set(), "devices": set(), "last": {}, "prev_bd": None})

    for r in records:
        parts = r["topic"].split("/")
        if parts[0] != namespace:
            continue
        stats["messages"] += 1
        # ---- STATE
        if parts[1] == "STATE":
            stats["STATE"] += 1
            try:
                st = json.loads(r["raw"])
                ok = isinstance(st, dict) and isinstance(st.get("online"), bool) and isinstance(st.get("timestamp"), int | float)
            except ValueError:
                st, ok = {}, False
            v.check("host-topic-phid-birth-payload" if st.get("online") else "host-topic-phid-death-payload", ok, r["topic"])
            v.check("host-topic-phid-birth-qos" if st.get("online") else "host-topic-phid-death-qos", r["qos"] == 1, f"QoS {r['qos']}")
            v.check("host-topic-phid-birth-retain" if st.get("online") else "host-topic-phid-death-retain", r["retain"], "not retained")
            hid = parts[2]
            if st.get("online") is False and hid in state_ts:
                v.check("host-topic-phid-birth-payload-timestamp", st.get("timestamp") == state_ts[hid],
                        f"death timestamp {st.get('timestamp')} != birth {state_ts[hid]}")
            if st.get("online"):
                state_ts[hid] = st.get("timestamp")
            host_online[hid] = st.get("online")
            if st.get("online") is False:
                for n in nodes.values():
                    if n["born"]:
                        n["walk"] = r["t"]
            continue
        kind = parts[2] if len(parts) > 2 else ""
        stats[kind] += 1
        # ---- topics
        dev_ok = (len(parts) == 5) if kind in DEVICE_KINDS else (len(parts) == 4)
        v.check("topic-structure-namespace-device-id-associated-message-types" if kind in DEVICE_KINDS
                else "topic-structure-namespace-device-id-non-associated-message-types", dev_ok, r["topic"])
        if kind not in NODE_KINDS | DEVICE_KINDS:
            v.check("topic-structure", False, r["topic"])
            continue
        key, device = (parts[1], parts[3]), (parts[4] if len(parts) > 4 else None)
        n = node(key)
        # ---- payload
        try:
            p = SP.decode(r["raw"])
            v.check("message-flow-edge-node-birth-publish-nbirth-payload" if kind == "NBIRTH" else "stf-payload-decodes", True)
        except Exception as e:                          # noqa: BLE001
            v.check("stf-payload-decodes", False, f"{r['topic']}: {e}")
            continue
        if kind in ("NCMD", "DCMD"):
            v.check("topics-ncmd-timestamp" if kind == "NCMD" else "topics-dcmd-timestamp", p.HasField("timestamp"), r["topic"])
            for m in p.metrics:
                if m.name == REBIRTH:
                    v.check("operational-behavior-data-commands-ncmd-rebirth-verb", kind == "NCMD", r["topic"])
                    v.check("operational-behavior-data-commands-ncmd-rebirth-value", SP.get_value(m) is True, "rebirth not true")
                    pending_rebirth[key] = r["t"]
            continue
        if kind == "NDEATH":
            v.check("message-flow-edge-node-birth-publish-will-message-qos", r["qos"] == 1, f"NDEATH QoS {r['qos']}")
            v.check("message-flow-edge-node-birth-publish-will-message-will-retained", not r["retain"], "NDEATH retained")
            v.check("topics-ndeath-seq", not p.HasField("seq"), "NDEATH has a seq")
            only = len(p.metrics) == 1 and p.metrics[0].name == "bdSeq"
            v.check("topics-ndeath-payload", only, f"{[m.name for m in p.metrics]}")
            bd = SP.get_value(p.metrics[0]) if only else None
            if n.get("walk") is not None:
                v.check("operational-behavior-primary-application-state-with-multiple-servers-walk",
                        r["t"] - n["walk"] < 2.0, f"NDEATH {r['t'] - n['walk']:.2f} s after the host went offline")
                n["walk"] = None
            if n["bd"] is not None and not n["dead_since_birth"]:
                v.check("topics-nbirth-bdseq-matching", bd == n["bd"], f"NDEATH bdSeq {bd}, NBIRTH bdSeq {n['bd']}")
            n.update(born=False, dead_since_birth=True, devices=set(), prev_bd=n["bd"] if not n["dead_since_birth"] else n["prev_bd"])
            continue
        # ---- every message from the edge node but NDEATH
        v.check({"NBIRTH": "topics-nbirth-mqtt", "DBIRTH": "topics-dbirth-mqtt", "DDATA": "topics-ddata-mqtt",
                 "NDATA": "topics-ndata-mqtt", "DDEATH": "topics-ddeath-mqtt"}[kind],
                r["qos"] == 0 and not r["retain"], f"{kind} QoS {r['qos']} retain {r['retain']}")
        v.check("payloads-sequence-num-always-included", p.HasField("seq"), f"{kind} without seq")
        v.check({"NBIRTH": "topics-nbirth-timestamp", "DBIRTH": "topics-dbirth-timestamp", "DDATA": "topics-ddata-timestamp",
                 "NDATA": "topics-ndata-timestamp", "DDEATH": "stf-ddeath-timestamp"}[kind], p.HasField("timestamp"), kind)
        if kind in ("NBIRTH", "DBIRTH", "NDATA", "DDATA"):
            v.check("payloads-name-birth-data-requirement", all(m.HasField("timestamp") for m in p.metrics),
                    f"{kind}: a metric without a timestamp")
        if kind == "NBIRTH":
            hid_online = [h for h, o in host_online.items() if o]
            v.check("operational-behavior-edge-node-birth-sequence-wait", bool(hid_online), "NBIRTH while no host is online")
            v.check("topics-nbirth-seq-num", p.seq == 0, f"NBIRTH seq {p.seq}")
            names = [m.name for m in p.metrics]
            bdm = [m for m in p.metrics if m.name == "bdSeq"]
            v.check("topics-nbirth-bdseq-included", len(bdm) == 1, "no bdSeq")
            bd = SP.get_value(bdm[0]) if bdm else None
            reb = [m for m in p.metrics if m.name == REBIRTH]
            v.check("topics-nbirth-rebirth-metric", len(reb) == 1 and reb[0].datatype == 11 and SP.get_value(reb[0]) is False,
                    "Node Control/Rebirth missing, not boolean or not false")
            v.check("operational-behavior-data-commands-rebirth-name-aliases", all(not m.HasField("alias") for m in reb),
                    "Node Control/Rebirth has an alias")
            if key in pending_rebirth:
                v.check("operational-behavior-data-commands-rebirth-action-2", r["t"] - pending_rebirth.pop(key) < 3.0,
                        "late birth after a rebirth request")
                v.check("operational-behavior-data-commands-rebirth-action-3", n["dead_since_birth"] or bd == n["bd"],
                        f"rebirth bdSeq {bd}, session bdSeq {n['bd']}")
            if n["dead_since_birth"] and n["prev_bd"] is not None:
                v.check("topics-nbirth-bdseq-increment", bd == (n["prev_bd"] + 1) % 256,
                        f"bdSeq {bd} after {n['prev_bd']}")
            n.update(born=True, seq=0, bd=bd, dead_since_birth=False, aliases={}, devices=set(), last={})
            _birth(v, n, p, None, kind)
            stats["names"] = len(names)
            continue
        # ---- after the NBIRTH: seq continuity
        if n.get("walk") is not None and r["t"] - n["walk"] > 0.5:
            v.check("operational-behavior-primary-application-state-with-multiple-servers-walk", False,
                    f"{kind} {r['t'] - n['walk']:.2f} s after the host went offline")
        if key in pending_rebirth:
            v.check("operational-behavior-data-commands-rebirth-action-1", r["t"] - pending_rebirth[key] < 0.5,
                    f"{kind} {r['t'] - pending_rebirth[key]:.2f} s after a rebirth request")
        if not n["born"]:
            v.check("message-flow-device-birth-publish-nbirth-wait" if kind == "DBIRTH" else "stf-data-after-birth",
                    False, f"{kind} without a current NBIRTH")
            continue
        expect = (n["seq"] + 1) % 256
        v.check("payloads-sequence-num-incrementing", p.seq == expect, f"{kind} seq {p.seq}, expected {expect}")
        if p.seq == 0 and n["seq"] == 255:
            stats["seq_wraps"] += 1
        n["seq"] = p.seq
        if kind == "DBIRTH":
            v.check("message-flow-device-birth-publish-nbirth-wait", True)
            n["devices"].add(device)
            _birth(v, n, p, device, kind)
        elif kind in ("NDATA", "DDATA"):
            if kind == "DDATA":
                v.check("stf-ddata-device-born", device in n["devices"], f"DDATA for unborn {device}")
            v.check("payloads-alias-data-cmd-requirement", all(m.HasField("alias") and not m.HasField("name") for m in p.metrics),
                    f"{kind} with names: {[m.name for m in p.metrics if m.HasField('name')][:3]}")
            for m in p.metrics:
                v.check("topics-nbirth-metric-reqs" if kind == "NDATA" else "topics-dbirth-metric-reqs",
                        m.alias in n["aliases"], f"alias {m.alias} in no birth")
                val = SP.get_value(m)
                v.check("topics-ddata-payload" if kind == "DDATA" else "operational-behavior-data-publish-nbirth-change",
                        n["last"].get(m.alias, object()) != val, f"{kind} alias {m.alias} repeats its value {val!r}")
                n["last"][m.alias] = val
        stats["metrics_data"] += len(p.metrics) if kind in ("NDATA", "DDATA") else 0
    for key, n in nodes.items():
        if n.get("walk") is not None:
            v.check("operational-behavior-primary-application-state-with-multiple-servers-walk", False,
                    f"{key[1]} never ended its session after the host went offline")
    return v, dict(stats)


def _birth(v, n, p, device, kind):
    for m in p.metrics:
        has = m.HasField("name") and m.HasField("datatype") and (m.WhichOneof("value") is not None or m.is_null)
        v.check("topics-nbirth-metrics" if kind == "NBIRTH" else "topics-dbirth-metrics", has, f"{kind} metric {m.name!r}")
        if m.name == REBIRTH:
            continue
        v.check("payloads-alias-birth-requirement", m.HasField("name") and m.HasField("alias"), f"{kind} {m.name} has no alias")
        if m.HasField("alias"):
            v.check("payloads-alias-uniqueness", m.alias not in n["aliases"], f"alias {m.alias} used twice")
            n["aliases"][m.alias] = (device, m.name)
            n["last"][m.alias] = SP.get_value(m)
