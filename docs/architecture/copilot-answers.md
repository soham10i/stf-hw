# Copilot answers: profile, depth, sources and cost

Each question carries three settings from the composer (the "Answer settings" popover, kept in the
browser):

| Setting | Values | What it changes |
|---|---|---|
| Who is asking | operator, engineer, researcher | the audience line the writer is given; the defaults for the two below; the example questions |
| Depth | auto, brief, standard, thorough | answer length, sub-searches, pages read, reasoning effort, the literature search (`services/api/depth.py`) |
| Web sources | vetted, strict | which pages an answer may use (`services/api/source_policy.py`) |

The profiles set these defaults:
- **Operator:** brief depth, vetted sources.
- **Engineer:** auto depth, vetted sources.
- **Researcher:** thorough depth, strict sources.

## Depth

| | brief | standard | thorough |
|---|---|---|---|
| Answer tokens (OpenAI-style / Gemini) | 1500 / 2048 | 3000 / 4096 | 6000 / 8192 |
| Deep-research sub-searches | 1 | 3 | 5 |
| Pages read per DuckDuckGo search | 2 | 3 | 4 |
| Peer-reviewed works (OpenAlex) | 0 | 0 | 5 |
| Length asked for | ≤120 words | 150–450 words | 700–1500-word report, evidence rated |

**Auto** picks the depth from the route and the question's style:
- a status or greeting question is brief;
- a deep research or a derivation is thorough;
- everything else is standard.

The figures are ceilings. Gemini's token budget (`token_budget.py`) and each provider's rate limits
still apply. A Groq request over its tokens-per-minute limit (HTTP 413) is retried once with half
the answer length.

## Sources

Every page is graded by its host:

| Grade | Examples | vetted | strict |
|---|---|---|---|
| authoritative | iso.org, iec.ch, nist.gov, any .gov/.edu/.ac.xx, doi.org, arxiv.org, publishers, part makers | used | used |
| reference | wikipedia.org, readthedocs.io, python.org, rapier.rs | used | used |
| community | blogs, tutorials, vendor marketing elsewhere | used, marked "unvetted" | dropped |
| blocked | reddit, quora, x/twitter, facebook, tiktok, 4chan, telegram, homework sites | **never** | **never** |

The policy is enforced in three places:
1. **The search prompts** (Gemini, Groq, DuckDuckGo) tell the model not to use forums or social media.
2. **DuckDuckGo queries** exclude the most common blocked hosts (`-site:`), and its results are
   filtered before any page is read.
3. **`SP.clean()` and `SP.strip_links()`** remove anything that slipped through, from the sources
   and from the answer's own links. The answer says how many pages were left out.

`STF_SOURCES_BLOCK` and `STF_SOURCES_TRUST` extend the lists.

## Literature

A thorough answer also searches OpenAlex (`services/api/scholar.py`):
- journal articles, reviews and proceedings that have an abstract;
- each with its DOI, venue, year and citation count.

The abstracts join the web findings, and they stand in for them when every web search fails.

Without a key OpenAlex shares a small free daily budget per network (about 100 searches); a free
key (`OPENALEX_API_KEY`) gives the server its own.

## Cost

Every model call adds its tokens to the question's meter (`token_budget.meter`, a context variable
that follows `asyncio.to_thread` and the deep research's threads). The reply carries:

```json
"usage": {"tokens": 89012, "calls": 9, "by": {"groq": 89012}, "depth": "thorough",
          "audience": "researcher", "sources": "strict", "removed": 2}
```

Each answer shows its tokens; the context panel shows the conversation's total.

The settings panel lists each provider's plan from `/chat/status` → `billing`. These are labels the
operator sets in `.env` (`GEMINI_BILLING`, `GROQ_BILLING`, …); the provider's own console is the
authority.

**Measured 2026-10-22.** A thorough deep research ("physics engines for industrial digital twins")
took 41 s and 89k tokens, all on Groq's free tier; 2 pages were left out by the policy. Groq's
browser search is the costly part: about 15–18k tokens per sub-search.
