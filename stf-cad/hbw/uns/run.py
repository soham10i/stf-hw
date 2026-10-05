"""
Upgrade 14, step 3 - the whole stack on this machine: broker, primary host, edge node.

    python3 -m uns.run [--speed 1]          (from stf-cad/hbw; or `make uns`)

Mosquitto on 127.0.0.1:8883 (TLS 1.3, the cell's CA), the primary host writing the Unified
Namespace, and the edge node publishing the PLC program's live data. The passwords are made
once and kept in .cache/uns/secrets.json (readable by you only). Connect any MQTT client - MQTT
Explorer, mosquitto_sub - as stf-viewer to read the UNS, or as stf-auditor to see everything.
"""
import argparse
import json
import os
import secrets
import signal
import threading
import time

from sil.stream import bundle

from uns import namespace as N
from uns.broker import CACHE, PORT, ROLES, Broker
from uns.edge import Edge
from uns.host import Host

SECRETS = CACHE / "secrets.json"


def passwords():
    try:
        pw = json.loads(SECRETS.read_text())
        if set(pw) == set(ROLES):
            return pw
    except (OSError, ValueError):
        pass
    pw = {r: secrets.token_urlsafe(18) for r in ROLES}
    SECRETS.parent.mkdir(parents=True, exist_ok=True)
    SECRETS.write_text(json.dumps(pw, indent=1))
    os.chmod(SECRETS, 0o600)
    return pw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speed", type=float, default=1.0, help="machine time per real time")
    a = ap.parse_args()

    # Ctrl-C and a process manager's SIGTERM both end it cleanly (NDEATH, STATE offline, broker),
    # even when started from a shell that ignores SIGINT for background jobs
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    bundle()
    pw = passwords()
    with Broker(port=PORT, workdir=CACHE / "run", passwords=pw) as b:
        host = Host(b.port, b.ca, pw["stf-scada"]).start()
        edge = Edge(b.port, b.ca, pw["stf-edge"], speed=a.speed)
        threading.Thread(target=edge.run, daemon=True).start()
        print(f"""
MQTT broker   mqtts://127.0.0.1:{b.port}   (TLS 1.3; trust {b.ca})
Sparkplug B   {N.topic('#')}            primary host '{N.HOST_ID}', edge node '{N.EDGE}'
Unified NS    {N.UNS_ROOT}/#
read the UNS  user stf-viewer, password in {SECRETS}

  mosquitto_sub -h 127.0.0.1 -p {b.port} --cafile {b.ca} -u stf-viewer -P "$(python3 -c "import json;print(json.load(open('{SECRETS}'))['stf-viewer'])")" -t '{N.UNS_ROOT}/#' -v

Ctrl-C stops the edge (NDEATH), the host (STATE offline) and the broker.""", flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            edge.shutdown()
            host.stop()


if __name__ == "__main__":
    main()
