"""The pgvector backend (services/api/vectors.py, PgVectorStore) and the STF_VECTOR_BACKEND
factory. No network: keepalive.urlopen is replaced with a fake that scripts PostgREST answers,
the same seam the other Supabase clients are tested through. The migration file is checked so
the RPC names in SQL and Python cannot drift apart."""

from __future__ import annotations

import io
import json
import urllib.error

import numpy as np
import pytest

from services.api import vectors as V

pytest.importorskip("fastapi")


class ToyEmbedder(V.Embedder):
    name = "toy"
    dim = 3

    def __init__(self, rows: dict[str, np.ndarray]):
        self.rows = rows

    def embed(self, texts):
        out = np.stack([self.rows[t] for t in texts])
        return out / np.linalg.norm(out, axis=1, keepdims=True)


TOY = ToyEmbedder(
    {
        "x": np.array([1.0, 0, 0]),
        "y": np.array([0, 1.0, 0]),
        "z": np.array([0, 0, 1.0]),
    }
)

TOY_EMB = {10: "[1,0,0]", 11: "[0,1,0]", 12: "[0,0,1]"}


class FakeResp:
    """The piece of urllib's response PgVectorStore touches."""

    def __init__(self, body: object, code: int = 200):
        self._raw = json.dumps(body).encode() if body is not None else b""
        self.status = code

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeRest:
    """Scripts PostgREST: GET/POST by path prefix; raises HTTPError where told."""

    def __init__(self, get: dict[str, object], post: dict[str, object], missing: set[str]):
        self.get, self.post, self.missing = get, post, missing
        self.calls: list[tuple[str, str, object]] = []

    def __call__(self, req, timeout=0):
        path = req.full_url.split("/rest/v1/", 1)[1]
        method = req.get_method()
        body = json.loads(req.data) if req.data else None
        self.calls.append((method, path, body))
        # keyed on table only (PostgREST paths carry long query strings)
        table = path.split("?", 1)[0]
        if table in self.missing:
            raise urllib.error.HTTPError(req.full_url, 404, "missing", {}, io.BytesIO(b"{}"))
        data = self.get.get(f"{method} {table}") if method == "GET" else self.post.get(
            f"{method} {table}"
        )
        if data == "404":
            raise urllib.error.HTTPError(req.full_url, 404, "missing", {}, io.BytesIO(b"{}"))
        if isinstance(data, Exception):
            raise data
        return FakeResp(data)


def fake_rest(monkeypatch, get=None, post=None, missing=()):
    rest = FakeRest(get or {}, post or {}, set(missing))
    monkeypatch.setattr(V.keepalive, "urlopen", rest)
    return rest


# ------------------------------------------------------------------ embedding text form
def test_pgvec_text_form_roundtrips():
    row = np.array([0.5, -0.25, 0.0], dtype=np.float32)
    text = V._pgvec(row)
    assert text.startswith("[") and text.endswith("]")
    np.testing.assert_allclose(V._parse_pgvec(text, 3), row, atol=1e-6)
    assert V._parse_pgvec("[]", 3).shape == (3,)


# ------------------------------------------------------------------ availability and readiness
def test_available_false_when_the_table_is_missing(monkeypatch):
    fake_rest(monkeypatch, missing={"kb_vectors"})
    store = V.PgVectorStore("https://p.supabase.co", "k", TOY)
    assert store.available() is False


def test_available_checks_the_dimension(monkeypatch):
    fake_rest(monkeypatch, get={"GET kb_vectors": [{"emb": "[1,0,0]"}]})
    store = V.PgVectorStore("https://p.supabase.co", "k", TOY)
    assert store.available() is True
    fake_rest(monkeypatch, get={"GET kb_vectors": [{"emb": "[1,0,0,0]"}]})
    assert store.available() is False


def test_ready_compares_the_meta_key(monkeypatch):
    ids = [10, 11, 12]
    key = V._cache_key(TOY, ids)
    fake_rest(
        monkeypatch,
        get={
            "GET kb_meta": [{"v": key}],
            "GET kb_vectors": [{"id": i} for i in ids],
        },
    )
    store = V.PgVectorStore("https://p.supabase.co", "k", TOY)
    assert store.ready(ids) is True
    assert store.ready([10, 11]) is False  # the kb changed: a rebuild is due
    assert store.count() == 3


