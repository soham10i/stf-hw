"""
How much an answer may spend: its depth, chosen per question.

  brief      a direct answer in a few sentences: one search, two pages read, a short reply
  standard   a complete answer: up to three sub-searches, three pages read
  thorough   a researched report: up to five sub-searches, four pages read each, peer-reviewed
             literature searched too, a long write-up that compares sources and states what is
             uncertain

"auto" picks one from the route and the question's style (respond.py): a greeting or a status
question is brief, a deep research is thorough, the rest standard. The operator can choose
another in the composer.

The numbers are ceilings, not targets: the token budget (token_budget.py) and the providers'
own rate limits still bound every call, and a Groq request over its per-minute limit is retried
shorter (chat.py).
"""

from __future__ import annotations

from dataclasses import dataclass

LEVELS = ("brief", "standard", "thorough")
AUDIENCES = ("operator", "engineer", "researcher")


@dataclass(frozen=True)
class Depth:
    """Answer-depth profile: token ceilings per provider and the style instruction."""

    name: str
    answer_tokens: int  # an OpenAI-style max_tokens for the answer (reasoning counts against it)
    gemini_tokens: int  # Gemini's maxOutputTokens (its thinking counts against it)
    effort: str  # gpt-oss reasoning effort
    subs: int  # sub-searches of a deep research
    pages: int  # pages read per search (DuckDuckGo) for the answer and the number check
    page_chars: int  # of each page, how much reaches the model
    results: int  # DuckDuckGo result links kept per search
    search_tokens: int  # one Groq browser search's max_tokens
    scholar: int  # peer-reviewed works looked up (OpenAlex); 0 = none
    length: str  # the length instruction the writer is given


PROFILES: dict[str, Depth] = {
    "brief": Depth(
        name="brief", answer_tokens=1500, gemini_tokens=2048, effort="low", subs=1,
        pages=2, page_chars=4000, results=4, search_tokens=1200, scholar=0,
        length="LENGTH (brief): answer in at most 120 words - the direct answer first, one "
        "supporting line, no headings.",
    ),
    "standard": Depth(
        name="standard", answer_tokens=3000, gemini_tokens=4096, effort="low", subs=3,
        pages=3, page_chars=6000, results=5, search_tokens=2000, scholar=0,
        length="LENGTH (standard): a complete answer of about 150-450 words; headings only "
        "when there are several parts.",
    ),
    "thorough": Depth(
        name="thorough", answer_tokens=6000, gemini_tokens=8192, effort="medium", subs=5,
        pages=4, page_chars=9000, results=8, search_tokens=2500, scholar=5,
        length=(
            "LENGTH (thorough): a researched report of about 700-1500 words in ### sections: "
            "the answer in two lines first; then the evidence, each claim linked to its source; "
            "where sources disagree and why; the limits of what is known; what it means for this "
            "twin; and a closing line that rates the evidence (standards / peer-reviewed / "
            "manufacturer / other). Do not pad: stop when the evidence runs out."
        ),
    ),
}

AUDIENCE = {
    "operator": "AUDIENCE: a line operator - plain words, what to do and what to check, units "
    "spelled out, no derivations.",
    "engineer": "AUDIENCE: an automation engineer - precise terms, units, equations where they "
    "help, the standard or datasheet each value comes from.",
    "researcher": "AUDIENCE: a researcher - the evidence and its quality first, methods and "
    "assumptions stated, peer-reviewed and standards sources preferred, open questions named.",
}


def pick(depth: str | None, mode: str, style: str) -> Depth:
    """The depth for this question: the operator's choice, or one set by the route and style."""
    if depth in PROFILES:
        return PROFILES[depth]  # type: ignore[index]
    if mode == "deep" or style == "derive":
        return PROFILES["thorough"]
    if style in ("greeting", "quick", "status") or mode == "chat":
        return PROFILES["brief"]
    return PROFILES["standard"]


def instruction(d: Depth, audience: str | None) -> str:
    """The system-prompt fragment setting answer length and audience."""
    return "\n".join(x for x in (d.length, AUDIENCE.get(audience or "")) if x)
