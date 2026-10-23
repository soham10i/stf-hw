"""
Load the factory's data into the database the API uses (Supabase, or the local SQLite file), so
the database holds what the dashboard shows - the same files the dashboard reads:

  web/public/month/: orders, events, sensors, raw, daily   the simulated month
  web/public/grid/grid_15min.csv                           the energy month
  web/public/bake/process.json                             the bake process
  web/public/vision/samples/                               ten photos and their decisions

    PYTHONPATH=packages .venv/bin/python -m services.api.db_seed            (or `make db-seed`)
    ... -m services.api.db_seed --reset     first forget every guest, conversation and photo

The factory tables are emptied and loaded again each run, so a run after the simulations change
brings the database level with them. Prints counts - never a key.
"""

from __future__ import annotations

import csv
import json
import os
import secrets
import sys
import time
import urllib.parse
import urllib.request

from . import guests as G
from .captures import jpeg_size, store_from_env
from .chat import dotenv
from .factory_db import TABLES, factory_from

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PUB = os.path.join(ROOT, "web", "public")
TZ = "+02:00"  # September and October, central European summer time (to 25 Oct)


def _f(v: str):
    if v in ("", None):
        return None
    try:
        x = float(v)
        return int(x) if x.is_integer() and "." not in v else x
    except ValueError:
        return v


def rows_csv(path: str) -> list[dict]:
    """Load one CSV with numeric strings coerced to numbers."""
    with open(path, newline="", encoding="utf-8") as f:
        return [{k: _f(v) for k, v in r.items()} for r in csv.DictReader(f)]


def ts(t: str) -> str:
    """Normalize a CSV timestamp to the full timestamptz shape Postgres accepts."""
    return t + (":00" if len(t) == 16 else "") + TZ


def build() -> dict[str, list[dict]]:
    """Assemble every table's seed rows from web/public/month."""
    m = os.path.join(PUB, "month")
    out: dict[str, list[dict]] = {}
    out["orders"] = [
        {
            "source": "month",
            "owner": "",
            "t": ts(r["time"]),
            "day": r["day"],
            "shift": r["shift"],
            "dur_s": r["dur"],
            "baked": r.get("baked", 9),
            "good": r["good"],
            "scrap": r["scrap"],
            "qc_fault": r.get("qc_fault") or "",
            "returned": r["returned"],
            "hall_c": r["temp"],
        }
        for r in rows_csv(os.path.join(m, "orders.csv"))
    ]
    out["events"] = [
        {
            "t": ts(r["time"]),
            "kind": r["kind"],
            "what": r["what"],
            "comp": r["comp"],
            "code": r["code"],
            "lost_s": r["lost_s"],
            "down_h": r["down_h"],
        }
        for r in rows_csv(os.path.join(m, "events.csv"))
    ]
    out["sensor_readings"] = [
        {
            "t": ts(r["time"]),
            "component": r["component"],
            "observed": r["observed"],
            "ewma_r": r["ewma_r"],
            "health_index": r["health_index"],
            "rul_shifts": r["rul_shifts"],
        }
        for r in rows_csv(os.path.join(m, "sensors.csv"))
    ]
    out["signals"] = [
        {**{k: v for k, v in r.items() if k != "time"}, "t": ts(r["time"])}
        for r in rows_csv(os.path.join(m, "raw.csv"))
    ]
    out["daily_kpis"] = [
        {k.lower(): v for k, v in r.items()} for r in rows_csv(os.path.join(m, "daily.csv"))
    ]
    out["energy_15min"] = [
        {**r, "dr_event": bool(r["dr_event"])}
        for r in rows_csv(os.path.join(PUB, "grid", "grid_15min.csv"))
    ]
    bake = json.load(open(os.path.join(PUB, "bake", "process.json"), encoding="utf-8"))
    out["bakes"] = [
        {
            "policy": p,
            "n": i + 1,
            "lot": c["lot"],
            "fridge": c["fridge"],
            "thick_mm": c["thick_mm"],
            "t0_c": c["t0"],
            "x0": c.get("x0"),
            "bake_s": c["bake_s"],
            "browning": c["b"],
            "water_pct": c["water_pct"],
            "core_peak_c": c.get("core_peak"),
            "verdict": c["verdict"],
            "target": c.get("target"),
        }
        for p, cs in bake["cookies"].items()
        for i, c in enumerate(cs)
    ]
    return out


