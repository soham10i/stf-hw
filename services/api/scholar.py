"""
Peer-reviewed literature for the copilot's deep research, from OpenAlex (openalex.org): an open
index of ~250 million scholarly works with their DOI, venue, year, citation count and abstract.

  works(query, n)   the most relevant journal articles, conference papers and reviews, each with
                    its abstract rebuilt from OpenAlex's inverted index
  found(query, n)   the same as websearch.Found: a "## Peer-reviewed literature" section for the
                    writer to cite, each work a source graded authoritative (its DOI link)

Without a key OpenAlex shares a small free daily budget per network (about 100 searches); a free
key from openalex.org/settings/api gives each its own. Nothing is sent but the search words.

  OPENALEX_API_KEY   optional
  OPENALEX_MAILTO    optional: a contact address OpenAlex asks polite clients to send
  STF_SCHOLAR        0 turns the literature search off (the tests do)
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

from . import netguard as NG
from .logging_config import get_logger

logger = get_logger(__name__)

URL = "https://api.openalex.org/works"
TIMEOUT_S = 12
ABSTRACT_CHARS = 1200
KINDS = "article|review|proceedings-article|book-chapter|preprint"
SELECT = (
    "id,doi,title,publication_year,cited_by_count,type,primary_location,"
    "abstract_inverted_index,authorships"
)


def _abstract(inv: dict | None) -> str:
    """OpenAlex keeps an abstract as {word: [positions]}: put the words back in order."""
    if not inv:
        return ""
    at: dict[int, str] = {}
    for word, places in inv.items():
        for p in places:
            at[p] = word
    return " ".join(at[i] for i in sorted(at))[:ABSTRACT_CHARS]


def works(query: str, n: int = 5, opener=None) -> list[dict]:
    """The `n` most relevant scholarly works for `query`, with an abstract; [] on any failure."""
    if os.environ.get("STF_SCHOLAR") == "0" and opener is None:
        return []
    params = {
        "search": query[:200],
        "filter": f"type:{KINDS},has_abstract:true",
        "per_page": str(max(1, min(n * 2, 20))),
        "select": SELECT,
    }
    if os.environ.get("OPENALEX_API_KEY"):
        params["api_key"] = os.environ["OPENALEX_API_KEY"]
    if os.environ.get("OPENALEX_MAILTO"):
        params["mailto"] = os.environ["OPENALEX_MAILTO"]
    url = f"{URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "stf-digital-twin/1.0"})
    try:
        with (opener or NG.opener).open(req, timeout=TIMEOUT_S) as r:
            data = json.loads(r.read())
    except Exception as e:  # noqa: BLE001 - the literature is extra evidence, never required
        logger.warning("OpenAlex search failed for %r: %s", query[:60], e)
        return []
    out = []
    for w in data.get("results") or []:
        link = w.get("doi") or w.get("id")
        title = (w.get("title") or "").strip()
        if not link or not title:
            continue
        src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
        names = [
            (a.get("author") or {}).get("display_name", "") for a in (w.get("authorships") or [])
        ]
        out.append(
            {
                "url": link,
                "title": title,
                "year": w.get("publication_year"),
                "venue": src,
                "cited_by": w.get("cited_by_count") or 0,
                "authors": ", ".join(x for x in names[:3] if x)
                + (" et al." if len(names) > 3 else ""),
                "abstract": _abstract(w.get("abstract_inverted_index")),
            }
        )
    # relevance first (OpenAlex's order), but a work nobody has cited after three years drops back
    out.sort(key=lambda w: (w["cited_by"] == 0 and (w["year"] or 0) < 2023,))
    return out[:n]


def found(query: str, n: int = 5, opener=None):
    """The works as a websearch.Found, or None when there are none."""
    from . import websearch as W

    ws = works(query, n, opener)
    if not ws:
        return None
    lines = []
    for w in ws:
        head = f"[{w['title']}]({w['url']})"
        meta = ", ".join(
            x
            for x in (w["authors"], w["venue"], str(w["year"] or ""), f"cited {w['cited_by']}×")
            if x
        )
        lines.append(f"- {head} - {meta}\n  {w['abstract']}")
    text = (
        "## Peer-reviewed literature (OpenAlex)\n\nAbstracts of the most relevant works; cite one "
        "only for what its abstract says.\n\n" + "\n".join(lines)
    )
    return W.Found(
        text=text,
        sources=[
            {
                "url": w["url"],
                "title": w["title"],
                "cited": False,
                "trusted": True,
                "grade": "authoritative",
            }
            for w in ws
        ],
        model="openalex",
        pages=" ".join(w["abstract"] for w in ws),
        steps=[f"searched the peer-reviewed literature (OpenAlex): {len(ws)} works for “{query}”"],
        via="openalex",
    )
