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

from .names import clean_deep


def _public_dir() -> str:
    """Where the twin's exports are: STF_PUBLIC_DIR if set; web/public in a checkout; else the
    built web app the server serves (STF_WEB_DIST) - the Docker image ships only that, and the
    build copies web/public into it."""
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
    clean = re.sub(r"[^a-z0-9äöüß ]+", " ", s.lower())
    words = clean.split()
    tokens = []
    for w in words:
        if len(w) > 1 and w not in STOP_WORDS:
            # simple stemming for common suffixes
            w = re.sub(r"ies$", "y", w)
            w = re.sub(r"(?<=[a-z]{3})(s|ed|ing)$", "", w)
            tokens.append(w)
    return tokens


@dataclass
class Passage:
    id: int
    doc: str
    path: list[str]
    text: str
    file: str = ""  # repo-relative, e.g. docs/plc/03-units.md
    line: int = 0  # where the passage starts in it
    anchor: str = ""  # its heading's anchor


class BM25:
    def __init__(self, passages: list[Passage], k1: float = 1.4, b: float = 0.75) -> None:
        self.passages = passages
        self.k1 = k1
        self.b = b
        self.df: dict[str, int] = {}
        self.doc_lens: list[int] = []
        self.doc_tfs: list[dict[str, int]] = []

        for p in passages:
            tokens = tokenize(f"{' '.join(p.path)} {' '.join(p.path)} {p.text}")
            tf: dict[str, int] = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            for t in tf:
                self.df[t] = self.df.get(t, 0) + 1
            self.doc_tfs.append(tf)
            self.doc_lens.append(len(tokens))

        self.avg_dl = sum(self.doc_lens) / max(1, len(self.doc_lens))

    def search(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
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


# Global cached data
_cache: dict[str, Any] = {}
_bm25_index: BM25 | None = None


def load_json(rel_path: str) -> Any:
    if rel_path in _cache:
        return _cache[rel_path]
    full = os.path.join(PUBLIC_DIR, rel_path)
    if not os.path.exists(full):
        return None
    try:
        with open(full, encoding="utf-8") as f:
            data = clean_deep(json.load(f))
            _cache[rel_path] = data
            return data
    except Exception:
        return None


def get_bm25() -> BM25:
    global _bm25_index
    if _bm25_index is not None:
        return _bm25_index
    kb = load_json("copilot/kb.json") or {}
    passages = [
        Passage(
            id=p.get("id", i),
            doc=p.get("doc", ""),
            path=p.get("path", []),
            text=p.get("text", ""),
            file=p.get("file", ""),
            line=p.get("line", 0),
            anchor=p.get("anchor", ""),
        )
        for i, p in enumerate(kb.get("passages", []))
    ]
    _bm25_index = BM25(passages)
    return _bm25_index
