"""
Upgrade 14, step 3 - the cell as a Sparkplug B edge node, live from the software-in-the-loop PLC.

    python3 -m uns.edge --port 8883 --speed 1      (from stf-cad/hbw; or `make uns`, which also
                                                     starts the broker and the primary host)

The values are Upgrade 13's: the compiled PLC program (plc.wasm) scanning the plant, streamed
by web/scripts/sil-stream.ts (sil/stream.py). What the edge node does, by the specification
(Eclipse Sparkplug 3.0; the IDs are its testable requirements, checked by uns/check.py):
  - every MQTT CONNECT carries an NDEATH will (QoS 1, not retained) with the next bdSeq, which
    starts at 0 and goes up by one per connection (topics-nbirth-bdseq-increment);
  - it waits for the primary host application's STATE online=true before its birth, and ends
    its session when that host goes offline (operational-behavior-edge-node-birth-sequence-wait,
    ...-primary-application-state-with-multiple-servers-walk);
  - the birth: NBIRTH with seq 0, every node metric with name, alias, datatype and value, the
    bdSeq of the will and 'Node Control/Rebirth' = false without an alias; then a DBIRTH per
    module, seq one higher each time;
  - data by exception: a DDATA or NDATA carries only the metrics that changed, by alias only,
    seq + 1 per message, 255 -> 0;
  - an NCMD 'Node Control/Rebirth' = true stops the data and sends the whole birth again with the
    same bdSeq; 'Node Control/Restart Order' = true restarts the simulated order;
  - a clean shutdown publishes the NDEATH before disconnecting.
"""
import argparse
import json
import os
import subprocess
import threading
import time
from pathlib import Path

from sil.stream import STREAM, command
from sil.stream import bundle as bundle_stream

from uns import namespace as N
from uns import sparkplug as SP
from uns.broker import CACHE, PORT
from uns.client import connect, make


