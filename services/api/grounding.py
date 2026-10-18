"""
The copilot's data access: the twin's exports (web/public), read once and shown with feature
names instead of design-step numbers (names.py), and BM25 search over the documents' passages
(web/public/copilot/kb.json, built from docs/ by `make copilot`). The tools are in tools.py.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from typing import Any

from .logging_config import get_logger
from .names import clean_deep

logger = get_logger(__name__)


def _public_dir() -> str:
    """Resolve the directory holding the twin's public assets and documentation.

    Returns:
        str: Absolute path to the directory containing public exports and documents.
    """
    if os.environ.get("STF_PUBLIC_DIR"):
        return os.environ["STF_PUBLIC_DIR"]
    src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "web", "public"))
    dist = os.environ.get("STF_WEB_DIST")
    if os.path.isdir(src) or not dist:
        return src
    return dist


PUBLIC_DIR = _public_dir()

STOP_WORDS = set(
    "a an the of to in on at for and or is are was were be been it its this that what which "
    "who how why when where do does did can could should would will i we you my our your "
    "there their than then with from by as into about any much many".split()
)


def tokenize(s: str) -> list[str]:
    """Tokenize a string into normalized, stemmed search tokens with stop words removed.

    Args:
        s: Raw input text.

    Returns:
        list[str]: Filtered and stemmed tokens.
    """
    clean = re.sub(r"[^a-z0-9äöüß ]+", " ", s.lower())
    words = clean.split()
    tokens = []
    for w in words:
        if len(w) > 1 and w not in STOP_WORDS:
            # Rule-based suffix stemming for common English variants
            w = re.sub(r"ies$", "y", w)
            w = re.sub(r"(?<=[a-z]{3})(s|ed|ing)$", "", w)
            tokens.append(w)
    return tokens


@dataclass
class Passage:
    """A single document passage indexed for search retrieval.

    Attributes:
        id: Unique identifier for the passage.
        doc: Document title or section identifier.
        path: Hierarchy of section headers leading to the passage.
        text: Passage body text.
        file: Repository-relative source file path.
        line: Starting line number in the source file.
        anchor: Heading anchor for deep linking in documentation.
    """

    id: int
    doc: str
    path: list[str]
    text: str
    file: str = ""
    line: int = 0
    anchor: str = ""


class BM25:
    """Okapi BM25 ranked retrieval model over document passages.

    Attributes:
        passages: List of Passage records indexed.
        k1: BM25 term frequency saturation parameter.
        b: BM25 document length normalization parameter.
    """

    def __init__(self, passages: list[Passage], k1: float = 1.4, b: float = 0.75) -> None:
        """Initialize the BM25 index with a collection of passages.

        Args:
            passages: List of passages to index.
            k1: Term frequency saturation tuning parameter (default 1.4).
            b: Document length normalization tuning parameter (default 0.75).
        """
        self.passages = passages
        self.k1 = k1
        self.b = b
        self.df: dict[str, int] = {}
        self.doc_lens: list[int] = []
        self.doc_tfs: list[dict[str, int]] = []

        for p in passages:
            path_str = " ".join(str(x) for x in (p.path or []) if x)
            tokens = tokenize(f"{path_str} {path_str} {p.text}")
            tf: dict[str, int] = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            for t in tf:
                self.df[t] = self.df.get(t, 0) + 1
            self.doc_tfs.append(tf)
            self.doc_lens.append(len(tokens))

        self.avg_dl = sum(self.doc_lens) / max(1, len(self.doc_lens))

    def search(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        """Search the indexed passages for the given query.

        Args:
            query: User search query string.
            top_k: Maximum number of top-ranking results to return.

        Returns:
            list[dict[str, Any]]: Ranked results containing passage, score, and token cover.
        """
        qt = list(set(tokenize(query)))
        if not qt:
            return []
        n_docs = len(self.passages)
        scored: list[dict[str, Any]] = []

        for i, p in enumerate(self.passages):
            score = 0.0
            tf = self.doc_tfs[i]
            dl = self.doc_lens[i]
            matches = 0
            for t in qt:
                f = tf.get(t, 0)
                if not f:
                    continue
                matches += 1
                n = self.df.get(t, 0)
                idf = math.log(1 + (n_docs - n + 0.5) / (n + 0.5))
                denom = f + self.k1 * (1 - self.b + self.b * dl / self.avg_dl)
                score += idf * (f * (self.k1 + 1)) / max(1e-6, denom)
            if score > 0:
                scored.append(
                    {
                        "passage": p,
                        "score": score,
                        "cover": matches / max(1, len(qt)),
                    }
                )

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]


# Global cache for loaded static JSON files and the singleton BM25 index
_cache: dict[str, Any] = {}
_bm25_index: BM25 | None = None


def load_json(rel_path: str) -> Any:
    """Load and parse a JSON file relative to the public assets directory.

    Caches successfully loaded results in memory to avoid redundant disk I/O.

    Args:
        rel_path: Path to the JSON file relative to PUBLIC_DIR.

    Returns:
        Any: Parsed JSON data structure, or None if the file is missing or unparseable.
    """
    if rel_path in _cache:
        return _cache[rel_path]
    full = os.path.join(PUBLIC_DIR, rel_path)
    if not os.path.exists(full):
        logger.debug("Static asset not found: %s", full)
        return None
    try:
        with open(full, encoding="utf-8") as f:
            data = clean_deep(json.load(f))
            _cache[rel_path] = data
            return data
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to load JSON asset '%s': %s", full, e)
        return None


def get_bm25() -> BM25:
    """Retrieve or initialize the singleton BM25 search index for copilot documents.

    Returns:
        BM25: The initialized BM25 search engine instance.
    """
    global _bm25_index
    if _bm25_index is not None:
        return _bm25_index
    kb = load_json("copilot/kb.json") or {}
    raw_passages = kb.get("passages", [])
    passages = [
        Passage(
            id=p.get("id", i),
            doc=p.get("doc", ""),
            path=[str(x) for x in p.get("path", []) if x],
            text=p.get("text", ""),
            file=p.get("file", ""),
            line=p.get("line", 0),
            anchor=p.get("anchor", ""),
        )
        for i, p in enumerate(raw_passages)
    ]
    _bm25_index = BM25(passages)
    logger.info("Initialized BM25 index with %d passages", len(passages))
    return _bm25_index