# ------------------------------------------------------------------ build
def test_build_resets_inserts_batches_and_caches(monkeypatch):
    ids = [10, 11, 12]
    rest = fake_rest(
        monkeypatch,
        post={"POST rpc/stf_kb_reset": None, "POST rpc/stf_kb_insert": None},
    )
    store = V.PgVectorStore("https://p.supabase.co", "k", TOY)
    store.build(ids, ["x", "y", "z"])
    methods = [c for c in rest.calls if c[0] == "POST"]
    assert methods[0][1].startswith("rpc/stf_kb_reset")  # truncate first, then the rows
    inserted = [body["p_rows"] for m, p, body in methods if p.startswith("rpc/stf_kb_insert")]
    assert [row["id"] for batch in inserted for row in batch] == ids
    assert inserted[0][0]["file"] != "" or "emb" in inserted[0][0]
    assert inserted[0][0]["emb"].startswith("[")
    got_ids, m = store.matrix()  # served from the cache the build left
    assert got_ids == ids and m.shape == (3, 3)


# ------------------------------------------------------------------ top-k
def test_top_uses_the_ann_rpc(monkeypatch):
    fake_rest(
        monkeypatch,
        post={"POST rpc/stf_match_kb": [{"id": 12, "score": 0.98}, {"id": 11, "score": 0.4}]},
    )
    store = V.PgVectorStore("https://p.supabase.co", "k", TOY)
    assert store.top("z", 2) == [(12, 0.98), (11, 0.4)]


def test_top_falls_back_to_bruteforce_when_the_rpc_is_missing(monkeypatch):
    rest = fake_rest(
        monkeypatch,
        get={"GET kb_vectors": [{"id": i, "emb": e} for i, e in TOY_EMB.items()],},
        post={"POST rpc/stf_match_kb": "404"},
    )
    store = V.PgVectorStore("https://p.supabase.co", "k", TOY)
    top = store.top("z", 2)
    assert top[0] == (12, pytest.approx(1.0))  # the exact neighbour, found without the RPC
    assert store._ann is False  # not retried after the first 404
    assert store.top("z", 1)[0][0] == 12
    assert len([c for c in rest.calls if "stf_match_kb" in c[1]]) == 1


# ------------------------------------------------------------------ backend selection
def test_pgvector_store_needs_supabase_config():
    assert V._pgvector_store({}, TOY) is None
    assert V._pgvector_store({"SUPABASE_URL": "https://p.supabase.co"}, TOY) is None


def test_auto_backend_prefers_pgvector_only_when_configured(monkeypatch):
    sentinel = V.PgVectorStore("https://p.supabase.co", "k", TOY)
    monkeypatch.setattr(V, "_pgvector_store", lambda env, e: sentinel)
    V._store = False
    got = V.get_store(
        {"STF_EMBEDDER": "hash", "STF_VECTOR_BACKEND": "auto",
         "SUPABASE_URL": "https://p.supabase.co", "SUPABASE_SERVICE_KEY": "k"}
    )
    assert got is sentinel
    V._store = False
    got = V.get_store({"STF_EMBEDDER": "hash", "STF_VECTOR_BACKEND": "sqlite",
                       "SUPABASE_URL": "https://p.supabase.co", "SUPABASE_SERVICE_KEY": "k"})
    assert isinstance(got, V.VectorStore)
    V._store = False
    assert V.get_store({"STF_EMBEDDER": "off"}) is None
    V._store = False


def test_auto_falls_back_to_sqlite_when_pgvector_cannot_answer(monkeypatch, tmp_path):
    def boom(env, embedder):
        raise OSError("unreachable")

    monkeypatch.setattr(V, "_pgvector_store", boom)
    monkeypatch.setenv("STF_DATA_DIR", str(tmp_path))
    V._store = False
    got = V.get_store({"STF_EMBEDDER": "hash", "STF_VECTOR_BACKEND": "auto",
                       "SUPABASE_URL": "https://p.supabase.co", "SUPABASE_SERVICE_KEY": "k"})
    assert isinstance(got, V.VectorStore)
    V._store = False


# ------------------------------------------------------------------ the migration matches the code
def test_migration_defines_what_the_store_calls(repo_root):
    sql = (repo_root / "supabase/migrations/20261023023000_stf_kb_vectors.sql").read_text()
    for needle in (
        "create extension if not exists vector",
        "kb_vectors",
        "kb_meta",
        "using hnsw (emb vector_cosine_ops)",
        "stf_kb_reset",
        "stf_kb_insert",
        "stf_match_kb",
    ):
        assert needle in sql, needle
