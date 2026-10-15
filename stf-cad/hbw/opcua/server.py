"""
Upgrade 14, step 2 - the cell as an OPC UA server, live from the software-in-the-loop PLC.

    STF_OPCUA_USER=operator STF_OPCUA_PASSWORD=... python3 -m opcua.server [--speed 1]
                                                            (from stf-cad/hbw; or `make opcua`)

The address space is opcua/model.py's. The values come from Upgrade 13: the compiled PLC
program (plc.wasm) scanning the plant, streamed by web/scripts/sil-stream.ts.

SECURITY (IEC 62443 zone Z3, see docs/SECURITY.md S14)
  - one endpoint, opc.tcp on 127.0.0.1:4840, Basic256Sha256 Sign & Encrypt only: no None endpoint;
  - username and password only (STF_OPCUA_USER / STF_OPCUA_PASSWORD, required), compared in
    constant time; no anonymous access; asyncua's default user manager, which accepts any
    password, is replaced;
  - client certificates must be in the trust list (.cache/opcua/pki/trusted);
  - every variable is read-only; the one method, StartOrder, restarts the simulated order.
"""
import argparse
import asyncio
import hmac
import json
import logging
import os
import socket
from pathlib import Path

from asyncua import Server, ua
from asyncua.crypto.cert_gen import setup_self_signed_certificate
from asyncua.crypto.permission_rules import User, UserRole
from asyncua.crypto.truststore import TrustStore
from asyncua.crypto.validator import CertificateValidator, CertificateValidatorOptions
from asyncua.server.user_managers import UserManager
from cryptography.x509.oid import ExtendedKeyUsageOID
from sil.stream import PHASES, STREAM, state_names
from sil.stream import bundle as bundle_stream

from opcua import model as M

HERE = Path(__file__).resolve().parent
PKI = HERE.parent / ".cache" / "opcua" / "pki"
ENDPOINT = os.environ.get("STF_OPCUA_ENDPOINT", "opc.tcp://127.0.0.1:4840/stf/")
APP_URI = "urn:stf-hw:opcua:server"
log = logging.getLogger("stf.opcua")


class OperatorUsers(UserManager):
    """Exactly one account, from the environment; no anonymous user."""

    def __init__(self, user, password):
        self.user, self.password = user, password

    def get_user(self, iserver, username=None, password=None, certificate=None):
        if not username or password is None:
            return None
        ok = hmac.compare_digest(username, self.user) & hmac.compare_digest(str(password), self.password)
        return User(role=UserRole.User) if ok else None


async def pki(hostname="localhost"):
    """The server's own key and certificate, generated once; the client trust list directory."""
    PKI.mkdir(parents=True, exist_ok=True)
    (PKI / "trusted").mkdir(exist_ok=True)
    key, cert = PKI / "server_key.pem", PKI / "server_cert.der"
    await setup_self_signed_certificate(key, cert, APP_URI, hostname, [ExtendedKeyUsageOID.SERVER_AUTH],
                                        {"countryName": "DE", "organizationName": "STF digital twin project",
                                         "commonName": "STF cell OPC UA server"})
    return key, cert


async def make_server(user, password, endpoint=ENDPOINT):
    server = Server(user_manager=OperatorUsers(user, password))
    await server.init()
    server.iserver.allow_remote_admin = False
    server.set_endpoint(endpoint)
    server.set_server_name("STF Smart Tabletop Factory (Upgrade 12)")
    await server.set_application_uri(APP_URI)
    server.set_security_policy([ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt])
    server.set_identity_tokens([ua.UserNameIdentityToken])
    key, cert = await pki()
    await server.load_certificate(str(cert))
    await server.load_private_key(str(key))
    store = TrustStore([PKI / "trusted"], [])
    await store.load()
    server.set_certificate_validator(CertificateValidator(
        CertificateValidatorOptions.BASIC_VALIDATION | CertificateValidatorOptions.PEER_CLIENT
        | CertificateValidatorOptions.TRUSTED, store))
    await M.load_companions(server)
    model = await M.build(server)
    return server, model


