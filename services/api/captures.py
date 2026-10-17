"""
The inspection camera's photographs: what the camera in the sorting line's colour hood
(stf-cad/hbw/vision/mount.py) sees each time a baked cookie passes under it, kept as a dataset
for the vision models.

The 3D twin renders the photo from the camera's own pose and optics and posts it here:

  POST /vision/captures?flavour=chocolate&n=12&source=twin   body: the JPEG
  GET  /vision/captures                                     the newest photos' records
  GET  /vision/captures/{id}.jpg                            one photo

A record is {"id", "t", "flavour", "n", "source", "bytes", "w", "h"}. Two stores keep them:

  LocalCaptures     files under STF_DATA_DIR/captures (the default): <id>.jpg + <id>.json,
                    the oldest pruned past STF_CAPTURE_KEEP. A host with an ephemeral disk
                    (Render's free tier) loses them at the next deploy.
  SupabaseCaptures  when SUPABASE_URL and SUPABASE_SERVICE_KEY are set: the JPEG in a PRIVATE
                    Storage bucket (SUPABASE_BUCKET, default "captures"), the record in the
                    table `captures` (docs/CAPTURES.md has its SQL). The service key stays on the
                    server; the browser only ever talks to this API.

Uploads come from any visitor's browser, so each one is checked: the app's own origin, a real
JPEG of a sane size, a known flavour, a rate per client and a cap per day.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Protocol

from fastapi import HTTPException, Request
from fastapi.responses import Response

from . import security as sec
from .chat import DailyCap, dotenv
from .store import ROOT

MAX_BYTES = 200_000  # a 256 px JPEG is ~10-30 kB
MIN_BYTES = 500
FLAVOURS = {"chocolate", "strawberry", "vanilla"}
SOURCES = {"twin", "line"}
ID = re.compile(r"^[0-9a-f]{32}$")
TIMEOUT_S = 15


def jpeg_size(b: bytes) -> tuple[int, int] | None:
    """(width, height) of a baseline or progressive JPEG, or None when it is not one."""
    if len(b) < 4 or b[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(b):
        if b[i] != 0xFF:
            return None
        marker = b[i + 1]
        size = int.from_bytes(b[i + 2 : i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2):  # start of frame: height, width
            return int.from_bytes(b[i + 7 : i + 9], "big"), int.from_bytes(b[i + 5 : i + 7], "big")
        i += 2 + size
    return None


class CaptureStore(Protocol):
    name: str

    def save(self, rec: dict, jpeg: bytes) -> None: ...
    def list(self, limit: int) -> list[dict]: ...
    def get(self, id: str) -> bytes | None: ...


class LocalCaptures:
    name = "local"

    def __init__(self, root: str, keep: int = 2000) -> None:
        self.dir = os.path.join(root, "captures")
        self.keep = keep

    def _p(self, id: str, ext: str) -> str:
        if not ID.match(id):
            raise ValueError("bad id")
        return os.path.join(self.dir, f"{id}.{ext}")

    def save(self, rec: dict, jpeg: bytes) -> None:
        os.makedirs(self.dir, exist_ok=True)
        with open(self._p(rec["id"], "jpg"), "wb") as f:
            f.write(jpeg)
        with open(self._p(rec["id"], "json"), "w", encoding="utf-8") as f:
            json.dump(rec, f)
        self._prune()

    def _records(self) -> list[dict]:
        try:
            names = [n for n in os.listdir(self.dir) if n.endswith(".json")]
        except OSError:
            return []
        out = []
        for n in names:
            try:
                with open(os.path.join(self.dir, n), encoding="utf-8") as f:
                    out.append(json.load(f))
            except (OSError, ValueError):
                continue
        return sorted(out, key=lambda r: r.get("t", 0), reverse=True)

    def _prune(self) -> None:
        for r in self._records()[self.keep :]:
            for ext in ("jpg", "json"):
                try:
                    os.remove(self._p(r["id"], ext))
                except (OSError, ValueError):
                    pass

    def list(self, limit: int) -> list[dict]:
        return self._records()[:limit]

    def get(self, id: str) -> bytes | None:
        try:
            with open(self._p(id, "jpg"), "rb") as f:
                return f.read()
        except (OSError, ValueError):
            return None


class SupabaseCaptures:
    """Supabase over its REST APIs: Storage for the JPEG, PostgREST for the record."""

    name = "supabase"

    def __init__(self, url: str, key: str, bucket: str = "captures", table: str = "captures"):
        self.url, self.key, self.bucket, self.table = url.rstrip("/"), key, bucket, table

    def _req(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        h = {"Authorization": f"Bearer {self.key}", "apikey": self.key, **(headers or {})}
        req = urllib.request.Request(self.url + path, method=method, data=body, headers=h)
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # noqa: S310 - the configured project URL
            return r.read()

    def save(self, rec: dict, jpeg: bytes) -> None:
        obj = f"/storage/v1/object/{self.bucket}/{rec['id']}.jpg"
        self._req("POST", obj, jpeg, {"Content-Type": "image/jpeg", "x-upsert": "false"})
        self._req(
            "POST",
            f"/rest/v1/{self.table}",
            json.dumps(rec).encode(),
            {"Content-Type": "application/json", "Prefer": "return=minimal"},
        )

    def list(self, limit: int) -> list[dict]:
        q = urllib.parse.urlencode({"select": "*", "order": "t.desc", "limit": str(limit)})
        return json.loads(self._req("GET", f"/rest/v1/{self.table}?{q}") or b"[]")

    def get(self, id: str) -> bytes | None:
        if not ID.match(id):
            return None
        try:
            return self._req("GET", f"/storage/v1/object/{self.bucket}/{id}.jpg")
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
            raise


def store_from_env(env: dict | None = None) -> CaptureStore:
    env = env if env is not None else {**dotenv(), **os.environ}
    url, key = env.get("SUPABASE_URL"), env.get("SUPABASE_SERVICE_KEY")
    if url and key:
        return SupabaseCaptures(url, key, env.get("SUPABASE_BUCKET") or "captures")
    root = env.get("STF_DATA_DIR") or ROOT
    return LocalCaptures(root, int(env.get("STF_CAPTURE_KEEP", "2000")))


class Captures:
    def __init__(self, settings: sec.Settings, store: CaptureStore | None = None) -> None:
        env = {**dotenv(), **os.environ}
        self.s = settings
        self.store = store or store_from_env(env)
        self.on = env.get("STF_CAPTURES", "1").lower() not in ("0", "false", "no")
        self.cap = DailyCap(int(env.get("STF_CAPTURE_DAILY", "500")))
        # per client: a burst of 4, then one every 3 s (a cookie passes the camera far less often)
        self.limiter = sec.RateLimiter(rate=1 / 3, burst=4)

    def status(self) -> dict:
        return {"enabled": self.on, "store": self.store.name, "max_bytes": MAX_BYTES}

    def _client(self, request: Request) -> str:
        client = request.client.host if request.client else "?"
        if client in ("127.0.0.1", "::1"):
            client = (request.headers.get("x-forwarded-for") or client).split(",")[0].strip()
        return client

    async def upload(self, request: Request) -> dict:
        if not self.on:
            raise HTTPException(status_code=503, detail="photo capture is off on this server")
        origin = request.headers.get("origin")
        if (
            origin
            and origin not in self.s.allowed_origins
            and sec._host(origin.split("://", 1)[-1]) != sec._host(request.headers.get("host"))
        ):
            raise HTTPException(status_code=403, detail="origin not allowed")
        if (request.headers.get("content-type") or "").split(";")[0].strip() != "image/jpeg":
            raise HTTPException(status_code=415, detail="a JPEG (image/jpeg) is expected")
        q = request.query_params
        flavour, source = q.get("flavour", ""), q.get("source", "twin")
        if flavour not in FLAVOURS or source not in SOURCES:
            raise HTTPException(status_code=400, detail="unknown flavour or source")
        try:
            n = int(q.get("n", "0"))
        except ValueError:
            n = 0
        if not self.limiter.allow(self._client(request)):
            raise HTTPException(status_code=429, detail="too many photos: wait a few seconds")
        body = await request.body()
        if not MIN_BYTES <= len(body) <= MAX_BYTES:
            raise HTTPException(status_code=413, detail=f"a photo of at most {MAX_BYTES} bytes")
        size = jpeg_size(body)
        if not size or not (32 <= size[0] <= 1024 and 32 <= size[1] <= 1024):
            raise HTTPException(status_code=400, detail="not a JPEG of 32 to 1024 px")
        if not self.cap.take():
            raise HTTPException(status_code=429, detail="today's photo budget is used up")
        rec = {
            "id": uuid.uuid4().hex,
            "t": time.time(),
            "flavour": flavour,
            "n": max(0, min(n, 10**9)),
            "source": source,
            "bytes": len(body),
            "w": size[0],
            "h": size[1],
        }
        try:
            self.store.save(rec, body)
        except (OSError, urllib.error.URLError, TimeoutError) as e:
            raise HTTPException(
                status_code=502, detail=f"the photo store did not answer ({type(e).__name__})"
            ) from None
        return rec

    def list(self, limit: int = 48) -> dict:
        try:
            items = self.store.list(max(1, min(limit, 200)))
        except (OSError, urllib.error.URLError, TimeoutError, ValueError):
            items = []
        return {"captures": items, **self.status()}

    def image(self, id: str) -> Response:
        if not ID.match(id):
            raise HTTPException(status_code=404, detail="no such photo")
        try:
            b = self.store.get(id)
        except (OSError, urllib.error.URLError, TimeoutError):
            b = None
        if not b:
            raise HTTPException(status_code=404, detail="no such photo")
        return Response(
            b,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400, immutable"},
        )
