"""Query rewriting for hybrid retrieval (Phase B3 of the copilot roadmap).

Three deterministic rewrites, no model calls, applied before BM25/vector search:

- ``spell_fix`` — SymSpell-style correction of query tokens against the corpus
  vocabulary. A typo'd term ("ovne") otherwise matches nothing lexically and only
  survives if the margin rule happens to admit it; fixing it up front recovers the
  exact hit. Correction only fires for tokens absent from the vocabulary with a
  verified Damerau-Levenshtein distance of at most 2 - anything else is left alone.
- ``expand`` — vocabulary expansion from the dashboard page the question was asked
  on (the chat request carries ``page``). Asking "why is it yellow?" on the vision
  page means colour/inspection vocabulary; the same words on the energy page mean
  something else. Terms are appended, never substituted.
- ``vector_query`` — what the vector side embeds. When BM25 is empty the raw query
  is often too terse for dense retrieval (the HyDE situation); embedding the expanded
  query instead stands in for a generated hypothetical answer without an LLM call
  in the retrieval hot path. Revisit with a real HyDE under a cheap local model.
"""

from __future__ import annotations

import logging
import re

from .grounding import STOP_WORDS, get_bm25, tokenize

logger = logging.getLogger(__name__)

MAX_FIX_DIST = 2
MIN_TOKEN_LEN = 4

# dashboard page id -> extra vocabulary for that page (page ids: tools.py Ctx.page,
# the docs/assistant guides). Keep small: terms every question on that page shares.
PAGE_TERMS: dict[str, tuple[str, ...]] = {
    "dashboard-overview": ("dashboard", "overview", "factory", "line", "cell"),
    "dashboard-quality": ("quality", "inspection", "vision", "cookie", "reject"),
    "dashboard-energy": ("energy", "power", "grid", "consumption", "kwh"),
    "dashboard-carbon": ("carbon", "emissions", "co2", "per cookie"),
    "dashboard-alarms": ("alarm", "fault", "stop", "safety"),
    "dashboard-security": ("security", "ot", "network", "access", "patch"),
    "panel-telemetry": ("telemetry", "sensor", "temperature", "signal"),
    "machine-sorting-line": ("sorting", "line", "conveyor", "colour"),
    "machine-gripper-robot": ("gripper", "vgr", "vacuum", "rack", "mold"),
}

# (word -> freq) built lazily from the kb; the delete-1 index maps a mangled form to
# the vocabulary words that could produce it. Rebuilt when the passage count changes.
_vocab: dict[str, int] | None = None
_delete_index: dict[str, set[str]] | None = None
_vocab_size: int = -1


def _rebuild() -> None:
    """Rebuild the vocabulary and the delete-1 index from the current kb passages."""
    global _vocab, _delete_index, _vocab_size
    freq: dict[str, int] = {}
    for p in get_bm25().passages:
        for t in tokenize(f"{' '.join(p.path)} {p.text}"):
            freq[t] = freq.get(t, 0) + 1
    index: dict[str, set[str]] = {}
    for w in freq:
        if len(w) < MIN_TOKEN_LEN:
            continue
        for d in _deletes(w):
            index.setdefault(d, set()).add(w)
    _vocab, _delete_index, _vocab_size = freq, index, len(get_bm25().passages)
    logger.info("rewrite vocab: %d tokens, %d delete-keys", len(freq), len(index))


def _ensure() -> None:
    if _vocab is None or _vocab_size != len(get_bm25().passages):
        _rebuild()


def _deletes(word: str) -> set[str]:
    """All strings one deletion away from ``word`` (SymSpell's index trick)."""
    return {word[:i] + word[i + 1 :] for i in range(len(word))}


def _damlev(a: str, b: str, maxd: int) -> int:
    """Bounded Damerau-Levenshtein distance; returns > maxd early when hopeless."""
    if abs(len(a) - len(b)) > maxd:
        return maxd + 1
    prev = list(range(len(b) + 1))
    prev2: list[int] = []
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        row_min = cur[0]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + cost)  # transposition
            row_min = min(row_min, cur[j])
        if row_min > maxd:
            return maxd + 1
        prev2, prev = prev, cur
    return prev[len(b)]


