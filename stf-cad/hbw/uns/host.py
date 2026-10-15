"""
Upgrade 14, step 3 - the primary host application, and the Unified Namespace it writes.

    python3 -m uns.host --port 8883           (from stf-cad/hbw; or `make uns`)

A Sparkplug host application (the SCADA/MES side) that knows nothing of the cell but what the
births tell it:
  - its MQTT CONNECT carries a STATE will (online=false, QoS 1, retained); after subscribing it
    publishes STATE online=true with the will's timestamp (host-topic-phid-birth-*);
  - it learns every metric's name, alias and datatype from the NBIRTH and DBIRTHs, and applies
    the data by alias;
  - it checks every message's seq: a gap, or data from a node it has no birth for, makes it ask
    for a Rebirth (NCMD 'Node Control/Rebirth' = true);
  - an NDEATH with the bdSeq of the node's current birth marks the node and its devices offline
    and every metric stale; an NDEATH with another bdSeq is an old session's and is ignored.

The Unified Namespace: every metric, as plain JSON, retained, under the ISA-95 path
    stf-hw/virtual-site/bakery/line-1/cell-u12/<device>/<metric>
        {"value": ..., "quality": "GOOD" | "STALE", "timestamp": ms, "unit": "mm", "sparkplug": "<topic>#<name>"}
plus .../cell-u12/_status {"online": bool, "bdSeq": n, "timestamp": ms}. A client that subscribes
late (a dashboard, an MES, an AI agent) gets the whole state from the retained messages alone.
"""
import argparse
import json
import os
import threading
import time

from uns import namespace as N
from uns import sparkplug as SP
from uns.broker import CACHE, PORT
from uns.client import connect, make


