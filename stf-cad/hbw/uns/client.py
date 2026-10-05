"""MQTT client helpers (paho-mqtt 2): every client of the cell talks TLS to the cell's broker."""
import ssl
import threading

import paho.mqtt.client as mqtt


def make(client_id, user, password, ca, v5=False):
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id,
                    protocol=mqtt.MQTTv5 if v5 else mqtt.MQTTv311, **({} if v5 else {"clean_session": True}))
    c.tls_set(ca_certs=str(ca), tls_version=ssl.PROTOCOL_TLS_CLIENT)      # verifies the server's certificate and name
    if user is not None:
        c.username_pw_set(user, password)
    return c


def connect(c, port, timeout=5.0, host="127.0.0.1", on_connect=None):
    """Connect and wait for the CONNACK. Returns the reason ('Success' or why not)."""
    got, ev = {}, threading.Event()

    def _oc(client, userdata, flags, rc, props):
        got["rc"] = str(rc)
        if on_connect and not rc.is_failure:
            on_connect(client)
        ev.set()
    c.on_connect = _oc
    try:
        kw = {"clean_start": True} if c.protocol == mqtt.MQTTv5 else {}
        c.connect(host, port, keepalive=5, **kw)
    except Exception as e:                       # noqa: BLE001 - TLS or socket refusal
        return type(e).__name__
    c.loop_start()
    if not ev.wait(timeout):
        c.loop_stop()
        return "timeout"
    if got["rc"] != "Success":
        c.loop_stop()
    return got["rc"]
