"""The inspection camera's photo store (services/api/captures.py): only real JPEGs of a known
flavour from the app's own origin are kept, within a rate and a daily budget; the local store
prunes its oldest photos; the Supabase store speaks Storage + PostgREST. No network."""

import asyncio
import json
import struct

import pytest

pytest.importorskip("fastapi")
from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402

from services.api import captures as C  # noqa: E402
from services.api import security as sec  # noqa: E402

SETTINGS = sec.Settings(("http://localhost:5173",), None, 4)


def jpeg(w=256, h=256, pad=2000) -> bytes:
    """A minimal JPEG header with a start-of-frame of w x h, padded to a realistic size."""
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, h, w, 1) + b"\x01\x11\x00"
    return (
        b"\xff\xd8"
        + b"\xff\xe0"
        + struct.pack(">H", 16)
        + b"JFIF\x00"
        + b"\x00" * 9
        + sof
        + b"\x00" * pad
        + b"\xff\xd9"
    )


def req(
    body: bytes, query="flavour=chocolate&n=3", ctype="image/jpeg", origin=None, client="10.0.0.1"
):
    headers = [(b"host", b"localhost:8000"), (b"content-type", ctype.encode())]
    if origin:
        headers.append((b"origin", origin.encode()))
    sent = {"done": False}

    async def receive():
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/vision/captures",
        "headers": headers,
        "query_string": query.encode(),
        "client": (client, 5000),
    }
    return Request(scope, receive)


def make(tmp_path, **kw):
    c = C.Captures(SETTINGS, store=C.LocalCaptures(str(tmp_path), keep=kw.pop("keep", 2000)))
    c.on = True
    return c


def up(c, body, **kw):
    return asyncio.run(c.upload(req(body, **kw)))


def test_jpeg_size_reads_the_frame_header():
    assert C.jpeg_size(jpeg(320, 240)) == (320, 240)
    assert C.jpeg_size(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100) is None


def test_a_photo_is_stored_and_listed_and_served(tmp_path):
    c = make(tmp_path)
    rec = up(c, jpeg())
    assert rec["flavour"] == "chocolate" and rec["n"] == 3 and (rec["w"], rec["h"]) == (256, 256)
    listed = c.list()["captures"]
    assert [r["id"] for r in listed] == [rec["id"]]
    assert c.image(rec["id"]).body == jpeg()


@pytest.mark.parametrize(
    "kw,code",
    [
        ({"ctype": "image/png"}, 415),
        ({"query": "flavour=pizza"}, 400),
        ({"query": "flavour=vanilla&source=hacker"}, 400),
        ({"origin": "https://evil.example"}, 403),
    ],
)
def test_uploads_that_are_refused(tmp_path, kw, code):
    with pytest.raises(HTTPException) as e:
        up(make(tmp_path), jpeg(), **kw)
    assert e.value.status_code == code


def test_not_a_jpeg_or_too_big_or_too_small(tmp_path):
    c = make(tmp_path)
    for body, code in [
        (b"\xff\xd8" + b"\x00" * 1000, 400),
        (jpeg(pad=C.MAX_BYTES), 413),
        (jpeg(8, 8, pad=600), 400),
    ]:
        with pytest.raises(HTTPException) as e:
            up(c, body, client=f"10.0.0.{code}{len(body) % 7}")
        assert e.value.status_code == code


def test_rate_per_client_and_daily_budget(tmp_path):
    c = make(tmp_path)
    for _ in range(4):
        up(c, jpeg())
    with pytest.raises(HTTPException) as e:
        up(c, jpeg())
    assert e.value.status_code == 429
    c.cap = C.DailyCap(1)
    up(c, jpeg(), client="10.9.9.9")
    with pytest.raises(HTTPException) as e:
        up(c, jpeg(), client="10.9.9.8")
    assert "budget" in e.value.detail


def test_the_local_store_keeps_only_the_newest(tmp_path):
    s = C.LocalCaptures(str(tmp_path), keep=2)
    for i in range(4):
        s.save({"id": f"{i:032x}", "t": float(i), "flavour": "vanilla"}, jpeg())
    assert [r["t"] for r in s.list(10)] == [3.0, 2.0]
    assert s.get(f"{0:032x}") is None and s.get("../../etc/passwd") is None


def test_the_supabase_store_uses_a_private_bucket_and_a_table():
    s = C.SupabaseCaptures("https://example.supabase.co/", "service-key-not-real")
    calls = []

    def fake(method, path, body=None, headers=None):
        calls.append((method, path, headers or {}))
        return json.dumps([{"id": "a" * 32}]).encode() if method == "GET" else b""

    s._req = fake
    s.save({"id": "b" * 32, "t": 1.0, "flavour": "chocolate"}, jpeg())
    assert calls[0][:2] == ("POST", f"/storage/v1/object/captures/{'b' * 32}.jpg")
    assert calls[0][2]["Content-Type"] == "image/jpeg"
    assert calls[1][:2] == ("POST", "/rest/v1/captures")
    assert s.list(5) == [{"id": "a" * 32}]
    assert calls[-1][1].startswith("/rest/v1/captures?select=")


def test_the_store_is_chosen_from_the_environment(tmp_path):
    assert isinstance(C.store_from_env({"STF_DATA_DIR": str(tmp_path)}), C.LocalCaptures)
    s = C.store_from_env({"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_KEY": "k"})
    assert isinstance(s, C.SupabaseCaptures) and s.bucket == "captures"
