"""
Which web pages the copilot may build an answer on.

Every page a search returns is graded by its host:

  authoritative  standards bodies, public agencies, universities, peer-reviewed publishers and
                 the manufacturers whose parts the twin uses
  reference      curated reference works and official software documentation (an encyclopaedia,
                 a language's own docs, a project's documentation site)
  community      everything else: company blogs, tutorials, Q&A sites, video platforms - shown,
                 marked "unvetted", never the only support for a claim in "strict" mode
  blocked        forums, social media, anonymous boards and homework-answer sites: never read,
                 never cited, never shown. User-generated content is not evidence, and some of it
                 is harmful to be seen quoting.

Two levels, chosen per question (the composer's "Sources" setting):

  vetted   (default) blocked pages are dropped; community pages stay, marked unvetted
  strict   only authoritative and reference pages are kept

The policy is applied in three places: the search prompts tell the model what not to use, the
DuckDuckGo queries exclude the blocked hosts, and `clean()` removes whatever slipped through from
the sources and from the answer's links (a search engine's model does not always obey).

  STF_SOURCES_BLOCK   extra hosts to block, comma-separated
  STF_SOURCES_TRUST   extra hosts to treat as authoritative, comma-separated
"""

from __future__ import annotations

import os
import re
import urllib.parse

LEVELS = ("vetted", "strict")
GRADES = ("authoritative", "reference", "community", "blocked")

AUTHORITATIVE = (
    # standards, agencies, research
    "iso.org",
    "iec.ch",
    "cenelec.eu",
    "etsi.org",
    "din.de",
    "dke.de",
    "vde.com",
    "vdi.de",
    "ieee.org",
    "nist.gov",
    "osha.gov",
    "hse.gov.uk",
    "europa.eu",
    "dguv.de",
    "baua.de",
    "isa.org",
    "plcopen.org",
    "opcfoundation.org",
    "industrialdigitaltwin.org",
    "plattform-i40.de",
    "fraunhofer.de",
    "dlr.de",
    "modelica.org",
    "fmi-standard.org",
    "w3.org",
    "ietf.org",
    "doi.org",
    "arxiv.org",
    "sciencedirect.com",
    "springer.com",
    "link.springer.com",
    "wiley.com",
    "nature.com",
    "science.org",
    "mdpi.com",
    "acm.org",
    "tandfonline.com",
    "sagepub.com",
    "iop.org",
    "frontiersin.org",
    "plos.org",
    "ncbi.nlm.nih.gov",
    "openalex.org",
    "semanticscholar.org",
    "nasa.gov",
    "cern.ch",
    # manufacturers and their documentation
    "fischertechnik.de",
    "beckhoff.com",
    "siemens.com",
    "festo.com",
    "sick.com",
    "pilz.com",
    "keyence.com",
    "keyence.de",
    "ifm.com",
    "rockwellautomation.com",
    "omron.com",
    "se.com",
    "abb.com",
    "boschrexroth.com",
    "codesys.com",
    "phoenixcontact.com",
    "wago.com",
    "smc.eu",
    "igus.com",
    "skf.com",
    "schaeffler.com",
    "raspberrypi.com",
    "kunbus.com",
    "revolutionpi.com",
    "meanwell.com",
    "nvidia.com",
    "mathworks.com",
    "ti.com",
    "analog.com",
    "st.com",
    "infineon.com",
    "maxongroup.com",
    "faulhaber.com",
    "danfoss.com",
    "sew-eurodrive.com",
    "murrelektronik.com",
    "turck.com",
    "balluff.com",
    "pepperl-fuchs.com",
    "eaton.com",
)
REFERENCE = (
    "wikipedia.org",
    "britannica.com",
    "python.org",
    "mozilla.org",
    "readthedocs.io",
    "docs.rs",
    "rapier.rs",
    "dimforge.com",
    "mujoco.org",
    "projectchrono.org",
    "drake.mit.edu",
    "threejs.org",
    "khronos.org",
    "docs.github.com",
    "learn.microsoft.com",
    "cloud.google.com",
    "ai.google.dev",
    "kernel.org",
)
BLOCKED = (
    # forums, social media, anonymous boards
    "reddit.com",
    "redd.it",
    "quora.com",
    "x.com",
    "twitter.com",
    "facebook.com",
    "fb.com",
    "instagram.com",
    "threads.net",
    "tiktok.com",
    "snapchat.com",
    "pinterest.com",
    "tumblr.com",
    "linkedin.com",
    "vk.com",
    "weibo.com",
    "4chan.org",
    "4channel.org",
    "8kun.top",
    "gab.com",
    "truthsocial.com",
    "parler.com",
    "gettr.com",
    "kiwifarms.net",
    "kiwifarms.st",
    "9gag.com",
    "telegram.org",
    "t.me",
    "discord.com",
    "discord.gg",
    "bitchute.com",
    "rumble.com",
    "odysee.com",
    "minds.com",
    "mastodon.social",
    "bsky.app",
    "lemmy.world",
    # homework-answer and content-farm sites
    "answers.com",
    "answers.yahoo.com",
    "brainly.com",
    "chegg.com",
    "coursehero.com",
    "studocu.com",
    "ehow.com",
    "wikihow.com",
)
# the hosts DuckDuckGo is asked to leave out: the ones a search returns most often (its query
# length is limited, so not the whole list - clean() catches the rest)
EXCLUDE_IN_QUERY = (
    "reddit.com",
    "quora.com",
    "x.com",
    "twitter.com",
    "facebook.com",
    "tiktok.com",
    "pinterest.com",
    "linkedin.com",
)
# public-sector and academic hosts are authoritative by their suffix: .gov, .edu, .ac.uk,
# .gov.in, .edu.au, .int
_PUBLIC = re.compile(
    r"(^|\.)(gov|edu|mil|int)(\.[a-z]{2})?$|(^|\.)ac\.[a-z]{2}$|(^|\.)uni-[\w-]+\.de$"
)

