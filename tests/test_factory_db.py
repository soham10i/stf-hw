"""The factory's data in the database (services/api/factory_db.py, db_seed.py): the seed is built
from the same files the dashboard reads, and the twin's records are kept per guest. SQLite only
(conftest.py): no test touches Supabase."""

import pytest

pytest.importorskip("fastapi")

from services.api import db_seed as D  # noqa: E402
from services.api import factory_db as F  # noqa: E402


def test_the_seed_is_what_the_dashboard_reads():
    import json

    data = D.build()
    month = json.load(open("web/public/month/month.json"))["kpi"]
    assert len(data["orders"]) == month["orders"]
    assert sum(r["good"] for r in data["orders"]) == month["good"]
    assert sum(r["baked"] for r in data["orders"]) == month["baked"]
    assert all(
        r["qc_fault"] in ("burnt", "underbaked", "cracked") for r in data["orders"]
    )  # one per order
    assert set(data) <= set(F.TABLES)
    for table, rows in data.items():
        cols = set(F.TABLES[table][0])
        assert all(set(r) <= cols for r in rows), table
    assert len(D.samples()) == 10


def test_sqlite_keeps_the_rows(tmp_path):
    db = F.SqliteFactory(str(tmp_path / "f.db"))
    db.insert(
        "inspections",
        [
            {
                "source": "twin",
                "owner": "a" * 32,
                "t": "2026-10-18T00:00:00+00:00",
                "n": 1,
                "flavour": "vanilla",
                "truth": "burnt",
                "verdict": "reject",
            }
        ],
    )
    assert db.count("inspections") == 1
    assert db.recent("inspections", "a" * 32)[0]["truth"] == "burnt"
    assert db.recent("inspections", "b" * 32) == []
    db.clear("inspections")
    assert db.count("inspections") == 0


def test_the_twin_stores_its_cookies_and_orders_as_the_guests():
    from fastapi.testclient import TestClient

    import services.api.app as appmod

    H = {"host": "localhost:8000"}
    with TestClient(appmod.app) as c:
        ok = c.post(
            "/twin/inspection",
            headers=H,
            json={
                "n": 3,
                "flavour": "vanilla",
                "truth": "burnt",
                "condition": "burnt",
                "p": 0.99,
                "verdict": "reject",
                "ae": 0.5,
                "unusual": False,
            },
        )
        assert ok.status_code == 200
        c.post(
            "/twin/order",
            headers=H,
            json={
                "flavour": "vanilla",
                "qty": 3,
                "baked": 4,
                "good": 3,
                "scrap": 1,
                "qc_fault": "burnt",
            },
        )
        mine = c.get("/twin/records", headers=H).json()
        assert [r["truth"] for r in mine["inspections"]] == ["burnt"]
        assert mine["orders"][0]["qc_fault"] == "burnt"
        guest = dict(c.cookies)
        c.cookies.clear()  # a new visitor: a guest of their own, who sees none of it
        assert c.get("/twin/records", headers=H).json()["inspections"] == []
        c.cookies.update(guest)
        bad = c.post(
            "/twin/inspection",
            headers=H,
            json={
                "n": 1,
                "flavour": "mint",
                "truth": "ok",
                "condition": "ok",
                "p": 1,
                "verdict": "pass",
                "ae": 0,
                "unusual": False,
            },
        )
        assert bad.status_code == 422