class Edge:
    def __init__(self, port, ca, password, speed=1.0, emit_ms=100, bdseq_file=CACHE / "bdseq", user="stf-edge",
                 host_id=N.HOST_ID, edge_id=N.EDGE, wait_for_host=True):
        self.port, self.ca, self.user, self.password = port, ca, user, password
        self.host_id, self.edge_id, self.wait_for_host = host_id, edge_id, wait_for_host
        self.speed, self.emit_ms, self.bdseq_file = speed, emit_ms, Path(bdseq_file)
        self.ms = N.catalogue()
        self.devices = N.by_device(self.ms)
        self.restart_alias = next(m.alias for m in self.ms if m.name == N.RESTART)
        self.lock = threading.RLock()
        self.client = None
        self.seq, self.bd, self.born, self.last = 0, None, False, {}
        self.d, self.homed, self.run_id = None, None, 0
        self.state_ts, self.host_online = 0, False
        self.session_end = threading.Event()
        self.stop = threading.Event()
        self.proc = None
        self.log = []                                   # what the edge did, for the proofs

    # ---------------------------------------------------------------- values
    def values(self, d):
        """(device, name) -> value of every metric, from one stream line."""
        if d["run"] != self.run_id:
            self.run_id, self.homed = d["run"], None
        if d["phase"] >= 1 and self.homed is None:
            self.homed = d["t"]
        fault = any(u[0] == 910 for u in d["units"]) or bool(d["flags"])
        out = {}
        for m in self.ms:
            if m.name == N.BDSEQ:
                v = self.bd
            elif m.name == "Production/OrderTime":
                v = round(d["t"] - self.homed, 3) if self.homed is not None else 0.0
            elif m.name == "Production/State":
                v = "OutOfService" if fault else ("Executing" if d["phase"] == 1 else "NotExecuting")
            else:
                v = m.get(d)
            out[(m.device, m.name)] = v
        return out

    # ---------------------------------------------------------------- publishing
    def _seq(self):
        s = self.seq
        self.seq = (self.seq + 1) % 256
        return s

    def publish(self, kind, device, metrics, seq=True):
        raw = SP.payload(metrics, seq=self._seq() if seq else None)
        self.client.publish(N.topic(kind, device, edge=self.edge_id), raw, qos=0, retain=False)

    def birth_metrics(self, device, vals):
        return [(m.name, m.alias, m.dtype, vals[(device, m.name)], m.props or None) for m in self.devices[device]]

    def birth(self):
        """NBIRTH (seq 0) and a DBIRTH per module: every metric with its current value."""
        with self.lock:
            if self.d is None:
                return False
            vals = self.values(self.d)
            self.seq = 0
            self.publish("NBIRTH", None, self.birth_metrics(None, vals))
            for dev in N.DEVICES.values():
                self.publish("DBIRTH", dev, self.birth_metrics(dev, vals))
            self.last, self.born = vals, True
            self.log.append(("birth", self.bd, time.time()))
            return True

    def data(self, d):
        with self.lock:
            self.d = d
            if not self.born:
                if self.client is not None and (self.host_online or not self.wait_for_host):
                    self.birth()                        # the host came online before the first stream line
                return
            vals = self.values(d)
            for dev in (None, *N.DEVICES.values()):
                changed = [(None, m.alias, m.dtype, vals[(dev, m.name)], None) for m in self.devices[dev]
                           if vals[(dev, m.name)] != self.last.get((dev, m.name))]
                if changed:
                    self.publish("NDATA" if dev is None else "DDATA", dev, changed)
            self.last = vals

    # ---------------------------------------------------------------- the session
    def next_bdseq(self):
        try:
            v = (int(self.bdseq_file.read_text()) + 1) % 256
        except (OSError, ValueError):
            v = 0
        self.bdseq_file.parent.mkdir(parents=True, exist_ok=True)
        self.bdseq_file.write_text(str(v))
        return v

    def death_payload(self):
        return SP.payload([(N.BDSEQ, None, N.UINT64, self.bd, None)])

    def on_message(self, client, userdata, msg):
        if msg.topic == N.state_topic(self.host_id):
            try:
                st = json.loads(msg.payload)
                online, ts = st["online"], st["timestamp"]
            except (ValueError, KeyError, TypeError):
                return
            if not isinstance(online, bool) or ts < self.state_ts:      # an older STATE: ignore it
                return
            self.state_ts, self.host_online = ts, online
            if online and not self.born:
                self.birth()
            elif not online and self.born:
                self.log.append(("host offline", self.bd, time.time()))
                self.end_session()
            return
        try:
            p = SP.decode(msg.payload)
        except Exception:                               # noqa: BLE001 - not a Sparkplug payload
            return
        for m in p.metrics:
            if m.name == N.REBIRTH and SP.get_value(m) is True:
                with self.lock:
                    self.log.append(("rebirth requested", self.bd, time.time()))
                    self.birth()
            elif m.alias == self.restart_alias and SP.get_value(m) is True and self.proc:
                self.proc.stdin.write("restart\n")
                self.proc.stdin.flush()
                self.log.append(("restart order", self.bd, time.time()))

    def end_session(self):
        """Intentional disconnect: the NDEATH first (operational-behavior-edge-node-intentional-disconnect-ndeath)."""
        with self.lock:
            if self.client is None:
                return
            on_loop = threading.current_thread() is getattr(self.client, "_thread", None)
            if self.born:
                info = self.client.publish(N.topic("NDEATH", edge=self.edge_id), self.death_payload(), qos=1, retain=False)
                # on paho's own network thread (a STATE message) the NDEATH cannot be waited for -
                # that thread sends it; it is queued ahead of the DISCONNECT either way
                if not on_loop:
                    info.wait_for_publish(3)
            self.born = False
            c, self.client = self.client, None
        c.disconnect()
        if not on_loop:
            c.loop_stop()
        self.session_end.set()

    def session(self):
        self.bd = self.next_bdseq()
        c = make(f"stf-edge-{self.edge_id}", self.user, self.password, self.ca)
        c.will_set(N.topic("NDEATH", edge=self.edge_id), self.death_payload(), qos=1, retain=False)
        c.on_message = self.on_message

        def on_disconnect(client, userdata, flags, rc, props):
            # an ended session's client can report its disconnect after the next session began
            with self.lock:
                if self.client is not None and client is not self.client:
                    return
                self.born = False
            self.session_end.set()
        c.on_disconnect = on_disconnect
        self.session_end.clear()
        self.host_online = False

        def subscribe(cl):
            cl.subscribe([(N.topic("NCMD", edge=self.edge_id), 1), (N.topic("DCMD", "+", edge=self.edge_id), 1),
                          (N.state_topic(self.host_id), 1)])
        self.client = c
        rc = connect(c, self.port, on_connect=subscribe)
        if rc != "Success":
            self.client = None
            return rc
        self.log.append(("connect", self.bd, time.time()))
        if not self.wait_for_host:
            self.birth()
        self.session_end.wait()
        return "ended"

    def stream(self):
        self.proc = subprocess.Popen(command(self.speed, self.emit_ms), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     text=True, bufsize=1)
        for line in self.proc.stdout:
            if self.stop.is_set():
                break
            self.data(json.loads(line))

    def run(self):
        if not STREAM.exists():
            bundle_stream()
        threading.Thread(target=self.stream, daemon=True).start()
        while not self.stop.is_set():
            rc = self.session()
            if rc not in ("ended", "Success"):
                print(f"edge: connect refused ({rc})", flush=True)
            if not self.stop.is_set():
                time.sleep(0.5)

    def shutdown(self):
        self.stop.set()
        self.end_session()
        if self.proc:
            self.proc.kill()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--emit-ms", type=int, default=100)
    ap.add_argument("--bdseq-file", default=str(CACHE / "bdseq"), help="where the bdSeq survives restarts")
    ap.add_argument("--mutant", default=None, help=argparse.SUPPRESS)      # uns/check.py only
    a = ap.parse_args()
    password = os.environ.get("STF_UNS_EDGE_PASSWORD")
    if not password:
        raise SystemExit("set STF_UNS_EDGE_PASSWORD (make uns does)")
    cls = Edge
    if a.mutant:
        from uns import mutants
        cls = mutants.EDGES[a.mutant]
    e = cls(a.port, CACHE / "pki" / "ca.pem", password, speed=a.speed, emit_ms=a.emit_ms, bdseq_file=a.bdseq_file)
    try:
        e.run()
    except KeyboardInterrupt:
        e.shutdown()


if __name__ == "__main__":
    main()
