"""
Sparkplug B payloads: build and read them with the official schema.

sparkplug_b.proto is Eclipse Tahu's (EPL-2.0, see README.md); sparkplug_b_pb2.py is generated
from it by protoc (grpcio-tools) and committed, so only the protobuf runtime is needed.
"""
import time

from uns.sparkplug.sparkplug_b_pb2 import Payload

INT_TYPES = {1: 8, 2: 16, 3: 32, 5: 0, 6: 0, 7: 0}          # Int8/16/32 (signed bits), UInt8/16/32
LONG_TYPES = {4: 64, 8: 0, 13: 0}                           # Int64, UInt64, DateTime


def now_ms():
    return int(time.time() * 1000)


def set_value(pm, dtype, value):
    pm.datatype = dtype
    if value is None:
        pm.is_null = True
    elif dtype in INT_TYPES:
        pm.int_value = int(value) & 0xFFFFFFFF                # signed: two's complement in the uint32
    elif dtype in LONG_TYPES:
        pm.long_value = int(value) & 0xFFFFFFFFFFFFFFFF
    elif dtype == 9:
        pm.float_value = float(value)
    elif dtype == 10:
        pm.double_value = float(value)
    elif dtype == 11:
        pm.boolean_value = bool(value)
    elif dtype in (12, 14, 15):
        pm.string_value = str(value)
    else:
        raise ValueError(f"datatype {dtype} not supported here")


def get_value(pm):
    if pm.is_null:
        return None
    kind = pm.WhichOneof("value")
    v = getattr(pm, kind) if kind else None
    if pm.datatype in INT_TYPES and INT_TYPES[pm.datatype] and v >= 1 << 31:
        v -= 1 << 32
    if pm.datatype == 4 and v >= 1 << 63:
        v -= 1 << 64
    return v


def props(pm):
    """A metric's PropertySet as a dict."""
    if not pm.HasField("properties"):
        return {}
    return {k: (getattr(v, v.WhichOneof("value")) if v.WhichOneof("value") else None)
            for k, v in zip(pm.properties.keys, pm.properties.values, strict=True)}


def _props(pm, props):
    for k, v in props.items():
        pm.properties.keys.append(k)
        pv = pm.properties.values.add()
        if isinstance(v, float):
            pv.type, pv.double_value = 10, v
        else:
            pv.type, pv.string_value = 12, str(v)


def payload(metrics, seq=None, ts=None):
    """metrics: (name or None, alias or None, datatype, value, properties or None) tuples."""
    p = Payload()
    p.timestamp = ts if ts is not None else now_ms()
    if seq is not None:
        p.seq = seq
    for name, alias, dtype, value, props in metrics:
        pm = p.metrics.add()
        if name is not None:
            pm.name = name
        if alias is not None:
            pm.alias = alias
        pm.timestamp = p.timestamp
        set_value(pm, dtype, value)
        if props:
            _props(pm, props)
    return p.SerializeToString()


def decode(raw):
    p = Payload()
    p.ParseFromString(raw)
    return p