def _stem(word: str) -> str:
    """The query token's dictionary form, under the same rules tokenize applies."""
    w = re.sub(r"ies$", "y", word)
    return re.sub(r"(?<=[a-z]{3})(s|ed|ing)$", "", w)


def _fix_token(token: str) -> str | None:
    """Best correction for one lowercase token, or None to leave it unchanged.

    Guards against overcorrection (validation found these live):
    - stop words ("does") are not in the corpus vocab, so they look like typos;
      never touch them, nor any token whose stemmed form the vocab already has
      (inflections are the stemmer's job at search time, not the fixer's).
    - tokens with digits ("24v") are identifiers, not words.
    - short words only admit distance-1 fixes: at distance 2 a 4-letter word has
      too many plausible neighbours ("what"->"heat").
    """
    assert _vocab is not None and _delete_index is not None
    if (
        token in _vocab
        or token in STOP_WORDS
        or len(token) < MIN_TOKEN_LEN
        or any(c.isdigit() for c in token)
        or _stem(token) in _vocab
    ):
        return None
    limit = 1 if len(token) <= 5 else MAX_FIX_DIST
    # a near-miss of a function word was almost certainly meant to be that word:
    # "dose" is a real noun but as a query typo it stands for "does", not "done"
    for s in STOP_WORDS:
        if abs(len(s) - len(token)) <= limit and len(s) >= 2 and _damlev(token, s, limit) <= limit:
            return s
    candidates: set[str] = set(_delete_index.get(token, ()))  # insertion typos
    for d in _deletes(token):
        candidates.update(_delete_index.get(d, ()))
    best: tuple[int, int, str] | None = None  # (distance, -freq, word)
    for c in candidates:
        dist = _damlev(token, c, MAX_FIX_DIST)
        if dist <= limit and (best is None or (dist, -_vocab[c]) < (best[0], best[1])):
            best = (dist, -_vocab[c], c)
    return best[2] if best else None


def spell_fix(query: str) -> str:
    """Correct typo'd tokens against the corpus vocabulary; unchanged when nothing fits."""
    _ensure()
    assert _vocab is not None
    out: list[str] = []
    fixed = 0
    for raw in query.split():
        # match the tokenizer's view: strip punctuation edges, keep the casing
        stripped = raw.strip(".,;:!?()[]{}\"'").lower()
        if stripped and stripped not in _vocab:
            corr = _fix_token(stripped)
            if corr:
                prefix = raw[: len(raw) - len(raw.lstrip(".,;:!?()[]{}\"'"))]
                suffix = raw[len(raw.rstrip(".,;:!?()[]{}\"'")) :]
                core = raw[len(prefix) : len(raw) - len(suffix) if suffix else len(raw)]
                out.append(prefix + (corr if core.islower() else corr.capitalize()) + suffix)
                fixed += 1
                continue
        out.append(raw)
    if fixed:
        logger.info("spell_fix: %d token(s) corrected in %r", fixed, query)
    return " ".join(out)


def expand(query: str, page: str | None) -> str:
    """Append the page's vocabulary to the query (dedup, keep order, never substitute)."""
    if not page:
        return query
    have = set(tokenize(query))
    extra = [t for t in PAGE_TERMS.get(page, ()) if t not in have]
    return query + (" " + " ".join(extra) if extra else "")


def vector_query(query: str, page: str | None, bm25_empty: bool) -> str:
    """What the vector side embeds: the raw query, or the page-expanded form when BM25
    found nothing (the HyDE-lite fallback - see the module docstring)."""
    return expand(query, page) if bm25_empty else query


def reset() -> None:
    """Drop the cached vocabulary (tests that swap the bm25 index)."""
    global _vocab, _delete_index, _vocab_size
    _vocab, _delete_index, _vocab_size = None, None, -1