class Host:
    def __init__(self, port, ca, password, user="stf-scada", host_id=N.HOST_ID, group=N.GROUP, uns=True):
        self.port, self.ca, self.user, self.password = port, ca, user, password
        self.host_id, self.group, self.uns = host_id, group, uns
        self.nodes = {}                                 # edge node id -> its state as the births and data tell it
        self.lock = threading.RLock()
        self.client = None
        self.ts = None
        self.log = []                                   # what the host did and why, for the proofs
        self.rebirths = 0
        self.stopping = False

    # ---------------------------------------------------------------- the session
    def state(self, online):
        return json.dumps({"online": online, "timestamp": self.ts}).encode()

    def start(self):
        self.ts = SP.now_ms()
        c = make(f"stf-host-{self.host_id}", self.user, self.password, self.ca)
        c.will_set(N.state_topic(self.host_id), self.state(False), qos=1, retain=True)
        c.on_message = self.on_message

        def subscribed(cl):
            cl.subscribe([(f"{N.NAMESPACE}/{self.group}/#", 1), (N.state_topic(self.host_id), 1)])
            cl.publish(N.state_topic(self.host_id), self.state(True), qos=1, retain=True)
        self.client = c
        rc = connect(c, self.port, on_connect=subscribed)
        if rc != "Success":
            raise RuntimeError(f"host: connect refused ({rc})")
        return self

    def stop(self):
        """Clean shutdown: the STATE death first, then DISCONNECT (host-topic-phid-death-payload-disconnect-clean)."""
        if self.client:
            self.stopping = True                        # our own death STATE must not be answered with a birth
            self.client.publish(N.state_topic(self.host_id), self.state(False), qos=1, retain=True).wait_for_publish(3)
            self.client.disconnect()
            self.client.loop_stop()
            self.client = None

    # ---------------------------------------------------------------- commands
    def ncmd(self, edge, metrics):
        self.client.publish(N.topic("NCMD", edge=edge, group=self.group), SP.payload(metrics), qos=0, retain=False)

    def rebirth(self, edge, why):
        n = self.nodes.setdefault(edge, self._node())
        if n.get("rebirth_pending"):
            return
        n["rebirth_pending"] = True
        self.rebirths += 1
        self.log.append(("rebirth request", edge, why, time.time()))
        self.ncmd(edge, [(N.REBIRTH, None, N.BOOLEAN, True, None)])      # by name: the metric has no alias

    def start_order(self, edge=N.EDGE):
        n = self.nodes[edge]
        alias = n["alias_of"][(None, N.RESTART)]
        self.ncmd(edge, [(None, alias, N.BOOLEAN, True, None)])

    # ---------------------------------------------------------------- the data
    @staticmethod
    def _node():
        return {"online": False, "bdseq": None, "seq": None, "aliases": {}, "alias_of": {}, "metrics": {},
                "devices": {}, "births": 0, "deaths": 0, "stale_deaths": 0, "gaps": 0}

    def value(self, edge, device, name):
        return self.nodes[edge]["metrics"][(device, name)]["value"]

    def _uns_put(self, edge, device, name, rec):
        if not self.uns or name in (N.BDSEQ, N.REBIRTH, N.RESTART):
            return
        body = {"value": rec["value"], "quality": "STALE" if rec["stale"] else "GOOD", "timestamp": rec["ts"],
                "sparkplug": f"{N.topic('DDATA' if device else 'NDATA', device, group=self.group, edge=edge)}#{name}"}
        if rec.get("unit"):
            body["unit"] = rec["unit"]
        self.client.publish(N._uns(device, name), json.dumps(body), qos=1, retain=True)

    def _uns_status(self, edge, n):
        if self.uns:
            self.client.publish(f"{N.UNS_ROOT}/_status", json.dumps(
                {"online": n["online"], "bdSeq": n["bdseq"], "timestamp": SP.now_ms(),
                 "devices": {d: v for d, v in n["devices"].items()}}), qos=1, retain=True)

    def _apply(self, edge, n, device, p, birth):
        for m in p.metrics:
            if birth:
                key = (device, m.name)
                if m.HasField("alias"):
                    n["aliases"][m.alias] = key
                    n["alias_of"][key] = m.alias
                props = SP.props(m)
                n["metrics"][key] = {"value": SP.get_value(m), "dtype": m.datatype, "ts": m.timestamp or p.timestamp,
                                     "stale": False, "unit": props.get("engUnit")}
            else:
                key = n["aliases"].get(m.alias) if m.HasField("alias") else (device, m.name)
                if key not in n["metrics"]:
                    return False                        # an alias no birth declared
                n["metrics"][key].update(value=SP.get_value(m), ts=m.timestamp or p.timestamp, stale=False)
            self._uns_put(edge, key[0], key[1], n["metrics"][key])
        return True

    def _stale(self, edge, n, device=None):
        for (d, name), rec in n["metrics"].items():
            if device is None or d == device:
                rec["stale"] = True
                self._uns_put(edge, d, name, rec)

    def on_message(self, client, userdata, msg):
        parts = msg.topic.split("/")
        if parts[1] == "STATE":
            st = json.loads(msg.payload)
            if parts[2] == self.host_id and st.get("online") is False and self.client and not self.stopping:
                # someone (or our own will) says we are offline while we are not: say otherwise
                self.client.publish(N.state_topic(self.host_id), self.state(True), qos=1, retain=True)
            return
        if len(parts) < 4:
            return
        kind, edge, device = parts[2], parts[3], parts[4] if len(parts) > 4 else None
        try:
            p = SP.decode(msg.payload)
        except Exception:                               # noqa: BLE001
            self.log.append(("undecodable", msg.topic, "", time.time()))
            return
        with self.lock:
            n = self.nodes.setdefault(edge, self._node())
            if kind == "NDEATH":
                bd = next((SP.get_value(m) for m in p.metrics if m.name == N.BDSEQ), None)
                if n["bdseq"] is not None and bd == n["bdseq"] and n["online"]:
                    n["online"], n["deaths"] = False, n["deaths"] + 1
                    for d in n["devices"]:
                        n["devices"][d] = False
                    self._stale(edge, n)
                    self._uns_status(edge, n)
                    self.log.append(("node offline", edge, f"bdSeq {bd}", time.time()))
                else:
                    n["stale_deaths"] += 1
                    self.log.append(("stale NDEATH ignored", edge, f"bdSeq {bd}, current {n['bdseq']}", time.time()))
                return
            if kind in ("NCMD", "DCMD"):
                return
            if kind == "NBIRTH":
                bd = next((SP.get_value(m) for m in p.metrics if m.name == N.BDSEQ), None)
                n.update(self._node(), bdseq=bd, seq=p.seq, online=True, births=n["births"] + 1,
                         deaths=n["deaths"], stale_deaths=n["stale_deaths"], gaps=n["gaps"])
                self._apply(edge, n, None, p, birth=True)
                self._uns_status(edge, n)
                return
            if not n["online"]:
                self.rebirth(edge, f"{kind} from a node with no birth")
                return
            expect = (n["seq"] + 1) % 256
            if p.seq != expect:
                n["gaps"] += 1
                n["online"] = False                     # its data cannot be trusted until it is born again
                self.rebirth(edge, f"{kind} seq {p.seq}, expected {expect}")
                return
            n["seq"] = p.seq
            if kind == "DBIRTH":
                n["devices"][device] = True
                self._apply(edge, n, device, p, birth=True)
                self._uns_status(edge, n)
            elif kind == "DDEATH":
                n["devices"][device] = False
                self._stale(edge, n, device)
            elif kind in ("NDATA", "DDATA"):
                if (kind == "DDATA" and not n["devices"].get(device)) or not self._apply(edge, n, device, p, birth=False):
                    n["online"] = False
                    self.rebirth(edge, f"{kind} for a metric or device with no birth")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=PORT)
    a = ap.parse_args()
    password = os.environ.get("STF_UNS_SCADA_PASSWORD")
    if not password:
        raise SystemExit("set STF_UNS_SCADA_PASSWORD (make uns does)")
    h = Host(a.port, CACHE / "pki" / "ca.pem", password).start()
    print(f"primary host '{h.host_id}' online; the Unified Namespace is under {N.UNS_ROOT}/#", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        h.stop()


if __name__ == "__main__":
    main()
