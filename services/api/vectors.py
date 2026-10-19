"""
The vector side of the copilot's memory: embeddings over the knowledge base's passages
(web/public/copilot/kb.json), stored in a small SQLite vector store, fused with the BM25 index
(grounding.py) by reciprocal rank fusion. BM25 stays the spine - the documents' citations,
score thresholds and the orchestrator's routing speak its language - while the vectors add
recall for questions whose words don't match the documents' words.

  hybrid_search(query, top_k)   BM25 + vector results, RRF-fused; each hit carries its BM25
                                "score" (0 when BM25 did not rank it) and a "vscore" cosine.
                                Vector-only candidates enter only when BM25 found nothing or
                                they beat the weakest BM25 hit's cosine by a clear margin, so
                                the fused ranking is a re-ranking of BM25's set, not a takeover.

The embedder is a seam, chosen by STF_EMBEDDER (auto by default):

  hash      default, zero dependencies: signed feature hashing of the stemmed search tokens
            into 384 dims, log-tf weighted, L2-normalised. Weak on synonyms, but deterministic
            and free - good enough to re-rank and safe to run everywhere, tests included.
  minilm    sentence-transformers all-MiniLM-L6-v2 (STF_EMBED_MODEL to change it) - real
            semantic vectors, downloaded once; falls back to hash when the import or the first
            embedding fails.
  http      an OpenAI-compatible /v1/embeddings endpoint (EMBEDDINGS_URL, optional
            EMBEDDINGS_KEY/EMBEDDINGS_MODEL) - text-embeddings-inference or vLLM on Azure
            Container Apps / Cloud Run serve this; falls back to hash when unreachable.
  off       vectors disabled: hybrid_search is BM25 with vscore 0.

The store is one SQLite file (STF_DATA_DIR or .data, vectors.sqlite) holding the embedding
matrix keyed by (embedder, dimensions, passage ids) - rebuilt only when the knowledge base or
the embedder changes. numpy is the only dependency, already in pyproject.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import urllib.error
import urllib.request

import numpy as np

from .grounding import get_bm25, tokenize
from .logging_config import get_logger

logger = get_logger(__name__)

DIM = 384  # the hash embedder's width; minilm is 384 too, http embedders report theirs
RRF_K = 60.0  # reciprocal rank fusion's smoothing constant
COS_MARGIN = 0.12  # a vector-only hit must beat the best BM25 hit's cosine by this to enter
VECTOR_ACCEPT = 0.45  # a vector-only hit counts as a match from this cosine on (search_docs)
VECTORS_FLOOR = 0.30  # never index fewer passages than this (a broken kb should not wipe rows)


class Embedder:
    """Abstract base class defining the embedding model interface."""

    name = "base"
    dim = DIM

    def embed(self, texts: list[str]) -> np.ndarray:
        """Encode an array of texts into an L2-normalized float32 matrix.

        Args:
            texts: List of input strings.

        Returns:
            np.ndarray: 2D array of shape (len(texts), dim).
        """
        raise NotImplementedError

    def ok(self) -> bool:
        """Check whether this embedding provider is operational and ready to use.

        Returns:
            bool: True if available, False otherwise.
        """
        return True


class HashEmbedder(Embedder):
    """Deterministic, dependency-free feature hashing embedder based on Blake2b digests."""

    name = "hash"

    def embed(self, texts: list[str]) -> np.ndarray:
        """Encode texts into 384-dimensional sparse vectors using sign hashing and log-TF weights.

        Args:
            texts: List of text passages or queries.

        Returns:
            np.ndarray: Normalized 2D float32 array where dot products equal cosine similarities.
        """
        rows = np.zeros((len(texts), DIM), dtype=np.float32)
        for r, text in enumerate(texts):
            for tok in set(tokenize(text)):
                d = hashlib.blake2b(tok.encode(), digest_size=8).digest()
                idx = int.from_bytes(d[:4], "little") % DIM
                sign = 1.0 if d[4] & 1 else -1.0
                rows[r, idx] += sign
            nz = rows[r] != 0
            if nz.any():
                rows[r][nz] = 1.0 + np.log(np.abs(rows[r][nz]))
                n = np.linalg.norm(rows[r])
                if n > 0:
                    rows[r] /= n
        return rows


class MiniLmEmbedder(Embedder):
    """Local transformer embedding model using sentence-transformers (all-MiniLM-L6-v2)."""

    name = "minilm"

    def __init__(self, model: str) -> None:
        """Initialize sentence-transformers model instance.

        Args:
            model: HuggingFace model identifier.
        """
        self.model_id = model
        self._model = None
        try:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415

            self._model = SentenceTransformer(model)
            self.dim = int(self._model.get_sentence_embedding_dimension())
        except Exception as e:
            logger.warning("sentence-transformers unavailable (%s); hash embedder instead", e)
            self._model = None

    def ok(self) -> bool:
        """Return True if sentence-transformers model loaded successfully."""
        return self._model is not None

    def embed(self, texts: list[str]) -> np.ndarray:
        """Encode texts using the local sentence transformer model.

        Args:
            texts: List of input strings.

        Returns:
            np.ndarray: L2-normalized float32 embedding matrix.
        """
        if self._model is None:
            return np.zeros((len(texts), self.dim), dtype=np.float32)
        v = self._model.encode(texts, normalize_embeddings=True)  # type: ignore[union-attr]
        return np.asarray(v, dtype=np.float32)


class HttpEmbedder(Embedder):
    """An OpenAI-compatible embeddings service client (TEI, vLLM, Azure OpenAI, etc.)."""

    def __init__(self, url: str, key: str | None, model: str | None) -> None:
        """Initialize the HTTP embedder endpoint.

        Args:
            url: Base URL or full endpoint URL for the embeddings service.
            key: Optional Bearer authentication token.
            model: Optional model name to include in embedding request payloads.
        """
        self.url = url.rstrip("/") + "/embeddings"
        self.key = key
        self.model = model
        self.name = "http"
        self._probe: np.ndarray | None = None

    def _post(self, texts: list[str]) -> dict:
        """Submit an embedding request to the remote endpoint.

        Args:
            texts: List of text strings to embed.

        Returns:
            dict: Parsed JSON response containing embeddings data.

        Raises:
            urllib.error.URLError: On network failure or connection refusal.
            TimeoutError: When the remote endpoint fails to respond within 30 seconds.
            json.JSONDecodeError: When the response is not valid JSON.
        """
        body: dict[str, object] = {"input": texts}
        if self.model:
            body["model"] = self.model
        req = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.key}"} if self.key else {}),
            },
        )
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - operator-configured URL
            return json.loads(r.read())

    def _rows(self, texts: list[str]) -> np.ndarray:
        """Fetch and normalize embedding vectors for given texts.

        Args:
            texts: List of text strings to encode.

        Returns:
            np.ndarray: Matrix of L2-normalized embedding vectors of shape (len(texts), dim).
        """
        try:
            d = self._post(texts)
            data = sorted(d.get("data", []), key=lambda x: x.get("index", 0))
            rows = np.asarray([x["embedding"] for x in data], dtype=np.float32)
            if rows.ndim < 2 or rows.shape[0] == 0:
                return np.zeros((len(texts), self.dim), dtype=np.float32)
            norms = np.linalg.norm(rows, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            return rows / norms
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError) as e:
            logger.error("HTTP embedding request failed to %s: %s", self.url, e)
            return np.zeros((len(texts), self.dim), dtype=np.float32)

    def ok(self) -> bool:
        """Check whether the remote embeddings service is reachable and responsive.

        Returns:
            bool: True if the probe request succeeded and valid embeddings were returned.
        """
        if self._probe is None:
            try:
                self._probe = self._rows(["probe"])
                if self._probe.shape[0] > 0 and self._probe.shape[1] > 0:
                    self.dim = int(self._probe.shape[1])
                else:
                    self._probe = np.zeros((0, 0), dtype=np.float32)
            except Exception as e:
                logger.warning(
                    "Embeddings endpoint %s unreachable (%s); falling back to hash embedder",
                    self.url,
                    e,
                )
                self._probe = np.zeros((0, 0), dtype=np.float32)
        return self._probe.shape[0] > 0

    def embed(self, texts: list[str]) -> np.ndarray:
        """Embed an array of text strings.

        Args:
            texts: List of strings to encode.

        Returns:
            np.ndarray: L2-normalized embedding rows.
        """
        return self._rows(texts)


def _data_dir() -> str:
    """Return the absolute path to the local data directory, creating it if needed."""
    root = os.environ.get("STF_DATA_DIR") or os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")), ".data"
    )
    os.makedirs(root, exist_ok=True)
    return root


def make_embedder(env: dict[str, str] | None = None) -> Embedder | None:
    """Factory creating an Embedder instance according to environment configuration.

    Resolution strategy:
      - 'off': Returns None (pure BM25 retrieval).
      - 'auto': Tries MiniLM if installed, then HTTP if configured, falls back to HashEmbedder.
      - 'minilm': Sentence-transformers (falls back to HashEmbedder with warning if absent).
      - 'http': Remote OpenAI-compatible API (falls back to HashEmbedder if absent).
      - 'hash': Fast deterministic token hashing.

    Args:
        env: Optional dictionary containing environment variables.

    Returns:
        Embedder | None: Configured Embedder instance, or None if vectors are disabled.
    """
    env = env if env is not None else os.environ
    want = env.get("STF_EMBEDDER", "auto").lower()
    if want == "off":
        return None
    if want in ("auto", "minilm"):
        m = MiniLmEmbedder(env.get("STF_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2"))
        if m.ok():
            return m
        if want == "minilm":
            logger.warning("STF_EMBEDDER=minilm requested but model is unavailable; falling back to hash")
    if want in ("auto", "http"):
        url = env.get("EMBEDDINGS_URL")
        if url:
            h = HttpEmbedder(url, env.get("EMBEDDINGS_KEY"), env.get("EMBEDDINGS_MODEL"))
            if h.ok():
                return h
        elif want == "http":
            logger.warning("STF_EMBEDDER=http requested but EMBEDDINGS_URL is not set; falling back to hash")
    return HashEmbedder()


class VectorStore:
    """Passage embeddings stored in a SQLite file: metadata and float32 BLOBs per passage ID."""

    def __init__(self, path: str, embedder: Embedder) -> None:
        """Initialize the vector store with SQLite database path and embedding model.

        Args:
            path: Local filesystem path to the SQLite vector database.
            embedder: Embedding strategy instance used to encode passages and queries.
        """
        self.path = path
        self.embedder = embedder
        self._lock = threading.Lock()
        self._matrix: np.ndarray | None = None
        self._ids: list[int] = []
        self._open()

    def _open(self) -> None:
        """Open the SQLite database connection and ensure tables exist."""
        try:
            self.db = sqlite3.connect(self.path, check_same_thread=False)
            self.db.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
            self.db.execute("CREATE TABLE IF NOT EXISTS vectors (id INTEGER PRIMARY KEY, v BLOB)")
            logger.debug("Vector store database initialized at '%s'", self.path)
        except sqlite3.Error as e:
            logger.error("Failed to initialize vector database at '%s': %s", self.path, e, exc_info=True)
            raise

    def _key(self, ids: list[int]) -> str:
        """Compute cache invalidation hash key based on embedder name, dimension, and passage IDs."""
        h = hashlib.blake2b(digest_size=10)
        h.update(self.embedder.name.encode())
        h.update(str(self.embedder.dim).encode())
        h.update(",".join(map(str, ids)).encode())
        return h.hexdigest()

    def _meta(self, k: str) -> str | None:
        """Retrieve a metadata value by key."""
        try:
            row = self.db.execute("SELECT v FROM meta WHERE k = ?", (k,)).fetchone()
            return row[0] if row else None
        except sqlite3.Error as e:
            logger.warning("Failed to read metadata key '%s' from vector store: %s", k, e)
            return None

    def ready(self, ids: list[int]) -> bool:
        """Check whether the persisted vector store is up to date for the given passage IDs."""
        fresh = self._meta("passages") == self._key(ids)
        enough = self.count() >= max(VECTORS_FLOOR, len(ids) // 2)
        return fresh and enough

    def count(self) -> int:
        """Return the number of stored passage vector embeddings."""
        try:
            return int(self.db.execute("SELECT COUNT(*) FROM vectors").fetchone()[0])
        except (sqlite3.Error, TypeError) as e:
            logger.warning("Failed to count vectors in store: %s", e)
            return 0

    def build(self, ids: list[int], texts: list[str]) -> None:
        """Embed all passages and persist them into the SQLite database.

        Args:
            ids: List of integer passage IDs matching the passages in the knowledge base.
            texts: List of textual passages to embed.
        """
        if not ids:
            return
        logger.info("Embedding %d passages with %s ...", len(ids), self.embedder.name)
        rows = []
        step = 64
        try:
            for i in range(0, len(texts), step):
                rows.append(self.embedder.embed(texts[i : i + step]))
            matrix = np.vstack(rows)
            with self._lock, self.db:
                self.db.execute("DELETE FROM vectors")
                self.db.executemany(
                    "INSERT INTO vectors (id, v) VALUES (?, ?)",
                    [(pid, matrix[r].astype(np.float32).tobytes()) for r, pid in enumerate(ids)],
                )
                self.db.execute(
                    "INSERT INTO meta (k, v) VALUES ('passages', ?) "
                    "ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                    (self._key(ids),),
                )
            self._matrix = matrix
            self._ids = list(ids)
            logger.info("Vector store successfully built: %d passages, dim %d", len(ids), matrix.shape[1])
        except Exception as e:
            logger.error("Failed to build vector store: %s", e, exc_info=True)
            raise

    def matrix(self) -> tuple[list[int], np.ndarray] | None:
        """Load and cache the IDs and the (N, dim) embedding matrix from SQLite."""
        if self._matrix is not None:
            return self._ids, self._matrix
        try:
            with self._lock:
                rows = self.db.execute("SELECT id, v FROM vectors ORDER BY id").fetchall()
            if not rows:
                return None
            self._ids = [int(r[0]) for r in rows]
            self._matrix = np.vstack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
            return self._ids, self._matrix
        except Exception as e:
            logger.error("Failed to load embedding matrix from SQLite: %s", e, exc_info=True)
            return None

    def top(self, query: str, k: int) -> list[tuple[int, float]]:
        """Calculate the top-k nearest passages by cosine similarity.

        Args:
            query: The search query string.
            k: Maximum number of nearest neighbors to return.

        Returns:
            list[tuple[int, float]]: List of (passage_id, cosine_similarity) tuples.
        """
        got = self.matrix()
        if not got:
            return []
        ids, m = got
        try:
            q = self.embedder.embed([query])[0]
            sims = m @ q
            top_indices = np.argsort(-sims)[:k]
            return [(ids[i], float(sims[i])) for i in top_indices]
        except Exception as e:
            logger.warning("Vector similarity calculation failed for query %r: %s", query[:60], e)
            return []


_store: VectorStore | None | bool = False  # False: uninitialised; None: vectors off/unavailable


def get_store(env: dict[str, str] | None = None) -> VectorStore | None:
    """Retrieve the singleton VectorStore instance, initializing it lazily if needed.

    Args:
        env: Optional dictionary containing environment variables.

    Returns:
        VectorStore | None: The active vector store, or None if vectors are disabled/unavailable.
    """
    global _store
    if _store is not False:
        return _store  # type: ignore[return-value]
    embedder = make_embedder(env)
    if embedder is None or not embedder.ok():
        _store = None
        return None
    passages = get_bm25().passages
    if not passages:
        _store = None
        return None
    try:
        store = VectorStore(os.path.join(_data_dir(), "vectors.sqlite"), embedder)
        ids = [p.id for p in passages]
        texts = [f"{' '.join(p.path)} {p.text}" for p in passages]
        if not store.ready(ids):
            store.build(ids, texts)
        _store = store
    except Exception as e:
        logger.warning("Vector store unavailable (%s); falling back to pure BM25 retrieval", e)
        _store = None
    return _store  # type: ignore[return-value]


def reset_store() -> None:
    """Reset the singleton vector store instance to allow re-initialization (e.g. in tests)."""
    global _store
    _store = False


def _bm25_cosines(query: str, store: VectorStore, top_k: int) -> dict[int, float]:
    """Compute the cosine similarity of BM25 matches for margin-based admission rules."""
    got = store.matrix()
    if not got:
        return {}
    ids, m = got
    row = {pid: r for r, pid in enumerate(ids)}
    try:
        q = store.embedder.embed([query])[0]
        return {
            h["passage"].id: float(m[row[h["passage"].id]] @ q)
            for h in get_bm25().search(query, top_k=top_k)
            if h["passage"].id in row
        }
    except Exception as e:
        logger.warning("Failed computing BM25 vector cosines: %s", e)
        return {}


def hybrid_search(query: str, top_k: int = 8) -> list[dict]:
    """Execute hybrid retrieval combining BM25 lexical search with dense vector embeddings via RRF.

    Reciprocal Rank Fusion (RRF) scores each document candidate by combining lexical ranking
    and semantic vector similarity without letting dense embeddings eclipse precision lexical hits.

    Args:
        query: User search query string.
        top_k: Number of highest-ranking candidate documents to return.

    Returns:
        list[dict]: List of matched passages with ranking metadata, BM25 score, and cosine vscore.
    """
    bm25_hits = get_bm25().search(query, top_k=top_k)
    try:
        store = get_store()
    except Exception as e:
        logger.warning("Failed to obtain vector store (%s); falling back to pure BM25", e)
        store = None

    if store is None:
        return [{**h, "vscore": 0.0, "via": "bm25"} for h in bm25_hits]

    by_id: dict[int, dict] = {}
    for rank, h in enumerate(bm25_hits):
        by_id[h["passage"].id] = {
            **h,
            "rrf": 1.0 / (RRF_K + rank + 1),
            "vscore": 0.0,
            "via": "bm25",
        }

    try:
        vec = store.top(query, top_k)
        vrank = {pid: 1.0 / (RRF_K + r + 1) for r, (pid, _) in enumerate(vec)}
        floors = _bm25_cosines(query, store, top_k)
        best_floor = max(floors.values(), default=0.0)
        passages = {p.id: p for p in get_bm25().passages}

        for pid, cos in vec:
            if pid in by_id:
                by_id[pid]["rrf"] += vrank[pid]
                by_id[pid]["vscore"] = cos
                by_id[pid]["via"] = "both"
                continue
            # A candidate missed by lexical search: admitted only under the cosine margin rule
            if bm25_hits and cos < best_floor + COS_MARGIN:
                continue
            p = passages.get(pid)
            if p is None:
                continue
            p_tokens = set(tokenize(f"{' '.join(p.path)} {p.text}"))
            q_tokens = set(tokenize(query))
            by_id[pid] = {
                "passage": p,
                "score": 0.0,
                "cover": len(q_tokens & p_tokens) / max(1, len(q_tokens)),
                "rrf": vrank[pid],
                "vscore": cos,
                "via": "vector",
            }
    except Exception as e:
        logger.warning("Vector search fusion failed (%s); returning lexical hits only", e)

    out = sorted(by_id.values(), key=lambda h: h["rrf"], reverse=True)
    return out[:top_k]