# the instruction every search prompt carries
PROMPT_RULE = (
    "- Never use or cite forums, social media, Q&A or homework sites, or anonymous boards (for "
    "example Reddit, Quora, X/Twitter, Facebook, TikTok, 4chan): they are not evidence. Prefer, "
    "in order: standards and public agencies, peer-reviewed papers, manufacturers' documentation, "
    "curated references."
)
STRICT_RULE = (
    "- Use ONLY standards bodies, public agencies, universities, peer-reviewed publishers, "
    "manufacturers' documentation and curated references. If they do not answer it, say so."
)


def _env_hosts(name: str) -> tuple[str, ...]:
    return tuple(
        h.strip().lower().removeprefix("www.")
        for h in os.environ.get(name, "").split(",")
        if h.strip()
    )


def host(url: str) -> str:
    """A URL's normalized host (lowercase, no 'www.')."""
    return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")


def _match(h: str, domains: tuple[str, ...]) -> bool:
    return any(h == d or h.endswith("." + d) for d in domains)


def grade(url: str) -> str:
    """The host's grade: authoritative, reference, community or blocked."""
    h = host(url)
    if not h:
        return "blocked"
    if _match(h, BLOCKED + _env_hosts("STF_SOURCES_BLOCK")):
        return "blocked"
    if _match(h, AUTHORITATIVE + _env_hosts("STF_SOURCES_TRUST")) or _PUBLIC.search(h):
        return "authoritative"
    if _match(h, REFERENCE):
        return "reference"
    return "community"


def allowed(url: str, level: str = "vetted") -> bool:
    """Whether a URL passes the source policy at the given strictness level."""
    g = grade(url)
    if g == "blocked":
        return False
    return level != "strict" or g in ("authoritative", "reference")


def rules(level: str = "vetted") -> str:
    """The lines a search prompt carries for this level."""
    return PROMPT_RULE + ("\n" + STRICT_RULE if level == "strict" else "")


def query_exclusions() -> str:
    """The '-site:...' clauses that keep low-grade hosts out of search queries."""
    return " ".join(f"-site:{h}" for h in EXCLUDE_IN_QUERY)


RANK = {"authoritative": 0, "reference": 1, "community": 2, "blocked": 3}


def rank_key(row: dict) -> tuple:
    """Cited pages first, then by grade."""
    return (not row.get("cited"), RANK.get(row.get("grade") or grade(row["url"]), 3))


_LINK = re.compile(r"\[([^\]]{1,200})\]\((https?://[^)\s]+)\)")


def strip_links(text: str, level: str = "vetted") -> tuple[str, set[str]]:
    """The text with every Markdown link to a page this level does not allow removed (its label
    and the link both: a link's label is a page title, not part of the sentence), and their URLs."""
    gone: set[str] = set()

    def drop(m: re.Match) -> str:
        """A markdown-link filter: drop the link (keep the text) when the host is not allowed."""
        if allowed(m.group(2), level):
            return m.group(0)
        gone.add(m.group(2))
        return ""

    out = _LINK.sub(drop, text or "")
    return re.sub(r"[ \t]{2,}", " ", out), gone


def clean(found, level: str = "vetted"):
    """The search's findings with the pages this level does not allow removed - from its sources
    and its answer's links - each remaining source graded. Returns (found, removed), `found`
    changed in place; `removed` counts distinct pages."""
    kept, removed = [], set()
    for s in found.sources:
        g = grade(s["url"])
        if not allowed(s["url"], level):
            removed.add(s["url"])
            continue
        kept.append({**s, "grade": g, "trusted": g in ("authoritative", "reference")})
    found.text, gone = strip_links(found.text, level)
    found.sources = sorted(kept, key=rank_key)
    return found, len(removed | gone)