class Feed:
    """The PLC stream applied to the address space, writing only what changed."""

    def __init__(self, server, model, io, units):
        self.server, self.m, self.io, self.units = server, model, io, units
        self.names = state_names()
        self.jobs = json.load(open(os.path.join(M.PUBLIC, "sil", "plc.json")))["jobs"]
        self.last = {}
        self.proc = None
        self.homed = None
        self.lines = 0

    async def put(self, node, value, vt):
        key = node.nodeid
        if self.last.get(key) != value:
            self.last[key] = value
            await self.server.write_attribute_value(node.nodeid, ua.DataValue(ua.Variant(value, vt)))

    async def apply(self, d):
        for area, vt in (("ix", ua.VariantType.Boolean), ("qx", ua.VariantType.Boolean)):
            for e, v in zip(self.io[area], d[area], strict=True):
                n = self.m.signals.get(e["name"])
                if n is not None:
                    await self.put(n, bool(v), vt)
        for e, v in zip(self.io["iw"], d["iw"], strict=True):
            n = self.m.signals[e["name"]]
            await self.put(n, float(v) if e["name"] == "sorting_A4" else int(v),
                           ua.VariantType.Double if e["name"] == "sorting_A4" else ua.VariantType.Int16)
        for e, v in zip(self.io["id"], d["id"], strict=True):
            await self.put(self.m.signals[e["name"]], float(v), ua.VariantType.Double)
        fault = False
        for u, (sn, job, alarm) in zip(self.units, d["units"], strict=True):
            n = self.m.units[u]
            await self.put(n["State"], sn, ua.VariantType.Int16)
            await self.put(n["StateText"], "ready" if sn == 100 else self.names.get(u, {}).get(sn, ""), ua.VariantType.String)
            await self.put(n["Job"], self.jobs[job - 1] if job else "", ua.VariantType.String)
            await self.put(n["Busy"], sn >= 1000, ua.VariantType.Boolean)
            await self.put(n["Fault"], sn == 910, ua.VariantType.Boolean)
            await self.put(n["Alarm"], alarm, ua.VariantType.Int16)
            fault |= sn == 910
        p = self.m.production
        if d["phase"] >= 1 and self.homed is None:
            self.homed = d["t"]
        await self.put(p["Phase"], PHASES.get(d["phase"], "?"), ua.VariantType.String)
        await self.put(p["JobsCompleted"], int(d["jobs"]), ua.VariantType.UInt32)
        await self.put(p["MachineTime"], float(d["t"]), ua.VariantType.Double)
        await self.put(p["Run"], int(d["run"]), ua.VariantType.UInt32)
        if self.homed is not None:
            await self.put(p["OrderTime"], round(float(d["t"]) - self.homed, 3), ua.VariantType.Double)
        st = "OutOfService" if fault or d["flags"] else ("Executing" if d["phase"] == 1 else "NotExecuting")
        cs = await self.m.item_state.get_child(["0:CurrentState"])
        await self.put(cs, ua.LocalizedText(st), ua.VariantType.LocalizedText)
        await self.put(await cs.get_child(["0:Id"]), self.m.states[st], ua.VariantType.NodeId)

    async def run(self, speed, emit_ms):
        self.proc = await asyncio.create_subprocess_exec(
            "node", str(STREAM), os.path.join(M.PUBLIC, "sil"), str(speed), str(emit_ms),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, limit=1 << 20)
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                break
            d = json.loads(line)
            if d["run"] != getattr(self, "_run", 0):
                self._run, self.homed = d["run"], None
            await self.apply(d)
            self.lines += 1

    async def restart(self):
        self.proc.stdin.write(b"restart\n")
        await self.proc.stdin.drain()


async def add_method(server, model, feed):
    async def start_order(parent):
        await feed.restart()
        return [ua.Variant(True, ua.VariantType.Boolean)]
    prod = model.production["_object"]
    accepted = ua.Argument(Name="Accepted", DataType=ua.NodeId(ua.ObjectIds.Boolean), ValueRank=-1,
                           Description=ua.LocalizedText("true: the simulated order restarts from power-up"))
    return await prod.add_method(ua.NodeId("Production.StartOrder", model.ns), f"{model.ns}:StartOrder", start_order,
                                 [], [accepted])


async def main(speed, emit_ms):
    user, password = os.environ.get("STF_OPCUA_USER"), os.environ.get("STF_OPCUA_PASSWORD")
    if not user or not password or len(password) < 12:
        raise SystemExit("set STF_OPCUA_USER and STF_OPCUA_PASSWORD (12 characters or more)")
    bundle_stream()
    server, model = await make_server(user, password)
    io = json.load(open(os.path.join(M.PUBLIC, "sil", "plc.json")))
    feed = Feed(server, model, io["io"], io["units"])
    await add_method(server, model, feed)
    async with server:
        print(f"OPC UA server on {ENDPOINT} (Basic256Sha256 Sign & Encrypt, user '{user}'); "
              f"trust a client by copying its certificate into {PKI / 'trusted'}")
        await feed.run(speed, emit_ms)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--speed", type=float, default=1.0, help="machine time per real time (0: as fast as possible)")
    ap.add_argument("--emit-ms", type=int, default=100, help="machine time between updates")
    a = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("asyncua.common.xmlimporter").setLevel(logging.ERROR)   # the companion specs' struct notes
    socket.setdefaulttimeout(None)
    asyncio.run(main(a.speed, a.emit_ms))