def samples() -> list[tuple[dict, bytes]]:
    """The vision sample photos with their labels."""
    d = os.path.join(PUB, "vision", "samples")
    s = json.load(open(os.path.join(d, "samples.json"), encoding="utf-8"))
    return [(x, open(os.path.join(d, x["file"]), "rb").read()) for x in s["samples"]]


def reset(db, caps) -> None:
    """Forget every guest, their conversations and photos, and every stored photo."""
    if db.name == "supabase":

        def req(method, path, body=None):
            """One authenticated PostgREST call against the seed target."""
            h = {
                "Authorization": f"Bearer {db.key}",
                "apikey": db.key,
                "Content-Type": "application/json",
            }
            r = urllib.request.Request(
                db.url + path,
                method=method,
                headers=h,
                data=json.dumps(body).encode() if body is not None else None,
            )
            with urllib.request.urlopen(r, timeout=30) as x:  # noqa: S310 - the configured project URL
                raw = x.read()
                return json.loads(raw) if raw else None

        # the bucket's objects (also any no table row points at), then the rows
        bucket = getattr(caps, "bucket", "captures")
        while True:
            objs = (
                req(
                    "POST",
                    f"/storage/v1/object/list/{bucket}",
                    {"prefix": "", "limit": 1000, "offset": 0},
                )
                or []
            )
            names = [o["name"] for o in objs if o.get("id")]
            if not names:
                break
            req("DELETE", f"/storage/v1/object/{bucket}", {"prefixes": names})
        for table, col in (
            ("inspections", "id"),
            ("captures", "id"),
            ("documents", "id"),
            ("guests", "id"),
        ):
            req("DELETE", f"/rest/v1/{table}?{urllib.parse.quote(col)}=not.is.null")
    else:
        for owner in [r[0] for r in db._db.execute("SELECT id FROM guests").fetchall()]:
            caps.forget(owner)
        db._db.execute("DELETE FROM documents")
        db._db.execute("DELETE FROM guests")
        caps.forget("sample")


def main() -> int:
    """The seed CLI: push the demo dataset into the configured database."""
    env = {**dotenv(), **os.environ}
    db, note = G.db_from_env(env)
    caps = store_from_env(env)
    fac = factory_from(db)
    print(f"database: {db.name} ({note})")
    if "--reset" in sys.argv:
        reset(db, caps)
        print("  reset: every guest, conversation and photo forgotten")
    data = build()
    for table in TABLES:
        fac.clear(table)
    for table, rows in data.items():
        t0 = time.monotonic()
        fac.insert(table, rows)
        print(f"  {table:16s} {len(rows):6d} rows  {time.monotonic() - t0:4.1f} s")
    # the ten sample photos: into the photo store, and their decisions into inspections
    caps.forget("sample")
    ins = []
    for x, jpeg in samples():
        w, h = jpeg_size(jpeg) or (0, 0)
        cid = secrets.token_hex(16)
        caps.save(
            {
                "id": cid,
                "t": time.time(),
                "flavour": x["flavour"],
                "n": x["n"],
                "source": "sample",
                "bytes": len(jpeg),
                "w": w,
                "h": h,
                "owner": "sample",
            },
            jpeg,
        )
        ins.append(
            {
                "source": "sample",
                "owner": "sample",
                "t": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
                "n": x["n"],
                "flavour": x["flavour"],
                "truth": x["truth"],
                "condition": x["condition"],
                "p": None,
                "verdict": x["verdict"],
                "ae": None,
                "unusual": x.get("unusual"),
                "capture_id": cid,
            }
        )
    fac.insert("inspections", ins)
    print(f"  {'inspections':16s} {len(ins):6d} rows  (and {len(ins)} photos, {caps.name})")
    # a table with a source column also keeps the visitors' own twin rows (factory_db clear):
    # it holds at least the seeded rows
    bad = [t for t, rows in data.items()
           if (fac.count(t) < len(rows) if "source" in TABLES[t][0] else fac.count(t) != len(rows))]
    if fac.count("inspections") < len(ins):
        bad.append("inspections")
    print("all loaded" if not bad else f"count mismatch: {', '.join(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
